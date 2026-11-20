"""Keeps the topic queue in step with the topic records, and queues only topics that have not been published.

It looks at every record in topics/records/ and decides what is published from the real publication history
(records/production_history.json), the queue's own statuses, and posts still awaiting confirmation
(records/pending_publications.json). It then:
 - adds a record that is not in the queue yet, as "queued", only if it has not been published or is not pending;
 - marks a queue entry "published" if the history proves it was posted but the queue still says "queued"
   (so a topic can never be queued or made twice);
 - never changes any other status (for example "failed") and never removes anything.
To rehearse a topic that was already published, set SYNC_NO_REPAIR=1 so its "queued" status is left alone.
Run it before the daily production:  python scripts/sync_queue.py
"""
import json
import os
import sys
from pathlib import Path


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def sync(root=".", repair=True):
    """Returns (added_ids, repaired_ids), or None if the queue could not be read."""
    root = Path(root)
    queue_path = root / "topics" / "topic_queue.json"
    queue = _read(queue_path, None)
    if not isinstance(queue, dict) or not isinstance(queue.get("topics"), list):
        print("sync_queue: the queue could not be read, nothing changed.")
        return None
    history = _read(root / "records" / "production_history.json", {"productions": []})
    pending = _read(root / "records" / "pending_publications.json", {"posts": []})
    posted = {p.get("topic_id") for p in history.get("productions", []) if isinstance(p, dict)}
    in_flight = {p.get("topic_id") for p in pending.get("posts", []) if isinstance(p, dict)}
    known = {t.get("id") for t in queue["topics"] if isinstance(t, dict)}
    added, repaired = [], []
    if repair:
        for entry in queue["topics"]:
            if isinstance(entry, dict) and entry.get("status") == "queued" and entry.get("id") in posted:
                entry["status"] = "published"
                repaired.append(entry["id"])
    for path in sorted((root / "topics" / "records").glob("*.json")):
        record = _read(path, None)
        if not isinstance(record, dict) or "id" not in record:
            continue
        topic_id = record["id"]
        if topic_id in known or topic_id in posted or topic_id in in_flight:
            continue
        if record.get("production_status") not in ("queued", None):
            continue
        queue["topics"].append({"id": topic_id, "title": record.get("title", ""), "category": record.get("category", ""),
                                "template": record.get("template", ""), "status": "queued"})
        known.add(topic_id)
        added.append(topic_id)
    if added or repaired:
        queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
    return added, repaired


def main():
    root = Path(__file__).resolve().parents[1]
    result = sync(root, repair=os.environ.get("SYNC_NO_REPAIR") != "1")
    if result is None:
        return 0
    added, repaired = result
    if added:
        print("sync_queue: added " + ", ".join(added))
    if repaired:
        print("sync_queue: marked as published (found in the publication history): " + ", ".join(repaired))
    if not added and not repaired:
        print("sync_queue: the queue is already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
