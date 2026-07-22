"""cBioPortal client: list clinical attributes and fetch per-sample values.

Attribute ids (e.g. ``SUBTYPE`` for PAM50, ``ER_STATUS_BY_IHC``) are
study-specific, so we do not hard-map them: the caller supplies the study id and
an optional attribute list (or ``all``). Sample ids look like ``TCGA-XX-XXXX-01``.

Clinical attributes live at two levels in cBioPortal:

- SAMPLE level (e.g. ANEUPLOIDY_SCORE, CANCER_TYPE, MSI scores), and
- PATIENT level (e.g. SUBTYPE/PAM50, ER_STATUS_BY_IHC, PR_STATUS_BY_IHC, HER2).

We fetch **both** and merge the patient-level values onto every sample of that
patient, so subtype/receptor-status columns are included.
"""

from __future__ import annotations

import logging

import requests

from ..errors import ApiError

log = logging.getLogger("gacdi_manifest.manifest.cbioportal")

DEFAULT_BASE = "https://www.cbioportal.org/api"


def list_attributes(session: requests.Session, study_id: str, *, base: str = DEFAULT_BASE) -> list[dict]:
    """Return the clinical attributes defined for *study_id*."""
    url = f"{base.rstrip('/')}/studies/{study_id}/clinical-attributes"
    resp = session.get(url, timeout=60)
    if resp.status_code >= 400:
        raise ApiError(f"cBioPortal HTTP {resp.status_code} for {url}: {resp.text[:200]}")
    return resp.json()


def _get_clinical(session: requests.Session, study_id: str, kind: str, base: str) -> list[dict]:
    url = f"{base.rstrip('/')}/studies/{study_id}/clinical-data"
    resp = session.get(url, params={"clinicalDataType": kind, "projection": "SUMMARY"}, timeout=120)
    if resp.status_code >= 400:
        raise ApiError(f"cBioPortal HTTP {resp.status_code} for {url}: {resp.text[:200]}")
    return resp.json()


def _derive_patient(sample_id: str) -> str:
    parts = sample_id.split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else sample_id


def fetch_clinical(
    session: requests.Session,
    study_id: str,
    *,
    attribute_ids: list[str] | None = None,
    base: str = DEFAULT_BASE,
) -> tuple[dict[str, dict], list[str]]:
    """Return ``{sample_id: {attr: value}}`` and the ordered attribute columns.

    Fetches SAMPLE- and PATIENT-level clinical data and merges the patient values
    onto each of that patient's samples. If *attribute_ids* is given, only those
    attributes are kept (order preserved).
    """
    sample_records = _get_clinical(session, study_id, "SAMPLE", base)
    patient_records = _get_clinical(session, study_id, "PATIENT", base)

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
