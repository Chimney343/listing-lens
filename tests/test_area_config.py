"""Tests for search area configuration and portal URL builders."""

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
    assert area.rooms_min is None
    assert area.rooms_max is None
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
        powiat="krakowski",
        gmina="gmina-miejska--krakow",
        property_type="mieszkanie",
    )

    assert (
        build_otodom_url(area)
        == "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/malopolskie/krakowski/gmina-miejska--krakow/krakow?page=1&limit=36"
    )
    assert (
        build_otodom_url(area, page=3)
        == "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/malopolskie/krakowski/gmina-miejska--krakow/krakow?page=3&limit=36"
    )


def test_build_otodom_url_with_filters():
    """Otodom URLs should append only the configured numeric filters."""
    area = SearchArea(
        city="krakow",
        voivodeship="malopolskie",
        powiat="krakowski",
        gmina="gmina-miejska--krakow",
        property_type="dom",
        price_min=450000,
        price_max=950000,
        area_min=55.5,
        area_max=120.0,
    )

    assert (
        build_otodom_url(area, page=2)
        == "https://www.otodom.pl/pl/wyniki/sprzedaz/dom/malopolskie/krakowski/gmina-miejska--krakow/krakow?page=2&limit=36&priceMin=450000&priceMax=950000&areaMin=55.5&areaMax=120.0"
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