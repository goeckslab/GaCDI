"""GDC builder importer (T0.3): GDC-specific logic behind the BuildImporter API.

All of this used to live inline in ``cli.py``. The behaviour is unchanged — this
module just packages the GDC query flags, filter construction, provenance, and
the ``/files`` calls so ``cli.py`` can dispatch to it generically.
"""

from __future__ import annotations

import datetime
import json

import requests

from .. import version_string
from ..base import BaseManifestSource
from ..clients.gdc import GDCFilesClient
from ..filters import build_filters
from ..model import FileRow

# Facets summarised in count-only previews.
PREVIEW_FACETS = [
    "data_category",
    "data_type",
    "experimental_strategy",
    "data_format",
    "platform",
    "access",
    "cases.primary_site",
    "analysis.workflow_type",
]


def _read_id_list(path: str | None) -> list[str]:
    """Read a cohort id file into a list (one id per line; blanks/#comments skipped)."""
    if not path:
        return []
    with open(path) as fh:
        return [
            line.strip()
            for line in fh
            if line.strip() and not line.lstrip().startswith("#")
        ]


def _row_to_filerow(row: dict) -> FileRow:
    """Map one raw GDC TSV row to a :class:`FileRow` (source-owned mapping)."""

    def pick(*keys: str) -> str:
        for k in keys:
            if row.get(k) not in (None, ""):
                return str(row[k]).strip()
        return ""

    return FileRow(
        file_id=pick("file_id", "id"),
        filename=pick("file_name", "filename"),
        md5=pick("md5sum", "md5"),
        size=pick("file_size", "size"),
        state=pick("state") or "released",
        meta=dict(row),
    )


class GDCManifestSource(BaseManifestSource):
    name = "gdc"
    help = "Build a manifest from the GDC files API."

    def __init__(self, client: GDCFilesClient | None = None) -> None:
        # The transport client is injected for tests; a default is created when
        # none is supplied so existing callers stay compatible.
        self._client = client or GDCFilesClient()

    def add_arguments(self, p) -> None:
        facets = p.add_argument_group("guided filters")
        facets.add_argument("--project", help="Project id, e.g. TCGA-BRCA (comma-separated for several).")
        facets.add_argument("--primary-site", dest="primary_site", help="e.g. Breast, Lung, Brain.")
        facets.add_argument("--disease-type", dest="disease_type")
        facets.add_argument("--data-category", dest="data_category")
        facets.add_argument("--data-type", dest="data_type")
        facets.add_argument("--experimental-strategy", dest="experimental_strategy")
        facets.add_argument("--workflow-type", dest="workflow_type", help="Analysis workflow, e.g. 'STAR - Counts'.")
        facets.add_argument("--platform", dest="platform")
        facets.add_argument("--data-format", dest="data_format")
        facets.add_argument("--access", help="open or controlled.")
        facets.add_argument("--sample-type", dest="sample_type")

        cohort = p.add_argument_group("cohort lists (match an uploaded set of ids)")
        cohort.add_argument("--file-id-list", dest="file_id_list",
                            help="Path to a file of GDC file ids (one per line) to match.")
        cohort.add_argument("--case-list", dest="case_list",
                            help="Path to case submitter barcodes (one per line; not native UUIDs).")
        cohort.add_argument("--sample-list", dest="sample_list",
                            help="Path to sample submitter barcodes (one per line; not native UUIDs).")

        adv = p.add_argument_group("advanced filters")
        adv.add_argument("--extra-filter", dest="extra_filters", action="append", default=[],
                         metavar="field=F;op=in;values=a,b",
                         help="Custom GDC query filter on any GDC field (server-side, repeatable).")
        adv.add_argument("--raw-filters", dest="raw_filters", help="Path to a raw GDC filters JSON file.")

    def build_query(self, args) -> dict:
        raw = None
        if args.raw_filters:
            with open(args.raw_filters) as fh:
                raw = json.load(fh)
        return build_filters(
            project=args.project,
            primary_site=args.primary_site,
            disease_type=args.disease_type,
            data_category=args.data_category,
            data_type=args.data_type,
            experimental_strategy=args.experimental_strategy,
            workflow_type=args.workflow_type,
            platform=args.platform,
            data_format=args.data_format,
            access=args.access,
            sample_type=args.sample_type,
            file_id_list=_read_id_list(args.file_id_list),
            case_list=_read_id_list(args.case_list),
            sample_list=_read_id_list(args.sample_list),
            extra_filters=args.extra_filters,
            raw_filters=raw,
        )

    def provenance(self, query: dict) -> dict:
        """Build the run's provenance record (source, endpoint, query, when, version)."""
        return {
            "source": "gdc",
            "endpoint": self._client.endpoint,
            "tool_version": version_string(),
            "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "query_filters": json.dumps(query, sort_keys=True, separators=(",", ":")),
        }

    def count(self, session: requests.Session, query: dict) -> int:
        return self._client.count(session, query)

    def facets(self, session: requests.Session, query: dict) -> dict:
        return self._client.facets(session, query, PREVIEW_FACETS)

    def fetch(self, session, query, *, max_files=None, total=None) -> list[FileRow]:
        rows = self._client.fetch_rows(session, query, max_files=max_files, total=total)
        return [_row_to_filerow(row) for row in rows]


# Compatibility alias: the historical class name. ``GDCManifestSource`` is preferred.
GDCImporter = GDCManifestSource
