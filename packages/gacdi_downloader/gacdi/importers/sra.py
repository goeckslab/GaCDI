"""Compatibility shim: ``gacdi.importers.sra`` is an alias of ``gacdi.sources.sra``.

The canonical module moved to :mod:`gacdi.sources.sra`. Aliasing it in
``sys.modules`` keeps historical imports — and white-box monkeypatching of module
internals via the old path — working transparently.
"""

import sys

from gacdi.sources import sra as _module

sys.modules[__name__] = _module
