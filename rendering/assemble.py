"""rendering: merged module (was 2 files: assembler, video_validator).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""
import sys
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))



# ============================================================================
# from rendering/assembler.py
# ============================================================================
# Joins scene clips, the narration mix and burned-in subtitles into one finished MP4, with a description.







class AssemblyError(Exception):
    """Raised when the final video cannot be built."""


def _run(command, cwd=None):
    if shutil.which("ffmpeg") is None:
        raise AssemblyError("FFmpeg was not found. Install it (sudo apt-get install -y ffmpeg).")
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise AssemblyError(f"FFmpeg failed: {result.stderr.strip()[-400:]}")
    return result


def subtitles_filter_available():
    if shutil.which("ffmpeg") is None:
        return False
    result = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return " subtitles " in result.stdout


def concat_clips(clip_paths, out_path):
    """Join clips that share one codec, size and frame rate, without re-encoding."""
    if not clip_paths:
        raise AssemblyError("There are no clips to join.")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    listing = out_path.with_suffix(".txt")
    listing.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in clip_paths), encoding="utf-8")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
          str(out_path)])
    listing.unlink()
    return out_path


def assemble(silent_video, out_path, audio=None, subtitles_ass=None, fps=30, crf=20, preset="medium", fonts_dir=None):
    """Add the audio track and burn in the subtitles. Returns the output path."""
    silent_video, out_path = Path(silent_video).resolve(), Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent_video)]
    if audio:
        command += ["-i", str(Path(audio).resolve())]
    cwd = None
    if subtitles_ass:
        ass = Path(subtitles_ass).resolve()
        cwd = str(ass.parent)  # run next to the file so the filter needs no path escaping
        extra = ""
        if fonts_dir and Path(fonts_dir).is_dir() and not set(str(fonts_dir)) & set(":\\'"):
            extra = f":fontsdir={Path(fonts_dir).resolve()}"
        command += ["-vf", f"subtitles={ass.name}{extra}"]
    command += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps),
                "-movflags", "+faststart"]
    if audio:
        command += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy", "-shortest"]
    else:
        command += ["-an"]
    command.append(str(out_path))
    _run(command, cwd=cwd)
    return out_path


# ---------------------------------------------------------------- chapters and description
CHAPTER_NAMES = {
    "hook": "Introduction", "intro": "Introduction", "question": "The question", "answer": "Simple explanation",
    "explanation_l2": "The science", "explanation_l3": "The technical details", "demonstration": "Evidence",
    "terminology": "Key terms", "equation": "The equations", "application": "Real-world uses",
    "misconception": "Common misconceptions", "limitation": "Assumptions and limits", "safety": "Safety",
    "conclusion": "Summary", "sources": "Sources", "prevention": None, "outro": None,
    "correct_procedure": "The correct approach", "overlooked": "What is overlooked",
    "what_changes": "What changes", "consequences": "The consequences", "why": "Why it happens",
}


def _clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def build_chapters(timed_storyboard, min_gap=10):
    """YouTube-style chapters: [(seconds, title)]. Returns [] if fewer than three fit."""
    raw = []
    for scene in timed_storyboard["scenes"]:
        kind = scene.get("section_kind")
        if kind == "scenario_intro":
            title = scene.get("data", {}).get("scenario_title") or scene.get("section_title")
            if not title:
                title = scene.get("on_screen_text") or "Scenario"
        else:
            title = CHAPTER_NAMES.get(kind)
        if title is None:
            continue
        if raw and raw[-1][1] == title:
            continue
        raw.append((scene["start_seconds"], title))
    chapters = []
    for start, title in raw:
        if chapters and start - chapters[-1][0] < min_gap:
            continue
        chapters.append((start, title))
    if chapters:
        chapters[0] = (0.0, chapters[0][1])
    return chapters if len(chapters) >= 3 else []


def build_description(record, timed_storyboard, fmt, voice_name):
    """Text for the video description: summary, chapters (long videos), sources and honest notes."""
    lines = [record["title"], "", record["central_question"], record["scientific_explanation"]["level_1"], ""]
    if fmt == "long":
        chapters = build_chapters(timed_storyboard)
        if chapters:
            lines.append("Chapters")
            lines += [f"{_clock(start)} {title}" for start, title in chapters]
            lines.append("")
    if record.get("safety_considerations") and record.get("template") in ("experiment", "chemistry_experiment"):
        lines += ["Safety", record["safety_considerations"], ""]
    lines.append("Sources")
    for source in record.get("sources", []):
        lines.append(f"- {source['title']} ({source['publisher']}): {source['url']}")
    lines += ["", "About this video",
              f"- The narration is a synthetic voice ({voice_name}).",
              "- The animations illustrate ideas and models. They are not experimental evidence.",
              "- Some values in the animations are assumed for illustration."]
    return "\n".join(lines) + "\n"


# ============================================================================
# from rendering/video_validator.py
# ============================================================================
# Checks that a video file is complete and matches what was asked for (uses ffprobe).






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
