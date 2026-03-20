"""Unit and integration tests for the OtodomSpider."""
import json
from unittest.mock import Mock, patch, AsyncMock

import pytest
import scrapy
from scrapy.http import Response, Request, TextResponse
from scrapy.utils.test import get_crawler

from property_scraper.spiders.otodom import OtodomSpider
from property_scraper.items import RawListingItem, RawJsonItem


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def spider():
    """Return an OtodomSpider instance with default parameters."""
    return OtodomSpider(
        city="krakow",
        voivodeship="malopolskie",
        powiat="krakowski",
        gmina="gmina-miejska--krakow",
        property_type="mieszkanie",
        districts="",
        price_min=None,
        price_max=None,
        max_pages="5",
        phase1_only="0",
        slug=None,
    )


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
                            "street": {"name": "Floriańska"},
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
    """Test the static helper methods of OtodomSpider."""

    def test_extract_price_dict(self):
        """Test _extract_price with dict input."""
        price_dict = {"value": 500000}
        assert OtodomSpider._extract_price(price_dict) == 500000

    def test_extract_price_scalar(self):
        """Test _extract_price with scalar input."""
        assert OtodomSpider._extract_price(750000) == 750000
        assert OtodomSpider._extract_price(None) is None

    def test_safe_int_valid(self):
        """Test _safe_int with valid inputs."""
        assert OtodomSpider._safe_int("42") == 42
        assert OtodomSpider._safe_int(42) == 42
        assert OtodomSpider._safe_int(None) is None

    def test_safe_int_invalid(self):
        """Test _safe_int with invalid inputs."""
        assert OtodomSpider._safe_int("not a number") is None
        assert OtodomSpider._safe_int([]) is None

    def test_safe_float_valid(self):
        """Test _safe_float with valid inputs."""
        assert OtodomSpider._safe_float("68.5") == 68.5
        assert OtodomSpider._safe_float(68.5) == 68.5
        assert OtodomSpider._safe_float(None) is None

    def test_safe_float_invalid(self):
        """Test _safe_float with invalid inputs."""
        assert OtodomSpider._safe_float("invalid") is None

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
        """Test _parse_floor with various inputs."""
        assert OtodomSpider._parse_floor(input_val) == expected


# ─── Unit Tests for Parsing Methods ────────────────────────────────────────

class TestParseSearchData:
    """Test the _parse_search_data method."""

    def test_parse_search_data_success(self, spider, mock_response_with_json):
        """Test successful extraction of search data."""
        result = spider._parse_search_data(mock_response_with_json)
        assert result is not None
        assert "pagination" in result
        assert "items" in result
        assert len(result["items"]) == 3

    def test_parse_search_data_no_script(self, spider):
        """Test when __NEXT_DATA__ script is missing."""
        html = "<html><body>No script</body></html>"
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        result = spider._parse_search_data(response)
        assert result is None

    def test_parse_search_data_invalid_json(self, spider):
        """Test when __NEXT_DATA__ contains invalid JSON."""
        html = '<script id="__NEXT_DATA__">{invalid json}</script>'
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        result = spider._parse_search_data(response)
        assert result is None


class TestAbsorbSearchItems:
    """Test the _absorb_search_items method."""

    def test_absorb_search_items_regular(self, spider):
        """Test absorbing regular listings."""
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
        """Test absorbing investment listings."""
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
        """Test absorbing mixed regular and investment listings."""
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
    """Test spider initialization with various parameters."""

    def test_default_init(self):
        """Test spider initialization with default parameters."""
        spider = OtodomSpider()
        assert spider.area.city == "mielec"
        assert spider.area.property_type == "mieszkanie"
        assert spider.area.max_pages is None
        assert spider.phase1_only is False

    def test_custom_init(self):
        """Test spider initialization with custom parameters."""
        spider = OtodomSpider(
            city="warszawa",
            districts="mokotow,wola",
            price_min="500000",
            price_max="1000000",
            max_pages="10",
            phase1_only="1",
        )
        assert spider.area.city == "warszawa"
        assert spider.area.districts == ["mokotow", "wola"]
        assert spider.area.price_min == 500000
        assert spider.area.price_max == 1000000
        assert spider.area.max_pages == 10
        assert spider.phase1_only is True
        
        # Test that parameters are stored
        assert spider._parameters["city"] == "warszawa"
        assert spider._parameters["districts"] == "mokotow,wola"
        assert spider._parameters["price_min"] == "500000"
        assert spider._parameters["price_max"] == "1000000"
        assert spider._parameters["max_pages"] == "10"
        assert spider._parameters["phase1_only"] == "1"

    def test_single_slug_mode(self):
        """Test spider initialization with single slug mode."""
        spider = OtodomSpider(slug="test-slug-123")
        assert spider.single_slug == "test-slug-123"
        assert spider.phase1_only is False
        assert spider._parameters["slug"] == "test-slug-123"

    def test_run_timestamp_internal(self):
        """Test that run_timestamp is set at construction time."""
        spider = OtodomSpider()
        # run_timestamp is generated in __init__ so run_dir is stable before start()
        assert spider.run_timestamp is not None
        assert len(spider.run_timestamp) == 15  # yyyyMMdd_HHmmss
        assert spider._start_time is None   # only set when scraping begins
        assert spider._end_time is None
        
        # Verify run_timestamp is not in parameters (it's infra, not a search param)
        assert "run_timestamp" not in spider._parameters
        
    def test_parameters_stored(self):
        """Test that all constructor parameters are stored in _parameters."""
        spider = OtodomSpider(
            city="krakow",
            voivodeship="malopolskie",
            powiat="krakowski",
            gmina="gmina-miejska--krakow",
            property_type="dom",
            districts="kazimierz,podgorze",
            price_min="300000",
            price_max="800000",
            max_pages="5",
            phase1_only="0",
            slug=None,
        )
        
        expected_params = {
            "city": "krakow",
            "voivodeship": "malopolskie",
            "powiat": "krakowski",
            "gmina": "gmina-miejska--krakow",
            "property_type": "dom",
            "districts": "kazimierz,podgorze",
            "price_min": "300000",
            "price_max": "800000",
            "max_pages": "5",
            "phase1_only": "0",
            "slug": None,
        }
        
        for key, value in expected_params.items():
            assert spider._parameters[key] == value


class TestStartMethod:
    """Test the start method."""

    @pytest.mark.asyncio
    async def test_start_single_slug(self, spider):
        """Test start method in single slug mode."""
        spider.single_slug = "test-offer-123"
        requests = []
        async for request in spider.start():
            requests.append(request)
        assert len(requests) == 1
        request = requests[0]
        assert isinstance(request, Request)
        assert "test-offer-123" in request.url
        assert request.callback == spider.parse_detail
        assert "playwright" in request.meta

    @pytest.mark.asyncio
    async def test_start_normal_mode(self, spider):
        """Test start method in normal search mode."""
        spider.single_slug = None
        requests = []
        async for request in spider.start():
            requests.append(request)
        assert len(requests) == 1
        request = requests[0]
        assert "page=1" in request.url
        assert request.callback == spider._bootstrap


class TestBootstrapMethod:
    """Test the _bootstrap method."""

    def test_bootstrap_success(self, spider, mock_response_with_json):
        """Test successful bootstrap with pagination."""
        spider._total_pages = 0  # Will be set by bootstrap
        spider._slugs = set()
        spider._investments = {}
        
        # Mock the _parse_search_data to return our sample data
        with patch.object(spider, '_parse_search_data') as mock_parse:
            mock_parse.return_value = {
                "pagination": {
                    "totalItems": 150,
                    "totalPages": 3,
                },
                "items": [
                    {"slug": "listing-1", "estate": "REGULAR"},
                    {"slug": "listing-2", "estate": "REGULAR"},
                ],
            }
            
            # Mock build_otodom_url to return predictable URLs
            with patch('property_scraper.spiders.otodom.build_otodom_url') as mock_url:
                mock_url.return_value = "https://example.com/page=2"
                
                # Execute bootstrap
                results = list(spider._bootstrap(mock_response_with_json))
                
                # Should generate requests for pages 2 and 3
                assert len(results) == 2  # Pages 2 and 3
                assert all(isinstance(r, Request) for r in results)
                assert results[0].callback == spider._collect_slugs

    def test_bootstrap_no_data(self, spider, mock_response_with_json):
        """Test bootstrap when no search data is found."""
        with patch.object(spider, '_parse_search_data', return_value=None):
            results = list(spider._bootstrap(mock_response_with_json))
            assert len(results) == 0  # No further requests


class TestParseDetailMethod:
    """Test the parse_detail method."""

    def test_parse_detail_success(self, spider, sample_detail_json):
        """Test successful parsing of detail page."""
        html = f'<script id="__NEXT_DATA__">{json.dumps(sample_detail_json)}</script>'
        response = TextResponse(
            url="https://www.otodom.pl/pl/oferta/test-slug",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        
        items = list(spider.parse_detail(response))
        assert len(items) == 2
        item = items[0]
        assert isinstance(item, RawListingItem)
        raw_item = items[1]
        assert isinstance(raw_item, RawJsonItem)
        
        # Verify key fields
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
        assert item["city"] == "Krakow"  # Capitalized
        assert item["district"] == "Centrum"
        assert item["street"] == "Floriańska"
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

    def test_parse_detail_no_script(self, spider):
        """Test detail parsing when __NEXT_DATA__ is missing."""
        html = "<html><body>No script</body></html>"
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        items = list(spider.parse_detail(response))
        assert len(items) == 0


# ─── Integration Tests for Error Handling ──────────────────────────────────

class TestErrorHandling:
    """Test error handling methods."""

    def test_on_search_error(self, spider):
        """Test _on_search_error method."""
        spider._search_pages_received = 2
        spider._total_pages = 3
        spider._slugs = {"slug1", "slug2"}
        
        # Mock failure
        failure = Mock()
        failure.value = "Connection failed"
        
        # Mock _finish_search_collection to track if called
        with patch.object(spider, '_finish_search_collection') as mock_finish:
            results = list(spider._on_search_error(failure))
            assert spider._search_pages_received == 3
            # Should call finish since we've reached total pages
            assert mock_finish.called

    def test_on_detail_error(self, spider, caplog):
        """Test _on_detail_error method."""
        failure = Mock()
        failure.request = Mock(url="https://example.com/offer/123")
        failure.value = "404 Not Found"
        
        # Should log error but not raise
        result = spider._on_detail_error(failure)
        if result is not None:
            list(result)  # Should be None or empty iterable
        assert "Detail page request failed" in caplog.text


# ─── Integration Tests for Investment Handling ─────────────────────────────

class TestInvestmentHandling:
    """Test investment-related methods."""

    def test_extract_units_from_html(self, spider):
        """Test _extract_units_from_html fallback method."""
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
        # Should collect 4 unit slugs (including external domain)
        assert len(spider._slugs) == 4
        assert "unit-1" in spider._slugs
        assert "unit-2" in spider._slugs
        assert "unit-3" in spider._slugs
        assert "unit-4" in spider._slugs
        assert "investment-slug" not in spider._slugs  # Parent excluded

    def test_finish_all_collection_phase1_only(self, spider, tmp_path):
        """Test _finish_all_collection with phase1_only=True."""
        spider.phase1_only = True
        spider._slugs = {"slug1", "slug2"}
        spider._investments = {123: ("inv-slug", 10)}
        spider._total_items = 100
        
        # Mock settings and set run_timestamp (simulating start() was called)
        spider.settings = {"DATA_DIR": str(tmp_path)}
        spider.run_timestamp = "test_timestamp"
        
        results = list(spider._finish_all_collection())
        assert len(results) == 0  # No detail requests in phase1_only mode
        
        # Check that slug run file was created in run_dir
        # run_dir = data_dir / "otodom" / run_timestamp
        slug_runs_file = tmp_path / "otodom" / spider.run_timestamp / "slug_runs.jsonl"
        assert slug_runs_file.exists()

    def test_finish_all_collection_normal(self, spider, tmp_path):
        """Test _finish_all_collection with phase1_only=False."""
        spider.phase1_only = False
        spider._slugs = {"slug1", "slug2", "slug3"}
        spider._investments = {}
        spider._total_items = 50
        
        spider.settings = {"DATA_DIR": str(tmp_path)}
        spider.run_timestamp = "test_timestamp"
        
        results = list(spider._finish_all_collection())
        # Should generate 3 detail requests
        assert len(results) == 3
        assert all(isinstance(r, Request) for r in results)
        assert all(r.callback == spider.parse_detail for r in results)
        
        # Verify URLs contain each slug
        urls = [r.url for r in results]
        slugs_in_urls = {url.split("/")[-1] for url in urls}
        assert slugs_in_urls == {"slug1", "slug2", "slug3"}


# ─── Test Property Type Mapping ────────────────────────────────────────────

def test_property_type_mapping():
    """Test the _PROPERTY_TYPE_MAP constant."""
    from property_scraper.spiders.otodom import _PROPERTY_TYPE_MAP
    
    assert _PROPERTY_TYPE_MAP["mieszkanie"] == "apartment"
    assert _PROPERTY_TYPE_MAP["dom"] == "house"
    assert "unknown" not in _PROPERTY_TYPE_MAP


# ─── Test Edge Cases ───────────────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_parse_detail_missing_fields(self, spider):
        """Test parsing detail page with missing optional fields."""
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
        
        items = list(spider.parse_detail(response))
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
        """Test floor parsing with edge cases."""
        assert OtodomSpider._parse_floor("") is None
        assert OtodomSpider._parse_floor("   ") is None
        assert OtodomSpider._parse_floor("ground_floor") == 0
        assert OtodomSpider._parse_floor("parter") == 0
        assert OtodomSpider._parse_floor("10") == 10
        assert OtodomSpider._parse_floor("-1") == -1

    def test_parse_detail_invalid_json(self, spider):
        """Test detail parsing with invalid JSON."""
        html = '<script id="__NEXT_DATA__">{invalid json}</script>'
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        items = list(spider.parse_detail(response))
        assert len(items) == 0

    def test_parse_detail_no_ad_data(self, spider):
        """Test detail parsing when ad data is missing."""
        json_data = {"props": {"pageProps": {}}}  # No 'ad' key
        html = f'<script id="__NEXT_DATA__">{json.dumps(json_data)}</script>'
        response = TextResponse(
            url="https://example.com",
            body=html.encode("utf-8"),
            encoding="utf-8",
        )
        items = list(spider.parse_detail(response))
        assert len(items) == 0
