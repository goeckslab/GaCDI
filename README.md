# GaCDI — Galaxy Cancer Data Importers

GaCDI provides Galaxy tools for importing cancer datasets from major public and
controlled-access cancer data repositories into Galaxy histories, ready for
downstream analyses and workflows.

Each supported repository is exposed as:

1. a subcommand of a shared **`gacdi`** Python package (the download engine), and
2. a thin **Galaxy tool** (XML wrapper) that calls it.

Every tool emits the same two outputs: a **dataset collection** of the downloaded
files plus a **summary** table (one row per file: identifier, filename, status,
size, checksum, source).

## Supported repositories

| Tool | Repository | Input modes | Backend |
|------|------------|-------------|---------|
| `gacdi_gdc` | [Genomic Data Commons](https://gdc.cancer.gov/) | manifest, API query | `gdc-client` + REST API |
| `gacdi_geo` | [Gene Expression Omnibus](https://www.ncbi.nlm.nih.gov/geo/) | accession (GSE/GSM) | NCBI FTP |
| `gacdi_sra` | [Sequence Read Archive](https://www.ncbi.nlm.nih.gov/sra) | accession (SRR/ERR/DRR) | `sra-tools` |
| `gacdi_cda` | [Cancer Data Aggregator](https://datacommons.cancer.gov/) | query | `cdapython` (cross-commons search → manifest) |
| `gacdi_xena` | [UCSC Xena](https://xena.ucsc.edu/public/) | accession, query | hub HTTP download |

Planned (Phase 2/3): PDC, IDC, ICDC, CDS, CTDC, TCIA, dbGaP, SEER — see
[the plan](#roadmap).

**CDA** is a *search* layer, not a downloader: `gacdi_cda` runs a cross-commons
query and emits a **manifest table** of matching files (owning commons, `file_id`,
size, checksum, DRS URI). Feed that into `gacdi_gdc` (etc.) to fetch the bytes;
files with a direct URL are downloaded automatically.

## Architecture

```
gacdi/            shared Python package (download engine)
  base.py         BaseImporter template method (resolve → download → verify → summarize)
  net.py          retrying HTTP session, streamed download, checksum verify
  manifest.py     manifest / accession / query parsing
  history.py      Galaxy output staging (collection dir) + summary TSV
  auth.py         controlled-access token handling (0600, never logged)
  importers/      gdc.py, geo.py, sra.py  (one class per repository)
tools/            Galaxy wrappers; macros.xml holds shared XML
containers/       Dockerfiles (base + per-tool) → hosted on Quay
```

Adding a repository = one importer class (implement `resolve` + `download`) plus
one thin XML wrapper; the download loop, retries, checksums, history staging and
summary are inherited.

## Command-line usage

```bash
# GDC — download from a portal manifest (add --token for controlled access)
gacdi gdc --input-mode manifest --manifest manifest.txt \
          --output-dir downloads --summary summary.tsv

# GEO — supplementary files for one or more accessions
gacdi geo --input-mode accession --accessions "GSE12345, GSM67890" \
          --output-dir downloads --summary summary.tsv

# SRA — runs converted to gzip-compressed FASTQ
gacdi sra --input-mode accession --accessions SRR000001 \
          --output-dir downloads --summary summary.tsv

# Xena — download a dataset matrix from a hub
gacdi xena --input-mode accession --accessions "TCGA.BRCA.sampleMap/HiSeqV2" \
           --set hub=https://tcga.xenahubs.net \
           --output-dir downloads --summary summary.tsv

# CDA — cross-commons search → manifest table (+ direct-URL downloads)
gacdi cda --input-mode query --query-json query.json \
          --output-dir downloads --summary summary.tsv

# Preview a selection without downloading
gacdi gdc --input-mode manifest --manifest manifest.txt --dry-run \
          --output-dir downloads --summary summary.tsv
```

Common options: `--max-files`, `--max-bytes`, `--retries`, `--jobs`,
`--dry-run`, `--continue-on-error`, `--token`.

## Runtime environment (containers)

A stock Galaxy does not ship `gdc-client`, `sra-tools`, `entrez-direct`, or the
`gacdi` package. Each tool therefore declares a pinned **container** (primary) and
Conda `<requirements>` (fallback):

- **`gacdi-base`** — Python + the `gacdi` core.
- **`gacdi-gdc` / `gacdi-geo` / `gacdi-sra`** — extend the base with the one
  repository binary.

Build locally:

```bash
docker build -f containers/Dockerfile.base -t gacdi-base:dev .
docker build -f containers/Dockerfile.sra  --build-arg BASE_IMAGE=gacdi-base:dev -t gacdi-sra:dev .
docker run --rm gacdi-sra:dev gacdi sra --help
```

CI (`.github/workflows/containers.yml`) builds and pushes the images to
`quay.io/<org>/…` on a version tag. **The Quay namespace (`paulocilasjr`) is a
placeholder — update `@QUAY_ORG@` in `tools/macros.xml`, `containers/Dockerfile.*`,
and the workflow before publishing.** Galaxy pulls the same image via Docker or
Singularity/Apptainer; the container resolver must be enabled on the Galaxy
instance (otherwise the Conda fallback is used).

## Controlled access

GDC controlled-access files require a download token. Upload the token as a
dataset and select it under *Controlled-access token file*. The token is copied to
a private `0600` temp file for the run and never written to logs. **Both the token
dataset and any downloaded controlled data persist in the Galaxy history and must
be handled in accordance with the repository's Data Use Agreement.**

## Development

```bash
python -m pip install -e '.[dev]'
pytest -q                       # unit tests (mocked; no network)
planemo lint tools/gdc tools/geo tools/sra
```

Unit tests never touch the network or external binaries; network integration
tests are marked `network` (`pytest -m network`).

## Roadmap

- **Phase 1 (this release):** GDC, GEO, SRA.
- **Phase 2:** PDC (GraphQL), IDC (`idc-index`/`s5cmd`), ICDC, CDS, CTDC — all
  reuse the manifest-based importer pattern.
- **Phase 3:** TCIA (NBIA REST), dbGaP (SRA + ngc), SEER (Data-Use-Agreement,
  documented/limited importer).

## License

See [LICENSE](LICENSE).
