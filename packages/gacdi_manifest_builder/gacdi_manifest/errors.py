"""Typed exceptions -> clean tool stderr and stable exit codes."""

from __future__ import annotations

from gacdi_core.errors import GacdiError, InputError as CoreInputError


class ManifestError(GacdiError):
    """Base class for expected manifest-builder failures."""

    exit_code = 1


class InputError(ManifestError, CoreInputError):
    """Missing, malformed or contradictory user inputs."""

    exit_code = 2


class ApiError(ManifestError):
    """A remote API (GDC / cBioPortal) returned an error or unexpected payload."""

    exit_code = 4
