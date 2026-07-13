"""Compatibility shim: ``gacdi.importers.xena`` is an alias of ``gacdi.sources.xena``.

The canonical module moved to :mod:`gacdi.sources.xena`. Aliasing it in
``sys.modules`` keeps historical imports — and white-box monkeypatching of module
internals via the old path — working transparently.
"""

import sys

from gacdi.sources import xena as _module

sys.modules[__name__] = _module
