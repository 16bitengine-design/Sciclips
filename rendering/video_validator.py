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
