"""GDC (Genomic Data Commons) importer.

Three input modes:

- ``bundle``   : the canonical asset manifest, metadata, and provenance sidecar.
- ``manifest`` : a GDC-exported manifest TSV.
- ``query``    : a JSON document with a GDC ``filters`` object; we query the REST
                 API to enumerate matching files, then download them.

Downloads use the official ``gdc-client`` (bioconda), which handles segmented
transfer, retries and checksum verification. Controlled-access files are
supported via ``--token`` (never logged).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from ..auth import TokenFile
from ..base import BaseImporter, RunConfig
from ..bundle import load_selection_bundle, sha256_file
from ..errors import ChecksumError, DownloadError, InputError
from ..manifest import load_query, parse_gdc_manifest
from ..history import unique_path
from ..model import DownloadResult, FileEntry, ProducedDataset
from ..net import md5sum
from ..proc import require, run

log = logging.getLogger("gacdi.gdc")

API_FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"
_QUERY_FIELDS = "file_id,file_name,md5sum,file_size"
# Files fetched per request when paging a query. The importer pages through *all*
# matching files regardless of this value; it only controls request granularity.
_PAGE_SIZE = 500
_SAFE_GDC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_GALAXY_EXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_GDC_PROFILE_EXTENSIONS = {
    "single_bam": {"bam"},
    "single_cram": {"cram"},
    "single_vcf": {"vcf", "vcf_bgzip"},
    "single_svs": {"svs"},
    "single_table": {"tabular", "csv", "txt"},
}
_GDC_PROFILE_FORMATS = {
    "single_bam": {"bam"},
    "single_cram": {"cram"},
    "single_vcf": {"vcf"},
    "single_svs": {"svs"},
    "single_table": {"tsv", "csv", "txt", "maf"},
}


def _validate_gdc_id(value: str) -> None:
    """Reject path or option-like IDs before invoking or cleaning up gdc-client."""
    if not _SAFE_GDC_ID.fullmatch(value) or value in {".", ".."}:
        raise InputError(
            f"Unsafe GDC asset id '{value}'. Expected an alphanumeric GDC identifier "
            "containing only letters, digits, dots, underscores, or hyphens."
        )


class GDCImporter(BaseImporter):
    name = "gdc"
    supports_controlled = True
    supported_modes = ("manifest", "bundle", "query")

    def resolve(self, cfg: RunConfig, token: TokenFile | None) -> list[FileEntry]:
        if cfg.input_mode == "manifest":
            if not cfg.manifest:
                raise InputError("GDC manifest mode requires --manifest.")
            access = str(cfg.options.get("legacy_access", "")).strip().lower()
            if access not in {"open", "controlled"}:
                raise InputError(
                    "Legacy GDC manifest mode requires an explicit access declaration: "
                    "pass --set legacy_access=open or --set legacy_access=controlled."
                )
            entries = parse_gdc_manifest(cfg.manifest, source=self.name)
            preflight_error = (
                "This legacy GDC manifest was declared controlled; provide a GDC token."
                if access == "controlled" and token is None
                else ""
            )
            for entry in entries:
                _validate_gdc_id(entry.file_id)
                entry.extra.update(
                    {
                        "asset_kind": "file",
                        "download_method": "gdc-client",
                        "access": access,
                        "payload_profile": "raw_mixed",
                        "preflight_error": preflight_error,
                    }
                )
            return entries
        if cfg.input_mode == "bundle":
            return self._resolve_bundle(cfg, token)
        return self._resolve_query(cfg)

    def _resolve_bundle(
        self, cfg: RunConfig, token: TokenFile | None
    ) -> list[FileEntry]:
        if not cfg.manifest or not cfg.metadata or not cfg.provenance:
            raise InputError(
                "GDC bundle mode requires --manifest, --metadata, and --provenance."
            )
        bundle = load_selection_bundle(cfg.manifest, cfg.metadata, cfg.provenance)
        if bundle.provenance.mode != "build":
            raise InputError(
                "The supplied selection bundle is a preview and cannot be downloaded; "
                "rerun the selector in build mode."
            )
        if bundle.source != self.name:
            raise InputError(
                f"GDC downloader requires a source 'gdc' bundle, found '{bundle.source}'."
            )
        invalid_methods = sorted(
            {asset.download_method for asset in bundle.assets if asset.download_method != "gdc-client"}
        )
        if invalid_methods:
            raise InputError(
                "GDC bundle assets must use download_method 'gdc-client'; found: "
                + ", ".join(invalid_methods)
            )
        unsupported_checksums = sorted(
            {
                asset.source_checksum_type
                for asset in bundle.assets
                if asset.source_checksum_type not in {"", "md5", "sha256"}
            }
        )
        if unsupported_checksums:
            raise InputError(
                "GDC bundle checksum types must be md5 or sha256; found: "
                + ", ".join(unsupported_checksums)
            )
        invalid_kinds = sorted({asset.asset_kind for asset in bundle.assets if asset.asset_kind != "file"})
        if invalid_kinds:
            raise InputError(
                "GDC bundle assets must use asset_kind 'file'; found: "
                + ", ".join(invalid_kinds)
            )
        profile = bundle.assets[0].payload_profile
        supported_profiles = {*_GDC_PROFILE_EXTENSIONS, "single_data", "raw_mixed"}
        if profile not in supported_profiles:
            raise InputError(
                f"Unsupported GDC payload_profile '{profile}'. Expected one of: "
                + ", ".join(sorted(supported_profiles))
            )
        for asset in bundle.assets:
            ext = asset.galaxy_ext_hint
            if not ext or not _SAFE_GALAXY_EXT.fullmatch(ext):
                raise InputError(
                    f"GDC asset '{asset.asset_id}' requires a safe galaxy_ext_hint."
                )
            allowed_exts = _GDC_PROFILE_EXTENSIONS.get(profile)
            if allowed_exts is not None and ext not in allowed_exts:
                raise InputError(
                    f"GDC payload_profile '{profile}' is incompatible with "
                    f"galaxy_ext_hint '{ext}' for asset '{asset.asset_id}'."
                )
            source_format = asset.file_format.strip().lower()
            allowed_formats = _GDC_PROFILE_FORMATS.get(profile)
            if allowed_formats is not None and source_format not in allowed_formats:
                raise InputError(
                    f"GDC payload_profile '{profile}' is incompatible with file_format "
                    f"'{asset.file_format}' for asset '{asset.asset_id}'."
                )
        if cfg.assign_ext:
            allowed_exts = _GDC_PROFILE_EXTENSIONS.get(profile)
            if profile == "raw_mixed" or (
                allowed_exts is not None and cfg.assign_ext not in allowed_exts
            ):
                raise InputError(
                    f"--assign-ext '{cfg.assign_ext}' is incompatible with GDC "
                    f"payload_profile '{profile}'."
                )
        allow_raw_mixed = str(cfg.options.get("allow_raw_mixed", "")).strip().lower()
        if profile == "raw_mixed" and allow_raw_mixed not in {"1", "true", "yes"}:
            raise InputError(
                "This GDC bundle has payload_profile 'raw_mixed'. Refine the selector to one "
                "file format/profile, or explicitly pass --set allow_raw_mixed=true to import "
                "a heterogeneous raw collection."
            )
        entries: list[FileEntry] = []
        for asset in bundle.assets:
            _validate_gdc_id(asset.asset_id)
            preflight_error = (
                "This GDC asset is controlled-access; provide a GDC token."
                if asset.access == "controlled" and token is None
                else ""
            )
            entries.append(
                FileEntry(
                    file_id=asset.asset_id,
                    filename=asset.asset_name,
                    size=asset.source_size,
                    md5=(
                        asset.source_checksum
                        if asset.source_checksum_type == "md5"
                        else None
                    ),
                    source=self.name,
                    extra={
                        "selection_asset": asset,
                        "selection_metadata": bundle.metadata_for(asset.source, asset.asset_id),
                        "selection_manifest_sha256": bundle.asset_manifest_sha256,
                        "selection_metadata_sha256": bundle.metadata_sha256,
                        "selection_provenance": bundle.provenance.values,
                        "asset_kind": asset.asset_kind,
                        "download_method": asset.download_method,
                        "access": asset.access,
                        "source_checksum_type": asset.source_checksum_type,
                        "source_checksum": asset.source_checksum,
                        "payload_profile": asset.payload_profile,
                        "galaxy_ext_hint": asset.galaxy_ext_hint,
                        "dbkey": asset.dbkey,
                        "preflight_error": preflight_error,
                    },
                )
            )
        return entries

    def _resolve_query(self, cfg: RunConfig) -> list[FileEntry]:
        if not cfg.query_json:
            raise InputError("GDC query mode requires --query-json.")
        query = load_query(cfg.query_json)
        filters = query.get("filters")
        if not filters:
            raise InputError("GDC query JSON must contain a 'filters' object.")
        fields = query.get("fields", _QUERY_FIELDS)
        # A user-supplied "size" only sets the page size; the loop below pages
        # through *every* matching file so nothing is silently capped. Sort by a
        # stable key so paging is consistent across requests.
        page_size = int(query.get("size", _PAGE_SIZE)) or _PAGE_SIZE

        entries: list[FileEntry] = []
        start, total = 0, None
        while True:
            payload = {
                "filters": filters,
                "fields": fields,
                "format": "JSON",
                "sort": "file_id:asc",
                "size": page_size,
                "from": start,
            }
            endpoint = str(cfg.options.get("gdc_files_endpoint") or API_FILES_ENDPOINT)
            resp = self.session.post(endpoint, json=payload, timeout=60)
            if resp.status_code >= 400:
                raise DownloadError(f"GDC API returned HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json().get("data", {})
            hits = data.get("hits", [])
            entries.extend(
                FileEntry(
                    file_id=h["file_id"],
                    filename=h.get("file_name") or h["file_id"],
                    md5=h.get("md5sum"),
                    size=int(h["file_size"]) if str(h.get("file_size", "")).isdigit() else None,
                    source=self.name,
                )
                for h in hits
                if h.get("file_id")
            )
            if total is None:
                try:
                    total = int(data.get("pagination", {}).get("total", len(entries)))
                except (TypeError, ValueError):
                    total = len(entries)
            start += len(hits)
            # Stop when the server returns no more rows, or we've covered the total.
            if not hits or start >= total:
                break

        if not entries:
            raise InputError("GDC query matched no files.")
        log.info("GDC query matched %d file(s).", len(entries))
        return entries

    def download(
        self,
        entry: FileEntry,
        dest_dir: str,
        cfg: RunConfig,
        token: TokenFile | None,
    ) -> DownloadResult:
        _validate_gdc_id(entry.file_id)
        if cfg.assign_ext and not _SAFE_GALAXY_EXT.fullmatch(cfg.assign_ext):
            raise InputError(
                f"Unsafe Galaxy datatype extension '{cfg.assign_ext}'."
            )
        destination = Path(dest_dir).resolve()
        subdir = (destination / entry.file_id).resolve()
        try:
            subdir.relative_to(destination)
        except ValueError as exc:  # defense in depth if validation changes later
            raise InputError(
                f"Refusing to use GDC output path outside the destination: {subdir}"
            ) from exc

        gdc = require("gdc-client")
        cmd = [gdc, "download", entry.file_id, "-d", dest_dir]
        if token is not None:
            cmd += ["-t", str(token)]
        try:
            run(cmd, secret_flags=("-t",))
        except subprocess.CalledProcessError as exc:
            raise DownloadError(
                f"gdc-client failed for {entry.file_id}: {(exc.stderr or '').strip()[:300]}"
            ) from exc

        # Re-resolve after the external client returns so a newly created symlink
        # cannot redirect iteration or cleanup outside the destination.
        subdir = (destination / entry.file_id).resolve()
        try:
            subdir.relative_to(destination)
        except ValueError as exc:
            raise DownloadError(
                "gdc-client created an output path outside the requested destination."
            ) from exc

        # gdc-client writes files into <dest_dir>/<file_id>/; flatten them into
        # the directory referenced by Galaxy's tool-provided collection metadata.
        produced: list[str] = []
        total = 0
        if subdir.is_dir():
            files = [
                item
                for item in sorted(subdir.iterdir())
                if item.is_file() and item.name != "logs"
            ]
            if cfg.input_mode == "bundle" and (
                len(files) != 1 or files[0].name != entry.filename
            ):
                names = ", ".join(item.name for item in files) or "(none)"
                shutil.rmtree(subdir, ignore_errors=True)
                raise DownloadError(
                    f"gdc-client output did not match canonical asset '{entry.filename}'; "
                    f"found: {names}."
            )
            for item in files:
                target = unique_path(Path(dest_dir), item.name)
                item.replace(target)
                produced.append(str(target))
                total += target.stat().st_size
            shutil.rmtree(subdir, ignore_errors=True)

        if not produced:
            raise DownloadError(f"gdc-client produced no files for {entry.file_id}.")
        output_records: list[ProducedDataset] = []
        observed_source_checksum = ""
        observed_source_checksum_type = ""
        source_verified: bool | None = None
        for index, path in enumerate(produced, start=1):
            output = Path(path)
            actual_size = output.stat().st_size
            if (
                cfg.input_mode == "bundle"
                and len(produced) == 1
                and entry.size is not None
                and actual_size != entry.size
            ):
                output.unlink(missing_ok=True)
                raise ChecksumError(
                    f"Size mismatch for {output.name}: expected {entry.size} bytes, "
                    f"got {actual_size}."
                )
            ext_hint = str(
                cfg.assign_ext
                or entry.extra.get("galaxy_ext_hint")
                or output.suffix.lstrip(".")
                or "data"
            )
            element_id = entry.file_id if len(produced) == 1 else f"{entry.file_id}_{index}"
            expected_checksum_type = str(
                entry.extra.get("source_checksum_type") or ("md5" if entry.md5 else "")
            )
            expected_checksum = str(entry.extra.get("source_checksum") or entry.md5 or "")
            produced_sha256 = sha256_file(output)
            if len(produced) == 1 and expected_checksum:
                observed_source_checksum_type = expected_checksum_type
                observed_source_checksum = (
                    md5sum(output)
                    if expected_checksum_type == "md5"
                    else produced_sha256
                )
                source_verified = (
                    observed_source_checksum.lower() == expected_checksum.lower()
                )
                if not source_verified:
                    output.unlink(missing_ok=True)
                    raise ChecksumError(
                        f"Checksum mismatch for {output.name}: expected {expected_checksum}, "
                        f"got {observed_source_checksum}"
                    )
            output_records.append(
                ProducedDataset(
                    path=path,
                    element_id=element_id,
                    role="primary" if index == 1 else "auxiliary",
                    galaxy_ext=ext_hint,
                    dbkey=str(entry.extra.get("dbkey") or "?"),
                    bytes=actual_size,
                    checksum_type="sha256",
                    checksum=produced_sha256,
                    verification=(
                        "source_checksum_verified" if source_verified else "calculated"
                    ),
                )
            )
        return DownloadResult(
            entry,
            "ok",
            paths=produced,
            bytes=total,
            md5=entry.md5,
            produced=output_records,
            observed_checksum_type=observed_source_checksum_type,
            observed_checksum=observed_source_checksum,
            checksum_verified=source_verified,
        )
