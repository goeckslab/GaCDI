"""Output writers: the lean manifest, the enriched metadata table, the report."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from . import version_string
from .join import JoinReport
from .model import FileRow

# Metadata columns summarised in the report's composition breakdown.
_COMPOSITION_COLUMNS = [
    ("data_type", "data_type"),
    ("data_format", "data_format"),
    ("galaxy_ext", "galaxy_datatype"),
    ("sample_type", "sample_type"),
    ("primary_site", "primary_site"),
    ("workflow_type", "workflow_type"),
]


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _top_counts(rows: list[dict], column: str, top: int = 15) -> tuple[list[tuple[str, int]], int]:
    counter = Counter((r.get(column) or "(blank)") for r in rows)
    return counter.most_common(top), len(counter)

# gdc-client / gacdi_gdc require exactly these columns, in this order.
MANIFEST_COLUMNS = ["id", "filename", "md5", "size", "state"]

BASE_METADATA_COLUMNS = [
    "file_id",
    "filename",
    "md5",
    "size",
    "state",
    "galaxy_ext",
    "data_format",
    "data_category",
    "data_type",
    "experimental_strategy",
    "workflow_type",
    "platform",
    "case_id",
    "case_barcode",
    "sample_id",
    "sample_barcode",
    "sample_type",
    "primary_site",
    "disease_type",
    "project",
    # Harmonized clinical core, populated from GDC-native demographic + diagnosis.
    "gender",
    "race",
    "ethnicity",
    "vital_status",
    "age_at_diagnosis",
    "primary_diagnosis",
    "stage",
    "grade",
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
    database_total: int | None = None,
    merged_rows: list[dict] | None = None,
    report: JoinReport | None = None,
    enrichment_columns: list[str] | None = None,
    facets: dict | None = None,
    max_examples: int = 25,
    provenance: dict | None = None,
    extra: list[tuple[str, str, str]] | None = None,
) -> None:
    """Write a meaningful tabular report: ``category  key  value`` rows.

    Sections: a **summary** (match counts, download size, annotation coverage), a
    **composition** breakdown of what the manifest contains, per-attribute
    annotation **coverage**, GDC **facets** (preview mode), and a short capped list
    of **unmatched** samples — instead of dumping every file UUID.
    """
    rows: list[tuple[str, str, str]] = []

    def add(category: str, key: str, value) -> None:
        rows.append((category, key, str(value)))

    # Version stamp: lets you confirm which build of the tool actually ran.
    add("summary", "gacdi_manifest_version", version_string())

    # --- provenance: what query produced these outputs, when, with what tool ----
    # Makes every run self-describing/reproducible. Kept in the report (not the
    # manifest/metadata, which must stay strictly tabular).
    for key, value in (provenance or {}).items():
        add("provenance", key, value)

    # --- summary -------------------------------------------------------
    if database_total is not None:
        add("summary", "files_matching_filters", database_total)
    if merged_rows is not None:
        total_bytes = sum(int(r["size"]) for r in merged_rows if str(r.get("size", "")).isdigit())
        add("summary", "files_in_manifest", len(merged_rows))
        add("summary", "total_download_size", _human_size(total_bytes))
        add("summary", "total_download_bytes", total_bytes)
    if report is not None:
        total = report.total_files or (len(merged_rows) if merged_rows else 0)
        add("summary", "files_matched_to_annotation", report.matched_files)
        if total:
            add("summary", "annotation_match_rate", f"{100 * report.matched_files / total:.1f}%")
        add("summary", "files_unmatched", len(report.unmatched_files))
        if enrichment_columns is not None:
            add("summary", "annotation_columns_added", len(enrichment_columns))
        add("summary", "annotations_unused", len(report.unused_annotations))
        if report.collisions:
            add("summary", "annotation_key_collisions", len(report.collisions))

    # --- composition: what am I about to download? ---------------------
    if merged_rows:
        for column, label in _COMPOSITION_COLUMNS:
            counts, distinct = _top_counts(merged_rows, column)
            if distinct == 1 and counts and counts[0][0] == "(blank)":
                continue  # column not populated for this selection
            for value, n in counts:
                add("composition:" + label, value, n)

    # --- per-attribute annotation coverage -----------------------------
    if merged_rows and enrichment_columns:
        for column in enrichment_columns:
            filled = sum(1 for r in merged_rows if str(r.get(column, "")).strip())
            add("annotation_coverage", column, filled)

    # --- GDC facets (preview mode) -------------------------------------
    if facets:
        for field_name, counts in facets.items():
            for value, n in counts.items():
                add("facet:" + field_name, str(value), n)

    # --- capped examples of unmatched samples (by barcode) -------------
    if merged_rows is not None and report is not None and report.unmatched_files:
        unmatched = [
            (r.get("sample_barcode") or r.get("file_id"))
            for r in merged_rows
            if r.get("matched") == "no"
        ]
        for barcode in unmatched[:max_examples]:
            add("unmatched_example", barcode, "")
        if len(unmatched) > max_examples:
            add("unmatched_example", "...", f"and {len(unmatched) - max_examples} more")

    for item in extra or []:
        rows.append(item)

    with Path(path).open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["category", "key", "value"])
        writer.writerows(rows)
