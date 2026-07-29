"""Minimal retrying HTTP session."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 60


def build_session(
    retries: int = 5,
    backoff: float = 0.5,
    allowed_methods: frozenset[str] = frozenset({"GET", "POST"}),
    user_agent: str | None = None,
) -> requests.Session:
    """Return a session that retries transient errors with exponential backoff."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=allowed_methods,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if user_agent:
        session.headers.update({"User-Agent": user_agent})
    return session
