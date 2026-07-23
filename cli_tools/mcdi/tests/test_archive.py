import gzip
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from mcdi.download import archive


def test_is_archive_recognizes_common_suffixes():
    for name in ["a.tar.gz", "a.tgz", "a.tar.bz2", "a.tar.xz", "a.tar", "a.zip", "a.gz", "a.bz2", "a.xz"]:
        assert archive.is_archive(Path(name)), name


def test_is_archive_false_for_plain_files():
    assert not archive.is_archive(Path("a.txt"))
    assert not archive.is_archive(Path("a.svs"))


def test_extract_tar_gz(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "inner.txt").write_text("hello")

    archive_path = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(src_dir / "inner.txt", arcname="inner.txt")

    result = archive.extract(archive_path)
    assert result == tmp_path.resolve()
    assert (tmp_path / "inner.txt").read_text() == "hello"


def test_extract_zip(tmp_path):
    archive_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("inner.txt", "hello zip")

    archive.extract(archive_path)
    assert (tmp_path / "inner.txt").read_text() == "hello zip"


def test_extract_bare_gz(tmp_path):
    archive_path = tmp_path / "data.txt.gz"
    with gzip.open(archive_path, "wb") as f:
        f.write(b"plain content")

    result = archive.extract(archive_path)
    assert result == tmp_path / "data.txt"
    assert result.read_bytes() == b"plain content"


def test_extract_rejects_tar_path_traversal(tmp_path):
    archive_path = tmp_path / "evil.tar"
    with tarfile.open(archive_path, "w") as tf:
        info = tarfile.TarInfo(name="../escaped.txt")
        data = b"pwned"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    with pytest.raises(archive.ArchiveError):
        archive.extract(archive_path)
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_extract_rejects_zip_path_traversal(tmp_path):
    archive_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("../escaped.txt", "pwned")

    with pytest.raises(archive.ArchiveError):
        archive.extract(archive_path)
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_extract_unsupported_type_raises(tmp_path):
    path = tmp_path / "plain.txt"
    path.write_text("not an archive")
    with pytest.raises(archive.ArchiveError):
        archive.extract(path)
