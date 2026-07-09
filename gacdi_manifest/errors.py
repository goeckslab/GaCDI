"""Typed exceptions -> clean tool stderr and stable exit codes."""

from __future__ import annotations


class ManifestError(Exception):
    """Base class for expected manifest-builder failures."""

    exit_code = 1


class InputError(ManifestError):
    """Missing, malformed or contradictory user inputs."""

    exit_code = 2


class ApiError(ManifestError):
    """A remote API (GDC / cBioPortal) returned an error or unexpected payload."""

    exit_code = 4
