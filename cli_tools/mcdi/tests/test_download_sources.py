import base64
import json
import time
from pathlib import Path

import pytest

from mcdi.download.sources import detect_source
from mcdi.download.sources.gdc import GDCSource
from mcdi.download.sources.pdc import PDCSource
from mcdi.errors import InputError

GDC_HEADER = ["id", "filename", "md5", "size", "state"]
PDC_HEADER = ["PDC Study ID", "PDC Study Version", "Data Category", "File Type",
              "File Name", "File MD5sum", "File Download Link"]


def _fresh_signed_url(resource: str = "https://example.cloudfront.net/foo.raw") -> str:
    policy = json.dumps(
        {"Statement": [{"Resource": resource, "Condition": {"DateLessThan": {"AWS:EpochTime": int(time.time()) + 86400}}}]},
        separators=(",", ":"),
    ).encode()
    encoded = base64.b64encode(policy).decode().replace("+", "-").replace("=", "_").replace("/", "~")
    return f"{resource}?Policy={encoded}&Key-Pair-Id=X&Signature=Y"


class _UnusedRefresher:
    def fetch_study(self, study_id):
        raise AssertionError("refresher should not be called for a fresh URL")


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

    url = _fresh_signed_url()
    manifest = tmp_path / "pdc_manifest.csv"
    manifest.write_text(
        "PDC Study ID,PDC Study Version,Data Category,File Type,File Name,"
        f"File MD5sum,File Download Link\nPDC000109,1,Raw Mass Spectra,raw,foo.raw,abc123,{url}\n"
    )
    entries = PDCSource(refresher=_UnusedRefresher()).parse_manifest(manifest)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.filename == "foo.raw"
    assert entry.md5 == "abc123"
    assert entry.url == url
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


def test_gdc_pdc_sniff_lines_default_false_and_unaffected_by_content_hook():
    # GDC/PDC don't override sniff_lines - the default no-match behavior
    # must hold regardless of what content is passed, so adding the hook for
    # IDC can't change their detection.
    assert not GDCSource.sniff_lines(["cp s3://idc-open-data/uuid1/* .\n"])
    assert not PDCSource.sniff_lines(["cp s3://idc-open-data/uuid1/* .\n"])


def test_detect_source_matches_headerless_manifest_via_sniff_lines(tmp_path):
    manifest = tmp_path / "m.s5cmd"
    manifest.write_text("# IDC portal export\ncp s3://idc-open-data/uuid1/* .\n")
    assert detect_source(manifest) == "idc"


def test_gdc_write_subset_manifest_keeps_only_failed_rows(tmp_path):
    manifest = tmp_path / "gdc_manifest.txt"
    manifest.write_text(
        "id\tfilename\tmd5\tsize\tstate\n"
        "uuid1\tA.svs\tmd5a\t100\treleased\n"
        "uuid2\tB.svs\tmd5b\t200\treleased\n"
    )
    output = tmp_path / "gdc_manifest.retry.txt"
    GDCSource().write_subset_manifest(manifest, {"uuid2"}, output)

    lines = output.read_text().splitlines()
    assert lines[0] == "id\tfilename\tmd5\tsize\tstate"
    assert lines[1] == "uuid2\tB.svs\tmd5b\t200\treleased"
    assert len(lines) == 2

    # the subset manifest must itself be re-parseable
    retried = GDCSource().parse_manifest(output)
    assert [e.file_id for e in retried] == ["uuid2"]


def test_pdc_write_subset_manifest_keeps_only_failed_rows(tmp_path):
    url_a = _fresh_signed_url("https://example.cloudfront.net/a.raw")
    url_b = _fresh_signed_url("https://example.cloudfront.net/b.raw")
    manifest = tmp_path / "pdc_manifest.csv"
    manifest.write_text(
        "PDC Study ID,PDC Study Version,Data Category,File Type,File Name,"
        "File MD5sum,File Download Link\n"
        f"PDC000109,1,Raw Mass Spectra,raw,a.raw,md5a,{url_a}\n"
        f"PDC000109,1,Raw Mass Spectra,raw,b.raw,md5b,{url_b}\n"
    )
    output = tmp_path / "pdc_manifest.retry.csv"
    PDCSource(refresher=_UnusedRefresher()).write_subset_manifest(manifest, {"b.raw"}, output)

    lines = output.read_text().splitlines()
    assert len(lines) == 2
    assert "b.raw" in lines[1]
    assert "a.raw" not in lines[1]

    retried = PDCSource(refresher=_UnusedRefresher()).parse_manifest(output)
    assert [e.filename for e in retried] == ["b.raw"]


def test_pdc_parse_manifest_ignores_filename_extension(tmp_path):
    manifest = tmp_path / "dataset_3.dat"
    manifest.write_text(
        "PDC Study ID,PDC Study Version,Data Category,File Type,File Name,"
        f"File MD5sum,File Download Link\nPDC000109,1,Raw Mass Spectra,raw,foo.raw,abc123,{_fresh_signed_url()}\n"
    )
    entries = PDCSource(refresher=_UnusedRefresher()).parse_manifest(manifest)
    assert len(entries) == 1
    assert entries[0].filename == "foo.raw"
