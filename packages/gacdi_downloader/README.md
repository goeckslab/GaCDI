# gacdi — Galaxy Cancer Data importer / downloader

This directory is the build root for the **`gacdi`** distribution (import package
`gacdi`, CLI `gacdi`): the download engine that consumes a manifest (or an
accession / query selection) and streams the files into a Galaxy dataset
collection with retries, checksum verification, and a provenance summary.

It builds in isolation from this directory:

```sh
python -m pip install -e packages/gacdi_core   # shared foundation, install first
python -m pip install -e packages/gacdi_downloader
```

See the [repository README](../../README.md) for the monorepo overview and how
the downloader pairs with the manifest builder, and
[docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) for the layered
source/client/registry design and the compatibility policy.

## Cookbook: adding a download source

A new source does not automatically require a new client class, container, or
environment file. The exact files depend on the repository's transport.

1. Choose or add a client/adapter under `gacdi/clients/`:
   - an HTTP API client, an SDK adapter, an external-tool adapter, or an existing
     generic download primitive (`gacdi.net.stream_download`).
2. Add `gacdi/sources/<name>.py` implementing `BaseDownloadSource` (from
   `gacdi.base`). Accept the client in the constructor (create a default when none
   is supplied) so tests can inject a fake; keep query/selection resolution and
   native-to-`FileEntry` mapping in the source.
3. Add a lazy `SourceSpec` entry to `gacdi/registry.py`
   (`target="gacdi.sources.<name>:<Name>DownloadSource"`).
4. Add client tests (real HTTP via `requests-mock`), source mapping tests (a fake
   client, no network), registry contract coverage, and a CLI integration test.
5. Add the Galaxy wrapper under `tools/<name>/` and its test data.
6. Add a specialized container only if the source needs extra system/runtime
   dependencies; otherwise it reuses the base image.
7. Document supported input modes, authentication, output mapping, provenance,
   retry semantics, and limitations.

**Definition of done:** importing the source performs no network access; the
absence of its optional dependency does not break another source; its registry
contract passes; client errors become stable tool-level errors; output contracts
and provenance validate; offline CLI tests pass; Galaxy lint/tests pass; and any
container change has a smoke test.
