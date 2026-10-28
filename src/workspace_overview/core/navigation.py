"""Navigation through row-major grids; no platform or UI dependencies."""

from enum import StrEnum


class Direction(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


def grid_neighbor(index: int, count: int, columns: int, direction: Direction) -> int:
    """Clamp at grid edges, choosing the last item in an incomplete next row."""
    if columns < 1:
        raise ValueError("A grid must have at least one column")
    if not 0 <= index < count:
        raise ValueError("The selected index must be inside the grid")
    direction = Direction(direction)
    row, column = divmod(index, columns)
    match direction:
        case Direction.LEFT:
            return index - 1 if column > 0 else index
        case Direction.RIGHT:
            return index + 1 if column < columns - 1 and index + 1 < count else index
        case Direction.UP:
            return index - columns if row > 0 else index
        case Direction.DOWN:
            return (
                min(index + columns, count - 1)
                if (row + 1) * columns < count
                else index
            )
    raise AssertionError("Unreachable direction")


def grid_entry(index: int, count: int, columns: int, direction: Direction) -> int:
    """Enter a neighboring panel from the opposite edge, preserving row/column."""
    if index < 0 or count < 1 or columns < 1:
        raise ValueError("Grid entry requires a valid source and nonempty target")
    row, column = divmod(index, columns)
    last_row = (count - 1) // columns
    match Direction(direction):
        case Direction.RIGHT:
            return min(row, last_row) * columns
        case Direction.LEFT:
            return min((min(row, last_row) + 1) * columns, count) - 1
        case Direction.DOWN:
            return min(column, count - 1)
        case Direction.UP:
            return min(last_row * columns + column, count - 1)
    raise AssertionError("Unreachable direction")
