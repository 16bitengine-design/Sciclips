# The modules of this package were merged into core.py; the old names stay valid.
import sys as _sys
from . import core as _merged
for _old in ('ai_writer', 'topic_manager', 'script_generator', 'storyboard_generator', 'script_validator', 'topic_scout'):
    _sys.modules[__name__ + "." + _old] = _merged
    globals()[_old] = _merged
