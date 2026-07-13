"""Build a GDC ``filters`` object from guided flags, custom facets and raw JSON.

Owning filter construction in Python (rather than the Galaxy Cheetah template)
keeps the wrapper trivial and lets us unit-test the exact query we send.
"""

from __future__ import annotations

from .errors import InputError

# Guided flag -> GDC field. File-level fields are unprefixed on the files
# endpoint; case-level fields use the ``cases.`` path.
GUIDED_FIELDS = {
    "project": "cases.project.project_id",
    "primary_site": "cases.primary_site",
    "disease_type": "cases.disease_type",
    "data_category": "data_category",
    "data_type": "data_type",
    "experimental_strategy": "experimental_strategy",
    "workflow_type": "analysis.workflow_type",
    "platform": "platform",
    "data_format": "data_format",
    "access": "access",
    "sample_type": "cases.samples.sample_type",
}

# Cohort-list flag -> GDC field. Each reads a list of ids and matches with ``in``.
COHORT_FIELDS = {
    "file_id_list": "file_id",
    "case_list": "cases.submitter_id",
    "sample_list": "cases.samples.submitter_id",
}


def _split(values: str) -> list[str]:
    return [v.strip() for v in values.split(",") if v.strip()]


def _clause(field: str, values: list[str], op: str = "in") -> dict:
    return {"op": op, "content": {"field": field, "value": values}}


def parse_extra_filter(spec: str) -> dict:
    """Parse ``field=<f>;op=in|exclude;values=a,b`` into a GDC filter clause."""
    parts = {}
    for chunk in spec.split(";"):
        if "=" in chunk:
            key, _, val = chunk.partition("=")
            parts[key.strip().lower()] = val.strip()
    field = parts.get("field")
    values = _split(parts.get("values", ""))
    op = parts.get("op", "in").lower()
    if not field or not values:
        raise InputError(f"Invalid --extra-filter '{spec}'; expected field=<f>;values=a,b[;op=in].")
    if op not in ("in", "exclude"):
        raise InputError(f"Unsupported op '{op}' in --extra-filter (use 'in' or 'exclude').")
    return _clause(field, values, op)


def build_filters(
    *,
    project: str | None = None,
    primary_site: str | None = None,
    disease_type: str | None = None,
    data_category: str | None = None,
    data_type: str | None = None,
    experimental_strategy: str | None = None,
    workflow_type: str | None = None,
    platform: str | None = None,
    data_format: str | None = None,
    access: str | None = None,
    sample_type: str | None = None,
    file_id_list: list[str] | None = None,
    case_list: list[str] | None = None,
    sample_list: list[str] | None = None,
    extra_filters: list[str] | None = None,
    raw_filters: dict | None = None,
) -> dict:
    """Combine every filter source with a top-level ``and``.

    Raises :class:`InputError` if no filter is supplied (guards against pulling a
    whole repository by accident).
    """
    content: list[dict] = []
    guided = {
        "project": project,
        "primary_site": primary_site,
        "disease_type": disease_type,
        "data_category": data_category,
        "data_type": data_type,
        "experimental_strategy": experimental_strategy,
        "workflow_type": workflow_type,
        "platform": platform,
        "data_format": data_format,
        "access": access,
        "sample_type": sample_type,
    }
    for name, value in guided.items():
        if value and value.strip():
            content.append(_clause(GUIDED_FIELDS[name], _split(value)))

    cohorts = {"file_id_list": file_id_list, "case_list": case_list, "sample_list": sample_list}
    for name, values in cohorts.items():
        ids = [v.strip() for v in (values or []) if v and v.strip()]
        if ids:
            content.append(_clause(COHORT_FIELDS[name], ids))

    for spec in extra_filters or []:
        content.append(parse_extra_filter(spec))

    if raw_filters:
        if raw_filters.get("op") == "and" and isinstance(raw_filters.get("content"), list):
            content.extend(raw_filters["content"])
        else:
            content.append(raw_filters)

    if not content:
        raise InputError(
            "No filters supplied. Provide at least one facet, custom filter or raw filters "
            "object so the manifest targets specific files rather than a whole repository."
        )
    return {"op": "and", "content": content}
