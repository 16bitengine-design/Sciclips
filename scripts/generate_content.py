"""Generates scripts and storyboards for one topic and checks them.

Writes files under output/<topic_id>/ (not stored in Git). Nothing is
rendered or published at this stage.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from content.script_generator import (  # noqa: E402
    ScriptError, available_variants, generate_script, script_to_text,
)
from content.script_validator import validate_script, validate_storyboard  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from research.science_validator import validate_topic_id  # noqa: E402


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(root, topic_id, video_format, out_dir):
    """Returns (ok, report_lines)."""
    lines, ok = [], True
    try:
        record = load_topic_record(root, topic_id)
    except FileNotFoundError:
        return False, [f"No topic record at topics/records/{topic_id}.json"]
    with open(Path(root) / "config" / "rendering.json", encoding="utf-8") as handle:
        rendering = json.load(handle)

    science = validate_topic_id(root, topic_id)
    lines.append(f"Science check: {science['status']} (human review still required)")
    if science["status"] == "failed":
        return False, lines + ["Stopping: fix the topic record first."] + science["errors"]

    formats = ["short", "long"] if video_format == "both" else [video_format]
    for fmt in formats:
        for variant in available_variants(record):
            tag = f"{fmt}/{variant}"
            try:
                script = generate_script(record, fmt, variant, rendering, science)
            except ScriptError as err:
                lines.append(f"{tag}: FAILED - {err}")
                ok = False
                continue
            storyboard = generate_storyboard(script, record, rendering)
            s_check = validate_script(script, record, rendering)
            b_check = validate_storyboard(storyboard, script, record, rendering)
            problems = s_check["errors"] + b_check["errors"]
            base = Path(out_dir) / topic_id / f"{fmt}_{variant}"
            _write(Path(f"{base}_script.json"), json.dumps(script, indent=2, ensure_ascii=False) + "\n")
            _write(Path(f"{base}_script.txt"), script_to_text(script))
            _write(Path(f"{base}_storyboard.json"), json.dumps(storyboard, indent=2, ensure_ascii=False) + "\n")
            status = "OK" if not problems else "PROBLEMS"
            lines.append(f"{tag}: {status} - {script['word_count']} words, about "
                         f"{script['estimated_duration_seconds']:.0f} s, {len(storyboard['scenes'])} scenes")
            for item in problems:
                lines.append(f"    error: {item}")
            for item in s_check["warnings"] + b_check["warnings"]:
                lines.append(f"    note: {item}")
            ok = ok and not problems
    return ok, lines


def main():
    topic_id = os.environ.get("TOPIC_ID", "physics-001")
    video_format = os.environ.get("VIDEO_FORMAT", "short")
    if video_format not in ("short", "long", "both"):
        print(f"Unknown video format: {video_format}")
        return 1
    ok, lines = run(".", topic_id, video_format, os.environ.get("OUTPUT_DIR", "output"))
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Script and storyboard\n\n```\n" + text + "\n```\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
