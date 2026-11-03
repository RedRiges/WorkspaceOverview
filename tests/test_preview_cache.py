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


class DeferredCapture:
    def __init__(self, backend):
        self.backend = backend
        self.requests = []
        self.pending = None
        self.result = None

    def submit(self, window_id):
        assert self.pending is None
        self.pending = window_id
        self.requests.append(window_id)
        return True

    def finish(self, image_override=None):
        image = image_override or self.backend.capture_preview(self.pending)
        self.result = (image, 85.0)

    def poll(self):
        result = self.result
        if result is not None:
            self.pending = self.result = None
        return result

    def cancel(self):
        self.pending = self.result = None

    close = cancel


def make_sampler():
    backend = CaptureBackend()
    cache = RamPreviewCache()
    worker = DeferredCapture(backend)
    now = [0.0]
    allowed = [True]
    sampler = PreviewSampler(
        backend, cache, lambda: allowed[0], worker=worker, clock=lambda: now[0]
    )
    return backend, cache, worker, sampler, now, allowed


def test_capture_only_active_non_minimized_windows_and_keep_hidden_images():
    backend, cache, worker, sampler, _, _ = make_sampler()
    sampler.sample(backend.snapshot())
    for _ in range(20):
        sampler.sample(backend.snapshot())
    assert worker.requests == [101]  # Busy worker never accumulates a queue.
    assert not cache.images
    worker.finish()
    sampler.sample(backend.snapshot())
    assert worker.requests == [101, 102]
    first = cache.images[101]
    worker.finish()
    backend.set_snapshot(
        replace(backend.snapshot(), active_workspace_id=20, active_window_id=201)
    )
    sampler.sample(backend.snapshot())
    assert worker.requests[-1] == 201
    assert cache.images[101] is first
    assert not backend.actions
    backend.remove_window(101)
    sampler.reconcile(backend.snapshot())
    assert 101 not in cache.images
    assert 101 not in sampler._schedule


def test_pause_and_clear_during_capture_cannot_repopulate_cache():
    backend, cache, worker, sampler, _, allowed = make_sampler()
    allowed[0] = False
    sampler.sample(backend.snapshot())
    assert not worker.requests
    allowed[0] = True
    sampler.sample(backend.snapshot())
    worker.finish()
    cache.clear()  # Even without cancelling, an old epoch is discarded.
    sampler.sample(backend.snapshot())
    assert not cache.images
    worker.finish()
    allowed[0] = False
    sampler.sample(backend.snapshot())
    assert not cache.images and worker.pending is None
    assert sampler._pending is None


def test_closed_or_reused_xid_during_capture_is_discarded():
    backend, cache, worker, sampler, _, _ = make_sampler()
    sampler.sample(backend.snapshot())
    worker.finish()
    backend.identities[101] = object()
    sampler.sample(backend.snapshot())
    assert not cache.images
    worker.finish()
    backend.remove_window(101)
    sampler.sample(backend.snapshot())
    assert not cache.images


def test_external_cache_survives_overlay_close_without_duplicate_captures():
    backend, cache, worker, sampler, _, _ = make_sampler()
    sampler.sample(backend.snapshot())
    worker.finish()
    sampler.sample(backend.snapshot(), only_missing=True)
    overview = Overview(backend, previews=cache.images)
    overview.open()
    assert overview.previews[101] is cache.images[101]
    worker.finish()
    sampler.sample(backend.snapshot(), only_missing=True)
    assert worker.requests == [101, 102]
    overview.close()
    assert len(cache.images) == 2
    cache.clear()
    assert not overview.previews


def test_static_images_back_off_and_changes_restore_short_interval():
    backend, cache, worker, sampler, now, _ = make_sampler()
    backend.remove_window(102)
    sampler.sample(backend.snapshot())
    for interval in (1.5, 3, 6, 12, 12):
        worker.finish(image())
        sampler.sample(backend.snapshot())
        assert sampler._schedule[101][2] == interval
        count = len(worker.requests)
        now[0] += interval - 0.01
        sampler.sample(backend.snapshot())
        assert len(worker.requests) == count
        now[0] += 0.02
        sampler.sample(backend.snapshot())
        assert len(worker.requests) == count + 1
    worker.finish(image(99))
    sampler.sample(backend.snapshot())
    assert cache.images[101] == image(99)
    assert sampler._schedule[101][2] == 1.5
    assert sampler.capture_ms == 85.0


def test_failed_capture_backs_off_without_losing_last_image():
    backend, cache, worker, sampler, now, _ = make_sampler()
    backend.remove_window(102)
    sampler.sample(backend.snapshot())
    worker.finish(image())
    sampler.sample(backend.snapshot())
    now[0] = 2
    sampler.sample(backend.snapshot())
    worker.result = (None, 0.0)
    sampler.sample(backend.snapshot())
    assert cache.images[101] == image()
    assert sampler._schedule[101][2] == 3.0
    sampler.cancel()
    assert not sampler._schedule
    sampler.sample(backend.snapshot())
    assert worker.pending == 101


def test_cache_size_remains_bounded_with_many_windows():
    cache = RamPreviewCache(max_bytes=192)
    for i in range(100):
        cache.put(i, object(), image(i))
        assert cache.bytes_used <= 192
    assert len(cache.images) == 32
    # Window objects and titles are not kept in the image mapping.
    assert all(not isinstance(v, Window) for v in cache.images.values())
