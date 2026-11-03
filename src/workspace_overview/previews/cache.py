"""Bounded RGB thumbnails in process memory; no files or window mutations."""

import time
from collections import OrderedDict
from types import MappingProxyType

from workspace_overview.core.backend import BackendError
from workspace_overview.core.models import Preview


class RamPreviewCache:
    def __init__(self, max_bytes: int = 16 * 1024 * 1024):
        if max_bytes < 1:
            raise ValueError("Cache size must be positive")
        self.max_bytes = max_bytes
        self.bytes_used = 0
        self.revision = 0
        self.epoch = 0
        self._images: OrderedDict[int, Preview] = OrderedDict()
        self._identities: dict[int, object] = {}
        self.images = MappingProxyType(self._images)

    def remove(self, window_id: int):
        image = self._images.pop(window_id, None)
        self._identities.pop(window_id, None)
        if image is not None:
            self.bytes_used -= len(image.pixels)
            self.revision += 1

    def reconcile(self, identities: dict[int, object]):
        for window_id, identity in tuple(self._identities.items()):
            if identities.get(window_id) != identity:
                self.remove(window_id)

    def put(self, window_id: int, identity: object, image: Preview):
        size = len(image.pixels)
        if size > self.max_bytes:
            return
        if self._identities.get(window_id) == identity:
            if self._images.get(window_id) == image:
                self._images.move_to_end(window_id)
                return
        self.remove(window_id)
        while self.bytes_used + size > self.max_bytes:
            self.remove(next(iter(self._images)))
        self._images[window_id] = image
        self._identities[window_id] = identity
        self.bytes_used += size
        self.revision += 1

    def clear(self):
        self._images.clear()
        self._identities.clear()
        self.bytes_used = 0
        self.revision += 1
        self.epoch += 1  # Invalidate any capture interrupted by a clear/lock request.


class PreviewSampler:
    """Schedule one capture in a separate process, with bounded per-window backoff."""

    def __init__(self, backend, cache, permitted, *, worker, clock=time.monotonic):
        self.backend = backend
        self.cache = cache
        self.permitted = permitted
        self.worker = worker
        self.clock = clock
        self._pending = None
        self._schedule = {}
        self.capture_ms = 0.0
        self.capture_max_ms = 0.0
        self.captures = 0

    def reconcile(self, snapshot):
        identities = {}
        for window in snapshot.windows:
            try:
                identities[window.id] = self.backend.preview_identity(window.id)
            except BackendError:
                pass
        self.cache.reconcile(identities)
        for window_id, (identity, _, _) in tuple(self._schedule.items()):
            if identities.get(window_id) != identity:
                del self._schedule[window_id]
        return identities

    def cancel(self):
        self.worker.cancel()
        self._pending = None
        self._schedule.clear()

    def close(self):
        self.cancel()
        self.worker.close()

    def _collect(self, identities, only_missing):
        if self._pending is None:
            return
        result = self.worker.poll()
        if result is None:
            return
        window_id, identity, epoch = self._pending
        self._pending = None
        image, duration = result
        self.capture_ms = duration
        self.capture_max_ms = max(self.capture_max_ms, duration)
        self.captures += 1
        if (
            not self.permitted()
            or self.cache.epoch != epoch
            or identities.get(window_id) != identity
        ):
            return
        previous = self.cache.images.get(window_id)
        interval = self._schedule.get(window_id, (None, 0, 1.5))[2]
        if image is None or image == previous:
            interval = min(12.0, interval * 2)
        else:
            interval = 1.5
        self._schedule[window_id] = (identity, self.clock() + interval, interval)
        if image is not None and (not only_missing or previous is None):
            self.cache.put(window_id, identity, image)

    def sample(self, snapshot, *, only_missing=False):
        identities = self.reconcile(snapshot)
        if not self.permitted():
            self.cancel()
            return
        self._collect(identities, only_missing)
        if self._pending is not None:
            return
        now = self.clock()
        candidates = [
            w.id
            for w in snapshot.windows
            if w.workspace_id == snapshot.active_workspace_id
            and not w.minimized
            and w.id in identities
            and (not only_missing or w.id not in self.cache.images)
            and self._schedule.get(w.id, (None, 0, 0))[1] <= now
        ]
        if not candidates:
            return
        # Oldest due window first; unseen windows get a first image promptly.
        window_id = min(
            candidates, key=lambda wid: self._schedule.get(wid, (None, 0, 0))[1]
        )
        if self.worker.submit(window_id):
            self._pending = (window_id, identities[window_id], self.cache.epoch)
