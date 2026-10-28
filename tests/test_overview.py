"""User workflows and changes that race with commands."""

from dataclasses import replace

import pytest

from workspace_overview.backends.mock import Action, MockBackend
from workspace_overview.core.models import Snapshot, Window
from workspace_overview.core.navigation import Direction
from workspace_overview.core.overview import Overview


@pytest.fixture
def session():
    backend = MockBackend.demo()
    overview = Overview(backend)
    assert overview.open()
    return backend, overview


def test_open_includes_minimized_and_fullscreen_windows(session):
    backend, overview = session
    assert overview.state.selected_workspace_id == 10
    assert overview.state.selected_window_id == 101
    assert overview.state.snapshot.window(102).fullscreen
    assert overview.state.snapshot.window(202).minimized
    assert set(overview.previews) == {101, 102, 201, 202}
    assert overview.previews[202] is None
    assert not backend.actions


def test_navigation_never_activates_or_moves_windows(session):
    backend, overview = session
    before = backend.snapshot()
    assert overview.navigate(Direction.RIGHT, columns=2)
    assert overview.state.selected_window_id == 102
    assert overview.cycle_workspace()
    assert overview.state.selected_window_id == 201
    assert overview.cycle_workspace()
    assert overview.state.selected_workspace_id == 30
    assert overview.state.selected_window_id is None
    assert not overview.navigate(Direction.DOWN, columns=2)
    assert overview.cycle_workspace()
    assert overview.state.selected_workspace_id == 10
    assert overview.cycle_workspace(-1)
    assert overview.state.selected_workspace_id == 30
    assert overview.select_window(202)
    assert backend.snapshot() == before
    assert not backend.actions


def test_move_is_confirmed_and_keeps_overview_open_on_original_active_desktop(session):
    backend, overview = session
    overview.select_window(102)
    assert overview.begin_move()
    assert overview.navigate(Direction.RIGHT, columns=3)
    assert overview.navigate(Direction.RIGHT, columns=3)
    assert overview.state.move.destination_workspace_id == 30
    assert not overview.cycle_workspace()
    assert not overview.select_window(201)
    assert not overview.activate_selected()
    assert backend.snapshot().window(102).workspace_id == 10
    assert not backend.actions
    assert overview.enter()
    assert backend.actions == [Action("move", 102, 30)]
    assert overview.state.snapshot.window(102).workspace_id == 30
    assert overview.state.snapshot.active_workspace_id == 10
    assert overview.state.selected_workspace_id == 30
    assert overview.state.selected_window_id == 102
    assert overview.state.move is None
    assert overview.state.is_open


def test_escape_cancels_move_before_closing(session):
    backend, overview = session
    overview.begin_move()
    overview.select_destination(30)
    overview.escape()
    assert overview.state.move is None
    assert overview.state.is_open
    assert overview.state.selected_window_id == 101
    overview.escape()
    assert not overview.state.is_open
    assert not overview.previews
    assert not backend.actions


def test_activate_minimized_window_on_other_desktop_closes_overview(session):
    backend, overview = session
    overview.select_window(202)
    assert overview.enter()
    assert not overview.state.is_open
    assert not overview.previews
    assert overview.state.snapshot.active_workspace_id == 20
    assert overview.state.snapshot.active_window_id == 202
    assert not backend.snapshot().window(202).minimized


def test_failed_move_keeps_mode_for_retry(session):
    backend, overview = session
    overview.begin_move()
    overview.select_destination(20)
    backend.fail_next("move", "Window manager refused")
    assert not overview.confirm_move()
    assert overview.state.error == "Window manager refused"
    assert overview.state.move is not None
    assert overview.state.is_open
    assert backend.snapshot().window(101).workspace_id == 10
    assert overview.confirm_move()
    assert overview.state.error is None


def test_failed_activation_keeps_overview_open(session):
    backend, overview = session
    overview.select_window(102)
    backend.fail_next("activate", "Focus refused")
    assert not overview.activate_selected()
    assert overview.state.is_open
    assert overview.state.error == "Focus refused"
    assert backend.snapshot().active_window_id == 101


@pytest.mark.parametrize("command", ["activate_selected", "begin_move"])
def test_disappearing_selection_never_operates_on_fallback_window(session, command):
    backend, overview = session
    backend.remove_window(101)
    assert not getattr(overview, command)()
    assert overview.state.selected_window_id == 102
    assert overview.state.error == "The selected window no longer exists"
    assert not backend.actions


def test_disappearing_move_source_cancels_pending_action(session):
    backend, overview = session
    overview.begin_move()
    overview.select_destination(20)
    backend.remove_window(101)
    assert not overview.confirm_move()
    assert overview.state.move is None
    assert overview.state.error == "The window being moved no longer exists"
    assert not backend.actions


def test_removed_destination_cancels_move_without_using_its_old_index(session):
    backend, overview = session
    overview.begin_move()
    overview.select_destination(30)
    snapshot = backend.snapshot()
    backend.set_snapshot(replace(snapshot, workspaces=snapshot.workspaces[:2]))
    assert not overview.confirm_move()
    assert overview.state.move is None
    assert overview.state.error == "The destination workspace no longer exists"
    assert not backend.actions


def test_external_move_cancels_stale_move_request(session):
    backend, overview = session
    overview.begin_move()
    overview.select_destination(30)
    backend.move_window(101, 20)
    assert not overview.confirm_move()
    assert overview.state.move is None
    assert "externally" in overview.state.error
    assert backend.actions == [Action("move", 101, 20)]


def test_refresh_preserves_selection_and_captures_only_new_windows(session):
    backend, overview = session
    overview.select_window(102)
    preview = overview.previews[102]
    backend.add_window(Window(103, 10, "New window"))
    overview.refresh()
    overview.refresh()
    assert overview.state.selected_window_id == 102
    assert overview.previews[102] is preview
    assert backend.capture_requests == [101, 102, 201, 202, 103]
    backend.remove_window(102)
    overview.refresh()
    assert 102 not in overview.previews
    assert overview.state.selected_window_id == 101


def test_external_activation_updates_active_desktop_without_changing_selection(session):
    backend, overview = session
    backend.activate_window(201)
    overview.refresh()
    assert overview.state.snapshot.active_workspace_id == 20
    assert overview.state.selected_workspace_id == 10
    assert overview.state.selected_window_id == 101


def test_workspace_removal_falls_back_to_active_workspace(session):
    backend, overview = session
    overview.select_workspace(30)
    snapshot = backend.snapshot()
    backend.set_snapshot(replace(snapshot, workspaces=snapshot.workspaces[:2]))
    overview.refresh()
    assert overview.state.selected_workspace_id == 10
    assert overview.state.selected_window_id == 101


def test_session_becoming_empty_clears_selection_move_and_previews(session):
    backend, overview = session
    overview.begin_move()
    backend.set_snapshot(Snapshot())
    overview.refresh()
    assert overview.state.selected_workspace_id is None
    assert overview.state.selected_window_id is None
    assert overview.state.move is None
    assert not overview.previews
    assert not overview.enter()


def test_preview_failure_is_fallback_and_is_retried_only_after_reopening():
    backend = MockBackend.demo()
    backend.fail_next("preview")
    overview = Overview(backend)
    assert overview.open()
    assert overview.previews[101] is None
    assert overview.previews[102] is not None
    assert overview.state.error is None
    overview.open()
    overview.refresh()
    assert backend.capture_requests.count(101) == 1
    overview.toggle()
    assert not overview.previews
    overview.toggle()
    assert overview.previews[101] is not None
    assert backend.capture_requests.count(101) == 2


def test_failed_refresh_keeps_last_snapshot_and_selection(session):
    backend, overview = session
    before = overview.state
    backend.fail_next("snapshot", "Display unavailable")
    assert not overview.refresh()
    assert overview.state.snapshot == before.snapshot
    assert overview.state.selected_window_id == before.selected_window_id
    assert overview.state.error == "Display unavailable"


def test_failed_open_can_be_retried():
    backend = MockBackend.demo()
    backend.fail_next("snapshot", "Display unavailable")
    overview = Overview(backend)
    assert not overview.open()
    assert not overview.state.is_open
    assert not overview.previews
    assert overview.open()
    assert overview.state.error is None


def test_empty_session_and_closed_commands_are_safe():
    backend = MockBackend()
    overview = Overview(backend)
    assert not overview.cycle_workspace()
    assert not overview.navigate(Direction.LEFT, columns=2)
    assert not overview.begin_move()
    assert not overview.enter()
    assert not overview.refresh()
    overview.open()
    assert not overview.select_workspace(10)
    assert not overview.select_window(1)
    assert not overview.select_destination(10)
    assert not overview.cycle_workspace()
    assert not overview.begin_move()
    assert not overview.enter()
    overview.escape()
    assert not overview.state.is_open
    assert not backend.actions


class IgnoringBackend(MockBackend):
    """A window manager may accept a request without doing what was requested."""

    def activate_window(self, window_id: int) -> None:
        pass

    def move_window(self, window_id: int, workspace_id: int) -> None:
        pass


@pytest.mark.parametrize("action", ["move", "activate"])
def test_actions_require_confirmation_from_fresh_snapshot(action):
    backend = IgnoringBackend(MockBackend.demo().snapshot())
    overview = Overview(backend)
    overview.open()
    overview.select_window(102)
    if action == "move":
        overview.begin_move()
        overview.select_destination(30)
        assert not overview.confirm_move()
    else:
        assert not overview.activate_selected()
    assert "did not confirm" in overview.state.error
    assert overview.state.is_open


def test_unexpected_workspace_switch_is_reported():
    class SwitchingBackend(MockBackend):
        def move_window(self, window_id, workspace_id):
            super().move_window(window_id, workspace_id)
            self.activate_window(window_id)

    backend = SwitchingBackend(MockBackend.demo().snapshot())
    overview = Overview(backend)
    overview.open()
    overview.begin_move()
    overview.select_destination(30)
    assert not overview.confirm_move()
    assert "unexpectedly switched" in overview.state.error
    assert overview.state.snapshot.active_workspace_id == 30
    assert overview.state.is_open


def test_snapshot_failure_after_action_never_reports_success():
    class UnreadableAfterActivation(MockBackend):
        def activate_window(self, window_id):
            super().activate_window(window_id)
            self.fail_next("snapshot", "Display lost after request")

    backend = UnreadableAfterActivation(MockBackend.demo().snapshot())
    overview = Overview(backend)
    overview.open()
    overview.select_window(102)
    assert not overview.activate_selected()
    assert overview.state.error == "Display lost after request"
    assert overview.state.is_open
    assert overview.refresh()
    assert overview.state.snapshot.active_window_id == 102


def test_reordering_preserves_selected_window_and_move_destination(session):
    backend, overview = session
    overview.select_window(102)
    overview.begin_move()
    overview.select_destination(30)
    snapshot = backend.snapshot()
    backend.set_snapshot(
        replace(
            snapshot,
            workspaces=tuple(reversed(snapshot.workspaces)),
            windows=tuple(reversed(snapshot.windows)),
        )
    )
    overview.refresh()
    assert overview.state.selected_window_id == 102
    assert overview.state.move.destination_workspace_id == 30
    assert overview.confirm_move()
    assert backend.snapshot().window(102).workspace_id == 30


def test_invalid_destination_does_not_replace_valid_pending_move(session):
    backend, overview = session
    overview.begin_move()
    overview.select_destination(20)
    assert not overview.select_destination(999)
    assert overview.state.move.destination_workspace_id == 20
    assert not backend.actions


def test_move_to_same_workspace_finishes_without_changing_session(session):
    backend, overview = session
    before = backend.snapshot()
    overview.begin_move()
    assert overview.confirm_move()
    assert overview.state.move is None
    assert overview.state.is_open
    assert backend.snapshot() == before


def test_preview_cache_cannot_be_changed_by_consumers(session):
    _, overview = session
    previews = overview.previews
    with pytest.raises(TypeError):
        previews[101] = None
    overview.close()
    assert not previews


def test_window_disappearing_inside_action_is_reported_and_reconciled():
    class VanishingBackend(MockBackend):
        def activate_window(self, window_id):
            self.remove_window(window_id)
            super().activate_window(window_id)

    backend = VanishingBackend(MockBackend.demo().snapshot())
    overview = Overview(backend)
    overview.open()
    assert not overview.activate_selected()
    assert overview.state.selected_window_id == 102
    assert overview.state.snapshot.window(101) is None
    assert overview.state.error == "Window 101 no longer exists"
    assert overview.state.is_open
    assert not backend.actions


def test_pinned_windows_require_explicit_unpinning_before_move(session):
    backend, overview = session
    snapshot = backend.snapshot()
    backend.set_snapshot(
        replace(
            snapshot,
            windows=tuple(
                replace(w, pinned=True) if w.id == 101 else w for w in snapshot.windows
            ),
        )
    )
    assert not overview.begin_move()
    assert overview.state.move is None
    assert "Unpin" in overview.state.error
    assert not backend.actions


def test_error_survives_passive_ui_refresh_until_user_changes_selection(session):
    backend, overview = session
    backend.fail_next("activate", "Focus refused")
    assert not overview.activate_selected()
    overview.refresh()
    assert overview.state.error == "Focus refused"
    overview.select_window(102)
    assert overview.state.error is None
