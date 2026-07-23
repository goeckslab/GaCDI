"""``mcdi`` — Multi-Commons Data Importer: single entry point for the ``manifest`` and ``download`` subcommands."""

from __future__ import annotations

import argparse
import logging
import sys

from . import version_string
from .download import cli as download_cli
from .errors import ManifestError
from .manifest import cli as manifest_cli

log = logging.getLogger("mcdi")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcdi", description="MCDI: Multi-Commons Data Importer.")
    parser.add_argument("--version", action="version", version=f"mcdi {version_string()}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    manifest_cli.add_arguments(sub)
    download_cli.add_arguments(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # Emit the running version to the job log so it is visible in Galaxy's job info.
    log.info("mcdi %s", version_string())
    try:
        return args.func(args)
    except ManifestError as exc:
        log.error("%s", exc)
        return exc.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
