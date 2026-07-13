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
# GDC-native clinical fields (demographic is one object per case; diagnoses is a
# list). Pulling these means the harmonized clinical columns come from GDC itself,
# with no cBioPortal call required.
# The harmonized column is named `gender`, but GDC's demographic field was renamed
# from `gender` to `sex_at_birth`; source it from the current field name.
_GENDER = re.compile(r"^cases\.\d+\.demographic\.sex_at_birth$")
_RACE = re.compile(r"^cases\.\d+\.demographic\.race$")
_ETHNICITY = re.compile(r"^cases\.\d+\.demographic\.ethnicity$")
_VITAL_STATUS = re.compile(r"^cases\.\d+\.demographic\.vital_status$")
_AGE_AT_DIAGNOSIS = re.compile(r"^cases\.\d+\.diagnoses\.\d+\.age_at_diagnosis$")
_PRIMARY_DIAGNOSIS = re.compile(r"^cases\.\d+\.diagnoses\.\d+\.primary_diagnosis$")
_STAGE = re.compile(r"^cases\.\d+\.diagnoses\.\d+\.ajcc_pathologic_stage$")
_GRADE = re.compile(r"^cases\.\d+\.diagnoses\.\d+\.tumor_grade$")


def _first_match(row: dict, pattern: re.Pattern) -> str | None:
    for key in sorted(row):
        if pattern.match(key) and str(row[key]).strip():
            return str(row[key]).strip()
    return None


def _get(row: dict, key: str) -> str:
    """Return a single flattened value as a stripped string ('' when absent)."""
    value = row.get(key)
    return str(value).strip() if value not in (None, "") else ""


_CASE_INDEX = re.compile(r"^cases\.(\d+)\.")


def _indices(row: dict, pattern: re.Pattern) -> list[int]:
    """Return the sorted distinct capture-group indices matched by *pattern*."""
    seen: set[int] = set()
    for key in row:
        m = pattern.match(key)
        if m:
            seen.add(int(m.group(1)))
    return sorted(seen)


def _case_record(row: dict, prefix: str) -> dict:
    """Case-level clinical fields under *prefix* (e.g. 'cases.0' or 'cases')."""
    return {
        "case_id": _get(row, f"{prefix}.case_id"),
        "case_barcode": _get(row, f"{prefix}.submitter_id"),
        "primary_site": _get(row, f"{prefix}.primary_site"),
        "disease_type": _get(row, f"{prefix}.disease_type"),
        "project": _get(row, f"{prefix}.project.project_id"),
        "gender": _get(row, f"{prefix}.demographic.sex_at_birth"),
        "race": _get(row, f"{prefix}.demographic.race"),
        "ethnicity": _get(row, f"{prefix}.demographic.ethnicity"),
        "vital_status": _get(row, f"{prefix}.demographic.vital_status"),
        "age_at_diagnosis": _get(row, f"{prefix}.diagnoses.0.age_at_diagnosis") or _get(row, f"{prefix}.diagnoses.age_at_diagnosis"),
        "primary_diagnosis": _get(row, f"{prefix}.diagnoses.0.primary_diagnosis") or _get(row, f"{prefix}.diagnoses.primary_diagnosis"),
        "stage": _get(row, f"{prefix}.diagnoses.0.ajcc_pathologic_stage") or _get(row, f"{prefix}.diagnoses.ajcc_pathologic_stage"),
        "grade": _get(row, f"{prefix}.diagnoses.0.tumor_grade") or _get(row, f"{prefix}.diagnoses.tumor_grade"),
    }


def enumerate_samples(row: dict) -> list[dict]:
    """Expand a flattened GDC file row into one record per (case, sample).

    Each record carries that case's clinical fields plus the sample's ids/type, so
    a file derived from several samples produces one metadata row per sample rather
    than silently collapsing to the first. A case with no samples still yields one
    record (empty sample fields), and a row with no indexed case falls back to the
    unprefixed form — so every file always produces at least one record.
    """
    records: list[dict] = []
    for ci in _indices(row, _CASE_INDEX):
        case = _case_record(row, f"cases.{ci}")
        sample_idx = _indices(row, re.compile(rf"^cases\.{ci}\.samples\.(\d+)\."))
        if not sample_idx:
            records.append({**case, "sample_id": "", "sample_barcode": "", "sample_type": ""})
        for sj in sample_idx:
            records.append({
                **case,
                "sample_id": _get(row, f"cases.{ci}.samples.{sj}.sample_id"),
                "sample_barcode": _get(row, f"cases.{ci}.samples.{sj}.submitter_id"),
                "sample_type": _get(row, f"cases.{ci}.samples.{sj}.sample_type"),
            })
    if not records:
        records.append({
            **_case_record(row, "cases"),
            "sample_id": _get(row, "cases.samples.sample_id"),
            "sample_barcode": _get(row, "cases.samples.submitter_id"),
            "sample_type": _get(row, "cases.samples.sample_type"),
        })
    return records


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


def gender(row: dict) -> str | None:
    return _first_match(row, _GENDER) or row.get("cases.demographic.sex_at_birth") or None


def race(row: dict) -> str | None:
    return _first_match(row, _RACE) or row.get("cases.demographic.race") or None


def ethnicity(row: dict) -> str | None:
    return _first_match(row, _ETHNICITY) or row.get("cases.demographic.ethnicity") or None


def vital_status(row: dict) -> str | None:
    return _first_match(row, _VITAL_STATUS) or row.get("cases.demographic.vital_status") or None


def age_at_diagnosis(row: dict) -> str | None:
    return _first_match(row, _AGE_AT_DIAGNOSIS) or row.get("cases.diagnoses.age_at_diagnosis") or None


def primary_diagnosis(row: dict) -> str | None:
    return _first_match(row, _PRIMARY_DIAGNOSIS) or row.get("cases.diagnoses.primary_diagnosis") or None


def stage(row: dict) -> str | None:
    return _first_match(row, _STAGE) or row.get("cases.diagnoses.ajcc_pathologic_stage") or None


def grade(row: dict) -> str | None:
    return _first_match(row, _GRADE) or row.get("cases.diagnoses.tumor_grade") or None


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

DOWNLOAD_METHODS = ("drs", "https", "ftp", "gcs", "sra-toolkit", "synapse", "nbia")
CHECKSUM_TYPES = ("md5", "sha256", "etag", "")
ACCESS_LEVELS = ("open", "controlled")
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


@dataclass
class ManifestRow:
    """The multi-source download-contract row (plan §4.1) — one row per file.

    This is the schema **new** (CRDC/imaging/NCBI) sources emit: DRS-aware, with a
    ``download_method`` + (``drs_uri`` | ``access_url``) pair so a single downstream
    tool can handle every source. GDC intentionally keeps its strict
    ``id/filename/md5/size/state`` manifest for ``gdc-client`` compatibility (see
    :data:`gacdi_manifest.io.MANIFEST_COLUMNS`) rather than this richer schema.
    """

    source: str = ""
    file_id: str = ""
    filename: str = ""
    drs_uri: str = ""
    access_url: str = ""       # fallback locator: FTP/GCS/SRA accession/Synapse id/NBIA ref
    download_method: str = ""  # one of DOWNLOAD_METHODS
    checksum: str = ""
    checksum_type: str = ""    # one of CHECKSUM_TYPES
    size: str = ""             # bytes; may be empty
    file_format: str = ""
    access: str = ""           # open | controlled
    case_id: str = ""          # linking key to metadata
    sample_id: str = ""        # linking key to metadata (may be empty for study-level items)
