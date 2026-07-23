from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..errors import InputError


def gdc_token(token_file: Optional[str] = None) -> Optional[str]:
    """Resolve the GDC auth token: --token-file overrides the GDC_TOKEN env var."""
    if token_file:
        try:
            return Path(token_file).read_text().strip()
        except OSError as exc:
            raise InputError(f"Could not read --token-file {token_file!r}: {exc}") from exc
    return os.environ.get("GDC_TOKEN")
