"""Retrying HTTP session — now provided by the shared ``gacdi.net``.

This module used to carry its own copy of ``build_session`` while the manifest
builder and the ``gacdi`` downloader lived on separate branches. They are now one
codebase and the builder depends on ``gacdi``, so this is a thin re-export kept
only so existing imports (``from .net import build_session``) keep working.
"""

from __future__ import annotations

from gacdi.net import build_session

__all__ = ["build_session"]
