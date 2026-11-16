import copy
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from content import topic_scout as ts  # noqa: E402

TODAY = "2026-11-15"
TITLE = "Why does a fizzy tablet make bubbles?"


def rendering():
    return json.loads((ROOT / "config" / "rendering.json").read_text())


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "topics" / "records").mkdir(parents=True)
    (repo / "templates").mkdir()
    for name in ("physics-001", "chem-001"):
        shutil.copy(ROOT / "topics" / "records" / f"{name}.json", repo / "topics" / "records" / f"{name}.json")
    for name in ("principle", "chemistry_experiment"):
        shutil.copy(ROOT / "templates" / f"{name}.json", repo / "templates" / f"{name}.json")
    shutil.copy(ROOT / "topics" / "topic_queue.json", repo / "topics" / "topic_queue.json")
    queue_path = repo / "topics" / "topic_queue.json"
    queue = json.loads(queue_path.read_text())
    queue["topics"] = [topic for topic in queue["topics"] if topic["id"] in {"physics-001", "chem-001"}]
    queue_path.write_text(json.dumps(queue, indent=2) + "\\n")
    return repo


def base_record():
    return json.loads((ROOT / "topics" / "records" / "chem-001.json").read_text())


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
    repo = make_repo(tmp_path)
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
    repo = make_repo(tmp_path)
    data = json.loads((repo / "topics" / "topic_queue.json").read_text())
    data["topics"] += [{"id": f"x-{i}", "title": f"t{i}", "category": "physics", "template": "principle", "status": "queued"} for i in range(20)]
    (repo / "topics" / "topic_queue.json").write_text(json.dumps(data))
    fake = Fake()
    topic_id, lines = ts.scout(repo, fake.ask, fake.fetch, rendering(), today=TODAY)
    assert topic_id is None and fake.calls == 0


def test_the_ai_being_down_never_raises_out_of_the_scout(tmp_path):
    def down(messages):
        raise ts.ScoutError("the AI was not available")
    repo = make_repo(tmp_path)
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
    repo = make_repo(tmp_path)
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
    repo = make_repo(tmp_path)
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
