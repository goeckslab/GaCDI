"""Compatibility shim: ``gacdi.importers.cda`` is an alias of ``gacdi.sources.cda``.

The canonical module moved to :mod:`gacdi.sources.cda`. Aliasing it in
``sys.modules`` keeps historical imports — and white-box monkeypatching of module
internals via the old path — working transparently.
"""

import sys

from gacdi.sources import cda as _module

sys.modules[__name__] = _module
