"""CLI entrypoint for running retail chain parsers."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Protocol

from core.excel_export import export_stores_to_excel
from core.logging_config import setup_logging
from core.models import StoreRecord
from parsers.kb_parser import KBParser
from parsers.maria_ra_parser import MariaRaParser
from parsers.monetka_parser import MonetkaParser


class ParserInterface(Protocol):
    """Type protocol for all parser classes."""

    def parse(self) -> list[StoreRecord]:
        """Parse stores and return unified records."""


def build_parser() -> argparse.ArgumentParser:
    """Build top-level CLI parser."""
    parser = argparse.ArgumentParser(description="Retail stores parser system")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run parsers and export Excel")
    run_parser.add_argument(
        "--network",
        choices=["kb", "monetka", "maria_ra"],
        help="Run parser only for selected network",
    )
    return parser


def get_selected_parsers(network: str | None) -> list[tuple[str, ParserInterface]]:
    """Return parser instances depending on CLI selection."""
    mapping: dict[str, tuple[str, ParserInterface]] = {
        "kb": ("kb", KBParser()),
        "monetka": ("monetka", MonetkaParser()),
        "maria_ra": ("maria_ra", MariaRaParser()),
    }
    if network:
        return [mapping[network]]
    return list(mapping.values())


def run(network: str | None = None) -> int:
    """Run selected parsers and export combined result."""
    setup_logging()
    logger = logging.getLogger("main")
    Path("output").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    all_stores: list[StoreRecord] = []
    try:
        for parser_name, parser_instance in get_selected_parsers(network):
            logger.info("Running parser: %s", parser_name)
            try:
                stores = parser_instance.parse()
                logger.info("Parser %s completed: %s stores", parser_name, len(stores))
                all_stores.extend(stores)
            except Exception as exc:
                logger.error("Parser %s failed: %s", parser_name, exc, exc_info=True)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")

    export_stores_to_excel(all_stores, output_path="output/stores.xlsx")
    logger.info("Export completed: output/stores.xlsx (%s stores)", len(all_stores))
    return 0


def main() -> int:
    """CLI main function."""
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        return run(network=None)
    if args.command != "run":
        parser.print_help()
        return 1
    return run(network=args.network)


if __name__ == "__main__":
    raise SystemExit(main())
