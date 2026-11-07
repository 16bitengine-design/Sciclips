"""Loads, checks and selects topics. Topic details live in topics/records/<id>.json."""
import json
import sys
from pathlib import Path

ALLOWED_STATUSES = (
    "queued", "researched", "scripted", "storyboarded", "rendered",
    "awaiting_approval", "published", "failed",
)
EXPERIMENT_TEMPLATES = ("experiment", "chemistry_experiment")
LIST_FIELDS = ("sources", "claims", "equations", "assumptions", "variables",
               "practical_applications", "misconceptions", "what_if_scenarios")


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_template(root, name):
    return _load(Path(root) / "templates" / f"{name}.json")


def load_topic_record(root, topic_id):
    return _load(Path(root) / "topics" / "records" / f"{topic_id}.json")


def validate_topic_record(record, template):
    errors = []
    for field in template["required_fields"]:
        if field not in record or record[field] in (None, "", [], {}):
            errors.append(f"Topic is missing '{field}'.")
    for field in LIST_FIELDS:
        if field in record and not isinstance(record[field], list):
            errors.append(f"'{field}' must be a list.")
    if record.get("production_status") not in ALLOWED_STATUSES:
        errors.append(f"production_status must be one of {ALLOWED_STATUSES}.")
    if record.get("template") == "theory" and record.get("theory_status") not in ("theory", "hypothesis"):
        errors.append("theory_status must be 'theory' or 'hypothesis'.")
    if record.get("template") in EXPERIMENT_TEMPLATES:
        risk = record.get("risk_level")
        sim_only = record.get("simulation_only") is True
        if risk not in ("low", "medium", "high"):
            errors.append("risk_level must be low, medium or high.")
        if not sim_only and not record.get("procedure_steps"):
            errors.append("procedure_steps are required unless simulation_only is true.")
        if risk == "high":
            if not sim_only:
                errors.append("High-risk experiments must be simulation_only.")
            if record.get("procedure_steps"):
                errors.append("High-risk experiments must not include procedure_steps (animate only).")
    return errors


def select_next_topic(root, require_approval=False):
    """First queued topic that has not been produced yet. Returns the queue entry or None."""
    queue = _load(Path(root) / "topics" / "topic_queue.json")["topics"]
    produced = {p.get("topic_id") for p in
                _load(Path(root) / "records" / "production_history.json").get("productions", [])}
    approved = set(_load(Path(root) / "topics" / "approved_topics.json").get("approved_topic_ids", []))
    for entry in queue:
        if entry.get("status") != "queued" or entry.get("id") in produced:
            continue
        if require_approval and entry.get("id") not in approved:
            continue
        return entry
    return None


def set_status(root, topic_id, new_status):
    if new_status not in ALLOWED_STATUSES:
        raise ValueError(f"Unknown status '{new_status}'")
    path = Path(root) / "topics" / "topic_queue.json"
    data = _load(path)
    for entry in data["topics"]:
        if entry["id"] == topic_id:
            entry["status"] = new_status
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
            return
    raise KeyError(f"Topic '{topic_id}' not in queue")


def main(argv):
    root = "."
    command = argv[1] if len(argv) > 1 else "list"
    if command == "list":
        for entry in _load(Path(root) / "topics" / "topic_queue.json")["topics"]:
            print(f"{entry['id']}: {entry['title']} [{entry['status']}]")
    elif command == "next":
        entry = select_next_topic(root)
        print(entry["id"] if entry else "No eligible topic.")
    elif command == "validate":
        bad = 0
        for entry in _load(Path(root) / "topics" / "topic_queue.json")["topics"]:
            record = load_topic_record(root, entry["id"])
            problems = validate_topic_record(record, load_template(root, record.get("template", "principle")))
            print(f"{entry['id']}: {'OK' if not problems else 'PROBLEMS'}")
            for p in problems:
                print(f"  - {p}")
            bad += bool(problems)
        return 1 if bad else 0
    else:
        print("Usage: topic_manager.py [list|next|validate]")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
