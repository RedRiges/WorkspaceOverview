"""The mock must obey the same action contract as a real adapter."""

import pytest

from workspace_overview.backends.mock import Action, MockBackend
from workspace_overview.core.backend import BackendError


def test_move_active_window_keeps_desktop_and_clears_focus():
    backend = MockBackend.demo()
    before = backend.snapshot()
    backend.move_window(101, 30)
    after = backend.snapshot()
    assert after.active_workspace_id == 10
    assert after.active_window_id is None
    assert after.window(101).workspace_id == 30
    assert before.window(101).workspace_id == 10
    assert backend.actions == [Action("move", 101, 30)]


def test_activation_switches_workspace_and_restores_minimized_window():
    backend = MockBackend.demo()
    backend.activate_window(202)
    assert backend.snapshot().active_workspace_id == 20
    assert backend.snapshot().active_window_id == 202
    assert not backend.snapshot().window(202).minimized


@pytest.mark.parametrize("window,workspace", [(999, 20), (101, 999)])
def test_invalid_move_cannot_partially_change_state(window, workspace):
    backend = MockBackend.demo()
    before = backend.snapshot()
    with pytest.raises(BackendError):
        backend.move_window(window, workspace)
    assert backend.snapshot() == before
    assert not backend.actions


def test_failure_is_one_shot_and_does_not_change_state():
    backend = MockBackend.demo()
    before = backend.snapshot()
    backend.fail_next("activate", "Activation denied")
    with pytest.raises(BackendError, match="Activation denied"):
        backend.activate_window(102)
    assert backend.snapshot() == before
    backend.activate_window(102)
    assert backend.snapshot().active_window_id == 102


def test_synthetic_images_and_missing_preview():
    backend = MockBackend.demo()
    preview = backend.capture_preview(101)
    assert len(preview.pixels) == preview.width * preview.height * 3
    assert preview == backend.capture_preview(101)
    assert preview != backend.capture_preview(102)
    assert backend.capture_preview(202) is None
    backend.remove_window(101)
    with pytest.raises(BackendError):
        backend.capture_preview(101)
