"""Exercise actual spawned processes and bounded IPC without a display."""

import time
from pathlib import Path

from workspace_overview.previews.worker import CaptureWorker


def wait_for(function):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = function()
        if result is not None and result is not False:
            return result
        time.sleep(0.01)
    raise AssertionError("Worker timed out")


def make_worker(monkeypatch, **kwargs):
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    from worker_process_fixture import capture

    return CaptureWorker(target=capture, **kwargs)


def test_slow_capture_does_not_block_poll_or_cancel_and_can_restart(monkeypatch):
    worker = make_worker(monkeypatch)
    try:
        assert worker.submit(1)
        old_process = worker._process
        started = time.monotonic()
        assert worker.poll() is None
        assert not worker.submit(2)
        worker.cancel()
        assert time.monotonic() - started < 0.5
        wait_for(lambda: worker.submit(2))
        assert worker._process is not old_process
        image, duration = wait_for(worker.poll)
        assert (image.width, image.height) == (320, 200)
        assert image.pixels == b"\x5a" * (320 * 200 * 3)
        assert duration == 100.0
    finally:
        worker.close()
        if worker._process is not None:
            worker._process.join(2)
            assert not worker._process.is_alive()


def test_worker_timeout_and_crash_report_failure_and_allow_recovery(monkeypatch):
    worker = make_worker(monkeypatch, timeout=0.3)
    try:
        assert worker.submit(1)
        assert wait_for(worker.poll) == (None, 0.0)
        worker._timeout = 5.0
        wait_for(lambda: worker.submit(3))  # Fixture exits without a reply.
        assert wait_for(worker.poll) == (None, 0.0)
        wait_for(lambda: worker.submit(2))
        assert wait_for(worker.poll)[0].width == 320
    finally:
        worker.close()
        if worker._process is not None:
            worker._process.join(2)
            assert not worker._process.is_alive()


def test_partial_image_never_blocks_the_ui(monkeypatch):
    worker = make_worker(monkeypatch)
    try:
        assert worker.submit(4)
        wait_for(lambda: (worker.poll(), bool(worker._incoming))[1])
        started = time.monotonic()
        assert worker.poll() is None
        worker.cancel()
        assert time.monotonic() - started < 0.5
        assert not worker._incoming
    finally:
        worker.close()
        if worker._process is not None:
            worker._process.join(2)
            assert not worker._process.is_alive()
