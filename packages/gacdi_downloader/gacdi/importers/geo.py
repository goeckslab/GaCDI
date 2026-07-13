"""Compatibility shim: ``gacdi.importers.geo`` is an alias of ``gacdi.sources.geo``.

The canonical module moved to :mod:`gacdi.sources.geo`. Aliasing it in
``sys.modules`` keeps historical imports — and white-box monkeypatching of module
internals via the old path — working transparently.
"""

import sys

from gacdi.sources import geo as _module

sys.modules[__name__] = _module
