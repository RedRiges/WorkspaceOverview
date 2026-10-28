"""Read compositor-owned pixmaps without redirecting/unmapping any windows."""

from workspace_overview.previews.pixels import decode_rgb


class CompositeCapture:
    def __init__(self) -> None:
        self._display = None
        self.status = "unavailable"
        try:
            from Xlib import X, display, error
        except ImportError:
            self.status = "python3-xlib is missing; using icons and titles"
            return
        self._X = X
        self._error = error
        self._errors = (
            error.XError,
            error.DisplayError,
            error.ConnectionClosedError,
            error.XauthError,
            error.XNoAuthError,
            OSError,
            ValueError,
        )
        try:
            self._display = display.Display()
            if not self._display.has_extension("Composite"):
                self.status = "XComposite unavailable; using icons and titles"
                self.close()
                return
            version = self._display.composite_query_version()
            if (version.major_version, version.minor_version) < (0, 2):
                self.status = "XComposite 0.2 or newer is required for previews"
                self.close()
                return
            self.status = "XComposite available (capture depends on each window)"
        except self._errors:
            self.status = (
                "Cannot connect preview capture to X11; using icons and titles"
            )
            self.close()

    def capture(self, window_id: int):
        display = self._display
        if display is None:
            return None
        pixmap = None
        try:
            window = display.create_resource_object("window", window_id)
            # Reparenting WMs redirect the frame. Its pixmap includes the client.
            for _ in range(32):
                tree = window.query_tree()
                if tree.parent.id == tree.root.id:
                    break
                if not tree.parent.id:
                    return None
                window = tree.parent
            else:
                return None
            attributes = window.get_attributes()
            if attributes.map_state != self._X.IsViewable:
                return None
            caught = self._error.CatchError()
            pixmap = window.composite_name_window_pixmap(onerror=caught)
            display.sync()
            if caught.get_error() is not None:
                return None
            geometry = pixmap.get_geometry()
            width, height = geometry.width, geometry.height
            if min(width, height) < 1 or width * height > 16_777_216:
                return None
            screen = next(
                (
                    display.screen(i)
                    for i in range(display.screen_count())
                    if display.screen(i).root.id == tree.root.id
                ),
                None,
            )
            if screen is None:
                return None
            visual = next(
                (
                    v
                    for depth in screen.allowed_depths
                    for v in depth.visuals
                    if v.visual_id == attributes.visual
                ),
                None,
            )
            if visual is None or visual.visual_class != self._X.TrueColor:
                return None
            formats = display.display.info.pixmap_formats
            fmt = next((f for f in formats if f.depth == geometry.depth), None)
            if fmt is None or fmt.scanline_pad not in (8, 16, 32):
                return None
            stride = (
                (width * fmt.bits_per_pixel + fmt.scanline_pad - 1)
                // fmt.scanline_pad
                * fmt.scanline_pad
                // 8
            )
            image = pixmap.get_image(0, 0, width, height, self._X.ZPixmap, 0xFFFFFFFF)
            return decode_rgb(
                image.data,
                width=width,
                height=height,
                bits_per_pixel=fmt.bits_per_pixel,
                stride=stride,
                byteorder=(
                    "little"
                    if display.display.info.image_byte_order == self._X.LSBFirst
                    else "big"
                ),
                masks=(visual.red_mask, visual.green_mask, visual.blue_mask),
            )
        except self._errors:
            return None
        finally:
            if pixmap is not None:
                try:
                    pixmap.free(onerror=self._error.CatchError())
                    display.sync()
                except self._errors:
                    pass

    def close(self) -> None:
        if self._display is not None:
            try:
                self._display.close()
            except self._errors:
                pass
            self._display = None
