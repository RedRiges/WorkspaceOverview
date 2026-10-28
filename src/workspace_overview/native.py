"""Load distribution-provided GTK/X11 libraries only for the native application."""

import os
import sys
from types import SimpleNamespace

from workspace_overview.core.backend import BackendError


def check_session(platform: str, environ: dict) -> None:
    if platform != "linux":
        raise BackendError("The native overview requires Linux with an X11 session")
    if environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        raise BackendError("Wayland is unsupported; log into your Xfce X11 session")
    if not environ.get("DISPLAY"):
        raise BackendError("DISPLAY is unset; run from a terminal inside Xfce")


def load_native() -> SimpleNamespace:
    check_session(sys.platform, os.environ)
    try:
        import gi

        for namespace, version in (
            ("Gtk", "3.0"),
            ("Gdk", "3.0"),
            ("GdkX11", "3.0"),
            ("Wnck", "3.0"),
            ("GdkPixbuf", "2.0"),
        ):
            gi.require_version(namespace, version)
        from gi.repository import Gdk, GdkPixbuf, GdkX11, Gio, GLib, Gtk, Pango, Wnck
    except (ImportError, ValueError) as exc:
        raise BackendError(
            "GTK3/libwnck bindings are missing. On Void install python3-gobject, "
            "gtk+3 and libwnck, then use scripts/run-x11 with /usr/bin/python3. "
            f"Details: {exc}"
        ) from exc
    initialized, _ = Gtk.init_check([])
    if not initialized:
        raise BackendError("Cannot open the X display; run as your desktop user")
    display = Gdk.Display.get_default()
    if not isinstance(display, GdkX11.X11Display):
        raise BackendError("GTK is not connected to an X11 display")
    if display.get_n_monitors() != 1:
        raise BackendError("This version supports exactly one physical monitor")
    return SimpleNamespace(
        Gtk=Gtk,
        Gdk=Gdk,
        GdkX11=GdkX11,
        Gio=Gio,
        GLib=GLib,
        GdkPixbuf=GdkPixbuf,
        Pango=Pango,
        Wnck=Wnck,
        display=display,
    )


def drain_events(native) -> None:
    context = native.GLib.MainContext.default()
    # Bound each pass even if another source continuously queues work.
    for _ in range(100):
        if not context.pending():
            break
        context.iteration(False)
