"""GaCDI — Galaxy Cancer Data Importers.

A shared toolkit for importing datasets from NIH/NCI cancer data repositories
into Galaxy histories. Each supported repository is exposed as a subcommand of
the ``gacdi`` CLI and, in turn, as a thin Galaxy tool wrapper.
"""

import os

__version__ = "0.1.1"

# Build identifier baked into the container image at build time (e.g. the git
# commit SHA). Lets you confirm the exact code a run used, even when the version
# number hasn't changed. Empty for local/editable installs.
BUILD = os.environ.get("GACDI_BUILD", "").strip()


def version_string() -> str:
    """Return the human-readable version, including the build id when present."""
    return f"{__version__}+{BUILD}" if BUILD else __version__


__all__ = ["__version__", "BUILD", "version_string"]
