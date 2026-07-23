# GaCDI — Galaxy Cancer Data Importers

Galaxy Cancer Data Importers (GaCDI) provides Galaxy tools for importing cancer
datasets from major public and controlled-access cancer data repositories into
Galaxy histories. This package provides one command, `mcdi` (Multi-Commons Data
Importer), with two subcommands: `mcdi manifest` builds a manifest from
filters, and `mcdi download` downloads the files a GDC or PDC manifest lists
(whether built here or exported from a portal).

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
mcdi manifest gdc --project TCGA-BRCA --data-type "Slide Image" --count-only \
  --manifest-out m.txt --metadata-out meta.tsv --report-out report.tsv

# Build a slide-image manifest enriched with cBioPortal subtypes + a custom table
mcdi manifest gdc \
  --project TCGA-BRCA --data-type "Slide Image" --access open \
  --cbioportal-study brca_tcga_pan_can_atlas_2018 \
  --cbioportal-attrs SUBTYPE,ER_STATUS_BY_IHC,PR_STATUS_BY_IHC,HER2_STATUS \
  --annotation-tsv histology.tsv --annotation-key-col sample \
  --join-level sample \
  --manifest-out gdc_manifest.txt --metadata-out metadata.tsv --report-out report.tsv

# Discover a study's cBioPortal attribute ids
mcdi manifest gdc --cbioportal-study brca_tcga_pan_can_atlas_2018 \
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

## Downloading files from a manifest

`mcdi download` fetches the files listed in a GDC or PDC manifest — either
one built by `mcdi manifest gdc` above, or one exported directly from a
portal:

- **GDC**: build a file cart in the [GDC portal](https://portal.gdc.cancer.gov)
  and download the manifest (TSV), or generate one via the API:
  `GET https://api.gdc.cancer.gov/v0/manifest/<uuid1>,<uuid2>,...`
- **PDC**: go to the [PDC portal](https://pdc.cancer.gov) Explore page, filter
  to the files you want, and use "Export File Manifest" (CSV or TSV). Note that
  the signed download links embedded in a PDC manifest expire after 7 days —
  re-export if downloads start failing.

```bash
mcdi download --manifest gdc_manifest.txt --output-dir downloads/
mcdi download --manifest pdc_manifest.csv --output-dir downloads/ --verify-checksum
```

The data commons is auto-detected from the manifest's header row; pass
`--source {gdc,pdc}` to override.

| Flag | Description |
|---|---|
| `--manifest PATH` | Path to the manifest (required) |
| `--output-dir DIR` | Directory to download files into (required) |
| `--source {gdc,pdc}` | Skip auto-detection |
| `--workers N` | Concurrent downloads (default: 4). PDC always runs at 1 to respect its rate limit, regardless of this flag. |
| `--verify-checksum` | Verify each file's md5 against the manifest after download |
| `--token-file PATH` | File containing a GDC auth token, for controlled-access files |

Controlled-access GDC files need an auth token, obtained by logging into the
GDC portal and downloading your token. Provide it either via the `GDC_TOKEN`
environment variable or `--token-file`:

```bash
export GDC_TOKEN="$(cat gdc-user-token.txt)"
mcdi download --manifest gdc_manifest.txt --output-dir downloads/
```

PDC downloads use pre-signed URLs embedded in the manifest and need no token.

Output layout:

- **GDC**: `downloads/gdc/<file_id>/<filename>`
- **PDC**: `downloads/pdc/<study_id>/<study_version>/<data_category>/[<run_metadata_id>/]<file_type>/<filename>`

Re-running against the same manifest and output directory skips files already
downloaded (verifying checksums too, if `--verify-checksum` is set), so
interrupted runs can simply be re-run.

## Runtime environment

The tool ships a pinned container (`quay.io/<org>/mcdi`) referenced from
the wrapper, with Python + `requests` Conda requirements as a fallback. The Quay
namespace (`paulocilasjr`) is a placeholder — update `@QUAY_ORG@` in
`tools/manifest_gdc/macros.xml`, `containers/Dockerfile.manifest`, and the workflow
before publishing.

```bash
docker build -f containers/Dockerfile.manifest -t mcdi:dev .
docker run --rm mcdi:dev mcdi manifest gdc --help
```

## Development

```bash
python -m pip install -e '.[dev]'
pytest -q                            # mocked; no network
planemo lint tools/manifest_gdc
```

## Roadmap

- **Phase 1 (this branch):** GDC manifest builder + enrichment + join/QC.
- **Phase 2:** CRDC GDC-style commons (PDC/IDC/ICDC/CDS/CTDC) reusing the filter/
  join core.
- **Phase 3:** GEO/SRA accession-list builders; on merge with the importer branch,
  fold shared HTTP utilities into the `gacdi` package.

## License

See [LICENSE](LICENSE).
