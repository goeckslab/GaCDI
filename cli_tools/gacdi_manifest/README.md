# GaCDI — Galaxy Cancer Data Importers

Galaxy Cancer Data Importers (GaCDI) provides Galaxy tools for importing cancer
datasets from major public and controlled-access cancer data repositories into
Galaxy histories.

## Manifest Builder (this branch)

`gacdi_manifest_gdc` generates the **manifests** that drive the importers. Instead
of downloading a whole dataset, the user filters the NCI
[Genomic Data Commons](https://gdc.cancer.gov/) and gets exactly the files they
want, described in two complementary outputs:

- **GDC manifest** — strict `id / filename / md5 / size / state`, consumable
  directly by `gdc-client` and by the GaCDI GDC importer.
- **metadata table** — the same files joined to sample barcodes and, optionally,
  clinical/molecular annotations (GDC fields, cBioPortal subtypes like PAM50 and
  ER/PR/HER2, and/or a user-uploaded annotation TSV). It also carries
  workflow-routing columns (`data_format`, `data_type`, `experimental_strategy`,
  `workflow_type`, `platform`, `primary_site`, `disease_type`) and a **`galaxy_ext`**
  column giving each file's best-effort Galaxy datatype (`bam`, `vcf`, `svs`,
  `tabular`, …) so downstream analysis tools know how to interpret it.
- **report** — match/precision QC (counts, unmatched files, unused annotations,
  key collisions); also the target of *preview counts only* mode.

**Why two files?** `gdc-client` rejects a manifest carrying extra clinical columns
or missing `state`. The lean manifest is kept separate from the rich research
table, which is joined back to the downloaded files by barcode afterwards.

### Command-line usage

```bash
# Preview how many files match before building
gacdi-manifest gdc --project TCGA-BRCA --data-type "Slide Image" --count-only \
  --manifest-out m.txt --metadata-out meta.tsv --report-out report.tsv

# Build a slide-image manifest enriched with cBioPortal subtypes + a custom table
gacdi-manifest gdc \
  --project TCGA-BRCA --data-type "Slide Image" --access open \
  --cbioportal-study brca_tcga_pan_can_atlas_2018 \
  --cbioportal-attrs SUBTYPE,ER_STATUS_BY_IHC,PR_STATUS_BY_IHC,HER2_STATUS \
  --annotation-tsv histology.tsv --annotation-key-col sample \
  --join-level sample \
  --manifest-out gdc_manifest.txt --metadata-out metadata.tsv --report-out report.tsv

# Discover a study's cBioPortal attribute ids
gacdi-manifest gdc --cbioportal-study brca_tcga_pan_can_atlas_2018 \
  --cbioportal-list-attrs --manifest-out m.txt --metadata-out meta.tsv --report-out report.tsv
```

Filters combine three sources (AND): guided facets (`--project`, `--primary-site`,
`--disease-type`, `--data-category`, `--data-type`, `--experimental-strategy`,
`--workflow-type`, `--platform`, `--data-format`, `--access`, `--sample-type`),
repeatable custom facets (`--extra-filter "field=…;op=in|exclude;values=a,b"`), and
a raw GDC filters JSON (`--raw-filters`). The manifest is emitted in a deterministic
(sorted) order for reproducible workflows.

## Data Commons Downloader

The same package provides `gacdi-download`, the runtime behind the Galaxy **GaCDI
Data Commons Downloader**. It accepts either a GDC TSV manifest or a PDC file
manifest in CSV/TSV form and detects the source from the first non-blank header.

```bash
gacdi-download --manifest portal_manifest.tsv --outdir downloads
```

Detection is intentionally strict:

- GDC requires `id`, `filename`, `md5`, and `size` (the portal also emits `state`).
- PDC is recognized from multiple PDC-specific file-manifest columns such as
  `File ID`, `File Name`, `PDC Study ID`, `Md5sum`, and `File Download Link`.
- A header that matches both or neither format is rejected, and the error lists
  the columns that were actually observed.

For GDC, the command invokes `gdc-client`. If `GDC_AUTH_TOKEN` is non-empty it is
passed through a mode-0600 FIFO, so the token is never written to a regular file
or exposed in process arguments. For PDC, files are streamed from each `File
Download Link` and checked against `File Size (in bytes)` and `Md5sum`. Existing
files with the expected MD5 are skipped. Partial or corrupt downloads are removed.

PDC download links expire after seven days, and PDC limits repeated downloads of
one file from an IP address to 10 attempts per 24 hours. The downloader reports
both conditions with actionable messages. Re-export an expired file manifest from
PDC **Explore → Files → Export File Manifest**.

Expected command exit codes are stable for Galaxy and workflow callers:

| Code | Meaning |
| ---: | --- |
| 0 | Success (including a valid header-only manifest) |
| 1 | Other expected manifest-package failure |
| 2 | Invalid, unknown, or ambiguous input manifest |
| 4 | Remote API failure while building a manifest |
| 5 | GDC/PDC transfer or integrity-check failure |

### End-to-end with the GaCDI downloader

This tool is designed to feed directly into the **GaCDI Data Commons Downloader**,
so a single Galaxy workflow goes *filter → manifest → download → analysis*:

```
[GaCDI Manifest Builder]--gdc_manifest.txt-->[GaCDI Data Commons Downloader]--collection-->[analysis tools]
                        \--metadata.tsv------------------------------(join)----/
```

**Compatibility contract (locked by `tests/test_importer_contract.py`):**

1. **Manifest → downloader.** `gdc_manifest.txt` is a TSV whose header
   (`id, filename, md5, size, state`) satisfies the downloader's detection rule;
   its datatype (`txt`) is accepted by the manifest input (`txt,tabular,csv`). Rows with no
   `id` are dropped so the manifest and metadata stay row-aligned. The same file
   also works with `gdc-client download -m gdc_manifest.txt`.
2. **Metadata ↔ history.** `metadata.tsv` leads with `file_id` and `filename` —
   the exact keys of the importer's history **summary** — so after download you
   join the metadata to the imported collection/summary on `file_id` (stable
   UUID) or `filename` to attach clinical labels, the `galaxy_ext` datatype hint,
   and subtype annotations to each sample in the history.

So: build the manifest here, run the importer to bring the samples into the
history, then join `metadata.tsv` to give those history datasets their
annotations (e.g. labels for an image ML model).

## Runtime environment

The manifest builder and downloader ship pinned containers in the `goeckslab`
Quay namespace. The downloader image combines the Python package with the pinned
GDC Data Transfer Tool 2.3 binary.

```bash
docker build -f cli_tools/gacdi_manifest/Dockerfile -t gacdi-manifest:dev cli_tools/gacdi_manifest
docker run --rm gacdi-manifest:dev gacdi-manifest gdc --help
docker build -f tools/gacdi-downloader/dependencies/Dockerfile -t gacdi-downloader:dev .
docker run --rm gacdi-downloader:dev gacdi-download --help
```

## Development

```bash
python -m pip install -e 'cli_tools/gacdi_manifest[dev]'
pytest -q                            # mocked; no network
planemo lint tools/manifest_gdc tools/gacdi-downloader
```

## Roadmap

- **Phase 1:** GDC manifest builder + enrichment + join/QC.
- **Phase 2 (current):** Unified GDC/PDC manifest downloader.
- **Phase 3:** Additional CRDC commons (IDC/ICDC/CDS/CTDC) reusing the filter/join core.
- **Phase 4:** GEO/SRA accession-list builders; on merge with the importer branch,
  fold shared HTTP utilities into the `gacdi` package.

## License

See [LICENSE](LICENSE).
