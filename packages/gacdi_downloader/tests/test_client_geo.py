"""Phase 5: isolated tests for the GEO directory client, plus source mapping
tests that inject a fake client (no HTTP)."""

from __future__ import annotations

import pytest
import requests

from gacdi.base import RunConfig
from gacdi.clients.geo import GEODirectoryClient, suppl_dir_url
from gacdi.errors import DownloadError, InputError
from gacdi.sources.geo import GEODownloadSource


# --- client (HTTP, requests_mock) -------------------------------------------
def test_client_suppl_dir_url_and_invalid():
    assert suppl_dir_url("GSE12345").endswith("/geo/series/GSE12nnn/GSE12345/suppl/")
    with pytest.raises(InputError):
        suppl_dir_url("XYZ1")


def test_client_list_filenames_parses_and_dedups(requests_mock):
    url = suppl_dir_url("GSE12345")
    requests_mock.get(
        url,
        text='<a href="../">Parent</a><a href="a.txt">a.txt</a><a href="a.txt">dup</a><a href="b.bam">b.bam</a>',
    )
    got_url, names = GEODirectoryClient().list_filenames(requests.Session(), "GSE12345")
    assert got_url == url
    assert names == ["a.txt", "b.bam"]


def test_client_http_error_becomes_download_error(requests_mock):
    requests_mock.get(suppl_dir_url("GSE12345"), status_code=404, text="no")
    with pytest.raises(DownloadError):
        GEODirectoryClient().list_filenames(requests.Session(), "GSE12345")


# --- source mapping with a fake client (no HTTP) ----------------------------
class _FakeClient:
    def __init__(self, url, names):
        self._url = url
        self._names = names

    def list_filenames(self, session, accession):
        return self._url, self._names


def test_source_maps_filenames_to_entries():
    source = GEODownloadSource(client=_FakeClient("https://x/suppl/", ["a.txt", "b.bam"]))
    entries = source.resolve(RunConfig(input_mode="accession", accessions="GSE1"), token=None)
    assert [e.filename for e in entries] == ["a.txt", "b.bam"]
    assert entries[0].url == "https://x/suppl/a.txt"
    assert entries[0].file_id == "GSE1"


def test_source_empty_listing_raises():
    source = GEODownloadSource(client=_FakeClient("https://x/suppl/", []))
    with pytest.raises(InputError):
        source.resolve(RunConfig(input_mode="accession", accessions="GSE1"), token=None)
