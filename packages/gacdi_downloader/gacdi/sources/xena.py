"""UCSC Xena importer.

Downloads full dataset matrices from a `UCSC Xena <https://xena.ucsc.edu/>`_ hub.
Xena hubs serve each dataset as a file at ``<hub>/download/<dataset>`` (often with
a ``.gz`` variant), so retrieval is a straight HTTP download — no extra binary is
required beyond the shared ``gacdi`` runtime.

Input modes:

- ``accession`` : dataset identifiers in ``--accessions``; the hub comes from
                  ``--set hub=<url>`` (or each accession may be a full URL).
- ``query``     : a JSON document ``{"hub": "<url>", "datasets": ["...", ...]}``.

Find the host and dataset ids on https://xenabrowser.net/datapages/.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from ..auth import TokenFile
from ..base import BaseDownloadSource, RunConfig
from ..errors import DownloadError, InputError
from ..history import unique_path
from ..manifest import load_query, parse_accessions
from ..model import DownloadResult, FileEntry
from ..net import stream_download


def download_candidates(hub: str, dataset: str) -> list[str]:
    """Return candidate download URLs for *dataset* on *hub* (plain then gzip)."""
    if dataset.startswith("http://") or dataset.startswith("https://"):
        return [dataset] if dataset.endswith(".gz") else [dataset, dataset + ".gz"]
    base = f"{hub.rstrip('/')}/download/{quote(dataset, safe='./')}"
    return [base, base + ".gz"] if not base.endswith(".gz") else [base]


def _dataset_basename(dataset: str) -> str:
    name = dataset.rstrip("/").split("/")[-1]
    return name or "xena_dataset"


class XenaDownloadSource(BaseDownloadSource):
    name = "xena"
    supports_controlled = False
    supported_modes = ("accession", "query")

    def resolve(self, cfg: RunConfig, token: TokenFile | None) -> list[FileEntry]:
        if cfg.input_mode == "query":
            query = load_query(cfg.query_json)
            hub = query.get("hub", "")
            datasets = query.get("datasets") or []
            if not datasets:
                raise InputError("Xena query JSON must list one or more 'datasets'.")
        else:
            hub = cfg.options.get("hub", "")
            datasets = [e.file_id for e in parse_accessions(cfg.accessions, source=self.name)]

        entries: list[FileEntry] = []
        for ds in datasets:
            is_url = ds.startswith("http://") or ds.startswith("https://")
            if not is_url and not hub:
                raise InputError(
                    "No Xena hub given. Provide --set hub=<url> (accession mode) or "
                    "'hub' in the query JSON, or use full dataset URLs."
                )
            entries.append(
                FileEntry(
                    file_id=ds,
                    filename=_dataset_basename(ds),
                    source=self.name,
                    extra={"hub": hub, "candidates": download_candidates(hub, ds)},
                )
            )
        return entries

    def download(
        self,
        entry: FileEntry,
        dest_dir: str,
        cfg: RunConfig,
        token: TokenFile | None,
    ) -> DownloadResult:
        candidates = entry.extra.get("candidates") or download_candidates(
            entry.extra.get("hub", ""), entry.file_id
        )
        last: Exception | None = None
        for url in candidates:
            filename = entry.filename + ".gz" if url.endswith(".gz") and not entry.filename.endswith(".gz") else entry.filename
            target = unique_path(Path(dest_dir), filename)
            try:
                written = stream_download(self.session, url, target)
                return DownloadResult(entry, "ok", paths=[str(target)], bytes=written)
            except DownloadError as exc:
                last = exc
        raise DownloadError(
            f"Could not download Xena dataset '{entry.file_id}' (tried {len(candidates)} URL(s)): {last}"
        )


# Compatibility alias: the historical class name. ``XenaDownloadSource`` is preferred.
XenaImporter = XenaDownloadSource
