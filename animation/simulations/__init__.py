# The modules of this package were merged into sims.py; the old names stay valid.
import sys as _sys
from . import sims as _merged
for _old in ('free_fall', 'gas_release', 'reaction_layout'):
    _sys.modules[__name__ + "." + _old] = _merged
    globals()[_old] = _merged
