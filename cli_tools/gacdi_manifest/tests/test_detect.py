from __future__ import annotations

import logging
from pathlib import Path

import pytest

from gacdi_manifest.download.detect import detect_source
from gacdi_manifest.errors import AmbiguousManifestError, UnknownManifestError

DATA = Path(__file__).parent / "data"


def test_detects_gdc_tsv(tmp_path):
    manifest = tmp_path / "gdc.tsv"
    manifest.write_text("id\tfilename\tmd5\tsize\tstate\n", encoding="utf-8")
    assert detect_source(manifest) == "gdc"


@pytest.mark.parametrize("name", ["pdc_manifest.csv", "pdc_manifest.tsv"])
def test_detects_real_pdc_headers(name):
    assert detect_source(DATA / name) == "pdc"


@pytest.mark.parametrize(
    "header",
    [
        "FILE ID,FILE_NAME,MD5SUM,FILE DOWNLOAD LINK\r\n",
        " File ID , File   Name , Md5sum , File_Download_Link \n",
    ],
)
def test_pdc_header_normalization(tmp_path, header):
    manifest = tmp_path / "pdc.csv"
    manifest.write_text(header, encoding="utf-8")
    assert detect_source(manifest) == "pdc"


def test_bom_crlf_and_leading_blanks(tmp_path):
    manifest = tmp_path / "gdc.tsv"
    manifest.write_bytes(b"\xef\xbb\xbf\r\n\r\nid\tfilename\tmd5\tsize\tstate\r\n")
    assert detect_source(manifest) == "gdc"


def test_gdc_extra_columns_warn(tmp_path, caplog):
    manifest = tmp_path / "gdc.tsv"
    manifest.write_text("id\tfilename\tmd5\tsize\tstate\textra\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert detect_source(manifest) == "gdc"
    assert "extra" in caplog.text


def test_unknown_header_reports_observed_and_expected_columns(tmp_path):
    manifest = tmp_path / "metadata.tsv"
    manifest.write_text("sample\tdisease\tlabel\n", encoding="utf-8")
    with pytest.raises(UnknownManifestError) as error:
        detect_source(manifest)
    message = str(error.value)
    assert "sample" in message
    assert "id/filename/md5/size" in message
    assert "File Download Link" in message


def test_ambiguous_header(tmp_path):
    manifest = tmp_path / "ambiguous.tsv"
    manifest.write_text(
        "id\tfilename\tmd5\tsize\tstate\tFile Name\tPDC Study ID\tFile Download Link\n",
        encoding="utf-8",
    )
    with pytest.raises(AmbiguousManifestError):
        detect_source(manifest)


def test_empty_file_is_unknown(tmp_path):
    manifest = tmp_path / "empty.tsv"
    manifest.write_text("\n\n", encoding="utf-8")
    with pytest.raises(UnknownManifestError, match="empty"):
        detect_source(manifest)


def test_header_only_file_detects_normally(tmp_path):
    manifest = tmp_path / "pdc.csv"
    manifest.write_text("File ID,File Name,Md5sum,File Download Link\n", encoding="utf-8")
    assert detect_source(manifest) == "pdc"


def test_pdc_study_manifest_is_not_mistaken_for_file_manifest(tmp_path):
    manifest = tmp_path / "study.csv"
    manifest.write_text("PDC Study ID,Study ID,Study Name\n", encoding="utf-8")
    with pytest.raises(UnknownManifestError):
        detect_source(manifest)
