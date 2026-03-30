"""CLI entrypoint for running retail chain parsers."""

from __future__ import annotations

import argparse
import logging
from time import perf_counter
from typing import Protocol

from dotenv import load_dotenv

from core.config import get_default_output_path, get_default_snapshot_path
from core.excel_export import export_stores_to_excel
from core.logging_config import setup_logging
from core.models import StoreRecord
from parsers.kb_parser import KBParser
from parsers.maria_ra_parser import MariaRaParser
from parsers.monetka_parser import MonetkaParser

EXIT_SUCCESS = 0
EXIT_RUNTIME_FAILURE = 1
EXIT_INTERRUPTED = 130


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
    run_parser.add_argument(
        "--output",
        default=get_default_output_path(),
        help="Path to the generated Excel report",
    )
    run_parser.add_argument(
        "--snapshot",
        default=get_default_snapshot_path(),
        help="Optional path to the diff snapshot JSON file",
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


def run(
    network: str | None = None,
    *,
    output_path: str | None = None,
    snapshot_path: str | None = None,
) -> int:
    """Run selected parsers and export combined result."""
    setup_logging()
    logger = logging.getLogger("main")
    started_at = perf_counter()
    resolved_output_path = output_path or get_default_output_path()
    resolved_snapshot_path = snapshot_path if snapshot_path is not None else get_default_snapshot_path()

    selected_parsers = get_selected_parsers(network)
    logger.info(
        "Run started: parsers=%s output=%s snapshot=%s",
        ",".join(parser_name for parser_name, _ in selected_parsers),
        resolved_output_path,
        resolved_snapshot_path or "<auto>",
    )

    all_stores: list[StoreRecord] = []
    failed_parsers: list[str] = []

    try:
        for parser_name, parser_instance in selected_parsers:
            logger.info("Running parser: %s", parser_name)
            try:
                stores = parser_instance.parse()
            except Exception as exc:
                failed_parsers.append(parser_name)
                logger.error("Parser %s failed: %s", parser_name, exc, exc_info=True)
                continue

            logger.info("Parser %s completed: %s stores", parser_name, len(stores))
            all_stores.extend(stores)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return EXIT_INTERRUPTED

    diff_result = export_stores_to_excel(
        all_stores,
        output_path=resolved_output_path,
        snapshot_path=resolved_snapshot_path,
    )
    duration_seconds = perf_counter() - started_at
    logger.info(
        "Run finished: stores=%s added=%s removed=%s changed=%s duration_seconds=%.2f",
        len(all_stores),
        len(diff_result.added),
        len(diff_result.removed),
        len(diff_result.changed),
        duration_seconds,
    )
    if failed_parsers:
        logger.error(
            "Run finished with parser failures: failed=%s successful=%s total=%s exit_code=%s",
            ",".join(failed_parsers),
            len(selected_parsers) - len(failed_parsers),
            len(selected_parsers),
            EXIT_RUNTIME_FAILURE,
        )
        return EXIT_RUNTIME_FAILURE
    return EXIT_SUCCESS


def main() -> int:
    """CLI main function."""
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        return run()
    if args.command != "run":
        parser.print_help()
        return 1

    return run(
        network=args.network,
        output_path=args.output,
        snapshot_path=args.snapshot,
    )


if __name__ == "__main__":
    raise SystemExit(main())
