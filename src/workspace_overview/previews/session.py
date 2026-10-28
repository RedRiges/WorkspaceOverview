"""Conservative screen-lock monitoring via existing session D-Bus services."""

SERVICES = (
    ("org.xfce.ScreenSaver", "/org/xfce/ScreenSaver"),
    ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver"),
    ("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver"),
)


class SessionGuard:
    """Unknown state disables capture. No locker is started or configured."""

    def __init__(self, native, changed):
        self.native = native
        self.changed = changed
        self.state = "unknown"
        self._closed = False
        self._proxies = []
        self._states = {}
        self._serials = {}
        self._handlers = []
        self._cancel = native.Gio.Cancellable()
        Gio = native.Gio
        for name, path in SERVICES:
            try:
                proxy = Gio.DBusProxy.new_for_bus_sync(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.DO_NOT_AUTO_START
                    | Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                    None,
                    name,
                    path,
                    name,
                    self._cancel,
                )
            except native.GLib.Error:
                continue
            self._proxies.append(proxy)
            self._states[proxy] = None
            self._serials[proxy] = 0
            self._handlers.extend(
                (proxy, proxy.connect(signal, handler))
                for signal, handler in (
                    ("g-signal", self._signal),
                    ("notify::g-name-owner", self._owner_changed),
                )
            )
            self._owner_changed(proxy)

    def _publish(self):
        if self._closed:
            return
        states = [
            self._states[p] for p in self._proxies if p.get_name_owner() is not None
        ]
        state = (
            "locked"
            if True in states
            else "unlocked"
            if states and all(s is False for s in states)
            else "unknown"
        )
        if state != self.state:
            self.state = state
            self.changed(state)

    def _owner_changed(self, proxy, *_args):
        self._serials[proxy] += 1
        serial = self._serials[proxy]
        self._states[proxy] = None
        self._publish()
        if proxy.get_name_owner() is None:
            return

        def finished(source, result):
            try:
                value = source.call_finish(result)
            except self.native.GLib.Error:
                value = None
            if self._closed or self._serials[proxy] != serial:
                return
            self._states[proxy] = (
                value.unpack()[0]
                if value is not None and value.get_type_string() == "(b)"
                else None
            )
            self._publish()

        proxy.call(
            "GetActive",
            None,
            self.native.Gio.DBusCallFlags.NO_AUTO_START,
            1000,
            self._cancel,
            finished,
        )

    def _signal(self, proxy, _sender, name, parameters):
        if name == "ActiveChanged" and parameters.get_type_string() == "(b)":
            self._serials[proxy] += 1  # An older GetActive reply must not undo a lock.
            self._states[proxy] = parameters.unpack()[0]
            self._publish()

    def close(self):
        self._closed = True
        self._cancel.cancel()
        for proxy, handler in self._handlers:
            proxy.disconnect(handler)
        self._handlers.clear()
        self._proxies.clear()
        self._states.clear()
        self._serials.clear()
