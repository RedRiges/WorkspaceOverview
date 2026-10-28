"""Real window discovery and bounded EWMH operations through libwnck."""

import time
from collections.abc import Callable

from workspace_overview.core.backend import BackendError
from workspace_overview.core.models import Snapshot, Window, Workspace


class X11Backend:
    def __init__(
        self,
        screen,
        *,
        window_types: set,
        pump: Callable[[], None],
        timestamp: Callable[[], int],
        previews=None,
        timeout: float = 1.5,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self.screen = screen
        self._types = window_types
        self._pump = pump
        self._timestamp = timestamp
        self._previews = previews
        self._timeout = timeout
        self._clock = clock
        self._sleep = sleep
        self.excluded_xids: set[int] = set()
        # Wnck desktop numbers shift when a desktop is removed. GObject identity
        # remains stable for live workspaces, so expose our own monotonically
        # increasing IDs to the core and never retarget a pending move by index.
        self._workspace_ids: dict[object, int] = {}
        self._next_workspace_id = 0

    def _update(self) -> None:
        self._pump()
        self.screen.force_update()

    def _workspaces(self) -> dict:
        # Do not depend on libwnck's enumeration order: Tab and the visual grid
        # both follow Xfce's desktop numbers, while IDs still track identity.
        workspaces = sorted(self.screen.get_workspaces(), key=lambda w: w.get_number())
        live = set(workspaces)
        self._workspace_ids = {
            w: key for w, key in self._workspace_ids.items() if w in live
        }
        for workspace in workspaces:
            if workspace not in self._workspace_ids:
                self._workspace_ids[workspace] = self._next_workspace_id
                self._next_workspace_id += 1
        return {self._workspace_ids[w]: w for w in workspaces}

    def _windows(self) -> list:
        return [
            w
            for w in self.screen.get_windows()
            if w.get_xid() not in self.excluded_xids
            and w.get_window_type() in self._types
        ]

    def _window(self, window_id: int):
        window = next((w for w in self._windows() if w.get_xid() == window_id), None)
        if window is None:
            raise BackendError("The requested window no longer exists")
        return window

    def snapshot(self) -> Snapshot:
        self._update()
        spaces = self._workspaces()
        active_space = self.screen.get_active_workspace()
        active_id = self._workspace_ids.get(active_space)
        if not spaces or active_id is None:
            raise BackendError("The window manager has not reported its workspaces")
        windows = []
        for w in sorted(self._windows(), key=lambda w: w.get_xid()):
            pinned = w.is_pinned()
            workspace_id = (
                active_id if pinned else self._workspace_ids.get(w.get_workspace())
            )
            if workspace_id is None:  # A window in the middle of closing/mapping.
                continue
            windows.append(
                Window(
                    id=w.get_xid(),
                    workspace_id=workspace_id,
                    title=w.get_name() or "Untitled window",
                    minimized=w.is_minimized(),
                    fullscreen=w.is_fullscreen(),
                    pinned=pinned,
                    maximized=w.is_maximized(),
                )
            )
        active = self.screen.get_active_window()
        active_xid = active.get_xid() if active is not None else None
        # Our overlay, panels, and transiently stale WM focus are not model windows.
        active_xid = next(
            (
                w.id
                for w in windows
                if w.id == active_xid
                and w.workspace_id == active_id
                and not w.minimized
            ),
            None,
        )
        return Snapshot(
            workspaces=tuple(
                Workspace(key, w.get_name() or f"Workspace {w.get_number() + 1}")
                for key, w in spaces.items()
            ),
            windows=tuple(windows),
            active_workspace_id=active_id,
            active_window_id=active_xid,
        )

    def _wait(self, predicate: Callable[[], bool], message: str) -> None:
        deadline = self._clock() + self._timeout
        while True:
            self._update()
            if predicate():
                return
            if self._clock() >= deadline:
                raise BackendError(message)
            self._sleep(0.01)

    def activate_window(self, window_id: int) -> None:
        self._update()
        window = self._window(window_id)
        timestamp = self._timestamp()
        if not timestamp:
            raise BackendError("No X server event timestamp is available; try again")
        workspace = window.get_workspace()
        if not window.is_pinned() and workspace is not None:
            if workspace != self.screen.get_active_workspace():
                workspace.activate(timestamp)
                self._wait(
                    lambda: self.screen.get_active_workspace() == workspace,
                    "The window manager refused to switch workspace",
                )
        window = self._window(window_id)
        if window.is_minimized():
            window.unminimize(timestamp)
        window.activate(timestamp)

        def activated() -> bool:
            current = self._window(window_id)
            active = self.screen.get_active_window()
            return (
                active is not None
                and active.get_xid() == window_id
                and not current.is_minimized()
            )

        self._wait(activated, "The window manager refused window activation")

    def move_window(self, window_id: int, workspace_id: int) -> None:
        self._update()
        spaces = self._workspaces()
        destination = spaces.get(workspace_id)
        if destination is None:
            raise BackendError("The destination workspace no longer exists")
        window = self._window(window_id)
        if window.is_pinned():
            raise BackendError(
                "Unpin this window in the window manager before moving it"
            )
        previous_active = self.screen.get_active_workspace()
        if window.get_workspace() != destination:
            window.move_to_workspace(destination)
            self._wait(
                lambda: self._window(window_id).get_workspace() == destination,
                "The window manager refused to move this window",
            )
        if self.screen.get_active_workspace() != previous_active:
            raise BackendError("The active workspace changed while moving the window")

    def capture_preview(self, window_id: int):
        self._window(window_id)
        return self._previews.capture(window_id) if self._previews else None

    def preview_identity(self, window_id: int):
        """Native object identity prevents thumbnails surviving XID reuse."""
        return self._window(window_id)

    def icon(self, window_id: int):
        return self._window(window_id).get_icon()

    def close(self) -> None:
        if self._previews:
            self._previews.close()


def create_backend(native, timestamp, *, previews=True) -> X11Backend:
    from workspace_overview.native import drain_events
    from workspace_overview.previews.xcomposite import CompositeCapture

    handle = native.Wnck.Handle.new(native.Wnck.ClientType.PAGER)
    screen = handle.get_default_screen()
    if screen is None:
        raise BackendError("libwnck cannot connect to the current X11 screen")
    capture = CompositeCapture() if previews else None
    backend = X11Backend(
        screen,
        window_types={native.Wnck.WindowType.NORMAL, native.Wnck.WindowType.DIALOG},
        pump=lambda: drain_events(native),
        timestamp=timestamp,
        previews=capture,
    )
    backend.handle = handle  # Keep its owned screen/window objects alive.
    backend.preview_status = capture.status if capture else "disabled by --no-previews"
    return backend
