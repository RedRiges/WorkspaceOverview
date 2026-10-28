"""Overview workflow independent of rendering and the window system."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from workspace_overview.core.backend import Backend, BackendError
from workspace_overview.core.models import Preview, Snapshot
from workspace_overview.core.navigation import Direction, grid_entry, grid_neighbor


@dataclass(frozen=True, slots=True)
class Move:
    window_id: int
    source_workspace_id: int
    destination_workspace_id: int


@dataclass(frozen=True, slots=True)
class OverviewState:
    snapshot: Snapshot = Snapshot()
    is_open: bool = False
    selected_workspace_id: int | None = None
    selected_window_id: int | None = None
    move: Move | None = None
    error: str | None = None


class Overview:
    """Selection is local; only activate/confirm_move mutate the backend.

    Call refresh on adapter notifications (or from a UI timer). Commands return
    False on missing selection, invalid mode, or an expected backend failure.
    Errors requiring explanation are available in state.error.
    """

    def __init__(
        self, backend: Backend, *, previews: Mapping[int, Preview] | None = None
    ) -> None:
        self._backend = backend
        self._state = OverviewState()
        self._previews: dict[int, Preview | None] = {}
        self._shared_previews = previews

    @property
    def state(self) -> OverviewState:
        return self._state

    @property
    def previews(self) -> Mapping[int, Preview | None]:
        if self._shared_previews is not None:
            return self._shared_previews
        return MappingProxyType(self._previews)

    def _error(self, message: str) -> bool:
        self._state = replace(self._state, error=message)
        return False

    @staticmethod
    def _initial_window(snapshot: Snapshot, workspace_id: int | None) -> int | None:
        windows = snapshot.windows_on(workspace_id)
        if any(w.id == snapshot.active_window_id for w in windows):
            return snapshot.active_window_id
        return windows[0].id if windows else None

    def _capture_new_previews(self) -> None:
        if self._shared_previews is not None:
            return  # Resident sampler owns capture, eviction and lifetime.
        ids = {window.id for window in self.state.snapshot.windows}
        for removed in self._previews.keys() - ids:
            del self._previews[removed]
        for window in self.state.snapshot.windows:
            if window.id not in self._previews:
                try:
                    self._previews[window.id] = self._backend.capture_preview(window.id)
                except BackendError:
                    self._previews[window.id] = None

    def open(self) -> bool:
        if self.state.is_open:
            return self.refresh()
        try:
            snapshot = self._backend.snapshot()
        except BackendError as exc:
            return self._error(str(exc))
        self._state = OverviewState(
            snapshot=snapshot,
            is_open=True,
            selected_workspace_id=snapshot.active_workspace_id,
            selected_window_id=self._initial_window(
                snapshot, snapshot.active_workspace_id
            ),
        )
        self._capture_new_previews()
        return True

    def close(self) -> None:
        self._previews.clear()
        self._state = replace(self.state, is_open=False, move=None, error=None)

    def toggle(self) -> bool:
        if self.state.is_open:
            self.close()
            return True
        return self.open()

    def refresh(self) -> bool:
        if not self.state.is_open:
            return False
        try:
            snapshot = self._backend.snapshot()
        except BackendError as exc:
            return self._error(str(exc))
        workspace_ids = {workspace.id for workspace in snapshot.workspaces}
        workspace_id = self.state.selected_workspace_id
        if workspace_id not in workspace_ids:
            workspace_id = snapshot.active_workspace_id
        window_id = self.state.selected_window_id
        if not any(w.id == window_id for w in snapshot.windows_on(workspace_id)):
            window_id = self._initial_window(snapshot, workspace_id)
        move = self.state.move
        error = self.state.error
        if move is not None:
            move_error = None
            source = snapshot.window(move.window_id)
            if source is None:
                move_error = "The window being moved no longer exists"
            elif source.workspace_id != move.source_workspace_id:
                move_error = (
                    "The window was moved externally; select a destination again"
                )
            elif move.destination_workspace_id not in workspace_ids:
                move_error = "The destination workspace no longer exists"
            if move_error:
                error = move_error
                move = None
        self._state = replace(
            self.state,
            snapshot=snapshot,
            selected_workspace_id=workspace_id,
            selected_window_id=window_id,
            move=move,
            error=error,
        )
        self._capture_new_previews()
        return True

    def select_workspace(self, workspace_id: int) -> bool:
        if not self.state.is_open or self.state.move is not None:
            return False
        if not any(w.id == workspace_id for w in self.state.snapshot.workspaces):
            return False
        if workspace_id != self.state.selected_workspace_id:
            self._state = replace(
                self.state,
                selected_workspace_id=workspace_id,
                selected_window_id=self._initial_window(
                    self.state.snapshot, workspace_id
                ),
                error=None,
            )
        return True

    def cycle_workspace(self, step: int = 1) -> bool:
        """Tab/Shift+Tab wrap in snapshot order, including empty workspaces."""
        if not self.state.is_open or self.state.move is not None:
            return False
        ids = [w.id for w in self.state.snapshot.workspaces]
        if not ids:
            return False
        index = ids.index(self.state.selected_workspace_id)
        return self.select_workspace(ids[(index + step) % len(ids)])

    def select_window(self, window_id: int) -> bool:
        """Select a card, including a card on another workspace; never activate."""
        if not self.state.is_open or self.state.move is not None:
            return False
        window = self.state.snapshot.window(window_id)
        if window is None:
            return False
        self._state = replace(
            self.state,
            selected_workspace_id=window.workspace_id,
            selected_window_id=window.id,
            error=None,
        )
        return True

    def navigate(
        self,
        direction: Direction,
        *,
        columns: int,
        workspace_columns: int | None = None,
    ) -> bool:
        """Arrow key: navigate cards, or destinations while in move mode.

        The UI supplies card columns and workspace columns. At a card edge (or
        on an empty workspace), cross into the neighboring workspace. Omitting
        workspace_columns retains card-only navigation for non-GUI callers.
        """
        if not self.state.is_open:
            return False
        if self.state.move is not None:
            move = self.state.move
            ids = [w.id for w in self.state.snapshot.workspaces]
            index = grid_neighbor(
                ids.index(move.destination_workspace_id),
                len(ids),
                workspace_columns if workspace_columns is not None else columns,
                direction,
            )
            return self.select_destination(ids[index])
        windows = self.state.snapshot.windows_on(self.state.selected_workspace_id)
        source_index = 0
        if windows:
            ids = [w.id for w in windows]
            source_index = ids.index(self.state.selected_window_id)
            index = grid_neighbor(source_index, len(ids), columns, direction)
            if index != source_index or workspace_columns is None:
                return self.select_window(ids[index])
        if workspace_columns is None or self.state.selected_workspace_id is None:
            return False
        workspace_ids = [w.id for w in self.state.snapshot.workspaces]
        source_workspace = workspace_ids.index(self.state.selected_workspace_id)
        destination = grid_neighbor(
            source_workspace, len(workspace_ids), workspace_columns, direction
        )
        if source_workspace == destination:
            return False
        self.select_workspace(workspace_ids[destination])
        targets = self.state.snapshot.windows_on(self.state.selected_workspace_id)
        if targets:
            entry = grid_entry(source_index, len(targets), columns, direction)
            self.select_window(targets[entry].id)
        return True

    def begin_move(self) -> bool:
        if not self.state.is_open or self.state.move is not None:
            return False
        window_id = self.state.selected_window_id
        if window_id is None or not self.refresh():
            return False
        window = self.state.snapshot.window(window_id)
        if window is None:
            return self._error("The selected window no longer exists")
        if window.pinned:
            return self._error(
                "Unpin this window in the window manager before moving it"
            )
        self._state = replace(
            self.state,
            selected_workspace_id=window.workspace_id,
            selected_window_id=window.id,
            move=Move(window.id, window.workspace_id, window.workspace_id),
            error=None,
        )
        return True

    def select_destination(self, workspace_id: int) -> bool:
        if self.state.move is None:
            return False
        if not any(w.id == workspace_id for w in self.state.snapshot.workspaces):
            return False
        self._state = replace(
            self.state,
            move=replace(self.state.move, destination_workspace_id=workspace_id),
            error=None,
        )
        return True

    def _action_failed(self, message: str) -> bool:
        # A failed request may still have partially changed the window system.
        self.refresh()
        return self._error(message)

    def confirm_move(self) -> bool:
        if self.state.move is None or not self.refresh():
            return False
        move = self.state.move
        if move is None:  # refresh can cancel a move after an external change.
            return False
        previous_active = self.state.snapshot.active_workspace_id
        try:
            self._backend.move_window(move.window_id, move.destination_workspace_id)
        except BackendError as exc:
            return self._action_failed(str(exc))
        # The move is no longer pending; don't treat our own change as external.
        self._state = replace(self.state, move=None, error=None)
        if not self.refresh():
            return False
        window = self.state.snapshot.window(move.window_id)
        if window is None or window.workspace_id != move.destination_workspace_id:
            return self._error("The backend did not confirm the requested move")
        if self.state.snapshot.active_workspace_id != previous_active:
            return self._error("The backend unexpectedly switched the active workspace")
        self._state = replace(
            self.state,
            selected_workspace_id=move.destination_workspace_id,
            selected_window_id=move.window_id,
        )
        return True

    def activate_selected(self) -> bool:
        if not self.state.is_open or self.state.move is not None:
            return False
        window_id = self.state.selected_window_id
        if window_id is None or not self.refresh():
            return False
        if self.state.snapshot.window(window_id) is None:
            return self._error("The selected window no longer exists")
        try:
            self._backend.activate_window(window_id)
        except BackendError as exc:
            return self._action_failed(str(exc))
        if not self.refresh():
            return False
        if self.state.snapshot.active_window_id != window_id:
            return self._error("The backend did not confirm window activation")
        self.close()
        return True

    def enter(self) -> bool:
        return self.confirm_move() if self.state.move else self.activate_selected()

    def escape(self) -> None:
        if self.state.move is not None:
            self._state = replace(self.state, move=None, error=None)
        else:
            self.close()
