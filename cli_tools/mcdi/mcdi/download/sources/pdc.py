from __future__ import annotations

import csv
from pathlib import Path

from .base import CANDIDATE_DELIMITERS, FileEntry, RateLimit, Source, read_header

# Columns present in every PDC file manifest (CSV/TSV) exported from the portal.
REQUIRED_HEADERS = {"PDC Study ID", "Data Category", "File Type", "File Download Link"}


def _find_md5_key(fieldnames: list[str]) -> str | None:
    for name in fieldnames:
        if "md5" in name.lower():
            return name
    return None


class PDCSource(Source):
    name = "pdc"

    @staticmethod
    def sniff(header_fields: list[str]) -> bool:
        return REQUIRED_HEADERS.issubset(set(header_fields))

    def parse_manifest(self, path: Path) -> list[FileEntry]:
        delimiter = next(
            (d for d in CANDIDATE_DELIMITERS if self.sniff(read_header(path, d))),
            CANDIDATE_DELIMITERS[-1],
        )
        entries = []
        with open(path, newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            md5_key = _find_md5_key(reader.fieldnames or [])
            for row in reader:
                filename = row["File Name"].strip()
                study_id = row["PDC Study ID"].strip()
                study_version = row["PDC Study Version"].strip()
                data_category = row["Data Category"].strip()
                file_type = row["File Type"].strip()
                run_metadata_id = (row.get("Run Metadata ID") or "").strip()

                parts = [study_id, study_version, data_category]
                if run_metadata_id and run_metadata_id.lower() != "null":
                    parts.append(run_metadata_id)
                parts.append(file_type)

                entries.append(
                    FileEntry(
                        file_id=filename,
                        filename=filename,
                        rel_dir=Path("pdc").joinpath(*parts),
                        url=row["File Download Link"].strip(),
                        md5=row[md5_key].strip() if md5_key and row.get(md5_key) else None,
                    )
                )
        return entries

    def request_kwargs(self, entry: FileEntry) -> dict:
        return {}

    def rate_limit(self) -> RateLimit:
        # Mirrors NCI's reference download script: pace requests to avoid
        # tripping PDC's 24h per-IP restriction on repeated file downloads.
        return RateLimit(max_per_window=10, window_seconds=600, per_file_sleep_seconds=2)
