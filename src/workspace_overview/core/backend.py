"""Contract implemented by in-memory and future X11 adapters."""

from typing import Protocol

from workspace_overview.core.models import Preview, Snapshot


class BackendError(RuntimeError):
    """An expected adapter failure that the overview can present to the user."""


class Backend(Protocol):
    """Synchronous boundary; all operations are called on the owning thread.

    Mutating methods return once the adapter can provide a refreshed snapshot.
    A future asynchronous X11 adapter must settle its requests with a bounded
    timeout before returning, or expose a separate pending-operation API.
    Expected failures raise BackendError; they never imply confirmed success.
    """

    def snapshot(self) -> Snapshot: ...

    def activate_window(self, window_id: int) -> None:
        """Activate/unminimize a window, switching workspace if necessary."""
        ...

    def move_window(self, window_id: int, workspace_id: int) -> None:
        """Move without switching the active workspace or activating a window."""
        ...

    def capture_preview(self, window_id: int) -> Preview | None:
        """Capture once; None or BackendError means use the icon/title fallback."""
        ...
