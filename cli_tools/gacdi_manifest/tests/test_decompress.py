from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from gacdi_manifest.download.decompress import (
    expand_directory,
    expand_gzip,
    expanded_name,
    should_expand,
)
from gacdi_manifest.errors import DownloadError


def _gz(path: Path, payload: bytes) -> Path:
    with gzip.open(path, "wb") as handle:
        handle.write(payload)
    return path


@pytest.mark.parametrize(
    "name",
    [
        "run.mzML.gz",
        "run.mzid.gz",
        "run.mzXML.gz",
        "peaks.mgf.gz",
        "matches.psm.gz",
        "table.tsv.gz",
        "notes.txt.gz",
        "search.pepXML.gz",
    ],
)
def test_text_and_xml_payloads_are_expandable(name):
    assert should_expand(Path(name)) is True


@pytest.mark.parametrize(
    "name",
    [
        # Compressed by design: gzip magic, but meaningless once expanded and
        # already modelled by dedicated Galaxy datatypes.
        "aligned.bam.gz",
        "variants.vcf.gz",
        "regions.bed.gz",
        "reads.fastq.gz",
        "genome.fasta.gz",
        "variants.vcf.gz.tbi",
        # Not gzip at all.
        "run.mzML",
        "instrument.raw",
        "slide.svs",
    ],
)
def test_protected_and_uncompressed_payloads_are_left_alone(name):
    assert should_expand(Path(name)) is False


def test_expanded_name_strips_only_the_gz_suffix():
    assert expanded_name(Path("a/b/run.mzML.gz")) == Path("a/b/run.mzML")


def test_expand_gzip_replaces_archive_with_contents(tmp_path):
    payload = b"<mzML>spectra</mzML>"
    archive = _gz(tmp_path / "run.mzML.gz", payload)

    result = expand_gzip(archive)

    assert result == tmp_path / "run.mzML"
    assert result.read_bytes() == payload
    assert not archive.exists()


def test_expand_gzip_on_truncated_archive_is_actionable_and_leaves_no_partial(tmp_path):
    archive = _gz(tmp_path / "run.mzML.gz", b"x" * 4096)
    archive.write_bytes(archive.read_bytes()[:12])

    with pytest.raises(DownloadError, match="Could not expand"):
        expand_gzip(archive)
    assert not (tmp_path / "run.mzML").exists()
    assert not (tmp_path / "run.mzML.partial").exists()


def test_expand_directory_recurses_and_skips_protected(tmp_path):
    nested = tmp_path / "uuid-1"
    nested.mkdir()
    _gz(tmp_path / "run.mzML.gz", b"<mzML/>")
    _gz(nested / "ids.mzid.gz", b"<MzIdentML/>")
    _gz(nested / "aligned.bam.gz", b"binary")

    assert expand_directory(tmp_path) == 2
    assert (tmp_path / "run.mzML").exists()
    assert (nested / "ids.mzid").exists()
    assert (nested / "aligned.bam.gz").exists()
    assert not (nested / "aligned.bam").exists()
