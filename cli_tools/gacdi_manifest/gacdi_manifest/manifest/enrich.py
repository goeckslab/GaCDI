"""Collect optional annotation sources into a single ``{sample_id: {attr: val}}``.

Sources (any combination): cBioPortal sample clinical data and a user-uploaded
annotation TSV. GDC-native fields (barcode, sample_type, project) are always
carried through by the join and need no collection here.
"""

from __future__ import annotations

import csv
from pathlib import Path

import requests

from . import cbioportal
from ..errors import InputError


def read_annotation_tsv(path: str | Path, key_col: str) -> tuple[dict[str, dict], list[str]]:
    """Read a TSV keyed by *key_col* into ``{key: {col: value}}`` + column order."""
    p = Path(path)
    if not p.is_file():
        raise InputError(f"Annotation file not found: {path}")
    with p.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        fields = reader.fieldnames or []
        if key_col not in fields:
            raise InputError(
                f"Annotation key column '{key_col}' not found. Columns: {', '.join(fields) or '(none)'}"
            )
        columns = [c for c in fields if c != key_col]
        annotations: dict[str, dict] = {}
        for row in reader:
            key = (row.get(key_col) or "").strip()
            if not key:
                continue
            annotations[key] = {c: (row.get(c) or "").strip() for c in columns}
    return annotations, columns


def split_studies(value: str | None) -> list[str]:
    """Split a comma-separated list of cBioPortal study ids."""
    return [s.strip() for s in (value or "").split(",") if s.strip()]


def collect(
    session: requests.Session,
    *,
    cbioportal_study: str | None = None,
    cbioportal_attrs: str | None = None,
    cbioportal_base: str = cbioportal.DEFAULT_BASE,
    annotation_tsv: str | None = None,
    annotation_key_col: str = "sample",
) -> tuple[dict[str, dict], list[str]]:
    """Gather and merge all enrichment sources into one annotation table.

    ``cbioportal_study`` may name several studies (comma-separated); they are
    fetched and merged in order. Columns are the union across sources; for a given
    sample/attribute the first source with a non-empty value wins (so list the
    highest-priority study first).
    """
    annotations: dict[str, dict] = {}
    columns: list[str] = []

    def merge(src: dict[str, dict], cols: list[str]) -> None:
        for c in cols:
            if c not in columns:
                columns.append(c)
        for key, attrs in src.items():
            dest = annotations.setdefault(key, {})
            for attr, value in attrs.items():
                # First non-empty value wins; fill blanks from later sources.
                if attr not in dest or (not str(dest[attr]).strip() and str(value).strip()):
                    dest[attr] = value

    attr_ids = None
    if cbioportal_attrs and cbioportal_attrs.strip().lower() != "all":
        attr_ids = [a.strip() for a in cbioportal_attrs.split(",") if a.strip()]

    for study in split_studies(cbioportal_study):
        data, cols = cbioportal.fetch_clinical(
            session, study, attribute_ids=attr_ids, base=cbioportal_base
        )
        merge(data, cols)

    if annotation_tsv:
        data, cols = read_annotation_tsv(annotation_tsv, annotation_key_col)
        merge(data, cols)

    return annotations, columns
