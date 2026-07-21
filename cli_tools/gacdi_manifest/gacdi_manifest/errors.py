"""Typed exceptions -> clean tool stderr and stable exit codes."""

from __future__ import annotations


class ManifestError(Exception):
    """Base class for expected manifest-builder failures."""

    exit_code = 1


class InputError(ManifestError):
    """Missing, malformed or contradictory user inputs."""

    exit_code = 2


class ManifestDetectionError(InputError):
    """A download manifest cannot be identified safely."""


class UnknownManifestError(ManifestDetectionError):
    """A manifest does not match a supported data commons."""


class AmbiguousManifestError(ManifestDetectionError):
    """A manifest simultaneously matches more than one data commons."""


class ApiError(ManifestError):
    """A remote API (GDC / cBioPortal) returned an error or unexpected payload."""

    exit_code = 4


class DownloadError(ManifestError):
    """A data transfer failed after the manifest was accepted."""

    exit_code = 5
