"""The retrying HTTP session both tools share.

Only the session constructor lives here — it is the single piece of transport
setup the builder and the downloader both need. Streaming download and checksum
helpers are downloader-specific and stay in the downloader package.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_session(retries: int = 5, backoff: float = 0.5) -> requests.Session:
    """Return a session that retries transient errors with exponential backoff."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


__all__ = ["build_session"]
