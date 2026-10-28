"""Portable checks of native-session requirements and X image formats."""

import pytest

from workspace_overview.__main__ import main
from workspace_overview.core.backend import BackendError
from workspace_overview.native import check_session
from workspace_overview.previews.pixels import decode_rgb
from workspace_overview.ui.layout import grid_columns


@pytest.mark.parametrize(
    "platform,environ",
    [
        ("darwin", {"DISPLAY": ":0"}),
        ("linux", {}),
        ("linux", {"DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"}),
    ],
)
def test_unsupported_sessions_have_explicit_error(platform, environ):
    with pytest.raises(BackendError):
        check_session(platform, environ)


def test_x11_session_without_logind_is_valid():
    check_session("linux", {"DISPLAY": ":0"})


def test_native_command_never_falls_back_to_mock(monkeypatch, capsys):
    monkeypatch.setattr("sys.platform", "darwin")
    assert main(["--check"]) == 2
    assert "requires Linux" in capsys.readouterr().err


@pytest.mark.parametrize(
    "width,count,expected",
    [
        (1366, 4, (2, 2)),
        (1920, 4, (3, 2)),
        (800, 1, (1, 3)),
        (200, 0, (1, 1)),
    ],
)
def test_rendering_and_navigation_use_identical_grid(width, count, expected):
    assert grid_columns(width, count) == expected


@pytest.mark.parametrize("byteorder", ["little", "big"])
@pytest.mark.parametrize(
    "bpp,masks,pixel",
    [
        (16, (0xF800, 0x07E0, 0x001F), 0xF800),
        (24, (0xFF0000, 0x00FF00, 0x0000FF), 0xFF0000),
        (32, (0xFF0000, 0x00FF00, 0x0000FF), 0xFF0000),
        (32, (0x3FF00000, 0x000FFC00, 0x000003FF), 0x3FF00000),
    ],
)
def test_truecolor_masks_and_byte_order(byteorder, bpp, masks, pixel):
    pixel_bytes = bpp // 8
    data = pixel.to_bytes(pixel_bytes, byteorder) + b"\x00" * (4 - pixel_bytes)
    preview = decode_rgb(
        data,
        width=1,
        height=1,
        bits_per_pixel=bpp,
        stride=4,
        byteorder=byteorder,
        masks=masks,
    )
    assert preview.pixels == bytes((255, 0, 0))


def test_row_padding_and_downscaling():
    # Two rows: red/green, blue/white. Each has two padding bytes.
    data = bytes.fromhex("0000ff 00ff00 ffff ff0000 ffffff ffff")
    preview = decode_rgb(
        data,
        width=2,
        height=2,
        bits_per_pixel=24,
        stride=8,
        byteorder="little",
        masks=(0xFF0000, 0xFF00, 0xFF),
    )
    assert preview.pixels == bytes.fromhex("ff0000 00ff00 0000ff ffffff")
    scaled = decode_rgb(
        data,
        width=2,
        height=2,
        bits_per_pixel=24,
        stride=8,
        byteorder="little",
        masks=(0xFF0000, 0xFF00, 0xFF),
        max_width=1,
        max_height=1,
    )
    assert (scaled.width, scaled.height, scaled.pixels) == (1, 1, b"\xff\x00\x00")


@pytest.mark.parametrize(
    "changes",
    [
        {"stride": 2},
        {"bits_per_pixel": 8},
        {"width": 0},
        {"masks": (0xFF00, 0xFF00, 0xFF)},
        {"masks": (0xA00000, 0xFF00, 0xFF)},
        {"byteorder": "invalid"},
        {"height": 20},
    ],
)
def test_bad_images_fall_back_instead_of_reading_invalid_pixels(changes):
    fields = dict(
        width=1,
        height=1,
        bits_per_pixel=32,
        stride=4,
        byteorder="little",
        masks=(0xFF0000, 0xFF00, 0xFF),
    )
    with pytest.raises(ValueError):
        decode_rgb(b"\0" * 4, **(fields | changes))
