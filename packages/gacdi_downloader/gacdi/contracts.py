"""Versioned selection-bundle contracts.

The canonical implementation now lives in :mod:`gacdi_core.contracts` (both the
builder and the downloader consume it). This module re-exports it so existing
``from gacdi.contracts import ...`` imports keep working.
"""

from __future__ import annotations

from gacdi_core.contracts import *  # noqa: F401,F403
from gacdi_core.contracts import __all__  # noqa: F401
