"""Validation rules for the canonical GaCDI selection bundle.

The canonical implementation now lives in :mod:`gacdi_core.validation` (both the
builder and the downloader consume it). This module re-exports it so existing
``from gacdi.validation import ...`` imports keep working.
"""

from __future__ import annotations

from gacdi_core.validation import *  # noqa: F401,F403
from gacdi_core.validation import __all__  # noqa: F401
