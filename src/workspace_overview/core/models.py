"""Immutable snapshots supplied by window-system adapters."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Workspace:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class Window:
    id: int
    workspace_id: int
    title: str
    icon_name: str = "application-x-executable"
    minimized: bool = False
    fullscreen: bool = False


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Ordered workspaces and normal windows from one display session.

    IDs remain stable during an object's lifetime; tuple order defines navigation
    order. Hidden, minimized and fullscreen normal windows belong in this list.
    """

    workspaces: tuple[Workspace, ...] = ()
    windows: tuple[Window, ...] = ()
    active_workspace_id: int | None = None
    active_window_id: int | None = None

    def __post_init__(self) -> None:
        # Accept sequences at adapter boundaries but retain immutable collections.
        object.__setattr__(self, "workspaces", tuple(self.workspaces))
        object.__setattr__(self, "windows", tuple(self.windows))
        workspace_ids = {workspace.id for workspace in self.workspaces}
        window_ids = {window.id for window in self.windows}
        if len(workspace_ids) != len(self.workspaces):
            raise ValueError("Workspace IDs must be unique")
        if len(window_ids) != len(self.windows):
            raise ValueError("Window IDs must be unique")
        if any(window.workspace_id not in workspace_ids for window in self.windows):
            raise ValueError("Every window must belong to an existing workspace")
        if self.workspaces:
            if self.active_workspace_id not in workspace_ids:
                raise ValueError("The active workspace must exist")
        elif self.active_workspace_id is not None:
            raise ValueError("An empty session cannot have an active workspace")
        if self.active_window_id is not None:
            active = self.window(self.active_window_id)
            if active is None or active.workspace_id != self.active_workspace_id:
                raise ValueError("The active window must be on the active workspace")
            if active.minimized:
                raise ValueError("The active window cannot be minimized")

    def window(self, window_id: int | None) -> Window | None:
        return next((window for window in self.windows if window.id == window_id), None)

    def windows_on(self, workspace_id: int | None) -> tuple[Window, ...]:
        return tuple(w for w in self.windows if w.workspace_id == workspace_id)


@dataclass(frozen=True, slots=True)
class Preview:
    """Packed RGB8 image in memory: three bytes per pixel, no row padding."""

    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "pixels", bytes(self.pixels))
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Preview dimensions must be positive")
        if len(self.pixels) != self.width * self.height * 3:
            raise ValueError("Preview data does not match its dimensions")
