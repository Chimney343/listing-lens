"""Tests for search area configuration and portal URL builders."""

from pathlib import Path

from otodom_config import load_config_from_file
from property_scraper.area_config import (
    SearchArea,
    build_gratka_url,
    build_morizon_url,
    build_otodom_url,
)


def test_search_area_defaults_are_stable():
    """Default search areas should expose the expected Poland-wide defaults."""
    area = SearchArea()

    assert area.city == "mielec"
    assert area.voivodeship == "podkarpackie"
    assert area.powiat == "mielecki"
    assert area.gmina == "gmina-miejska--mielec"
    assert area.property_type == "mieszkanie"
    assert area.districts == []
    assert area.price_min is None
    assert area.price_max is None
    assert area.area_min is None
    assert area.area_max is None
    assert area.terrain_area_min is None
    assert area.terrain_area_max is None
    assert area.price_per_meter_min is None
    assert area.price_per_meter_max is None
    assert area.build_year_min is None
    assert area.build_year_max is None
    assert area.rooms_number == []
    assert area.building_material == []
    assert area.extras == []
    assert area.max_pages is None


def test_search_area_districts_use_independent_lists():
    """Each SearchArea instance should get its own districts list."""
    first = SearchArea()
    second = SearchArea()

    first.districts.append("stare-miasto")

    assert first.districts == ["stare-miasto"]
    assert second.districts == []


def test_build_otodom_url_without_filters():
    """Otodom URLs should include the base path and default paging params."""
    area = SearchArea(
        city="krakow",
        voivodeship="malopolskie",
        powiat="krakow",
        gmina="krakow",
        property_type="mieszkanie",
    )

    assert (
        build_otodom_url(area)
        == "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/malopolskie/krakow/krakow/krakow?limit=36&ownerTypeSingleSelect=ALL&by=DEFAULT&direction=DESC"
    )
    assert (
        build_otodom_url(area, page=3)
        == "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/malopolskie/krakow/krakow/krakow?limit=36&ownerTypeSingleSelect=ALL&page=3&by=DEFAULT&direction=DESC"
    )


def test_build_otodom_url_matches_canonical_single_location_url():
    """Otodom canonical location URL should be generated with default fixed controls."""
    area = SearchArea(
        city="mielec",
        voivodeship="podkarpackie",
        powiat="mielecki",
        gmina="gmina-miejska--mielec",
        property_type="dom",
    )

    assert (
        build_otodom_url(area)
        == "https://www.otodom.pl/pl/wyniki/sprzedaz/dom/podkarpackie/mielecki/gmina-miejska--mielec/mielec?limit=36&ownerTypeSingleSelect=ALL&by=DEFAULT&direction=DESC"
    )


def test_build_otodom_url_with_filters():
    """Otodom URLs should append only the configured numeric filters."""
    area = SearchArea(
        city="krakow",
        voivodeship="malopolskie",
        powiat="krakow",
        gmina="krakow",
        property_type="dom",
        price_min=450000,
        price_max=950000,
        area_min=55.5,
        area_max=120.0,
    )

    assert (
        build_otodom_url(area, page=2)
        == "https://www.otodom.pl/pl/wyniki/sprzedaz/dom/malopolskie/krakow/krakow/krakow?limit=36&ownerTypeSingleSelect=ALL&page=2&priceMin=450000&priceMax=950000&areaMin=55.5&areaMax=120.0&by=DEFAULT&direction=DESC"
    )


def test_build_otodom_url_matches_full_filter_single_location_url():
    """Otodom full filter URL should encode scalar and categorical filters exactly."""
    area = SearchArea(
        city="mielec",
        voivodeship="podkarpackie",
        powiat="mielecki",
        gmina="gmina-miejska--mielec",
        property_type="dom",
        price_min=5000,
        price_max=100000,
        area_min=25,
        area_max=50,
        terrain_area_min=50,
        terrain_area_max=100,
        price_per_meter_min=5000,
        price_per_meter_max=10000,
        build_year_min=1950,
        build_year_max=2025,
        rooms_number=["ONE", "TWO", "THREE", "FIVE", "FOUR"],
        building_material=["BRICK"],
        extras=["IS_BUNGALOV", "HAS_PHOTOS"],
    )

    assert (
        build_otodom_url(area)
        == "https://www.otodom.pl/pl/wyniki/sprzedaz/dom/podkarpackie/mielecki/gmina-miejska--mielec/mielec?limit=36&ownerTypeSingleSelect=ALL&priceMin=5000&priceMax=100000&areaMin=25&areaMax=50&terrainAreaMin=50&terrainAreaMax=100&pricePerMeterMin=5000&pricePerMeterMax=10000&buildYearMin=1950&buildYearMax=2025&roomsNumber=%5BONE%2CTWO%2CTHREE%2CFIVE%2CFOUR%5D&buildingMaterial=%5BBRICK%5D&extras=%5BIS_BUNGALOV%2CHAS_PHOTOS%5D&by=DEFAULT&direction=DESC"
    )


def test_developer_otodom_config_builds_expected_current_url():
    """The local developer preset should load cleanly and build the current preset URL."""
    config_path = Path(__file__).resolve().parents[1] / "config" / "otodom.developer.yaml"

    config = load_config_from_file(str(config_path))
    assert config.slug is None

    assert (
        build_otodom_url(config.to_search_area())
        == "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/podkarpackie/mielecki/gmina-miejska--mielec/mielec?limit=36&ownerTypeSingleSelect=ALL&by=DEFAULT&direction=DESC"
    )


def test_build_gratka_url_with_and_without_filters():
    """Gratka URLs should keep the base path stable and add supported filters."""
    area = SearchArea(city="krakow")

    assert build_gratka_url(area) == "https://gratka.pl/nieruchomosci/mieszkania/krakow/sprzedaz?page=1"

    area.price_min = 300000
    area.price_max = 650000

    assert (
        build_gratka_url(area, page=4)
        == "https://gratka.pl/nieruchomosci/mieszkania/krakow/sprzedaz?page=4&cena-calkowita:min=300000&cena-calkowita:max=650000"
    )


def test_build_morizon_url_with_and_without_filters():
    """Morizon URLs should keep the base path stable and add supported filters."""
    area = SearchArea(city="krakow")

    assert build_morizon_url(area) == "https://www.morizon.pl/mieszkania/krakow/?page=1"

    area.price_min = 300000
    area.price_max = 650000

    assert (
        build_morizon_url(area, page=4)
        == "https://www.morizon.pl/mieszkania/krakow/?page=4&ps[price_from]=300000&ps[price_to]=650000"
    )