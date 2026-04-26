from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode


@dataclass
class SearchArea:
    city: str = "mielec"
    voivodeship: str = "podkarpackie"
    powiat: str = "mielecki"
    gmina: str = "gmina-miejska--mielec"
    property_type: str = "mieszkanie"  # mieszkanie | dom | dzialka | etc.
    districts: list[str] = field(default_factory=list)  # empty = all
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    area_min: Optional[float] = None
    area_max: Optional[float] = None
    terrain_area_min: Optional[float] = None
    terrain_area_max: Optional[float] = None
    price_per_meter_min: Optional[int] = None
    price_per_meter_max: Optional[int] = None
    build_year_min: Optional[int] = None
    build_year_max: Optional[int] = None
    rooms_number: list[str] = field(default_factory=list)
    building_material: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)
    max_pages: Optional[int] = None  # None means no limit, scrape all pages


OTODOM_DISTRICT_SLUGS = {
    "stare-miasto": "stare-miasto",
    "krowodrza": "krowodrza",
    "debniki": "debniki",
    "podgorze": "podgorze",
    "grzegorzki": "grzegorzki",
    "bronowice": "bronowice",
    "pradnik-bialy": "pradnik-bialy",
    "pradnik-czerwony": "pradnik-czerwony",
    "czyzyny": "czyzyny",
    "nowa-huta": "nowa-huta",
    "zwierzyniec": "zwierzyniec",
}


OTODOM_ROOMS_NUMBER_VALUES = ["ONE", "TWO", "THREE", "FIVE", "FOUR"]
OTODOM_BUILDING_MATERIAL_VALUES = ["BRICK"]
OTODOM_EXTRAS_VALUES = ["IS_BUNGALOV", "HAS_PHOTOS"]


def split_csv_values(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Parse a comma-separated string or list into a trimmed list of values."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = value
    return [str(part).strip() for part in parts if str(part).strip()]


def normalize_otodom_categorical_values(
    value: str | list[str] | tuple[str, ...] | None,
    *,
    allowed_values: list[str],
    field_name: str,
) -> list[str]:
    """Normalize categorical Otodom filters and validate against allowed values."""
    allowed = set(allowed_values)
    normalized: list[str] = []
    for raw in split_csv_values(value):
        token = raw.upper()
        if token not in allowed:
            raise ValueError(
                f"Unsupported value for {field_name}: {raw!r}. "
                f"Allowed values: {', '.join(allowed_values)}"
            )
        if token not in normalized:
            normalized.append(token)
    return normalized


def _otodom_list_param(values: list[str]) -> str:
    """Encode Otodom categorical filters in bracket-list format."""
    return f"[{','.join(values)}]"


def build_otodom_url(area: SearchArea, page: int = 1) -> str:
    base = (
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/{area.property_type}"
        f"/{area.voivodeship}/{area.powiat}/{area.gmina}/{area.city}"
    )
    params: list[tuple[str, str | int | float]] = [
        ("limit", "36"),
        ("ownerTypeSingleSelect", "ALL"),
    ]
    if page > 1:
        params.append(("page", page))
    if area.price_min is not None:
        params.append(("priceMin", area.price_min))
    if area.price_max is not None:
        params.append(("priceMax", area.price_max))
    if area.area_min is not None:
        params.append(("areaMin", area.area_min))
    if area.area_max is not None:
        params.append(("areaMax", area.area_max))
    if area.terrain_area_min is not None:
        params.append(("terrainAreaMin", area.terrain_area_min))
    if area.terrain_area_max is not None:
        params.append(("terrainAreaMax", area.terrain_area_max))
    if area.price_per_meter_min is not None:
        params.append(("pricePerMeterMin", area.price_per_meter_min))
    if area.price_per_meter_max is not None:
        params.append(("pricePerMeterMax", area.price_per_meter_max))
    if area.build_year_min is not None:
        params.append(("buildYearMin", area.build_year_min))
    if area.build_year_max is not None:
        params.append(("buildYearMax", area.build_year_max))
    if area.rooms_number:
        params.append(("roomsNumber", _otodom_list_param(area.rooms_number)))
    if area.building_material:
        params.append(("buildingMaterial", _otodom_list_param(area.building_material)))
    if area.extras:
        params.append(("extras", _otodom_list_param(area.extras)))
    params.extend([("by", "DEFAULT"), ("direction", "DESC")])
    return f"{base}?{urlencode(params)}"


def build_gratka_url(area: SearchArea, page: int = 1) -> str:
    # NOTE: Verify query param format against current Gratka search URLs before use.
    base = f"https://gratka.pl/nieruchomosci/mieszkania/{area.city}/sprzedaz"
    params = [f"page={page}"]
    if area.price_min:
        params.append(f"cena-calkowita:min={area.price_min}")
    if area.price_max:
        params.append(f"cena-calkowita:max={area.price_max}")
    return f"{base}?{'&'.join(params)}"


def build_morizon_url(area: SearchArea, page: int = 1) -> str:
    # NOTE: Verify query param format against current Morizon search URLs before use.
    base = f"https://www.morizon.pl/mieszkania/{area.city}"
    params = [f"page={page}"]
    if area.price_min:
        params.append(f"ps[price_from]={area.price_min}")
    if area.price_max:
        params.append(f"ps[price_to]={area.price_max}")
    return f"{base}/?{'&'.join(params)}"
