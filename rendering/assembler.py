"""Joins scene clips, the narration mix and burned-in subtitles into one finished MP4, with a description.

Everything runs with FFmpeg. Nothing here publishes anything.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path


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


def assemble(silent_video, out_path, audio=None, subtitles_ass=None, fps=30, crf=20, preset="medium"):
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
        command += ["-vf", f"subtitles={ass.name}"]
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
