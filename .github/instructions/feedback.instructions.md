---
applyTo: "**/feedback/**,**/cli.py,**/feedback.py"
---

# Stage 6 — Feedback Loop

## Objective

Record user decisions on listings (viewed, dismissed, applied) with reasons, and use accumulated feedback to recalibrate scoring weights over time. Initial recalibration is manual pattern analysis; automated recalibration can be added later.

## Dependencies

```
pydantic>=2.9
# No additional dependencies — uses existing DB client
```

## Feedback Schema

```python
# feedback/feedback.py

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Optional

class FeedbackOutcome(str, Enum):
    VIEWED = "viewed"           # Clicked through, looked at photos/details
    DISMISSED = "dismissed"     # Decided not to pursue
    APPLIED = "applied"         # Contacted seller/agent
    VISITED = "visited"         # Physically visited the flat
    OFFER_MADE = "offer_made"   # Made an offer
    PURCHASED = "purchased"     # Deal closed

class DismissalReason(str, Enum):
    TOO_EXPENSIVE = "too_expensive"
    BAD_LOCATION = "bad_location"
    NEEDS_RENOVATION = "needs_renovation"
    TOO_SMALL = "too_small"
    BAD_LAYOUT = "bad_layout"
    NO_LIFT = "no_lift"
    BAD_FLOOR = "bad_floor"
    POOR_LISTING = "poor_listing"     # bad photos, no info
    SUSPICIOUS = "suspicious"          # something felt off
    ALREADY_GONE = "already_gone"
    OTHER = "other"

class FeedbackEntry(BaseModel):
    listing_hash: str
    outcome: FeedbackOutcome
    notes: Optional[str] = None
    dismissal_reason: Optional[DismissalReason] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

## Feedback Recording

```python
class FeedbackManager:
    def __init__(self, db_client):
        self.db = db_client
    
    def record(self, entry: FeedbackEntry):
        """Record a feedback entry against a listing."""
        with self.db._conn() as conn:
            conn.execute(
                "INSERT INTO feedback (listing_hash, outcome, notes, dismissal_reason) "
                "VALUES (%s, %s, %s, %s)",
                (entry.listing_hash, entry.outcome.value, entry.notes,
                 entry.dismissal_reason.value if entry.dismissal_reason else None),
            )
    
    def get_feedback_for_listing(self, listing_hash: str) -> list[dict]:
        with self.db._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE listing_hash = %s ORDER BY created_at DESC",
                (listing_hash,),
            ).fetchall()
            cols = [d.name for d in conn.execute("SELECT * FROM feedback WHERE FALSE").description]
            return [dict(zip(cols, r)) for r in rows]
    
    def get_all_feedback(self) -> list[dict]:
        with self.db._conn() as conn:
            rows = conn.execute(
                "SELECT f.*, l.district, l.price_pln, l.area_m2, l.rooms, "
                "l.floor, l.composite_score, l.score_json "
                "FROM feedback f JOIN listings l ON f.listing_hash = l.listing_hash"
            ).fetchall()
            cols = [d.name for d in conn.execute(
                "SELECT f.*, l.district, l.price_pln, l.area_m2, l.rooms, "
                "l.floor, l.composite_score, l.score_json "
                "FROM feedback f JOIN listings l ON f.listing_hash = l.listing_hash WHERE FALSE"
            ).description]
            return [dict(zip(cols, r)) for r in rows]
```

## Weight Recalibration (Manual Phase)

The initial approach is manual: periodically analyze feedback patterns and adjust weights.

### Analysis Queries

```python
def analyze_feedback_patterns(db) -> dict:
    """
    Analyze feedback to identify scoring calibration issues.
    Returns a report dict with insights.
    """
    all_feedback = FeedbackManager(db).get_all_feedback()
    
    # Separate by outcome
    applied = [f for f in all_feedback if f["outcome"] in ("applied", "visited", "offer_made", "purchased")]
    dismissed = [f for f in all_feedback if f["outcome"] == "dismissed"]
    
    report = {}
    
    # 1. Score distribution for applied vs. dismissed
    applied_scores = [f["listings"]["composite_score"] for f in applied if f["listings"].get("composite_score")]
    dismissed_scores = [f["listings"]["composite_score"] for f in dismissed if f["listings"].get("composite_score")]
    
    report["avg_score_applied"] = sum(applied_scores) / len(applied_scores) if applied_scores else None
    report["avg_score_dismissed"] = sum(dismissed_scores) / len(dismissed_scores) if dismissed_scores else None
    
    # 2. Most common dismissal reasons
    from collections import Counter
    reasons = Counter(f["dismissal_reason"] for f in dismissed if f["dismissal_reason"])
    report["top_dismissal_reasons"] = reasons.most_common(5)
    
    # 3. Score dimension analysis for false positives
    # (high-scored listings that were dismissed)
    false_positives = [
        f for f in dismissed 
        if f["listings"].get("composite_score") and f["listings"]["composite_score"] >= 3.5
    ]
    report["false_positive_count"] = len(false_positives)
    
    if false_positives:
        # Which dimension was the model wrong about?
        fp_reasons = Counter(f["dismissal_reason"] for f in false_positives if f["dismissal_reason"])
        report["false_positive_reasons"] = fp_reasons.most_common(5)
    
    # 4. Score dimension analysis for false negatives
    # (low-scored listings that were applied to)
    false_negatives = [
        f for f in applied
        if f["listings"].get("composite_score") and f["listings"]["composite_score"] < 3.0
    ]
    report["false_negative_count"] = len(false_negatives)
    
    # 5. District preference drift
    # Which districts do you actually apply to vs. what scores highest?
    applied_districts = Counter(f["listings"]["district"] for f in applied if f["listings"].get("district"))
    report["preferred_districts"] = applied_districts.most_common(5)
    
    # 6. Price sensitivity
    # What's the actual price range you engage with?
    applied_prices = [f["listings"]["price_pln"] for f in applied if f["listings"].get("price_pln")]
    if applied_prices:
        report["applied_price_range"] = {
            "min": min(applied_prices),
            "max": max(applied_prices),
            "median": sorted(applied_prices)[len(applied_prices) // 2],
        }
    
    return report
```

### Interpreting the Report

Run `analyze_feedback_patterns()` after ~50 feedback entries. Look for:

1. **If `avg_score_applied` and `avg_score_dismissed` are close**: The scoring model isn't differentiating well. Consider adjusting the system prompt or adding more Kraków-specific knowledge.

2. **If top dismissal reason is `too_expensive`**: Increase the financial weight or tighten the price/m² benchmarks in the system prompt.

3. **If top dismissal reason is `bad_location`**: Increase the location weight or refine the district scoring tiers.

4. **If `false_positive_count` is high**: The model is too generous. Lower dimension scores in the prompt or add stricter red flag triggers.

5. **If `preferred_districts` don't match the prompt's district rankings**: Update the location scoring section of the system prompt.

### Applying Weight Changes

```python
# After analyzing patterns, adjust weights:
from scoring.weights import ScoringWeights

# Example: user keeps dismissing for price reasons
# → increase financial weight
adjusted_weights = ScoringWeights(
    location=0.25,      # was 0.30
    physical=0.20,      # was 0.25
    financial=0.40,     # was 0.30 — increased
    listing_quality=0.15,
)

# Re-score all active listings with new weights
scorer = ListingScorer(adapter, weights=adjusted_weights)
await scorer.score_unscored_listings(db, limit=500)
```

## Automated Recalibration (Future)

When you have 100+ feedback entries, implement automated weight optimization:

```python
# Future: optimize weights using feedback as ground truth
from scipy.optimize import minimize

def objective(weights_array, feedback_data):
    """
    Minimize: misclassification rate.
    A listing is "misclassified" if:
    - It scored >= 3.5 but was dismissed
    - It scored < 3.0 but was applied to
    """
    w_loc, w_phys, w_fin, w_qual = weights_array
    
    errors = 0
    for entry in feedback_data:
        scores = entry["listings"]["score_json"]
        if not scores:
            continue
        
        composite = (
            scores["location"]["score"] * w_loc +
            scores["physical"]["score"] * w_phys +
            scores["financial"]["score"] * w_fin +
            scores["listing_quality"]["score"] * w_qual
        )
        
        is_positive = entry["outcome"] in ("applied", "visited", "offer_made")
        
        if composite >= 3.5 and not is_positive:
            errors += 1  # false positive
        elif composite < 3.0 and is_positive:
            errors += 2  # false negative (weighted higher)
    
    return errors

# Constraints: weights must sum to 1.0 and each be in [0.05, 0.60]
result = minimize(
    objective,
    x0=[0.30, 0.25, 0.30, 0.15],
    args=(feedback_data,),
    bounds=[(0.05, 0.60)] * 4,
    constraints={"type": "eq", "fun": lambda w: sum(w) - 1.0},
)
optimized_weights = ScoringWeights(
    location=result.x[0],
    physical=result.x[1],
    financial=result.x[2],
    listing_quality=result.x[3],
)
```

## CLI / Interface for Recording Feedback

For now, use a simple CLI. A web UI can be added later.

```python
# feedback/cli.py

import typer

app = typer.Typer()

@app.command()
def view_top(n: int = 10):
    """Show top N scored listings."""
    from storage.db import DatabaseClient
    db = DatabaseClient()
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT listing_hash, title, district, price_pln, area_m2, composite_score "
            "FROM listings WHERE is_active = TRUE AND composite_score IS NOT NULL "
            "ORDER BY composite_score DESC LIMIT %s",
            (n,),
        ).fetchall()
    
    for i, (lh, title, district, price, area, score) in enumerate(rows, 1):
        print(f"{i}. [{score:.1f}] {title}")
        print(f"   {district} | {price:,} PLN | {area} m²")
        print(f"   Hash: {lh}")
        print()

@app.command()
def record(
    listing_hash: str,
    outcome: str,          # viewed, dismissed, applied, visited, offer_made
    reason: str = None,    # too_expensive, bad_location, etc.
    notes: str = None,
):
    """Record feedback for a listing."""
    from storage.db import DatabaseClient
    db = DatabaseClient()
    mgr = FeedbackManager(db)
    
    entry = FeedbackEntry(
        listing_hash=listing_hash,
        outcome=FeedbackOutcome(outcome),
        dismissal_reason=DismissalReason(reason) if reason else None,
        notes=notes,
    )
    mgr.record(entry)
    print(f"Recorded: {outcome} for {listing_hash}")

@app.command()
def analyze():
    """Analyze feedback patterns and print report."""
    from storage.db import DatabaseClient
    db = DatabaseClient()
    report = analyze_feedback_patterns(db)
    
    print("=== FEEDBACK ANALYSIS ===")
    print(f"Avg score (applied): {report.get('avg_score_applied', 'N/A')}")
    print(f"Avg score (dismissed): {report.get('avg_score_dismissed', 'N/A')}")
    print(f"False positives: {report.get('false_positive_count', 0)}")
    print(f"False negatives: {report.get('false_negative_count', 0)}")
    print(f"Top dismissal reasons: {report.get('top_dismissal_reasons', [])}")
    print(f"Preferred districts: {report.get('preferred_districts', [])}")
    if report.get("applied_price_range"):
        pr = report["applied_price_range"]
        print(f"Price range (applied): {pr['min']:,} - {pr['max']:,} PLN (median: {pr['median']:,})")

if __name__ == "__main__":
    app()
```

## Feedback-Driven Prompt Evolution

Beyond weight changes, use feedback patterns to evolve the system prompt itself:

- If users consistently dismiss listings with "wielka płyta" → add explicit penalty in the physical dimension prompt
- If users prefer certain streets/neighborhoods within a district → add micro-location detail to the location prompt
- If "needs renovation" is a frequent dismissal but the LLM doesn't flag it → add more Polish renovation phrases to the red flags section

Store prompt versions with timestamps. When changing the prompt, re-score a sample of previously scored listings to measure drift.

## Testing

1. Record 5 feedback entries (mix of outcomes) → verify they appear in DB
2. Run `analyze_feedback_patterns()` → verify report structure
3. Adjust weights → re-score a listing → verify composite changes
4. Test CLI commands: `view_top`, `record`, `analyze`
5. Verify feedback entries are linked to correct listings via foreign key
