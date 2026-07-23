from __future__ import annotations

import csv
from pathlib import Path

import pytest
import requests

from mcdi.download import engine
from mcdi.download.sources import detect_source
from mcdi.download.sources.pdc import PDCSource

GRAPHQL_URL = "https://pdc.cancer.gov/graphql"

# A small, stable CPTAC study used only as a source of a couple of tiny
# open-access files to exercise the download pipeline end-to-end.
STUDY_ID = "PDC000109"
SAMPLE_FILE_COUNT = 2

# `filesPerStudy` is the same query the PDC portal's Explore page uses to
# resolve each file's CloudFront `signedUrl`. It isn't in PDC's published
# API docs (found via GraphQL suggestion errors: `filesPerStudy(pdc_study_id)
# { signedUrl { url } }`), but it's a live query against the same public,
# tokenless GraphQL endpoint the portal itself calls, not a private one.
FILES_PER_STUDY_QUERY = """
query FilesPerStudy($studyId: String!) {
  filesPerStudy(pdc_study_id: $studyId) {
    file_id
    file_name
    file_size
    md5sum
    file_type
    data_category
    signedUrl { url }
  }
}
"""


def _fetch_sample_files() -> list[dict]:
    """Ask PDC's live GraphQL API for a fresh, signed download URL per file.

    PDC's exported manifests embed pre-signed CloudFront URLs whose
    signatures expire ~7 days after issuance (see README). A manifest
    fixture checked into the repo would eventually go stale and start
    failing with 403s, so the manifest content is instead built here, at
    test time, from a live `signedUrl` query.
    """
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": FILES_PER_STUDY_QUERY, "variables": {"studyId": STUDY_ID}},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        pytest.skip(f"PDC GraphQL API returned errors: {payload['errors']}")
    files = payload["data"]["filesPerStudy"]
    if not files:
        pytest.skip(f"PDC study {STUDY_ID} returned no files")
    return sorted(files, key=lambda f: int(f["file_size"]))[:SAMPLE_FILE_COUNT]


def _write_manifest(path: Path, files: list[dict]) -> None:
    fieldnames = [
        "PDC Study ID",
        "PDC Study Version",
        "Data Category",
        "File Type",
        "File Name",
        "File MD5sum",
        "File Download Link",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for file in files:
            writer.writerow(
                {
                    "PDC Study ID": STUDY_ID,
                    # Not exposed by filesPerStudy; only affects the local
                    # output subdirectory name, not download correctness.
                    "PDC Study Version": "1",
                    "Data Category": file["data_category"],
                    "File Type": file["file_type"],
                    "File Name": file["file_name"],
                    "File MD5sum": file["md5sum"],
                    "File Download Link": file["signedUrl"]["url"],
                }
            )


@pytest.mark.network
def test_pdc_manifest_round_trip(tmp_path):
    files = _fetch_sample_files()
    manifest_path = tmp_path / "pdc_manifest.csv"
    _write_manifest(manifest_path, files)

    assert detect_source(manifest_path) == "pdc"

    source = PDCSource()
    entries = source.parse_manifest(manifest_path)
    assert len(entries) == len(files)

    output_dir = tmp_path / "downloads"
    results = engine.run(entries, source, output_dir, workers=1, verify=True)

    assert {r.status for r in results} == {"downloaded"}
    for entry, file in zip(entries, files):
        dest = output_dir / entry.rel_dir / entry.filename
        assert dest.is_file()
        assert dest.stat().st_size == int(file["file_size"])

    # Re-running against the same output dir should skip files already
    # downloaded and checksum-verified rather than re-fetching them.
    results_again = engine.run(entries, source, output_dir, workers=1, verify=True)
    assert {r.status for r in results_again} == {"skipped"}
