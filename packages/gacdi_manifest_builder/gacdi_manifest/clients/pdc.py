"""PDC GraphQL transport client.

Owns the GraphQL conversation with the Proteomic Data Commons: the endpoint,
request construction for the ``getPaginatedUIStudy`` and ``filesPerStudy``
operations, pagination, and translation of transport/GraphQL errors into
:class:`~gacdi_manifest.errors.ApiError`. It returns raw study/file dicts; the
source (:mod:`gacdi_manifest.sources.pdc`) owns filter matching, DRS/FileRow
mapping, and harmonization.
"""

from __future__ import annotations

import logging
from typing import Iterator

import requests

from ..errors import ApiError

log = logging.getLogger("gacdi_manifest.clients.pdc")

PDC_GRAPHQL = "https://proteomic.datacommons.cancer.gov/graphql"

# Study-level fields requested for every study (attached to each file row by the
# source for harmonization + passthrough).
STUDY_FIELDS = (
    "pdc_study_id",
    "submitter_id_name",
    "disease_type",
    "primary_site",
    "analytical_fraction",
    "experiment_type",
)


class PDCGraphQLClient:
    """GraphQL client for the Proteomic Data Commons public API."""

    def __init__(self, *, endpoint: str = PDC_GRAPHQL, timeout: int = 60) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def _gql(self, session: requests.Session, query: str) -> dict:
        try:
            resp = session.post(self.endpoint, json={"query": query}, timeout=self.timeout)
        except requests.RequestException as exc:  # pragma: no cover - network only
            raise ApiError(f"PDC request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ApiError(f"PDC API returned HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if body.get("errors"):
            raise ApiError(f"PDC GraphQL error: {body['errors'][0].get('message', '')[:300]}")
        return body.get("data") or {}

    def iter_studies(self, session: requests.Session, *, page_size: int = 100) -> Iterator[dict]:
        """Yield raw UI study dicts across all pages."""
        offset = 0
        fields = " ".join(STUDY_FIELDS)
        while True:
            data = self._gql(
                session,
                f"{{ getPaginatedUIStudy(offset:{offset} limit:{page_size}) "
                f"{{ total uiStudies {{ {fields} }} }} }}",
            )
            page = data.get("getPaginatedUIStudy") or {}
            batch = page.get("uiStudies") or []
            yield from batch
            offset += page_size
            if offset >= int(page.get("total") or 0) or not batch:
                break

    def files_for_study(self, session: requests.Session, study_id: str) -> list[dict]:
        """Return the raw file dicts for one study."""
        data = self._gql(
            session,
            f'{{ filesPerStudy(pdc_study_id:"{study_id}" acceptDUA:true) '
            f"{{ file_id file_name file_type md5sum file_size data_category }} }}",
        )
        return list(data.get("filesPerStudy") or [])


__all__ = ["PDC_GRAPHQL", "STUDY_FIELDS", "PDCGraphQLClient"]
