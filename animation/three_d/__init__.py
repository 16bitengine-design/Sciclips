# Package marker.

# The modules of this package were merged into engine3d.py; the old names stay valid.
import sys as _sys
from . import engine3d as _merged
for _old in ('math3d', 'mesh', 'rasterizer', 'scenes3d'):
    _sys.modules[__name__ + "." + _old] = _merged
    globals()[_old] = _merged
