"""Unit and integration tests for OtodomSlugSpider and OtodomDetailSpider."""
import json
from unittest.mock import Mock, patch, AsyncMock

import pytest
import scrapy
from scrapy.http import Response, Request, TextResponse
from scrapy.utils.test import get_crawler

from property_scraper.spiders.otodom import OtodomSlugSpider, OtodomDetailSpider
from property_scraper.items import RawListingItem, RawJsonItem


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def spider():
    """Slug spider instance with typical Kraków parameters.

    Most test classes exercise slug-collection logic, so the shared ``spider``
    fixture points to ``OtodomSlugSpider``.  Tests that exercise detail-parsing
    methods use the ``detail_spider`` fixture instead.
    """
    return OtodomSlugSpider(
        city="krakow",
        voivodeship="malopolskie",
        powiat="krakowski",
        gmina="gmina-miejska--krakow",
        property_type="mieszkanie",
        districts="",
        price_min=None,
        price_max=None,
        max_pages="5",
    )


@pytest.fixture
def detail_spider():
    """Detail spider instance for testing advert-page parsing."""
    return OtodomDetailSpider(city="krakow")


@pytest.fixture
def sample_search_json():
    """Return a sample search page JSON data."""
    return {
        "props": {
            "pageProps": {
                "data": {
                    "searchAds": {
                        "pagination": {
                            "totalItems": 150,
                            "totalPages": 3,
                        },
                        "items": [
                            {
                                "id": 12345,
                                "slug": "mieszkanie-krakow-centrum-12345",
                                "estate": "REGULAR",
                            },
                            {
                                "id": 67890,
                                "slug": "mieszkanie-krakow-kazimierz-67890",
                                "estate": "REGULAR",
                            },
                            {
                                "id": 99999,
                                "slug": "inwestycja-nova-99999",
                                "estate": "INVESTMENT",
                                "investmentUnitsNumber": 50,
                            },
                        ],
                    }
                }
            }
        }
    }


@pytest.fixture
def sample_detail_json():
    """Return a sample detail page JSON data."""
    return {
        "props": {
            "pageProps": {
                "ad": {
                    "id": 12345,
                    "title": "Przestronne mieszkanie w centrum",
                    "description": "Opis mieszkania...",
                    "totalPrice": {"value": 850000},
                    "pricePerSquareMeter": {"value": 12500},
                    "areaInSquareMeters": 68.0,
                    "roomsNumber": 3,
                    "target": {"ProperType": "mieszkanie"},
                    "market": "secondary",
                    "agency": True,
                    "dateCreated": "2026-01-15T10:30:00Z",
                    "location": {
                        "address": {
                            "district": {"name": "Centrum"},
                            "street": {"name": "Florianska"},
                        },
                        "coordinates": {
                            "latitude": 50.0614,
                            "longitude": 19.9372,
                        },
                    },
                    "images": [
                        {"large": "https://example.com/photo1.jpg"},
                        {"medium": "https://example.com/photo2.jpg"},
                    ],
                    "characteristics": [
                        {"key": "m", "value": "68"},
                        {"key": "rooms_num", "value": "3"},
                        {"key": "floor_no", "value": "2"},
                        {"key": "building_floors_num", "value": "5"},
                        {"key": "build_year", "value": "2010"},
                        {"key": "lift", "value": "yes"},
                        {"key": "heating", "value": "municipal"},
                        {"key": "parking", "value": "garage"},
                        {"key": "building_material", "value": "brick"},
                    ],
                    "features": ["balcony", "terrace"],
                }
            }
        }
    }


@pytest.fixture
def mock_response_with_json(sample_search_json):
    """Create a mock TextResponse with JSON data in __NEXT_DATA__."""
    html = f'<script id="__NEXT_DATA__">{json.dumps(sample_search_json)}</script>'
    return TextResponse(
        url="https://www.otodom.pl/pl/wyniki/wynajem/mieszkanie/krakow",
        body=html.encode("utf-8"),
        encoding="utf-8",
    )


# ─── Unit Tests for Static Helper Methods ──────────────────────────────────

class TestStaticHelpers:
    """Test the static helper methods of OtodomDetailSpider."""

    def test_extract_price_dict(self):
        price_dict = {"value": 500000}
        assert OtodomDetailSpider._extract_price(price_dict) == 500000

    def test_extract_price_scalar(self):
        assert OtodomDetailSpider._extract_price(750000) == 750000
        assert OtodomDetailSpider._extract_price(None) is None

    def test_safe_int_valid(self):
        assert OtodomDetailSpider._safe_int("42") == 42
        assert OtodomDetailSpider._safe_int(42) == 42
        assert OtodomDetailSpider._safe_int(None) is None

    def test_safe_int_invalid(self):
        assert OtodomDetailSpider._safe_int("not a number") is None
        assert OtodomDetailSpider._safe_int([]) is None

    def test_safe_float_valid(self):
        assert OtodomDetailSpider._safe_float("68.5") == 68.5
        assert OtodomDetailSpider._safe_float(68.5) == 68.5
        assert OtodomDetailSpider._safe_float(None) is None

    def test_safe_float_invalid(self):
        assert OtodomDetailSpider._safe_float("invalid") is None

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("2", 2),
            ("0", 0),
            ("ground_floor", 0),
            ("parter", 0),
            (None, None),
            ("invalid", None),
            ("", None),
        ],
    )
    def test_parse_floor(self, input_val, expected):
        assert OtodomDetailSpider._parse_floor(input_val) == expected


# ─── Unit Tests for Parsing Methods ────────────────────────────────────────

class TestParseSearchData:
    """Test the _parse_search_data method on OtodomSlugSpider."""

    def test_parse_search_data_success(self, spider, mock_response_with_json):
        result = spider._parse_search_data(mock_response_with_json)
        assert result is not None
        assert "pagination" in result
        assert "items" in result
        assert len(result["items"]) == 3

    def test_parse_search_data_no_script(self, spider):
        html = "<html><body>No script</body></html>"
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        result = spider._parse_search_data(response)
        assert result is None

    def test_parse_search_data_invalid_json(self, spider):
        html = '<script id="__NEXT_DATA__">{invalid json}</script>'
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        result = spider._parse_search_data(response)
        assert result is None


class TestAbsorbSearchItems:
    """Test the _absorb_search_items method on OtodomSlugSpider."""

    def test_absorb_search_items_regular(self, spider):
        spider._slugs = set()
        spider._investments = {}
        spider._total_pages = 5
        search_data = {
            "items": [
                {"slug": "listing-1", "estate": "REGULAR"},
                {"slug": "listing-2", "estate": "REGULAR"},
            ]
        }
        spider._absorb_search_items(search_data, page=1)
        assert len(spider._slugs) == 2
        assert "listing-1" in spider._slugs
        assert "listing-2" in spider._slugs
        assert len(spider._investments) == 0

    def test_absorb_search_items_investment(self, spider):
        spider._slugs = set()
        spider._investments = {}
        spider._total_pages = 5
        search_data = {
            "items": [
                {
                    "id": 999,
                    "slug": "investment-1",
                    "estate": "INVESTMENT",
                    "investmentUnitsNumber": 30,
                }
            ]
        }
        spider._absorb_search_items(search_data, page=1)
        assert len(spider._slugs) == 0  # Investment slugs not added yet
        assert len(spider._investments) == 1
        assert 999 in spider._investments
        assert spider._investments[999] == ("investment-1", 30)

    def test_absorb_search_items_mixed(self, spider):
        spider._slugs = set()
        spider._investments = {}
        spider._total_pages = 5
        search_data = {
            "items": [
                {"slug": "regular-1", "estate": "REGULAR"},
                {
                    "id": 100,
                    "slug": "investment-1",
                    "estate": "INVESTMENT",
                    "investmentUnitsNumber": 20,
                },
                {"slug": "regular-2", "estate": "REGULAR"},
            ]
        }
        spider._absorb_search_items(search_data, page=1)
        assert len(spider._slugs) == 2
        assert len(spider._investments) == 1
        assert "regular-1" in spider._slugs
        assert "regular-2" in spider._slugs
        assert spider._investments[100] == ("investment-1", 20)


# ─── Integration Tests for Spider Flow ─────────────────────────────────────

class TestSpiderInitialization:

    def test_slug_spider_defaults(self):
        spider = OtodomSlugSpider()
        assert spider.area.city == "mielec"
        assert spider.area.property_type == "mieszkanie"
        assert spider.area.max_pages is None

    def test_slug_spider_custom_params(self):
        spider = OtodomSlugSpider(
            city="warszawa",
            districts="mokotow,wola",
            price_min="500000",
            price_max="1000000",
            max_pages="10",
        )
        assert spider.area.city == "warszawa"
        assert spider.area.districts == ["mokotow", "wola"]
        assert spider.area.price_min == 500000
        assert spider.area.price_max == 1000000
        assert spider.area.max_pages == 10
        assert spider._parameters["city"] == "warszawa"
        assert spider._parameters["districts"] == "mokotow,wola"
        assert spider._parameters["price_min"] == "500000"
        assert spider._parameters["price_max"] == "1000000"
        assert spider._parameters["max_pages"] == "10"

    def test_detail_spider_single_slug(self):
        spider = OtodomDetailSpider(slug="test-slug-123")
        assert spider.single_slug == "test-slug-123"
        assert spider._slugs_list == []

    def test_detail_spider_inline_slugs(self):
        spider = OtodomDetailSpider(slugs="slug-a,slug-b,slug-c")
        assert spider._slugs_list == ["slug-a", "slug-b", "slug-c"]
        assert spider.single_slug is None

    def test_detail_spider_slug_run_file(self, tmp_path):
        """Detail spider reads slugs from a slug_runs.jsonl file."""
        import json
        slug_file = tmp_path / "slug_runs.jsonl"
        slug_file.write_text(
            json.dumps({
                "record_type": "slug_collection",
                "slugs": ["run-slug-1", "run-slug-2", "run-slug-3"],
            }) + "\n",
            encoding="utf-8",
        )
        spider = OtodomDetailSpider(slug_run_file=str(slug_file))
        assert spider._slugs_list == ["run-slug-1", "run-slug-2", "run-slug-3"]

    def test_detail_spider_slug_run_file_missing_record(self, tmp_path):
        """Detail spider raises if no slug_collection record is present."""
        import json
        slug_file = tmp_path / "slug_runs.jsonl"
        slug_file.write_text(
            json.dumps({"record_type": "completion"}) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="slug_collection"):
            OtodomDetailSpider(slug_run_file=str(slug_file))

    def test_run_timestamp_set_at_construction(self):
        for cls in (OtodomSlugSpider, OtodomDetailSpider):
            spider = cls()
            assert spider.run_timestamp is not None
            assert len(spider.run_timestamp) == 15  # yyyyMMdd_HHmmss
            assert spider._start_time is None
            assert spider._end_time is None

    def test_slug_spider_parameters_stored(self):
        spider = OtodomSlugSpider(
            city="krakow",
            voivodeship="malopolskie",
            powiat="krakowski",
            gmina="gmina-miejska--krakow",
            property_type="dom",
            districts="kazimierz,podgorze",
            price_min="300000",
            price_max="800000",
            max_pages="5",
        )
        expected = {
            "city": "krakow",
            "voivodeship": "malopolskie",
            "powiat": "krakowski",
            "gmina": "gmina-miejska--krakow",
            "property_type": "dom",
            "districts": "kazimierz,podgorze",
            "price_min": "300000",
            "price_max": "800000",
            "max_pages": "5",
        }
        for key, value in expected.items():
            assert spider._parameters[key] == value

    def test_null_string_handling(self):
        spider = OtodomSlugSpider(
            city="test", voivodeship="test", powiat="test", gmina="test",
            property_type="mieszkanie",
            price_min="null", price_max="NULL", max_pages="Null",
        )
        assert spider.area.price_min is None
        assert spider.area.price_max is None
        assert spider.area.max_pages is None

        spider2 = OtodomSlugSpider(
            city="test", voivodeship="test", powiat="test", gmina="test",
            property_type="mieszkanie", price_min="", price_max="", max_pages="",
        )
        assert spider2.area.price_min is None
        assert spider2.area.price_max is None
        assert spider2.area.max_pages is None

        spider3 = OtodomSlugSpider(
            city="test", voivodeship="test", powiat="test", gmina="test",
            property_type="mieszkanie",
            price_min="500000", price_max="1000000", max_pages="10",
        )
        assert spider3.area.price_min == 500000
        assert spider3.area.price_max == 1000000
        assert spider3.area.max_pages == 10


class TestStartMethod:

    @pytest.mark.asyncio
    async def test_detail_spider_single_slug_start(self, detail_spider):
        """Detail spider in single-slug mode yields exactly one request."""
        detail_spider.single_slug = "test-offer-123"
        requests = []
        async for request in detail_spider.start():
            requests.append(request)
        assert len(requests) == 1
        request = requests[0]
        assert isinstance(request, Request)
        assert "test-offer-123" in request.url
        assert request.callback == detail_spider.parse_detail
        assert "playwright" in request.meta

    @pytest.mark.asyncio
    async def test_detail_spider_inline_slugs_start(self, detail_spider):
        """Detail spider with inline slugs yields one request per slug."""
        detail_spider._slugs_list = ["slug-a", "slug-b", "slug-c"]
        requests = []
        async for request in detail_spider.start():
            requests.append(request)
        assert len(requests) == 3
        urls = {r.url for r in requests}
        assert all("otodom.pl/pl/oferta/" in u for u in urls)
        assert all(r.callback == detail_spider.parse_detail for r in requests)

    @pytest.mark.asyncio
    async def test_slug_spider_always_bootstraps(self, spider):
        """Slug spider always yields a bootstrap request to the first search page."""
        requests = []
        async for request in spider.start():
            requests.append(request)
        assert len(requests) == 1
        request = requests[0]
        assert "page=1" in request.url
        assert request.callback == spider._bootstrap


class TestBootstrapMethod:

    def test_bootstrap_success(self, spider, mock_response_with_json):
        spider._total_pages = 0
        spider._slugs = set()
        spider._investments = {}

        with patch.object(spider, '_parse_search_data') as mock_parse:
            mock_parse.return_value = {
                "pagination": {"totalItems": 150, "totalPages": 3},
                "items": [
                    {"slug": "listing-1", "estate": "REGULAR"},
                    {"slug": "listing-2", "estate": "REGULAR"},
                ],
            }
            with patch('property_scraper.spiders.otodom.build_otodom_url') as mock_url:
                mock_url.return_value = "https://example.com/page=2"
                results = list(spider._bootstrap(mock_response_with_json))
                # Pages 2 and 3 (max_pages=5 but only 3 total)
                assert len(results) == 2
                assert all(isinstance(r, Request) for r in results)
                assert results[0].callback == spider._collect_slugs

    def test_bootstrap_no_data(self, spider, mock_response_with_json):
        with patch.object(spider, '_parse_search_data', return_value=None):
            results = list(spider._bootstrap(mock_response_with_json))
            assert len(results) == 0


class TestParseDetailMethod:

    def test_parse_detail_success(self, detail_spider, sample_detail_json):
        html = f'<script id="__NEXT_DATA__">{json.dumps(sample_detail_json)}</script>'
        response = TextResponse(
            url="https://www.otodom.pl/pl/oferta/test-slug",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )

        items = list(detail_spider.parse_detail(response))
        assert len(items) == 2
        item = items[0]
        assert isinstance(item, RawListingItem)
        raw_item = items[1]
        assert isinstance(raw_item, RawJsonItem)

        assert item["source_portal"] == "otodom"
        assert item["external_id"] == "12345"
        assert item["title"] == "Przestronne mieszkanie w centrum"
        assert item["price_pln"] == 850000
        assert item["price_per_m2"] == 12500
        assert item["area_m2"] == 68.0
        assert item["rooms"] == 3
        assert item["floor"] == 2
        assert item["total_floors"] == 5
        assert item["year_built"] == 2010
        assert item["city"] == "Krakow"  # capitalised from detail_spider.city
        assert item["district"] == "Centrum"
        assert item["street"] == "Florianska"
        assert item["latitude"] == 50.0614
        assert item["longitude"] == 19.9372
        assert item["has_lift"] is True
        assert item["has_balcony"] is True
        assert item["has_terrace"] is True
        assert item["has_storage"] is False
        assert item["heating_type"] == "municipal"
        assert item["parking"] == "garage"
        assert item["building_material"] == "brick"
        assert item["property_type"] == "apartment"
        assert item["market_type"] == "secondary"
        assert item["listing_type"] == "agency"
        assert len(item["photo_urls"]) == 2
        assert item["photo_count"] == 2
        assert raw_item["raw_json"] == sample_detail_json["props"]["pageProps"]["ad"]
        assert raw_item["external_id"] == "12345"
        assert raw_item["source_url"] == "https://www.otodom.pl/pl/oferta/test-slug"

    def test_parse_detail_no_script(self, detail_spider):
        html = "<html><body>No script</body></html>"
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        items = list(detail_spider.parse_detail(response))
        assert len(items) == 0


# ─── Integration Tests for Error Handling ──────────────────────────────────

class TestErrorHandling:

    def test_on_search_error(self, spider):
        spider._search_pages_received = 2
        spider._total_pages = 3
        spider._slugs = {"slug1", "slug2"}

        failure = Mock()
        failure.value = "Connection failed"

        with patch.object(spider, '_finish_search_collection') as mock_finish:
            list(spider._on_search_error(failure))
            assert spider._search_pages_received == 3
            assert mock_finish.called

    def test_on_detail_error(self, detail_spider, caplog):
        failure = Mock()
        failure.request = Mock(url="https://example.com/offer/123")
        failure.value = "404 Not Found"

        result = detail_spider._on_detail_error(failure)
        if result is not None:
            list(result)
        assert "Detail page request failed" in caplog.text


# ─── Integration Tests for Investment Handling ─────────────────────────────

class TestInvestmentHandling:

    def test_extract_units_from_html(self, spider):
        spider._slugs = set()
        html = '''
        <html>
            <a href="/pl/oferta/unit-1">Unit 1</a>
            <a href="/pl/oferta/unit-2">Unit 2</a>
            <a href="/pl/oferta/investment-slug">Parent</a>
            <a href="/pl/oferta/unit-3#extra">Unit 3</a>
            <a href="https://other.com/pl/oferta/unit-4">External</a>
        </html>
        '''
        response = TextResponse(
            url="https://www.otodom.pl/pl/inwestycja/investment-slug",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )

        spider._extract_units_from_html(response, "investment-slug")
        assert len(spider._slugs) == 4
        assert "unit-1" in spider._slugs
        assert "unit-2" in spider._slugs
        assert "unit-3" in spider._slugs
        assert "unit-4" in spider._slugs
        assert "investment-slug" not in spider._slugs

    def test_finish_all_collection_yields_nothing(self, spider, tmp_path):
        """Slug spider always stops after persisting — never yields detail requests."""
        spider._slugs = {"slug1", "slug2"}
        spider._investments = {123: ("inv-slug", 10)}
        spider._total_items = 100

        spider.settings = {"DATA_DIR": str(tmp_path)}
        spider.run_timestamp = "test_timestamp"

        spider._finish_all_collection()

        slug_runs_file = tmp_path / "otodom" / "test_timestamp" / "slug_runs.jsonl"
        assert slug_runs_file.exists()

    def test_finish_all_collection_record_content(self, spider, tmp_path):
        """slug_runs.jsonl contains expected fields."""
        spider._slugs = {"slug1", "slug2", "slug3"}
        spider._investments = {}
        spider._total_items = 50

        spider.settings = {"DATA_DIR": str(tmp_path)}
        spider.run_timestamp = "test_timestamp"

        spider._finish_all_collection()

        slug_runs_file = tmp_path / "otodom" / "test_timestamp" / "slug_runs.jsonl"
        with open(slug_runs_file) as f:
            record = json.loads(f.readline())

        assert record["record_type"] == "slug_collection"
        assert record["slug_count"] == 3
        assert set(record["slugs"]) == {"slug1", "slug2", "slug3"}
        assert record["total_advertised"] == 50


# ─── Test Property Type Mapping ────────────────────────────────────────────

def test_property_type_mapping():
    from property_scraper.spiders.otodom import _PROPERTY_TYPE_MAP
    assert _PROPERTY_TYPE_MAP["mieszkanie"] == "apartment"
    assert _PROPERTY_TYPE_MAP["dom"] == "house"
    assert "unknown" not in _PROPERTY_TYPE_MAP


# ─── Test Edge Cases ───────────────────────────────────────────────────────

class TestEdgeCases:

    def test_parse_detail_missing_fields(self, detail_spider):
        json_data = {
            "props": {
                "pageProps": {
                    "ad": {
                        "id": 999,
                        "title": "Test",
                        "description": "",
                        "totalPrice": None,
                        "location": {},
                        "images": [],
                        "characteristics": [],
                        "features": [],
                    }
                }
            }
        }
        html = f'<script id="__NEXT_DATA__">{json.dumps(json_data)}</script>'
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )

        items = list(detail_spider.parse_detail(response))
        assert len(items) == 2
        item = items[0]
        assert isinstance(item, RawListingItem)
        assert item["price_pln"] is None
        assert item["price_per_m2"] is None
        assert item["area_m2"] is None
        assert item["rooms"] is None
        assert item["district"] is None
        assert item["street"] is None
        assert item["latitude"] is None
        assert item["longitude"] is None
        assert item["photo_urls"] == []
        assert item["photo_count"] == 0

    def test_parse_floor_edge_cases(self):
        assert OtodomDetailSpider._parse_floor("") is None
        assert OtodomDetailSpider._parse_floor("   ") is None
        assert OtodomDetailSpider._parse_floor("ground_floor") == 0
        assert OtodomDetailSpider._parse_floor("parter") == 0
        assert OtodomDetailSpider._parse_floor("10") == 10
        assert OtodomDetailSpider._parse_floor("-1") == -1

    def test_parse_detail_invalid_json(self, detail_spider):
        html = '<script id="__NEXT_DATA__">{invalid json}</script>'
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        items = list(detail_spider.parse_detail(response))
        assert len(items) == 0

    def test_parse_detail_no_ad_data(self, detail_spider):
        json_data = {"props": {"pageProps": {}}}
        html = f'<script id="__NEXT_DATA__">{json.dumps(json_data)}</script>'
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        items = list(detail_spider.parse_detail(response))
        assert len(items) == 0
