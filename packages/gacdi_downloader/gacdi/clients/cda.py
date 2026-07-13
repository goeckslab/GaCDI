"""Cancer Data Aggregator SDK adapter.

Owns the lazy ``cdapython`` invocation: importing the optional SDK only when a CDA
query actually runs, calling ``fetch_rows``, and normalising the result to a list
of dicts. The source (:mod:`gacdi.sources.cda`) owns query mapping, commons
routing, and asset mapping.
"""

from __future__ import annotations

from ..errors import DependencyError


class CDASdkAdapter:
    """Adapter around the optional ``cdapython`` SDK."""

    def fetch_rows(self, **kwargs) -> list[dict]:
        """Call ``cdapython.fetch_rows`` and normalise the result to a list of dicts.

        ``cdapython`` is imported lazily so the package works without it installed;
        it is only required at runtime for the CDA tool (provided by the gacdi-cda
        container image).
        """
        try:
            from cdapython import fetch_rows  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised via container only
            raise DependencyError(
                "The 'cdapython' package is required for the CDA importer. It is "
                "provided by the GaCDI CDA container image."
            ) from exc
        result = fetch_rows(**kwargs)
        if hasattr(result, "to_dict"):  # pandas DataFrame
            return result.to_dict("records")
        return list(result)


__all__ = ["CDASdkAdapter"]
