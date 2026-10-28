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


def press_key(native, name, *, shift=False):
    """Send actual X keyboard events through GTK's normal input path."""
    from Xlib import XK, X, display

    connection = display.Display()
    key = connection.keysym_to_keycode(XK.string_to_keysym(name))
    modifier = connection.keysym_to_keycode(XK.string_to_keysym("Shift_L"))
    try:
        if shift:
            connection.xtest_fake_input(X.KeyPress, modifier)
        connection.xtest_fake_input(X.KeyPress, key)
        connection.xtest_fake_input(X.KeyRelease, key)
        if shift:
            connection.xtest_fake_input(X.KeyRelease, modifier)
        connection.sync()
        drain_events(native)
    finally:
        connection.close()


def background_alpha(window_id):
    """Read an unused margin pixel of the native ARGB window, not a CSS value."""
    from Xlib import X, display

    connection = display.Display()
    try:
        window = connection.create_resource_object("window", window_id)
        assert window.get_geometry().depth == 32
        pixel = window.get_image(2, 2, 1, 1, X.ZPixmap, 0xFFFFFFFF).data
        order = (
            "little"
            if connection.display.info.image_byte_order == X.LSBFirst
            else "big"
        )
        return (int.from_bytes(pixel[:4], order) >> 24) & 255
    finally:
        connection.close()


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
    if os.environ.get("WORKSPACE_OVERVIEW_TEST_COMPOSITOR") == "false":
        assert not native.Gdk.Screen.get_default().is_composited()
        assert backend.capture_preview(xid) is None
        return
    settle(native, lambda: native.Gdk.Screen.get_default().is_composited())
    # Allow the reparenting/compositing requests for this freshly mapped window.
    settle(native, lambda: backend.capture_preview(xid) is not None)
    image = backend.capture_preview(xid)
    assert 1 <= image.width <= 320
    assert 1 <= image.height <= 200


def test_real_gtk_overview_excludes_itself_and_activates_card(session):
    native, window, backend, xid = session
    # A maximized application must be discovered and rendered separately from
    # fullscreen, even though both can fill most or all of the screen.
    window.maximize()
    settle(native, lambda: backend.snapshot().window(xid).maximized)
    assert not backend.snapshot().window(xid).fullscreen
    original_workspace_count = len(backend.snapshot().workspaces)
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
        # A real RGBA backing surface carries partial alpha only with a compositor.
        expected_alpha = 184 if native.Gdk.Screen.get_default().is_composited() else 255
        settle(native, lambda: abs(background_alpha(own_xid) - expected_alpha) <= 2)
        assert app.window.get_opacity() == 1.0  # Never fade text and previews globally.
        settle(
            native,
            lambda: (
                app.backend.screen.get_active_window() is not None
                and app.backend.screen.get_active_window().get_xid() == own_xid
            ),
        )
        # Four workspaces fit on this 1280px display in one row. Increasing to
        # eight must overflow horizontally and keep the selected destination visible.
        assert all(
            app.grid.child_get_property(panel, "top-attach") == 0
            for panel in app.grid.get_children()
        )
        horizontal = app.scroller.get_hadjustment()
        if original_workspace_count == 4:
            settle(
                native,
                lambda: horizontal.get_upper() <= horizontal.get_page_size() + 1,
            )
        backend.screen.change_workspace_count(8)
        settle(native, lambda: len(app.overview.state.snapshot.workspaces) == 8)
        order = [w.id for w in app.overview.state.snapshot.workspaces]

        def selection_visible():
            panel = app._selected_panel
            if panel is None or panel.get_allocated_width() <= 1:
                return False
            position = panel.translate_coordinates(app.grid, 0, 0)
            if position is None:
                return False
            start = position[0] - horizontal.get_value()
            end = start + panel.get_allocated_width()
            return start >= -1 and end <= horizontal.get_page_size() + 1

        app.overview.select_workspace(order[-1])
        app._render()
        settle(native, selection_visible)
        assert horizontal.get_value() > 0
        assert all(
            app.grid.child_get_property(panel, "top-attach") == 0
            for panel in app.grid.get_children()
        )
        app.overview.select_workspace(order[0])
        app._render()
        settle(native, selection_visible)
        press_key(native, "Tab")
        settle(native, lambda: app.overview.state.selected_workspace_id == order[1])
        press_key(native, "Tab", shift=True)
        settle(native, lambda: app.overview.state.selected_workspace_id == order[0])
        # The fixture is the only application window; right crosses its card edge.
        press_key(native, "Right")
        settle(native, lambda: app.overview.state.selected_workspace_id == order[1])
        press_key(native, "Left")
        settle(native, lambda: app.overview.state.selected_workspace_id == order[0])
        assert app.overview.state.snapshot.active_workspace_id == order[0]
        # Move mode must reveal its destination, even while the source stays selected.
        press_key(native, "F2")
        app._perform(lambda: app.overview.select_destination(order[-1]))
        settle(native, selection_visible)
        assert horizontal.get_value() > 0
        press_key(native, "Escape")
        settle(native, selection_visible)
        assert app.overview.select_window(xid)
        event = native.Gdk.Event.new(native.Gdk.EventType.KEY_PRESS)
        event.keyval = native.Gdk.KEY_Return
        event.time = native.GdkX11.x11_get_server_time(app.window.get_window())
        event.state = native.Gdk.ModifierType(0)
        app.window.emit("key-press-event", event)
        assert app.window is None
    finally:
        app.stop()
        backend.screen.change_workspace_count(original_workspace_count)
        settle(
            native,
            lambda: len(backend.snapshot().workspaces) == original_workspace_count,
        )
