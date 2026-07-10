"""Core data structures + barcode extraction from GDC TSV rows."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# GDC TSV flattens nested fields as e.g. "cases.0.submitter_id",
# "cases.0.samples.0.submitter_id", "cases.0.samples.0.sample_type".
_CASE_BARCODE = re.compile(r"^cases\.\d+\.submitter_id$")
_SAMPLE_BARCODE = re.compile(r"^cases\.\d+\.samples\.\d+\.submitter_id$")
_SAMPLE_TYPE = re.compile(r"^cases\.\d+\.samples\.\d+\.sample_type$")
_PROJECT = re.compile(r"^cases\.\d+\.project\.project_id$")
_PRIMARY_SITE = re.compile(r"^cases\.\d+\.primary_site$")
_DISEASE_TYPE = re.compile(r"^cases\.\d+\.disease_type$")
# GDC-native UUIDs: stable join keys that don't depend on TCGA barcode structure.
_CASE_ID = re.compile(r"^cases\.\d+\.case_id$")
_SAMPLE_ID = re.compile(r"^cases\.\d+\.samples\.\d+\.sample_id$")


def _first_match(row: dict, pattern: re.Pattern) -> str | None:
    for key in sorted(row):
        if pattern.match(key) and str(row[key]).strip():
            return str(row[key]).strip()
    return None


def field_value(row: dict, name: str) -> str | None:
    """Return a flat (file-level) field value, e.g. ``data_format`` or ``platform``."""
    value = row.get(name)
    return str(value).strip() if value not in (None, "") else None


def case_barcode(row: dict) -> str | None:
    return _first_match(row, _CASE_BARCODE) or row.get("cases.submitter_id") or None


def sample_barcode(row: dict) -> str | None:
    return _first_match(row, _SAMPLE_BARCODE) or row.get("cases.samples.submitter_id") or None


def sample_type(row: dict) -> str | None:
    return _first_match(row, _SAMPLE_TYPE) or row.get("cases.samples.sample_type") or None


def project_id(row: dict) -> str | None:
    return _first_match(row, _PROJECT) or row.get("cases.project.project_id") or None


def primary_site(row: dict) -> str | None:
    return _first_match(row, _PRIMARY_SITE) or row.get("cases.primary_site") or None


def disease_type(row: dict) -> str | None:
    return _first_match(row, _DISEASE_TYPE) or row.get("cases.disease_type") or None


def case_id(row: dict) -> str | None:
    return _first_match(row, _CASE_ID) or row.get("cases.case_id") or None


def sample_id(row: dict) -> str | None:
    return _first_match(row, _SAMPLE_ID) or row.get("cases.samples.sample_id") or None


# Best-effort mapping of a downloaded file to a Galaxy datatype extension, so the
# manifest/metadata can tell downstream workflow tools how to interpret each file.
# Filename suffix wins (most reliable); GDC data_format is the fallback.
_EXT_BY_SUFFIX = [
    (".bam", "bam"),
    (".bai", "bai"),
    (".cram", "cram"),
    (".vcf.gz", "vcf_bgzip"),
    (".vcf", "vcf"),
    (".maf.gz", "tabular"),
    (".maf", "tabular"),
    (".seg", "tabular"),
    (".gct", "tabular"),
    (".tsv", "tabular"),
    (".csv", "csv"),
    (".txt", "txt"),
    (".bedpe", "bedpe"),
    (".bed", "bed"),
    (".gtf", "gtf"),
    (".gff3", "gff3"),
    (".fastq.gz", "fastqsanger.gz"),
    (".fastq", "fastqsanger"),
    (".fq.gz", "fastqsanger.gz"),
    (".bw", "bigwig"),
    (".bigwig", "bigwig"),
    (".svs", "svs"),
    (".tiff", "tiff"),
    (".tif", "tiff"),
    (".idat", "idat"),
    (".json", "json"),
    (".xml", "xml"),
    (".gz", "data"),
]
_EXT_BY_FORMAT = {
    "BAM": "bam",
    "BAI": "bai",
    "CRAM": "cram",
    "VCF": "vcf",
    "MAF": "tabular",
    "TXT": "txt",
    "TSV": "tabular",
    "CSV": "csv",
    "SEG": "tabular",
    "BEDPE": "bedpe",
    "BED": "bed",
    "GTF": "gtf",
    "GFF3": "gff3",
    "FASTQ": "fastqsanger",
    "SVS": "svs",
    "TIFF": "tiff",
    "IDAT": "idat",
    "BCR XML": "xml",
    "BCR SSF XML": "xml",
    "JSON": "json",
}


def galaxy_ext(filename: str | None, data_format: str | None = None) -> str:
    """Return a best-effort Galaxy datatype extension for a file.

    Defaults to ``data`` (Galaxy's generic type) when nothing matches.
    """
    name = (filename or "").lower()
    for suffix, ext in _EXT_BY_SUFFIX:
        if name.endswith(suffix):
            return ext
    if data_format:
        ext = _EXT_BY_FORMAT.get(data_format.strip().upper())
        if ext:
            return ext
    return "data"


# ---------------------------------------------------------------------------
# Cross-source output contracts (frozen in T0.1; see docs/CONTRACTS.md).
#
# Manifests use PER-SOURCE DIALECTS over a shared semantic SUPERSET: each source
# populates the subset of superset fields it has, under columns suited to its
# downloader. GDC keeps its strict, lean gdc-client/importer-compatible dialect;
# richer sources (DRS/FTP/GCS/…) add locator + access columns directly.
# ---------------------------------------------------------------------------

# Semantic superset a manifest row may carry (documentation + validation target).
MANIFEST_SUPERSET: tuple[str, ...] = (
    "source",           # short source id, e.g. "gdc", "idc"
    "file_id",          # source-native file identifier
    "filename",
    "drs_uri",          # GA4GH DRS URI when available (CRDC nodes)
    "access_url",       # fallback locator: ftp/gcs/accession/synapse/nbia ref
    "download_method",  # see DOWNLOAD_METHODS
    "checksum",
    "checksum_type",    # md5|sha256|etag|""
    "size",             # bytes
    "file_format",
    "access",           # open|controlled (load-bearing for the downloader)
    "case_id",          # link key to metadata
    "sample_id",        # link key to metadata (may be empty)
)

DOWNLOAD_METHODS = frozenset(
    {"drs", "https", "ftp", "gcs", "sra-toolkit", "synapse", "nbia"}
)
ACCESS_VALUES = frozenset({"open", "controlled"})

# Per-source physical manifest column order (the "dialect"). GDC stays lean and
# byte-identical to preserve the gdc-client / GaCDI-importer contract locked in
# tests/test_importer_contract.py. New sources register their own dialect here.
MANIFEST_DIALECTS: dict[str, list[str]] = {
    "gdc": ["id", "filename", "md5", "size", "state"],
}

# Harmonized metadata core: best-effort populated for EVERY source. Native source
# fields are preserved alongside as `<source>__<field>` columns (native_column).
HARMONIZED_CORE_COLUMNS: list[str] = [
    "source", "case_id", "sample_id", "file_id",
    "project", "primary_site", "disease_type", "sample_type",
    "gender", "race", "ethnicity", "vital_status",
    "age_at_diagnosis", "primary_diagnosis", "stage", "grade",
]


def native_column(source: str, field_name: str) -> str:
    """Column name for a source-native passthrough field, e.g. ``gdc__platform``."""
    return f"{source}__{field_name}"


@dataclass
class ManifestRow:
    """A downloadable file in source-agnostic (superset) terms.

    Importers build these; the writer projects them onto the source's manifest
    dialect (:data:`MANIFEST_DIALECTS`). Only ``source``/``file_id``/``filename``
    are always required; the rest are populated when the source provides them.
    """

    source: str
    file_id: str
    filename: str
    download_method: str = ""
    drs_uri: str = ""
    access_url: str = ""
    checksum: str = ""
    checksum_type: str = ""
    size: str = ""
    file_format: str = ""
    access: str = ""
    case_id: str = ""
    sample_id: str = ""


@dataclass
class MetadataRecord:
    """One (file x sample) metadata record: harmonized core + native passthrough."""

    source: str
    file_id: str
    case_id: str = ""
    sample_id: str = ""
    core: dict = field(default_factory=dict)    # subset of HARMONIZED_CORE_COLUMNS
    native: dict = field(default_factory=dict)  # raw source fields (unprefixed)

    def as_row(self) -> dict:
        """Flatten to an output row: identity + core + prefixed native columns."""
        row: dict = {
            "source": self.source,
            "file_id": self.file_id,
            "case_id": self.case_id,
            "sample_id": self.sample_id,
        }
        row.update(self.core)
        for name, value in self.native.items():
            row[native_column(self.source, name)] = value
        return row


@dataclass
class FileRow:
    """One GDC file plus the raw metadata row it came from."""

    file_id: str
    filename: str
    md5: str
    size: str
    state: str
    meta: dict = field(default_factory=dict)

    @property
    def case_barcode(self) -> str | None:
        return case_barcode(self.meta)

    @property
    def sample_barcode(self) -> str | None:
        return sample_barcode(self.meta)

    @property
    def case_id(self) -> str | None:
        return case_id(self.meta)

    @property
    def sample_id(self) -> str | None:
        return sample_id(self.meta)

    @property
    def data_format(self) -> str | None:
        return field_value(self.meta, "data_format")

    @property
    def galaxy_ext(self) -> str:
        return galaxy_ext(self.filename, self.data_format)
