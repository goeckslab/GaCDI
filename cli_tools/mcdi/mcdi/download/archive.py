"""Extraction of archives (tar/zip/gz/bz2/xz) downloaded from commons manifests."""

from __future__ import annotations

import bz2
import gzip
import lzma
import shutil
import tarfile
import zipfile
from pathlib import Path

_TAR_SUFFIXES = {
    ".tar.gz": "r:gz",
    ".tgz": "r:gz",
    ".tar.bz2": "r:bz2",
    ".tbz2": "r:bz2",
    ".tar.xz": "r:xz",
    ".txz": "r:xz",
    ".tar": "r:",
}
_SINGLE_FILE_OPENERS = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}


class ArchiveError(Exception):
    """An archive could not be safely extracted."""


def _tar_mode(name: str) -> str | None:
    for suffix, mode in _TAR_SUFFIXES.items():
        if name.endswith(suffix):
            return mode
    return None


def is_archive(path: Path) -> bool:
    name = path.name.lower()
    return _tar_mode(name) is not None or name.endswith(".zip") or name.endswith(tuple(_SINGLE_FILE_OPENERS))


def _check_member_path(member_name: str, dest_dir: Path) -> None:
    """Reject an archive member whose path would land outside ``dest_dir`` (zip-slip)."""
    target = (dest_dir / member_name).resolve()
    if target != dest_dir and dest_dir not in target.parents:
        raise ArchiveError(f"archive member escapes destination: {member_name!r}")


def extract(path: Path) -> Path:
    """Extract ``path`` in place, into its own parent directory.

    Returns the directory extracted into (tar/zip), or the decompressed file's
    path (bare .gz/.bz2/.xz).
    """
    dest_dir = path.parent.resolve()
    name = path.name.lower()

    tar_mode = _tar_mode(name)
    if tar_mode is not None:
        with tarfile.open(path, tar_mode) as tf:
            members = tf.getmembers()
            for member in members:
                _check_member_path(member.name, dest_dir)
                if member.issym() or member.islnk():
                    raise ArchiveError(f"refusing to extract link member: {member.name!r}")
            if hasattr(tarfile, "data_filter"):
                tf.extractall(dest_dir, members=members, filter="data")
            else:
                tf.extractall(dest_dir, members=members)
        return dest_dir

    if name.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            for member_name in zf.namelist():
                _check_member_path(member_name, dest_dir)
            zf.extractall(dest_dir)
        return dest_dir

    for suffix, opener in _SINGLE_FILE_OPENERS.items():
        if name.endswith(suffix):
            target = path.with_name(path.name[: -len(suffix)])
            with opener(path, "rb") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            return target

    raise ArchiveError(f"unsupported archive type: {path.name!r}")
