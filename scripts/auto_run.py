"""Daily automatic production: picks the next topic, makes the video, checks it, publishes it.

Safety rules (all automatic, nobody has to click anything):
 - config/automation.json can switch everything off ("enabled") or make it a rehearsal ("dry_run").
 - At most `videos_per_day` videos go out per day.
 - A topic is never published twice, and is given up on after `max_attempts_per_topic` failed tries.
 - After `pause_after_failures` failed days in a row the whole thing pauses itself (records/auto_state.json).
 - A video is only published if every automatic check passed and the voice is a publishable one.
Nothing here edits science: it only publishes what the normal checks already passed.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULTS = {"enabled": False, "dry_run": True, "videos_per_day": 1, "format": "short", "quality": "full",
            "narration": "kokoro", "max_attempts_per_topic": 2, "pause_after_failures": 3,
            "made_for_kids": False, "hashtags": ["science", "sciclips"], "publisher": "buffer",
            "buffer_mode": "shareNow"}
VARIANT = "explainer"


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _default_producer(root, topic_id, fmt, out_dir, quality, narration):
    from scripts.produce_video import run  # imported late so tests do not need the video tools
    return run(root, topic_id, fmt, out_dir, quality, narration)


def _default_publisher(root, env, cfg):
    """(publisher, accounts). Buffer with Cloudinary is the default; Zernio is the alternative."""
    if cfg.get("publisher", "buffer") == "zernio":
        from publishing.zernio import Zernio
        client = Zernio(env.get("ZERNIO_API_KEY"))
        accounts = {"youtube": env.get("ZERNIO_YOUTUBE_ACCOUNT_ID"), "tiktok": env.get("ZERNIO_TIKTOK_ACCOUNT_ID")}
        if not (accounts["youtube"] or accounts["tiktok"]):
            accounts = client.find_accounts()
        return client, accounts
    from publishing.buffer_cloudinary import Buffer, BufferPublisher, Cloudinary
    buffer = Buffer(env.get("BUFFER_API_KEY"))
    accounts = {"youtube": env.get("BUFFER_YOUTUBE_CHANNEL_ID") or None, "tiktok": env.get("BUFFER_TIKTOK_CHANNEL_ID") or None}
    if not (accounts["youtube"] or accounts["tiktok"]):
        accounts = buffer.find_channels()
    return BufferPublisher(buffer, Cloudinary(env.get("CLOUDINARY_URL")), cfg.get("buffer_mode", "shareNow")), accounts


def _caption(record, hashtags):
    tags = " ".join("#" + h.lstrip("#") for h in hashtags)
    return f"{record['title']} {tags}".strip()


def run(root=".", now=None, producer=None, publisher=None, env=None):
    """Returns (exit_code, lines). Exit code 1 only for a real failure worth looking at."""
    env = os.environ if env is None else env
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    root = Path(root)
    cfg = {**DEFAULTS, **_read(root / "config" / "automation.json", {})}
    state_path = root / "records" / "auto_state.json"
    state = {"paused": False, "consecutive_failures": 0, "attempts": {}, **_read(state_path, {})}
    history_path = root / "records" / "production_history.json"
    history = _read(history_path, {"productions": []})
    history.setdefault("productions", [])

    if not cfg["enabled"]:
        return 0, ["Automation is switched off (config/automation.json)."]
    if state["paused"]:
        return 0, ["Automation has paused itself after repeated failures. Set paused to false in "
                   "records/auto_state.json when the cause is fixed."]
    posted_today = sum(1 for p in history["productions"] if str(p.get("published_at", "")).startswith(today))
    if posted_today >= cfg["videos_per_day"]:
        return 0, [f"Already published {posted_today} video(s) today. Daily limit reached."]

    from content import topic_manager as tm
    entry = None
    while True:
        entry = tm.select_next_topic(str(root))
        if entry is None:
            return 0, ["No topic is waiting in the queue. Nothing to do today."]
        if state["attempts"].get(entry["id"], 0) >= cfg["max_attempts_per_topic"]:
            tm.set_status(str(root), entry["id"], "failed")
            continue
        break
    topic_id = entry["id"]
    lines = [f"Topic: {topic_id} - {entry.get('title', '')}", f"Mode: {'REHEARSAL (nothing is posted)' if cfg['dry_run'] else 'LIVE'}"]

    def fail(reason):
        state["attempts"][topic_id] = state["attempts"].get(topic_id, 0) + 1
        state["consecutive_failures"] += 1
        if state["consecutive_failures"] >= cfg["pause_after_failures"]:
            state["paused"] = True
            lines.append("Too many failures in a row: automation is now paused.")
        _write(state_path, state)
        lines.append(f"FAILED: {reason}")
        return 1, lines

    out_dir = env.get("OUTPUT_DIR", "output")
    produce = producer or _default_producer
    try:
        ok, report_lines = produce(str(root), topic_id, cfg["format"], out_dir, cfg["quality"], cfg["narration"])
    except Exception as error:  # a crash is a failed day, not a reason to stop the schedule
        return fail(f"production crashed ({type(error).__name__}: {str(error)[:150]})")
    lines += report_lines
    final_dir = Path(out_dir) / topic_id / f"{cfg['format']}_{VARIANT}" / "final"
    report = _read(final_dir / "final_report.json", {})
    videos = sorted(final_dir.glob("*.mp4"))
    if not ok or not report or not videos:
        return fail("the video was not produced cleanly")
    if report.get("problems"):
        return fail("the finished video has problems: " + "; ".join(report["problems"][:3]))
    if cfg["quality"] != "full" or not report.get("publishable_voice"):
        return fail("the video is a draft or its voice is not publishable")

    record = tm.load_topic_record(str(root), topic_id)
    description = (final_dir / "description.txt").read_text(encoding="utf-8") if (final_dir / "description.txt").exists() else record["title"]
    published = {}
    if cfg["dry_run"]:
        lines.append(f"Rehearsal complete: would publish '{record['title']}' ({videos[0].name}).")
    else:
        try:
            client, accounts = (publisher or _default_publisher)(str(root), env, cfg)
            published = client.publish_video(videos[0], record["title"], description + "\n\n" + _caption(record, cfg["hashtags"]),
                                             _caption(record, cfg["hashtags"]), accounts, cfg["hashtags"], cfg["made_for_kids"])
        except Exception as error:
            return fail(f"publishing failed ({type(error).__name__}: {str(error)[:150]})")
        history["productions"].append({"topic_id": topic_id, "format": cfg["format"], "variant": VARIANT,
                                       "published_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                       "youtube_url": published.get("youtube", ""), "tiktok_url": published.get("tiktok", "")})
        _write(history_path, history)
        tm.set_status(str(root), topic_id, "published")
        lines.append("Published: " + ", ".join(f"{k}: {v or 'ok'}" for k, v in published.items() if k != "failed"))
        for platform, reason in published.get("failed", {}).items():
            lines.append(f"  note: {platform} did not publish ({reason})")
    state["consecutive_failures"] = 0
    state["attempts"].pop(topic_id, None)
    state["last_run"] = today
    _write(state_path, state)
    return 0, lines


def main():
    code, lines = run(".")
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Automatic production\n\n```\n" + text + "\n```\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
