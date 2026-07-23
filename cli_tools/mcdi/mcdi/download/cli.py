"""``mcdi download`` — download the files listed in a GDC or PDC manifest."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ..errors import InputError
from . import config, engine
from .sources import SOURCES, detect_source

log = logging.getLogger("mcdi.download")


def add_arguments(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``download`` subcommand to ``subparsers``."""
    parser = subparsers.add_parser(
        "download",
        help="Download files listed in a GDC or PDC manifest.",
    )
    parser.add_argument("--manifest", required=True, type=Path, help="Path to the exported manifest file")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory to download files into")
    parser.add_argument(
        "--source",
        choices=sorted(SOURCES),
        help="Data commons the manifest came from (auto-detected from the header if omitted)",
    )
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent downloads (default: 4)")
    parser.add_argument(
        "--verify-checksum",
        action="store_true",
        help="Verify each downloaded file's md5 against the manifest",
    )
    parser.add_argument(
        "--token-file",
        help="Path to a file containing a GDC auth token (overrides GDC_TOKEN env var)",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace) -> int:
    if not args.manifest.is_file():
        raise InputError(f"manifest not found: {args.manifest}")

    source_name = args.source or detect_source(args.manifest)
    source_cls = SOURCES[source_name]

    if source_name == "gdc":
        source = source_cls(token=config.gdc_token(args.token_file))
    else:
        source = source_cls()

    entries = source.parse_manifest(args.manifest)
    if not entries:
        log.warning("Manifest contained no files.")
        return 1

    log.info("Detected source: %s (%d file(s))", source_name, len(entries))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = engine.run(
        entries,
        source,
        args.output_dir,
        workers=args.workers,
        verify=args.verify_checksum,
    )

    failed = [r for r in results if r.status == "error"]
    mismatches = [r for r in results if r.status == "checksum_mismatch"]
    print(
        f"\nDone: {len(results)} total, {len(failed)} error(s), "
        f"{len(mismatches)} checksum mismatch(es)"
    )
    return 1 if failed or mismatches else 0
