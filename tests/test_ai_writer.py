import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from content import ai_writer  # noqa: E402
from content import script_generator as gen  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402

OK_SCIENCE = {"status": "passed_automated_checks"}
VARIANTS = ai_writer.SIM_VARIANTS["free_fall"]


def record():
    return load_topic_record(str(ROOT), "physics-001")


def rendering():
    return json.loads((ROOT / "config" / "rendering.json").read_text())


def reply(steps):
    return {"choices": [{"message": {"content": json.dumps({"steps": steps})}}]}


class Env:
    """Turns the AI on for one test and puts everything back afterwards."""

    def __init__(self, post):
        self.post, self.saved = post, {}

    def __enter__(self):
        for key, value in (("SCICLIPS_AI", "1"), ("GITHUB_TOKEN", "test-token")):
            self.saved[key] = os.environ.get(key)
            os.environ[key] = value
        self.old_post = ai_writer._post
        ai_writer._post = self.post
        return self

    def __exit__(self, *exc):
        ai_writer._post = self.old_post
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def good_steps(rec):
    sentences = ai_writer.sentences_of(gen._reusable_text(rec))
    by_start = {s.split()[0] + s.split()[1]: s for s in sentences}
    assert len(sentences) > 6
    return [{"line": sentences[i], "picture": p} for i, p in ((0, "vacuum"), (1, "with_air"), (2, "vacuum"), (3, "terminal_speed"))]


def test_the_ai_is_off_by_default():
    os.environ.pop("SCICLIPS_AI", None)
    assert not ai_writer.ai_enabled()


def test_a_good_answer_is_accepted():
    rec = record()
    steps = good_steps(rec)
    with Env(lambda payload, token, timeout=60: reply(steps)):
        got = ai_writer.propose_steps(rec, gen._reusable_text(rec), "free_fall")
    assert [s["line"] for s in got] == [s["line"] for s in steps]
    assert got[3]["variant"] == "terminal_speed"


def test_an_answer_in_code_fences_is_accepted():
    rec = record()
    text = "```json\n" + json.dumps({"steps": good_steps(rec)}) + "\n```"
    with Env(lambda payload, token, timeout=60: {"choices": [{"message": {"content": text}}]}):
        assert ai_writer.propose_steps(rec, gen._reusable_text(rec), "free_fall")


def test_an_invented_line_is_refused():
    rec = record()
    steps = good_steps(rec)
    steps[1]["line"] = "Feathers are secretly lighter than air."
    with Env(lambda payload, token, timeout=60: reply(steps)):
        assert ai_writer.propose_steps(rec, gen._reusable_text(rec), "free_fall") is None


def test_an_unknown_picture_is_refused():
    rec = record()
    steps = good_steps(rec)
    steps[0]["picture"] = "magic"
    with Env(lambda payload, token, timeout=60: reply(steps)):
        assert ai_writer.propose_steps(rec, gen._reusable_text(rec), "free_fall") is None


def test_too_few_or_repeated_lines_are_refused():
    rec = record()
    steps = good_steps(rec)
    with Env(lambda payload, token, timeout=60: reply(steps[:2])):
        assert ai_writer.propose_steps(rec, gen._reusable_text(rec), "free_fall") is None
    steps[1] = dict(steps[0])
    with Env(lambda payload, token, timeout=60: reply(steps)):
        assert ai_writer.propose_steps(rec, gen._reusable_text(rec), "free_fall") is None


def test_a_network_failure_never_raises():
    def broken(payload, token, timeout=60):
        raise OSError("no network")
    rec = record()
    with Env(broken):
        assert ai_writer.propose_steps(rec, gen._reusable_text(rec), "free_fall") is None


def test_the_request_only_offers_record_sentences_and_known_pictures():
    rec = record()
    seen = {}

    def spy(payload, token, timeout=60):
        seen.update(payload)
        return reply(good_steps(rec))
    with Env(spy):
        ai_writer.propose_steps(rec, gen._reusable_text(rec), "free_fall")
    prompt = json.loads(seen["messages"][1]["content"])
    assert set(prompt["pictures"]) == set(VARIANTS)
    assert all(line in gen._reusable_text(rec) for line in prompt["allowed_lines"])


def test_a_video_is_made_from_the_ai_plan_when_it_is_good():
    rec = record()
    steps = good_steps(rec)
    saved = gen.SHOW_STEPS_FILE
    gen.SHOW_STEPS_FILE = ROOT / "config" / "no_such_file.json"
    try:
        with Env(lambda payload, token, timeout=60: reply(steps)):
            script = gen.generate_script(rec, "short", "explainer", rendering(), OK_SCIENCE)
    finally:
        gen.SHOW_STEPS_FILE = saved
    shows = [s for s in script["sections"] if s["kind"] == "demonstration"]
    assert [s["data"]["simulation_variant"] for s in shows] == ["vacuum", "with_air", "vacuum", "terminal_speed"]


def test_a_video_is_still_made_when_the_ai_fails():
    def broken(payload, token, timeout=60):
        raise OSError("no network")
    rec = record()
    saved = gen.SHOW_STEPS_FILE
    gen.SHOW_STEPS_FILE = ROOT / "config" / "no_such_file.json"
    try:
        with Env(broken):
            script = gen.generate_script(rec, "short", "explainer", rendering(), OK_SCIENCE)
    finally:
        gen.SHOW_STEPS_FILE = saved
    assert any(s["kind"] == "demonstration" for s in script["sections"])
