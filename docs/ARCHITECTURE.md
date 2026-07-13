# GaCDI architecture & decision record

This document records the architecture GaCDI settled on after the packages/
refactor, plus the compatibility policy and ownership rules that keep it stable.
It replaces the pre-refactor ground-truth notes, whose still-valid decisions are
folded into sections 5 and 6 below.

## 1. Three distributions under `packages/`

GaCDI is a monorepo of three independently installable Python distributions:

| Distribution | Import package | CLI | Directory | Role |
|---|---|---|---|---|
| `gacdi-core` | `gacdi_core` | — | `packages/gacdi_core/` | Shared foundation: selection-bundle contracts, validators, retrying HTTP session, minimal error root |
| `gacdi` | `gacdi` | `gacdi` (alias `gacdi-downloader`) | `packages/gacdi_downloader/` | Download engine: consume a manifest/accession/query, stream files into a Galaxy collection + summary |
| `gacdi-manifest` | `gacdi_manifest` | `gacdi-manifest` (alias `gacdi-manifest-builder`) | `packages/gacdi_manifest_builder/` | Manifest builder: query a repository with filters, emit a manifest + enriched metadata + canonical selection bundle |

Both tools depend on `gacdi-core`; the builder no longer depends on the
downloader at runtime. Install order in the monorepo is core first, then the two
tools (see each package README and `.github/workflows/ci.yml`).

## 2. Per-tool internal structure

Each tool keeps a role-specific abstract base class, a lazy registry, and a
shared CLI workflow, and composes injected transport at the boundaries:

```
CLI arguments
    -> role-specific source          (gacdi.sources.* / gacdi_manifest.sources.*)
        -> injected client/adapter   (gacdi.clients.* / gacdi_manifest.clients.*)
            -> HTTP API, SDK, or executable
        -> native-to-domain mapping
    -> shared base workflow          (BaseDownloadSource / BaseManifestSource)
        -> validation, limits, retries, output, provenance
```

- **Base classes** own the invariant workflow: `BaseDownloadSource` (resolve →
  download → verify → summarize) and `BaseManifestSource` (build query → count →
  fetch → harmonize → write manifest/bundle).
- **Sources** map user intent and native data into GaCDI domain objects.
- **Clients/adapters** own communication with an HTTP API, SDK, or command-line
  tool: endpoints, request construction, pagination, auth, error translation, and
  raw-response validation. They do no CLI parsing and no Galaxy output writing.
- **Registries** are lazy: a `SourceSpec` names a `"module:Class"` import target
  loaded only when the source is selected, so one broken or optional source
  cannot break the other CLI subcommands.

Not every source needs a dedicated client. Xena composes the shared
`stream_download` primitive and deliberately has none.

## 3. Compatibility policy

This refactor was behaviour-neutral and compatibility-first. The following public
surfaces are preserved and covered by tests:

- **Distributions & imports:** `gacdi`, `gacdi-manifest`, `gacdi`, `gacdi_manifest`.
- **CLIs:** `gacdi` and `gacdi-manifest` (descriptive aliases `gacdi-downloader` /
  `gacdi-manifest-builder` added alongside).
- **Class names:** the preferred names are `BaseDownloadSource` / `*DownloadSource`
  and `BaseManifestSource` / `*ManifestSource`; the historical `BaseImporter` /
  `*Importer` and `BuildImporter` names remain as aliases pointing at the same
  objects.
- **Import paths:** `gacdi.importers.*` (including per-source submodules) and
  `gacdi_manifest.importer` continue to work as shims; `gacdi.contracts`,
  `gacdi.validation`, `gacdi.net.build_session`, and `gacdi_manifest.net.build_session`
  re-export from `gacdi-core`.
- **Registry accessors:** `get_source()` is preferred; `get_importer()` is an alias.
- **Galaxy tool IDs, command names, and Quay image names** are unchanged.

**Deprecation policy:** none of these compatibility aliases/shims are removed in
this refactor. They are supported for at least one full minor release. Any future
removal, or any rename of a public distribution/import/CLI/image/Galaxy tool ID,
requires a separate migration plan, a deprecation notice, and a major-version
decision — it is not a behaviour-neutral change.

## 4. `gacdi-core` ownership rules

`gacdi-core` must stay narrow — it is not a place for miscellaneous shared code. A
symbol belongs there **only** when both runtime tools consume the same concept:
the selection-bundle contracts, their validators, the retrying HTTP session
constructor, and the minimal `GacdiError` / contract `InputError` root.

It must **not** hold: builder `FileRow`/`ManifestRow` models; downloader
`FileEntry`/`DownloadResult`/`RunSummary` models; manifest parsing only the
downloader consumes; history/output writers; tool-specific exception hierarchies;
or repository-specific DTOs, clients, or mapping functions. See
`packages/gacdi_core/README.md`.

## 5. Standing decisions (still valid)

- **Two halves, one system.** The builder emits a manifest + canonical selection
  bundle; the downloader consumes it. They are separate distributions with
  separate test suites; a cross-tool integration suite exercises the handoff.
- **GDC manifest column contract.** The GDC manifest keeps its locked column names
  `id / filename / md5 / size / state` (consumable by `gdc-client` and by the
  downloader's `parse_gdc_manifest`). The richer multi-source selection schema is
  a separate canonical bundle, not a rename of these columns.
- **Testing.** `pytest` with `requests-mock` for HTTP; no second mocking stack.
  Offline suites use injected fakes/sessions; live calls are marked `network`.
  Client extraction added isolated client tests (real HTTP via `requests-mock`)
  and source-mapping tests (injected fake clients).
- **Galaxy packaging.** Tool IDs and command names are frozen. XML wrappers are
  not grouped into subdirectories and the per-tool manifest macros are kept
  self-contained, because `.shed.yml`'s `auto_tool_repositories` splitting
  requires each generated repository to carry its own macros; directory symmetry
  alone does not justify risking packaging completeness.

## 6. Superseded decision

The historical notes recorded a decision to keep the builder and downloader
**fully decoupled**, with the builder duplicating `net.py` and mirroring the
downloader's contract modules rather than importing them, to preserve a
`manifest_tool` fast-forward. That decision is **superseded**: the shared concepts
now live in `gacdi-core`, which both tools import, removing the duplication while
still keeping the builder independent of the downloader at runtime.
