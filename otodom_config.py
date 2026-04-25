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


def _safe_float(value: str | None, field_name: str) -> float | int | None:
    """Safely convert string to float with validation."""
    if not value:
        return None
    try:
        if "." not in value:
            return int(value)
        return float(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid float value for {field_name}: {value!r}") from e


class OtodomSpiderConfig(BaseModel):
    """Pydantic-compatible configuration for OtodomSpider."""
    
    city: str = Field(default="mielec", description="City name in Polish lowercase")
    voivodeship: str = Field(default="podkarpackie", description="Voivodeship (województwo)")
    powiat: str = Field(default="mielecki", description="County (powiat)")
    gmina: str = Field(default="gmina-miejska--mielec", description="Municipality (gmina)")
    property_type: str = Field(default="mieszkanie", description="Property type: 'mieszkanie' (apartment) or 'dom' (house)")
    districts: str | list[str] = Field(default="", description="District names as comma-separated string or list")
    price_min: Optional[str] = Field(default=None, description="Minimum price in PLN as string")
    price_max: Optional[str] = Field(default=None, description="Maximum price in PLN as string")
    area_min: Optional[str] = Field(default=None, description="Minimum area in m2 as string")
    area_max: Optional[str] = Field(default=None, description="Maximum area in m2 as string")
    terrain_area_min: Optional[str] = Field(default=None, description="Minimum terrain area as string")
    terrain_area_max: Optional[str] = Field(default=None, description="Maximum terrain area as string")
    price_per_meter_min: Optional[str] = Field(default=None, description="Minimum price per meter in PLN as string")
    price_per_meter_max: Optional[str] = Field(default=None, description="Maximum price per meter in PLN as string")
    build_year_min: Optional[str] = Field(default=None, description="Minimum build year as string")
    build_year_max: Optional[str] = Field(default=None, description="Maximum build year as string")
    rooms_number: str | list[str] = Field(default_factory=list, description="Room categories as comma-separated string or list")
    building_material: str | list[str] = Field(default_factory=list, description="Building material categories as comma-separated string or list")
    extras: str | list[str] = Field(default_factory=list, description="Extra categories as comma-separated string or list")
    max_pages: Optional[str] = Field(default=None, description="Maximum number of search pages to scrape as string")
    phase1_only: str = Field(default="0", description="'1' to stop after slug collection, '0' to continue to detail scraping")
    use_db_slug_queue: Optional[str] = Field(default=None, description="'1' to enable DB-backed slug handoff, '0' to keep file-based handoff")
    slug: Optional[str] = Field(default=None, description="Single slug to scrape (bypasses search)")
    
    @field_validator(
        'price_min',
        'price_max',
        'area_min',
        'area_max',
        'terrain_area_min',
        'terrain_area_max',
        'price_per_meter_min',
        'price_per_meter_max',
        'build_year_min',
        'build_year_max',
        'max_pages',
        mode='before',
    )
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

    @property
    def use_db_slug_queue_bool(self) -> bool:
        """Convert use_db_slug_queue string to boolean."""
        if self.use_db_slug_queue is None:
            return False
        return self.use_db_slug_queue.strip() not in ("0", "false", "")
    
    def to_search_area(self):
        """Convert config to SearchArea object.
        
        Raises:
            ValueError: If scalar fields contain invalid numeric values
        """
        from property_scraper.area_config import (
            OTODOM_BUILDING_MATERIAL_VALUES,
            OTODOM_EXTRAS_VALUES,
            OTODOM_ROOMS_NUMBER_VALUES,
            SearchArea,
            normalize_otodom_categorical_values,
            split_csv_values,
        )
        
        return SearchArea(
            city=self.city,
            voivodeship=self.voivodeship,
            powiat=self.powiat,
            gmina=self.gmina,
            property_type=self.property_type,
            districts=split_csv_values(self.districts),
            price_min=_safe_int(self.price_min, "price_min"),
            price_max=_safe_int(self.price_max, "price_max"),
            area_min=_safe_float(self.area_min, "area_min"),
            area_max=_safe_float(self.area_max, "area_max"),
            terrain_area_min=_safe_float(self.terrain_area_min, "terrain_area_min"),
            terrain_area_max=_safe_float(self.terrain_area_max, "terrain_area_max"),
            price_per_meter_min=_safe_int(self.price_per_meter_min, "price_per_meter_min"),
            price_per_meter_max=_safe_int(self.price_per_meter_max, "price_per_meter_max"),
            build_year_min=_safe_int(self.build_year_min, "build_year_min"),
            build_year_max=_safe_int(self.build_year_max, "build_year_max"),
            rooms_number=normalize_otodom_categorical_values(
                self.rooms_number,
                allowed_values=OTODOM_ROOMS_NUMBER_VALUES,
                field_name="rooms_number",
            ),
            building_material=normalize_otodom_categorical_values(
                self.building_material,
                allowed_values=OTODOM_BUILDING_MATERIAL_VALUES,
                field_name="building_material",
            ),
            extras=normalize_otodom_categorical_values(
                self.extras,
                allowed_values=OTODOM_EXTRAS_VALUES,
                field_name="extras",
            ),
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