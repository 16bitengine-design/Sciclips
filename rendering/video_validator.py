"""Checks that a video file is complete and matches what was asked for (uses ffprobe)."""
import json
import os
import shutil
import subprocess


def probe(path):
    """Return ffprobe's description of the file, or raise RuntimeError."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe was not found. Install FFmpeg.")
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe could not read the file")
    return json.loads(result.stdout)


def _fps(stream):
    try:
        num, den = stream.get("avg_frame_rate", "0/1").split("/")
        return float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return 0.0


def validate_video(path, width=None, height=None, duration=None, duration_tolerance=0.3, fps=None,
                   expect_audio=False, max_size_mb=200):
    """Returns a list of problems; an empty list means the file looks fine."""
    problems = []
    if not os.path.exists(path):
        return [f"File not found: {path}"]
    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb == 0:
        return ["File is empty."]
    if size_mb > max_size_mb:
        problems.append(f"File is {size_mb:.1f} MB, over the {max_size_mb} MB limit.")
    try:
        info = probe(path)
    except RuntimeError as err:
        return problems + [f"Cannot read video: {err}"]
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        return problems + ["No video stream."]
    if video.get("codec_name") != "h264":
        problems.append(f"Video codec is {video.get('codec_name')}, expected h264.")
    if video.get("pix_fmt") != "yuv420p":
        problems.append(f"Pixel format is {video.get('pix_fmt')}, expected yuv420p.")
    if width and video.get("width") != width:
        problems.append(f"Width is {video.get('width')}, expected {width}.")
    if height and video.get("height") != height:
        problems.append(f"Height is {video.get('height')}, expected {height}.")
    if fps and abs(_fps(video) - fps) > 0.5:
        problems.append(f"Frame rate is {_fps(video):.2f}, expected {fps}.")
    actual = float(info.get("format", {}).get("duration") or 0)
    if duration is not None and abs(actual - duration) > duration_tolerance:
        problems.append(f"Duration is {actual:.2f} s, expected about {duration:.2f} s.")
    if actual <= 0:
        problems.append("Video has no duration.")
    if expect_audio and audio is None:
        problems.append("Audio is missing.")
    if expect_audio and audio is not None and audio.get("codec_name") != "aac":
        problems.append(f"Audio codec is {audio.get('codec_name')}, expected aac.")
    return problems


# ------------------------------------------------------------------ final video checks
ACCEPTED_PROFILES = ("High", "Main", "Baseline", "Constrained Baseline")
ASPECTS = {"short": 9 / 16, "long": 16 / 9}


def decode_check(path):
    """True if FFmpeg can read every frame without errors (detects damaged files)."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg was not found. Install FFmpeg.")
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
                            capture_output=True, text=True)
    return result.returncode == 0 and not result.stderr.strip()


def validate_final(path, fmt, width, height, fps, duration, rendering, full_quality, expect_audio):
    """Checks a finished video. Returns {"problems": [...], "warnings": [...]}."""
    limits = rendering[fmt]
    problems = validate_video(path, width, height, duration, 0.25, fps, expect_audio,
                              rendering.get("max_output_size_mb", 200))
    warnings = []
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return {"problems": problems, "warnings": warnings}
    if not decode_check(path):
        problems.append("The video did not decode cleanly, so it may be damaged.")
    try:
        info = probe(path)
    except RuntimeError as err:
        return {"problems": problems + [str(err)], "warnings": warnings}
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video:
        if video.get("profile") not in ACCEPTED_PROFILES:
            problems.append(f"H.264 profile is {video.get('profile')}, which some platforms may refuse.")
        ratio = (video.get("width") or 1) / (video.get("height") or 1)
        if abs(ratio - ASPECTS[fmt]) > 0.01:
            problems.append(f"Aspect ratio is wrong for a {fmt} video.")
    if audio:
        if int(audio.get("channels", 0)) > 2:
            problems.append("Audio has more than two channels.")
        if int(audio.get("sample_rate", 0)) not in (44100, 48000):
            problems.append(f"Audio sample rate is {audio.get('sample_rate')}, expected 44100 or 48000.")
    actual = float(info.get("format", {}).get("duration") or 0)
    if actual > limits["max_duration_seconds"]:
        problems.append(f"Video is {actual:.0f} s, over the {limits['max_duration_seconds']} s limit for {fmt} videos.")
    if actual < limits["min_duration_seconds"]:
        warnings.append(f"Video is {actual:.0f} s, under the usual {limits['min_duration_seconds']} s for {fmt} videos.")
    if not full_quality:
        warnings.append("Draft quality: smaller and slower than the targets, so this file is not for publishing.")
    return {"problems": problems, "warnings": warnings}
