"""GaCDI shared foundation.

A deliberately narrow package that both runtime tools consume: the canonical
selection-bundle contracts, their validators, the retrying HTTP session
constructor, and a minimal shared error root. Tool-specific domain models,
history/output writers, and exception hierarchies deliberately do **not** live
here (see the refactor plan's ownership rules).
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
