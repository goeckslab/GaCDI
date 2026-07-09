"""Core data structures + barcode extraction from GDC TSV rows."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# GDC TSV flattens nested fields as e.g. "cases.0.submitter_id",
# "cases.0.samples.0.submitter_id", "cases.0.samples.0.sample_type".
_CASE_BARCODE = re.compile(r"^cases\.\d+\.submitter_id$")
_SAMPLE_BARCODE = re.compile(r"^cases\.\d+\.samples\.\d+\.submitter_id$")
_SAMPLE_TYPE = re.compile(r"^cases\.\d+\.samples\.\d+\.sample_type$")
_PROJECT = re.compile(r"^cases\.\d+\.project\.project_id$")


def _first_match(row: dict, pattern: re.Pattern) -> str | None:
    for key in sorted(row):
        if pattern.match(key) and str(row[key]).strip():
            return str(row[key]).strip()
    return None


def case_barcode(row: dict) -> str | None:
    return _first_match(row, _CASE_BARCODE) or row.get("cases.submitter_id") or None


def sample_barcode(row: dict) -> str | None:
    return _first_match(row, _SAMPLE_BARCODE) or row.get("cases.samples.submitter_id") or None


def sample_type(row: dict) -> str | None:
    return _first_match(row, _SAMPLE_TYPE) or row.get("cases.samples.sample_type") or None


def project_id(row: dict) -> str | None:
    return _first_match(row, _PROJECT) or row.get("cases.project.project_id") or None


@dataclass
class FileRow:
    """One GDC file plus the raw metadata row it came from."""

    file_id: str
    filename: str
    md5: str
    size: str
    state: str
    meta: dict = field(default_factory=dict)

    @property
    def case_barcode(self) -> str | None:
        return case_barcode(self.meta)

    @property
    def sample_barcode(self) -> str | None:
        return sample_barcode(self.meta)
