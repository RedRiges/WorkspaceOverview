"""Spawnable IPC fixture; intentionally slow X11 stand-in for lifecycle tests."""

import struct
import time


def capture(connection):
    while True:
        request = struct.unpack("!I", connection.recv(4))[0]
        if request == 1:
            time.sleep(30)
        elif request == 2:
            header = struct.pack("!HHd", 320, 200, 100.0)
            connection.sendall(header + b"\x5a" * (320 * 200 * 3))
        elif request == 4:
            # A header alone must not cause poll() to wait for the image.
            connection.sendall(struct.pack("!HHd", 320, 200, 100.0))
            time.sleep(30)
        else:
            return
