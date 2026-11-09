"""Voice profiles: blended voices plus a 'radio' sound added with FFmpeg.

A profile lives in config/voices.json. Blending averages Kokoro's voice styles by weight, which makes a
voice that is not any one of the originals. The radio sound is a gentle filter chain, not a copy of any person.
"""
import json
import shutil
import subprocess
import wave
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "voices.json"


class VoiceStyleError(Exception):
    """Raised for a missing profile or a failed audio filter."""


def load_voices(path=None):
    path = Path(path) if path else DEFAULT_PATH
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def get_profile(name, voices=None):
    """Profile settings for a name, with the shared radio chain filled in. Raises VoiceStyleError."""
    voices = voices or load_voices()
    profiles = voices.get("profiles", {})
    if name not in profiles:
        raise VoiceStyleError(f"Unknown voice profile '{name}'. Known profiles: {', '.join(sorted(profiles))}")
    profile = dict(profiles[name])
    profile["name"] = name
    profile["post"] = {**voices.get("radio_chain", {}), **profile.get("post", {})}
    blend = profile.get("blend") or {}
    if not blend or any(w <= 0 for w in blend.values()):
        raise VoiceStyleError(f"Profile '{name}' needs a blend with positive weights.")
    return profile


def normalised_blend(blend):
    total = float(sum(blend.values()))
    return {name: weight / total for name, weight in blend.items()}


def blend_style(engine, blend):
    """Weighted average of the voice styles, as one style the engine can speak with."""
    parts = normalised_blend(blend)
    style = None
    for name, weight in parts.items():
        piece = engine.get_voice_style(name) * weight
        style = piece if style is None else style + piece
    return style


def _rate(path):
    with wave.open(str(path), "rb") as handle:
        return handle.getframerate()


def build_filter(post, sample_rate):
    """The FFmpeg filter chain for the radio sound. Pitch below 1 lowers the voice without changing its speed."""
    chain = []
    if post.get("highpass_hz"):
        chain.append(f"highpass=f={post['highpass_hz']}")
    pitch = float(post.get("pitch", 1.0))
    if abs(pitch - 1.0) > 0.001:
        chain += [f"asetrate={round(sample_rate * pitch)}", f"aresample={sample_rate}", f"atempo={1.0 / pitch:.5f}"]
    if post.get("warmth_db"):
        chain.append(f"equalizer=f=140:t=o:w=1.5:g={post['warmth_db']}")
    if post.get("presence_db"):
        chain.append(f"equalizer=f=3000:t=o:w=1.5:g={post['presence_db']}")
    if post.get("deess_db"):
        chain.append(f"equalizer=f=7500:t=o:w=1:g={post['deess_db']}")
    if post.get("compress"):
        chain.append("acompressor=threshold=-20dB:ratio=3:attack=8:release=120:makeup=4")
    chain.append("alimiter=limit=0.9:level=0")
    return ",".join(chain)


def apply_radio_sound(in_path, out_path, post):
    """Filter one WAV file. Returns the output path."""
    if shutil.which("ffmpeg") is None:
        raise VoiceStyleError("FFmpeg was not found. Install it (sudo apt-get install -y ffmpeg).")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(in_path), "-af", build_filter(post, _rate(in_path)),
               str(out_path)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not Path(out_path).exists():
        raise VoiceStyleError(f"The radio filter failed: {result.stderr.strip()[-300:]}")
    return Path(out_path)
