"""Minimal shared error root for GaCDI.

Only the concepts both tools genuinely share live here: a common root
(:class:`GacdiError`) and the input/contract-validation error
(:class:`InputError`) raised by the shared validators. Each tool keeps its own
richer exception hierarchy (auth/download/dependency, or manifest/api) in its own
package.
"""

from __future__ import annotations


class GacdiError(Exception):
    """Base class for all expected GaCDI failures.

    ``exit_code`` is used by the CLIs as the process return code.
    """

    exit_code = 1


class InputError(GacdiError):
    """User-supplied inputs (or a selection bundle) are missing, malformed, or contradictory."""

    exit_code = 2


__all__ = ["GacdiError", "InputError"]
