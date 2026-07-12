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

### End-to-end with the GaCDI GDC importer

This tool is designed to feed directly into the **GaCDI GDC importer** (the
manifest-download branch), so a single Galaxy workflow goes *filter → manifest →
download → analysis*:

```
[GaCDI Manifest Builder]--gdc_manifest.txt-->[GaCDI GDC importer]--collection-->[analysis tools]
                        \--metadata.tsv------------------------------(join)----/
```

**Compatibility contract (locked by `tests/test_importer_contract.py`):**

1. **Manifest → importer.** `gdc_manifest.txt` is a TSV whose header
   (`id, filename, md5, size, state`) is a superset of what the importer's
   `parse_gdc_manifest` requires (`id/filename/md5/size`); its datatype (`txt`)
   is accepted by the importer's manifest input (`tabular,txt`). Rows with no
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

The tool ships a pinned container (`quay.io/<org>/gacdi-manifest`) referenced from
the wrapper, with Python + `requests` Conda requirements as a fallback. The Quay
namespace (`paulocilasjr`) is a placeholder — update `@QUAY_ORG@` in
`tools/manifest_gdc/macros.xml`, `containers/Dockerfile.manifest`, and the workflow
before publishing.

```bash
docker build -f containers/Dockerfile.manifest -t gacdi-manifest:dev .
docker run --rm gacdi-manifest:dev gacdi-manifest gdc --help
```

## Development

```bash
# The builder depends on the sibling `gacdi` package (shared HTTP session, GDC
# manifest parser, history summary contract). In this monorepo install it editable
# first, from the repo root:
python -m pip install -e .                       # installs gacdi (repo root)
python -m pip install -e 'cli_tools/gacdi_manifest[dev]'
pytest -q                            # mocked; no network
planemo lint tools/manifest_gdc
```

## Roadmap

- **Phase 1 (done):** GDC manifest builder + enrichment + join/QC, behind a pluggable
  `BuildImporter` interface + registry (`gacdi-manifest <database> …`).
- **Phase 2 (in progress):** CRDC GDC-style commons reusing the filter/join core.
  **PDC** shipped — `gacdi-manifest pdc` emits a GA4GH **DRS** manifest
  (`drs://dg.4DFC:<id>`, `download_method=drs`) plus harmonized + `pdc__` passthrough
  metadata; Galaxy tool `gacdi_manifest_pdc`. **IDC** shipped — `gacdi-manifest idc`
  emits a **GCS** manifest (one row per DICOM series, `download_method=gcs`,
  `gs://idc-open-data/<series>/`); Galaxy tool `gacdi_manifest_idc`. ICDC/CDS/CTDC to
  follow (CDS spike deferred — host not reachable at time of writing).
- **Phase 3:** GEO/SRA accession-list builders; on merge with the importer branch,
  fold shared HTTP utilities into the `gacdi` package.

## Sources

| Source | Subcommand | Manifest | Status |
|---|---|---|---|
| GDC (Genomic Data Commons) | `gdc` | strict `id/filename/md5/size/state` | shipped |
| PDC (Proteomic Data Commons) | `pdc` | §4.1 DRS (`drs://dg.4DFC:<id>`) | shipped |
| IDC (Imaging Data Commons) | `idc` | §4.1 GCS (series, `gs://idc-open-data/<id>/`) | shipped |

## License

See [LICENSE](LICENSE).
