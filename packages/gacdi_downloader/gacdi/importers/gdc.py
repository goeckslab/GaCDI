"""Compatibility shim: ``gacdi.importers.gdc`` is an alias of ``gacdi.sources.gdc``.

The canonical module moved to :mod:`gacdi.sources.gdc`. Aliasing it in
``sys.modules`` keeps historical imports — and white-box monkeypatching of module
internals via the old path — working transparently.
"""

import sys

from gacdi.sources import gdc as _module

sys.modules[__name__] = _module
