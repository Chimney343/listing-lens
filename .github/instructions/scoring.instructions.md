---
applyTo: "**/scoring/**,**/schemas.py,**/adapter.py,**/prompts.py,**/scorer.py"
---

# Stage 5 — LLM Scoring Engine

## Objective

Build a provider-agnostic LLM scoring engine that evaluates each listing across multiple dimensions and produces a structured JSON score. Uses Instructor + Pydantic for guaranteed structured output across Claude, OpenAI, and Gemini. Design now for a future vision scoring pass on photos.

## Dependencies

```
instructor>=1.7
pydantic>=2.9
openai>=1.50          # for OpenAI/compatible providers
anthropic>=0.40       # for Claude
google-generativeai   # for Gemini (optional)
```

## Scoring Schema (Pydantic)

```python
# scoring/schemas.py

from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

class ScoreValue(int, Enum):
    """1-5 scale for each dimension."""
    TERRIBLE = 1
    BELOW_AVERAGE = 2
    AVERAGE = 3
    GOOD = 4
    EXCELLENT = 5

class RedFlag(BaseModel):
    category: str           # "renovation", "pricing", "listing_quality", "location", "structural"
    description: str        # human-readable explanation
    severity: str           # "low", "medium", "high"

class DimensionScore(BaseModel):
    score: ScoreValue
    reasoning: str = Field(max_length=200)

class ListingScore(BaseModel):
    """Structured scoring output from the LLM."""
    
    # Per-dimension scores
    location: DimensionScore
    physical: DimensionScore
    financial: DimensionScore
    listing_quality: DimensionScore
    
    # Composite
    composite_score: float = Field(ge=1.0, le=5.0, description="Weighted average of dimension scores")
    
    # Summary
    summary: str = Field(max_length=500, description="2-3 sentence summary of the listing's strengths and weaknesses")
    
    # Red flags
    red_flags: list[RedFlag] = Field(default_factory=list, max_length=5)
    
    # Recommendation
    recommendation: str = Field(description="One of: 'strong_buy', 'worth_viewing', 'borderline', 'skip', 'avoid'")
```

## Scoring Weights (Configurable)

```python
# scoring/weights.py

from pydantic import BaseModel

class ScoringWeights(BaseModel):
    """Configurable weights for composite score calculation."""
    location: float = 0.30
    physical: float = 0.25
    financial: float = 0.30
    listing_quality: float = 0.15
    
    def validate_sum(self):
        total = self.location + self.physical + self.financial + self.listing_quality
        assert abs(total - 1.0) < 0.01, f"Weights must sum to 1.0, got {total}"

DEFAULT_WEIGHTS = ScoringWeights()
```

## Provider-Agnostic Adapter

```python
# scoring/adapter.py

import instructor
from pydantic import BaseModel
from typing import Type

class LLMAdapter:
    """
    Provider-agnostic adapter for LLM scoring.
    Uses Instructor for structured output across all providers.
    """
    
    def __init__(self, provider: str = "openai", model: str = "gpt-4o-mini"):
        self.provider = provider
        self.model = model
        self.client = self._create_client()
    
    def _create_client(self):
        if self.provider == "openai":
            from openai import OpenAI
            return instructor.from_openai(OpenAI())
        
        elif self.provider == "anthropic":
            from anthropic import Anthropic
            return instructor.from_anthropic(Anthropic())
        
        elif self.provider == "gemini":
            import google.generativeai as genai
            return instructor.from_gemini(
                client=genai.GenerativeModel(model_name=self.model)
            )
        
        elif self.provider == "ollama":
            # Local model via Ollama (for testing or cost savings)
            from openai import OpenAI
            return instructor.from_openai(
                OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"),
                mode=instructor.Mode.JSON,
            )
        
        else:
            raise ValueError(f"Unknown provider: {self.provider}")
    
    def score(
        self,
        system_prompt: str,
        user_content: str,
        response_model: Type[BaseModel] = ListingScore,
        max_retries: int = 3,
    ) -> BaseModel:
        """
        Send listing data to LLM and get structured score back.
        Instructor handles validation, retries, and JSON parsing.
        """
        return self.client.chat.completions.create(
            model=self.model,
            response_model=response_model,
            max_retries=max_retries,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
```

## System Prompt

```python
# scoring/prompts.py

SCORING_SYSTEM_PROMPT = """You are a property evaluation assistant for a buyer searching for an apartment in Kraków, Poland. You score listings on a 1-5 scale across four dimensions and flag red flags.

## SCORING DIMENSIONS

### 1. Location (weight: 30%)
Score the district and micro-location:
- **5 (Excellent)**: Prime districts — Stare Miasto, Kazimierz, Dębniki (near Vistula), Krowodrza (Łobzów/Salwator), Grzegórzki (near center). Quiet street, good transit, parks nearby.
- **4 (Good)**: Solid districts — Podgórze (Zabłocie/Stare Podgórze — gentrifying), Bronowice, Ruczaj (near campus/tech), Prądnik Biały/Czerwony (established residential). Reasonable commute.
- **3 (Average)**: Functional but unexciting — Bieńczyce, Mistrzejowice, Czyżyny (near airport noise), Prokocim. Decent transit but far from center.
- **2 (Below average)**: Far-flung or declining — Wzgórza Krzesławickie, Swoszowice, Bieżanów (poor transit), edge-of-city locations.
- **1 (Poor)**: Industrial zones, high-crime areas, or locations with severe noise/pollution.

Consider: commute to city center, neighborhood trajectory (gentrifying = positive signal), noise environment, proximity to green spaces and amenities.

### 2. Physical Characteristics (weight: 25%)
Score the flat's attributes:
- **Floor**: Middle floors (2nd-5th) preferred. Ground floor penalize slightly (noise, security), top floor without lift penalize heavily (5th+ walkup).
- **Orientation**: South/Southwest windows are best. North-only is worst.
- **Building**: Newer construction or well-maintained historic buildings score higher. "Wielka płyta" (prefab concrete) scores lower unless recently renovated. Pre-war kamienica can score high if renovated.
- **Layout**: Separate kitchen vs. kitchenette (aneks), through-rooms (pokoje przechodnie) are negative. Logical room proportions.
- **Extras**: Lift in buildings 4+ floors is important. Balcony/terrace is a strong positive. Storage (piwnica/komórka) is positive. Parking is positive, especially in dense districts.

### 3. Financial (weight: 30%)
Evaluate the asking price:
- Compare price/m² to typical Kraków averages by district (as of 2025):
  - Stare Miasto: 18,000-25,000 PLN/m²
  - Kazimierz: 16,000-22,000 PLN/m²
  - Krowodrza: 14,000-19,000 PLN/m²
  - Dębniki: 13,000-17,000 PLN/m²
  - Podgórze: 12,000-16,000 PLN/m²
  - Grzegórzki: 14,000-19,000 PLN/m²
  - Ruczaj: 11,000-15,000 PLN/m²
  - Bronowice: 11,000-14,000 PLN/m²
  - Prądnik: 10,000-14,000 PLN/m²
  - Nowa Huta (Bieńczyce, Mistrzejowice): 8,000-12,000 PLN/m²
  - Czyżyny: 10,000-14,000 PLN/m²
  
- **5**: Significantly below district average — potential bargain
- **4**: Slightly below average or fair price for above-average property
- **3**: At district average
- **2**: Above average without justification
- **1**: Significantly overpriced for the district and condition
  
- Factor in: price trend (dropping price = potentially motivated seller), time on market (> 4 weeks at same price = overpriced signal), primary vs. secondary market (primary typically commands 10-15% premium).

### 4. Listing Quality (weight: 15%)
Score the listing itself as a signal about the seller/property:
- **Photos**: 10+ high-quality photos showing all rooms, kitchen, bathroom, building exterior, neighborhood = 5. Few/dark/blurry photos = 1-2. Photos that hide rooms or use extreme wide-angle = red flag.
- **Description**: Detailed, honest description mentioning specifics (renovation year, appliances included, utility costs, czynsz) = 4-5. Copy-paste template with no specifics = 2. Overly salesy with no substance = 1-2.
- **Floor plan**: Presence of a floor plan is a strong positive signal (indicates professional/transparent seller).
- **Agency vs. Private**: Private sellers sometimes indicate negotiability. Agency listings are more common and neutral. Multiple agencies listing the same flat = potential red flag (owner desperate?).

## RED FLAGS TO DETECT

Always flag these in your response:
- "Do remontu" / "do odświeżenia" / "do wykończenia" — needs full or partial renovation (cost: 1,500-3,000 PLN/m²)
- Ground floor described ambiguously (parter vs. wysoki parter)
- Photos showing damage, mold, or suspiciously empty rooms
- Description mentions "udziały" (shares) — not full ownership
- Very high czynsz (> 1,000 PLN/mo for a 2-room flat) — indicates building problems or unpaid renovations
- Cross-listed on 3+ portals for 4+ weeks — flat is not moving
- "Bez księgi wieczystej" — no land register = risky
- Phrases indicating the flat is in a building scheduled for demolition or major structural work
- Unusually low price/m² without explanation (may indicate legal or structural issues)

## OUTPUT FORMAT

You MUST return a valid JSON object matching the ListingScore schema. Always provide:
- Score 1-5 for each dimension with reasoning (max 200 chars)
- A composite_score (weighted average)
- A 2-3 sentence summary
- Any red flags detected
- A recommendation: 'strong_buy', 'worth_viewing', 'borderline', 'skip', or 'avoid'

Be direct and honest. Do not inflate scores to be polite. A 3 is average and perfectly fine for most listings."""
```

## Building the User Prompt

```python
# scoring/scorer.py

from datetime import datetime

def build_user_prompt(listing: dict, price_history: list[dict]) -> str:
    """
    Build the user message containing all listing data for scoring.
    """
    # Price history summary
    price_summary = "No price changes recorded."
    if len(price_history) > 1:
        first = price_history[0]
        last = price_history[-1]
        change = last["price_pln"] - first["price_pln"]
        days = (datetime.fromisoformat(last["recorded_at"]) - 
                datetime.fromisoformat(first["recorded_at"])).days
        price_summary = (
            f"Price changed from {first['price_pln']:,} PLN to {last['price_pln']:,} PLN "
            f"over {days} days ({change:+,} PLN, {change/first['price_pln']*100:+.1f}%)."
        )
    
    # Time on market
    first_seen = listing.get("first_seen", "")
    if first_seen:
        days_on_market = (datetime.utcnow() - datetime.fromisoformat(first_seen)).days
    else:
        days_on_market = 0
    
    prompt = f"""## LISTING DATA

**Title**: {listing.get('title', 'N/A')}
**District**: {listing.get('district', 'N/A')}
**Street**: {listing.get('street', 'N/A')}

**Price**: {listing.get('price_pln', 'N/A'):,} PLN
**Price/m²**: {listing.get('price_per_m2', 'N/A')} PLN/m²
**Area**: {listing.get('area_m2', 'N/A')} m²
**Rooms**: {listing.get('rooms', 'N/A')}
**Floor**: {listing.get('floor', 'N/A')} / {listing.get('total_floors', 'N/A')}
**Year built**: {listing.get('year_built', 'N/A')}
**Building material**: {listing.get('building_material', 'N/A')}
**Market**: {listing.get('market_type', 'N/A')}

**Has lift**: {listing.get('has_lift', 'N/A')}
**Has balcony**: {listing.get('has_balcony', 'N/A')}
**Has terrace**: {listing.get('has_terrace', 'N/A')}
**Has storage**: {listing.get('has_storage', 'N/A')}
**Heating**: {listing.get('heating_type', 'N/A')}
**Parking**: {listing.get('parking', 'N/A')}

**Listing type**: {listing.get('listing_type', 'N/A')}
**Photo count**: {listing.get('photo_count', 0)}
**Has floor plan**: {listing.get('has_floor_plan', False)}
**Description length**: {listing.get('description_length', 0)} chars

**Cross-listed on**: {listing.get('cross_listing_count', 1)} portal(s)
**Days on market**: {days_on_market}
**Price history**: {price_summary}

## DESCRIPTION TEXT

{listing.get('description', 'No description available.')}
"""
    return prompt
```

## Scoring Orchestration

```python
# scoring/scorer.py (continued)

class ListingScorer:
    def __init__(
        self, 
        adapter: LLMAdapter, 
        weights: ScoringWeights = DEFAULT_WEIGHTS,
    ):
        self.adapter = adapter
        self.weights = weights
    
    def score_listing(self, db, listing_hash: str) -> ListingScore:
        """Score a single listing."""
        listing = db.get_listing_by_hash(listing_hash)
        price_history = db.get_price_history(listing_hash)
        
        user_prompt = build_user_prompt(listing, price_history)
        
        result: ListingScore = self.adapter.score(
            system_prompt=SCORING_SYSTEM_PROMPT,
            user_content=user_prompt,
            response_model=ListingScore,
        )
        
        # Recalculate composite with configurable weights
        result.composite_score = round(
            result.location.score * self.weights.location +
            result.physical.score * self.weights.physical +
            result.financial.score * self.weights.financial +
            result.listing_quality.score * self.weights.listing_quality,
            2,
        )
        
        # Persist score
        db.update_listing_score(
            listing_hash=listing_hash,
            composite_score=result.composite_score,
            score_json=result.model_dump(),
        )
        
        return result
    
    def score_unscored_listings(self, db, limit: int = 50):
        """Score all listings that haven't been scored yet."""
        unscored = db.get_unscored_listings(limit=limit)
        
        results = []
        for listing in unscored:
            try:
                score = self.score_listing(db, listing["listing_hash"])
                results.append((listing["listing_hash"], score))
            except Exception as e:
                print(f"Scoring failed for {listing['listing_hash']}: {e}")
        
        return results
```

## Vision Scoring (Future — Design Now)

The architecture supports a second scoring pass that sends photos to a vision-capable model. This is NOT implemented now but the schema is ready:

```python
class VisionScore(BaseModel):
    """Score from visual inspection of photos."""
    condition_score: ScoreValue      # visible condition of walls, floors, fixtures
    natural_light_score: ScoreValue  # brightness, window size/orientation
    layout_quality_score: ScoreValue # room proportions, flow
    renovation_level: str            # "new", "recent", "dated", "needs_work", "raw"
    photo_quality_score: ScoreValue  # are photos professional or amateur?
    visual_red_flags: list[str]      # mold, water damage, cracks, etc.
    summary: str

# Future implementation:
# 1. Retrieve presigned photo URLs from MinIO
# 2. Send photos to Claude/GPT-4o vision endpoint
# 3. Merge VisionScore into the composite score
```

## LLM Cost Estimation

| Provider         | Model            | Cost per listing (~1,500 tokens in, ~500 out) | Monthly (100 listings) |
| ---------------- | ---------------- | ----------------------------------------------- | ---------------------- |
| OpenAI           | gpt-4o-mini      | ~$0.002                                         | ~$0.20                 |
| Anthropic        | Claude Haiku 3.5 | ~$0.002                                         | ~$0.20                 |
| Anthropic        | Claude Sonnet    | ~$0.015                                         | ~$1.50                 |
| Google           | Gemini 2.0 Flash | ~$0.001                                         | ~$0.10                 |
| Local (Ollama)   | qwen2.5:7b       | Free (compute only)                             | €0                     |

**Recommendation**: Use gpt-4o-mini or Claude Haiku for batch scoring. Use Sonnet/GPT-4o for the vision scoring pass when implemented.

## Testing

1. Score a known listing manually → verify all dimensions have scores 1-5
2. Score a listing with obvious red flags ("do remontu", ground floor) → verify red_flags populated
3. Switch provider (OpenAI → Anthropic) → verify output schema is identical
4. Score same listing twice → verify deterministic-ish results (scores within ±1)
5. Verify composite_score matches weight calculation
6. Test with Ollama locally → verify it works as a free fallback
