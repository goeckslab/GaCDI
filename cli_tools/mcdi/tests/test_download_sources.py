from pathlib import Path

import pytest

from mcdi.download.sources import detect_source
from mcdi.download.sources.gdc import GDCSource
from mcdi.download.sources.pdc import PDCSource
from mcdi.errors import InputError

GDC_HEADER = ["id", "filename", "md5", "size", "state"]
PDC_HEADER = ["PDC Study ID", "PDC Study Version", "Data Category", "File Type",
              "File Name", "File MD5sum", "File Download Link"]


def test_gdc_sniff_and_parse(tmp_path):
    assert GDCSource.sniff(GDC_HEADER)
    assert not GDCSource.sniff(PDC_HEADER)

    manifest = tmp_path / "gdc_manifest.txt"
    manifest.write_text("id\tfilename\tmd5\tsize\tstate\n"
                         "uuid1\tA.svs\tmd5a\t100\treleased\n")
    entries = GDCSource().parse_manifest(manifest)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.file_id == "uuid1"
    assert entry.filename == "A.svs"
    assert entry.md5 == "md5a"
    assert entry.size == 100
    assert entry.rel_dir == Path("gdc") / "uuid1"
    assert entry.url.endswith("/data/uuid1")


def test_gdc_request_kwargs_carries_token():
    assert GDCSource(token="tok-123").request_kwargs(None) == {"headers": {"X-Auth-Token": "tok-123"}}
    assert GDCSource().request_kwargs(None) == {"headers": {}}


def test_pdc_sniff_and_parse(tmp_path):
    assert PDCSource.sniff(PDC_HEADER)
    assert not PDCSource.sniff(GDC_HEADER)

    manifest = tmp_path / "pdc_manifest.csv"
    manifest.write_text(
        "PDC Study ID,PDC Study Version,Data Category,File Type,File Name,"
        "File MD5sum,File Download Link\n"
        "PDC000109,1,Raw Mass Spectra,raw,foo.raw,abc123,https://example.com/foo.raw\n"
    )
    entries = PDCSource().parse_manifest(manifest)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.filename == "foo.raw"
    assert entry.md5 == "abc123"
    assert entry.url == "https://example.com/foo.raw"
    assert entry.rel_dir == Path("pdc") / "PDC000109" / "1" / "Raw Mass Spectra" / "raw"


def test_detect_source_success(tmp_path):
    manifest = tmp_path / "m.txt"
    manifest.write_text("id\tfilename\tmd5\tsize\tstate\nuuid1\tA.svs\tmd5a\t100\treleased\n")
    assert detect_source(manifest) == "gdc"


def test_detect_source_unrecognized_raises_input_error(tmp_path):
    manifest = tmp_path / "m.txt"
    manifest.write_text("foo\tbar\n1\t2\n")
    with pytest.raises(InputError):
        detect_source(manifest)


def test_detect_source_ignores_filename_extension(tmp_path):
    # Pipelines that stage uploads under a generic name (e.g. Galaxy's
    # `dataset_<uuid>.dat`) don't preserve the manifest's original
    # extension, so detection must work from content alone.
    gdc_manifest = tmp_path / "dataset_1.dat"
    gdc_manifest.write_text("id\tfilename\tmd5\tsize\tstate\nuuid1\tA.svs\tmd5a\t100\treleased\n")
    assert detect_source(gdc_manifest) == "gdc"

    pdc_manifest = tmp_path / "dataset_2.dat"
    pdc_manifest.write_text(
        "PDC Study ID,PDC Study Version,Data Category,File Type,File Name,"
        "File MD5sum,File Download Link\n"
        "PDC000109,1,Raw Mass Spectra,raw,foo.raw,abc123,https://example.com/foo.raw\n"
    )
    assert detect_source(pdc_manifest) == "pdc"


def test_pdc_parse_manifest_ignores_filename_extension(tmp_path):
    manifest = tmp_path / "dataset_3.dat"
    manifest.write_text(
        "PDC Study ID,PDC Study Version,Data Category,File Type,File Name,"
        "File MD5sum,File Download Link\n"
        "PDC000109,1,Raw Mass Spectra,raw,foo.raw,abc123,https://example.com/foo.raw\n"
    )
    entries = PDCSource().parse_manifest(manifest)
    assert len(entries) == 1
    assert entries[0].filename == "foo.raw"
