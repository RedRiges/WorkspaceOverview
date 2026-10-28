"""Adapter boundary validation and grid edge behavior."""

import pytest

from workspace_overview.core.models import Preview, Snapshot, Window, Workspace
from workspace_overview.core.navigation import Direction, grid_entry, grid_neighbor


@pytest.mark.parametrize(
    "changes",
    [
        {"workspaces": (Workspace(10, "A"), Workspace(10, "B"))},
        {"windows": (Window(1, 10, "A"), Window(1, 10, "B"))},
        {"windows": (Window(1, 99, "Missing workspace"),)},
        {"active_workspace_id": 99},
        {"active_window_id": 99},
        {"windows": (Window(1, 20, "Elsewhere"),), "active_window_id": 1},
        {"windows": (Window(1, 10, "Hidden", minimized=True),), "active_window_id": 1},
    ],
)
def test_reject_inconsistent_adapter_snapshots(changes):
    fields = {
        "workspaces": (Workspace(10, "A"), Workspace(20, "B")),
        "windows": (Window(1, 10, "Terminal"),),
        "active_workspace_id": 10,
    }
    with pytest.raises(ValueError):
        Snapshot(**(fields | changes))


def test_snapshot_detaches_collections_from_adapter():
    windows = [Window(1, 10, "Terminal")]
    snapshot = Snapshot((Workspace(10, "A"),), windows, 10)
    windows.clear()
    assert snapshot.window(1).title == "Terminal"


@pytest.mark.parametrize("width,height,pixels", [(0, 1, b""), (1, 1, b"ab")])
def test_reject_invalid_preview_buffers(width, height, pixels):
    with pytest.raises(ValueError):
        Preview(width, height, pixels)


@pytest.mark.parametrize(
    "index,direction,expected",
    [
        (0, Direction.LEFT, 0),
        (0, Direction.UP, 0),
        (0, Direction.RIGHT, 1),
        (2, Direction.RIGHT, 2),  # Don't wrap to the next row.
        (3, Direction.LEFT, 3),
        (1, Direction.DOWN, 4),
        (2, Direction.DOWN, 4),  # Last row has only two cards.
        (4, Direction.DOWN, 4),
        (4, Direction.RIGHT, 4),
        (4, Direction.UP, 1),
    ],
)
def test_grid_edges_and_incomplete_rows(index, direction, expected):
    assert grid_neighbor(index, 5, 3, direction) == expected


@pytest.mark.parametrize("index,count,columns", [(0, 0, 2), (0, 1, 0), (2, 2, 1)])
def test_invalid_grid_input_is_rejected(index, count, columns):
    with pytest.raises(ValueError):
        grid_neighbor(index, count, columns, Direction.DOWN)


@pytest.mark.parametrize(
    "source,count,direction,expected",
    [
        (4, 5, Direction.RIGHT, 3),
        (3, 5, Direction.LEFT, 4),
        (4, 5, Direction.DOWN, 1),
        (2, 5, Direction.UP, 4),
        (8, 2, Direction.RIGHT, 0),
        (8, 2, Direction.LEFT, 1),
        (8, 2, Direction.DOWN, 1),
    ],
)
def test_enter_adjacent_workspace_from_near_edge(source, count, direction, expected):
    assert grid_entry(source, count, 3, direction) == expected
