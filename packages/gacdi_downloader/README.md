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
the downloader pairs with the manifest builder.
