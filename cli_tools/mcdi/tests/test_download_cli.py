import hashlib
import io
import tarfile

from mcdi.cli import main

FILE_A = b"hello world\n"
FILE_B = b"second file\n"


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _tar_gz_bytes(member_name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name=member_name)
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _write_gdc_manifest(path, rows):
    lines = ["id\tfilename\tmd5\tsize\tstate"]
    for file_id, filename, md5, size in rows:
        lines.append(f"{file_id}\t{filename}\t{md5}\t{size}\treleased")
    path.write_text("\n".join(lines) + "\n")


def _mock_known_open_empty(requests_mock):
    """Stub the bulk access-field lookup `check_access` makes before probing
    individual files, so tests aren't asserting anything about which files
    GDC would call "open" - they exercise the per-file probe fallback path
    instead, which is what actually needs mocked file URLs anyway."""
    requests_mock.post("https://api.gdc.cancer.gov/files", json={"data": {"hits": []}})


def test_missing_manifest_exits_input_error(tmp_path):
    rc = main([
        "download",
        "--manifest", str(tmp_path / "nope.txt"),
        "--output-dir", str(tmp_path / "out"),
    ])
    assert rc == 2


def test_full_download_with_checksum_verification(tmp_path, requests_mock):
    _mock_known_open_empty(requests_mock)
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [
        ("uuid1", "a.txt", _md5(FILE_A), len(FILE_A)),
        ("uuid2", "b.txt", _md5(FILE_B), len(FILE_B)),
    ])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=FILE_A)
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid2", content=FILE_B)

    output_dir = tmp_path / "out"
    rc = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(output_dir),
        "--verify-checksum",
        "--workers", "2",
    ])
    assert rc == 0

    a = output_dir / "gdc" / "uuid1" / "a.txt"
    b = output_dir / "gdc" / "uuid2" / "b.txt"
    assert a.read_bytes() == FILE_A
    assert b.read_bytes() == FILE_B

    # Re-running should skip already-downloaded, checksum-verified files -
    # including skipping their pre-flight access re-check.
    rc_again = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(output_dir),
        "--verify-checksum",
    ])
    assert rc_again == 0
    # First run: 1 known_open lookup + 2 pre-flight probes + 2 real downloads.
    # Second run: everything already satisfied locally, so zero new calls.
    assert requests_mock.call_count == 5


def test_checksum_mismatch_reported_as_failure(tmp_path, requests_mock):
    _mock_known_open_empty(requests_mock)
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [("uuid1", "a.txt", "deadbeef" * 4, len(FILE_A))])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=FILE_A)

    rc = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(tmp_path / "out"),
        "--verify-checksum",
        "--retries", "0",  # a checksum mismatch is retried by default; keep this test fast/deterministic
    ])
    assert rc == 1


def test_gdc_token_passed_as_header(tmp_path, requests_mock):
    _mock_known_open_empty(requests_mock)
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [("uuid1", "a.txt", _md5(FILE_A), len(FILE_A))])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=FILE_A)

    token_file = tmp_path / "token.txt"
    token_file.write_text("secret-token\n")

    rc = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(tmp_path / "out"),
        "--token-file", str(token_file),
    ])
    assert rc == 0
    # Both the pre-flight probe and the real download carry the token; the
    # real download happens last, so it's what last_request reflects.
    assert requests_mock.last_request.headers["X-Auth-Token"] == "secret-token"


def test_bad_token_file_exits_input_error(tmp_path):
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [("uuid1", "a.txt", _md5(FILE_A), len(FILE_A))])

    rc = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(tmp_path / "out"),
        "--token-file", str(tmp_path / "missing-token.txt"),
    ])
    assert rc == 2


def test_preflight_aborts_before_downloading_anything(tmp_path, requests_mock):
    """One inaccessible file among several must stop the whole run before any
    download starts - not be discovered only after the others succeed."""
    _mock_known_open_empty(requests_mock)
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [
        ("uuid1", "a.txt", _md5(FILE_A), len(FILE_A)),
        ("uuid2", "b.txt", _md5(FILE_B), len(FILE_B)),
    ])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=FILE_A)
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid2", status_code=403, json={"message": "not authorized"})

    output_dir = tmp_path / "out"
    rc = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(output_dir),
    ])
    assert rc == 1
    # Nothing was downloaded, including the file that would have succeeded.
    assert not output_dir.exists() or not any(output_dir.rglob("*"))


def test_extract_off_by_default(tmp_path, requests_mock):
    _mock_known_open_empty(requests_mock)
    archive_bytes = _tar_gz_bytes("inner.txt", b"payload")
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [("uuid1", "bundle.tar.gz", _md5(archive_bytes), len(archive_bytes))])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=archive_bytes)

    output_dir = tmp_path / "out"
    rc = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(output_dir),
    ])
    assert rc == 0

    dest_dir = output_dir / "gdc" / "uuid1"
    assert (dest_dir / "bundle.tar.gz").exists()
    assert not (dest_dir / "inner.txt").exists()


def test_extract_flag_unpacks_archive(tmp_path, requests_mock):
    _mock_known_open_empty(requests_mock)
    archive_bytes = _tar_gz_bytes("inner.txt", b"payload")
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [("uuid1", "bundle.tar.gz", _md5(archive_bytes), len(archive_bytes))])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=archive_bytes)

    output_dir = tmp_path / "out"
    rc = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(output_dir),
        "--extract",
    ])
    assert rc == 0

    dest_dir = output_dir / "gdc" / "uuid1"
    # only the extracted contents remain at the manifest's output path...
    assert not (dest_dir / "bundle.tar.gz").exists()
    assert (dest_dir / "inner.txt").read_bytes() == b"payload"
    # ...the archive moved aside to the sibling archive directory, not deleted
    archived_dir = output_dir.with_name(output_dir.name + ".mcdi-archives") / "gdc" / "uuid1"
    assert (archived_dir / "bundle.tar.gz").read_bytes() == archive_bytes

    # re-running with --extract again doesn't re-fetch, re-probe, or re-extract
    rc_again = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(output_dir),
        "--extract",
    ])
    assert rc_again == 0
    assert requests_mock.call_count == 3  # 1 known_open + 1 pre-flight probe + 1 download, first run only


def test_extract_failure_leaves_archive_in_place(tmp_path, requests_mock):
    _mock_known_open_empty(requests_mock)
    # Named like a tar.gz but not actually one - extraction must fail cleanly.
    bad_bytes = b"not actually a gzip stream"
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [("uuid1", "bundle.tar.gz", _md5(bad_bytes), len(bad_bytes))])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=bad_bytes)

    output_dir = tmp_path / "out"
    rc = main([
        "download",
        "--manifest", str(manifest),
        "--output-dir", str(output_dir),
        "--extract",
    ])
    assert rc == 1  # extraction errors are reported as a run failure

    dest_dir = output_dir / "gdc" / "uuid1"
    # the archive was NOT moved aside, since extraction never succeeded
    assert (dest_dir / "bundle.tar.gz").read_bytes() == bad_bytes
    archived_dir = output_dir.with_name(output_dir.name + ".mcdi-archives") / "gdc" / "uuid1"
    assert not archived_dir.exists()
