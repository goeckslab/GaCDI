"""Command-line dispatcher for GDC and PDC download manifests."""

from __future__ import annotations

import argparse
import logging
import sys

from .. import version_string
from ..errors import ManifestError
from .detect import detect_source
from .gdc import download_gdc
from .pdc import download_pdc

log = logging.getLogger("gacdi_manifest.download")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gacdi-download",
        description="Download files from an auto-detected GDC or PDC file manifest.",
    )
    parser.add_argument("--version", action="version", version=f"gacdi-download {version_string()}")
    parser.add_argument("--manifest", required=True, help="GDC or PDC manifest (CSV or TSV).")
    parser.add_argument("--outdir", required=True, help="Directory in which to place downloaded files.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    log.info("gacdi-download %s", version_string())
    try:
        source = detect_source(args.manifest)
        log.info("Detected %s manifest.", source.upper())
        if source == "gdc":
            return download_gdc(args.manifest, args.outdir)
        download_pdc(args.manifest, args.outdir)
        return 0
    except ManifestError as exc:
        log.error("%s", exc)
        return exc.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
