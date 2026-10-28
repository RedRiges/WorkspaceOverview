"""Shared dimensions for the single-row workspace strip."""


def strip_dimensions(width: int, workspace_count: int) -> tuple[int, int, int]:
    """Return workspace columns, card columns and minimum panel width.

    Fit the complete row when possible, reserving outer padding, gaps and room
    for a vertical scrollbar. Overflow horizontally instead of shrinking cards
    below a readable size or wrapping workspaces into another row.
    """
    workspaces = max(1, workspace_count)
    panel_width = max(264, (width - 64 - 12 * (workspaces - 1)) // workspaces)
    cards = max(1, min(3, (panel_width - 48) // 224))
    return workspaces, cards, panel_width
