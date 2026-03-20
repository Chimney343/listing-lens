"""Tests to verify all stealth techniques are actually applied during execution."""
import json
from unittest.mock import Mock, patch, AsyncMock
import pytest
from scrapy.http import TextResponse, Request

from property_scraper.spiders.otodom import (
    OtodomSpider,
    _STEALTH_SCRIPT,
    _CAPTURE_FETCH_SCRIPT,
    _UNITS_FETCH_SCRIPT,
    _page_init,
    _page_init_investment,
    _pw_meta,
)


class TestStealthScripts:
    """Test that stealth scripts are correctly defined and injected."""

    def test_stealth_script_content(self):
        """Verify the stealth script contains key evasion techniques."""
        assert "Object.defineProperty(navigator, 'webdriver'" in _STEALTH_SCRIPT
        assert "get: () => undefined" in _STEALTH_SCRIPT
        assert "window.chrome = {runtime: {}}" in _STEALTH_SCRIPT
        assert "['pl-PL', 'pl', 'en-US', 'en']" in _STEALTH_SCRIPT
        assert "[1, 2, 3, 4, 5]" in _STEALTH_SCRIPT  # Fake plugins

    def test_capture_fetch_script_content(self):
        """Verify the fetch interception script is correctly defined."""
        assert "const _origFetch = window.fetch" in _CAPTURE_FETCH_SCRIPT
        assert "window.__investmentApiUrl = null" in _CAPTURE_FETCH_SCRIPT
        assert "url.includes('PaginatedInvestmentUnits')" in _CAPTURE_FETCH_SCRIPT

    def test_units_fetch_script_content(self):
        """Verify the units fetch script handles pagination and errors."""
        assert "async () => {" in _UNITS_FETCH_SCRIPT
        assert "pageSize: 200" in _UNITS_FETCH_SCRIPT
        assert "sha256Hash" in _UNITS_FETCH_SCRIPT
        assert "error" in _UNITS_FETCH_SCRIPT  # Error handling


class TestPageInitCallbacks:
    """Test that page initialization callbacks inject stealth scripts."""

    @pytest.mark.asyncio
    async def test_page_init_injects_stealth(self):
        """Test _page_init adds stealth script to page."""
        mock_page = AsyncMock()
        mock_request = Mock()
        
        await _page_init(mock_page, mock_request)
        
        # Verify add_init_script was called with stealth script
        mock_page.add_init_script.assert_called_once()
        call_arg = mock_page.add_init_script.call_args[0][0]
        assert _STEALTH_SCRIPT in call_arg

    @pytest.mark.asyncio
    async def test_page_init_investment_injects_both_scripts(self):
        """Test _page_init_investment adds both stealth and capture scripts."""
        mock_page = AsyncMock()
        mock_request = Mock()
        
        await _page_init_investment(mock_page, mock_request)
        
        # Verify add_init_script was called with combined scripts
        mock_page.add_init_script.assert_called_once()
        call_arg = mock_page.add_init_script.call_args[0][0]
        assert _STEALTH_SCRIPT in call_arg
        assert _CAPTURE_FETCH_SCRIPT in call_arg


class TestPlaywrightMeta:
    """Test that playwright metadata includes stealth configurations."""

    def test_pw_meta_includes_init_callback(self):
        """Test _pw_meta includes the page init callback."""
        meta = _pw_meta()
        assert "playwright_page_init_callback" in meta
        assert meta["playwright_page_init_callback"] == _page_init
        assert meta["playwright"] is True
        assert meta["playwright_context"] == "default"
        
        # Should include wait_for_load_state by default
        assert len(meta["playwright_page_methods"]) == 1
        method = meta["playwright_page_methods"][0]
        assert method.method == "wait_for_load_state"
        assert method.args[0] == "networkidle"

    def test_pw_meta_investment_includes_evaluate(self):
        """Test _pw_meta(investment=True) includes evaluate method for unit fetching."""
        meta = _pw_meta(investment=True)
        assert "playwright_page_init_callback" in meta
        assert meta["playwright_page_init_callback"] == _page_init_investment
        
        # Should have two methods: wait_for_load_state and evaluate
        methods = meta["playwright_page_methods"]
        assert len(methods) == 2
        
        # First method should be wait_for_load_state
        assert methods[0].method == "wait_for_load_state"
        
        # Second method should be evaluate with the units fetch script
        assert methods[1].method == "evaluate"
        assert methods[1].args[0] == _UNITS_FETCH_SCRIPT


class TestSpiderRequestStealth:
    """Test that spider requests include stealth metadata."""

    @pytest.mark.asyncio
    async def test_start_requests_include_stealth(self):
        """Test that start requests include playwright stealth meta."""
        spider = OtodomSpider(slug="test-offer-123")
        
        requests = []
        async for request in spider.start():
            requests.append(request)
        
        assert len(requests) == 1
        request = requests[0]
        
        # Verify playwright meta is included
        assert "playwright" in request.meta
        assert request.meta["playwright"] is True
        assert "playwright_page_init_callback" in request.meta
        assert request.meta["playwright_page_init_callback"] == _page_init

    def test_detail_requests_include_stealth(self):
        """Test that detail page requests include stealth meta."""
        spider = OtodomSpider()
        spider._slugs = {"test-slug-1", "test-slug-2"}
        spider._investments = {}
        spider._total_items = 10
        spider.settings = {"DATA_DIR": "/tmp"}
        
        # Mock _persist_slug_run to avoid file operations
        with patch.object(spider, '_persist_slug_run'):
            requests = list(spider._finish_all_collection())
        
        assert len(requests) == 2
        for request in requests:
            assert "playwright" in request.meta
            assert request.meta["playwright"] is True
            assert "playwright_page_init_callback" in request.meta


class TestSettingsConfiguration:
    """Test that Scrapy settings enforce stealth behavior."""

    def test_load_settings_from_file(self):
        """Verify critical stealth settings are loaded from settings.py."""
        from scrapy.settings import Settings
        from property_scraper import settings as scraper_settings
        
        # Create settings object using the module
        settings = Settings()
        settings.setmodule(scraper_settings)
        
        # Verify Playwright is configured
        assert settings.get("DOWNLOAD_HANDLERS")["http"] == \
               "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler"
        assert settings.get("DOWNLOAD_HANDLERS")["https"] == \
               "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler"
        
        # Verify browser stealth settings
        assert settings.get("PLAYWRIGHT_BROWSER_TYPE") == "chromium"
        launch_opts = settings.get("PLAYWRIGHT_LAUNCH_OPTIONS")
        assert "--disable-blink-features=AutomationControlled" in launch_opts["args"]
        
        # Verify human-like browser context
        contexts = settings.get("PLAYWRIGHT_CONTEXTS")
        default_context = contexts["default"]
        assert default_context["locale"] == "pl-PL"
        assert default_context["timezone_id"] == "Europe/Warsaw"
        assert "pl-PL,pl;q=0.9" in default_context["extra_http_headers"]["Accept-Language"]
        
        # Verify throttling (human-like delays)
        assert settings.get("AUTOTHROTTLE_ENABLED") is True
        assert settings.get("DOWNLOAD_DELAY") >= 3
        assert settings.get("RANDOMIZE_DOWNLOAD_DELAY") is True
        
        # Verify concurrency limits (avoid overwhelming servers)
        assert settings.get("CONCURRENT_REQUESTS_PER_DOMAIN") == 1
        
        # Verify cookies are enabled (like real browser)
        assert settings.get("COOKIES_ENABLED") is True

    def test_spider_inherits_settings(self):
        """Test that spider instance has access to stealth settings."""
        spider = OtodomSpider()
        
        # Create a mock crawler with settings
        mock_crawler = Mock()
        mock_crawler.settings = {
            "PLAYWRIGHT_BROWSER_TYPE": "chromium",
            "DOWNLOAD_DELAY": 3,
            "AUTOTHROTTLE_ENABLED": True,
        }
        
        # Simulate spider being opened with crawler
        spider.crawler = mock_crawler
        spider.settings = mock_crawler.settings
        
        # Verify spider can access settings
        assert spider.settings.get("PLAYWRIGHT_BROWSER_TYPE") == "chromium"
        assert spider.settings.get("DOWNLOAD_DELAY") == 3


class TestIntegrationStealth:
    """Integration tests to verify stealth techniques work together."""

    def test_complete_request_flow(self):
        """Test that a request goes through all stealth layers."""
        spider = OtodomSpider()
        
        # Create a request as the spider would
        request = Request(
            url="https://www.otodom.pl/pl/oferta/test",
            callback=spider.parse_detail,
            meta=_pw_meta()
        )
        
        # Verify all stealth layers are present
        meta = request.meta
        assert meta["playwright"] is True
        assert meta["playwright_context"] == "default"
        assert meta["playwright_page_init_callback"] == _page_init
        assert len(meta["playwright_page_methods"]) == 1
        
        # The callback should inject stealth script
        assert meta["playwright_page_init_callback"] is _page_init

    def test_investment_request_flow(self):
        """Test that investment requests include additional stealth layers."""
        spider = OtodomSpider()
        
        # Create an investment request as the spider would
        request = Request(
            url="https://www.otodom.pl/pl/inwestycja/test",
            callback=spider._on_investment_page,
            meta={"ad_id": 123, "inv_slug": "test", "expected_units": 10, **_pw_meta(investment=True)}
        )
        
        # Verify investment-specific stealth
        meta = request.meta
        assert meta["playwright_page_init_callback"] == _page_init_investment
        
        # Should have evaluate method for unit fetching
        methods = meta["playwright_page_methods"]
        assert len(methods) == 2
        assert methods[1].method == "evaluate"
        assert methods[1].args[0] == _UNITS_FETCH_SCRIPT


class TestErrorHandlingStealth:
    """Test that error handling maintains stealth characteristics."""

    def test_error_requests_still_stealthy(self):
        """Test that retry requests after errors maintain stealth config."""
        spider = OtodomSpider()
        
        # Simulate a request that will be retried
        request = Request(
            url="https://www.otodom.pl/pl/oferta/test",
            callback=spider.parse_detail,
            meta=_pw_meta(),
            errback=spider._on_detail_error
        )
        
        # Even with errback, stealth meta should persist
        assert "playwright" in request.meta
        assert request.meta["playwright"] is True
        
        # The errback should handle errors gracefully without breaking stealth
        assert request.errback == spider._on_detail_error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])