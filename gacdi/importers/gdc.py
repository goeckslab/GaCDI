"""GDC (Genomic Data Commons) importer.

Two input modes:

- ``manifest`` : a GDC-exported manifest TSV.
- ``query``    : a JSON document with a GDC ``filters`` object; we query the REST
                 API to enumerate matching files, then download them.

Downloads use the official ``gdc-client`` (bioconda), which handles segmented
transfer, retries and checksum verification. Controlled-access files are
supported via ``--token`` (never logged).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..auth import TokenFile
from ..base import BaseImporter, RunConfig
from ..errors import DownloadError, InputError
from ..manifest import load_query, parse_gdc_manifest
from ..history import unique_path
from ..model import DownloadResult, FileEntry
from ..proc import require, run

API_FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"
_QUERY_FIELDS = "file_id,file_name,md5sum,file_size"


class GDCImporter(BaseImporter):
    name = "gdc"
    supports_controlled = True
    supported_modes = ("manifest", "query")

    def resolve(self, cfg: RunConfig, token: TokenFile | None) -> list[FileEntry]:
        if cfg.input_mode == "manifest":
            if not cfg.manifest:
                raise InputError("GDC manifest mode requires --manifest.")
            return parse_gdc_manifest(cfg.manifest, source=self.name)
        return self._resolve_query(cfg)

    def _resolve_query(self, cfg: RunConfig) -> list[FileEntry]:
        if not cfg.query_json:
            raise InputError("GDC query mode requires --query-json.")
        query = load_query(cfg.query_json)
        filters = query.get("filters")
        if not filters:
            raise InputError("GDC query JSON must contain a 'filters' object.")
        payload = {
            "filters": filters,
            "fields": query.get("fields", _QUERY_FIELDS),
            "format": "JSON",
            "size": query.get("size", 100),
        }
        resp = self.session.post(API_FILES_ENDPOINT, json=payload, timeout=60)
        if resp.status_code >= 400:
            raise DownloadError(f"GDC API returned HTTP {resp.status_code}: {resp.text[:200]}")
        hits = resp.json().get("data", {}).get("hits", [])
        entries = [
            FileEntry(
                file_id=h["file_id"],
                filename=h.get("file_name") or h["file_id"],
                md5=h.get("md5sum"),
                size=int(h["file_size"]) if str(h.get("file_size", "")).isdigit() else None,
                source=self.name,
            )
            for h in hits
            if h.get("file_id")
        ]
        if not entries:
            raise InputError("GDC query matched no files.")
        return entries

    def download(
        self,
        entry: FileEntry,
        dest_dir: str,
        cfg: RunConfig,
        token: TokenFile | None,
    ) -> DownloadResult:
        gdc = require("gdc-client")
        cmd = [gdc, "download", entry.file_id, "-d", dest_dir]
        if token is not None:
            cmd += ["-t", str(token)]
        try:
            run(cmd, secret_flags=("-t",))
        except subprocess.CalledProcessError as exc:
            raise DownloadError(
                f"gdc-client failed for {entry.file_id}: {(exc.stderr or '').strip()[:300]}"
            ) from exc

        # gdc-client writes files into <dest_dir>/<file_id>/; flatten them so
        # Galaxy's discover_datasets finds them at the collection root.
        subdir = Path(dest_dir) / entry.file_id
        produced: list[str] = []
        total = 0
        if subdir.is_dir():
            for item in sorted(subdir.iterdir()):
                if item.is_file() and item.name != "logs":
                    target = unique_path(Path(dest_dir), item.name)
                    item.replace(target)
                    produced.append(str(target))
                    total += target.stat().st_size
            shutil.rmtree(subdir, ignore_errors=True)

        if not produced:
            raise DownloadError(f"gdc-client produced no files for {entry.file_id}.")
        return DownloadResult(entry, "ok", paths=produced, bytes=total, md5=entry.md5)
