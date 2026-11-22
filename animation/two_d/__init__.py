# The modules of this package were merged into draw.py; the old names stay valid.
import sys as _sys
from . import draw as _merged
for _old in ('backgrounds', 'asset_designer', 'themes', 'canvas', 'icons', 'illustrations', 'sim_draw', 'diagrams', 'scene_plan', 'scenes', 'renderer', 'thumbnail'):
    _sys.modules[__name__ + "." + _old] = _merged
    globals()[_old] = _merged
