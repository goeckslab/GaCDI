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

## Two halves: build a manifest, then import it

GaCDI has two complementary halves that share one design:

1. **Manifest Builder** (`packages/gacdi_manifest_builder/`, CLI `gacdi-manifest`) —
   queries a repository with user-defined filters and emits a lean **download
   manifest** plus a rich **metadata** table (harmonized clinical core +
   source-native passthrough). It does *not* download; the manifest is its contract
   to the importer. See
   [packages/gacdi_manifest_builder/README.md](packages/gacdi_manifest_builder/README.md)
   and the frozen output contracts in
   [packages/gacdi_manifest_builder/docs/CONTRACTS.md](packages/gacdi_manifest_builder/docs/CONTRACTS.md).
2. **Importer / downloader** (`packages/gacdi_downloader/`, CLI `gacdi`) — consumes a manifest (or
   accession/query), streams the files with retries and checksum verification, and
   stages a Galaxy dataset collection + summary.

Pipeline: `gacdi-manifest <source> …` → `manifest.txt` → `gacdi <source> --input-mode
manifest --manifest manifest.txt …` → collection, joined back to `metadata.tsv`.

## Supported repositories

| Tool | Repository | Input modes | Backend |
|------|------------|-------------|---------|
| `gacdi_gdc` | [Genomic Data Commons](https://gdc.cancer.gov/) | manifest, API query | `gdc-client` + REST API |
| `gacdi_geo` | [Gene Expression Omnibus](https://www.ncbi.nlm.nih.gov/geo/) | accession (GSE/GSM) | NCBI FTP |
| `gacdi_sra` | [Sequence Read Archive](https://www.ncbi.nlm.nih.gov/sra) | accession (SRR/ERR/DRR) | `sra-tools` |
| `gacdi_cda` | [Cancer Data Aggregator](https://datacommons.cancer.gov/) | query | `cdapython` (cross-commons search → manifest) |
| `gacdi_xena` | [UCSC Xena](https://xena.ucsc.edu/public/) | accession, query | hub HTTP download |

PDC and IDC currently ship as selector/builder tools. They emit validated canonical
selection bundles, but their DRS and GCS download executors are not implemented yet:

| Tool | Repository | Selection output | Status |
|------|------------|------------------|--------|
| `gacdi_manifest_pdc` | [Proteomic Data Commons](https://proteomic.datacommons.cancer.gov/) | DRS file manifest + canonical selection bundle | selector shipped; downloader pending |
| `gacdi_manifest_idc` | [Imaging Data Commons](https://imaging.datacommons.cancer.gov/) | GCS DICOM-series manifest + canonical selection bundle | selector shipped; downloader pending |

Planned (Phase 2/3): PDC/IDC download executors, ICDC, CDS, CTDC, TCIA, dbGaP,
and SEER — see [the roadmap](#roadmap).

**CDA** is a *search* layer, not a downloader: `gacdi_cda` runs a cross-commons
query and emits a **manifest table** of matching files (owning commons, `file_id`,
size, checksum, DRS URI). Feed that into `gacdi_gdc` (etc.) to fetch the bytes;
files with a direct URL are downloaded automatically.

## Architecture

The monorepo has three independently installable distributions under `packages/`:

```
packages/
  gacdi_core/            shared foundation (gacdi-core): selection-bundle contracts,
                         validators, retrying HTTP session, minimal error root
  gacdi_downloader/      the download engine (dist `gacdi`, import `gacdi`)
    gacdi/base.py        BaseDownloadSource template method (resolve → download → verify → summarize)
    gacdi/registry.py    lazy SourceSpec registry (get_source)
    gacdi/sources/       gdc, geo, sra, cda, xena  (one class per repository)
    gacdi/clients/       injected transport clients/adapters per source
  gacdi_manifest_builder/  the manifest builder (dist `gacdi-manifest`, import `gacdi_manifest`)
    gacdi_manifest/base.py     BaseManifestSource
    gacdi_manifest/registry.py lazy registry
    gacdi_manifest/sources/     gdc, pdc, idc
    gacdi_manifest/clients/     injected transport clients per source
tools/            Galaxy wrappers; macros.xml holds shared XML
containers/       downloader/ and manifest_builder/ Dockerfiles → hosted on Quay
integration_tests/  cross-tool builder → downloader selection-bundle handoff
```

Adding a repository = one source class (compose a client, implement `resolve` +
`download`, or `build_query` + `fetch`) plus a lazy registry entry and a thin XML
wrapper; the workflow loop, retries, checksums, history staging, and summary are
inherited. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design,
compatibility policy, and the per-tool "add a source" cookbooks.

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
docker build -f containers/downloader/Dockerfile.base -t gacdi-base:dev .
docker build -f containers/downloader/Dockerfile.sra  --build-arg BASE_IMAGE=gacdi-base:dev -t gacdi-sra:dev .
docker run --rm gacdi-sra:dev gacdi sra --help
```

CI (`.github/workflows/containers.yml`) builds and pushes the images to
`quay.io/<org>/…` on a version tag. **The Quay namespace (`paulocilasjr`) is a
placeholder — update `@QUAY_ORG@` in `tools/macros.xml`, `containers/downloader/Dockerfile.* and containers/manifest_builder/Dockerfile`,
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
# Install the shared foundation first, then the two tools (editable).
python -m pip install -e packages/gacdi_core
python -m pip install -e 'packages/gacdi_downloader[dev]'
python -m pip install -e 'packages/gacdi_manifest_builder[dev]'

# Per-tool offline suites (run from each package root):
( cd packages/gacdi_downloader && pytest -q -m "not network" )
( cd packages/gacdi_manifest_builder && pytest -q -m "not network" )
# Cross-tool selection-bundle handoff:
pytest -q integration_tests

planemo lint tools/gdc tools/geo tools/sra
```

Unit tests never touch the network or external binaries; network integration
tests are marked `network` (`pytest -m network`).

## Roadmap

- **Phase 1 (this release):** GDC, GEO, SRA.
- **Phase 2:** PDC and IDC selectors are shipped; add their DRS/GCS download
  executors. Add ICDC, CDS, and CTDC using the same canonical bundle pattern.
- **Phase 3:** TCIA (NBIA REST), dbGaP (SRA + ngc), SEER (Data-Use-Agreement,
  documented/limited importer).

## License

See [LICENSE](LICENSE).
