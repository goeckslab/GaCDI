"""cBioPortal enrichment orchestration: list attributes and merge clinical values.

The raw HTTP calls now live in :class:`gacdi_manifest.clients.cbioportal.CBioPortalClient`;
this module owns the enrichment/join orchestration the plan keeps *outside* the
client: fetching SAMPLE- and PATIENT-level clinical data and merging the
patient-level values onto every sample of that patient, plus attribute-column
selection.

Attribute ids (e.g. ``SUBTYPE`` for PAM50, ``ER_STATUS_BY_IHC``) are
study-specific, so we do not hard-map them: the caller supplies the study id and
an optional attribute list (or ``all``). Sample ids look like ``TCGA-XX-XXXX-01``.
"""

from __future__ import annotations

import logging

import requests

from .clients.cbioportal import DEFAULT_BASE, CBioPortalClient

log = logging.getLogger("gacdi_manifest.cbioportal")


def list_attributes(
    session: requests.Session,
    study_id: str,
    *,
    base: str = DEFAULT_BASE,
    client: CBioPortalClient | None = None,
) -> list[dict]:
    """Return the clinical attributes defined for *study_id*."""
    client = client or CBioPortalClient(base=base)
    return client.list_attributes(session, study_id)


def _derive_patient(sample_id: str) -> str:
    parts = sample_id.split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else sample_id


def fetch_clinical(
    session: requests.Session,
    study_id: str,
    *,
    attribute_ids: list[str] | None = None,
    base: str = DEFAULT_BASE,
    client: CBioPortalClient | None = None,
) -> tuple[dict[str, dict], list[str]]:
    """Return ``{sample_id: {attr: value}}`` and the ordered attribute columns.

    Fetches SAMPLE- and PATIENT-level clinical data and merges the patient values
    onto each of that patient's samples. If *attribute_ids* is given, only those
    attributes are kept (order preserved).
    """
    client = client or CBioPortalClient(base=base)
    sample_records = client.clinical_data(session, study_id, "SAMPLE")
    patient_records = client.clinical_data(session, study_id, "PATIENT")

    by_sample: dict[str, dict] = {}
    sample_patient: dict[str, str] = {}
    sample_cols: list[str] = []
    for rec in sample_records:
        sample = rec.get("sampleId")
        attr = rec.get("clinicalAttributeId")
        if not sample or not attr:
            continue
        by_sample.setdefault(sample, {})[attr] = rec.get("value", "")
        if rec.get("patientId"):
            sample_patient[sample] = rec["patientId"]
        if attr not in sample_cols:
            sample_cols.append(attr)

    by_patient: dict[str, dict] = {}
    patient_cols: list[str] = []
    for rec in patient_records:
        patient = rec.get("patientId")
        attr = rec.get("clinicalAttributeId")
        if not patient or not attr:
            continue
        by_patient.setdefault(patient, {})[attr] = rec.get("value", "")
        if attr not in patient_cols:
            patient_cols.append(attr)

    merged: dict[str, dict] = {}
    for sample, attrs in by_sample.items():
        row = dict(attrs)
        patient = sample_patient.get(sample) or _derive_patient(sample)
        if patient in by_patient:
            row.update(by_patient[patient])
        merged[sample] = row

    all_cols = sample_cols + [c for c in patient_cols if c not in sample_cols]
    if attribute_ids:
        cols = [c for c in attribute_ids if c in all_cols]
        keep = set(cols)
        merged = {s: {c: v for c, v in a.items() if c in keep} for s, a in merged.items()}
    else:
        cols = sorted(all_cols)

    log.info(
        "cBioPortal: %d sample(s), %d attribute(s) (sample+patient merged).",
        len(merged),
        len(cols),
    )
    return merged, cols


__all__ = ["DEFAULT_BASE", "CBioPortalClient", "list_attributes", "fetch_clinical"]
