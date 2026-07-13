"""Transport clients/adapters for the downloader.

Each client owns communication with one repository's HTTP API, SDK, or external
tool: endpoints/request construction, native response validation, and
transport-specific error translation. The source classes in
:mod:`gacdi.sources` own selection resolution and mapping native responses into
:class:`~gacdi.model.FileEntry` / :class:`~gacdi.model.DownloadResult` objects.
"""
