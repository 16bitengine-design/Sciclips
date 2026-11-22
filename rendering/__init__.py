# The modules of this package were merged into assemble.py; the old names stay valid.
import sys as _sys
from . import assemble as _merged
for _old in ('assembler', 'video_validator'):
    _sys.modules[__name__ + "." + _old] = _merged
    globals()[_old] = _merged
