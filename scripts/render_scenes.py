"""Renders storyboard scenes for one topic into silent MP4 clips and checks each clip.

Output goes to output/<topic_id>/<format>_<variant>/ (not stored in Git).
Stage 5 renders draft quality by default so the check runs quickly.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from animation.two_d.renderer import RenderError, frame_rate, frame_size, render_storyboard  # noqa: E402
from content.script_generator import ScriptError, available_variants, generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from rendering.video_validator import validate_video  # noqa: E402
from research.science_validator import validate_topic_id  # noqa: E402


def run(root, topic_id, video_format, out_dir, quality="draft"):
    """Returns (ok, report_lines)."""
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
                folder = Path(out_dir) / topic_id / f"{fmt}_{variant}" / "scenes"
                reports = render_storyboard(storyboard, record, folder, quality)
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
            ok = ok and not bad
    return ok, lines


def main():
    topic_id = os.environ.get("TOPIC_ID", "physics-001")
    video_format = os.environ.get("VIDEO_FORMAT", "short")
    quality = os.environ.get("RENDER_QUALITY", "draft")
    if video_format not in ("short", "long", "both"):
        print(f"Unknown video format: {video_format}")
        return 1
    ok, lines = run(".", topic_id, video_format, os.environ.get("OUTPUT_DIR", "output"), quality)
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## 2D scene rendering\n\n```\n" + text + "\n```\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
