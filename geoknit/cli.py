"""Command-line entry point: ``geoknit``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from geoknit import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the ``geoknit`` command."""
    parser = argparse.ArgumentParser(
        prog="geoknit",
        description="Local visual programming for geospatial analysis.",
    )
    parser.add_argument("--version", action="version", version=f"geoknit {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
