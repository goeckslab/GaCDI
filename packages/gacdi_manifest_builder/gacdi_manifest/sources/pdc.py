"""PDC builder importer (T1.1b): first CRDC node behind the BuildImporter API.

Proteomic Data Commons exposes a public GraphQL API (no auth for open metadata).
Confirmed live in the T1.0 spike:

* ``getPaginatedUIStudy`` — study browse (disease_type, primary_site,
  analytical_fraction, ...).
* ``filesPerStudy(pdc_study_id, acceptDUA:true)`` — per-study file listing
  (file_id, file_name, file_type, md5sum, file_size, data_category).

File identity uses the CRDC DRS server: every PDC ``file_id`` resolves at
``drs://dg.4DFC:<file_id>`` (md5 checksum, s3 access) — so the manifest is a
DRS-uniform §4.1 manifest with ``download_method=drs`` (plan T1.2).
"""

from __future__ import annotations

import datetime

from .. import version_string
from ..base import BaseManifestSource
from ..clients.pdc import PDC_GRAPHQL, STUDY_FIELDS as _STUDY_FIELDS, PDCGraphQLClient
from ..errors import InputError
from ..model import FileRow, ManifestRow

# Re-exported for compatibility; the canonical constant lives in clients.pdc.
__all__ = ["PDC_GRAPHQL", "DRS_PREFIX", "PDCManifestSource", "PDCImporter"]

# CRDC DRS prefix that resolves PDC file ids (confirmed: self_uri drs://dg.4DFC:<uuid>).
DRS_PREFIX = "drs://dg.4DFC:"


def _matches(value: str, wanted: str | None) -> bool:
    """Case-insensitive membership: PDC packs multi-values as ';'-joined strings."""
    if not wanted:
        return True
    have = {v.strip().lower() for v in (value or "").split(";")}
    want = {w.strip().lower() for w in wanted.split(",") if w.strip()}
    return bool(have & want) if want else True


class PDCManifestSource(BaseManifestSource):
    name = "pdc"
    help = "Build a DRS manifest from the Proteomic Data Commons (PDC)."
    manifest_dialect = "source"

    def __init__(self, client: PDCGraphQLClient | None = None) -> None:
        # The transport client is injected for tests; a default is created when
        # none is supplied so existing callers stay compatible.
        self._client = client or PDCGraphQLClient()

    def add_arguments(self, p) -> None:
        f = p.add_argument_group("guided filters")
        f.add_argument("--pdc-study-id", dest="pdc_study_id",
                       help="One or more PDC study ids (comma-separated), e.g. PDC000714.")
        f.add_argument("--disease-type", dest="disease_type", help="e.g. Colon Adenocarcinoma.")
        f.add_argument("--primary-site", dest="primary_site", help="e.g. Brain, Colon.")
        f.add_argument("--analytical-fraction", dest="analytical_fraction",
                       help="e.g. Proteome, Phosphoproteome, Ubiquitylome.")
        f.add_argument("--data-category", dest="data_category",
                       help="Keep only files in this data category, e.g. 'Raw Mass Spectra'.")

    def build_query(self, args) -> dict:
        study_ids = [s.strip() for s in (args.pdc_study_id or "").split(",") if s.strip()]
        query = {
            "study_ids": study_ids,
            "disease_type": args.disease_type,
            "primary_site": args.primary_site,
            "analytical_fraction": args.analytical_fraction,
            "data_category": args.data_category,
        }
        if not any([study_ids, args.disease_type, args.primary_site, args.analytical_fraction]):
            raise InputError(
                "No PDC filters supplied. Provide --pdc-study-id, or one of --disease-type / "
                "--primary-site / --analytical-fraction, so the manifest targets specific studies."
            )
        return query

    def _matching_studies(self, session, query: dict) -> list[dict]:
        """Return study dicts matching the query (by explicit id, or by facet filters)."""
        wanted_ids = set(query["study_ids"])
        studies: list[dict] = []
        for s in self._client.iter_studies(session):
            if wanted_ids:
                if s.get("pdc_study_id") in wanted_ids:
                    studies.append(s)
            elif (_matches(s.get("disease_type", ""), query["disease_type"])
                  and _matches(s.get("primary_site", ""), query["primary_site"])
                  and _matches(s.get("analytical_fraction", ""), query["analytical_fraction"])):
                studies.append(s)
        return studies

    def _files(self, session, study: dict, data_category: str | None, limit_remaining):
        """Yield FileRow objects for one study, tagged with study-level fields."""
        sid = study.get("pdc_study_id")
        for f in self._client.files_for_study(session, sid):
            if not _matches(f.get("data_category", ""), data_category):
                continue
            meta = {
                "file_type": f.get("file_type") or "",
                "data_category": f.get("data_category") or "",
                "data_format": f.get("file_type") or "",
            }
            for k in _STUDY_FIELDS:
                meta[k] = study.get(k) or ""
            yield FileRow(
                file_id=f.get("file_id") or "",
                filename=f.get("file_name") or "",
                md5=f.get("md5sum") or "",
                size=str(f.get("file_size") or ""),
                state="released",
                meta=meta,
            )

    def _collect(self, session, query, *, max_files=None) -> list[FileRow]:
        rows: list[FileRow] = []
        for study in self._matching_studies(session, query):
            for fr in self._files(session, study, query["data_category"], None):
                rows.append(fr)
                if max_files is not None and len(rows) >= max_files:
                    return rows
        return rows

    def count(self, session, query) -> int:
        return len(self._collect(session, query))

    def fetch(self, session, query, *, max_files=None, total=None) -> list[FileRow]:
        return self._collect(session, query, max_files=max_files)

    def to_manifest_rows(self, file_rows: list[FileRow]) -> list[ManifestRow]:
        return [
            ManifestRow(
                source="pdc",
                file_id=fr.file_id,
                filename=fr.filename,
                drs_uri=f"{DRS_PREFIX}{fr.file_id}" if fr.file_id else "",
                download_method="drs",
                checksum=fr.md5,
                checksum_type="md5" if fr.md5 else "",
                size=fr.size,
                file_format=fr.meta.get("file_type", ""),
                access="open",
            )
            for fr in file_rows
        ]

    def harmonize(self, row: dict) -> dict:
        return {
            "disease_type": row.get("pdc__disease_type", ""),
            "primary_site": row.get("pdc__primary_site", ""),
            "project": row.get("pdc__pdc_study_id", ""),
        }

    def provenance(self, query: dict) -> dict:
        import json
        return {
            "source": "pdc",
            "endpoint": self._client.endpoint,
            "tool_version": version_string(),
            "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "query_filters": json.dumps(query, sort_keys=True, separators=(",", ":")),
        }


# Compatibility alias: the historical class name. ``PDCManifestSource`` is preferred.
PDCImporter = PDCManifestSource
