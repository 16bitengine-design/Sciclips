"""tests: merged module (was 4 files: test_apply_update, test_automation, test_scene_plan, test_scout).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""



# ============================================================================
# from tests/test_apply_update.py
# ============================================================================
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import apply_update as au  # noqa: E402


def make_zip(path, files, manifest=None):
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
        if manifest is not None:
            archive.writestr("MANIFEST.json", json.dumps(manifest))


def test_files_are_written_and_listed_files_are_deleted(tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "gone.py").write_text("x")
    make_zip(tmp_path / "update.zip", {"new/a.py": "A", "b.txt": "B"}, {"delete": ["old/gone.py"]})
    written, deleted, manual, refused = au.apply(tmp_path)
    assert sorted(written) == ["b.txt", "new/a.py"] and deleted == ["old/gone.py"] and not manual and not refused
    assert (tmp_path / "new" / "a.py").read_text() == "A" and not (tmp_path / "old").exists()
    assert not (tmp_path / "update.zip").exists()           # it cannot be applied twice


def test_unsafe_paths_are_refused_and_workflow_files_are_left_for_hand_copying(tmp_path):
    make_zip(tmp_path / "update.zip", {"../evil.py": "x", "/abs.py": "x", ".git/config": "x", ".github/workflows/w.yml": "w", "ok.py": "ok"})
    written, deleted, manual, refused = au.apply(tmp_path)
    assert written == ["ok.py"] and manual == [".github/workflows/w.yml"]
    assert set(refused) == {"../evil.py", "/abs.py", ".git/config"}
    assert not (tmp_path.parent / "evil.py").exists() and not (tmp_path / ".git").exists() and not (tmp_path / ".github").exists()


def test_state_files_and_workflows_can_never_be_deleted(tmp_path):
    (tmp_path / "records").mkdir()
    (tmp_path / "records" / "auto_state.json").write_text("{}")
    make_zip(tmp_path / "update.zip", {"a.txt": "a"}, {"delete": ["records/auto_state.json", ".github/workflows/x.yml", "../x"]})
    written, deleted, manual, refused = au.apply(tmp_path)
    assert deleted == [] and len(refused) == 3 and (tmp_path / "records" / "auto_state.json").exists()


def test_a_zip_without_a_manifest_still_works(tmp_path):
    make_zip(tmp_path / "update.zip", {"only.txt": "1"})
    assert au.apply(tmp_path)[0] == ["only.txt"]


# ============================================================================
# from tests/test_automation.py
# ============================================================================
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TEST_AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_AUTOMATION_ROOT))
sys.path.insert(0, str(TEST_AUTOMATION_ROOT / "scripts"))

import auto_run  # noqa: E402
from publishing.buffer_github import Buffer, BufferPublisher, GithubReleaseMedia, PublishError, PublicationUnconfirmed  # noqa: E402

NOW = datetime(2026, 11, 15, 14, 0, tzinfo=timezone.utc)
TITLES = {t: json.loads((TEST_AUTOMATION_ROOT / "topics" / "records" / f"{t}.json").read_text())["title"] for t in ("physics-001", "chem-001")}


def make_repo(tmp_path, **config):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "topics" / "records").mkdir(parents=True)
    (repo / "records").mkdir()
    for topic in ("physics-001", "chem-001"):
        shutil.copy(TEST_AUTOMATION_ROOT / "topics" / "records" / f"{topic}.json", repo / "topics" / "records" / f"{topic}.json")
    shutil.copy(TEST_AUTOMATION_ROOT / "topics" / "topic_queue.json", repo / "topics" / "topic_queue.json")
    # Tests must start from a clean queue, not inherit live production statuses.
    queue_path = repo / "topics" / "topic_queue.json"
    queue = json.loads(queue_path.read_text())
    queue["topics"] = [topic for topic in queue["topics"] if topic["id"] in {"physics-001", "chem-001"}]
    for topic in queue["topics"]:
        topic["status"] = "queued"
    queue_path.write_text(json.dumps(queue, indent=2) + "\n")
    (repo / "topics" / "approved_topics.json").write_text('{"approved_topic_ids": []}')
    (repo / "records" / "production_history.json").write_text('{"productions": []}')
    settings = {"enabled": True, "dry_run": False, "videos_per_day": 1, "pause_after_failures": 3,
                "max_attempts_per_topic": 2}
    settings.update(config)
    (repo / "config" / "automation.json").write_text(json.dumps(settings))
    return repo


def good_producer(problems=(), publishable=True):
    def produce(root, topic_id, fmt, out_dir, quality, narration):
        final = Path(out_dir) / topic_id / f"{fmt}_explainer" / "final"
        final.mkdir(parents=True, exist_ok=True)
        (final / f"{topic_id}_{fmt}_explainer.mp4").write_bytes(b"video")
        (final / "description.txt").write_text("A description.")
        (final / "final_report.json").write_text(json.dumps({"problems": list(problems), "publishable_voice": publishable}))
        return True, ["short/explainer: OK"]
    return produce


class FakeClient:
    def __init__(self, fail=False, partial=False):
        self.calls, self.fail, self.partial = [], fail, partial

    def publish_video(self, video, title, description, caption, accounts, tags, made_for_kids):
        self.calls.append((Path(video).name, title, accounts, made_for_kids))
        if self.fail:
            raise PublishError("boom")
        result = {"youtube": "https://youtu.be/abc", "tiktok": "https://tiktok.com/x", "failed": {}}
        if self.partial:
            result = {"youtube": "https://youtu.be/abc", "failed": {"tiktok": "capacity"}}
        return result


def run(repo, producer=None, client=None, now=NOW, run_kind="schedule", schedule_cron="0 12 * * *"):
    client = client or FakeClient()
    return auto_run.run(str(repo), now=now, producer=producer or good_producer(),
                        publisher=lambda root, env, cfg: (client, {"youtube": "yt1", "tiktok": "tt1"}),
                        env={"OUTPUT_DIR": str(repo / "output"),
                             "SCICLIPS_RUN_KIND": run_kind,
                             "SCICLIPS_SCHEDULE_CRON": schedule_cron}), client


def state(repo):
    return json.loads((repo / "records" / "auto_state.json").read_text())


def test_a_good_run_publishes_and_marks_the_topic_done(tmp_path):
    repo = make_repo(tmp_path)
    (code, lines), client = run(repo)
    assert code == 0 and len(client.calls) == 1 and client.calls[0][1] == TITLES["physics-001"]
    history = json.loads((repo / "records" / "production_history.json").read_text())["productions"]
    assert history[0]["topic_id"] == "physics-001" and history[0]["youtube_url"]
    queue = json.loads((repo / "topics" / "topic_queue.json").read_text())["topics"]
    assert queue[0]["status"] == "published" and queue[1]["status"] == "queued"
    assert state(repo)["consecutive_failures"] == 0


def test_one_video_a_day_and_never_the_same_topic_twice(tmp_path):
    repo = make_repo(tmp_path)
    run(repo)
    (code, lines), client = run(repo)
    assert code == 0 and client.calls == [] and ("limit" in lines[0] or "already been completed" in lines[0])
    tomorrow = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)
    (code, lines), client = run(repo, now=tomorrow)
    assert client.calls[0][1] == TITLES["chem-001"]
    (code, lines), client = run(repo, now=datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc))
    assert code == 1 and client.calls == [] and "no validated topic" in lines[-1]


def test_manual_sample_does_not_consume_a_scheduled_slot(tmp_path):
    repo = make_repo(tmp_path, videos_per_day=1)
    (code, lines), manual = run(repo, run_kind="workflow_dispatch")
    assert code == 0 and len(manual.calls) == 1
    (code, lines), scheduled = run(repo, schedule_cron="0 12 * * *")
    assert code == 0 and len(scheduled.calls) == 1
    history = json.loads((repo / "records" / "production_history.json").read_text())["productions"]
    assert [p["run_kind"] for p in history] == ["manual", "schedule"]
    assert history[1]["schedule_slot"] == "2026-11-15|0 12 * * *"


def test_two_distinct_schedule_slots_can_publish_two_videos(tmp_path):
    repo = make_repo(tmp_path, videos_per_day=2)
    (code, lines), first = run(repo, schedule_cron="0 12 * * *")
    second_time = datetime(2026, 11, 15, 17, 0, tzinfo=timezone.utc)
    (code, lines), second = run(repo, now=second_time, schedule_cron="0 17 * * *")
    assert len(first.calls) == 1 and len(second.calls) == 1
    history = json.loads((repo / "records" / "production_history.json").read_text())["productions"]
    assert len(history) == 2 and len({p["schedule_slot"] for p in history}) == 2


def test_same_schedule_slot_cannot_publish_twice(tmp_path):
    repo = make_repo(tmp_path, videos_per_day=2)
    run(repo, schedule_cron="0 12 * * *")
    (code, lines), duplicate = run(repo, schedule_cron="0 12 * * *")
    assert code == 0 and duplicate.calls == [] and "already been completed" in lines[0]


def test_switched_off_does_nothing(tmp_path):
    repo = make_repo(tmp_path, enabled=False)
    (code, lines), client = run(repo)
    assert code == 0 and client.calls == [] and "switched off" in lines[0]


def test_a_rehearsal_posts_nothing_and_keeps_the_topic(tmp_path):
    repo = make_repo(tmp_path, dry_run=True)
    (code, lines), client = run(repo)
    assert code == 0 and client.calls == [] and any("Rehearsal" in line for line in lines)
    queue = json.loads((repo / "topics" / "topic_queue.json").read_text())["topics"]
    assert queue[0]["status"] == "queued"


def test_a_video_with_problems_is_never_published(tmp_path):
    repo = make_repo(tmp_path)
    (code, lines), client = run(repo, producer=good_producer(problems=["audio too quiet"]))
    assert code == 1 and client.calls == [] and state(repo)["consecutive_failures"] == 1


def test_a_robot_voice_or_draft_is_never_published(tmp_path):
    repo = make_repo(tmp_path)
    (code, lines), client = run(repo, producer=good_producer(publishable=False))
    assert code == 1 and client.calls == []


def test_a_crash_is_a_failed_day_not_a_dead_schedule(tmp_path):
    def crash(*args):
        raise RuntimeError("renderer fell over")
    repo = make_repo(tmp_path)
    (code, lines), client = run(repo, producer=crash)
    assert code == 1 and client.calls == [] and "crashed" in lines[-1]


def test_a_failed_post_does_not_mark_the_topic_published(tmp_path):
    repo = make_repo(tmp_path)
    (code, lines), client = run(repo, client=FakeClient(fail=True))
    assert code == 1
    assert json.loads((repo / "records" / "production_history.json").read_text())["productions"] == []


def test_one_platform_failing_still_counts_as_published(tmp_path):
    repo = make_repo(tmp_path)
    (code, lines), client = run(repo, client=FakeClient(partial=True))
    assert code == 0 and any("tiktok did not publish" in line for line in lines)
    queue = json.loads((repo / "topics" / "topic_queue.json").read_text())["topics"]
    assert queue[0]["status"] == "published"


def test_it_pauses_itself_after_repeated_failures_and_stays_paused(tmp_path):
    repo = make_repo(tmp_path, max_attempts_per_topic=9)
    for day in range(10, 13):
        (code, lines), client = run(repo, producer=good_producer(problems=["bad"]),
                                    now=datetime(2026, 11, day, 14, 0, tzinfo=timezone.utc))
        assert code == 1
    assert state(repo)["paused"] is True
    (code, lines), client = run(repo)
    assert code == 0 and client.calls == [] and "paused" in lines[0]


def test_a_topic_that_keeps_failing_is_given_up_on(tmp_path):
    repo = make_repo(tmp_path, pause_after_failures=9)
    for day in (10, 11):
        run(repo, producer=good_producer(problems=["bad"]), now=datetime(2026, 11, day, 14, 0, tzinfo=timezone.utc))
    (code, lines), client = run(repo, now=datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc))
    queue = json.loads((repo / "topics" / "topic_queue.json").read_text())["topics"]
    assert queue[0]["status"] == "failed" and client.calls[0][1] == TITLES["chem-001"]


# --- Buffer and GitHub Releases ---------------------------------------------------------------
class FakePublishingNet:
    def __init__(self, buffer_reply=None, github_status=201):
        self.requests, self.buffer_reply, self.github_status = [], buffer_reply, github_status
        self.release = None
        self.tag = None

    def __call__(self, method, url, headers, body=None):
        self.requests.append((method, url, headers, body))
        if method == "GET" and "/releases/tags/" in url:
            self.tag = url.rsplit("/", 1)[-1]
            if self.release:
                return 200, json.dumps(self.release).encode()
            return 404, b'{"message":"Not Found"}'
        if url == "https://api.github.com/repos/test-owner/test-repo/releases":
            payload = json.loads(body)
            self.tag = payload["tag_name"]
            self.release = {"id": 12, "tag_name": self.tag, "upload_url": "https://uploads.github.com/repos/test-owner/test-repo/releases/12/assets{?name,label}",
                            "assets": []}
            return 201, json.dumps(self.release).encode()
        if url.startswith("https://uploads.github.com/"):
            if self.github_status >= 400:
                return self.github_status, b'{"message":"Upload rejected"}'
            name = url.split("?name=", 1)[1]
            asset = {"name": name, "browser_download_url": "https://github.com/test-owner/test-repo/releases/download/" + self.tag + "/" + name}
            self.release["assets"].append(asset)
            return 201, json.dumps(asset).encode()
        if url == "https://api.buffer.com":
            query = json.loads(body)["query"]
            if "organizations" in query:
                return 200, json.dumps({"data": {"account": {"organizations": [{"id": "org1"}]}}}).encode()
            if "channels(" in query:
                return 200, json.dumps({"data": {"channels": [{"id": "c_yt", "service": "youtube"}, {"id": "c_tt", "service": "tiktok"}]}}).encode()
            if "post(input:" in query:
                return 200, json.dumps({"data": {"post": {
                    "id": "p1", "status": "sent", "sentAt": "2026-11-16T18:00:00Z",
                    "externalLink": "https://www.youtube.com/watch?v=test123"
                }}}).encode()
            reply = self.buffer_reply or {"data": {"createPost": {"post": {"id": "p1"}}}}
            return 200, json.dumps(reply).encode()
        raise AssertionError("Unexpected request: " + url)


def make_publisher(net):
    return BufferPublisher(Buffer("key", transport=net),
                           GithubReleaseMedia("token", "test-owner/test-repo", transport=net))


def test_buffer_publisher_uploads_once_to_github_then_posts_to_each_channel(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    net = FakePublishingNet()
    result = make_publisher(net).publish_video(video, "T" * 150, "Long description", "Short caption",
                                               {"youtube": "c_yt", "tiktok": "c_tt"}, [], False)
    assert result["youtube"] == "https://www.youtube.com/watch?v=test123" and result["youtube_post_id"] == "p1"
    assert result["youtube_sent_at"] == "2026-11-16T18:00:00Z" and result["tiktok"] == "Buffer post p1"
    assert result["failed"] == {}
    uploads = [r for r in net.requests if r[1].startswith("https://uploads.github.com/")]
    posts = [json.loads(r[3])["query"] for r in net.requests if r[1] == "https://api.buffer.com"]
    create_posts = [query for query in posts if "createPost" in query]
    assert len(uploads) == 1 and len(create_posts) == 2
    assert any("post(input:" in query for query in posts)  # publication lifecycle was checked
    assert result["media_url"].startswith("https://github.com/test-owner/test-repo/releases/download/")
    youtube, tiktok = create_posts
    assert result["media_url"] in youtube and result["media_url"] in tiktok
    assert "schedulingType: automatic" in youtube and "mode: shareNow" in youtube
    assert "isAiGenerated: true" in youtube and "madeForKids: false" in youtube and 'categoryId: "28"' in youtube
    assert ("T" * 100) in youtube and ("T" * 101) not in youtube
    assert "metadata" not in tiktok and "Short caption" in tiktok


def test_github_release_upload_uses_public_asset_url_and_is_idempotent(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    net = FakePublishingNet()
    host = GithubReleaseMedia("token", "test-owner/test-repo", transport=net)
    first = host.upload_video(video)
    second = host.upload_video(video)
    assert first == second
    assert sum(r[1].startswith("https://uploads.github.com/") for r in net.requests) == 1


def test_github_release_upload_reports_api_errors_without_leaking_token(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    net = FakePublishingNet(github_status=401)
    try:
        make_publisher(net).publish_video(video, "t", "d", "c", {"youtube": "c_yt"})
        assert False
    except PublishError as error:
        assert "401" in str(error) and "token" not in str(error)


def test_buffer_finds_the_channels_when_ids_are_not_given():
    assert Buffer("key", transport=FakePublishingNet()).find_channels() == {"youtube": "c_yt", "tiktok": "c_tt"}


def test_one_channel_failing_still_counts_and_is_reported(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")

    class Half(FakePublishingNet):
        def __call__(self, method, url, headers, body=None):
            if url == "https://api.buffer.com" and ("tiktok" in str(body) or "c_tt" in str(body)):
                return 200, json.dumps({"data": {"createPost": {"message": "TikTok is at capacity"}}}).encode()
            return super().__call__(method, url, headers, body)
    result = make_publisher(Half()).publish_video(video, "t", "d", "c", {"youtube": "c_yt", "tiktok": "c_tt"})
    assert result["youtube"] and "capacity" in result["failed"]["tiktok"]


def test_buffer_failure_is_clear_and_required_credentials_are_checked():
    try:
        Buffer("")
        assert False
    except PublishError:
        pass
    try:
        GithubReleaseMedia("", "test-owner/test-repo")
        assert False
    except PublishError:
        pass


def test_buffer_scheduled_status_is_not_counted_as_published():
    class ScheduledBuffer:
        def get_post(self, post_id):
            return {"id": post_id, "status": "scheduled", "sentAt": None, "externalLink": None}
    publisher = BufferPublisher(ScheduledBuffer(), None)
    try:
        publisher._wait_until_sent("pending-1", attempts=1, interval=0)
        assert False, "scheduled must not be treated as published"
    except PublicationUnconfirmed as error:
        assert error.post_id == "pending-1" and error.status == "scheduled"


def test_pending_buffer_post_is_verified_before_any_new_video(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    pending = {
        "posts": [{
            "topic_id": "physics-001", "title": TITLES["physics-001"],
            "format": "short", "variant": "explainer", "run_kind": "schedule",
            "schedule_cron": "0 12 * * *", "date": "2026-11-15",
            "buffer_post_id": "pending-123"
        }]
    }
    (repo / "records" / "pending_publications.json").write_text(json.dumps(pending))
    class SentBuffer:
        def __init__(self, api_key):
            assert api_key == "buffer-key"
        def get_post(self, post_id):
            assert post_id == "pending-123"
            return {"id": post_id, "status": "sent", "sentAt": "2026-11-15T14:01:00Z",
                    "externalLink": "https://www.youtube.com/watch?v=verified"}
    monkeypatch.setattr("publishing.buffer_github.Buffer", SentBuffer)
    def must_not_produce(*args, **kwargs):
        raise AssertionError("pending post must be resolved before production")
    code, lines = auto_run.run(
        str(repo), producer=must_not_produce, publisher=must_not_produce,
        env={"BUFFER_API_KEY": "buffer-key", "SCICLIPS_RUN_KIND": "schedule"}
    )
    assert code == 0 and "Publication recovered and verified" in lines[0]
    queue = json.loads((repo / "topics" / "topic_queue.json").read_text())["topics"]
    assert queue[0]["status"] == "published"
    history = json.loads((repo / "records" / "production_history.json").read_text())["productions"]
    assert history[0]["youtube_url"] == "https://www.youtube.com/watch?v=verified"
    assert history[0]["youtube_buffer_post_id"] == "pending-123"
    assert json.loads((repo / "records" / "pending_publications.json").read_text())["posts"] == []


# ============================================================================
# from tests/test_scene_plan.py
# ============================================================================
# Checks for the per-topic picture plans (animation/two_d/scene_plan.py). Pure Python, no drawing.
import copy

import pytest

from animation.two_d import scene_plan as sp


def _view(extra=None):
    elements = [{"type": "rect", "x": 80, "y": 72, "w": 130, "h": 46, "color": "blue", "alpha": 0.5},
                {"type": "ellipse", "x": 45, "y": 20, "w": 14, "h": 14, "color": "warn", "dy": 40},
                {"type": "arrow", "x": 115, "y": 70, "x2": 115, "y2": 54, "color": "good", "appear": 0.5}]
    return {"elements": elements + (extra or [])}


GOOD = {"views": {"demo": _view(), "intro": _view()}}


def test_a_good_plan_is_accepted():
    clean = sp.validate(GOOD)
    assert set(clean["views"]) == {"demo", "intro"}


def test_needs_a_demo_view_and_one_more():
    with pytest.raises(sp.PlanError):
        sp.validate({"views": {"demo": _view()}})
    with pytest.raises(sp.PlanError):
        sp.validate({"views": {"intro": _view(), "result": _view()}})


def test_rejects_unknown_type_colour_and_long_text():
    for bad in ({"type": "star", "x": 1, "y": 1},
                {"type": "rect", "x": 1, "y": 1, "w": 5, "h": 5, "color": "pink"},
                {"type": "text", "x": 1, "y": 1, "text": "x" * 25}):
        plan = copy.deepcopy(GOOD)
        plan["views"]["demo"]["elements"].append(bad)
        with pytest.raises(sp.PlanError):
            sp.validate(plan)


def test_rejects_things_that_leave_the_stage():
    plan = copy.deepcopy(GOOD)
    plan["views"]["demo"]["elements"].append({"type": "ellipse", "x": 150, "y": 50, "w": 10, "h": 10, "dx": 60})
    with pytest.raises(sp.PlanError):
        sp.validate(plan)


def test_a_view_must_have_moving_elements():
    still = {"elements": [{"type": "rect", "x": 10 * i, "y": 10, "w": 5, "h": 5} for i in range(1, 4)]}
    with pytest.raises(sp.PlanError):
        sp.validate({"views": {"demo": still, "intro": _view()}})


def test_junk_is_rejected():
    for junk in (None, [], {}, {"views": []}, {"views": {"demo": {"elements": "x"}}}):
        with pytest.raises(sp.PlanError):
            sp.validate(junk)


def test_consecutive_scenes_of_one_section_take_turns_among_the_views():
    names = [sp.view_for({"section_kind": "demonstration", "scene_number": n}) for n in range(1, 9)]
    assert set(names) >= {"demo", "explain"} and all(a != b for a, b in zip(names, names[1:]))


def test_every_section_kind_has_choices_that_are_real_views():
    for kind, choices in sp.VIEW_CHOICES.items():
        assert choices and set(choices) <= set(sp.VIEWS), kind
    assert sp.view_for({"section_kind": "something_new", "scene_number": 3}) == "demo"


# ============================================================================
# from tests/test_scout.py
# ============================================================================
import copy
import json
import shutil
import sys
from pathlib import Path

TEST_SCOUT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_SCOUT_ROOT))

from content import topic_scout as ts  # noqa: E402

TODAY = "2026-11-15"
TITLE = "Why does a fizzy tablet make bubbles?"


def rendering():
    return json.loads((TEST_SCOUT_ROOT / "config" / "config.json").read_text())["rendering"]


def TEST_SCOUT_make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "topics" / "records").mkdir(parents=True)
    (repo / "templates").mkdir()
    for name in ("physics-001", "chem-001"):
        shutil.copy(TEST_SCOUT_ROOT / "topics" / "records" / f"{name}.json", repo / "topics" / "records" / f"{name}.json")
    for name in ("principle", "chemistry_experiment"):
        shutil.copy(TEST_SCOUT_ROOT / "templates" / f"{name}.json", repo / "templates" / f"{name}.json")
    shutil.copy(TEST_SCOUT_ROOT / "topics" / "topic_queue.json", repo / "topics" / "topic_queue.json")
    queue_path = repo / "topics" / "topic_queue.json"
    queue = json.loads(queue_path.read_text())
    queue["topics"] = [topic for topic in queue["topics"] if topic["id"] in {"physics-001", "chem-001"}]
    queue_path.write_text(json.dumps(queue, indent=2) + "\n")
    return repo


def base_record():
    return json.loads((TEST_SCOUT_ROOT / "topics" / "records" / "chem-001.json").read_text())


URLS = [s["url"] for s in base_record()["sources"]]


def page_for(record):
    return " ".join(c["text"] for c in record["claims"]) + " " + ("More plain words about fizzing and gas. " * 60)


class Fake:
    """A pretend AI and a pretend web."""

    def __init__(self, idea=None, mutate=None, supported=True, bad_quote=False, page_ok=True):
        self.record = base_record()
        if mutate:
            mutate(self.record)
        self.idea = idea or {"title": TITLE, "central_question": "Where do the bubbles come from?", "category": "chemistry",
                             "template": "chemistry_experiment", "source_urls": URLS}
        self.supported, self.bad_quote, self.page_ok, self.calls = supported, bad_quote, page_ok, 0

    def ask(self, messages):
        self.calls += 1
        payload = json.loads(messages[1]["content"])
        if "already_used" in payload:
            return json.dumps(self.idea)
        if "example_record" in payload:
            return json.dumps(self.record)
        results = []
        for claim in payload["claims"]:
            quote = "this sentence is not on any page at all here" if self.bad_quote else claim["text"]
            results.append({"id": claim["id"], "supported": self.supported, "source_id": claim["source_ids"][0], "quote": quote})
        return json.dumps({"results": results})

    def fetch(self, url):
        if not self.page_ok:
            raise OSError("404")
        return page_for(base_record())


def go(tmp_path, fake, tries=1):
    repo = TEST_SCOUT_make_repo(tmp_path)
    topic_id, lines = ts.scout(repo, fake.ask, fake.fetch, rendering(), today=TODAY, tries=tries)
    return repo, topic_id, lines


def queue(repo):
    return json.loads((repo / "topics" / "topic_queue.json").read_text())["topics"]


def test_a_good_topic_is_added_to_the_queue_and_saved(tmp_path):
    repo, topic_id, lines = go(tmp_path, Fake())
    assert topic_id == "chem-002", lines
    record = json.loads((repo / "topics" / "records" / "chem-002.json").read_text())
    assert record["title"] == TITLE and record["production_status"] == "queued"
    assert "simulation" not in record and all(s["date_accessed"] == TODAY for s in record["sources"])
    assert queue(repo)[-1] == {"id": "chem-002", "title": TITLE, "category": "chemistry",
                               "template": "chemistry_experiment", "status": "queued"}


def test_a_claim_the_page_does_not_support_drops_the_topic(tmp_path):
    repo, topic_id, lines = go(tmp_path, Fake(supported=False))
    assert topic_id is None and len(queue(repo)) == 2 and "not supported" in lines[0]


def test_a_made_up_supporting_quote_drops_the_topic(tmp_path):
    repo, topic_id, lines = go(tmp_path, Fake(bad_quote=True))
    assert topic_id is None and "not really on any downloaded page" in lines[0]
    assert not (repo / "topics" / "records" / "chem-002.json").exists()


def test_an_unreadable_page_drops_the_topic(tmp_path):
    repo, topic_id, lines = go(tmp_path, Fake(page_ok=False))
    assert topic_id is None and "could not read" in lines[0]


def test_pages_from_untrusted_sites_drop_the_topic(tmp_path):
    idea = {"title": TITLE, "central_question": "Why?", "category": "chemistry", "template": "chemistry_experiment",
            "source_urls": ["https://someblog.example.com/a", "https://another.example.net/b"]}
    repo, topic_id, lines = go(tmp_path, Fake(idea=idea))
    assert topic_id is None and "trusted" in lines[0]


def test_a_topic_that_already_exists_is_dropped(tmp_path):
    idea = {"title": "What happens when baking soda meets vinegar?", "central_question": "Why?", "category": "chemistry",
            "template": "chemistry_experiment", "source_urls": URLS}
    repo, topic_id, lines = go(tmp_path, Fake(idea=idea))
    assert topic_id is None and "already exists" in lines[0]


def test_an_unbalanced_equation_is_caught_by_the_science_checks(tmp_path):
    def unbalance(record):
        record["equations"][0]["equation"] = "CH3COOH + NaHCO3 -> CH3COONa + CO2"
    repo, topic_id, lines = go(tmp_path, Fake(mutate=unbalance))
    assert topic_id is None and "science checks" in lines[0]


def test_a_source_the_ai_made_up_is_caught(tmp_path):
    def invent(record):
        record["sources"][0]["url"] = "https://www.nasa.gov/not-a-page-we-downloaded"
    repo, topic_id, lines = go(tmp_path, Fake(mutate=invent))
    assert topic_id is None and "not one of the downloaded pages" in lines[0]


def test_source_language_in_a_draft_is_caught_before_it_reaches_a_video(tmp_path):
    def cite(record):
        record["supporting_evidence"][0] = "NASA describes a very visible fizzing reaction."
    repo, topic_id, lines = go(tmp_path, Fake(mutate=cite))
    assert topic_id is None and "plain words" in lines[0] or "source language" in lines[0]


def test_a_missing_required_field_is_caught(tmp_path):
    def lose(record):
        del record["assumptions"]
    repo, topic_id, lines = go(tmp_path, Fake(mutate=lose))
    assert topic_id is None and "science checks" in lines[0]


def test_a_full_queue_costs_nothing(tmp_path):
    repo = TEST_SCOUT_make_repo(tmp_path)
    data = json.loads((repo / "topics" / "topic_queue.json").read_text())
    data["topics"] += [{"id": f"x-{i}", "title": f"t{i}", "category": "physics", "template": "principle", "status": "queued"} for i in range(20)]
    (repo / "topics" / "topic_queue.json").write_text(json.dumps(data))
    fake = Fake()
    topic_id, lines = ts.scout(repo, fake.ask, fake.fetch, rendering(), today=TODAY)
    assert topic_id is None and fake.calls == 0


def test_the_ai_being_down_never_raises_out_of_the_scout(tmp_path):
    def down(messages):
        raise ts.ScoutError("the AI was not available")
    repo = TEST_SCOUT_make_repo(tmp_path)
    try:
        ts.scout(repo, down, Fake().fetch, rendering(), today=TODAY)
    except ts.ScoutError:
        pass  # scripts/scout_topic.py catches this and adds nothing


def test_web_page_text_drops_scripts_and_menus():
    html = "<html><nav>Menu</nav><script>var x=1;</script><body><p>Real   words here.</p><footer>Foot</footer></body></html>"
    assert ts.page_text(html) == "Real words here."


def test_scout_ai_request_retries_transient_bad_responses(monkeypatch):
    import os
    from scripts import scout_topic

    monkeypatch.setenv("SCICLIPS_GEMINI_API_KEY", "test-token")
    calls = []
    def flaky(payload, token, timeout=60, url=None):
        calls.append((payload, token, timeout))
        if len(calls) < 3:
            raise RuntimeError("temporary non-JSON response: OK")
        return {"choices": [{"message": {"content": '{"title":"ok"}'}}]}

    monkeypatch.setattr(scout_topic.ai_writer, "_post", flaky)
    monkeypatch.setattr(scout_topic.time, "sleep", lambda seconds: None)
    answer = scout_topic.make_ask()([{"role": "user", "content": "test"}])
    assert answer == '{"title":"ok"}'
    assert len(calls) == 3
    assert all(call[1] == "test-token" and call[2] == scout_topic.AI_REQUEST_TIMEOUT for call in calls)


def test_scout_ai_request_rejects_empty_success_response(monkeypatch):
    import pytest
    from scripts import scout_topic

    monkeypatch.delenv("SCICLIPS_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SCICLIPS_GEMINI_API_KEY", raising=False)
    with pytest.raises(ts.ScoutError, match="Gemini API key is not configured"):
        scout_topic.make_ask()


def test_scout_switches_to_gemini_when_primary_returns_non_json(monkeypatch):
    from scripts import scout_topic

    monkeypatch.setenv("SCICLIPS_GEMINI_API_KEY", "gemini-token")
    calls = []

    def post(payload, token, timeout=60, url=None):
        calls.append((payload["model"], token, timeout, url))
        if payload["model"] == "gemini-3.8-flash":
            raise RuntimeError("the AI service answered 200 with something that is not JSON: b'OK\\r\\n'")
        return {"choices": [{"message": {"content": '{"title":"recovered"}'}}]}

    monkeypatch.setattr(scout_topic.ai_writer, "_post", post)
    answer = scout_topic.make_ask()([{"role": "user", "content": "test"}])
    assert answer == '{"title":"recovered"}'
    assert len(calls) == 2
    assert calls[0][1] == calls[1][1] == "gemini-token"
    assert calls[0][0] == "gemini-3.8-flash"
    assert calls[1][0] == "gemini-3.5-flash-lite"
    assert calls[1][3] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def test_gemini_model_ids_accept_models_prefix(monkeypatch):
    from scripts import scout_topic

    monkeypatch.setenv("SCICLIPS_GEMINI_API_KEY", "gemini-token")
    monkeypatch.setenv("SCICLIPS_GEMINI_MODEL", "models/gemini-3.8-flash")
    monkeypatch.setenv("SCICLIPS_GEMINI_FALLBACK_MODEL", "models/gemini-3.5-flash-lite")
    calls = []

    def post(payload, token, timeout=60, url=None):
        calls.append(payload["model"])
        return {"choices": [{"message": {"content": '{"title":"ok"}'}}]}

    monkeypatch.setattr(scout_topic.ai_writer, "_post", post)
    assert scout_topic.make_ask()([{"role": "user", "content": "test"}]) == '{"title":"ok"}'
    assert calls == ["gemini-3.8-flash"]


def test_scout_keeps_primary_provider_when_it_works(monkeypatch):
    from scripts import scout_topic

    monkeypatch.setenv("SCICLIPS_GEMINI_API_KEY", "gemini-token")
    calls = []

    def post(payload, token, timeout=60, url=None):
        calls.append((payload["model"], token))
        return {"choices": [{"message": {"content": '{"title":"primary"}'}}]}

    monkeypatch.setattr(scout_topic.ai_writer, "_post", post)
    assert scout_topic.make_ask()([{"role": "user", "content": "test"}]) == '{"title":"primary"}'
    assert calls == [("gemini-3.8-flash", "gemini-token")]

def test_topic_bank_refills_in_bounded_batches_until_target(tmp_path, monkeypatch):
    from scripts import scout_topic
    repo = TEST_SCOUT_make_repo(tmp_path)
    data = json.loads((repo / 'topics' / 'topic_queue.json').read_text())
    data['topics'] = [item for item in data['topics'] if item['status'] == 'queued']
    (repo / 'topics' / 'topic_queue.json').write_text(json.dumps(data))
    calls = []
    def add_one(root, ask, fetch_page, render, tries=4):
        calls.append(tries)
        current = json.loads((Path(root) / 'topics' / 'topic_queue.json').read_text())
        index = len(calls)
        item = {'id': f'reserve-{index}', 'title': f'Reserve topic {index}', 'category': 'physics', 'template': 'principle', 'status': 'queued'}
        current['topics'].append(item)
        (Path(root) / 'topics' / 'topic_queue.json').write_text(json.dumps(current))
        return item['id'], [f'Added {item["id"]}']
    monkeypatch.setattr(scout_topic.topic_scout, 'scout', add_one)
    lines = scout_topic.replenish_topic_bank(repo, lambda _: '', lambda _: '', {}, tries=4)
    assert len(calls) == scout_topic.MAX_TOPICS_PER_RUN == 4
    # The fixture starts with zero queued topics (both seed topics are published),
    # so four successful additions leave four queued topics after this bounded run.
    assert scout_topic.queued_count(repo) == 4
    assert 'added 4 topic(s)' in lines[-2]

def test_topic_bank_does_not_spend_ai_calls_when_above_low_watermark(tmp_path, monkeypatch):
    from scripts import scout_topic
    repo = TEST_SCOUT_make_repo(tmp_path)
    data = json.loads((repo / 'topics' / 'topic_queue.json').read_text())
    for i in range(8):
        data['topics'].append({'id': f'ready-{i}', 'title': f'Ready {i}', 'category': 'physics', 'template': 'principle', 'status': 'queued'})
    (repo / 'topics' / 'topic_queue.json').write_text(json.dumps(data))
    def should_not_run(*args, **kwargs):
        raise AssertionError('AI scout should not run when the bank is healthy')
    monkeypatch.setattr(scout_topic.topic_scout, 'scout', should_not_run)
    lines = scout_topic.replenish_topic_bank(repo, None, None, {})
    assert 'Topic bank healthy' in lines[0]

def test_trusted_source_matching_rejects_lookalike_domains():
    from research.source_collector import domain_tier
    assert domain_tier("https://www.nasa.gov/education") == "preferred"
    assert domain_tier("https://nasa.gov.evil.example/page") == "needs_review"
    assert domain_tier("https://notnasa.gov.com/page") == "needs_review"


def test_download_keeps_two_good_sources_when_one_link_is_dead():
    urls = ["https://www.nasa.gov/a", "https://www.noaa.gov/b", "https://www.acs.org/c"]
    def fetch(url):
        if url == urls[1]:
            raise OSError("404")
        return "Readable science page. " * 100
    pages = ts.download(fetch, urls)
    assert set(pages) == {urls[0], urls[2]}


def test_download_searches_for_trusted_replacements_when_suggested_links_are_dead():
    original = ["https://www.nasa.gov/dead-page", "https://www.rsc.org/dead-page"]
    replacements = ["https://www.usgs.gov/water-science-school/science/water-density",
                    "https://www.noaa.gov/office-education/outreach-communication/hands-on-science-activities/build-a-boat"]
    calls = []
    def fetch(url):
        calls.append(url)
        if url in original:
            raise OSError("404")
        return "Trusted source text with enough readable words. " * 50
    pages = ts.download(fetch, original, search=lambda query: replacements, query="floating and sinking")
    assert set(pages) == set(replacements)
    assert calls[-2:] == replacements


def test_tidy_supplies_required_video_planning_fields_when_ai_omits_them():
    record = base_record()
    record.pop("short_video_potential", None)
    record.pop("long_video_potential", None)
    idea = {"title": "Why do some things float?", "central_question": "Why do some things float?",
            "category": "physics", "template": "principle"}
    tidy = ts.tidy(record, idea, "physics-002", {}, TODAY)
    assert tidy["short_video_potential"]["suitable"] is True
    assert tidy["short_video_potential"]["angle"] == idea["central_question"]
    assert tidy["long_video_potential"]["suitable"] is True
    assert "deeper explanation" in tidy["long_video_potential"]["angle"]


def test_tidy_removes_unlisted_attribution_phrases_from_scriptable_text():
    record = base_record()
    record["scientific_explanation"]["level_3"] = "According to Archimedes' Principle: the buoyant force equals the weight displaced."
    idea = {"title": "Why do objects float?", "central_question": "Why do objects float?",
            "category": "physics", "template": "principle"}
    tidy = ts.tidy(record, idea, "physics-002", {}, TODAY)
    assert "According to" not in tidy["scientific_explanation"]["level_3"]
    assert "the buoyant force equals" in tidy["scientific_explanation"]["level_3"]


def test_claim_verification_accepts_an_exact_quote_from_another_downloaded_source():
    record = {
        "sources": [
            {"id": "s1", "url": "https://www.usgs.gov/a"},
            {"id": "s2", "url": "https://www.noaa.gov/b"},
        ],
        "claims": [{"id": "c1", "text": "Buoyancy is an upward force.", "source_ids": ["s1"]}],
    }
    pages = {
        "https://www.usgs.gov/a": "An unrelated source page with enough words to be read.",
        "https://www.noaa.gov/b": "The buoyant force is equal to the weight of the water displaced by the object in the fluid.",
    }
    def ask(_messages):
        return json.dumps({"results": [{
            "id": "c1", "supported": True, "source_id": "s2",
            "quote": "The buoyant force is equal to the weight of the water displaced by the object in the fluid."
        }]})
    ts.verify_claims(ask, record, pages)
    assert record["claims"][0]["source_ids"] == ["s1", "s2"]


# ---------------------------------------------------------------- self-repair and picture plans
GOOD_PLAN = {"views": {name: {"elements": [
    {"type": "rect", "x": 80, "y": 70, "w": 120, "h": 40, "color": "blue", "alpha": 0.5},
    {"type": "ellipse", "x": 40, "y": 20, "w": 12, "h": 12, "color": "warn", "dy": 40},
    {"type": "text", "x": 80, "y": 10, "text": "Bubbles rise", "appear": 0.4}]} for name in ("intro", "demo", "problem", "result", "explain")}}


class RepairFake(Fake):
    """First draft is missing a required field; the repair request returns the good record."""

    def __init__(self, plan=GOOD_PLAN, **kwargs):
        super().__init__(**kwargs)
        self.broken = base_record()
        self.broken.pop("hazards", None)
        self.plan, self.requests = plan, []

    def ask(self, messages):
        payload = json.loads(messages[1]["content"])
        if "example_view" in payload:
            self.requests.append("plan")
            return json.dumps(self.plan)
        if "problems" in payload:
            self.requests.append("repair:" + payload["problems"])
            return json.dumps(self.record)
        if "example_record" in payload:
            self.requests.append("draft")
            return json.dumps(self.broken)
        return super().ask(messages)


def test_a_draft_the_checks_reject_is_repaired_from_their_own_complaint(tmp_path):
    fake = RepairFake()
    repo, topic_id, lines = go(tmp_path, fake)
    assert topic_id == "chem-002", lines
    assert fake.requests[0] == "draft" and fake.requests[1].startswith("repair:") and "hazards" in fake.requests[1]


def test_a_draft_that_cannot_be_repaired_is_dropped_after_two_repairs(tmp_path):
    class Stubborn(RepairFake):
        def ask(self, messages):
            payload = json.loads(messages[1]["content"])
            if "problems" in payload:
                self.requests.append("repair")
                return json.dumps(self.broken)
            return super().ask(messages)
    fake = Stubborn()
    repo, topic_id, lines = go(tmp_path, fake)
    assert topic_id is None and "hazards" in lines[0]
    assert fake.requests.count("repair") == ts.MAX_REPAIRS


def test_with_pictures_on_the_topic_carries_a_checked_scene_plan(tmp_path):
    fake = RepairFake()
    repo = TEST_SCOUT_make_repo(tmp_path)
    topic_id, lines = ts.scout(repo, fake.ask, fake.fetch, rendering(), today=TODAY, tries=1, pictures=True)
    assert topic_id == "chem-002", lines
    saved = json.loads((repo / "topics" / "records" / "chem-002.json").read_text())
    assert saved["scene_plan"] == GOOD_PLAN


def test_a_topic_without_a_valid_scene_plan_is_dropped_when_pictures_are_required(tmp_path):
    fake = RepairFake(plan={"views": {"demo": {"elements": []}}})
    repo = TEST_SCOUT_make_repo(tmp_path)
    topic_id, lines = ts.scout(repo, fake.ask, fake.fetch, rendering(), today=TODAY, tries=1, pictures=True)
    assert topic_id is None and "picture plan" in lines[0]
    assert not (repo / "topics" / "records" / "chem-002.json").exists()


def test_tidy_never_keeps_a_scene_plan_written_by_the_draft_step():
    record = base_record()
    record["scene_plan"] = GOOD_PLAN
    idea = {"title": "T?", "central_question": "Q?", "category": "physics", "template": "principle"}
    assert "scene_plan" not in ts.tidy(record, idea, "physics-009", {}, TODAY)


def test_a_model_claim_without_a_source_does_not_need_a_page_quote():
    record = {"sources": [{"id": "s1", "url": "https://www.nasa.gov/a"}],
              "claims": [{"id": "c1", "kind": "mathematical_model", "text": "d = v t", "source_ids": []}]}
    ts.verify_claims(lambda _m: json.dumps({"results": []}), record, {"https://www.nasa.gov/a": "x " * 50})
