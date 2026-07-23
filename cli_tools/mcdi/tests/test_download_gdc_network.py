from __future__ import annotations

from pathlib import Path

import pytest

from mcdi.download import engine
from mcdi.download.sources import detect_source
from mcdi.download.sources.gdc import GDCSource

# Small, open-access legacy GDC files (~1.5KB each) used purely to exercise
# the download pipeline against the real API. Released open-access files and
# their UUIDs don't change on GDC, so unlike PDC these can just be pinned
# directly in a manifest fixture instead of generated per test run.
SAMPLE_FILES = [
    {
        "id": "888550f3-e65b-4eba-8c49-0767606c1d1f",
        "filename": "TCGA-KIRP.6a47cd8d-e96b-44a4-a606-9b3447694233.ascat3.allelic_specific.seg.txt",
        "md5": "8ab04b492980883480b2ae8493110b82",
        "size": 1578,
    },
    {
        "id": "793399f0-24a4-46c6-807c-b3fd1ad1b915",
        "filename": "TCGA-KIRP.4406c3fd-d35a-45cc-8064-4caf5bc6a126.ascat3.allelic_specific.seg.txt",
        "md5": "dfa036fbc86c005e0a73ded6f37098ac",
        "size": 1578,
    },
]


def _write_manifest(path: Path) -> None:
    with open(path, "w") as f:
        f.write("id\tfilename\tmd5\tsize\n")
        for file in SAMPLE_FILES:
            f.write(f"{file['id']}\t{file['filename']}\t{file['md5']}\t{file['size']}\n")


@pytest.mark.network
def test_gdc_manifest_round_trip(tmp_path):
    manifest_path = tmp_path / "gdc_manifest.tsv"
    _write_manifest(manifest_path)

    assert detect_source(manifest_path) == "gdc"

    source = GDCSource()
    entries = source.parse_manifest(manifest_path)
    assert len(entries) == len(SAMPLE_FILES)

    output_dir = tmp_path / "downloads"
    results = engine.run(entries, source, output_dir, workers=2, verify=True)

    assert {r.status for r in results} == {"downloaded"}
    for entry, file in zip(entries, SAMPLE_FILES):
        dest = output_dir / entry.rel_dir / entry.filename
        assert dest.is_file()
        assert dest.stat().st_size == file["size"]

    # Re-running against the same output dir should skip files already
    # downloaded and checksum-verified rather than re-fetching them.
    results_again = engine.run(entries, source, output_dir, workers=2, verify=True)
    assert {r.status for r in results_again} == {"skipped"}
