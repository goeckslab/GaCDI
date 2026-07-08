import hashlib

import pytest
import requests

from gacdi.errors import ChecksumError, DownloadError
from gacdi.net import md5sum, stream_download


def test_stream_download_ok(tmp_path, requests_mock):
    content = b"hello world"
    requests_mock.get("https://example.org/f.txt", content=content)
    dest = tmp_path / "f.txt"
    n = stream_download(requests.Session(), "https://example.org/f.txt", dest)
    assert n == len(content)
    assert dest.read_bytes() == content
    assert not dest.with_suffix(".txt.part").exists()


def test_stream_download_checksum_ok(tmp_path, requests_mock):
    content = b"abc"
    digest = hashlib.md5(content).hexdigest()
    requests_mock.get("https://example.org/x", content=content)
    dest = tmp_path / "x"
    stream_download(requests.Session(), "https://example.org/x", dest, expected_md5=digest)
    assert md5sum(dest) == digest


def test_stream_download_checksum_bad(tmp_path, requests_mock):
    requests_mock.get("https://example.org/x", content=b"abc")
    dest = tmp_path / "x"
    with pytest.raises(ChecksumError):
        stream_download(requests.Session(), "https://example.org/x", dest, expected_md5="00")
    assert not dest.exists()
    assert not dest.with_suffix(".part").exists()


def test_stream_download_http_error(tmp_path, requests_mock):
    requests_mock.get("https://example.org/x", status_code=404)
    with pytest.raises(DownloadError):
        stream_download(requests.Session(), "https://example.org/x", tmp_path / "x")
