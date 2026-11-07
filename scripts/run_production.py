"""Stage 2 production entry point.

For now this only checks the request and writes a summary. Later stages
add script writing, animation, rendering and publishing here.
It never publishes anything at this stage.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from validate_config import load_json, validate  # noqa: E402

VALID_FORMATS = ("short", "long", "both")
VALID_COMPLEXITY = ("low", "medium", "high")
VALID_MODES = ("TEST", "APPROVAL", "AUTOMATIC")


def plan(root, topic_id, video_format, complexity, mode):
    """Returns (ok, lines). `lines` is a human-readable report."""
    lines = []

    problems = validate(root)
    if problems:
        return False, ["Configuration problems:"] + [f"- {p}" for p in problems]

    if video_format not in VALID_FORMATS:
        return False, [f"Unknown video format: {video_format}"]
    if complexity not in VALID_COMPLEXITY:
        return False, [f"Unknown animation complexity: {complexity}"]
    if mode not in VALID_MODES:
        return False, [f"Unknown output mode: {mode}"]

    if mode != "TEST":
        return False, [
            f"Mode {mode} is not available yet. Only TEST works until the "
            "pipeline is finished and you enable other modes explicitly."
        ]

    settings = load_json(root, "config/settings.json")
    if settings.get("operating_mode") != "TEST":
        return False, ["settings.json operating_mode must be TEST at this stage."]

    topics = load_json(root, "topics/topic_queue.json").get("topics", [])
    match = [t for t in topics if t.get("id") == topic_id]
    if not match:
        known = ", ".join(t.get("id", "?") for t in topics) or "(none)"
        return False, [f"Topic '{topic_id}' not found. Known topics: {known}"]

    topic = match[0]
    lines += [
        "Request accepted (nothing is rendered or published yet).",
        f"- Topic: {topic['id']} - {topic['title']}",
        f"- Format: {video_format}",
        f"- Animation complexity: {complexity}",
        f"- Mode: {mode}",
        "- Publishing: disabled in this stage",
    ]
    return True, lines


def main():
    topic_id = os.environ.get("TOPIC_ID", "physics-001")
    video_format = os.environ.get("VIDEO_FORMAT", "short")
    complexity = os.environ.get("ANIMATION_COMPLEXITY", "low")
    mode = os.environ.get("OUTPUT_MODE", "TEST")

    ok, lines = plan(".", topic_id, video_format, complexity, mode)
    report = "\n".join(lines)
    print(report)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("## Manual production\n\n" + report + "\n")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
