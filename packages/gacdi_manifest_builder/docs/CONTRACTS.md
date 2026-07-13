# Output Contracts (frozen — T0.1)

The tool emits **two files per run** (plus an optional provenance sidecar, T0.4).
These are the interface to (a) the downstream **download tool** and (b) Galaxy
workflows. Treat any change here as **breaking**.

Two decisions were made by the maintainer at the T0.1 gate and are baked in below:

1. **Manifest = per-source dialects over a shared semantic superset.**
2. **Metadata passthrough = prefixed native columns** (`<source>__<field>`).

---

## 1. Manifest (download contract) — one row per file

The manifest is what the separate downloader consumes. Different sources are
downloaded by different mechanisms (gdc-client, DRS, FTP, GCS, SRA toolkit,
Synapse, NBIA), so **each source emits its own column *dialect*** — the physical
columns appropriate to its downloader — while every dialect is a projection of one
shared **semantic superset**. The downstream tool dispatches on the source and its
`download_method`.

### 1.1 Semantic superset (`model.MANIFEST_SUPERSET`)

Each source populates the subset it actually has:

| Field | Meaning |
|---|---|
| `source` | short source id (`gdc`, `idc`, `geo`, …) |
| `file_id` | source-native file identifier |
| `filename` | |
| `drs_uri` | GA4GH DRS URI when the source exposes it (CRDC nodes); else empty |
| `access_url` | fallback locator: FTP (GEO), GCS (IDC), SRA accession, Synapse id (HTAN), NBIA ref (TCIA) |
| `download_method` | `drs \| https \| ftp \| gcs \| sra-toolkit \| synapse \| nbia` |
| `checksum` | may be empty if the source provides none |
| `checksum_type` | `md5 \| sha256 \| etag \| ""` |
| `size` | bytes; may be empty |
| `file_format` | |
| `access` | `open \| controlled` — **load-bearing**: tells the downloader when credentials are required |
| `case_id` | link key to metadata |
| `sample_id` | link key to metadata (may be empty for study-level items) |

Enums: `model.DOWNLOAD_METHODS`, `model.ACCESS_VALUES`.

### 1.2 Per-source dialects (`model.MANIFEST_DIALECTS`)

#### GDC dialect (frozen, back-compatible)

```
id    filename    md5    size    state
```

GDC keeps its **strict, lean** dialect unchanged so it stays compatible with both
`gdc-client -m` (which rejects extra columns) and the GaCDI GDC importer's
`parse_gdc_manifest` (locked by `tests/test_importer_contract.py`, which requires
`{id, filename, md5, size}`). Semantic mapping: `id`=`file_id`, `md5`=`checksum`
(`checksum_type=md5`), `state` is GDC-specific.

Because gdc-client forbids extra manifest columns, GDC's `access`,
`download_method`, `case_id`, and `sample_id` are **carried in the metadata file**
(joined by `file_id`), not the manifest. Sources whose downloaders tolerate richer
manifests (DRS/FTP/GCS/…) include locator + `access` + `download_method` columns
directly in their dialect.

> Invariant test: `MANIFEST_DIALECTS["gdc"] == io.MANIFEST_COLUMNS`
> (`tests/test_contracts.py`) keeps the registry and the writer from drifting apart.

New sources register their dialect in `MANIFEST_DIALECTS` when added (§ per the
"adding a source" checklist).

---

## 2. Metadata (analysis enrichment) — harmonized core + native passthrough

One row per **(file × sample)** (T0.7). Not a forced single flat schema:

### 2.1 Harmonized core (`model.HARMONIZED_CORE_COLUMNS`)

Best-effort populated for **every** source:

```
source  case_id  sample_id  file_id  project  primary_site  disease_type
sample_type  gender  race  ethnicity  vital_status  age_at_diagnosis
primary_diagnosis  stage  grade
```

A source emits the subset of these it can populate. (For GDC, the clinical fields
— gender/race/vital_status/age/stage/grade — are filled from GDC's own
demographic + diagnosis fields in T0.9; cBioPortal is demoted to subtype-only
enrichment.)

### 2.2 Source-native passthrough — **prefixed columns**

Every native field the source returns is preserved as an additional column named
**`<source>__<field>`** (helper: `model.native_column(source, field)`), e.g.
`gdc__data_category`, `gdc__analysis__workflow_type`. Nothing the source gives us
is silently dropped. Chosen over a `native_json` blob so a Galaxy step can filter
on native fields directly.

### 2.3 Join key

`source` + `file_id` (and `sample_id` where present). A Galaxy step can filter
metadata **before** handing the manifest to the downloader.

---

## 3. Provenance (T0.4)

Both outputs get a provenance record — `source`, endpoint + API/version, the exact
query, tool version, UTC timestamp — as a header comment and/or `*.provenance.json`
sidecar. The report already stamps `gacdi_manifest_version`; T0.4 extends this to
the manifest and metadata.

---

## 4. Models (`gacdi_manifest/model.py`)

- `ManifestRow` — source-agnostic superset row an importer builds; the writer
  projects it onto the source's dialect.
- `MetadataRecord` — one (file × sample) record: `core` (harmonized subset) +
  `native` (raw source fields, prefixed on write via `.as_row()`).

These are the frozen targets every importer's `to_manifest_rows` /
`to_metadata_records` produces.
