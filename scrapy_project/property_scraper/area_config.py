from dataclasses import dataclass, field


@dataclass
class SearchArea:
    city: str = "krakow"
    voivodeship: str = "malopolskie"
    districts: list[str] = field(default_factory=list)  # empty = all
    price_min: int | None = None
    price_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    rooms_min: int | None = None
    rooms_max: int | None = None
    max_pages: int = 20


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


def build_otodom_url(area: SearchArea, page: int = 1) -> str:
    base = f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{area.voivodeship}/{area.city}"
    params = [f"page={page}", "limit=36"]
    if area.price_min:
        params.append(f"priceMin={area.price_min}")
    if area.price_max:
        params.append(f"priceMax={area.price_max}")
    if area.area_min:
        params.append(f"areaMin={area.area_min}")
    if area.area_max:
        params.append(f"areaMax={area.area_max}")
    return f"{base}?{'&'.join(params)}"


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
