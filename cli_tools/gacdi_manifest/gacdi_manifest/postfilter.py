"""Second-layer filters applied to the *generated metadata rows*.

Unlike :mod:`gacdi_manifest.filters` (which builds the GDC query and decides
which files GDC returns), these run **after** the query and the annotation join,
on the metadata table this tool produced. They trim the final manifest/metadata
down to the samples you care about — e.g. "keep only rows where ``ER_STATUS`` is
present", or "drop ``sample_type`` = Solid Tissue Normal" — using the columns you
can see in the metadata output.

A file is kept in the manifest as long as at least one of its (file x sample)
rows survives, since GDC files are downloaded whole.
"""

from __future__ import annotations

from .errors import InputError

# op -> whether it needs values=. Kept in one place so parsing and help agree.
_VALUE_OPS = {"in", "equals", "exclude", "not_equals", "contains"}
_NO_VALUE_OPS = {"present", "non_blank", "blank", "absent"}
_OPS = _VALUE_OPS | _NO_VALUE_OPS


def parse_metadata_filter(spec: str) -> dict:
    """Parse ``column=<c>;op=<op>;values=a,b`` into a normalized filter dict.

    ``op`` defaults to ``present`` (keep rows whose column is non-blank). Value
    operators (``in``/``equals``/``exclude``/``not_equals``/``contains``) require
    ``values=``; the presence/absence operators ignore it.
    """
    parts: dict[str, str] = {}
    for chunk in spec.split(";"):
        if "=" in chunk:
            key, _, val = chunk.partition("=")
            parts[key.strip().lower()] = val.strip()
    column = parts.get("column") or parts.get("field")
    op = (parts.get("op") or "present").lower()
    values = [v.strip() for v in parts.get("values", "").split(",") if v.strip()]
    if not column:
        raise InputError(
            f"Invalid --metadata-filter '{spec}'; expected column=<c>[;op=<op>][;values=a,b]."
        )
    if op not in _OPS:
        raise InputError(
            f"Unsupported op '{op}' in --metadata-filter (use one of: {', '.join(sorted(_OPS))})."
        )
    if op in _VALUE_OPS and not values:
        raise InputError(f"--metadata-filter op '{op}' needs values=... in '{spec}'.")
    return {"column": column, "op": op, "values": values}


def _row_passes(row: dict, f: dict) -> bool:
    raw = row.get(f["column"], "")
    value = ("" if raw is None else str(raw)).strip()
    op = f["op"]
    if op in ("present", "non_blank"):
        return value != ""
    if op in ("blank", "absent"):
        return value == ""
    if op in ("in", "equals"):
        return value in f["values"]
    if op in ("exclude", "not_equals"):
        return value not in f["values"]
    if op == "contains":
        low = value.lower()
        return any(v.lower() in low for v in f["values"])
    return True  # unreachable: op validated in parse


def apply_metadata_filters(
    rows: list[dict],
    specs: list[str],
    *,
    columns: list[str] | None = None,
) -> list[dict]:
    """Return the subset of *rows* passing every filter in *specs* (ANDed).

    *columns* is the known metadata header; when given, a filter naming a column
    that does not exist raises :class:`InputError` (catches typos early) rather
    than silently dropping every row.
    """
    filters = [parse_metadata_filter(s) for s in specs]
    if not filters:
        return list(rows)
    if columns is not None:
        known = set(columns)
        unknown = [f["column"] for f in filters if f["column"] not in known]
        if unknown:
            raise InputError(
                f"--metadata-filter names unknown metadata column(s): {', '.join(unknown)}. "
                f"Available columns: {', '.join(columns)}."
            )
    return [r for r in rows if all(_row_passes(r, f) for f in filters)]
