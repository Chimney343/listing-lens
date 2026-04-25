"""Tests for project downloader middlewares."""

from unittest.mock import Mock, patch

from scrapy import Request

from property_scraper.middlewares import CorrelationIdMiddleware, RandomBrowserMiddlewareCompat


def test_process_request_sets_correlation_meta_and_header() -> None:
    middleware = CorrelationIdMiddleware()
    request = Request("https://www.otodom.pl/pl/oferta/sample-slug")

    with patch("property_scraper.middlewares.get_correlation_id", return_value="cid-123"):
        middleware.process_request(request, spider=Mock())

    assert request.meta["correlation_id"] == "cid-123"
    assert request.headers.get(b"X-Correlation-ID") == b"cid-123"
    assert "_obs_started_at" in request.meta


def test_process_request_generates_correlation_when_missing() -> None:
    middleware = CorrelationIdMiddleware()
    request = Request("https://www.otodom.pl/pl/oferta/sample-slug")

    with patch("property_scraper.middlewares.get_correlation_id", return_value=""):
        with patch("property_scraper.middlewares.set_correlation_id", return_value="generated-cid") as mock_set:
            middleware.process_request(request, spider=Mock())

    mock_set.assert_called_once_with()
    assert request.meta["correlation_id"] == "generated-cid"
    assert request.headers.get(b"X-Correlation-ID") == b"generated-cid"


def test_process_exception_logs_bounded_endpoint_kind() -> None:
    middleware = CorrelationIdMiddleware()
    request = Request("https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/mielec")
    request.meta["_obs_started_at"] = 10.0
    spider = Mock()

    with patch("property_scraper.middlewares.time.perf_counter", return_value=10.5):
        middleware.process_exception(request, RuntimeError("boom"), spider=spider)

    spider._log.error.assert_called_once()
    args, kwargs = spider._log.error.call_args
    assert args[0] == "Request failed with exception"
    assert kwargs["endpoint_kind"] == "search_page"
    assert kwargs["error_type"] == "RuntimeError"
    assert kwargs["duration_ms"] == 500.0


def test_endpoint_kind_classifier() -> None:
    middleware = CorrelationIdMiddleware()

    assert middleware._endpoint_kind("https://www.otodom.pl/pl/wyniki/sprzedaz") == "search_page"
    assert middleware._endpoint_kind("https://www.otodom.pl/pl/inwestycja/abc") == "investment_page"
    assert middleware._endpoint_kind("https://www.otodom.pl/pl/oferta/abc") == "detail_page"
    assert middleware._endpoint_kind("https://www.otodom.pl/") == "other"


def test_random_browser_middleware_compat_accepts_optional_spider() -> None:
    class _FakeSettings:
        def getlist(self, _key: str, default):
            return default

    middleware = RandomBrowserMiddlewareCompat(_FakeSettings())
    request = Request("https://www.otodom.pl/pl/oferta/sample-slug")

    middleware.process_request(request)

    assert "impersonate" in request.meta
