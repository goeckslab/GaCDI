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


# Best-effort mapping of a downloaded file to a Galaxy datatype extension, so the
# manifest/metadata can tell downstream workflow tools how to interpret each file.
# Filename suffix wins (most reliable); GDC data_format is the fallback.
_EXT_BY_SUFFIX = [
    (".pep.xml", "pepxml"),
    (".pepxml", "pepxml"),
    (".mzml", "mzml"),
    (".mzid", "mzid"),
    (".mgf", "mgf"),
    (".raw", "thermo.raw"),
    (".fasta", "fasta"),
    (".fa", "fasta"),
    (".wiff", "data"),
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
    def data_format(self) -> str | None:
        return field_value(self.meta, "data_format")

    @property
    def galaxy_ext(self) -> str:
        return galaxy_ext(self.filename, self.data_format)
