"""Isolated test driver: real X11 windows, resident subprocess, D-Bus lock signals.

The lock provider here is a test service on a private session bus. It does not
lock the host screen. Only this driver's own fixture windows are manipulated.
"""

import os
import signal
import subprocess
import sys
import time

from workspace_overview.backends.x11 import create_backend
from workspace_overview.native import drain_events, load_native


def main():
    native = load_native()
    Gio, GLib = native.Gio, native.GLib

    def settle(condition, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            drain_events(native)
            if condition():
                return
            time.sleep(0.02)
        raise AssertionError("Resident condition timed out")

    def command(*args):
        process = subprocess.Popen(
            [sys.executable, "-m", "workspace_overview", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            settle(lambda: process.poll() is not None)
            out, err = process.communicate()
            assert process.returncode == 0, out + err
            assert "Traceback" not in err, err
            return out
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    locked = [True]
    interface = Gio.DBusNodeInfo.new_for_xml("""
    <node><interface name="org.xfce.ScreenSaver">
      <method name="GetActive"><arg type="b" direction="out"/></method>
      <signal name="ActiveChanged"><arg type="b"/></signal>
    </interface></node>""").interfaces[0]

    def method(_connection, _sender, _path, _interface, _method, _args, invocation):
        invocation.return_value(GLib.Variant("(b)", (locked[0],)))

    registration = connection.register_object(
        "/org/xfce/ScreenSaver", interface, method, None, None
    )

    def own_locker():
        return Gio.bus_own_name_on_connection(
            connection, "org.xfce.ScreenSaver", Gio.BusNameOwnerFlags.NONE, None, None
        )

    def set_locked(value):
        locked[0] = value
        connection.emit_signal(
            None,
            "/org/xfce/ScreenSaver",
            "org.xfce.ScreenSaver",
            "ActiveChanged",
            GLib.Variant("(b)", (value,)),
        )
        connection.flush_sync(None)

    def has_owner(name):
        return connection.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", (name,)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        ).unpack()[0]

    owner = own_locker()
    settle(lambda: has_owner("org.xfce.ScreenSaver"))
    window = native.Gtk.Window(title="RAM cache fixture")
    window.set_default_size(300, 160)
    window.add(native.Gtk.Label(label="Last captured content"))
    window.show_all()
    xid = window.get_window().get_xid()
    backend = create_backend(native, lambda: 0, previews=False)
    settle(lambda: backend.snapshot().window(xid) is not None)
    settle(lambda: backend.snapshot().active_window_id == xid)
    before = backend.snapshot()
    # Moving a fixture uses no timestamp and must not change the active workspace.
    other = next(w.id for w in before.workspaces if w.id != before.active_workspace_id)
    primary = subprocess.Popen(
        [sys.executable, "-m", "workspace_overview", "--background"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    composited = os.environ.get("WORKSPACE_OVERVIEW_TEST_COMPOSITOR") != "false"

    def has_overview():
        return any(w.title == "Workspace Overview" for w in backend.snapshot().windows)

    try:
        settle(lambda: has_owner("io.github.redriges.WorkspaceOverview"))
        settle(lambda: "locked" in command("--status"))
        assert "0 images" in command("--status")
        assert not has_overview()
        assert primary.poll() is None
        set_locked(False)
        expected = "1 images" if composited else "no compositor"
        settle(lambda: expected in command("--status"))
        after = backend.snapshot()
        assert after.active_workspace_id == before.active_workspace_id
        assert after.active_window_id == before.active_window_id
        backend.move_window(xid, other)
        command()  # Show the overview without activating the hidden fixture.
        settle(has_overview)
        if composited:
            assert "1 images" in command("--status")
        assert backend.snapshot().active_workspace_id == before.active_workspace_id
        command()  # Hide it, keeping the same resident process/cache.
        settle(lambda: not has_overview())
        assert primary.poll() is None
        if composited:
            assert "1 images" in command("--status")
        window.destroy()
        settle(lambda: "0 images" in command("--status"))
        window = native.Gtk.Window(title="New RAM cache fixture")
        window.set_default_size(300, 160)
        window.show_all()
        settle(lambda: expected in command("--status"))
        command()
        settle(has_overview)
        set_locked(True)
        settle(
            lambda: (
                "locked" in command("--status") and "0 images" in command("--status")
            )
        )
        settle(lambda: not has_overview())
        command()  # Locked sessions must not reopen the overlay.
        assert not has_overview()
        set_locked(False)
        settle(lambda: expected in command("--status"))
        Gio.bus_unown_name(owner)
        owner = 0
        settle(lambda: "unknown" in command("--status"))
        assert "0 images" in command("--status")
        command("--background", "--no-previews")
        owner = own_locker()
        settle(lambda: "disabled" in command("--status"))
        assert "0 images" in command("--status")
        command("--clear-cache")
        command("--background", "--previews")
        settle(lambda: expected in command("--status"))
        command("--quit")
        settle(lambda: primary.poll() is not None)
        out, err = primary.communicate()
        assert primary.returncode == 0, out + err
        assert "Traceback" not in err, err
        assert "not running" in command("--status")
        assert not has_owner("io.github.redriges.WorkspaceOverview")
        # A terminal interrupt must stop the resident, not leave a hidden process.
        primary = subprocess.Popen(
            [sys.executable, "-m", "workspace_overview", "--background"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        settle(lambda: has_owner("io.github.redriges.WorkspaceOverview"))
        settle(lambda: expected in command("--status"))
        primary.send_signal(signal.SIGINT)
        settle(lambda: primary.poll() is not None)
        out, err = primary.communicate()
        assert primary.returncode == 0, out + err
        assert "Traceback" not in err, err
        assert not has_owner("io.github.redriges.WorkspaceOverview")
        print(
            "Resident lifecycle, cache retention, lock/owner loss "
            "and remote commands passed"
        )
    finally:
        if primary.poll() is None:
            primary.terminate()
            try:
                primary.wait(timeout=3)
            except subprocess.TimeoutExpired:
                primary.kill()
                primary.wait()
            out, err = primary.communicate()
            if out or err:
                print(out + err, file=sys.stderr)
        window.destroy()
        backend.close()
        if owner:
            Gio.bus_unown_name(owner)
        connection.unregister_object(registration)


if __name__ == "__main__":
    main()
