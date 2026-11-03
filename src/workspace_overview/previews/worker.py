"""One low-priority capture process; bounded RAM IPC, no GTK in the worker."""

import multiprocessing
import os
import signal
import socket
import struct
import time

from workspace_overview.core.models import Preview

_REQUEST = struct.Struct("!I")
_HEADER = struct.Struct("!HHd")
_MAX_PACKET = _HEADER.size + 320 * 200 * 3


def _capture_loop(connection):
    # Spawn instead of fork: never inherit GTK or an existing Xlib connection.
    from workspace_overview.previews.xcomposite import CompositeCapture

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        os.nice(10)
    except OSError:
        pass
    capture = CompositeCapture()
    try:
        while True:
            request = bytearray()
            while len(request) < _REQUEST.size:
                part = connection.recv(_REQUEST.size - len(request))
                if not part:
                    return
                request.extend(part)
            started = time.perf_counter()
            image = capture.capture(_REQUEST.unpack(request)[0])
            duration = (time.perf_counter() - started) * 1000
            if image is None:
                connection.sendall(_HEADER.pack(0, 0, duration))
            else:
                connection.sendall(
                    _HEADER.pack(image.width, image.height, duration) + image.pixels
                )
            image = None
    except OSError:
        pass
    finally:
        capture.close()
        connection.close()


class CaptureWorker:
    """One in-flight request; nonblocking reads, no files or shared-memory files."""

    def __init__(self, *, target=_capture_loop, timeout=5.0):
        self._context = multiprocessing.get_context("spawn")
        self._target = target
        self._timeout = timeout
        self._process = None
        self._connection = None
        self._pending_since = None
        self._incoming = bytearray()

    def submit(self, window_id):
        if self._pending_since is not None:
            return False
        if self._process is not None and self._connection is None:
            if self._process.is_alive():
                return False  # Reap cancellation before starting a replacement.
            self._process.join(0)
            self._process.close()
            self._process = None
        if self._process is None:
            parent, child = socket.socketpair()
            parent.setblocking(False)
            process = self._context.Process(
                target=self._target, args=(child,), daemon=True
            )
            try:
                process.start()
            except (OSError, RuntimeError):
                parent.close()
                child.close()
                return False
            child.close()
            self._process, self._connection = process, parent
        try:
            # With one request at a time, the outbound socket buffer is empty.
            if self._connection.send(_REQUEST.pack(window_id)) != _REQUEST.size:
                self.cancel()
                return False
        except OSError:
            self.cancel()
            return False
        self._pending_since = time.monotonic()
        return True

    def poll(self):
        if self._pending_since is None:
            return None
        try:
            while len(self._incoming) < _MAX_PACKET:
                try:
                    part = self._connection.recv(_MAX_PACKET - len(self._incoming))
                except BlockingIOError:
                    break
                if not part:
                    raise EOFError
                self._incoming.extend(part)
                if len(self._incoming) >= _HEADER.size:
                    width, height, duration = _HEADER.unpack_from(self._incoming)
                    if not (0 <= width <= 320 and 0 <= height <= 200):
                        raise ValueError("Invalid worker image dimensions")
                    size = width * height * 3
                    if len(self._incoming) == _HEADER.size + size:
                        image = None
                        if size:
                            image = Preview(
                                width, height, bytes(self._incoming[_HEADER.size :])
                            )
                        self._incoming.clear()
                        self._pending_since = None
                        return image, duration
            if self._process.is_alive():
                if time.monotonic() - self._pending_since < self._timeout:
                    return None
        except (EOFError, OSError, ValueError):
            pass
        self.cancel()
        return None, 0.0

    def cancel(self):
        self._pending_since = None
        self._incoming.clear()
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._process is not None:
            if self._process.is_alive():
                self._process.kill()
            self._process.join(0)
        # Never wait for X11 or start a replacement before this process exits.

    def close(self):
        self.cancel()
