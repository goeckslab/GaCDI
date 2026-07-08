"""Subprocess helper for importers that shell out to external binaries.

`gdc-client`, `prefetch`, `fasterq-dump` and friends are invoked here so that
argument redaction (tokens) and dependency checks live in one place.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Iterable, Sequence

from .errors import DependencyError

log = logging.getLogger("gacdi.proc")


def require(binary: str) -> str:
    """Return the resolved path to *binary* or raise :class:`DependencyError`."""
    path = shutil.which(binary)
    if path is None:
        raise DependencyError(
            f"Required tool '{binary}' was not found on PATH. It is provided by "
            f"the GaCDI container image or the tool's Conda requirements."
        )
    return path


def _redact(cmd: Sequence[str], secret_flags: Iterable[str]) -> list[str]:
    """Return a copy of *cmd* with the value following any secret flag masked."""
    secret = set(secret_flags)
    out: list[str] = []
    mask_next = False
    for token in cmd:
        if mask_next:
            out.append("***")
            mask_next = False
            continue
        out.append(token)
        if token in secret:
            mask_next = True
    return out


def run(
    cmd: Sequence[str],
    *,
    cwd: str | None = None,
    secret_flags: Iterable[str] = (),
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run *cmd*, logging a redacted command line.

    Token values (identified by ``secret_flags``, e.g. ``-t``) are never logged.
    Raises :class:`subprocess.CalledProcessError` on non-zero exit when *check*.
    """
    log.info("running: %s", " ".join(_redact(cmd, secret_flags)))
    return subprocess.run(  # noqa: S603 - inputs are constructed by importers
        list(cmd),
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )
