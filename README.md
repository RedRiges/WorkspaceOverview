# Workspace Overview

lightweight, keyboard-first workspace overview for Xfce on X11

Workspace Overview aims to make it easy to find, activate, and move windows across workspaces—including windows hidden behind fullscreen applications. Inspired by the overview experience of macOS Mission Control, it is designed to fit naturally into Xfce rather than replace its window manager

> **Status: early development / v0.1 specification** 

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

## Keyboard and mouse controls (planned)

| Input | Action |
| --- | --- |
| `Super + Tab` | Open or close the overview |
| `Tab` / `Shift + Tab` | Select the next or previous workspace |
| Arrow keys | Select a window in the current workspace |
| `Enter` | Activate the selected window |
| `F2` | Enter window-move mode |
| Arrow keys, then `Enter` | Select the destination workspace and confirm the move |
| `Esc` | Cancel a pending move, or close the overview |
| Left click | Activate the selected window |

Moving a window **does not automatically switch the active workspace**. The overview remains open after a move. Navigation alone never activates or moves a window.

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

## Development setup (macOS)

The repository currently contains development tooling only. Application code,
the core, and the mock backend have not been implemented yet.

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

There are no Python source files or tests yet. pytest currently exits with code 5
(`no tests collected`). This is expected until actual tests are added; it is not
a passing test suite.

## Contributing and releases

The project is being developed in public from the beginning. APIs, interface details, and shortcuts may change before the first release. Issues and constructive feedback are welcome once the repository is ready to accept them.

No installation instructions are published yet because there is no usable release. Contribution guidelines will be added before accepting outside code contributions.

## License

Workspace Overview is licensed under the GNU General Public License version 3 only (`GPL-3.0-only`). See [LICENSE](LICENSE) for the full text.

AI-created commits identify the AI agent and model in their commit messages. See [AGENTS.md](AGENTS.md) for the attribution rules.

---

*Workspace Overview is an independent project, not affiliated with Apple, the Xfce project, or the XLibre project.*
