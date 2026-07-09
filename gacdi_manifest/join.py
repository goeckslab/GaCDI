"""Barcode normalization and the manifest<->annotation join (with QC report).

The join is *left* on the manifest: every selected file is kept, matched or not,
so downloads are never silently dropped. A report records match counts, unmatched
files, unused annotations and colliding keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import FileRow, project_id, sample_type


def normalize_barcode(barcode: str | None, level: str = "sample", trim_vial: bool = True) -> str | None:
    """Reduce a TCGA barcode to a join key at the requested *level*.

    - ``patient`` : ``TCGA-XX-XXXX``
    - ``sample``  : ``TCGA-XX-XXXX-01`` (vial letter trimmed when *trim_vial*)
    - ``full``    : unchanged
    """
    if not barcode:
        return None
    bc = barcode.strip()
    if level == "full":
        return bc
    parts = bc.split("-")
    if level == "patient":
        return "-".join(parts[:3]) if len(parts) >= 3 else bc
    # sample level
    if len(parts) < 4:
        return bc
    sample_field = parts[3]
    if trim_vial and len(sample_field) >= 3 and sample_field[-1].isalpha():
        sample_field = sample_field[:-1]
    return "-".join(parts[:3] + [sample_field])


@dataclass
class JoinReport:
    total_files: int = 0
    matched_files: int = 0
    unmatched_files: list[str] = field(default_factory=list)  # file_id (barcode)
    unused_annotations: list[str] = field(default_factory=list)  # annotation keys never matched
    collisions: list[str] = field(default_factory=list)  # norm keys with conflicting annotations


def _index_annotations(
    annotations: dict[str, dict], level: str, trim_vial: bool
) -> tuple[dict[str, dict], list[str]]:
    """Normalize annotation keys; report collisions (distinct ids -> same key with conflicts)."""
    index: dict[str, dict] = {}
    origin: dict[str, str] = {}
    collisions: list[str] = []
    for raw_id, attrs in annotations.items():
        key = normalize_barcode(raw_id, level, trim_vial)
        if key is None:
            continue
        if key in index and index[key] != attrs and origin.get(key) != raw_id:
            if key not in collisions:
                collisions.append(key)
        index[key] = {**index.get(key, {}), **attrs}
        origin[key] = raw_id
    return index, collisions


def join(
    file_rows: list[FileRow],
    annotations: dict[str, dict],
    *,
    level: str = "sample",
    trim_vial: bool = True,
    annotation_columns: list[str] | None = None,
) -> tuple[list[dict], JoinReport]:
    """Left-join annotations onto file rows; return merged rows + a report."""
    index, collisions = _index_annotations(annotations, level, trim_vial)
    ann_cols = annotation_columns or sorted({c for a in annotations.values() for c in a})
    report = JoinReport(total_files=len(file_rows), collisions=collisions)
    used_keys: set[str] = set()
    merged: list[dict] = []

    for fr in file_rows:
        barcode = fr.sample_barcode or fr.case_barcode
        key = normalize_barcode(barcode, level, trim_vial)
        attrs = index.get(key) if key else None
        if attrs is not None:
            report.matched_files += 1
            used_keys.add(key)
        else:
            report.unmatched_files.append(fr.file_id)
        row = {
            "file_id": fr.file_id,
            "filename": fr.filename,
            "md5": fr.md5,
            "size": fr.size,
            "state": fr.state,
            "case_barcode": fr.case_barcode or "",
            "sample_barcode": fr.sample_barcode or "",
            "sample_type": sample_type(fr.meta) or "",
            "project": project_id(fr.meta) or "",
            "matched": "yes" if attrs is not None else "no",
        }
        for col in ann_cols:
            row[col] = (attrs or {}).get(col, "")
        merged.append(row)

    report.unused_annotations = [k for k in index if k not in used_keys]
    return merged, report
