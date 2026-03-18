---
applyTo: "**/dedup/**,**/pipelines.py,**/deduplicator*"
---

# Stage 2 — Deduplication Engine

## Objective

Identify when the same physical flat appears across multiple portals or as duplicate listings within a portal. Group duplicates under a single canonical record while retaining all source URLs. The cross-listing count and persistence across portals is itself a scoring signal.

## Dependencies

```
hashlib (stdlib)
pydantic>=2.9
```

## Deduplication Strategy

### Hash Key Construction

Create a deterministic hash from the fields that identify the *physical property*, deliberately **excluding** URL and portal name:

```python
import hashlib
from typing import Optional

def compute_listing_hash(
    district: Optional[str],
    area_m2: Optional[float],
    floor: Optional[int],
    price_pln: Optional[int],
    rooms: Optional[int] = None,
    street: Optional[str] = None,
) -> str:
    """
    Compute a SHA-256 hash that identifies a unique physical listing.
    
    Excluded: source_url, source_portal, external_id (these differ per portal).
    Included: fields that identify the same flat regardless of where it's listed.
    """
    # Normalize area to 1 decimal place to handle rounding differences
    area_normalized = f"{area_m2:.1f}" if area_m2 else "none"
    
    # Normalize district to lowercase, stripped
    district_normalized = district.lower().strip() if district else "none"
    
    # Street is optional but helps disambiguate flats in same building
    street_normalized = street.lower().strip() if street else "none"
    
    components = [
        district_normalized,
        area_normalized,
        str(floor) if floor is not None else "none",
        str(price_pln) if price_pln is not None else "none",
        str(rooms) if rooms is not None else "none",
        street_normalized,
    ]
    
    raw = "|".join(components)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]  # 16 chars is sufficient
```

### Why This Hash Composition

| Field      | Rationale                                                                 |
| ---------- | ------------------------------------------------------------------------- |
| `district` | Same flat is always in the same dzielnica                                 |
| `area_m2`  | The most stable identifier — rarely differs across portals by more than rounding |
| `floor`    | Distinguishes flats in the same building                                  |
| `price_pln`| Same seller typically posts same price across portals simultaneously       |
| `rooms`    | Additional disambiguator                                                  |
| `street`   | Optional but very useful when available                                   |

### Known Limitations

- **Price changes**: If a seller updates the price on one portal but not another, the hash diverges. Mitigation: use a secondary "fuzzy match" for listings that match on district + area + floor + rooms but differ in price by ≤5%.
- **Area rounding**: otodom may report 52.3 m² while gratka says 52 m². Mitigation: round to 1 decimal.
- **Missing fields**: If floor is `None` on one portal, the hash includes "none". This may cause false negatives. Mitigation: fallback to fuzzy matching when key fields are missing.

## Fuzzy Matching (Secondary Pass)

After hash-based dedup, run a fuzzy match on remaining listings:

```python
def is_fuzzy_duplicate(a: RawListing, b: RawListing) -> bool:
    """
    Check if two listings are likely the same flat despite hash mismatch.
    Used as a secondary pass after exact hash dedup.
    """
    # Must be same district
    if a.district != b.district:
        return False
    
    # Area must be within 2 m² (portals round differently)
    if a.area_m2 and b.area_m2:
        if abs(a.area_m2 - b.area_m2) > 2.0:
            return False
    else:
        return False  # Can't compare without area
    
    # Floor must match (if both present)
    if a.floor is not None and b.floor is not None:
        if a.floor != b.floor:
            return False
    
    # Rooms must match (if both present)
    if a.rooms is not None and b.rooms is not None:
        if a.rooms != b.rooms:
            return False
    
    # Price within 5% tolerance
    if a.price_pln and b.price_pln:
        price_diff_pct = abs(a.price_pln - b.price_pln) / max(a.price_pln, b.price_pln)
        if price_diff_pct > 0.05:
            return False
    
    return True
```

## Data Model

### Canonical Listing Record

When duplicates are found, one listing becomes the "canonical" record. Preference order for canonical source:
1. Listing with the most complete data (most non-None fields)
2. If tied, prefer otodom (generally most structured data)
3. If tied, prefer the oldest scraped listing

```python
from pydantic import BaseModel
from datetime import datetime

class SourceReference(BaseModel):
    """A single portal's version of a listing."""
    source_portal: str
    source_url: str
    external_id: str
    date_first_seen: datetime
    date_last_seen: datetime
    price_at_source: int | None = None  # track per-source price independently

class CanonicalListing(BaseModel):
    """The deduplicated, canonical representation of a property."""
    listing_hash: str                         # computed hash (primary key)
    sources: list[SourceReference]            # all portal references
    cross_listing_count: int                  # len(sources) — scoring signal
    
    # Best-available data merged from all sources
    # (populated from the most complete source)
    title: str
    description: str
    district: str | None
    street: str | None
    # ... all fields from RawListing ...
    
    # Derived metadata
    first_seen: datetime
    last_seen: datetime
    is_active: bool = True
    gone_check_count: int = 0                 # how many times confirmed absent
```

## Deduplication Workflow

```
1. Scraper yields RawListing objects
2. For each RawListing:
   a. Compute listing_hash
   b. Query DB: does this hash already exist?
      YES → Add new SourceReference to existing CanonicalListing
            Update cross_listing_count
            Merge any new data (fill None fields from new source)
            Update last_seen timestamp
      NO  → Run fuzzy_match against recent listings in same district
            FUZZY MATCH FOUND → Same as YES path above
            NO MATCH → Create new CanonicalListing
3. Log dedup stats: new listings, duplicates found, fuzzy matches
```

## Implementation: `dedup/deduplicator.py`

```python
class Deduplicator:
    def __init__(self, db_client):
        self.db = db_client
    
    def process(self, raw_listing: RawListing) -> tuple[str, bool]:
        """
        Process a raw listing through dedup.
        Returns: (listing_hash, is_new)
        """
        listing_hash = compute_listing_hash(
            district=raw_listing.district,
            area_m2=raw_listing.area_m2,
            floor=raw_listing.floor,
            price_pln=raw_listing.price_pln,
            rooms=raw_listing.rooms,
            street=raw_listing.street,
        )
        
        existing = self.db.get_listing_by_hash(listing_hash)
        
        if existing:
            self._merge_duplicate(existing, raw_listing)
            return listing_hash, False
        
        # Try fuzzy match
        candidates = self.db.get_recent_listings_in_district(
            district=raw_listing.district,
            days_back=30,
        )
        for candidate in candidates:
            if is_fuzzy_duplicate(raw_listing, candidate):
                self._merge_duplicate(candidate, raw_listing)
                return candidate.listing_hash, False
        
        # Genuinely new listing
        self._create_new(listing_hash, raw_listing)
        return listing_hash, True
    
    def _merge_duplicate(self, existing, new_listing):
        """Add source reference and fill missing fields."""
        source_ref = SourceReference(
            source_portal=new_listing.source_portal,
            source_url=str(new_listing.source_url),
            external_id=new_listing.external_id,
            date_first_seen=new_listing.date_scraped,
            date_last_seen=new_listing.date_scraped,
            price_at_source=new_listing.price_pln,
        )
        self.db.add_source_reference(existing.listing_hash, source_ref)
        self.db.fill_missing_fields(existing.listing_hash, new_listing)
    
    def _create_new(self, listing_hash, raw_listing):
        """Create a new canonical listing."""
        self.db.insert_canonical_listing(listing_hash, raw_listing)
```

## Cross-Listing as a Signal

The `cross_listing_count` is a scoring input:

- **Listed on 1 portal**: Neutral
- **Listed on 2-3 portals**: Normal for agency listings
- **Listed on 3+ portals AND time-on-market > 3 weeks**: Potential red flag — flat may be overpriced or have issues

This signal is consumed by the scoring engine in Stage 5.

## Performance Note

The fuzzy match step calls `get_recent_listings_in_district()` which returns all active listings in a district from the last 30 days. As the DB grows, this becomes O(n) per incoming listing — and O(n²) over a full scrape run. Mitigate by:

1. Adding a composite index: `CREATE INDEX idx_listings_fuzzy ON listings(district, area_m2, rooms) WHERE is_active = TRUE;`
2. Filtering in SQL rather than Python — push area±2 and rooms constraints into the query
3. Skipping fuzzy match entirely when all hash fields are non-null (the hash is reliable when data is complete)

## Testing Dedup

1. Create two `RawListing` objects for the same flat from different portals with identical physical attributes → should produce same hash
2. Create two listings with area 52.3 vs 52.0 → hash differs, but fuzzy match should catch it
3. Create two genuinely different listings in same building → should NOT match
4. Verify that merging fills None fields from the new source
5. Verify cross_listing_count increments correctly
