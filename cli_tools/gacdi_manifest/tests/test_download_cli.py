import hashlib

from gacdi_manifest.download.cli import main

FILE_A = b"hello world\n"
FILE_B = b"second file\n"


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _write_gdc_manifest(path, rows):
    lines = ["id\tfilename\tmd5\tsize\tstate"]
    for file_id, filename, md5, size in rows:
        lines.append(f"{file_id}\t{filename}\t{md5}\t{size}\treleased")
    path.write_text("\n".join(lines) + "\n")


def test_missing_manifest_exits_input_error(tmp_path):
    rc = main([
        "--manifest", str(tmp_path / "nope.txt"),
        "--output-dir", str(tmp_path / "out"),
    ])
    assert rc == 2


def test_full_download_with_checksum_verification(tmp_path, requests_mock):
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [
        ("uuid1", "a.txt", _md5(FILE_A), len(FILE_A)),
        ("uuid2", "b.txt", _md5(FILE_B), len(FILE_B)),
    ])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=FILE_A)
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid2", content=FILE_B)

    output_dir = tmp_path / "out"
    rc = main([
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

    # Re-running should skip already-downloaded, checksum-verified files.
    rc_again = main([
        "--manifest", str(manifest),
        "--output-dir", str(output_dir),
        "--verify-checksum",
    ])
    assert rc_again == 0
    assert requests_mock.call_count == 2  # no re-fetch on the second run


def test_checksum_mismatch_reported_as_failure(tmp_path, requests_mock):
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [("uuid1", "a.txt", "deadbeef" * 4, len(FILE_A))])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=FILE_A)

    rc = main([
        "--manifest", str(manifest),
        "--output-dir", str(tmp_path / "out"),
        "--verify-checksum",
    ])
    assert rc == 1


def test_gdc_token_passed_as_header(tmp_path, requests_mock):
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [("uuid1", "a.txt", _md5(FILE_A), len(FILE_A))])
    requests_mock.get("https://api.gdc.cancer.gov/data/uuid1", content=FILE_A)

    token_file = tmp_path / "token.txt"
    token_file.write_text("secret-token\n")

    rc = main([
        "--manifest", str(manifest),
        "--output-dir", str(tmp_path / "out"),
        "--token-file", str(token_file),
    ])
    assert rc == 0
    assert requests_mock.last_request.headers["X-Auth-Token"] == "secret-token"


def test_bad_token_file_exits_input_error(tmp_path):
    manifest = tmp_path / "gdc_manifest.txt"
    _write_gdc_manifest(manifest, [("uuid1", "a.txt", _md5(FILE_A), len(FILE_A))])

    rc = main([
        "--manifest", str(manifest),
        "--output-dir", str(tmp_path / "out"),
        "--token-file", str(tmp_path / "missing-token.txt"),
    ])
    assert rc == 2
