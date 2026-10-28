"""Native entry point. Never silently substitutes a mock backend."""

import sys

from workspace_overview.cli import parse_args
from workspace_overview.core.backend import BackendError


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)
    try:
        from workspace_overview.native import load_native

        native = load_native()
        if args.check:
            from workspace_overview.backends.x11 import create_backend

            backend = create_backend(
                native, lambda: 0, previews=args.previews is not False
            )
            try:
                snapshot = backend.snapshot()
                manager = backend.screen.get_window_manager_name() or "unknown"
                print(f"Window manager: {manager}")
                print(
                    f"Workspaces: {len(snapshot.workspaces)}; "
                    f"windows: {len(snapshot.windows)}"
                )
                composited = native.Gdk.Screen.get_default().is_composited()
                print(f"Compositor: {'active' if composited else 'inactive'}")
                print(f"Previews: {backend.preview_status}")
                print("Native X11 backend ready. No window operations were requested.")
            finally:
                backend.close()
            return 0
        from workspace_overview.ui.gtk import build_application

        app = build_application(native)
        result = app.run([sys.argv[0], *argv])
        return app.exit_status or result
    except BackendError as exc:
        print(f"workspace-overview: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
