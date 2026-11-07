"""Checks that the project's configuration and data files are valid.

Run by the workflow and by the tests. Returns a list of problems;
an empty list means everything is fine.
"""
import json
import sys
from pathlib import Path

JSON_FILES = [
    "config/settings.json",
    "config/publishing.json",
    "config/rendering.json",
    "topics/topic_queue.json",
    "topics/approved_topics.json",
    "records/production_history.json",
    "records/publishing_history.json",
]


def load_json(root, relative_path):
    with open(Path(root) / relative_path, encoding="utf-8") as handle:
        return json.load(handle)


def validate(root="."):
    problems = []
    data = {}

    for rel in JSON_FILES:
        try:
            data[rel] = load_json(root, rel)
        except FileNotFoundError:
            problems.append(f"Missing file: {rel}")
        except json.JSONDecodeError as err:
            problems.append(f"Invalid JSON in {rel}: {err}")

    settings = data.get("config/settings.json")
    if settings is not None:
        if settings.get("operating_mode") not in settings.get("allowed_modes", []):
            problems.append("settings.json: operating_mode is not an allowed mode")
        if settings.get("never_switch_to_paid_service") is not True:
            problems.append("settings.json: never_switch_to_paid_service must be true")
        if settings.get("operating_mode") != "AUTOMATIC" and settings.get(
            "automatic_publishing_enabled"
        ):
            problems.append(
                "settings.json: automatic_publishing_enabled is true but mode is not AUTOMATIC"
            )

    publishing = data.get("config/publishing.json")
    if publishing is not None:
        names = publishing.get("secret_names", {})
        for key in ("api_key", "youtube_account_id", "tiktok_account_id"):
            if key not in names:
                problems.append(f"publishing.json: secret_names is missing '{key}'")

    rendering = data.get("config/rendering.json")
    if rendering is not None:
        for fmt in ("short", "long"):
            if fmt not in rendering:
                problems.append(f"rendering.json: missing '{fmt}' section")

    queue = data.get("topics/topic_queue.json")
    if queue is not None:
        ids = [t.get("id") for t in queue.get("topics", [])]
        if len(ids) != len(set(ids)):
            problems.append("topic_queue.json: duplicate topic ids")
        for topic in queue.get("topics", []):
            for key in ("id", "title", "status"):
                if not topic.get(key):
                    problems.append(f"topic_queue.json: a topic is missing '{key}'")

    return problems


def main():
    problems = validate(".")
    if problems:
        print("CONFIGURATION PROBLEMS FOUND:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Configuration OK: all files present and valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
