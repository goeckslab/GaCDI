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
  ER/PR/HER2, and/or a user-uploaded annotation TSV).
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

Filters combine three sources (AND): guided facets (`--project`, `--data-category`,
`--data-type`, `--experimental-strategy`, `--data-format`, `--access`,
`--sample-type`), repeatable custom facets
(`--extra-filter "field=…;op=in|exclude;values=a,b"`), and a raw GDC filters JSON
(`--raw-filters`).

### Downstream

Feed `gdc_manifest.txt` to the **GaCDI GDC** importer (or `gdc-client download -m
gdc_manifest.txt`) to fetch the files, then join the results to `metadata.tsv` by
the `sample`/barcode column for analysis (e.g. labels for an image ML model).

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
