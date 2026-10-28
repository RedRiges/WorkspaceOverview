"""Native entry point. Never silently substitutes a mock backend."""

import argparse
import sys

from workspace_overview.core.backend import BackendError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Workspace Overview for Xfce/X11")
    parser.add_argument(
        "--check", action="store_true", help="check native dependencies and X11 session"
    )
    parser.add_argument(
        "--no-previews", action="store_true", help="use window icons and titles only"
    )
    args = parser.parse_args(argv)
    try:
        from workspace_overview.native import load_native

        native = load_native()
        if args.check:
            from workspace_overview.backends.x11 import create_backend

            backend = create_backend(native, lambda: 0, previews=not args.no_previews)
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

        app = build_application(native, previews=not args.no_previews)
        result = app.run([sys.argv[0]])
        return app.exit_status or result
    except BackendError as exc:
        print(f"workspace-overview: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
