"""Builds the narration track, an original background pad, the final mix and checks them (FFmpeg)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

SAMPLE_RATE = 44100
TARGET_LUFS = -16.0


class AudioError(Exception):
    """Raised when audio cannot be built."""


def _run(command):
    if shutil.which("ffmpeg") is None:
        raise AudioError("FFmpeg was not found. Install it (sudo apt-get install -y ffmpeg).")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioError(f"FFmpeg failed: {result.stderr.strip()[-300:]}")
    return result


def build_narration_track(items, out_path):
    """Join scene audio files, each padded or cut to its scene length. items = [(wav_path, seconds)]."""
    if not items:
        raise AudioError("No scene audio to join.")
    command = ["ffmpeg", "-y", "-loglevel", "error"]
    filters, labels = [], []
    for i, (path, seconds) in enumerate(items):
        command += ["-i", str(path)]
        filters.append(f"[{i}:a]aresample={SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=mono,"
                       f"apad=whole_dur={seconds:.3f},atrim=0:{seconds:.3f},asetpts=N/SR/TB[a{i}]")
        labels.append(f"[a{i}]")
    filters.append("".join(labels) + f"concat=n={len(items)}:v=0:a=1[out]")
    command += ["-filter_complex", ";".join(filters), "-map", "[out]", str(out_path)]
    _run(command)
    return Path(out_path)


def make_music(seconds, out_path):
    """A soft, original background pad made from four sine tones. Created here, so no licence issues."""
    seconds = max(4.0, float(seconds))
    tones = [110.0, 164.81, 220.0, 261.63]
    command = ["ffmpeg", "-y", "-loglevel", "error"]
    for freq in tones:
        command += ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate={SAMPLE_RATE}:duration={seconds:.3f}"]
    chain = ("amix=inputs=4:normalize=0,lowpass=f=900,tremolo=f=0.15:d=0.4,volume=0.6,"
             f"afade=t=in:d=2,afade=t=out:st={seconds - 3:.3f}:d=3")
    command += ["-filter_complex", "[0:a][1:a][2:a][3:a]" + chain + "[out]", "-map", "[out]", "-ac", "1",
                str(out_path)]
    _run(command)
    return Path(out_path)


def mix(narration_wav, out_m4a, music_wav=None, music_db=-26.0, lufs=TARGET_LUFS):
    """Mix narration with optional music, normalise loudness and save as AAC."""
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(narration_wav)]
    norm = f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    if music_wav:
        command += ["-i", str(music_wav), "-filter_complex",
                    f"[1:a]volume={music_db}dB[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,{norm}[out]",
                    "-map", "[out]"]
    else:
        command += ["-af", norm]
    command += ["-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "aac", "-b:a", "160k", str(out_m4a)]
    _run(command)
    return Path(out_m4a)


def measure_loudness(path):
    """Integrated loudness in LUFS, or None if it cannot be measured."""
    result = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                             f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                            capture_output=True, text=True)
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr, re.S)
    if not match:
        return None
    try:
        return float(json.loads(match.group(0))["input_i"])
    except (ValueError, KeyError):
        return None


def validate_audio(path, duration, tolerance=0.4, lufs=TARGET_LUFS, lufs_tolerance=3.0):
    """Returns a list of problems; empty means the audio looks fine."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return [f"Audio file missing or empty: {path}"]
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return ["Cannot read audio file."]
    info = json.loads(result.stdout)
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if audio is None:
        return ["No audio stream."]
    problems = []
    if audio.get("codec_name") != "aac":
        problems.append(f"Audio codec is {audio.get('codec_name')}, expected aac.")
    actual = float(info.get("format", {}).get("duration") or 0)
    if abs(actual - duration) > tolerance:
        problems.append(f"Audio is {actual:.2f} s, expected about {duration:.2f} s.")
    loudness = measure_loudness(path)
    if loudness is None:
        problems.append("Could not measure loudness.")
    elif abs(loudness - lufs) > lufs_tolerance:
        problems.append(f"Loudness is {loudness:.1f} LUFS, expected about {lufs:.0f}.")
    return problems
