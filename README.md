# Workspace Overview

lightweight, keyboard-first workspace overview for Xfce on X11

Workspace Overview aims to make it easy to find, activate, and move windows across workspaces—including windows hidden behind fullscreen applications. Inspired by the overview experience of macOS Mission Control, it is designed to fit naturally into Xfce rather than replace its window manager

> **Status: early native GTK3/X11 implementation, ready for integration testing**

## Target platform

- **OS:** Void Linux (x86_64, glibc, runit)
- **Desktop:** Xfce 4.20 with Xfwm4
- **Display server:** XLibre (X11)
- **Initial scope:** one physical monitor, one X11 session

Support for other X11 desktops or distributions may be considered later; it is not a v0.1 target. Wayland is out of scope.

## Planned features (v0.1)

- List all workspaces managed by Xfwm4
- Discover normal application windows, including minimized, obscured, and fullscreen windows
- Display workspaces in a grid, with non-overlapping cards for their windows
- Capture a **static preview** of each available window when the overview opens
- Activate a selected window using the keyboard or mouse
- Move windows between workspaces using keyboard-first controls
- React gracefully when windows appear, disappear, or move while the overview is open
- Fall back to a window icon and title when a preview cannot be captured

**Nested X servers:** A Xephyr session is treated as one window of the main X11 session. The overview does not inspect or control windows inside Xephyr, including applications managed by a nested window manager such as IceWM.

## Keyboard and mouse controls

| Input | Action |
| --- | --- |
| `Super + Tab` | Open or close the overview |
| `Tab` / `Shift + Tab` | Select the next or previous workspace |
| Arrow keys | Select a window; at the card-grid edge, select the neighboring workspace |
| `Enter` | Activate the selected window |
| `F2` | Enter window-move mode |
| Arrow keys, then `Enter` | Select the destination workspace and confirm the move |
| `Esc` | Cancel a pending move, or close the overview |
| Left click | Activate the selected window |

Moving a window **does not automatically switch the active workspace**. The overview remains open after a move. Navigation alone never activates or moves a window.

Workspaces follow their Xfce number, from left to right and then top to bottom.
Tab moves forward through that order and wraps; Shift+Tab moves backward. Arrows
follow the visible grid, including empty workspaces, and stop at its outer edges.

The global `Super + Tab` shortcut will be configured through Xfce rather than by installing a system-wide keyboard hook.

## Design direction

A midpoint between **macOS Mission Control** and a **native Xfce dashboard**:

- A fullscreen grid of workspaces with consistent, non-overlapping window cards
- Static previews preserving the content's aspect ratio
- GTK3 widgets, system fonts, icons, and theme colors wherever practical
- Clear, separate visual states for the active workspace and keyboard-selected window
- A subtly translucent desktop-dimming backdrop where supported by the compositor, with an opaque fallback
- No animations in v0.1

## Architecture

| Component | Responsibility |
| --- | --- |
| **Core** | Pure-Python state model, selection, navigation, and move workflow; no GTK/X11 dependency |
| **Mock backend** | Synthetic workspaces, windows, and images for development and tests |
| **X11 backend** | Window discovery, activation, workspace changes, and notifications via libwnck/X11 |
| **Preview backend** | One-shot window-image capture using XComposite; graceful fallback |
| **GTK3 UI** | Workspace grid, cards, focus indicators, input handling, and theme integration |

**Language and dependencies:** Python (3.14 on the target Void system; keep the platform-independent core compatible with Python 3.12+), GTK3/PyGObject, libwnck, and XComposite. The project uses **uv** for Python project management. Native GTK/libwnck components are installed through the system package manager; they are not vendored into the uv environment.

The initial development workflow uses macOS for Core/Mock tests and Void Linux for real X11 integration. macOS is **not** a supported runtime target.

## Out of scope for v0.1

- Wayland or multi-monitor support
- Live previews, animations, or drag-and-drop
- Creating, deleting, or renaming workspaces
- Controlling windows inside other X servers
- Replacing Xfwm4 or changing Xfce settings automatically
- A mandatory background daemon
- Network access, telemetry, or elevated privileges at runtime

## Technical notes

- Capturing obscured windows is a key feasibility test. Some minimized or fullscreen windows may not expose a usable current image; those windows will display an icon and title instead.
- The X11 window manager ultimately decides whether activation and workspace-move requests succeed. The application must verify results and handle failures without disrupting other windows.
- Window titles can contain private information; the project should not persist window titles or previews to disk by default.

Created mainly by LLMs with a sysadmin-level-competency real person supervision. DO NOT USE IN PRODUCTION

## Run on Void Linux / Xfce (real windows)

Run from a terminal inside your normal Xfce **X11** session, as your desktop user.
The native entry point always uses real windows; it never substitutes mock data.

Install the distribution packages:

```sh
sudo xbps-install -S python3 python3-gobject gtk+3 libwnck python3-xlib
```

From an existing checkout:

```sh
git pull --ff-only
./scripts/run-x11 --check
./scripts/run-x11
```

For a new checkout, first run
`git clone https://github.com/RedRiges/WorkspaceOverview.git` and
`cd WorkspaceOverview`. GitHub login is not required for this public repository.

`scripts/run-x11` uses `/usr/bin/python3` and the source in this checkout. This
keeps the interpreter compatible with Void's compiled PyGObject bindings. The
development `.venv` created by uv may use a different Python and cannot normally
import those bindings; use the script for native testing. No global pip install
or GTK compilation is needed. Updating the checkout updates the native app.

`--check` reports dependency/display errors, window-manager name, workspace and
window counts, compositor state, and preview availability. It does not activate
or move anything, and does not print window titles. Launching without `--check`
opens the fullscreen overview. Use `./scripts/run-x11 --no-previews` to diagnose
the window controls separately from XComposite capture.

For `Super+Tab`, copy the absolute path printed by `realpath scripts/run-x11`
into **Xfce Settings → Keyboard → Application Shortcuts**, and assign the shortcut
manually. Repeating the launch command toggles an existing overview through the
session D-Bus. The process exits when the overview closes; no daemon is installed.

### First real-session checks

1. Open two applications on different workspaces; minimize one window and make
   another fullscreen. Launch the overview and check that both appear.
2. Use Tab / Shift+Tab to select the next / previous numbered workspace. Use
   arrows to select cards and cross into adjacent workspaces at a card-grid edge,
   including empty workspaces. Only selection should change.
3. Press Enter or click a card. The chosen window should receive focus; a
   minimized window should be restored and its workspace activated.
4. Reopen, select a window, press F2, select a destination with arrows, and press
   Enter. The window should move while the active workspace stays unchanged and
   the overview remains open. Esc cancels an unconfirmed move.
5. Open or close another application while the overview is visible. The cards
   should update without selecting or acting on a different window accidentally.

Window actions wait up to 1.5 seconds per request for confirmation by the window
manager. Errors are displayed in the overview. The application does not change
Xfce settings, window geometry, the compositor configuration, or workspace count.

Pinned windows are shown on the current active workspace with an **all
workspaces** label. They can be activated; moving them requires unpinning through
the window manager first. Normal and dialog windows are included; panels, desktop
windows, tooltips, and the overview itself are excluded.

Window-state badges appear in the upper-right corner of the thumbnail, including
when only an application icon is available:

- **На весь экран**: fullscreen icon and an accent-colored badge.
- **Развёрнуто**: maximize icon and an accent outline for windows maximized in
  both dimensions. Fullscreen takes precedence if both states are reported.
- **Свёрнуто**: minimize icon and a neutral outlined badge.

The minimized badge can appear alongside the fullscreen or maximized badge.
They follow the window's state as the overview refreshes. Badges pass clicks
through to the card.

Previews use existing XComposite pixmaps, including window-manager frames when
applicable. The app does not redirect windows itself or capture the desktop behind
them. Minimized, unredirected fullscreen, or otherwise unavailable images fall
back to the real application icon and title. Thumbnails stay in memory. Preview
availability must be checked on the actual Xfwm4/XLibre setup.

This version supports one monitor and X11 only. With an active compositor and an
RGBA visual, the theme-colored backdrop is translucent (72% opacity). Text and
previews retain their full opacity. Without compositing, the backdrop is opaque;
this also updates if compositing changes while the overview is open. Use
`./scripts/run-x11 --check` to check whether the compositor is active.
Automated Linux integration tests use Xvfb and Openbox, with and without xcompmgr;
they do not establish compatibility with every Xfwm4/XLibre configuration.

Package/API references: [Void PyGObject](https://github.com/void-linux/void-packages/blob/master/srcpkgs/python3-gobject/template),
[Void libwnck](https://github.com/void-linux/void-packages/blob/master/srcpkgs/libwnck/template),
[GTK3](https://docs.gtk.org/gtk3/), and
[python-xlib XComposite](https://github.com/python-xlib/python-xlib/blob/master/Xlib/ext/composite.py).

## Development setup (macOS)

The platform-independent core and in-memory mock backend run on macOS. Native
GTK/X11 testing uses Linux; macOS checks do not exercise a real window manager.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed
(`brew install uv` on macOS), then run these commands from the repository root:

```sh
uv sync --locked
uv run --locked python --version
```

The `.python-version` file selects Python 3.14 for local development. uv downloads
a suitable interpreter if needed and creates `.venv` inside the project. It does
not replace the system Python. The project declares Python 3.12+ compatibility;
Ruff uses that minimum version when checking syntax and suggesting upgrades.

`pytest` and `ruff` are development dependencies. Their resolved versions are
recorded in `uv.lock`, which is committed alongside `pyproject.toml`. No GTK or
X11 dependencies are needed for this setup.

Development commands:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
```

Run the console walkthrough with synthetic workspaces and windows:

```sh
uv run --locked workspace-overview-demo
```

It lists three workspaces and four windows, moves the synthetic Browser to the
empty workspace, then activates it. It never reads or controls real windows.
This is a scripted demonstration, not an interactive window overview.

## Core and mock backend

The package lives in `src/workspace_overview`:

| Module | Responsibility |
| --- | --- |
| `core/models.py` | Immutable workspaces, windows, validated snapshots, and RGB previews |
| `core/backend.py` | Backend protocol and expected operation errors |
| `core/navigation.py` | Arrow navigation through a row-major grid |
| `core/overview.py` | Selection, opening/closing, move confirmation, and state reconciliation |
| `backends/mock.py` | In-memory session, generated previews, and simulated failures |
| `backends/x11.py` | libwnck discovery, activation, workspace moves, and bounded confirmation |
| `previews/` | XComposite capture and TrueColor-to-RGB thumbnail conversion |
| `ui/gtk.py` | Fullscreen GTK3 cards, keyboard/mouse controls, and session refresh |

The core has no runtime dependencies outside the Python standard library. For
example, from `uv run python`:

```python
from workspace_overview.backends.mock import MockBackend
from workspace_overview.core.overview import Overview

backend = MockBackend.demo()
overview = Overview(backend)
overview.open()
overview.select_window(102)  # Synthetic Browser; does not activate it.
overview.begin_move()
overview.select_destination(30)
overview.confirm_move()  # Returns True only after observing the result.

assert overview.state.snapshot.active_workspace_id == 10
assert overview.state.selected_workspace_id == 30
assert overview.state.is_open
```

`cycle_workspace(1)` / `cycle_workspace(-1)` implement Tab / Shift+Tab with wrap.
`navigate(Direction.RIGHT, columns=2, workspace_columns=3)` implements an arrow
key; the caller supplies both displayed grids' column counts. At a card-grid edge
or on an empty workspace, navigation crosses into the adjacent workspace. It
stops at the outer workspace-grid edges, including incomplete final rows. Omit
`workspace_columns` for card-only navigation. In move mode arrows select a
destination workspace.
`enter()` confirms a move or activates the selected window. `escape()` cancels a
move first, then closes the overview on the next call. `toggle()` opens/closes it.
Mouse handlers can use `select_window()` followed by `activate_selected()`.

Successful moves keep the overview open and select the moved window at its
destination without changing the active workspace. Successful activation closes
the overview. Backend failures leave it open and populate `state.error`.

Call `refresh()` after external changes. Selection uses stable IDs, surviving
reordering; removal falls back to an available window/workspace. A pending move
is cancelled if its source disappears, moves externally, or its destination
disappears. Mock helpers `add_window()`, `remove_window()`, `set_snapshot()`, and
`fail_next("move", "Refused")` simulate these conditions.

Previews are captured once per opening and once for newly discovered windows.
`overview.previews` is read-only; a `None` entry means show the window's icon/title.
The mock generates small RGB checkerboards in memory. Closing clears the preview
cache; no titles or images are saved to disk by the core or backend.

The backend contract is synchronous. The core verifies action results using a
fresh snapshot, including rejection of silent no-ops. The X11 adapter pumps the
GLib event loop while awaiting confirmation, with a bounded timeout; UI actions
are guarded against reentrancy. The overview refreshes its snapshot every 300 ms.
Existing thumbnails stay static for the current opening.

The default test suite skips `tests/integration`. CI additionally enables those
tests on a disposable Xvfb display with a real window manager, with and without a
compositor. The tests create their own GTK windows and exercise native capture,
actions, X11 keyboard input, and the rendered backdrop's alpha channel.
Do not enable `WORKSPACE_OVERVIEW_NATIVE_TESTS=1` on your everyday desktop.

## Contributing and releases

The project is being developed in public from the beginning. APIs, interface details, and shortcuts may change before the first release. Issues and constructive feedback are welcome once the repository is ready to accept them.

The checkout can be run for integration testing as described above; there is no
stable release yet. Contribution guidelines will be added before accepting
outside code contributions.

## License

Workspace Overview is licensed under the GNU General Public License version 3 only (`GPL-3.0-only`). See [LICENSE](LICENSE) for the full text.

AI-created commits identify the AI agent and model in their commit messages. See [AGENTS.md](AGENTS.md) for the attribution rules.

---

*Workspace Overview is an independent project, not affiliated with Apple, the Xfce project, or the XLibre project.*
