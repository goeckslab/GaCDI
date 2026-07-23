import hashlib
from pathlib import Path

from mcdi.download import engine
from mcdi.download.sources.gdc import GDCSource
from mcdi.download.sources.base import FileEntry

FILE_A = b"hello world\n"


def _entry(file_id="uuid1", filename="a.txt", md5=None) -> FileEntry:
    return FileEntry(
        file_id=file_id,
        filename=filename,
        rel_dir=Path("gdc") / file_id,
        url=f"https://api.gdc.cancer.gov/data/{file_id}",
        md5=md5,
    )


def _result(status: str, detail: str = "") -> engine.DownloadResult:
    return engine.DownloadResult(_entry(), status, detail)


def test_is_retryable_transient_http_statuses():
    for code in (429, 500, 502, 503, 504):
        assert engine._is_retryable(_result("error", f"HTTP {code}"))


def test_is_retryable_false_for_permanent_http_statuses():
    for code in (400, 401, 403, 404):
        assert not engine._is_retryable(_result("error", f"HTTP {code}"))


def test_is_retryable_true_for_connection_errors():
    # A requests.RequestException detail doesn't start with "HTTP ".
    assert engine._is_retryable(_result("error", "Connection reset by peer"))


def test_is_retryable_true_for_checksum_mismatch():
    assert engine._is_retryable(_result("checksum_mismatch", "md5 did not match manifest"))


def test_is_retryable_false_for_downloaded_and_skipped():
    assert not engine._is_retryable(_result("downloaded"))
    assert not engine._is_retryable(_result("skipped", "already present"))


def test_known_open_short_circuits_on_empty_list():
    # No requests_mock registration at all - this must not attempt any HTTP call.
    assert GDCSource().known_open([], session=None) == set()


def test_check_access_skips_files_already_satisfied_locally(tmp_path, requests_mock):
    # No mocks registered for anything - if check_access tried to touch the
    # network here, the test would fail with a mocking error.
    entry = _entry(md5="deadbeef")
    dest = tmp_path / "gdc" / "uuid1" / "a.txt"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(FILE_A)

    failures = engine.check_access([entry], GDCSource(), output_dir=tmp_path, verify=False)
    assert failures == []
    assert requests_mock.call_count == 0


def test_check_access_skips_known_open_files(requests_mock):
    entry = _entry()
    requests_mock.post("https://api.gdc.cancer.gov/files", json={"data": {"hits": [{"file_id": "uuid1", "access": "open"}]}})

    failures = engine.check_access([entry], GDCSource())
    assert failures == []
    # Only the bulk lookup ran; no per-file probe was needed for a known-open file.
    assert requests_mock.call_count == 1


def test_check_access_reports_inaccessible_files(requests_mock):
    open_entry = _entry(file_id="uuid1", filename="a.txt")
    denied_entry = _entry(file_id="uuid2", filename="b.txt")
    requests_mock.post("https://api.gdc.cancer.gov/files", json={"data": {"hits": []}})
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=FILE_A)
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid2", status_code=403, json={"message": "denied"})

    failures = engine.check_access([open_entry, denied_entry], GDCSource())
    assert [f.entry.file_id for f in failures] == ["uuid2"]
    assert "403" in failures[0].detail


def test_run_retries_transient_failure_then_succeeds(tmp_path, requests_mock):
    entry_md5 = hashlib.md5(FILE_A).hexdigest()
    requests_mock.get(
        "https://api.gdc.cancer.gov/data/uuid1",
        [
            {"status_code": 503, "content": b""},
            {"status_code": 200, "content": FILE_A},
        ],
    )
    entry = _entry(md5=entry_md5)

    results = engine.run([entry], GDCSource(), tmp_path, retries=1, retry_backoff=0)
    assert len(results) == 1
    assert results[0].status == "downloaded"
    assert (tmp_path / "gdc" / "uuid1" / "a.txt").read_bytes() == FILE_A


def test_run_does_not_retry_permanent_failure(tmp_path, requests_mock):
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", status_code=403, json={"message": "denied"})
    entry = _entry()

    results = engine.run([entry], GDCSource(), tmp_path, retries=2, retry_backoff=0)
    assert len(results) == 1
    assert results[0].status == "error"
    # One attempt only - no retry passes for a permanent-looking failure.
    assert requests_mock.call_count == 1
