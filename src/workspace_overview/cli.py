"""Options shared by the invoking process and the resident primary instance."""

import argparse


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Workspace Overview for Xfce/X11")
    command = parser.add_mutually_exclusive_group()
    command.add_argument(
        "--check", action="store_true", help="check native dependencies"
    )
    command.add_argument(
        "--background",
        action="store_true",
        help="start RAM capture without opening overview",
    )
    command.add_argument(
        "--quit",
        action="store_true",
        help="stop the resident process and clear its cache",
    )
    command.add_argument(
        "--clear-cache", action="store_true", help="discard cached images"
    )
    command.add_argument(
        "--status", action="store_true", help="show resident/cache status"
    )
    capture = parser.add_mutually_exclusive_group()
    capture.add_argument(
        "--no-previews",
        dest="previews",
        action="store_false",
        help="disable capture and clear cached images in the running instance",
    )
    capture.add_argument(
        "--previews",
        dest="previews",
        action="store_true",
        help="enable preview capture",
    )
    parser.set_defaults(previews=None)
    return parser.parse_args(argv)
