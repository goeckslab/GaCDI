"""Output writers: the lean manifest, the enriched metadata table, the report."""

from __future__ import annotations

import csv
from pathlib import Path

from .join import JoinReport
from .model import FileRow

# gdc-client / gacdi_gdc require exactly these columns, in this order.
MANIFEST_COLUMNS = ["id", "filename", "md5", "size", "state"]

BASE_METADATA_COLUMNS = [
    "file_id",
    "filename",
    "md5",
    "size",
    "state",
    "case_barcode",
    "sample_barcode",
    "sample_type",
    "project",
    "matched",
]


def write_manifest(path: str | Path, file_rows: list[FileRow]) -> None:
    """Write the strict GDC download manifest."""
    with Path(path).open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(MANIFEST_COLUMNS)
        for fr in file_rows:
            writer.writerow([fr.file_id, fr.filename, fr.md5, fr.size, fr.state])


def write_metadata(path: str | Path, merged_rows: list[dict], annotation_columns: list[str]) -> None:
    """Write the enriched research table (base columns + annotation columns)."""
    columns = BASE_METADATA_COLUMNS + [c for c in annotation_columns if c not in BASE_METADATA_COLUMNS]
    with Path(path).open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(columns)
        for row in merged_rows:
            writer.writerow([row.get(c, "") for c in columns])


def write_report(
    path: str | Path,
    *,
    matched_total: int | None = None,
    report: JoinReport | None = None,
    facets: dict | None = None,
    extra: list[tuple[str, str, str]] | None = None,
) -> None:
    """Write a tabular QC/preview report: ``category  key  value`` rows."""
    rows: list[tuple[str, str, str]] = []
    if matched_total is not None:
        rows.append(("summary", "files_matching_filters", str(matched_total)))
    if report is not None:
        rows.append(("summary", "files_in_manifest", str(report.total_files)))
        rows.append(("summary", "files_matched_to_annotation", str(report.matched_files)))
        rows.append(("summary", "files_unmatched", str(len(report.unmatched_files))))
        rows.append(("summary", "annotations_unused", str(len(report.unused_annotations))))
        for fid in report.unmatched_files:
            rows.append(("unmatched_file", fid, ""))
        for key in report.unused_annotations:
            rows.append(("unused_annotation", key, ""))
        for key in report.collisions:
            rows.append(("collision", key, "conflicting annotations for normalized key"))
    if facets:
        for field_name, counts in facets.items():
            for value, n in counts.items():
                rows.append(("facet:" + field_name, str(value), str(n)))
    for item in extra or []:
        rows.append(item)

    with Path(path).open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["category", "key", "value"])
        writer.writerows(rows)
