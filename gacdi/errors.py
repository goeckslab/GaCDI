"""Typed exceptions for GaCDI.

Importers raise these so the CLI can translate them into clean, user-facing
stderr messages and stable exit codes instead of leaking tracebacks into Galaxy
job logs.

The shared root :class:`GacdiError` and the contract/input :class:`InputError`
now live in :mod:`gacdi_core.errors` (both tools use them); they are re-exported
here so ``from gacdi.errors import GacdiError, InputError`` keeps working. The
download/auth/dependency errors below are downloader-specific and stay here.
"""

from __future__ import annotations

from gacdi_core.errors import GacdiError, InputError


class AuthError(GacdiError):
    """A controlled-access token is required, missing, or invalid."""

    exit_code = 3


class DownloadError(GacdiError):
    """A file could not be retrieved from the remote repository."""

    exit_code = 4


class ChecksumError(DownloadError):
    """A downloaded file failed checksum verification."""

    exit_code = 5


class DependencyError(GacdiError):
    """A required external binary (e.g. gdc-client, prefetch) is unavailable."""

    exit_code = 6


__all__ = [
    "GacdiError",
    "InputError",
    "AuthError",
    "DownloadError",
    "ChecksumError",
    "DependencyError",
]
