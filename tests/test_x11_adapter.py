"""libwnck adapter contract checks without requiring a display on macOS."""

from dataclasses import dataclass

import pytest

from workspace_overview.backends.x11 import X11Backend
from workspace_overview.core.backend import BackendError


@dataclass(eq=False)
class Space:
    screen: object
    number: int

    def get_name(self):
        return f"Desktop {self.number}"

    def get_number(self):
        return self.number

    def activate(self, timestamp):
        assert timestamp == 123
        self.screen.active_space = self


class NativeWindow:
    def __init__(self, screen, xid, space, *, kind="NORMAL", pinned=False):
        self.screen, self.xid, self.space = screen, xid, space
        self.kind, self.pinned = kind, pinned
        self.minimized, self.fullscreen, self.ignore = False, False, False

    def get_xid(self):
        return self.xid

    def get_window_type(self):
        return self.kind

    def get_workspace(self):
        return self.space

    def is_pinned(self):
        return self.pinned

    def is_minimized(self):
        return self.minimized

    def is_fullscreen(self):
        return self.fullscreen

    def get_name(self):
        return "Window"

    def unminimize(self, timestamp):
        assert timestamp == 123
        if not self.ignore:
            self.minimized = False

    def activate(self, timestamp):
        assert timestamp == 123
        if not self.ignore:
            self.screen.active_window = self

    def move_to_workspace(self, space):
        if not self.ignore:
            self.space = space


class Screen:
    def __init__(self):
        self.spaces = [Space(self, i) for i in range(3)]
        self.active_space = self.spaces[0]
        self.windows = [NativeWindow(self, 1, self.spaces[0])]
        self.active_window = self.windows[0]

    def force_update(self):
        pass

    def get_workspaces(self):
        return self.spaces

    def get_windows(self):
        return self.windows

    def get_active_workspace(self):
        return self.active_space

    def get_active_window(self):
        return self.active_window


@pytest.fixture
def adapter():
    screen = Screen()
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    backend = X11Backend(
        screen,
        window_types={"NORMAL", "DIALOG"},
        pump=lambda: None,
        timestamp=lambda: 123,
        timeout=0.03,
        clock=lambda: clock[0],
        sleep=sleep,
    )
    return screen, backend


def test_discovery_keeps_hidden_windows_and_filters_panels_and_self(adapter):
    screen, backend = adapter
    screen.windows[0].minimized = True
    screen.windows += [
        NativeWindow(screen, 2, screen.spaces[0], kind="DOCK"),
        NativeWindow(screen, 3, screen.spaces[0]),
        NativeWindow(screen, 4, screen.spaces[1], kind="DIALOG"),
    ]
    screen.windows[-1].fullscreen = True
    backend.excluded_xids.add(3)
    snapshot = backend.snapshot()
    assert [w.id for w in snapshot.windows] == [1, 4]
    assert snapshot.window(1).minimized
    assert snapshot.window(4).fullscreen
    assert snapshot.active_window_id is None


def test_workspace_ids_survive_desktop_number_changes(adapter):
    screen, backend = adapter
    before = backend.snapshot()
    target = screen.spaces[2]
    screen.spaces.pop(1)
    target.number = 1
    after = backend.snapshot()
    assert after.workspaces[-1].id == before.workspaces[-1].id
    with pytest.raises(BackendError, match="destination"):
        backend.move_window(1, before.workspaces[1].id)


def test_move_does_not_request_desktop_activation(adapter):
    screen, backend = adapter
    target = backend.snapshot().workspaces[-1].id
    backend.move_window(1, target)
    assert screen.windows[0].space is screen.spaces[-1]
    assert screen.active_space is screen.spaces[0]


def test_activation_waits_for_desktop_and_restores_minimized_window(adapter):
    screen, backend = adapter
    screen.windows[0].space = screen.spaces[2]
    screen.windows[0].minimized = True
    backend.activate_window(1)
    assert screen.active_space is screen.spaces[2]
    assert not screen.windows[0].minimized
    assert backend.snapshot().active_window_id == 1


@pytest.mark.parametrize("action", ["activate", "move"])
def test_refused_requests_time_out_instead_of_reporting_success(adapter, action):
    screen, backend = adapter
    target = backend.snapshot().workspaces[-1].id
    screen.windows[0].ignore = True
    screen.active_window = None
    with pytest.raises(BackendError, match="refused"):
        if action == "activate":
            backend.activate_window(1)
        else:
            backend.move_window(1, target)


def test_pinned_window_is_visible_but_is_not_silently_unpinned(adapter):
    screen, backend = adapter
    screen.windows[0].space = None
    screen.windows[0].pinned = True
    snapshot = backend.snapshot()
    assert snapshot.window(1).pinned
    assert snapshot.window(1).workspace_id == snapshot.active_workspace_id
    with pytest.raises(BackendError, match="Unpin"):
        backend.move_window(1, snapshot.workspaces[1].id)


def test_missing_timestamp_never_sends_activation(adapter):
    screen, backend = adapter
    backend._timestamp = lambda: 0
    screen.active_window = None
    with pytest.raises(BackendError, match="timestamp"):
        backend.activate_window(1)
    assert screen.active_window is None


def test_native_workspace_order_follows_desktop_numbers_not_enumeration(adapter):
    screen, backend = adapter
    screen.spaces.reverse()
    first = backend.snapshot()
    assert [w.name for w in first.workspaces] == ["Desktop 0", "Desktop 1", "Desktop 2"]
    screen.spaces.reverse()
    assert backend.snapshot().workspaces == first.workspaces
