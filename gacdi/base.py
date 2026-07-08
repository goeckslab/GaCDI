"""The importer base class and the shared run configuration.

``BaseImporter.run`` is a template method: it owns input validation, the
download/retry loop, budget caps, summary writing and error handling, while each
repository subclass only implements :meth:`resolve` and :meth:`download`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests

from .auth import TokenFile
from .errors import AuthError, DownloadError, GacdiError, InputError
from .history import ensure_output_dir, write_summary
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

        token = TokenFile(cfg.token) if cfg.token else None
        try:
            entries = self.resolve(cfg, token)
            if cfg.max_files is not None:
                entries = entries[: cfg.max_files]
            if not entries:
                raise InputError("Nothing to download after resolving the selection.")

            out = ensure_output_dir(cfg.output_dir)
            results: list[DownloadResult] = []
            used = 0
            for entry in entries:
                if cfg.dry_run:
                    results.append(
                        DownloadResult(entry, "planned", message="dry-run (not downloaded)")
                    )
                    continue
                res = self._download_with_retry(entry, str(out), cfg, token)
                results.append(res)
                used += res.bytes
                if cfg.max_bytes is not None and used >= cfg.max_bytes:
                    log.warning("Reached max-bytes budget (%d); stopping.", cfg.max_bytes)
                    break

            summary = RunSummary(self.name, results)
            write_summary(cfg.summary, summary)
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
        for attempt in range(1, max(cfg.retries, 1) + 1):
            try:
                return self.download(entry, dest_dir, cfg, token)
            except DownloadError as exc:
                last = exc
                log.warning(
                    "attempt %d/%d failed for %s: %s",
                    attempt,
                    cfg.retries,
                    entry.file_id,
                    exc,
                )
            except GacdiError:
                raise  # input/auth/dependency errors are not retryable
        return DownloadResult(entry, "failed", message=str(last) if last else "unknown error")
