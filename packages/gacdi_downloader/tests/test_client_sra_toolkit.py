"""Phase 5: isolated tests for the SRA toolkit adapter, plus a source mapping
test that injects a fake toolkit (no subprocess)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gacdi.base import RunConfig
from gacdi.clients.sra_toolkit import SRAToolkitAdapter
from gacdi.errors import DownloadError
from gacdi.model import FileEntry
from gacdi.sources.sra import SRADownloadSource


# --- adapter ----------------------------------------------------------------
def test_adapter_runs_prefetch(monkeypatch):
    seen = {}
    monkeypatch.setattr("gacdi.clients.sra_toolkit.require", lambda b: b)
    monkeypatch.setattr("gacdi.clients.sra_toolkit.run", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    SRAToolkitAdapter().prefetch("SRR1", "/tmp/out")
    assert seen["cmd"][:2] == ["prefetch", "SRR1"]


def test_adapter_prefetch_failure_becomes_download_error(monkeypatch):
    monkeypatch.setattr("gacdi.clients.sra_toolkit.require", lambda b: b)

    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, stderr="nope")

    monkeypatch.setattr("gacdi.clients.sra_toolkit.run", boom)
    with pytest.raises(DownloadError, match="prefetch failed"):
        SRAToolkitAdapter().prefetch("SRR1", "/tmp/out")


def test_adapter_fasterq_failure_becomes_download_error(monkeypatch):
    monkeypatch.setattr("gacdi.clients.sra_toolkit.require", lambda b: b)

    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, stderr="nope")

    monkeypatch.setattr("gacdi.clients.sra_toolkit.run", boom)
    with pytest.raises(DownloadError, match="fasterq-dump failed"):
        SRAToolkitAdapter().fasterq_dump("SRR1", "/tmp/out", accession="SRR1")


# --- source with a fake toolkit ---------------------------------------------
class _FakeToolkit:
    def __init__(self, dest_writer):
        self._writer = dest_writer

    def prefetch(self, accession, dest_dir):
        (Path(dest_dir) / accession).mkdir(parents=True, exist_ok=True)

    def fasterq_dump(self, source_arg, dest_dir, *, threads=1, accession=""):
        self._writer(Path(dest_dir), accession)


def test_source_maps_and_gzips_produced_fastq(tmp_path):
    def write_fastq(dest, acc):
        (dest / f"{acc}.fastq").write_text("@r\nACGT\n+\nIIII\n")

    source = SRADownloadSource(toolkit=_FakeToolkit(write_fastq))
    entry = FileEntry(file_id="SRR1", filename="SRR1", source="sra")
    result = source.download(entry, str(tmp_path), RunConfig(input_mode="accession", jobs=1), token=None)
    assert result.status == "ok"
    assert result.paths and result.paths[0].endswith(".fastq.gz")


def test_source_no_fastq_raises(tmp_path):
    source = SRADownloadSource(toolkit=_FakeToolkit(lambda dest, acc: None))
    entry = FileEntry(file_id="SRR1", filename="SRR1", source="sra")
    with pytest.raises(DownloadError):
        source.download(entry, str(tmp_path), RunConfig(input_mode="accession"), token=None)
