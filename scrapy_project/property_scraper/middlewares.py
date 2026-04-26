"""Project downloader middlewares."""

from __future__ import annotations

import time

import structlog

try:
	from scrapy_impersonate.middleware import RandomBrowserMiddleware as _RandomBrowserMiddleware
except ImportError:
	class _RandomBrowserMiddleware:
		"""Fallback no-op when scrapy-impersonate is unavailable."""

		def __init__(self, *args, **kwargs):
			pass

		@classmethod
		def from_crawler(cls, _crawler):
			return cls()

		def process_request(self, _request, _spider=None):
			return None

try:
	from logging_config import get_correlation_id, set_correlation_id
except ImportError:
	def get_correlation_id() -> str:
		return ""

	def set_correlation_id(cid: str | None = None) -> str:
		return cid or ""


class RandomBrowserMiddlewareCompat(_RandomBrowserMiddleware):
	"""Backwards/forwards-compatible wrapper for scrapy-impersonate middleware."""

	def process_request(self, request, spider=None):
		return super().process_request(request, spider)


class CorrelationIdMiddleware:
	"""Propagate run correlation IDs and emit bounded request failure telemetry."""

	_log = structlog.get_logger(__name__)

	@staticmethod
	def _endpoint_kind(url: str) -> str:
		if "/pl/oferta/" in url:
			return "detail_page"
		if "/pl/inwestycja/" in url:
			return "investment_page"
		if "/pl/wyniki/" in url:
			return "search_page"
		return "other"

	def process_request(self, request, spider=None):
		request.meta["_obs_started_at"] = time.perf_counter()

		correlation_id = request.meta.get("correlation_id") or get_correlation_id()
		if not correlation_id:
			correlation_id = set_correlation_id()

		request.meta["correlation_id"] = correlation_id
		request.headers.setdefault(b"X-Correlation-ID", correlation_id.encode("utf-8"))

	def process_response(self, request, response, spider=None):
		started = request.meta.get("_obs_started_at")
		if started is None or response.status < 400:
			return response

		duration_ms = (time.perf_counter() - started) * 1000
		logger = getattr(spider, "_log", self._log)
		logger.warning(
			"Request returned error status",
			endpoint_kind=self._endpoint_kind(request.url),
			status=response.status,
			duration_ms=round(duration_ms, 1),
		)
		return response

	def process_exception(self, request, exception, spider=None):
		started = request.meta.get("_obs_started_at")
		duration_ms = None
		if started is not None:
			duration_ms = round((time.perf_counter() - started) * 1000, 1)

		logger = getattr(spider, "_log", self._log)
		logger.error(
			"Request failed with exception",
			endpoint_kind=self._endpoint_kind(request.url),
			error_type=exception.__class__.__name__,
			duration_ms=duration_ms,
		)
		return None
