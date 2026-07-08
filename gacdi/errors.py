"""Typed exceptions for GaCDI.

Importers raise these so the CLI can translate them into clean, user-facing
stderr messages and stable exit codes instead of leaking tracebacks into Galaxy
job logs.
"""

from __future__ import annotations


class GacdiError(Exception):
    """Base class for all expected GaCDI failures.

    ``exit_code`` is used by the CLI as the process return code.
    """

    exit_code = 1


class InputError(GacdiError):
    """The user-supplied inputs are missing, malformed, or contradictory."""

    exit_code = 2


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
