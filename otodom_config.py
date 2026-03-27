#!/usr/bin/env python3
"""Pydantic configuration model for OtodomSpider."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator


def _safe_int(value: str | None, field_name: str) -> int | None:
    """
    Safely convert string to int with validation.
    
    Args:
        value: String value to convert
        field_name: Field name for error messages
        
    Returns:
        Integer value or None
        
    Raises:
        ValueError: If value is not a valid integer
    """
    if not value:
        return None
    try:
        return int(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid integer value for {field_name}: {value!r}") from e


class OtodomSpiderConfig(BaseModel):
    """Pydantic-compatible configuration for OtodomSpider."""
    
    city: str = Field(default="mielec", description="City name in Polish lowercase")
    voivodeship: str = Field(default="podkarpackie", description="Voivodeship (województwo)")
    powiat: str = Field(default="mielecki", description="County (powiat)")
    gmina: str = Field(default="gmina-miejska--mielec", description="Municipality (gmina)")
    property_type: str = Field(default="mieszkanie", description="Property type: 'mieszkanie' (apartment) or 'dom' (house)")
    districts: str = Field(default="", description="Comma-separated district names")
    price_min: Optional[str] = Field(default=None, description="Minimum price in PLN as string")
    price_max: Optional[str] = Field(default=None, description="Maximum price in PLN as string")
    max_pages: Optional[str] = Field(default=None, description="Maximum number of search pages to scrape as string")
    phase1_only: str = Field(default="0", description="'1' to stop after slug collection, '0' to continue to detail scraping")
    slug: Optional[str] = Field(default=None, description="Single slug to scrape (bypasses search)")
    
    @field_validator('price_min', 'price_max', 'max_pages', mode='before')
    @classmethod
    def empty_string_to_none(cls, v):
        """Convert empty strings to None for optional fields."""
        if v == "":
            return None
        return v
    
    @property
    def phase1_only_bool(self) -> bool:
        """Convert phase1_only string to boolean."""
        return self.phase1_only.strip() not in ("0", "false", "")
    
    def to_search_area(self):
        """Convert config to SearchArea object.
        
        Raises:
            ValueError: If price fields or max_pages contain invalid integer values
        """
        from property_scraper.area_config import SearchArea
        
        return SearchArea(
            city=self.city,
            voivodeship=self.voivodeship,
            powiat=self.powiat,
            gmina=self.gmina,
            property_type=self.property_type,
            districts=[d.strip() for d in self.districts.split(",") if d.strip()],
            price_min=_safe_int(self.price_min, "price_min"),
            price_max=_safe_int(self.price_max, "price_max"),
            max_pages=_safe_int(self.max_pages, "max_pages"),
        )


def load_config_from_file(filepath: str) -> OtodomSpiderConfig:
    """Load configuration from a JSON or YAML file."""
    import json
    from pathlib import Path
    
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {filepath}")
    
    if path.suffix.lower() == '.json':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    elif path.suffix.lower() in ('.yaml', '.yml'):
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    else:
        raise ValueError(f"Unsupported config file format: {path.suffix}. Use .json or .yaml")
    
    return OtodomSpiderConfig(**data)


def create_default_config(filepath: str) -> None:
    """Create a default configuration file."""
    import json
    from pathlib import Path
    
    config = OtodomSpiderConfig()
    path = Path(filepath)
    
    # Ensure directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)
    
    print(f"Created default config at: {path}")