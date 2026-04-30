"""Placeholder command line interface for the builder scaffold."""

from __future__ import annotations

import argparse

from welfare_inspections import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="welfare-inspections",
        description=(
            "Placeholder CLI for the Israel welfare inspection dataset builder."
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
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
