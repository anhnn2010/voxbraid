"""CLI foundation. Audio commands are intentionally not advertised in M0."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from voxbraid import __version__
from voxbraid.diagnostics import collect_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voxbraid",
        description="VoxBraid: multi-voice TXT-to-audio (M0 foundation; rendering comes later).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")
    subcommands.add_parser(
        "doctor", help="Inspect Python and optional audio executables (offline check)."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        for check in collect_diagnostics():
            status = "OK" if check.available else "MISSING"
            print(f"[{status}] {check.name}: {check.detail}")
        print("M0 only: preview/render commands will be implemented in later milestones.")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
