"""Memory bounds, identity reuse and capture permission races."""

from dataclasses import replace

from workspace_overview.backends.mock import MockBackend
from workspace_overview.core.models import Preview, Window
from workspace_overview.core.overview import Overview
from workspace_overview.previews.cache import PreviewSampler, RamPreviewCache


def image(value=0):
    return Preview(2, 1, bytes([value]) * 6)


class CaptureBackend(MockBackend):
    def __init__(self):
        super().__init__(MockBackend.demo().snapshot())
        self.identities = {w.id: object() for w in self.snapshot().windows}

    def preview_identity(self, window_id):
        self._window(window_id)
        return self.identities[window_id]


def test_cache_budget_replacement_eviction_and_clear():
    cache = RamPreviewCache(max_bytes=12)
    cache.put(1, "first", image(1))
    cache.put(2, "second", image(2))
    cache.put(1, "first", image(3))
    cache.put(3, "third", image(4))
    assert list(cache.images) == [1, 3]
    assert cache.bytes_used == 12
    cache.put(4, "huge", Preview(5, 1, b"\0" * 15))
    assert list(cache.images) == [1, 3]
    cache.remove(1)
    assert cache.bytes_used == 6
    cache.clear()
    assert not cache.images and cache.bytes_used == 0


def test_closed_or_reused_xids_never_retain_old_images():
    cache = RamPreviewCache()
    first, second = object(), object()
    cache.put(1, first, image())
    cache.put(2, second, image())
    cache.reconcile({1: object(), 2: second})
    assert set(cache.images) == {2}
    cache.reconcile({})
    assert not cache.images


def test_capture_only_active_non_minimized_windows_and_keep_hidden_images():
    backend = CaptureBackend()
    cache = RamPreviewCache()
    sampler = PreviewSampler(backend, cache, lambda: True)
    sampler.sample(backend.snapshot())
    sampler.sample(backend.snapshot())
    assert backend.capture_requests == [101, 102]
    first = cache.images[101]
    backend.set_snapshot(
        replace(backend.snapshot(), active_workspace_id=20, active_window_id=201)
    )
    sampler.sample(backend.snapshot())
    assert backend.capture_requests[-1] == 201
    assert cache.images[101] is first
    assert not backend.actions
    backend.remove_window(101)
    sampler.reconcile(backend.snapshot())
    assert 101 not in cache.images


def test_pause_and_clear_during_capture_cannot_repopulate_cache():
    backend = CaptureBackend()
    cache = RamPreviewCache()
    allowed = [False]
    sampler = PreviewSampler(backend, cache, lambda: allowed[0])
    sampler.sample(backend.snapshot())
    assert not backend.capture_requests
    allowed[0] = True
    sampler.after_capture = cache.clear
    sampler.sample(backend.snapshot())
    assert backend.capture_requests and not cache.images
    sampler.after_capture = lambda: allowed.__setitem__(0, False)
    sampler.sample(backend.snapshot())
    assert not cache.images


def test_xid_reused_during_capture_is_discarded():
    backend = CaptureBackend()
    cache = RamPreviewCache()
    sampler = PreviewSampler(backend, cache, lambda: True)
    sampler.after_capture = lambda: backend.identities.__setitem__(101, object())
    sampler.sample(backend.snapshot())
    assert not cache.images


def test_external_cache_survives_overlay_close_without_duplicate_captures():
    backend = CaptureBackend()
    cache = RamPreviewCache()
    sampler = PreviewSampler(backend, cache, lambda: True)
    sampler.sample(backend.snapshot())
    overview = Overview(backend, previews=cache.images)
    overview.open()
    assert overview.previews[101] is cache.images[101]
    sampler.sample(backend.snapshot(), only_missing=True)
    assert backend.capture_requests == [101, 102]
    sampler.sample(backend.snapshot(), only_missing=True)
    assert backend.capture_requests == [101, 102]
    overview.close()
    assert len(cache.images) == 2
    cache.clear()
    assert not overview.previews


def test_cache_size_remains_bounded_with_many_windows():
    cache = RamPreviewCache(max_bytes=192)
    for i in range(100):
        cache.put(i, object(), image(i))
        assert cache.bytes_used <= 192
    assert len(cache.images) == 32
    # Window objects and titles are not kept in the image mapping.
    assert all(not isinstance(v, Window) for v in cache.images.values())
