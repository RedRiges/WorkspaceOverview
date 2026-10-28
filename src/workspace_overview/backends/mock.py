"""Deterministic in-memory backend. Never accesses real windows or files."""

from dataclasses import dataclass, replace
from typing import Literal, Self

from workspace_overview.core.backend import BackendError
from workspace_overview.core.models import Preview, Snapshot, Window, Workspace

type Operation = Literal["snapshot", "activate", "move", "preview"]


@dataclass(frozen=True, slots=True)
class Action:
    operation: Literal["activate", "move"]
    window_id: int
    workspace_id: int | None = None


class MockBackend:
    def __init__(
        self,
        snapshot: Snapshot | None = None,
        *,
        unavailable_previews: frozenset[int] = frozenset(),
    ) -> None:
        self._snapshot = snapshot if snapshot is not None else Snapshot()
        self.unavailable_previews = unavailable_previews
        self.actions: list[Action] = []
        self.capture_requests: list[int] = []
        self._failures: dict[Operation, str] = {}

    @classmethod
    def demo(cls) -> Self:
        return cls(
            Snapshot(
                workspaces=(
                    Workspace(10, "Work"),
                    Workspace(20, "Reference"),
                    Workspace(30, "Empty"),
                ),
                windows=(
                    Window(101, 10, "Terminal", "utilities-terminal"),
                    Window(102, 10, "Browser", "web-browser", fullscreen=True),
                    Window(201, 20, "Editor", "text-editor"),
                    Window(202, 20, "Notes", "text-editor", minimized=True),
                ),
                active_workspace_id=10,
                active_window_id=101,
            ),
            unavailable_previews=frozenset({202}),
        )

    def fail_next(
        self, operation: Operation, message: str = "Simulated failure"
    ) -> None:
        """Fail the next matching call, then resume normal operation."""
        if operation not in {"snapshot", "activate", "move", "preview"}:
            raise ValueError("Unknown mock operation")
        self._failures[operation] = message

    def _check_failure(self, operation: Operation) -> None:
        message = self._failures.pop(operation, None)
        if message is not None:
            raise BackendError(message)

    def _window(self, window_id: int) -> Window:
        window = self._snapshot.window(window_id)
        if window is None:
            raise BackendError(f"Window {window_id} no longer exists")
        return window

    def snapshot(self) -> Snapshot:
        self._check_failure("snapshot")
        return self._snapshot

    def set_snapshot(self, snapshot: Snapshot) -> None:
        """Simulate external changes, including workspace removal/reordering."""
        self._snapshot = snapshot

    def add_window(self, window: Window) -> None:
        self._snapshot = replace(
            self._snapshot, windows=(*self._snapshot.windows, window)
        )

    def remove_window(self, window_id: int) -> None:
        self._window(window_id)
        active = self._snapshot.active_window_id
        self._snapshot = replace(
            self._snapshot,
            windows=tuple(w for w in self._snapshot.windows if w.id != window_id),
            active_window_id=None if active == window_id else active,
        )

    def activate_window(self, window_id: int) -> None:
        self._check_failure("activate")
        window = self._window(window_id)
        self._snapshot = replace(
            self._snapshot,
            windows=tuple(
                replace(w, minimized=False) if w.id == window_id else w
                for w in self._snapshot.windows
            ),
            active_workspace_id=window.workspace_id,
            active_window_id=window_id,
        )
        self.actions.append(Action("activate", window_id))

    def move_window(self, window_id: int, workspace_id: int) -> None:
        self._check_failure("move")
        self._window(window_id)
        if not any(w.id == workspace_id for w in self._snapshot.workspaces):
            raise BackendError(f"Workspace {workspace_id} no longer exists")
        active = self._snapshot.active_window_id
        if active == window_id and workspace_id != self._snapshot.active_workspace_id:
            active = None
        self._snapshot = replace(
            self._snapshot,
            windows=tuple(
                replace(w, workspace_id=workspace_id) if w.id == window_id else w
                for w in self._snapshot.windows
            ),
            active_window_id=active,
        )
        self.actions.append(Action("move", window_id, workspace_id))

    def capture_preview(self, window_id: int) -> Preview | None:
        self.capture_requests.append(window_id)
        self._check_failure("preview")
        self._window(window_id)
        if window_id in self.unavailable_previews:
            return None
        # Small synthetic RGB checkerboard, with a stable color per window ID.
        width, height = 96, 60
        color = tuple((window_id * factor) % 192 + 32 for factor in (31, 67, 97))
        pixels = bytearray()
        for y in range(height):
            for x in range(width):
                shade = 1 if (x // 12 + y // 12) % 2 else 2
                pixels.extend(channel // shade for channel in color)
        return Preview(width, height, bytes(pixels))
