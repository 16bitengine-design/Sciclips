"""Builds finished videos for one topic: narration, scene clips, subtitles, final MP4, thumbnail and description.

Output goes to output/<topic_id>/<format>_<variant>/ (not stored in Git). The finished files are in final/.
Quality 'draft' is quick (half size, 12 frames a second) and is never for publishing.
Quality 'full' uses the sizes and frame rates in config/rendering.json.
Nothing here publishes anything.
"""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from animation.two_d import themes  # noqa: E402
from animation.two_d.canvas import use_theme  # noqa: E402
from animation.two_d.renderer import (  # noqa: E402
    RenderError, frame_rate, frame_size, render_storyboard, save_thumbnail,
)
from animation.two_d.thumbnail import make_thumbnail  # noqa: E402
from audio.pipeline import produce  # noqa: E402
from content.script_generator import ScriptError, available_variants, generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from rendering.assembler import (  # noqa: E402
    AssemblyError, assemble, build_description, concat_clips, subtitles_filter_available,
)
from rendering.video_validator import validate_final, validate_video  # noqa: E402
from research.science_validator import validate_topic_id  # noqa: E402


def run(root, topic_id, video_format, out_dir, quality="draft", narration=None):
    """Returns (ok, report_lines)."""
    lines, ok = [], True
    try:
        record = load_topic_record(root, topic_id)
    except FileNotFoundError:
        return False, [f"No topic record at topics/records/{topic_id}.json"]
    with open(Path(root) / "config" / "rendering.json", encoding="utf-8") as handle:
        rendering = json.load(handle)
    science = validate_topic_id(root, topic_id)
    if science["status"] == "failed":
        return False, ["Science check failed; nothing produced."] + science["errors"]
    theme_name = os.environ.get("THEME_OVERRIDE") or ""
    if theme_name in ("", "config"):
        theme_name = rendering.get("style", {}).get("theme", "classic")
    if theme_name not in themes.THEMES:
        return False, [f"Unknown theme '{theme_name}'. Known themes: {', '.join(themes.THEMES)}"]
    with use_theme(theme_name):
        return _build(root, topic_id, video_format, out_dir, quality, narration, record, rendering, science,
                      theme_name)


def _build(root, topic_id, video_format, out_dir, quality, narration, record, rendering, science, theme_name):
    """Returns (ok, report_lines)."""
    lines, ok = [], True
    crf = rendering.get("final", {}).get("crf", 20)
    preset = rendering.get("final", {}).get("preset", "medium")
    voice_name = rendering.get("narration", {}).get("provider", "kokoro")

    formats = ["short", "long"] if video_format == "both" else [video_format]
    for fmt in formats:
        for variant in available_variants(record):
            tag = f"{fmt}/{variant}"
            try:
                script = generate_script(record, fmt, variant, rendering, science)
                storyboard = generate_storyboard(script, record, rendering)
                base = Path(out_dir) / topic_id / f"{fmt}_{variant}"
                audio = produce(storyboard, record, rendering, base, narration or "none")
                timed = audio["storyboard"]
                reports = render_storyboard(timed, record, base / "scenes", quality)
                width, height = frame_size(timed, quality)
                fps = frame_rate(timed, quality)
                silent = concat_clips([r["path"] for r in reports], base / "work" / "silent.mp4")
                has_voice = "audio_mix" in audio["files"]
                final = base / "final" / f"{topic_id}_{fmt}_{variant}.mp4"
                if not subtitles_filter_available():
                    raise AssemblyError("This FFmpeg cannot burn in subtitles (the 'subtitles' filter is missing).")
                assemble(silent, final, audio["files"].get("audio_mix"), audio["files"]["ass"], fps, crf, preset,
                         Path(root) / "assets" / "fonts")
                shutil.copy(audio["files"]["srt"], base / "final" / f"{topic_id}_{fmt}_{variant}.srt")
                (base / "final" / "description.txt").write_text(
                    build_description(record, timed, fmt, f"{voice_name} text-to-speech"), encoding="utf-8")
                if theme_name == "classic":
                    save_thumbnail(timed, record, base / "final" / "thumbnail.jpg", quality)
                else:
                    make_thumbnail(record, fmt, base / "final" / "thumbnail.jpg")
                check = validate_final(final, fmt, width, height, fps, timed["total_duration_seconds"], rendering,
                                       quality == "full", has_voice)
            except (ScriptError, RenderError, AssemblyError) as err:
                lines.append(f"{tag}: FAILED - {err}")
                ok = False
                continue
            problems = check["problems"] + audio["problems"]
            size_mb = final.stat().st_size / (1024 * 1024)
            report = {"topic_id": topic_id, "format": fmt, "variant": variant, "quality": quality, "theme": theme_name,
                      "voice": audio["provider"], "publishable_voice": audio["timeline"]["publishable"],
                      "width": width, "height": height, "fps": fps, "seconds": timed["total_duration_seconds"],
                      "size_mb": round(size_mb, 2), "problems": problems, "warnings": check["warnings"],
                      "notes": audio["notes"]}
            (base / "final" / "final_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            shutil.rmtree(base / "work", ignore_errors=True)
            lines.append(f"{tag}: {'OK' if not problems else 'PROBLEMS'} - {final.name}, {width}x{height} at {fps} fps, "
                         f"{timed['total_duration_seconds']:.0f} s, {size_mb:.1f} MB, {theme_name} style, voice: "
                         f"{audio['provider'] if has_voice else 'none (subtitles only)'} ({quality} quality)")
            for item in problems:
                lines.append(f"    problem: {item}")
            for item in check["warnings"] + [n for n in audio["notes"] if n.startswith("warning")]:
                lines.append(f"    note: {item}")
            ok = ok and not problems
    return ok, lines


def main():
    topic_id = os.environ.get("TOPIC_ID", "physics-001")
    video_format = os.environ.get("VIDEO_FORMAT", "short")
    quality = os.environ.get("RENDER_QUALITY", "draft")
    if video_format not in ("short", "long", "both"):
        print(f"Unknown video format: {video_format}")
        return 1
    with open("config/rendering.json", encoding="utf-8") as handle:
        configured = json.load(handle).get("narration", {}).get("provider", "none")
    narration = os.environ.get("NARRATION_PROVIDER") or configured
    ok, lines = run(".", topic_id, video_format, os.environ.get("OUTPUT_DIR", "output"), quality, narration)
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Finished videos\n\n```\n" + text + "\n```\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
