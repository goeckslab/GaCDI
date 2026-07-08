"""Controlled-access token handling.

Tokens (GDC, dbGaP) arrive as an uploaded Galaxy dataset. We copy the token to a
private, ``0600`` temp file for the duration of the run and never write its
contents to logs. Callers are responsible for calling :meth:`TokenFile.cleanup`
(or using it as a context manager).
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from .errors import AuthError


class TokenFile:
    """A securely-permissioned copy of a controlled-access token file."""

    def __init__(self, source: str | os.PathLike):
        src = Path(source)
        if not src.is_file():
            raise AuthError(f"Token file not found: {source}")
        data = src.read_bytes().strip()
        if not data:
            raise AuthError("Token file is empty.")

        fd, tmp = tempfile.mkstemp(prefix="gacdi_token_", suffix=".txt")
        os.close(fd)
        self.path = Path(tmp)
        self.path.write_bytes(data)
        self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600

    def cleanup(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> "TokenFile":
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()

    def __fspath__(self) -> str:
        return str(self.path)

    def __str__(self) -> str:
        return str(self.path)
