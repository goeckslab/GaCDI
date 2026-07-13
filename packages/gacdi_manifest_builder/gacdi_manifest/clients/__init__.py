"""Transport clients for the manifest builder.

Each client owns communication with one repository's API: endpoints, request
construction, pagination, facets, and translation of transport errors into
:class:`~gacdi_manifest.errors.ApiError`. Clients return raw/native responses;
the source classes in :mod:`gacdi_manifest.sources` own query construction and
mapping native rows into :class:`~gacdi_manifest.model.FileRow` objects.
"""
