"""Retrying HTTP session — the single implementation lives in ``gacdi.net``.

The manifest builder and the ``gacdi`` downloader are one codebase now, so rather
than keep a second copy of ``build_session`` the builder re-exports the canonical
one. ``gacdi.net.build_session`` is the superset implementation (same retry/backoff
policy, plus HEAD support and the streamed/checksum download helpers used by the
downloader). Existing imports (``from .net import build_session``) keep working.
"""

from __future__ import annotations

from gacdi.net import build_session

__all__ = ["build_session"]
