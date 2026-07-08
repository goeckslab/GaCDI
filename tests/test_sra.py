import gzip
from pathlib import Path

import pytest

from gacdi.base import RunConfig
from gacdi.errors import InputError
from gacdi.importers.sra import SRAImporter
from gacdi.model import FileEntry


def test_resolve_validates_accessions():
    imp = SRAImporter()
    with pytest.raises(InputError):
        imp.resolve(RunConfig(input_mode="accession", accessions="not-an-accession"), None)
    entries = imp.resolve(RunConfig(input_mode="accession", accessions="SRR000001, SRR000002"), None)
    assert [e.file_id for e in entries] == ["SRR000001", "SRR000002"]


def test_download_paired(tmp_path, monkeypatch):
    monkeypatch.setattr("gacdi.importers.sra.require", lambda b: b)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "prefetch":
            d = Path(tmp_path) / "SRR000001"
            d.mkdir(parents=True, exist_ok=True)
            (d / "SRR000001.sra").write_bytes(b"sra")
        else:  # fasterq-dump
            (Path(tmp_path) / "SRR000001_1.fastq").write_text("@r\nAC\n+\nII\n")
            (Path(tmp_path) / "SRR000001_2.fastq").write_text("@r\nGT\n+\nII\n")

    monkeypatch.setattr("gacdi.importers.sra.run", fake_run)
    entry = FileEntry(file_id="SRR000001", filename="SRR000001", source="sra")
    res = SRAImporter().download(entry, str(tmp_path), RunConfig(), None)
    assert res.status == "ok"
    assert sorted(Path(p).name for p in res.paths) == [
        "SRR000001_1.fastq.gz",
        "SRR000001_2.fastq.gz",
    ]
    # gzip is valid and the prefetch dir was cleaned up
    with gzip.open(tmp_path / "SRR000001_1.fastq.gz", "rt") as fh:
        assert fh.read().startswith("@r")
    assert not (tmp_path / "SRR000001").exists()


def test_download_no_fastq_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("gacdi.importers.sra.require", lambda b: b)
    monkeypatch.setattr("gacdi.importers.sra.run", lambda cmd, **kw: None)
    with pytest.raises(Exception):
        SRAImporter().download(
            FileEntry(file_id="SRR000001", filename="SRR000001"), str(tmp_path), RunConfig(), None
        )
