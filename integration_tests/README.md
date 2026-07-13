# Cross-tool integration tests

This suite installs both GaCDI distributions together and exercises the
selection-bundle handoff: the manifest builder writes the canonical asset
manifest, association metadata, and provenance JSON, and the downloader loads,
validates, and resolves them.

## Running

Install both distributions (editable) and run from the repository root:

```sh
python -m pip install -e '.[dev]'
python -m pip install -e 'cli_tools/gacdi_manifest[dev]'
pytest -q integration_tests
```

## Offline baselines

The two per-distribution suites remain separate and are run from their own
project roots:

| Suite | Command | Baseline |
|---|---|---|
| Downloader (`gacdi`) | `pytest -q -m "not network"` (repo root) | 104 passed at Phase 0 start |
| Builder (`gacdi-manifest`) | `pytest -q -m "not network"` (`cli_tools/gacdi_manifest`) | 93 passed at Phase 0 start |

Phase 0 added characterization tests (CLI surface, exit codes, public import
surface, registry contract, golden outputs) on top of these baselines.
