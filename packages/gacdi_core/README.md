# gacdi-core

The narrow shared foundation used by both GaCDI distributions — the manifest
builder (`gacdi-manifest`) and the downloader (`gacdi`).

It contains exactly the concepts both runtime tools consume:

- `gacdi_core.contracts` — the canonical selection-bundle schema (asset manifest,
  association metadata, and provenance) written by the builder and read by the
  downloader.
- `gacdi_core.validation` — the validators for that contract.
- `gacdi_core.net` — the retrying HTTP session constructor.
- `gacdi_core.errors` — a minimal shared error root (`GacdiError`) and the
  contract/input error (`InputError`) the validators raise.

## Ownership rules

A symbol belongs in `gacdi-core` **only** when both runtime tools consume the
same concept. It must not become a miscellaneous module collection. In
particular, the following do **not** belong here:

- builder `FileRow` / `ManifestRow` models;
- downloader `FileEntry` / `DownloadResult` / `RunSummary` models;
- manifest parsing that only the downloader consumes;
- history / output writers;
- tool-specific exception hierarchies and messages;
- repository-specific DTOs, clients, or mapping functions.
