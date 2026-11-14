import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import auto_run  # noqa: E402
from publishing.zernio import Zernio, ZernioError  # noqa: E402

NOW = datetime(2026, 11, 15, 14, 0, tzinfo=timezone.utc)
TITLES = {t: json.loads((ROOT / "topics" / "records" / f"{t}.json").read_text())["title"] for t in ("physics-001", "chem-001")}


def make_repo(tmp_path, **config):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "topics" / "records").mkdir(parents=True)
    (repo / "records").mkdir()
    for topic in ("physics-001", "chem-001"):
        shutil.copy(ROOT / "topics" / "records" / f"{topic}.json", repo / "topics" / "records" / f"{topic}.json")
    shutil.copy(ROOT / "topics" / "topic_queue.json", repo / "topics" / "topic_queue.json")
    (repo / "topics" / "approved_topics.json").write_text('{"approved_topic_ids": []}')
    (repo / "records" / "production_history.json").write_text('{"productions": []}')
    settings = {"enabled": True, "dry_run": False, "videos_per_day": 1, "pause_after_failures": 3,
                "max_attempts_per_topic": 2}
    settings.update(config)
    (repo / "config" / "automation.json").write_text(json.dumps(settings))
    return repo


from publishing.buffer_cloudinary import Buffer, BufferPublisher, Cloudinary, PublishError  # noqa: E402


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
            raise ZernioError("boom")
        result = {"youtube": "https://youtu.be/abc", "tiktok": "https://tiktok.com/x", "failed": {}}
        if self.partial:
            result = {"youtube": "https://youtu.be/abc", "failed": {"tiktok": "capacity"}}
        return result


def run(repo, producer=None, client=None, now=NOW):
    client = client or FakeClient()
    return auto_run.run(str(repo), now=now, producer=producer or good_producer(),
                        publisher=lambda root, env, cfg: (client, {"youtube": "yt1", "tiktok": "tt1"}),
                        env={"OUTPUT_DIR": str(repo / "output")}), client


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
    assert code == 0 and client.calls == [] and "limit" in lines[0]
    tomorrow = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)
    (code, lines), client = run(repo, now=tomorrow)
    assert client.calls[0][1] == TITLES["chem-001"]
    (code, lines), client = run(repo, now=datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc))
    assert client.calls == [] and "No topic" in lines[0]


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


# --- Zernio -------------------------------------------------------------------------------
class FakeNet:
    def __init__(self, post_reply=None, put_status=200):
        self.requests, self.post_reply, self.put_status = [], post_reply, put_status

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, headers, body))
        if url.endswith("/media/presign"):
            return 200, json.dumps({"uploadUrl": "https://upload.example/x", "publicUrl": "https://cdn.example/v.mp4"}).encode()
        if method == "PUT":
            return self.put_status, b""
        if url.endswith("/posts"):
            reply = self.post_reply or {"post": {"platforms": [
                {"platform": "youtube", "status": "published", "platformPostUrl": "https://youtu.be/1"},
                {"platform": "tiktok", "status": "published", "platformPostUrl": "https://tiktok.com/1"}]}}
            return 200, json.dumps(reply).encode()
        return 404, b"{}"


def test_zernio_uploads_then_posts_with_the_documented_fields(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    net = FakeNet()
    result = Zernio("sk_test", transport=net).publish_video(video, "T" * 150, "desc", "cap", {"youtube": "y", "tiktok": "t"}, ["a"])
    assert result["youtube"] == "https://youtu.be/1" and result["tiktok"].endswith("/1")
    post = json.loads([r for r in net.requests if r[1].endswith("/posts")][0][3])
    assert post["publishNow"] is True and post["mediaItems"] == [{"type": "video", "url": "https://cdn.example/v.mp4"}]
    youtube = post["platforms"][0]["platformSpecificData"]
    assert len(youtube["title"]) == 100 and youtube["containsSyntheticMedia"] is True
    assert post["tiktokSettings"]["content_preview_confirmed"] and post["tiktokSettings"]["express_consent_given"]
    assert [r[0] for r in net.requests] == ["POST", "PUT", "POST"]


def test_zernio_reports_failures_clearly(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    for net in (FakeNet(put_status=500), FakeNet(post_reply={"post": {"platforms": [{"platform": "youtube", "status": "failed", "error": "quota"}]}})):
        try:
            Zernio("sk_test", transport=net).publish_video(video, "t", "d", "c", {"youtube": "y"})
            assert False
        except ZernioError:
            pass


def test_zernio_needs_an_api_key():
    import os
    saved = os.environ.pop("ZERNIO_API_KEY", None)
    try:
        Zernio(None)
        assert False
    except ZernioError:
        pass
    finally:
        if saved:
            os.environ["ZERNIO_API_KEY"] = saved


# --- Buffer and Cloudinary --------------------------------------------------------------------
class FakeBufferNet:
    def __init__(self, buffer_reply=None, cloud_status=200):
        self.requests, self.buffer_reply, self.cloud_status = [], buffer_reply, cloud_status

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, headers, body))
        if "cloudinary.com" in url:
            if self.cloud_status >= 400:
                return self.cloud_status, json.dumps({"error": {"message": "Invalid signature"}}).encode()
            return 200, json.dumps({"secure_url": "https://res.cloudinary.com/demo/video/upload/v1/sciclips/x.mp4"}).encode()
        query = json.loads(body)["query"]
        if "organizations" in query:
            return 200, json.dumps({"data": {"account": {"organizations": [{"id": "org1"}]}}}).encode()
        if "channels(" in query:
            return 200, json.dumps({"data": {"channels": [{"id": "c_yt", "service": "youtube"}, {"id": "c_tt", "service": "tiktok"}]}}).encode()
        reply = self.buffer_reply or {"data": {"createPost": {"post": {"id": "p1"}}}}
        return 200, json.dumps(reply).encode()


def make_publisher(net):
    return BufferPublisher(Buffer("key", transport=net), Cloudinary("cloudinary://k:s@demo", transport=net, clock=lambda: 1700000000))


def test_buffer_publisher_uploads_once_then_posts_to_each_channel(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    net = FakeBufferNet()
    result = make_publisher(net).publish_video(video, "T" * 150, "Long description", "Short caption",
                                               {"youtube": "c_yt", "tiktok": "c_tt"}, [], False)
    assert result["youtube"] == "Buffer post p1" and result["tiktok"] == "Buffer post p1" and result["failed"] == {}
    posts = [json.loads(r[3])["query"] for r in net.requests if r[1] == "https://api.buffer.com"]
    assert len(posts) == 2 and sum("cloudinary" in r[1] for r in net.requests) == 1
    youtube, tiktok = posts
    assert "https://res.cloudinary.com/demo/video/upload/v1/sciclips/x.mp4" in youtube
    assert "schedulingType: automatic" in youtube and "mode: shareNow" in youtube
    assert "isAiGenerated: true" in youtube and "madeForKids: false" in youtube and 'categoryId: "28"' in youtube
    assert ("T" * 100) in youtube and ("T" * 101) not in youtube
    assert "metadata" not in tiktok and "Short caption" in tiktok


def test_cloudinary_request_is_signed_the_documented_way(tmp_path):
    import hashlib
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    net = FakeBufferNet()
    Cloudinary("cloudinary://k:s@demo", transport=net, clock=lambda: 1700000000).upload_video(video, "sciclips/v")
    method, url, headers, body = net.requests[0]
    assert url == "https://api.cloudinary.com/v1_1/demo/video/upload" and "boundary=" in headers["Content-Type"]
    expected = hashlib.sha1(b"overwrite=true&public_id=sciclips/v&timestamp=1700000000s").hexdigest()
    assert expected.encode() in body and b'name="api_key"' in body and b"data" in body


def test_buffer_finds_the_channels_when_ids_are_not_given():
    assert Buffer("key", transport=FakeBufferNet()).find_channels() == {"youtube": "c_yt", "tiktok": "c_tt"}


def test_one_channel_failing_still_counts_and_is_reported(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")

    class Half(FakeBufferNet):
        def __call__(self, method, url, headers, body):
            if "tiktok" in str(body) or "c_tt" in str(body):
                return 200, json.dumps({"data": {"createPost": {"message": "TikTok is at capacity"}}}).encode()
            return super().__call__(method, url, headers, body)
    result = make_publisher(Half()).publish_video(video, "t", "d", "c", {"youtube": "c_yt", "tiktok": "c_tt"})
    assert result["youtube"] and "capacity" in result["failed"]["tiktok"]


def test_buffer_and_cloudinary_failures_are_clear(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    for net in (FakeBufferNet(cloud_status=401), FakeBufferNet(buffer_reply={"data": {"createPost": {"message": "No"}}})):
        try:
            make_publisher(net).publish_video(video, "t", "d", "c", {"youtube": "c_yt"})
            assert False
        except PublishError:
            pass
    import os
    saved = {k: os.environ.pop(k, None) for k in ("BUFFER_API_KEY", "CLOUDINARY_URL")}
    try:
        for build in (lambda: Cloudinary(""), lambda: Buffer("")):
            try:
                build()
                assert False
            except PublishError:
                pass
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
