# Package marker.

# The modules of this package were merged into audio_core.py; the old names stay valid.
import sys as _sys
from . import audio_core as _merged
for _old in ('audio_mixer', 'narration', 'speakable', 'subtitles', 'voice_style', 'pipeline'):
    _sys.modules[__name__ + "." + _old] = _merged
    globals()[_old] = _merged
