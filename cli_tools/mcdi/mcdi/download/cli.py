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
        "-x",
        "--extract",
        action="store_true",
        help="Extract recognized archives (.tar.gz, .tgz, .tar.bz2, .tar.xz, .tar, .zip, .gz, .bz2, .xz) "
             "in place after download, keeping only the extracted contents at the manifest's output "
             "path. On success the archive itself moves to a sibling '<output-dir>.mcdi-archives' "
             "directory (not deleted); on failure it's left where it was downloaded. Off by default.",
    )
    parser.add_argument(
        "--token-file",
        help="Path to a file containing a GDC auth token (overrides GDC_TOKEN env var)",
    )
    parser.add_argument(
        "--retries", type=int, default=2,
        help="Extra attempts for files that fail transiently (network errors, 429/5xx, checksum "
             "mismatches) within this run, on top of each request's own transport-level retries "
             "(default: 2). Useful in contexts like a Galaxy job where nothing will rerun the "
             "command for you on a retry.",
    )
    parser.add_argument(
        "--retry-backoff", type=float, default=5.0,
        help="Seconds to wait before each retry pass, multiplied by the attempt number (default: 5.0)",
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

    log.info("Checking that all %d file(s) are accessible before downloading anything...", len(entries))
    failures = engine.check_access(
        entries, source, output_dir=args.output_dir, verify=args.verify_checksum, extract=args.extract,
        workers=args.workers,
    )
    if failures:
        log.error(
            "%d of %d file(s) failed the pre-flight access check; aborting before downloading anything.",
            len(failures), len(entries),
        )
        for failure in failures:
            log.error("  %s (%s): %s", failure.entry.filename, failure.entry.file_id, failure.detail)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = engine.run(
        entries,
        source,
        args.output_dir,
        workers=args.workers,
        verify=args.verify_checksum,
        extract=args.extract,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
    )

    failed = [r for r in results if r.status == "error"]
    mismatches = [r for r in results if r.status == "checksum_mismatch"]
    extract_failed = [r for r in results if r.extract_error]
    print(
        f"\nDone: {len(results)} total, {len(failed)} error(s), "
        f"{len(mismatches)} checksum mismatch(es), {len(extract_failed)} extraction error(s)"
    )
    return 1 if failed or mismatches or extract_failed else 0
