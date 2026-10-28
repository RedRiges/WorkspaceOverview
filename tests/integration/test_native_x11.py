"""Opt-in tests with real GTK windows on a disposable X11 display.

Only the windows created here are moved/minimized/activated. CI runs this in
Xvfb + Openbox + xcompmgr; do not enable it on the user's everyday desktop.
"""

import os
import time

import pytest

if os.environ.get("WORKSPACE_OVERVIEW_NATIVE_TESTS") != "1":
    pytest.skip("requires an isolated X11 test display", allow_module_level=True)

from workspace_overview.backends.x11 import create_backend
from workspace_overview.native import drain_events, load_native
from workspace_overview.ui.gtk import build_application


def settle(native, condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        drain_events(native)
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("X11 condition timed out")


@pytest.fixture
def session():
    native = load_native()
    window = native.Gtk.Window(title="Workspace Overview integration fixture")
    window.add_events(native.Gdk.EventMask.PROPERTY_CHANGE_MASK)
    window.set_default_size(320, 180)
    window.add(native.Gtk.Label(label="Real X11 test window"))
    window.show_all()
    backend = create_backend(
        native, lambda: native.GdkX11.x11_get_server_time(window.get_window())
    )
    xid = window.get_window().get_xid()
    settle(native, lambda: backend.snapshot().window(xid) is not None)
    try:
        yield native, window, backend, xid
    finally:
        backend.close()
        window.destroy()
        drain_events(native)


def test_real_discovery_move_and_activation(session):
    native, window, backend, xid = session
    before = backend.snapshot()
    original = before.window(xid).workspace_id
    target = next(w.id for w in before.workspaces if w.id != original)
    try:
        backend.move_window(xid, target)
        assert backend.snapshot().window(xid).workspace_id == target
        assert backend.snapshot().active_workspace_id == before.active_workspace_id
    finally:
        backend.move_window(xid, original)
    window.iconify()
    settle(native, lambda: backend.snapshot().window(xid).minimized)
    backend.activate_window(xid)
    assert backend.snapshot().active_window_id == xid
    assert not backend.snapshot().window(xid).minimized


def test_real_xcomposite_capture(session):
    native, _window, backend, xid = session
    settle(native, lambda: native.Gdk.Screen.get_default().is_composited())
    # Allow the reparenting/compositing requests for this freshly mapped window.
    settle(native, lambda: backend.capture_preview(xid) is not None)
    image = backend.capture_preview(xid)
    assert 1 <= image.width <= 320
    assert 1 <= image.height <= 200


def test_real_gtk_overview_excludes_itself_and_activates_card(session):
    native, _window, _backend, xid = session
    app = build_application(native)
    assert app.register(None)
    app.activate()
    try:
        assert app.exit_status == 0
        assert app.window is not None
        settle(native, lambda: app.window.get_mapped())
        own_xid = app.window.get_window().get_xid()
        assert app.overview.state.snapshot.window(own_xid) is None
        assert app.overview.state.snapshot.window(xid) is not None
        assert app.overview.select_window(xid)
        event = native.Gdk.Event.new(native.Gdk.EventType.KEY_PRESS)
        event.keyval = native.Gdk.KEY_Return
        event.time = native.GdkX11.x11_get_server_time(app.window.get_window())
        event.state = native.Gdk.ModifierType(0)
        app.window.emit("key-press-event", event)
        assert app.window is None
    finally:
        if app.window is not None:
            app.window.destroy()
