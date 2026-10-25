# mcdi — Multi-Commons Data Importer

`mcdi` is a command-line tool for importing cancer datasets from major public
and controlled-access cancer data repositories: the NCI Genomic Data Commons
([GDC](https://portal.gdc.cancer.gov)), Proteomic Data Commons
([PDC](https://pdc.cancer.gov)), and Imaging Data Commons
([IDC](https://portal.imaging.datacommons.cancer.gov)). It has two
subcommands: `mcdi manifest` builds a manifest from filters, and `mcdi
download` downloads the files a GDC, PDC, or IDC manifest lists.

Manifests are usually exported directly from one of those three portals;
`mcdi download` accepts any of their native export formats as-is. `mcdi
manifest gdc` additionally builds a GDC manifest — plus enriched metadata —
straight from filters, as an alternative to the portal UI.

`mcdi` also powers the GaCDI (Galaxy Cancer Data Importers) Galaxy tools
published in this repo (`manifest_gdc`, `manifest_downloader`) — see their
own help text for Galaxy-specific usage.

## Installation

```bash
pip install cli_tools/mcdi
```

Or run the published container directly, without installing anything locally
(the same image also backs the repo's Galaxy tools):

```bash
docker run --rm quay.io/goeckslab/mcdi:<version> mcdi manifest gdc --help
docker run --rm quay.io/goeckslab/mcdi:<version> mcdi download --help
```

## Manifest Builder

`mcdi manifest gdc` builds the **manifests** that drive the downloader.
Instead of downloading a whole dataset, you filter the NCI
[Genomic Data Commons](https://gdc.cancer.gov/) and get exactly the files you
want, described in two complementary outputs:

- **GDC manifest** — strict `id / filename / md5 / size / state`, consumable
  directly by `gdc-client` and by `mcdi download` (the GaCDI Manifest Downloader).
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

### Feeding the manifest into `mcdi download`

The usual flow is *filter → manifest → download → analysis*: build the
manifest here, run `mcdi download` (below) to fetch the files, then join
`metadata.tsv` to the downloaded files to attach clinical labels, the
`galaxy_ext` datatype hint, and subtype annotations to each sample. (This
hand-off is also what powers the paired GaCDI Galaxy tools.)

This works because of a contract between the two tools:

1. **Manifest → downloader.** `gdc_manifest.txt` is a TSV whose header
   (`id, filename, md5, size, state`) is a superset of what `mcdi download`'s
   GDC parsing requires (`id/filename/md5/size`). Rows with no `id` are
   dropped so the manifest and metadata stay row-aligned. The same file also
   works with `gdc-client download -m gdc_manifest.txt`.
2. **Metadata ↔ downloaded files.** `metadata.tsv` leads with `file_id` and
   `filename` — the same identifiers `mcdi download` organizes its output by
   (see "Output layout" below) — so after download you join the metadata on
   `file_id` (stable UUID) or `filename` to attach clinical labels, the
   `galaxy_ext` datatype hint, and subtype annotations to each sample.

## Downloading files from a manifest

`mcdi download` fetches the files listed in a GDC, PDC, or IDC manifest —
either one built by `mcdi manifest gdc` above, or one exported directly from
a portal:

- **GDC**: build a file cart in the [GDC portal](https://portal.gdc.cancer.gov)
  and download the manifest (TSV), or generate one via the API:
  `GET https://api.gdc.cancer.gov/v0/manifest/<uuid1>,<uuid2>,...`
- **PDC**: go to the [PDC portal](https://pdc.cancer.gov) Explore page, filter
  to the files you want, and use "Export File Manifest" (CSV or TSV). Note that
  the signed download links embedded in a PDC manifest expire after 7 days —
  re-export if downloads start failing.
- **IDC**: build a cohort in the [IDC portal](https://portal.imaging.datacommons.cancer.gov)
  and export either manifest format it offers — the **s5cmd manifest** (a
  `.s5cmd` script of `cp s3://...` lines, one per DICOM series) or the
  **CSV/TSV cohort manifest** (a table keyed by `SeriesInstanceUID`). Both are
  auto-detected and accepted. A manifest entry references a whole series (many
  files, not one), so the actual file list is resolved at download time
  against [idc-index](https://github.com/ImagingDataCommons/idc-index)'s
  metadata and the public `idc-open-data` S3 bucket; only AWS-hosted series are
  currently supported. No token is needed — all IDC data is open access.

```bash
mcdi download --manifest gdc_manifest.txt --output-dir downloads/
mcdi download --manifest pdc_manifest.csv --output-dir downloads/ --verify-checksum
mcdi download --manifest idc_manifest.s5cmd --output-dir downloads/
```

The data commons is auto-detected from the manifest's content; pass
`--source {gdc,idc,pdc}` to override.

| Flag | Description |
|---|---|
| `--manifest PATH` | Path to the manifest (required) |
| `--output-dir DIR` | Directory to download files into (required) |
| `--source {gdc,idc,pdc}` | Skip auto-detection |
| `--workers N` | Concurrent downloads (default: 4). PDC always runs at 1 to respect its rate limit, regardless of this flag. |
| `--verify-checksum` | Verify each file's md5 against the manifest after download. No-op for IDC entries: IDC has no reliable per-object checksum (S3's ETag isn't sound for multipart uploads), so `md5` is always unset and verification is silently skipped, same as any manifest entry without one. |
| `-x`, `--extract` | Extract recognized archives (`.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`, `.tar`, `.zip`, `.gz`, `.bz2`, `.xz`) in place after download, keeping only the extracted contents at the manifest's output path. Off by default. |
| `--token-file PATH` | File containing a GDC auth token, for controlled-access files |
| `--retries N` | Extra attempts for files that fail transiently within this run (default: 2) |
| `--retry-backoff SECONDS` | Wait before each retry pass, multiplied by the attempt number (default: 5.0) |
| `--retry-manifest-out PATH` | Where to write the retry manifest on a partial failure (default: `<manifest>.retry<ext>`, next to `--manifest`) |

Some commons files are themselves archives (e.g. a `.tar.gz` bundle of slides).
`--extract` unpacks any recognized archive into the same directory it was
downloaded into, right after downloading it. On success, the archive itself
then moves to a sibling `<output-dir>.mcdi-archives/` directory (mirroring
`--output-dir`'s layout) — it isn't deleted, just relocated out of the way,
so `--output-dir` ends up holding only the extracted contents, not a
redundant copy of the packed archive next to them. Anything that
recursively scans `--output-dir` afterward only ever sees the actual
extracted files. If extraction fails, the
archive is left where it was downloaded instead, so there's still something
to show for it. The archive's presence in `.mcdi-archives/` also doubles as
the idempotency marker, so reruns skip both re-downloading and
re-extracting.

**Pre-flight access check.** Before downloading anything, every file in the
manifest is probed with a cheap ranged request (skipping ones already
correctly present locally, and — for GDC — ones a single bulk lookup already
confirms are open-access). If even one file turns out to be inaccessible
(e.g. a controlled-access file without a valid token), the whole run aborts
before downloading *any* file, naming exactly which one(s) failed and why —
rather than downloading most of a large manifest only to fail on the last
file. This always runs; there's no flag to skip it.

**Retries.** Beyond the transport-level retries already built into every
request, a failed file (connection errors, `429`/`5xx`, or a checksum
mismatch — not permanent-looking failures like `401`/`403`/`404`) gets
`--retries` more whole-batch attempts, waiting `--retry-backoff × attempt`
seconds between passes. This matters most in automated contexts where
nothing else will rerun the command for you on a failure.

**Partial success.** If some files succeed and others still fail after
retries, the run doesn't just fail outright — it also writes a manifest of
just the failed files (`<manifest>.retry<ext>`, or `--retry-manifest-out`'s
path if given) so you can rerun `mcdi download` against only those, instead
of the whole original manifest. The exit code tells you which case you're
in: `0` clean success, `3` partial success (some files missing, but at least
one succeeded), `1` total failure (nothing usable was produced).

Controlled-access GDC files need an auth token, obtained by logging into the
GDC portal and downloading your token. Provide it either via the `GDC_TOKEN`
environment variable or `--token-file`:

```bash
export GDC_TOKEN="$(cat gdc-user-token.txt)"
mcdi download --manifest gdc_manifest.txt --output-dir downloads/
```

PDC downloads use pre-signed URLs embedded in the manifest and need no token.
IDC downloads are open access and also need no token.

Output layout:

- **GDC**: `downloads/gdc/<file_id>/<filename>`
- **PDC**: `downloads/pdc/<study_id>/<study_version>/<data_category>/[<run_metadata_id>/]<file_type>/<filename>`
- **IDC**: `downloads/idc/<collection_id>/<PatientID>/<StudyInstanceUID>/<Modality>_<SeriesInstanceUID>/<filename>`
  (mirrors idc-index's own default download hierarchy)

Re-running against the same manifest and output directory skips files already
downloaded (verifying checksums too, if `--verify-checksum` is set), so
interrupted runs can simply be re-run — the pre-flight check skips them too,
so a rerun over mostly-complete output is cheap, not another full pass.

## Runtime environment

Both Galaxy tools (`manifest_gdc`, `manifest_downloader`) reference the same
pinned container, `quay.io/goeckslab/mcdi:<version>` — there's no Conda
package, so the container is the sole runtime. It's built from
`cli_tools/mcdi/Dockerfile`, tagged from `mcdi/__init__.py`'s `__version__`,
and built/pushed automatically by `.github/workflows/containers.yml` on
merges to `main` that touch `cli_tools/mcdi/**`.

```bash
docker build -t mcdi:dev cli_tools/mcdi
docker run --rm mcdi:dev mcdi manifest gdc --help
docker run --rm mcdi:dev mcdi download --help
```

### Building behind a TLS-inspecting proxy

If HTTPS traffic passes through an institutional or corporate proxy, its
self-signed root CA must be trusted inside the container. Supply the
PEM-encoded CA certificate (or an existing PEM CA bundle) as a BuildKit secret
when building:

```bash
MCDI_CA_CERT=/absolute/path/to/organization-root-ca.crt
docker build \
  --secret id=mcdi_ca_cert,src="$MCDI_CA_CERT" \
  --build-arg MCDI_CA_CERT_SHA256="$(openssl dgst -sha256 -r "$MCDI_CA_CERT" | cut -d ' ' -f 1)" \
  -t quay.io/goeckslab/mcdi:0.5.0 \
  .
```

The Dockerfile installs that CA into Debian's system trust store and configures
both Python's TLS layer and `requests` to use the resulting combined bundle.
The certificate becomes part of the final image, while the secret input stays
out of the build context and no extra copy lands under `/app`. Use the CA
certificate that issued the proxy's certificates (normally the organization's
root CA), not the certificate for `idc-open-data.s3.amazonaws.com` itself. The
SHA-256 build argument safely invalidates Docker's cache when the certificate
changes; the build fails if it does not match the supplied file.

To confirm the resulting image can establish the same connection that IDC
downloads use:

```bash
docker run --rm quay.io/goeckslab/mcdi:0.5.0 \
  python -c 'import requests; r = requests.get("https://idc-open-data.s3.amazonaws.com", timeout=30); print(r.status_code)'
```

Omit `--secret` for ordinary builds that do not require a private CA.

## License

See [LICENSE](LICENSE).

## Contributing

```bash
python -m pip install -e '.[dev]'
pytest -q -m "not network"           # mocked; add `-m network` for live-API tests
planemo lint tools/manifest_gdc tools/manifest_downloader
```
