"""Shared grid dimensions used for rendering and keyboard navigation."""


def grid_columns(width: int, workspace_count: int) -> tuple[int, int]:
    workspaces = max(1, min(workspace_count, 3, max(1, width - 32) // 480))
    panel_width = max(1, width - 32) // workspaces
    cards = max(1, min(3, (panel_width - 48) // 224))
    return workspaces, cards
