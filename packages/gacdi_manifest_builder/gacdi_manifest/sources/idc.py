"""IDC builder importer (imaging family): NCI Imaging Data Commons.

Confirmed live in the spike:

* ``GET  /v2/collections`` — collection catalogue (collection_id, cancer_type).
* ``POST /v2/cohorts/manifest/preview`` with body
  ``{"cohort_def": {"name","description","filters": {...}}, "fields": [...]}`` —
  an **instance-level** DICOM manifest under ``manifest.manifest_data`` (fields incl.
  ``collection_id, PatientID, SeriesInstanceUID, crdc_series_uuid, gcs_url``), with
  ``manifest.totalFound`` and a top-level ``next_page`` token for paging.

IDC uses the public GCS bucket ``gs://idc-open-data/<crdc_series_uuid>/`` as the
stable series locator (its series ids do not resolve at the CRDC DRS server), so the
§4.1 manifest is emitted with ``download_method=gcs`` and that folder as ``access_url``.
We collapse the instance rows to **one row per series** (the natural download unit).
"""

from __future__ import annotations

import datetime
import json

from .. import version_string
from ..base import BaseManifestSource
from ..clients.idc import IDC_API, IDCCohortClient
from ..errors import InputError
from ..model import FileRow, ManifestRow

IDC_GCS_BUCKET = "gs://idc-open-data/"

# Re-exported for compatibility; the canonical constant lives in clients.idc.
__all__ = ["IDC_API", "IDC_GCS_BUCKET", "IDCManifestSource", "IDCImporter"]


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


class IDCManifestSource(BaseManifestSource):
    name = "idc"
    help = "Build a GCS manifest from the Imaging Data Commons (IDC), one row per DICOM series."
    manifest_dialect = "source"

    def __init__(self, client: IDCCohortClient | None = None) -> None:
        # The transport client is injected for tests; a default is created when
        # none is supplied so existing callers stay compatible.
        self._client = client or IDCCohortClient()

    def add_arguments(self, p) -> None:
        f = p.add_argument_group("guided filters")
        f.add_argument("--collection-id", dest="collection_id",
                       help="One or more IDC collection ids (comma-separated), e.g. 4d_lung, tcga_luad.")
        f.add_argument("--patient-id", dest="patient_id",
                       help="One or more PatientIDs (comma-separated) to restrict to a cohort.")

    def build_query(self, args) -> dict:
        filters: dict[str, list[str]] = {}
        if _split(args.collection_id):
            filters["collection_id"] = _split(args.collection_id)
        if _split(args.patient_id):
            filters["PatientID"] = _split(args.patient_id)
        if not filters:
            raise InputError(
                "No IDC filters supplied. Provide --collection-id (and/or --patient-id) so the "
                "manifest targets specific imaging series rather than the whole archive."
            )
        return {"filters": filters}

    def _series(self, session, query: dict, *, max_files=None) -> list[FileRow]:
        """Page the instance manifest, collapsing to one FileRow per series."""
        seen: set[str] = set()
        rows: list[FileRow] = []
        for r in self._client.iter_instances(session, query["filters"]):
            uuid = r.get("crdc_series_uuid")
            if not uuid or uuid in seen:
                continue
            seen.add(uuid)
            rows.append(FileRow(
                file_id=uuid,
                filename=r.get("SeriesInstanceUID") or "",
                md5="",
                size="",
                state="released",
                meta={
                    "collection_id": r.get("collection_id") or "",
                    "PatientID": r.get("PatientID") or "",
                    "StudyInstanceUID": r.get("StudyInstanceUID") or "",
                    "SeriesInstanceUID": r.get("SeriesInstanceUID") or "",
                    "crdc_series_uuid": uuid,
                    "gcs_url": f"{IDC_GCS_BUCKET}{uuid}/",
                },
            ))
            if max_files is not None and len(rows) >= max_files:
                return rows
        return rows

    def count(self, session, query) -> int:
        # Cheap preview: instance total (the built manifest is series-level; a series
        # count would require paging the whole collection).
        return self._client.total_found(session, query["filters"])

    def fetch(self, session, query, *, max_files=None, total=None) -> list[FileRow]:
        return self._series(session, query, max_files=max_files)

    def to_manifest_rows(self, file_rows: list[FileRow]) -> list[ManifestRow]:
        return [
            ManifestRow(
                source="idc",
                file_id=fr.file_id,
                filename=fr.filename,
                access_url=fr.meta.get("gcs_url", ""),
                download_method="gcs",
                size=fr.size,
                file_format="DICOM",
                access="open",
                case_id=fr.meta.get("PatientID", ""),
            )
            for fr in file_rows
        ]

    def harmonize(self, row: dict) -> dict:
        return {
            "project": row.get("idc__collection_id", ""),
            "case_id": row.get("idc__PatientID", ""),
        }

    def provenance(self, query: dict) -> dict:
        return {
            "source": "idc",
            "endpoint": self._client.endpoint,
            "tool_version": version_string(),
            "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "query_filters": json.dumps(query, sort_keys=True, separators=(",", ":")),
        }


# Compatibility alias: the historical class name. ``IDCManifestSource`` is preferred.
IDCImporter = IDCManifestSource
