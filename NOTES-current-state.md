# NOTES — Current State (T0.0 ground-truth)

> Deliverable for **T0.0** of the implementation plan. Reconciles the plan's §1/§4/§5
> assumptions against the actual repo as of branch `manifest_tool` (commit `be8d7c5`).
> Read this before starting any other task. Where the plan is stale, the correction
> is recorded here (the plan itself lives only in chat, not as a repo file).

Baseline verified: **36 tests pass offline** (`pytest -m "not network"`, 0.07s).

---

## 1. Actual repo layout (what's really here)

```
GaCDI/
├── cli_tools/gacdi_manifest/         ← THE ACTIVE PACKAGE (all real code)
│   ├── pyproject.toml                  hatchling; entry point gacdi-manifest=cli:main
│   ├── Dockerfile                      (duplicate #1 — see §6 note)
│   ├── README.md                       accurate; has a Roadmap (Phase 1/2/3)
│   ├── gacdi_manifest/                 the importable package (11 modules, see §3)
│   └── tests/                          8 test files, requests-mock based (see §4)
├── tools/manifest_gdc/               ← GALAXY WRAPPER (plan didn't mention this path)
│   ├── gacdi_manifest_gdc.xml           full GDC tool: inputs, 3 outputs, 1 planemo test
│   └── macros.xml
├── containers/                       ← PACKAGING (plan didn't mention; partly pre-scaffolded)
│   ├── Dockerfile.manifest              (duplicate #2 — referenced by README)
│   └── env/                             per-source conda envs ALREADY STUBBED:
│       ├── base.yml   (python, requests)
│       ├── gdc.yml    (gdc-client=2.3)
│       ├── cda.yml    (pip: cdapython)
│       ├── geo.yml    (entrez-direct=22.4)
│       └── sra.yml    (sra-tools=3.1.1)
├── .shed.yml                          Toolshed metadata (single tool: gacdi_manifest_gdc)
├── gacdi/          ← EMPTY (only __pycache__) — stale, safe to ignore/remove
├── gacdi_manifest/ ← EMPTY (only __pycache__) — stale, safe to ignore/remove
└── tests/          ← EMPTY (only __pycache__) — stale, safe to ignore/remove
```

**Surprises vs the plan:**
- The Galaxy wrapper already exists at `tools/manifest_gdc/` — plan §7 T0.10 ("Galaxy tool
  skeleton") is partly **already done** for GDC. Treat T0.10 as *conform the existing wrapper
  to the frozen contract*, not build-from-scratch.
- `containers/env/*.yml` already encodes the **optional-deps-per-source** idea from plan §3
  (gdc/cda/geo/sra stubs present; pdc/idc/tcia/htan/cbioportal/ctdc/cdas/psdc not yet). Good
  starting point — reuse, don't reinvent.
- Three empty root dirs (`gacdi/`, `gacdi_manifest/`, `tests/`) are leftover `__pycache__`
  shells. The plan's §5 "reuse `join.py`, `io.py`, ..." refers to the **`cli_tools/...`**
  copies, not these.

---

## 2. Source support — confirmed

| Source | Status | Evidence |
|---|---|---|
| **GDC** | fully implemented | `gdc.py` hits `api.gdc.cancer.gov/files`; wired through `cli.py` |
| **cBioPortal** | enrichment-only helper | `cbioportal.py` + `enrich.py`; joins clinical attrs onto GDC files |
| other 10 | no code | only conda-env stubs for cda/geo/sra exist |

The plan's §1 "current state" is **accurate**. No importer abstraction exists yet.

---

## 3. Module inventory (`cli_tools/gacdi_manifest/gacdi_manifest/`)

| Module | Role | Reusable across sources? |
|---|---|---|
| `cli.py` | argparse; **single hardcoded `gdc` subparser**; `if args.database=="gdc"` dispatch | needs refactor (T0.2/T0.3) |
| `gdc.py` | GDC `/files` client: `count`, `query_files` (paged TSV), `facets` | GDC-specific |
| `filters.py` | `build_filters` — guided + `--extra-filter` + `--raw-filters` → GDC filter JSON | GDC-specific grammar |
| `cbioportal.py` | clinical-attr list + per-sample fetch (SAMPLE+PATIENT merge) | source client |
| `enrich.py` | `collect()` merges cBioPortal + user TSV into `{sample_id: {attr: val}}` | mostly reusable |
| `join.py` | `normalize_barcode` (**TCGA-shaped**) + left join + `JoinReport` | reusable core |
| `model.py` | `FileRow`, barcode/field extraction (regex on flattened TSV), `galaxy_ext` map | partly reusable |
| `io.py` | `write_manifest` / `write_metadata` / `write_report`; column constants | reusable core |
| `net.py` | `build_session` retry/backoff (marked TEMPORARY, dup of `gacdi.net`) | reusable |
| `errors.py` | `ManifestError`/`InputError`/`ApiError` + exit codes | reusable |
| `__init__.py` | `__version__=0.1.0`, `BUILD` env, `version_string()` | reusable |

Plan §5's target architecture (`importer.py` Protocol + `registry.py` + `sources/*`) does
**not exist yet** — accurate as a to-build.

---

## 4. Test & HTTP-mocking approach (resolves plan §9's open question)

- **Framework:** `pytest`. **Mocking:** **`requests-mock`** (declared in `pyproject.toml`
  `[dev]`), used via the `requests_mock` fixture with `text=callback` / `json=` handlers.
  Example: `conftest.py` registers `FILES_ENDPOINT` and branches on the POST body
  (facets → aggregations, `size==0` → count, else → TSV).
- **No vcrpy / no `responses`** in use. **Recommendation:** keep `requests-mock`; do not
  introduce a second mocking stack. Layer golden-file assertions (plan §9) on top of it.
- **Offline:** all 36 tests run with `-m "not network"`. One `network` marker exists for
  optional live calls. The Galaxy `<test>` in the XML uses a **live** GDC count/facet call
  (run via `planemo test`), so it is not offline — keep that in mind for CI.
- Test files: `test_cli.py`, `test_importer_contract.py`, `test_gdc_cbio.py`, `test_join.py`,
  `test_filters.py`, `test_model.py`, `test_io_enrich.py`, `conftest.py`.

---

## 5. ⚠️ Contract conflicts the plan must resolve BEFORE T0.1

### 5a. The plan's new manifest schema BREAKS the locked importer contract
- **Today** `MANIFEST_COLUMNS = ["id","filename","md5","size","state"]` (`io.py:38`), and
  `tests/test_importer_contract.py` **locks** that the downstream GaCDI GDC importer's
  `parse_gdc_manifest` requires columns **`{id, filename, md5, size}`** and is also
  `gdc-client`-compatible.
- **Plan §4.1** renames these to `file_id` / `checksum` and adds `drs_uri`, `download_method`,
  `access`, etc. As written, that **fails `test_importer_contract.py`** and breaks the
  existing downstream importer + `gdc-client`.
- **Options to put to the human (this is a real, unlisted decision):**
  1. Keep `id`/`filename`/`md5`/`size`/`state` as the GDC manifest's canonical column names
     and add the new multi-source columns (`source`, `drs_uri`, `download_method`, `access`,
     …) *alongside* them → back-compatible, slightly redundant.
  2. Adopt the plan's `file_id`/`checksum` names and **update the downstream importer +
     contract test** in lockstep → cleaner, but a coordinated breaking change across tools.
  3. Per-source manifest dialects sharing a superset schema.
- **Recommendation:** Option 1 for GDC (preserve the locked contract), with the richer
  columns added. Confirm before freezing in T0.1.

### 5b. `--max-files` still non-deterministic (confirms T0.5 is needed)
`gdc.query_files` sends **no `sort`** in the payload (`gdc.py:104-111`); `cli.py:153` sorts
*after* fetch. So a cap takes GDC's default order then sorts the survivors — not reproducible.
T0.5 (server-side `sort=file_id:asc`) is correctly scoped.

### 5c. Join key is TCGA-only (confirms T0.6) + a hidden dependency
`normalize_barcode` slices `TCGA-XX-XXXX-01A` on `-` (`join.py:22-43`) and is the *primary*
key. **Also:** the GDC `FIELDS` list requests only `submitter_id` (barcodes), **not**
`case_id` / `sample_id` UUIDs. So T0.6 ("native case_id/sample_id join") must **first add
`cases.case_id` and `cases.samples.sample_id` to `gdc.FIELDS`** — they aren't fetched today.

### 5d. Multi-sample files pick one arbitrarily (confirms T0.7)
`_first_match` returns the first barcode in sorted key order (`model.py:18-22`). Pooled files
silently attribute to one sample.

### 5e. GDC-native clinical fields absent (confirms T0.9)
`gdc.FIELDS` has no `demographic.*` / `diagnoses.*`. cBioPortal is currently the *primary*
clinical source via `enrich.collect`. T0.9 correctly adds these to `FIELDS` + demotes cBio.

### 5f. Provenance partially present (scopes T0.4)
`write_report` already stamps `gacdi_manifest_version` (`io.py:106`), but the **manifest and
metadata files carry no provenance header/sidecar**. T0.4 = add source/endpoint/version/
query/UTC-timestamp to *those two* outputs (report already has the version).

---

## 6. Minor cleanup items noticed (not blocking)
- **Two Dockerfiles:** `cli_tools/gacdi_manifest/Dockerfile` and
  `containers/Dockerfile.manifest`. README references only the latter, and its `COPY` paths
  (`pyproject.toml`, `gacdi_manifest/`) assume the build context is `cli_tools/gacdi_manifest/`,
  yet README shows `docker build -f containers/Dockerfile.manifest .` from repo root — **path
  mismatch, likely broken build**. Reconcile before Phase 1 packaging work.
- **Three empty root dirs** (`gacdi/`, `gacdi_manifest/`, `tests/`) — delete or `.gitignore`
  their `__pycache__` to avoid confusion with the real `cli_tools/...` package.
- `net.py` docstring says it's a temporary dup of `gacdi.net` pending a branch merge.

---

## 7. Corrections to the plan text
- §5 "reusable pieces already exist: `join.py`, `io.py`, `model.py`, `net.py`" → correct, but
  they live under **`cli_tools/gacdi_manifest/gacdi_manifest/`**, not repo root.
- §7 T0.10 "Galaxy tool skeleton" → a full GDC wrapper **already exists** at
  `tools/manifest_gdc/gacdi_manifest_gdc.xml`; retask T0.10 to "align existing wrapper to the
  frozen contract + add second output datatypes if schema changes."
- §9 "adopt vcrpy/pytest-recording if no mock approach exists" → **not needed**; `requests-mock`
  is already the approach.
- §3 "optional extras per source" → partially pre-scaffolded in `containers/env/`.
- §4.1 manifest schema → see conflict 5a; not mergeable as-is without a downstream decision.
