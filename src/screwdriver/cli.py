from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Build and return the Screwdriver command-line parser."""

    parser = argparse.ArgumentParser(
        prog="screwdriver",
        description="Inspect and analyze Linux robotic systems.",
    )

    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser(
        "inspect",
        help="Create a robotic-system snapshot.",
    )

    modes = inspect_parser.add_mutually_exclusive_group()

    modes.add_argument(
        "--local",
        action="store_true",
        help="Perform a complete offline inspection.",
    )

    modes.add_argument(
        "--agentic",
        action="store_true",
        help="Create an AI-organized inspection.",
    )

    inspect_parser.add_argument(
        "--focus",
        help="Focus agentic inspection on selected components.",
    )

    inspect_parser.add_argument(
        "--output",
        type=Path,
        default=Path("."),
        help="Directory for generated files.",
    )

    analyze_parser = commands.add_parser(
        "analyze",
        help="Analyze an existing inspection snapshot.",
    )

    analyze_parser.add_argument(
        "snapshot",
        type=Path,
        help="Path to the inspection snapshot.",
    )

    analyze_parser.add_argument(
        "--output",
        type=Path,
        default=Path("."),
        help="Directory for generated reports.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Screwdriver command-line interface."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inspect":
        mode = "agentic" if args.agentic else "local"

        if args.focus and mode != "agentic":
            parser.error("--focus requires --agentic")

        print(f"Inspection mode: {mode}")
        print(f"Output directory: {args.output}")

        if args.focus:
            print(f"Focus: {args.focus}")

        print("System inspection is not implemented yet.")
        return 0

    if args.command == "analyze":
        print(f"Snapshot: {args.snapshot}")
        print(f"Output directory: {args.output}")
        print("System analysis is not implemented yet.")
        return 0

    parser.error("unknown command")
    return 2