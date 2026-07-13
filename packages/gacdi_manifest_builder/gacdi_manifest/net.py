"""Retrying HTTP session — the single implementation lives in ``gacdi_core.net``.

The builder and the ``gacdi`` downloader share one retrying session constructor.
It lives in the shared foundation package; this module re-exports it so existing
imports (``from .net import build_session``) keep working.
"""

from __future__ import annotations

from gacdi_core.net import build_session

__all__ = ["build_session"]
