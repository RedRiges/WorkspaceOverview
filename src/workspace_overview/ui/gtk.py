"""Native GTK3 overview using the real X11 backend."""

import sys

from workspace_overview.backends.x11 import create_backend
from workspace_overview.core.backend import BackendError
from workspace_overview.core.navigation import Direction
from workspace_overview.core.overview import Overview
from workspace_overview.ui.layout import grid_columns

CSS = b"""
#workspace-overview { background-image: none; background-color: @theme_bg_color; }
#workspace-overview.composited { background-color: alpha(@theme_bg_color, 0.72); }
#workspace-overview scrolledwindow, #workspace-overview viewport {
    background-image: none; background-color: transparent;
}
.workspace { padding: 12px; border: 2px solid alpha(@theme_fg_color, 0.18);
             border-radius: 8px; background-color: alpha(@theme_bg_color, 0.9); }
.workspace.selected { border-color: @theme_selected_bg_color; }
.workspace.destination { border-color: #d5a326; }
.window-card { padding: 8px; border: 2px solid transparent; border-radius: 6px;
               background-color: @theme_bg_color; }
.window-card.selected { border-color: @theme_selected_bg_color;
                       background-color: alpha(@theme_selected_bg_color, 0.22); }
.overview-title { font-size: 20px; font-weight: bold; }
.overview-status { padding: 6px; }
"""


def build_application(native, *, previews: bool = True):
    Gtk, Gdk, GLib = native.Gtk, native.Gdk, native.GLib

    class Application(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="io.github.redriges.WorkspaceOverview")
            self.window = None
            self.overview = None
            self.backend = None
            self._timer = 0
            self._busy = False
            self._close_requested = False
            self._event_time = 0
            self._screen = None
            self._compositor_handler = 0
            self._css = None
            self._has_rgba_visual = False
            self.exit_status = 0

        def do_activate(self):
            if self.window is not None:
                self._close()
                return
            self._busy = True
            try:
                self._create_window()
                self.backend = create_backend(
                    native, self._timestamp, previews=previews
                )
                self.backend.excluded_xids.add(self.window.get_window().get_xid())
                self.overview = Overview(self.backend)
                if not self.overview.open():
                    raise BackendError(self.overview.state.error)
                self._render()
                self.window.show_all()
                self.window.present_with_time(self._timestamp())
                self._timer = GLib.timeout_add(300, self._poll)
            except BackendError as exc:
                print(f"workspace-overview: {exc}", file=sys.stderr)
                self.exit_status = 2
                if self.window is not None:
                    self.window.destroy()
                self.quit()
            finally:
                self._busy = False
            if self._close_requested:
                self._close()

        def _timestamp(self):
            if self._event_time:
                return self._event_time
            if self.window is not None and self.window.get_window() is not None:
                # PROPERTY_CHANGE_MASK is installed before realize, as required
                # by gdk_x11_get_server_time; don't use wall-clock timestamps.
                return native.GdkX11.x11_get_server_time(self.window.get_window())
            return 0

        def _create_window(self):
            self.window = Gtk.ApplicationWindow(
                application=self, title="Workspace Overview"
            )
            self.window.set_name("workspace-overview")
            self._screen = self.window.get_screen()
            rgba = self._screen.get_rgba_visual()
            self._has_rgba_visual = rgba is not None
            if rgba is not None:
                self.window.set_visual(rgba)  # Must happen before realize.
            self._compositor_handler = self._screen.connect(
                "composited-changed", self._update_compositing
            )
            self._update_compositing()
            self.window.set_decorated(False)
            self.window.set_skip_taskbar_hint(True)
            self.window.set_skip_pager_hint(True)
            self.window.set_keep_above(True)
            self.window.stick()
            self.window.fullscreen()
            self.window.add_events(
                Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.PROPERTY_CHANGE_MASK
            )
            self.window.connect("key-press-event", self._key)
            self.window.connect("delete-event", self._delete)
            self.window.connect("destroy", self._destroyed)
            self._css = Gtk.CssProvider()
            self._css.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_screen(
                self._screen, self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            root.set_border_width(16)
            self.window.add(root)
            header = Gtk.Box(spacing=12)
            title = Gtk.Label(label="Workspace Overview", xalign=0)
            title.get_style_context().add_class("overview-title")
            header.pack_start(title, True, True, 0)
            self.move_button = Gtk.Button(label="Move selected · F2")
            self.move_button.connect("clicked", lambda _: self._perform(self._move))
            header.pack_start(self.move_button, False, False, 0)
            close = Gtk.Button(label="Close · Esc")
            close.connect("clicked", lambda _: self._close())
            header.pack_start(close, False, False, 0)
            root.pack_start(header, False, False, 0)
            self.scroller = Gtk.ScrolledWindow()
            self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.grid = Gtk.Grid(column_spacing=12, row_spacing=12)
            self.grid.set_direction(Gtk.TextDirection.LTR)
            self.grid.set_column_homogeneous(True)
            self.scroller.add(self.grid)
            root.pack_start(self.scroller, True, True, 0)
            self.status = Gtk.Label(xalign=0)
            self.status.set_line_wrap(True)
            self.status.get_style_context().add_class("overview-status")
            root.pack_start(self.status, False, False, 0)
            help_label = Gtk.Label(
                label="Tab / Shift+Tab: next / previous workspace"
                "   ·   Arrows: windows / neighboring workspace"
                "   ·   Enter: activate"
                "   ·   F2: move   ·   Esc: cancel / close",
                xalign=0,
            )
            help_label.set_line_wrap(True)
            root.pack_start(help_label, False, False, 0)
            self.window.realize()

        def _update_compositing(self, *_args):
            if self.window is None:
                return
            style = self.window.get_style_context()
            if self._has_rgba_visual and self._screen.is_composited():
                style.add_class("composited")
            else:
                style.remove_class("composited")
            self.window.queue_draw()

        def _render(self):
            state = self.overview.state
            width = native.display.get_monitor(0).get_geometry().width
            self.workspace_columns, self.card_columns = grid_columns(
                width, len(state.snapshot.workspaces)
            )
            for child in self.grid.get_children():
                child.destroy()
            selected_widget = None
            for index, workspace in enumerate(state.snapshot.workspaces):
                panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                panel.set_valign(Gtk.Align.START)
                panel.set_hexpand(True)
                style = panel.get_style_context()
                style.add_class("workspace")
                if workspace.id == state.selected_workspace_id:
                    style.add_class("selected")
                if state.move and workspace.id == state.move.destination_workspace_id:
                    style.add_class("destination")
                name = workspace.name
                if workspace.id == state.snapshot.active_workspace_id:
                    name += "  • active"
                header = Gtk.Button(label=name)
                header.connect("clicked", self._workspace_clicked, workspace.id)
                panel.pack_start(header, False, False, 0)
                if state.move and workspace.id == state.move.destination_workspace_id:
                    selected_widget = header
                elif not state.move and workspace.id == state.selected_workspace_id:
                    # Empty workspaces need a focus/scroll target, too.
                    selected_widget = header
                cards = Gtk.Grid(column_spacing=8, row_spacing=8)
                cards.set_direction(Gtk.TextDirection.LTR)
                cards.set_column_homogeneous(True)
                panel.pack_start(cards, False, False, 0)
                windows = state.snapshot.windows_on(workspace.id)
                if not windows:
                    panel.pack_start(Gtk.Label(label="No windows"), False, False, 16)
                for card_index, window in enumerate(windows):
                    card = self._card(window)
                    cards.attach(
                        card,
                        card_index % self.card_columns,
                        card_index // self.card_columns,
                        1,
                        1,
                    )
                    if window.id == state.selected_window_id:
                        card.get_style_context().add_class("selected")
                        if not state.move:
                            selected_widget = card
                self.grid.attach(
                    panel,
                    index % self.workspace_columns,
                    index // self.workspace_columns,
                    1,
                    1,
                )
            self.move_button.set_label(
                "Confirm move · Enter" if state.move else "Move selected · F2"
            )
            selected = state.snapshot.window(state.selected_window_id)
            self.move_button.set_sensitive(selected is not None and not selected.pinned)
            if state.error:
                message = state.error
            elif state.move:
                destination = next(
                    w.name
                    for w in state.snapshot.workspaces
                    if w.id == state.move.destination_workspace_id
                )
                message = (
                    f"Move to {destination} — arrows choose, "
                    "Enter confirms, Esc cancels"
                )
            else:
                message = (
                    f"{len(state.snapshot.windows)} windows · "
                    f"{len(state.snapshot.workspaces)} workspaces"
                )
            self.status.set_text(message)
            self.grid.show_all()
            if selected_widget is not None:
                selected_widget.grab_focus()

        def _card(self, window):
            card = Gtk.Button()
            card.set_hexpand(True)
            card.get_style_context().add_class("window-card")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add(box)
            image = Gtk.Image()
            image.set_size_request(160, 100)
            preview = self.overview.previews.get(window.id)
            if preview:
                pixbuf = native.GdkPixbuf.Pixbuf.new_from_bytes(
                    GLib.Bytes.new(preview.pixels),
                    native.GdkPixbuf.Colorspace.RGB,
                    False,
                    8,
                    preview.width,
                    preview.height,
                    preview.width * 3,
                )
                scale = min(1, 192 / preview.width, 120 / preview.height)
                image.set_from_pixbuf(
                    pixbuf.scale_simple(
                        max(1, int(preview.width * scale)),
                        max(1, int(preview.height * scale)),
                        native.GdkPixbuf.InterpType.BILINEAR,
                    )
                )
            else:
                try:
                    icon = self.backend.icon(window.id)
                except BackendError:
                    icon = None
                if icon:
                    image.set_from_pixbuf(
                        icon.scale_simple(48, 48, native.GdkPixbuf.InterpType.BILINEAR)
                    )
                else:
                    image.set_from_icon_name(window.icon_name, Gtk.IconSize.DIALOG)
            box.pack_start(image, False, False, 0)
            label = Gtk.Label(label=window.title)
            label.set_max_width_chars(24)
            label.set_ellipsize(native.Pango.EllipsizeMode.END)
            box.pack_start(label, False, False, 0)
            flags = []
            if window.minimized:
                flags.append("minimized")
            if window.fullscreen:
                flags.append("fullscreen")
            if window.pinned:
                flags.append("all workspaces")
            box.pack_start(Gtk.Label(label=" · ".join(flags)), False, False, 0)
            card.set_tooltip_text(window.title)
            card.connect("clicked", self._card_clicked, window.id)
            return card

        def _perform(self, action, *, activation=False):
            if self._busy or self.overview is None:
                return
            self._busy = True
            self._event_time = Gtk.get_current_event_time() or self._timestamp()
            try:
                if activation:
                    self.window.hide()  # Let the target receive focus, not the overlay.
                    native.display.flush()
                action()
                if not self.overview.state.is_open:
                    self.window.destroy()
                else:
                    self._render()
                    if activation:
                        self.window.show_all()
                        self.window.present_with_time(self._timestamp())
            finally:
                self._event_time = 0
                self._busy = False
            if self._close_requested:
                self._close()

        def _card_clicked(self, _button, window_id):
            if self._busy:
                return
            if self.overview.state.move:
                target = self.overview.state.snapshot.window(window_id)
                self._perform(
                    lambda: self.overview.select_destination(target.workspace_id)
                )
            else:

                def activate():
                    if self.overview.select_window(window_id):
                        self.overview.activate_selected()

                self._perform(activate, activation=True)

        def _workspace_clicked(self, _button, workspace_id):
            self._perform(
                lambda: (
                    self.overview.select_destination(workspace_id)
                    if self.overview.state.move
                    else self.overview.select_workspace(workspace_id)
                )
            )

        def _move(self):
            if self.overview.state.move:
                self.overview.confirm_move()
            else:
                self.overview.begin_move()

        def _key(self, _window, event):
            if self._busy:
                return True
            key = event.keyval
            arrows = {
                Gdk.KEY_Left: Direction.LEFT,
                Gdk.KEY_Right: Direction.RIGHT,
                Gdk.KEY_Up: Direction.UP,
                Gdk.KEY_Down: Direction.DOWN,
            }
            if key in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
                backwards = (
                    key == Gdk.KEY_ISO_Left_Tab
                    or event.state & Gdk.ModifierType.SHIFT_MASK
                )
                self._perform(
                    lambda: self.overview.cycle_workspace(-1 if backwards else 1)
                )
            elif key in arrows:
                self._perform(
                    lambda: self.overview.navigate(
                        arrows[key],
                        columns=self.card_columns,
                        workspace_columns=self.workspace_columns,
                    )
                )
            elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self._perform(
                    self.overview.enter, activation=self.overview.state.move is None
                )
            elif key == Gdk.KEY_F2:
                self._perform(self.overview.begin_move)
            elif key == Gdk.KEY_Escape:
                self._perform(self.overview.escape)
            else:
                return False
            return True

        def _poll(self):
            if self.overview is None:
                return False
            if self._busy:
                return True
            self._busy = True
            try:
                before = self.overview.state
                self.overview.refresh()
                if self.overview.state != before:
                    self._render()
            finally:
                self._busy = False
            if self._close_requested:
                self._close()
                return False
            return True

        def _delete(self, *_args):
            self._close()
            return True

        def _close(self):
            if self._busy:
                self._close_requested = True
            elif self.window is not None:
                self.window.destroy()

        def _destroyed(self, *_args):
            if self._compositor_handler:
                self._screen.disconnect(self._compositor_handler)
                self._compositor_handler = 0
            if self._css is not None:
                Gtk.StyleContext.remove_provider_for_screen(self._screen, self._css)
                self._css = None
            if self._timer:
                GLib.source_remove(self._timer)
                self._timer = 0
            if self.overview:
                self.overview.close()
            if self.backend:
                self.backend.close()
            self.window = None
            self.overview = None
            self.backend = None
            self.quit()

    return Application()
