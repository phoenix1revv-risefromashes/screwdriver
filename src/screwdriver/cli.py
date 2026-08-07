"""Command-line interface for Screwdriver."""

import argparse
from collections.abc import Sequence

from screwdriver import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the Screwdriver argument parser."""

    parser = argparse.ArgumentParser(
        prog="screwdriver",
        description="Inspect and diagnose Linux robotics systems.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    commands.add_parser(
        "inspect",
        help="Inspect the Linux host system.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Screwdriver CLI."""

    args = build_parser().parse_args(argv)

    if args.command == "inspect":
        print("Screwdriver foundation ready. Host inspection is the next feature.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())