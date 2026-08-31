"""Console entry point for comfy-network-tools."""

from __future__ import annotations

import argparse
import sys

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comfy-network-tools",
        description=(
            "Interactive admin for a central AI-model repository distributed to "
            "LAN hosts over SSH."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv if argv is not None else sys.argv[1:])
    from .ui.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
