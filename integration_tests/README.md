# Cross-tool integration tests

This suite installs both GaCDI tools together and exercises their handoffs. It
covers the canonical selection bundle (asset manifest, association metadata,
and provenance JSON) and the legacy GDC manifest/metadata compatibility surface.

## Running

Install both distributions (editable) and run from the repository root:

```sh
python -m pip install -e packages/gacdi_core
python -m pip install -e 'packages/gacdi_downloader[dev]'
python -m pip install -e 'packages/gacdi_manifest_builder[dev]'
pytest -q integration_tests
```

## Offline baselines

The two per-distribution suites remain separate and are run from their own
project roots:

| Suite | Command | Baseline |
|---|---|---|
| Core (`gacdi-core`) | `pytest -q` (`packages/gacdi_core`) | Shared contract tests |
| Downloader (`gacdi`) | `pytest -q -m "not network"` (`packages/gacdi_downloader`) | 104 passed at Phase 0 start |
| Builder (`gacdi-manifest`) | `pytest -q -m "not network"` (`packages/gacdi_manifest_builder`) | 93 passed at Phase 0 start |

Phase 0 added characterization tests (CLI surface, exit codes, public import
surface, registry contract, golden outputs) on top of these baselines.
