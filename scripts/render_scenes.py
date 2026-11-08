"""Makes narration, subtitles and scene clips for one topic, and checks everything.

Output goes to output/<topic_id>/<format>_<variant>/ (not stored in Git):
  scenes/      silent MP4 clips plus a contact sheet
  audio/       one WAV per scene, the narration track and audio_mix.m4a
  subtitles.srt, subtitles.ass, timeline.json, storyboard_timed.json
Scene lengths follow the narration audio. Draft quality is used by default so the check runs quickly.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.pipeline import produce  # noqa: E402
from animation.two_d.renderer import RenderError, frame_rate, frame_size, render_storyboard  # noqa: E402
from content.script_generator import ScriptError, available_variants, generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from rendering.video_validator import validate_video  # noqa: E402
from research.science_validator import validate_topic_id  # noqa: E402


def run(root, topic_id, video_format, out_dir, quality="draft", narration=None):
    """Returns (ok, report_lines). narration is espeak, piper or none (the default here)."""
    lines, ok = [], True
    try:
        record = load_topic_record(root, topic_id)
    except FileNotFoundError:
        return False, [f"No topic record at topics/records/{topic_id}.json"]
    with open(Path(root) / "config" / "rendering.json", encoding="utf-8") as handle:
        rendering = json.load(handle)
    max_mb = rendering.get("max_output_size_mb", 200)

    science = validate_topic_id(root, topic_id)
    if science["status"] == "failed":
        return False, ["Science check failed; nothing rendered."] + science["errors"]

    formats = ["short", "long"] if video_format == "both" else [video_format]
    for fmt in formats:
        for variant in available_variants(record):
            tag = f"{fmt}/{variant}"
            try:
                script = generate_script(record, fmt, variant, rendering, science)
                storyboard = generate_storyboard(script, record, rendering)
                base = Path(out_dir) / topic_id / f"{fmt}_{variant}"
                audio = produce(storyboard, record, rendering, base, narration or "none")
                storyboard = audio["storyboard"]
                reports = render_storyboard(storyboard, record, base / "scenes", quality)
            except (ScriptError, RenderError) as err:
                lines.append(f"{tag}: FAILED - {err}")
                ok = False
                continue
            width, height = frame_size(storyboard, quality)
            fps = frame_rate(storyboard, quality)
            bad = 0
            for report in reports:
                problems = validate_video(report["path"], width, height, report["duration_seconds"], 0.3, fps,
                                          max_size_mb=max_mb)
                for problem in problems:
                    lines.append(f"    scene {report['scene_number']}: {problem}")
                bad += bool(problems)
            total = sum(r["duration_seconds"] for r in reports)
            lines.append(f"{tag}: {'OK' if not bad else 'PROBLEMS'} - {len(reports)} clips, {width}x{height} "
                         f"at {fps} fps, about {total:.0f} s of video ({quality} quality)")
            voice = audio["provider"]
            lines.append(f"    narration: {voice if voice != 'none' else 'none (subtitles only)'}, "
                         f"{audio['timeline']['subtitle_cues']} subtitle cues"
                         + (f", loudness {audio['timeline']['loudness_lufs']:.1f} LUFS"
                            if audio["timeline"]["loudness_lufs"] is not None else ""))
            for note in audio["notes"]:
                lines.append(f"    note: {note}")
            for problem in audio["problems"]:
                lines.append(f"    audio problem: {problem}")
            if audio["timeline"]["licence_note"] and not audio["timeline"]["publishable"]:
                lines.append(f"    licence: {audio['timeline']['licence_note']}")
            ok = ok and not bad and not audio["problems"]
    return ok, lines


def main():
    topic_id = os.environ.get("TOPIC_ID", "physics-001")
    video_format = os.environ.get("VIDEO_FORMAT", "short")
    quality = os.environ.get("RENDER_QUALITY", "draft")
    with open("config/rendering.json", encoding="utf-8") as handle:
        configured = json.load(handle).get("narration", {}).get("provider", "none")
    narration = os.environ.get("NARRATION_PROVIDER") or configured
    if video_format not in ("short", "long", "both"):
        print(f"Unknown video format: {video_format}")
        return 1
    ok, lines = run(".", topic_id, video_format, os.environ.get("OUTPUT_DIR", "output"), quality, narration)
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## 2D scene rendering\n\n```\n" + text + "\n```\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
