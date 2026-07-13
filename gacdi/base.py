"""The importer base class and the shared run configuration.

``BaseImporter.run`` is a template method: it owns input validation, the
download/retry loop, budget caps, summary writing and error handling, while each
repository subclass only implements :meth:`resolve` and :meth:`download`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from .auth import TokenFile
from .errors import AuthError, DownloadError, GacdiError, InputError
from .history import (
    ensure_output_dir,
    write_import_provenance,
    write_imported_metadata,
    write_dataset_map,
    write_galaxy_metadata,
    write_retry_bundle,
    write_summary,
    write_transfer_report,
)
from .model import DownloadResult, FileEntry, RunSummary
from .net import build_session

log = logging.getLogger("gacdi.base")


@dataclass
class RunConfig:
    """Normalised CLI arguments passed to an importer."""

    input_mode: str = "manifest"
    manifest: str | None = None
    accessions: str | None = None
    query_json: str | None = None
    output_dir: str = "downloads"
    summary: str = "summary.tsv"
    token: str | None = None
    assign_ext: str | None = None
    max_files: int | None = None
    max_bytes: int | None = None
    retries: int = 3
    jobs: int = 1
    dry_run: bool = False
    continue_on_error: bool = False
    # Importer-specific options supplied via ``--set key=value`` (e.g. Xena hub).
    options: dict = field(default_factory=dict)
    # Canonical selection-bundle sidecars and optional richer materialization
    # outputs. Appended to preserve positional compatibility with RunConfig 0.1.
    metadata: str | None = None
    provenance: str | None = None
    transfer_report: str | None = None
    dataset_map: str | None = None
    galaxy_metadata: str | None = None
    imported_metadata: str | None = None
    import_provenance: str | None = None
    retry_manifest: str | None = None
    retry_metadata: str | None = None
    retry_provenance: str | None = None


class BaseImporter(ABC):
    """Base class for all repository importers."""

    #: registry key / CLI subcommand, e.g. "gdc".
    name: str = ""
    #: whether this importer can consume a controlled-access token.
    supports_controlled: bool = False
    #: input modes this importer accepts.
    supported_modes: tuple[str, ...] = ("manifest",)

    def __init__(self, session: requests.Session | None = None):
        # Sessions are injected in tests so no unit test hits the network.
        self._session = session

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = build_session()
        return self._session

    # --- hooks implemented by subclasses ---------------------------------
    @abstractmethod
    def resolve(self, cfg: RunConfig, token: TokenFile | None) -> list[FileEntry]:
        """Expand the user's selection into a concrete list of files."""

    @abstractmethod
    def download(
        self,
        entry: FileEntry,
        dest_dir: str,
        cfg: RunConfig,
        token: TokenFile | None,
    ) -> DownloadResult:
        """Fetch one entry into *dest_dir* and return the result."""

    # --- template method -------------------------------------------------
    def run(self, cfg: RunConfig) -> RunSummary:
        if cfg.input_mode not in self.supported_modes:
            raise InputError(
                f"{self.name}: input mode '{cfg.input_mode}' is not supported "
                f"(available: {', '.join(self.supported_modes)})."
            )
        if cfg.token and not self.supports_controlled:
            raise AuthError(f"{self.name} does not support controlled-access tokens.")
        if (cfg.retry_metadata or cfg.retry_provenance) and not cfg.retry_manifest:
            raise InputError(
                "--retry-metadata and --retry-provenance require --retry-manifest."
            )

        token = TokenFile(cfg.token) if cfg.token else None
        started_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            entries = self.resolve(cfg, token)
            if not entries:
                raise InputError("Nothing to download after resolving the selection.")

            out = ensure_output_dir(cfg.output_dir)
            results: list[DownloadResult] = []
            used = 0
            for index, entry in enumerate(entries):
                preflight_error = str(entry.extra.get("preflight_error", ""))
                if preflight_error and not cfg.dry_run:
                    results.append(
                        DownloadResult(entry, "failed", message=preflight_error, attempts=0)
                    )
                    continue
                if cfg.max_files is not None and index >= cfg.max_files:
                    results.append(
                        DownloadResult(
                            entry,
                            "excluded_file_limit",
                            message=f"excluded by max-files limit ({cfg.max_files})",
                        )
                    )
                    continue
                if cfg.max_bytes is not None and (
                    used >= cfg.max_bytes
                    or (entry.size is not None and used + entry.size > cfg.max_bytes)
                ):
                    results.append(
                        DownloadResult(
                            entry,
                            "excluded_byte_limit",
                            message=f"excluded by max-bytes limit ({cfg.max_bytes})",
                        )
                    )
                    continue
                if cfg.dry_run:
                    results.append(
                        DownloadResult(entry, "planned", message="dry-run (not downloaded)")
                    )
                    if entry.size is not None:
                        used += entry.size
                    continue
                res = self._download_with_retry(entry, str(out), cfg, token)
                results.append(res)
                used += res.bytes

            summary = RunSummary(self.name, results)
            write_summary(cfg.summary, summary)
            if cfg.transfer_report:
                write_transfer_report(cfg.transfer_report, summary)
            if cfg.dataset_map:
                write_dataset_map(cfg.dataset_map, summary)
            if cfg.galaxy_metadata:
                write_galaxy_metadata(cfg.galaxy_metadata, summary)
            if cfg.imported_metadata:
                write_imported_metadata(cfg.imported_metadata, summary)
            if cfg.retry_manifest:
                retry_manifest = Path(cfg.retry_manifest)
                write_retry_bundle(
                    retry_manifest,
                    cfg.retry_metadata or str(retry_manifest.with_name("retry_metadata.tsv")),
                    cfg.retry_provenance
                    or str(retry_manifest.with_name("retry_provenance.json")),
                    summary,
                )
            if cfg.import_provenance:
                write_import_provenance(
                    cfg.import_provenance,
                    summary,
                    started_utc=started_utc,
                    finished_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    retries=max(cfg.retries, 0),
                    max_files=cfg.max_files,
                    max_bytes=cfg.max_bytes,
                    failure_policy=(
                        "best_effort" if cfg.continue_on_error else "fail_on_any_error"
                    ),
                )
            return summary
        finally:
            if token is not None:
                token.cleanup()

    def _download_with_retry(
        self,
        entry: FileEntry,
        dest_dir: str,
        cfg: RunConfig,
        token: TokenFile | None,
    ) -> DownloadResult:
        last: Exception | None = None
        total_attempts = max(cfg.retries, 0) + 1
        for attempt in range(1, total_attempts + 1):
            try:
                result = self.download(entry, dest_dir, cfg, token)
                result.attempts = attempt
                return result
            except DownloadError as exc:
                last = exc
                log.warning(
                    "attempt %d/%d failed for %s: %s",
                    attempt,
                    total_attempts,
                    entry.file_id,
                    exc,
                )
            except GacdiError as exc:
                # Non-download errors are not retryable, but retaining an asset
                # result ensures Galaxy receives complete transfer accounting.
                return DownloadResult(entry, "failed", message=str(exc), attempts=attempt)
        return DownloadResult(
            entry,
            "failed",
            message=str(last) if last else "unknown error",
            attempts=total_attempts,
        )
