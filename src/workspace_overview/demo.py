"""Console walkthrough using synthetic data only; no GUI or real window access."""

from workspace_overview.backends.mock import MockBackend
from workspace_overview.core.overview import Overview


def describe(overview: Overview) -> None:
    state = overview.state
    for workspace in state.snapshot.workspaces:
        active = (
            " [active]" if workspace.id == state.snapshot.active_workspace_id else ""
        )
        print(f"{workspace.name}{active}")
        for window in state.snapshot.windows_on(workspace.id):
            selected = "*" if window.id == state.selected_window_id else " "
            preview = "preview" if overview.previews.get(window.id) else "icon/title"
            print(f"  {selected} {window.title} ({preview})")


def main() -> None:
    overview = Overview(MockBackend.demo())
    overview.open()
    print("Synthetic session — no real windows are accessed.\n")
    describe(overview)
    overview.select_window(102)
    overview.begin_move()
    overview.select_destination(30)
    if not overview.confirm_move():
        raise RuntimeError(overview.state.error)
    print("\nMoved Browser to Empty; Work remains active.\n")
    describe(overview)
    if not overview.activate_selected():
        raise RuntimeError(overview.state.error)
    print("\nActivated Browser on Empty; overview closed.")


if __name__ == "__main__":
    main()
