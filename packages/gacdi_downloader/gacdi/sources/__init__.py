"""Download sources: one module per repository (``gacdi.sources.<name>``).

Each module defines a ``*DownloadSource`` class (with a historical ``*Importer``
alias) implementing :class:`gacdi.base.BaseDownloadSource`. The lazy registry in
:mod:`gacdi.registry` maps source names to these classes.
"""
