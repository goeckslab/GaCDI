# PDC manifest spike

Validated on 2026-07-20 against the official PDC portal source and public API.

- CSV and TSV exports use the same 16-column file-manifest schema represented by
  the fixtures in this directory.
- The current URL header is `File Download Link` (not `File Download URL`).
- `File ID` is a stable UUID, and `Md5sum` plus `File Size (in bytes)` provide
  integrity metadata.
- The portal populates the link from `filesPerStudy.signedUrl.url`; exported links
  expire after seven days. The fixtures therefore replace the real link with
  `https://example.invalid/...`.
- The example filename, UUID, size, and MD5 were returned by the public
  `fileMetadata` GraphQL query for the UUID shown in the fixture.
- Because valid exports already carry signed URLs and no permanent unsigned path
  is exposed by the manifest, the optional GraphQL fallback and a committed live
  PDC download test are intentionally not used. Offline tests cover the transfer
  contract without expiring credentials or consuming PDC's per-file quota.
