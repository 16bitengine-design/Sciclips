# The modules of this package were merged into checks.py; the old names stay valid.
import sys as _sys
from . import checks as _merged
for _old in ('claim_checker', 'equation_checker', 'safety_checker', 'source_collector', 'science_validator'):
    _sys.modules[__name__ + "." + _old] = _merged
    globals()[_old] = _merged
