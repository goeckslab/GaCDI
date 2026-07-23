"""CLI: ``gacdi-download`` — download the files listed in a GDC or PDC manifest."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .. import version_string
from ..errors import InputError, ManifestError
from . import config, engine
from .sources import SOURCES, detect_source

log = logging.getLogger("gacdi_manifest.download")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gacdi-download",
        description="Download files listed in a GDC or PDC manifest.",
    )
    parser.add_argument("--version", action="version", version=f"gacdi-download {version_string()}")
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
    return parser


def _run(args: argparse.Namespace) -> int:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    log.info("gacdi-download %s", version_string())
    try:
        return _run(args)
    except ManifestError as exc:
        log.error("%s", exc)
        return exc.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
