"""Compatibility patch for scrapy-playwright shutdown on Windows.

This module patches scrapy-playwright's threaded loop adapter to drain its
internal coroutine queue before stopping the background event loop.
"""

from __future__ import annotations

import asyncio
import platform


class _StopSignal:
    """Sentinel item used to wake the queue consumer during shutdown."""

    promise = None


def patch_threaded_loop_adapter(adapter_cls: type | None = None, *, force: bool = False) -> bool:
    """Patch scrapy-playwright threaded loop shutdown to avoid pending-task warnings.

    Returns True when the patch was applied, False when skipped.
    """
    if not force and platform.system() != "Windows":
        return False

    if adapter_cls is None:
        try:
            from scrapy_playwright import _utils as playwright_utils
        except Exception:
            return False
        adapter_cls = playwright_utils._ThreadedLoopAdapter

    if getattr(adapter_cls, "_listing_lens_stop_patch", False):
        return False

    @classmethod
    def _patched_stop(cls, download_handler_id: int) -> None:
        stop_event = cls._stop_events.get(download_handler_id)
        if stop_event is None:
            return

        stop_event.set()
        if not all(ev.is_set() for ev in cls._stop_events.values()):
            return

        try:
            put_future = asyncio.run_coroutine_threadsafe(cls._coro_queue.put(_StopSignal()), cls._loop)
            put_future.result(timeout=5)

            join_future = asyncio.run_coroutine_threadsafe(cls._coro_queue.join(), cls._loop)
            join_future.result(timeout=10)
        except Exception:
            # Fall back to original shutdown semantics if draining fails.
            pass
        finally:
            cls._loop.call_soon_threadsafe(cls._loop.stop)
            cls._thread.join(timeout=10)
            cls._stop_events.clear()

    adapter_cls.stop = _patched_stop
    adapter_cls._listing_lens_stop_patch = True
    return True
