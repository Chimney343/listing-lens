from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from property_scraper.playwright_shutdown import patch_threaded_loop_adapter


class _FakeEvent:
    def __init__(self, is_set: bool = False) -> None:
        self._is_set = is_set

    def set(self) -> None:
        self._is_set = True

    def is_set(self) -> bool:
        return self._is_set


class _FakeLoop:
    def __init__(self) -> None:
        self.stop_called = False

    def stop(self) -> None:
        self.stop_called = True

    def call_soon_threadsafe(self, callback, *args) -> None:
        callback(*args)


class _FakeThread:
    def __init__(self) -> None:
        self.join_called = False
        self.join_timeout = None

    def join(self, timeout=None) -> None:
        self.join_called = True
        self.join_timeout = timeout


class _FakeQueue:
    async def put(self, _item) -> None:
        return None

    async def join(self) -> None:
        return None


class _FakeAdapter:
    _stop_events = {1: _FakeEvent(False)}
    _coro_queue = _FakeQueue()
    _loop = _FakeLoop()
    _thread = _FakeThread()

    @classmethod
    def stop(cls, _download_handler_id: int) -> None:
        raise AssertionError("original stop should be patched")


def test_patch_threaded_loop_adapter_patches_stop_and_drains_queue(monkeypatch) -> None:
    run_calls: list[object] = []

    def _fake_run_coroutine_threadsafe(coro, _loop):
        run_calls.append(coro)
        if inspect.iscoroutine(coro):
            coro.close()

        class _DoneFuture:
            def result(self, timeout=None):
                return None

        return _DoneFuture()

    monkeypatch.setattr(
        "property_scraper.playwright_shutdown.asyncio.run_coroutine_threadsafe",
        _fake_run_coroutine_threadsafe,
    )

    applied = patch_threaded_loop_adapter(_FakeAdapter, force=True)
    assert applied is True

    _FakeAdapter.stop(1)

    assert len(run_calls) == 2
    assert _FakeAdapter._loop.stop_called is True
    assert _FakeAdapter._thread.join_called is True
    assert _FakeAdapter._thread.join_timeout == 10
    assert _FakeAdapter._stop_events == {}


def test_patch_threaded_loop_adapter_idempotent(monkeypatch) -> None:
    adapter = SimpleNamespace(stop=lambda *_args, **_kwargs: None)
    adapter._stop_events = {}
    adapter._coro_queue = _FakeQueue()
    adapter._loop = _FakeLoop()
    adapter._thread = _FakeThread()

    applied_first = patch_threaded_loop_adapter(adapter, force=True)
    applied_second = patch_threaded_loop_adapter(adapter, force=True)

    assert applied_first is True
    assert applied_second is False


def test_patch_threaded_loop_adapter_skips_non_windows(monkeypatch) -> None:
    monkeypatch.setattr("property_scraper.playwright_shutdown.platform.system", lambda: "Linux")

    applied = patch_threaded_loop_adapter(_FakeAdapter, force=False)

    assert applied is False
