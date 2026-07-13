"""Phase 0 characterization: golden coverage of the downloader summary output.

A GDC dry-run over a fixed manifest is fully deterministic and exercises the
shared summary writer. The golden must not change during a behaviour-neutral
refactor.
"""

from __future__ import annotations

from pathlib import Path

from gacdi.cli import main

GOLDEN = Path(__file__).parent / "golden" / "gdc_summary.tsv"


def test_downloader_summary_matches_golden(tmp_path):
    manifest = tmp_path / "m.txt"
    manifest.write_text(
        "id\tfilename\tmd5\tsize\tstate\n"
        "ID1\ta.bam\taaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\t10\treleased\n"
        "ID2\tb.bam\tbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\t20\treleased\n"
    )
    summary = tmp_path / "summary.tsv"
    rc = main(
        [
            "gdc",
            "--input-mode",
            "manifest",
            "--manifest",
            str(manifest),
            "--set",
            "legacy_access=open",
            "--output-dir",
            str(tmp_path / "out"),
            "--summary",
            str(summary),
            "--dry-run",
        ]
    )
    assert rc == 0
    assert summary.read_text() == GOLDEN.read_text()
