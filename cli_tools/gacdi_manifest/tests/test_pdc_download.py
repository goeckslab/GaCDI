from __future__ import annotations

import csv
import gzip
import hashlib
import io
import http.server
import threading
from pathlib import Path

import pytest
import requests

from gacdi_manifest.download.pdc import download_pdc
from gacdi_manifest.errors import DownloadError
from gacdi_manifest.net import build_session

HEADERS = [
    "File ID",
    "File Name",
    "File Size (in bytes)",
    "Md5sum",
    "File Download Link",
    "PDC Study ID",
]


def _manifest(path: Path, rows: list[dict[str, str]], delimiter: str = ",") -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _row(name: str, url: str, content: bytes, file_id: str = "uuid-1") -> dict[str, str]:
    return {
        "File ID": file_id,
        "File Name": name,
        "File Size (in bytes)": str(len(content)),
        "Md5sum": hashlib.md5(content).hexdigest(),
        "File Download Link": url,
        "PDC Study ID": "PDC000001",
    }


def test_happy_path_two_files(tmp_path, requests_mock):
    first, second = b"first file", b"second file"
    rows = [
        _row("one.mzML", "https://pdc.test/one", first),
        _row("two.raw", "https://pdc.test/two", second, "uuid-2"),
    ]
    manifest = _manifest(tmp_path / "manifest.csv", rows)
    requests_mock.get("https://pdc.test/one", content=first)
    requests_mock.get("https://pdc.test/two", content=second)

    assert download_pdc(manifest, tmp_path / "out") == 2
    assert (tmp_path / "out/one.mzML").read_bytes() == first
    assert (tmp_path / "out/two.raw").read_bytes() == second


def test_md5_mismatch_removes_partial(tmp_path, requests_mock):
    row = _row("bad.mzML", "https://pdc.test/bad", b"wanted")
    row["File Size (in bytes)"] = str(len(b"same-size"))
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    requests_mock.get("https://pdc.test/bad", content=b"same-size")

    with pytest.raises(DownloadError, match="MD5 mismatch"):
        download_pdc(manifest, tmp_path / "out")
    assert not (tmp_path / "out/bad.mzML").exists()
    assert not (tmp_path / "out/bad.mzML.partial").exists()


def test_size_mismatch(tmp_path, requests_mock):
    row = _row("bad.raw", "https://pdc.test/bad", b"expected")
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    requests_mock.get("https://pdc.test/bad", content=b"short")
    with pytest.raises(DownloadError, match="Size mismatch"):
        download_pdc(manifest, tmp_path / "out")


def test_http_error_names_file(tmp_path, requests_mock):
    row = _row("missing.raw", "https://pdc.test/missing", b"x")
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    requests_mock.get("https://pdc.test/missing", status_code=404)
    with pytest.raises(DownloadError, match="missing.raw.*HTTP 404"):
        download_pdc(manifest, tmp_path / "out")


def test_expired_s3_url_has_actionable_message(tmp_path, requests_mock):
    row = _row("expired.raw", "https://pdc.test/expired", b"x")
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    requests_mock.get("https://pdc.test/expired", status_code=403, text="<Code>ExpiredToken</Code>")
    with pytest.raises(DownloadError, match="expire.*7 days.*Re-export"):
        download_pdc(manifest, tmp_path / "out")


def test_rate_limit_has_actionable_message(tmp_path, requests_mock):
    row = _row("limited.raw", "https://pdc.test/limited", b"x")
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    requests_mock.get("https://pdc.test/limited", status_code=429)
    with pytest.raises(DownloadError, match="download limit.*24 hours"):
        download_pdc(manifest, tmp_path / "out")


class _RetryHandler(http.server.BaseHTTPRequestHandler):
    attempts = 0
    always_fail = False
    content = b"retry succeeded"

    def do_GET(self):
        type(self).attempts += 1
        if type(self).always_fail or type(self).attempts == 1:
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).content)))
        self.end_headers()
        self.wfile.write(type(self).content)

    def log_message(self, *args):
        pass


def _retry_server(always_fail=False):
    _RetryHandler.attempts = 0
    _RetryHandler.always_fail = always_fail
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RetryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_500_then_200_succeeds_after_retry(tmp_path):
    server, thread = _retry_server()
    try:
        url = f"http://127.0.0.1:{server.server_port}/file"
        manifest = _manifest(tmp_path / "manifest.csv", [_row("retry.raw", url, _RetryHandler.content)])
        session = build_session(retries=1, backoff=0)
        assert download_pdc(manifest, tmp_path / "out", session=session) == 1
        assert _RetryHandler.attempts == 2
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_500_through_retry_budget_fails(tmp_path):
    server, thread = _retry_server(always_fail=True)
    try:
        url = f"http://127.0.0.1:{server.server_port}/file"
        manifest = _manifest(tmp_path / "manifest.csv", [_row("retry.raw", url, b"x")])
        session = build_session(retries=1, backoff=0)
        with pytest.raises(DownloadError, match="retry.raw.*HTTP 500"):
            download_pdc(manifest, tmp_path / "out", session=session)
        assert _RetryHandler.attempts == 2
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class _FailingSession:
    def get(self, *args, **kwargs):
        raise requests.ConnectionError("offline")


def test_connection_error_is_download_error(tmp_path):
    row = _row("failed.raw", "https://pdc.test/failed", b"x")
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    with pytest.raises(DownloadError, match="failed.raw.*offline"):
        download_pdc(manifest, tmp_path / "out", session=_FailingSession())


def test_existing_matching_file_is_skipped(tmp_path, requests_mock):
    content = b"already complete"
    row = _row("complete.mzML", "https://pdc.test/complete", content)
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    outdir = tmp_path / "out"
    outdir.mkdir()
    (outdir / "complete.mzML").write_bytes(content)
    assert download_pdc(manifest, outdir) == 0
    assert not requests_mock.called


def test_path_traversal_is_rejected(tmp_path, requests_mock):
    row = _row("../../outside", "https://pdc.test/evil", b"x")
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    with pytest.raises(DownloadError, match="Unsafe"):
        download_pdc(manifest, tmp_path / "out")
    assert not (tmp_path / "outside").exists()
    assert not requests_mock.called


def test_duplicate_names_append_file_id(tmp_path, requests_mock):
    first, second = b"one", b"two"
    rows = [
        _row("same.mzML", "https://pdc.test/1", first),
        _row("same.mzML", "https://pdc.test/2", second, "uuid-2"),
    ]
    manifest = _manifest(tmp_path / "manifest.csv", rows)
    requests_mock.get("https://pdc.test/1", content=first)
    requests_mock.get("https://pdc.test/2", content=second)
    download_pdc(manifest, tmp_path / "out")
    assert (tmp_path / "out/same.mzML").read_bytes() == first
    assert (tmp_path / "out/same__uuid-2.mzML").read_bytes() == second


def test_header_only_manifest_succeeds(tmp_path):
    manifest = _manifest(tmp_path / "manifest.csv", [])
    assert download_pdc(manifest, tmp_path / "out") == 0
    assert list((tmp_path / "out").iterdir()) == []


def test_missing_download_link_is_actionable(tmp_path):
    row = _row("no-link.raw", "", b"x")
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    with pytest.raises(DownloadError, match="no File Download Link.*Re-export"):
        download_pdc(manifest, tmp_path / "out")


def test_missing_md5_is_rejected_before_download(tmp_path, requests_mock):
    row = _row("unchecked.raw", "https://pdc.test/unchecked", b"x")
    row["Md5sum"] = ""
    manifest = _manifest(tmp_path / "manifest.csv", [row])
    with pytest.raises(DownloadError, match="no Md5sum"):
        download_pdc(manifest, tmp_path / "out")
    assert not requests_mock.called


def _gzipped(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        handle.write(payload)
    return buffer.getvalue()


def test_gzipped_xml_is_expanded_for_downstream_tools(tmp_path, requests_mock):
    spectra, identifications = b"<mzML>spectra</mzML>", b"<MzIdentML/>"
    rows = [
        _row("run.mzML.gz", "https://pdc.test/mzml", _gzipped(spectra)),
        _row("run.mzid.gz", "https://pdc.test/mzid", _gzipped(identifications), "uuid-2"),
    ]
    manifest = _manifest(tmp_path / "manifest.csv", rows)
    requests_mock.get("https://pdc.test/mzml", content=_gzipped(spectra))
    requests_mock.get("https://pdc.test/mzid", content=_gzipped(identifications))

    assert download_pdc(manifest, tmp_path / "out") == 2
    assert (tmp_path / "out/run.mzML").read_bytes() == spectra
    assert (tmp_path / "out/run.mzid").read_bytes() == identifications
    assert not (tmp_path / "out/run.mzML.gz").exists()


def test_integrity_is_verified_against_the_compressed_bytes(tmp_path, requests_mock):
    """The manifest describes the archive, so a corrupt archive must still fail."""
    archive = _gzipped(b"<mzML>spectra</mzML>")
    row = _row("run.mzML.gz", "https://pdc.test/mzml", archive)
    requests_mock.get("https://pdc.test/mzml", content=_gzipped(b"<mzML>different</mzML>"))
    row["File Size (in bytes)"] = str(len(_gzipped(b"<mzML>different</mzML>")))
    manifest = _manifest(tmp_path / "manifest.csv", [row])

    with pytest.raises(DownloadError, match="MD5 mismatch"):
        download_pdc(manifest, tmp_path / "out")
    assert not (tmp_path / "out/run.mzML").exists()
    assert not (tmp_path / "out/run.mzML.gz").exists()


def test_keep_compressed_preserves_the_published_file(tmp_path, requests_mock):
    archive = _gzipped(b"<mzML>spectra</mzML>")
    manifest = _manifest(tmp_path / "manifest.csv", [_row("run.mzML.gz", "https://pdc.test/m", archive)])
    requests_mock.get("https://pdc.test/m", content=archive)

    assert download_pdc(manifest, tmp_path / "out", decompress=False) == 1
    assert (tmp_path / "out/run.mzML.gz").read_bytes() == archive
    assert not (tmp_path / "out/run.mzML").exists()


def test_rerun_skips_an_already_expanded_file(tmp_path, requests_mock):
    """Expanded output is the resume signal; its MD5 cannot match the manifest."""
    archive = _gzipped(b"<mzML>spectra</mzML>")
    manifest = _manifest(tmp_path / "manifest.csv", [_row("run.mzML.gz", "https://pdc.test/m", archive)])
    outdir = tmp_path / "out"
    outdir.mkdir()
    (outdir / "run.mzML").write_bytes(b"<mzML>spectra</mzML>")

    assert download_pdc(manifest, outdir) == 0
    assert not requests_mock.called


def test_resumed_archive_from_an_interrupted_run_is_expanded(tmp_path, requests_mock):
    """A verified archive left by a crash before expansion is finished, not refetched."""
    archive = _gzipped(b"<mzML>spectra</mzML>")
    manifest = _manifest(tmp_path / "manifest.csv", [_row("run.mzML.gz", "https://pdc.test/m", archive)])
    outdir = tmp_path / "out"
    outdir.mkdir()
    (outdir / "run.mzML.gz").write_bytes(archive)

    assert download_pdc(manifest, outdir) == 0
    assert not requests_mock.called
    assert (outdir / "run.mzML").read_bytes() == b"<mzML>spectra</mzML>"
    assert not (outdir / "run.mzML.gz").exists()
