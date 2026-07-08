"""Unified command-line entry point: ``gacdi <database> [options]``.

Every repository shares the same option surface so the Galaxy wrappers stay
consistent. The CLI translates arguments into a :class:`RunConfig`, dispatches to
the registered importer, prints a short report and returns a stable exit code.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .base import RunConfig
from .errors import GacdiError, InputError
from .importers import REGISTRY, get_importer

log = logging.getLogger("gacdi")


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input-mode",
        choices=("manifest", "accession", "query"),
        default="manifest",
        help="How the selection is provided.",
    )
    src = parser.add_argument_group("selection source")
    src.add_argument("--manifest", help="Path to a manifest file (manifest mode).")
    src.add_argument("--accessions", help="Comma/space/newline separated accessions (accession mode).")
    src.add_argument("--query-json", dest="query_json", help="Path to a JSON query document (query mode).")

    out = parser.add_argument_group("outputs")
    out.add_argument("--output-dir", default="downloads", help="Directory for downloaded files (collection).")
    out.add_argument("--summary", default="summary.tsv", help="Path for the summary TSV.")

    ctl = parser.add_argument_group("behaviour")
    ctl.add_argument("--token", help="Controlled-access token file (where supported).")
    ctl.add_argument("--assign-ext", dest="assign_ext", help="Force a Galaxy datatype extension.")
    ctl.add_argument("--max-files", type=int, help="Cap on the number of files to download.")
    ctl.add_argument("--max-bytes", type=int, help="Approximate byte budget; stop once exceeded.")
    ctl.add_argument("--retries", type=int, default=3, help="Retries per file on transient failure.")
    ctl.add_argument("--jobs", type=int, default=1, help="Parallelism/threads passed to backends.")
    ctl.add_argument(
        "--set",
        dest="options_raw",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Importer-specific option (repeatable), e.g. --set hub=https://tcga.xenahubs.net.",
    )
    ctl.add_argument("--dry-run", action="store_true", help="Resolve the selection but do not download.")
    ctl.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Exit 0 even if some files failed (failures still recorded in the summary).",
    )
    ctl.add_argument("--verbose", action="store_true", help="Verbose logging.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gacdi", description="Galaxy Cancer Data Importers.")
    parser.add_argument("--version", action="version", version=f"gacdi {__version__}")
    sub = parser.add_subparsers(dest="database", required=True, metavar="DATABASE")
    for name in sorted(REGISTRY):
        db_parser = sub.add_parser(name, help=f"Import data from {name.upper()}.")
        _add_common_arguments(db_parser)
    return parser


def _parse_options(pairs: list[str]) -> dict:
    options: dict = {}
    for item in pairs:
        if "=" not in item:
            raise InputError(f"--set expects KEY=VALUE, got '{item}'.")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise InputError(f"--set expects a non-empty key, got '{item}'.")
        options[key] = value.strip()
    return options


def _config_from_args(args: argparse.Namespace) -> RunConfig:
    return RunConfig(
        options=_parse_options(args.options_raw),
        input_mode=args.input_mode,
        manifest=args.manifest,
        accessions=args.accessions,
        query_json=args.query_json,
        output_dir=args.output_dir,
        summary=args.summary,
        token=args.token,
        assign_ext=args.assign_ext,
        max_files=args.max_files,
        max_bytes=args.max_bytes,
        retries=args.retries,
        jobs=args.jobs,
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        importer = get_importer(args.database)
        summary = importer.run(_config_from_args(args))
    except GacdiError as exc:
        log.error("%s", exc)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        log.error("Interrupted.")
        return 130

    ok, failed = len(summary.ok), len(summary.failed)
    log.info(
        "%s: %d file(s) downloaded, %d failed, %d bytes total.",
        summary.database,
        ok,
        failed,
        summary.total_bytes(),
    )
    if failed and not args.continue_on_error and not args.dry_run:
        log.error("%d file(s) failed; see the summary dataset for details.", failed)
        return 4
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
