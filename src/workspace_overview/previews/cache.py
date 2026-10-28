"""Bounded RGB thumbnails in process memory; no files or window mutations."""

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
    """Capture at most one eligible window per tick, preserving hidden images."""

    def __init__(self, backend, cache, permitted, *, after_capture=lambda: None):
        self.backend = backend
        self.cache = cache
        self.permitted = permitted
        self.after_capture = after_capture
        self._cursor = 0

    def reconcile(self, snapshot):
        identities = {}
        for window in snapshot.windows:
            try:
                identities[window.id] = self.backend.preview_identity(window.id)
            except BackendError:
                pass  # Closing/mapping races are discarded, never reused.
        self.cache.reconcile(identities)
        return identities

    def sample(self, snapshot, *, only_missing=False):
        identities = self.reconcile(snapshot)
        if not self.permitted():
            return
        candidates = [
            w.id
            for w in snapshot.windows
            if w.workspace_id == snapshot.active_workspace_id
            and not w.minimized
            and w.id in identities
            and (not only_missing or w.id not in self.cache.images)
        ]
        if not candidates:
            return
        window_id = candidates[self._cursor % len(candidates)]
        self._cursor += 1
        epoch = self.cache.epoch
        try:
            image = self.backend.capture_preview(window_id)
            self.after_capture()
            if (
                image is not None
                and self.permitted()
                and self.cache.epoch == epoch
                and self.backend.preview_identity(window_id) == identities[window_id]
            ):
                self.cache.put(window_id, identities[window_id], image)
        except BackendError:
            pass  # Keep the last successful thumbnail when a capture is unavailable.
