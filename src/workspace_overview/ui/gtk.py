"""Native GTK3 overview using the real X11 backend."""

import signal
import sys

from workspace_overview.backends.x11 import create_backend
from workspace_overview.cli import parse_args
from workspace_overview.core.backend import BackendError
from workspace_overview.core.navigation import Direction
from workspace_overview.core.overview import Overview
from workspace_overview.native import drain_events
from workspace_overview.previews.cache import PreviewSampler, RamPreviewCache
from workspace_overview.previews.session import SessionGuard
from workspace_overview.ui.layout import strip_dimensions

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
.window-state-badge { padding: 4px 7px; border-radius: 6px;
                      font-size: 11px; font-weight: bold; }
.fullscreen-badge { background-color: @theme_selected_bg_color;
                    color: @theme_selected_fg_color; }
.maximized-badge { background-color: @theme_bg_color; color: @theme_fg_color;
                   border: 1px solid @theme_selected_bg_color; }
.minimized-badge { background-color: @theme_bg_color; color: @theme_fg_color;
                   border: 1px solid alpha(@theme_fg_color, 0.45); }
.overview-title { font-size: 20px; font-weight: bold; }
.overview-status { padding: 6px; }
"""


def build_application(native, *, previews: bool = True):
    Gtk, Gdk, GLib = native.Gtk, native.Gdk, native.GLib

    class Application(Gtk.Application):
        def __init__(self):
            super().__init__(
                application_id="io.github.redriges.WorkspaceOverview",
                flags=native.Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
            )
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
            self._selected_panel = None
            self._reveal_pending = False
            self._reveal_source = 0
            self.cache = RamPreviewCache()
            self.guard = None
            self.sampler = None
            self._previews_enabled = previews
            self._background_timer = 0
            self._closed_handler = 0
            self._held = False
            self._own_xid = None
            self._rendered_revision = -1
            self._render_pending = False
            self._stop_requested = False
            self._capture_error = False
            self._signal_sources = {}
            self.exit_status = 0

        def do_command_line(self, command):
            try:
                args = parse_args(command.get_arguments()[1:])
            except SystemExit as exc:
                return int(exc.code)
            if args.quit:
                self.stop()
                return 0
            if args.status:
                command.print_literal(self.cache_status() + "\n")
                return 0
            if args.clear_cache:
                self._clear_previews()
                return 0
            if args.previews is not None:
                self._previews_enabled = args.previews
                if not args.previews:
                    self._clear_previews()
            try:
                if args.background:
                    self._ensure_resident()
                else:
                    self.activate()
            except BackendError as exc:
                command.printerr_literal(f"workspace-overview: {exc}\n")
                self.stop()
                return 2
            return self.exit_status

        def _ensure_resident(self):
            if self.backend is not None:
                return
            self.backend = create_backend(native, self._timestamp, previews=True)
            self.guard = SessionGuard(native, self._lock_changed)
            self.sampler = PreviewSampler(
                self.backend,
                self.cache,
                self._capture_permitted,
                after_capture=lambda: drain_events(native),
            )
            self._closed_handler = self.backend.screen.connect(
                "window-closed", self._window_closed
            )
            self.hold()
            self._held = True
            self._background_timer = GLib.timeout_add(750, self._sample_background)
            for number in (signal.SIGINT, signal.SIGTERM):
                self._signal_sources[number] = GLib.unix_signal_add(
                    GLib.PRIORITY_DEFAULT, number, self._signal_stop, number
                )

        def _signal_stop(self, number):
            self._signal_sources.pop(number, None)
            self.stop()
            return False

        def _capture_permitted(self):
            return (
                self._previews_enabled
                and not self._stop_requested
                and self.guard is not None
                and self.guard.state == "unlocked"
                and native.Gdk.Screen.get_default().is_composited()
            )

        def cache_status(self):
            if self.backend is None:
                return "Workspace Overview is not running."
            if not self._previews_enabled:
                state = "disabled"
            elif self.guard.state != "unlocked":
                state = f"paused (screen-lock state: {self.guard.state})"
            elif not native.Gdk.Screen.get_default().is_composited():
                state = "paused (no compositor)"
            elif self._capture_error:
                state = "paused (window discovery unavailable)"
            else:
                state = "active"
            return (
                f"Background capture: {state}\n"
                f"RAM cache: {len(self.cache.images)} images; "
                f"{self.cache.bytes_used} / {self.cache.max_bytes} bytes"
            )

        def _clear_previews(self):
            self.cache.clear()
            self._render_pending = True
            if self.overview is not None and not self._busy:
                self._render()

        def _lock_changed(self, state):
            if state != "unlocked":
                self._clear_previews()
            if state == "locked":
                self._close()
            self._render_pending = True

        def _window_closed(self, _screen, window):
            self.cache.remove(window.get_xid())

        def _sample_background(self):
            if self._busy or self.backend is None:
                return True
            self._busy = True
            try:
                snapshot = self.backend.snapshot()
                self.sampler.sample(snapshot, only_missing=self.overview is not None)
                self._capture_error = False
            except BackendError:
                self.cache.clear()
                self._capture_error = True
            finally:
                self._busy = False
            self._finish_pending()
            return self.backend is not None

        def _finish_pending(self):
            if self._stop_requested:
                self.stop()
            elif self._close_requested:
                self._close()

        def do_activate(self):
            if self._busy:
                self._close_requested = True
                return
            if self.window is not None:
                self._close()
                return
            self._busy = True
            try:
                self._ensure_resident()
                if self.guard.state == "locked":
                    return
                self._close_requested = False
                self._create_window()
                self._own_xid = self.window.get_window().get_xid()
                self.backend.excluded_xids.add(self._own_xid)
                self.overview = Overview(self.backend, previews=self.cache.images)
                if not self.overview.open():
                    raise BackendError(self.overview.state.error)
                self.sampler.reconcile(self.overview.state.snapshot)
                self._render()
                self.window.show_all()
                self.window.present_with_time(self._timestamp())
                self._timer = GLib.timeout_add(300, self._poll)
            except BackendError as exc:
                print(f"workspace-overview: {exc}", file=sys.stderr)
                self.exit_status = 2
                if self.window is not None:
                    self.window.destroy()
                self._stop_requested = True
            finally:
                self._busy = False
            self._finish_pending()

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
            self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            self.scroller.set_overlay_scrolling(False)
            self.grid = Gtk.Grid(column_spacing=12, row_spacing=12)
            self.grid.set_direction(Gtk.TextDirection.LTR)
            self.grid.set_column_homogeneous(True)
            self.grid.set_valign(Gtk.Align.CENTER)
            self.grid.connect("size-allocate", self._queue_reveal)
            self.scroller.get_hadjustment().connect("changed", self._queue_reveal)
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
            self.workspace_columns, self.card_columns, panel_width = strip_dimensions(
                width, len(state.snapshot.workspaces)
            )
            self._selected_panel = None
            for child in self.grid.get_children():
                child.destroy()
            selected_widget = None
            for index, workspace in enumerate(state.snapshot.workspaces):
                panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                panel.set_valign(Gtk.Align.START)
                panel.set_hexpand(True)
                panel.set_size_request(panel_width, -1)
                style = panel.get_style_context()
                style.add_class("workspace")
                if workspace.id == state.selected_workspace_id:
                    style.add_class("selected")
                if state.move and workspace.id == state.move.destination_workspace_id:
                    style.add_class("destination")
                name = workspace.name
                if workspace.id == state.snapshot.active_workspace_id:
                    name += "  • active"
                header = Gtk.Button(label=f"{index + 1} · {name}")
                header.get_child().set_ellipsize(native.Pango.EllipsizeMode.END)
                header.get_child().set_max_width_chars(22)
                header.set_tooltip_text(name)
                header.connect("clicked", self._workspace_clicked, workspace.id)
                panel.pack_start(header, False, False, 0)
                if state.move and workspace.id == state.move.destination_workspace_id:
                    selected_widget = header
                    self._selected_panel = panel
                elif not state.move and workspace.id == state.selected_workspace_id:
                    # Empty workspaces need a focus/scroll target, too.
                    selected_widget = header
                    self._selected_panel = panel
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
                    index,
                    0,
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
                if not self._previews_enabled:
                    message += " · Previews disabled"
                elif self.guard.state != "unlocked":
                    message += " · Previews paused: screen-lock state unknown"
            self.status.set_text(message)
            self._rendered_revision = self.cache.revision
            self._render_pending = False
            self._reveal_pending = True
            self.grid.show_all()
            if selected_widget is not None:
                selected_widget.grab_focus()
            self._queue_reveal()

        def _queue_reveal(self, *_args):
            if self._reveal_pending and not self._reveal_source:
                # Wait until GTK has allocated the new cards and scroll range.
                self._reveal_source = GLib.idle_add(self._reveal_selection)

        def _reveal_selection(self):
            self._reveal_source = 0
            panel = self._selected_panel
            if self.window is None or panel is None:
                return False
            adjustment = self.scroller.get_hadjustment()
            position = panel.translate_coordinates(self.grid, 0, 0)
            if (
                position is None
                or adjustment.get_page_size() <= 1
                or panel.get_allocated_width() <= 1
            ):
                return False  # A later size allocation will queue another attempt.
            self._reveal_pending = False
            center = position[0] + panel.get_allocated_width() / 2
            maximum = max(
                adjustment.get_lower(),
                adjustment.get_upper() - adjustment.get_page_size(),
            )
            adjustment.set_value(
                max(
                    adjustment.get_lower(),
                    min(maximum, center - adjustment.get_page_size() / 2),
                )
            )
            return False

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
            thumbnail = Gtk.Overlay()
            thumbnail.add(image)
            states = []
            if window.fullscreen:
                states.append(
                    ("fullscreen-badge", "view-fullscreen-symbolic", "На весь экран")
                )
            elif window.maximized:
                states.append(
                    ("maximized-badge", "window-maximize-symbolic", "Развёрнуто")
                )
            if window.minimized:
                states.append(
                    ("minimized-badge", "window-minimize-symbolic", "Свёрнуто")
                )
            badges = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            badges.set_halign(Gtk.Align.END)
            badges.set_valign(Gtk.Align.START)
            badges.set_margin_top(4)
            badges.set_margin_end(4)
            for style, icon_name, text in states:
                badge = Gtk.Box(spacing=4)
                badge.get_style_context().add_class("window-state-badge")
                badge.get_style_context().add_class(style)
                badge.set_halign(Gtk.Align.END)
                badge.pack_start(
                    Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU),
                    False,
                    False,
                    0,
                )
                badge.pack_start(Gtk.Label(label=text), False, False, 0)
                badges.pack_start(badge, False, False, 0)
            if states:
                thumbnail.add_overlay(badges)
                thumbnail.set_overlay_pass_through(badges, True)
            box.pack_start(thumbnail, False, False, 0)
            label = Gtk.Label(label=window.title)
            label.set_max_width_chars(24)
            label.set_ellipsize(native.Pango.EllipsizeMode.END)
            box.pack_start(label, False, False, 0)
            flags = []
            if window.pinned:
                flags.append("all workspaces")
            box.pack_start(Gtk.Label(label=" · ".join(flags)), False, False, 0)
            card.set_tooltip_text("\n".join([window.title, *(s[2] for s in states)]))
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
            self._finish_pending()

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
                self.sampler.reconcile(self.overview.state.snapshot)
                if (
                    self.overview.state != before
                    or self._rendered_revision != self.cache.revision
                    or self._render_pending
                ):
                    self._render()
            finally:
                self._busy = False
            self._finish_pending()
            return self.overview is not None

        def _delete(self, *_args):
            self._close()
            return True

        def _close(self):
            if self._busy:
                self._close_requested = True
            elif self.window is not None:
                self._close_requested = False
                self.window.destroy()

        def _destroyed(self, *_args):
            self._reveal_pending = False
            self._selected_panel = None
            if self._reveal_source:
                GLib.source_remove(self._reveal_source)
                self._reveal_source = 0
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
            if self.backend and self._own_xid is not None:
                self.backend.excluded_xids.discard(self._own_xid)
            self._own_xid = None
            self.window = None
            self.overview = None

        def stop(self):
            self._stop_requested = True
            self.cache.clear()
            if self._busy:
                return
            if self.window is not None:
                self.window.destroy()
            self._dispose_resident()
            self.quit()

        def _dispose_resident(self):
            for source in self._signal_sources.values():
                GLib.source_remove(source)
            self._signal_sources.clear()
            if self._background_timer:
                GLib.source_remove(self._background_timer)
                self._background_timer = 0
            if self.guard is not None:
                self.guard.close()
                self.guard = None
            if self.backend is not None:
                if self._closed_handler:
                    self.backend.screen.disconnect(self._closed_handler)
                    self._closed_handler = 0
                self.backend.close()
                self.backend = None
            self.sampler = None
            self.cache.clear()
            if self._held:
                self.release()
                self._held = False

        def do_shutdown(self):
            if self.window is not None:
                self.window.destroy()
            self._dispose_resident()
            Gtk.Application.do_shutdown(self)

    return Application()
