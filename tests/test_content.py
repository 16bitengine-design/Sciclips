"""tests: merged module (was 5 files: test_ai_writer, test_chemistry, test_stage2, test_stage3, test_stage4).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""



# ============================================================================
# from tests/test_ai_writer.py
# ============================================================================
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
    return json.loads((ROOT / "config" / "config.json").read_text())["rendering"]


def reply(steps):
    return {"choices": [{"message": {"content": json.dumps({"steps": steps})}}]}


class Env:
    """Turns the AI on for one test and puts everything back afterwards."""

    def __init__(self, post):
        self.post, self.saved = post, {}

    def __enter__(self):
        for key, value in (("SCICLIPS_AI", "1"), ("SCICLIPS_GEMINI_API_KEY", "test-token")):
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


def test_a_redirected_post_keeps_its_body_and_arrives(tmp_path):
    import http.server
    import threading
    seen = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            if self.path == "/start":
                self.send_response(307)
                self.send_header("Location", "/final")
                self.end_headers()
                return
            seen["body"], seen["auth"] = json.loads(body), self.headers.get("Authorization")
            data = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        reply = ai_writer._post({"hello": "world"}, "tok", timeout=10, url=f"http://127.0.0.1:{server.server_port}/start")
    finally:
        server.shutdown()
    assert reply["choices"][0]["message"]["content"] == "ok"
    assert seen["body"] == {"hello": "world"} and seen["auth"] == "Bearer tok"


def test_a_reply_that_is_not_json_is_explained():
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>hello</html>")

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        try:
            ai_writer._post({}, "tok", timeout=10, url=f"http://127.0.0.1:{server.server_port}/x")
            assert False
        except RuntimeError as error:
            assert "not JSON" in str(error) and "hello" in str(error)
    finally:
        server.shutdown()



def test_gemini_requests_do_not_receive_github_specific_headers():
    import http.server
    import threading
    seen = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.update({
                "accept": self.headers.get("Accept"),
                "github_version": self.headers.get("X-GitHub-Api-Version"),
                "authorization": self.headers.get("Authorization"),
            })
            body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        response = ai_writer._post(
            {"model": "gemini-3.8-flash"}, "gemini-token", timeout=10,
            url=f"http://127.0.0.1:{server.server_port}/v1beta/openai/chat/completions",
        )
    finally:
        server.shutdown()
    assert response["choices"][0]["message"]["content"] == "ok"
    assert seen["accept"] == "application/json"
    assert seen["github_version"] is None
    assert seen["authorization"] == "Bearer gemini-token"


# ============================================================================
# from tests/test_chemistry.py
# ============================================================================
import copy
import sys
from pathlib import Path

TEST_CHEMISTRY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_CHEMISTRY_ROOT))

from content import topic_manager as tm  # noqa: E402
from research.equation_checker import check_chemical_equation, parse_formula  # noqa: E402
from research.safety_checker import check_safety  # noqa: E402
from research.science_validator import validate_topic_id, validate_topic_science  # noqa: E402


def chem():
    return tm.load_topic_record(str(TEST_CHEMISTRY_ROOT), "chem-001")


def template():
    return tm.load_template(str(TEST_CHEMISTRY_ROOT), "chemistry_experiment")


# --- chemical equations ---------------------------------------------
def test_formula_with_brackets():
    assert parse_formula("Ca(OH)2") == {"Ca": 1, "O": 2, "H": 2}


def test_balanced_equations_pass():
    assert check_chemical_equation("CH3COOH + NaHCO3 -> CH3COONa + H2O + CO2") == []
    assert check_chemical_equation("2H2 + O2 -> 2H2O") == []
    assert check_chemical_equation("3NaHCO3 + C6H8O7 -> Na3C6H5O7 + 3H2O + 3CO2") == []
    assert check_chemical_equation("Ca(OH)2 + 2HCl -> CaCl2 + 2H2O") == []


def test_unbalanced_equation_detected():
    assert check_chemical_equation("H2 + O2 -> H2O")


def test_state_symbols_are_ignored():
    assert check_chemical_equation("2H2(g) + O2(g) -> 2H2O(l)") == []


def test_bad_formula_detected():
    assert check_chemical_equation("Xx9( + O2 -> H2O")


# --- real chemistry topic -------------------------------------------
def test_chemistry_topic_passes():
    result = validate_topic_id(str(TEST_CHEMISTRY_ROOT), "chem-001")
    assert result["status"] == "passed_automated_checks", result
    assert result["human_review_required"] is True


def test_unbalanced_topic_equation_fails():
    rec = chem()
    rec["equations"][0]["equation"] = "CH3COOH + NaHCO3 -> CH3COONa + H2O"
    assert validate_topic_science(rec, template())["status"] == "failed"


# --- safety rules ----------------------------------------------------
def test_blocked_subject_always_fails():
    rec = chem()
    rec["title"] = "How to make an explosive at home"
    assert check_safety(rec)["errors"]


def test_high_hazard_needs_simulation_only():
    rec = chem()
    rec["title"] = "What happens when chlorine is released?"
    assert check_safety(rec)["errors"]


def test_high_hazard_simulation_only_needs_human_review():
    rec = chem()
    rec["title"] = "What happens when chlorine is released?"
    rec["risk_level"] = "high"
    rec["simulation_only"] = True
    rec["supervision_required"] = True
    del rec["procedure_steps"]
    for reagent in rec["reagents"]:
        reagent["hazard_class"] = "high"
    result = check_safety(rec)
    assert result["errors"] == [] and result["needs_approval"]
    assert validate_topic_science(rec, template())["status"] == "needs_human_approval"


def test_high_risk_with_steps_rejected():
    rec = chem()
    rec["risk_level"] = "high"
    rec["simulation_only"] = True
    rec["supervision_required"] = True
    assert tm.validate_topic_record(rec, template())  # procedure_steps still present


def test_reagent_hazard_cannot_exceed_experiment_risk():
    rec = chem()
    rec["reagents"][0]["hazard_class"] = "high"
    assert check_safety(rec)["errors"]


def test_medium_risk_requires_supervision():
    rec = copy.deepcopy(chem())
    rec["risk_level"] = "medium"
    rec["supervision_required"] = False
    assert check_safety(rec)["errors"]


def test_steps_required_unless_simulation_only():
    rec = chem()
    del rec["procedure_steps"]
    assert any("procedure_steps" in e for e in tm.validate_topic_record(rec, template()))


# ============================================================================
# from tests/test_stage2.py
# ============================================================================
import json
import shutil
import sys
from pathlib import Path

TEST_STAGE2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_STAGE2_ROOT / "scripts"))

from validate_config import validate  # noqa: E402
from run_production import plan  # noqa: E402


def make_copy(tmp_path):
    dest = tmp_path / "repo"
    for folder in ("config", "topics", "records"):
        shutil.copytree(TEST_STAGE2_ROOT / folder, dest / folder)
    return dest


def make_test_config(tmp_path):
    """Give planner tests an isolated TEST-mode copy of production config."""
    repo = make_copy(tmp_path)
    path = repo / "config" / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["settings"]["operating_mode"] = "TEST"
    # TEST mode must not advertise automatic publishing as enabled.
    data["settings"]["automatic_publishing_enabled"] = False
    path.write_text(json.dumps(data), encoding="utf-8")
    return repo


def test_real_config_is_valid():
    assert validate(str(TEST_STAGE2_ROOT)) == []


def test_missing_file_is_reported(tmp_path):
    repo = make_copy(tmp_path)
    (repo / "config" / "config.json").unlink()
    assert any("config.json" in p for p in validate(str(repo)))


def test_a_missing_config_section_is_reported(tmp_path):
    repo = make_copy(tmp_path)
    path = repo / "config" / "config.json"
    data = json.loads(path.read_text())
    del data["rendering"]
    path.write_text(json.dumps(data))
    assert any("rendering" in p for p in validate(str(repo)))


def test_broken_json_is_reported(tmp_path):
    repo = make_copy(tmp_path)
    (repo / "topics" / "topic_queue.json").write_text("{ not json")
    assert any("Invalid JSON" in p for p in validate(str(repo)))


def test_paid_service_guard(tmp_path):
    repo = make_copy(tmp_path)
    path = repo / "config" / "config.json"
    data = json.loads(path.read_text())
    data["settings"]["never_switch_to_paid_service"] = False
    path.write_text(json.dumps(data))
    assert any("paid" in p for p in validate(str(repo)))


def test_plan_accepts_good_request(tmp_path):
    repo = make_test_config(tmp_path)
    ok, lines = plan(str(repo), "physics-001", "short", "low", "TEST")
    assert ok


def test_plan_rejects_unknown_topic(tmp_path):
    repo = make_test_config(tmp_path)
    ok, lines = plan(str(repo), "nope-999", "short", "low", "TEST")
    assert not ok and "not found" in lines[0]


def test_plan_refuses_non_test_modes(tmp_path):
    repo = make_test_config(tmp_path)
    for mode in ("APPROVAL", "AUTOMATIC"):
        ok, _ = plan(str(repo), "physics-001", "short", "low", mode)
        assert not ok


# ============================================================================
# from tests/test_stage3.py
# ============================================================================
import copy
import json
import shutil
import sys
from pathlib import Path

TEST_STAGE3_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_STAGE3_ROOT))

from content import topic_manager as tm  # noqa: E402
from research.claim_checker import check_claims  # noqa: E402
from research.equation_checker import check_equations, parse_units  # noqa: E402
from research.science_validator import validate_topic_id, validate_topic_science  # noqa: E402
from research.source_collector import validate_sources  # noqa: E402


def good_record():
    return tm.load_topic_record(str(TEST_STAGE3_ROOT), "physics-001")


def TEST_STAGE3_template():
    return tm.load_template(str(TEST_STAGE3_ROOT), "principle")


def TEST_STAGE3_make_copy(tmp_path):
    dest = tmp_path / "repo"
    for folder in ("config", "topics", "records", "templates"):
        shutil.copytree(TEST_STAGE3_ROOT / folder, dest / folder)

    # Isolate queue tests from both live queue statuses and production history.
    queue_path = dest / "topics" / "topic_queue.json"
    queue = json.loads(queue_path.read_text())
    queue["topics"] = [entry for entry in queue["topics"] if entry["id"] in {"physics-001", "chem-001"}]
    for entry in queue["topics"]:
        entry["status"] = "queued"
    queue_path.write_text(json.dumps(queue, indent=2) + "\n")

    history_path = dest / "records" / "production_history.json"
    history = json.loads(history_path.read_text())
    history["productions"] = []
    history_path.write_text(json.dumps(history, indent=2) + "\n")
    return dest


# --- units -----------------------------------------------------------
def test_units_newton_equals_base_units():
    assert parse_units("N") == parse_units("kg m s^-2")


def test_units_mismatch_detected():
    bad = [{"id": "x", "dimension_check": {"lhs": "N", "rhs": "kg m s^-1"}}]
    assert check_equations(bad)["errors"]


def test_unknown_unit_detected():
    bad = [{"id": "x", "dimension_check": {"lhs": "banana", "rhs": "m"}}]
    assert check_equations(bad)["errors"]


# --- numeric checks --------------------------------------------------
def test_mass_independence_passes():
    eq = good_record()["equations"]
    assert check_equations(eq)["errors"] == []


def test_wrong_expected_value_detected():
    eq = copy.deepcopy(good_record()["equations"])
    eq[2]["numeric_checks"][1]["expected"] = 1.6
    assert check_equations(eq)["errors"]


# --- sources ---------------------------------------------------------
def test_good_sources_pass():
    errors, warnings, ids = validate_sources(good_record()["sources"])
    assert errors == [] and ids == ["s1", "s2", "s3", "s4", "s5"]


def test_source_without_https_fails():
    src = copy.deepcopy(good_record()["sources"])
    src[0]["url"] = "http://example.com"
    assert validate_sources(src)[0]


def test_non_preferred_source_flagged_for_review():
    src = copy.deepcopy(good_record()["sources"])
    src[0]["url"] = "https://someblog.example.com/post"
    assert validate_sources(src)[1]


# --- claims ----------------------------------------------------------
def test_unknown_source_reference_fails():
    claims = [{"id": "c", "kind": "law", "text": "x", "source_ids": ["zzz"]}]
    assert check_claims(claims, ["s1"], [])["errors"]


def test_unsourced_fact_needs_approval():
    claims = [{"id": "c", "kind": "established_fact", "text": "x", "source_ids": []}]
    result = check_claims(claims, ["s1"], [])
    assert result["errors"] == [] and result["needs_approval"]


def test_hypothesis_worded_as_proven_fails():
    claims = [{"id": "c", "kind": "hypothesis", "text": "This is proven.", "source_ids": []}]
    assert check_claims(claims, [], [])["errors"]


def test_theory_called_just_a_guess_fails():
    claims = [{"id": "c", "kind": "theory", "text": "It is just a guess.", "source_ids": ["s1"]}]
    assert check_claims(claims, ["s1"], [])["errors"]


# --- topic records and validator -------------------------------------
def test_real_topic_passes_with_human_review_flag():
    result = validate_topic_id(str(TEST_STAGE3_ROOT), "physics-001")
    assert result["status"] == "passed_automated_checks"
    assert result["human_review_required"] is True


def test_missing_field_fails():
    rec = good_record()
    del rec["assumptions"]
    assert validate_topic_science(rec, TEST_STAGE3_template())["status"] == "failed"


def test_high_risk_experiment_must_be_simulation_only():
    rec = copy.deepcopy(good_record())
    rec["template"] = "experiment"
    rec["risk_level"] = "high"
    rec["simulation_only"] = False
    errors = tm.validate_topic_record(rec, {"required_fields": []})
    assert any("simulation_only" in e for e in errors)


def test_all_templates_exist():
    for name in ("principle", "phenomenon", "experiment", "chemistry_experiment", "theory", "what_if", "engineering", "misconception"):
        assert "required_fields" in tm.load_template(str(TEST_STAGE3_ROOT), name)


# --- queue handling --------------------------------------------------
def test_next_topic_and_status_update(tmp_path):
    repo = TEST_STAGE3_make_copy(tmp_path)
    assert tm.select_next_topic(str(repo))["id"] == "physics-001"
    tm.set_status(str(repo), "physics-001", "researched")
    assert tm.select_next_topic(str(repo))["id"] == "chem-001"
    tm.set_status(str(repo), "chem-001", "researched")
    assert tm.select_next_topic(str(repo)) is None


def test_already_produced_topic_is_skipped(tmp_path):
    repo = TEST_STAGE3_make_copy(tmp_path)
    path = repo / "records" / "production_history.json"
    data = json.loads(path.read_text())
    data["productions"].append({"topic_id": "physics-001"})
    data["productions"].append({"topic_id": "chem-001"})
    path.write_text(json.dumps(data))


    assert tm.select_next_topic(str(repo)) is None


def test_approval_required_blocks_unapproved(tmp_path):
    repo = TEST_STAGE3_make_copy(tmp_path)
    assert tm.select_next_topic(str(repo), require_approval=True) is None


def test_bad_status_rejected(tmp_path):
    repo = TEST_STAGE3_make_copy(tmp_path)
    try:
        tm.set_status(str(repo), "physics-001", "banana")
        assert False, "should have raised"
    except ValueError:
        pass


# ============================================================================
# from tests/test_stage4.py
# ============================================================================
import copy
import json
import sys
from pathlib import Path

TEST_STAGE4_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_STAGE4_ROOT))
sys.path.insert(0, str(TEST_STAGE4_ROOT / "scripts"))

from content.script_generator import (  # noqa: E402
    ScriptError, available_variants, complete_what_if_scenarios, generate_script, script_to_text,
)
from content.script_validator import validate_script, validate_storyboard  # noqa: E402
from content.storyboard_generator import generate_storyboard, split_into_chunks  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from generate_content import run  # noqa: E402
from research.science_validator import validate_topic_id  # noqa: E402

TOPICS = ("physics-001", "chem-001")
TEST_STAGE4_OK_SCIENCE = {"status": "passed_automated_checks"}


def TEST_STAGE4_rendering():
    return json.loads((TEST_STAGE4_ROOT / "config" / "config.json").read_text())["rendering"]


def TEST_STAGE4_record(topic):
    return load_topic_record(str(TEST_STAGE4_ROOT), topic)


def build(topic, fmt, variant, rec=None):
    rec = rec or TEST_STAGE4_record(topic)
    script = generate_script(rec, fmt, variant, TEST_STAGE4_rendering(), TEST_STAGE4_OK_SCIENCE)
    return rec, script, generate_storyboard(script, rec, TEST_STAGE4_rendering())


# --- every topic, format and variant works -----------------------------
def test_all_combinations_validate_without_errors():
    for topic in TOPICS:
        for fmt in ("short", "long"):
            for variant in ("explainer", "what_if"):
                rec, script, board = build(topic, fmt, variant)
                assert validate_script(script, rec, TEST_STAGE4_rendering())["errors"] == [], (topic, fmt, variant)
                assert validate_storyboard(board, script, rec, TEST_STAGE4_rendering())["errors"] == [], (topic, fmt, variant)


def test_short_scripts_fit_the_time_limit():
    for topic in TOPICS:
        for variant in ("explainer", "what_if"):
            _, script, board = build(topic, "short", variant)
            assert script["estimated_duration_seconds"] <= 90
            assert board["total_duration_seconds"] <= 90


def test_narration_is_copied_from_the_record_not_invented():
    rec, script, _ = build("physics-001", "short", "explainer")
    scenario_text = [w[k] for w in rec["what_if_scenarios"] for k in ("correct", "what_changes", "consequences", "why", "prevention")]
    text = " ".join(" ".join(str(x) for x in (list(rec["scientific_explanation"].values())
                                               + rec["supporting_evidence"] + rec["practical_applications"] + scenario_text
                                               + [rec["principle_statement"]])).split())
    shows = [s for s in script["sections"] if s["kind"] == "demonstration"]
    assert shows and all(s["narration"] in text for s in shows)
    long_rec, long_script, _ = build("physics-001", "long", "explainer")
    answer = [s for s in long_script["sections"] if s["kind"] == "answer"][0]
    assert answer["narration"].endswith(long_rec["scientific_explanation"]["level_1"])


def test_short_explainer_shows_instead_of_explaining():
    for topic in TOPICS:
        _, script, board = build(topic, "short", "explainer")
        kinds = [s["kind"] for s in script["sections"]]
        assert kinds.count("demonstration") >= 2
        for gone in ("intro", "answer", "terminology", "equation", "application", "limitation", "sources"):
            assert gone not in kinds, (topic, gone)
        assert any(sc["animation_type"] == "simulation" for sc in board["scenes"])


def test_physics_short_shows_the_why_the_air_effect_and_the_apollo_drop():
    _, script, _ = build("physics-001", "short", "explainer")
    variants = [s["data"]["simulation_variant"] for s in script["sections"] if s["kind"] == "demonstration"]
    assert variants == ["vacuum", "with_air", "vacuum", "air_vs_vacuum", "terminal_speed", "terminal_speed"]


def test_no_video_has_a_sources_scene_but_the_script_still_lists_sources():
    for topic in TOPICS:
        for fmt in ("short", "long"):
            for variant in ("explainer", "what_if"):
                _, script, board = build(topic, fmt, variant)
                assert all(s["kind"] != "sources" for s in script["sections"])
                assert all(sc["section_kind"] != "sources" for sc in board["scenes"])
                assert script["sources"]


def test_a_show_step_that_is_not_in_the_record_is_refused(tmp_path):
    import content.script_generator as gen
    steps = tmp_path / "steps.json"
    steps.write_text(json.dumps({"physics-001": [{"line": "An invented fact."}]}))
    saved = gen.SHOW_STEPS_FILE
    gen.SHOW_STEPS_FILE = steps
    try:
        try:
            generate_script(TEST_STAGE4_record("physics-001"), "short", "explainer", TEST_STAGE4_rendering(), TEST_STAGE4_OK_SCIENCE)
            assert False
        except ScriptError:
            pass
    finally:
        gen.SHOW_STEPS_FILE = saved


def test_what_if_has_all_six_parts_in_order():
    _, script, _ = build("chem-001", "short", "what_if")
    kinds = [s["kind"] for s in script["sections"]]
    parts = ["correct_procedure", "overlooked", "what_changes", "consequences", "why", "prevention"]
    positions = [kinds.index(p) for p in parts]
    assert positions == sorted(positions)


def test_experiment_scripts_include_safety():
    for fmt in ("short", "long"):
        _, script, _ = build("chem-001", fmt, "explainer")
        assert any(s["kind"] == "safety" for s in script["sections"])


def test_all_claims_are_illustrated_in_long_explainer():
    for topic in TOPICS:
        rec, script, _ = build(topic, "long", "explainer")
        assert validate_script(script, rec, TEST_STAGE4_rendering())["warnings"] == [] or all(
            "under the" in w for w in validate_script(script, rec, TEST_STAGE4_rendering())["warnings"])


# --- safety stops --------------------------------------------------------
def test_failed_science_blocks_script():
    try:
        generate_script(TEST_STAGE4_record("physics-001"), "short", "explainer", TEST_STAGE4_rendering(), {"status": "failed"})
        assert False
    except ScriptError:
        pass


def test_unavailable_what_if_is_refused():
    rec = TEST_STAGE4_record("physics-001")
    rec["what_if_scenarios"] = [{"title": "x", "summary": "y"}]
    assert available_variants(rec) == ["explainer"]
    try:
        generate_script(rec, "short", "what_if", TEST_STAGE4_rendering(), TEST_STAGE4_OK_SCIENCE)
        assert False
    except ScriptError:
        pass


def test_overlong_short_script_is_refused():
    rec = TEST_STAGE4_record("physics-001")
    rec["central_question"] = "word " * 400 + "end?"
    try:
        generate_script(rec, "short", "explainer", TEST_STAGE4_rendering(), TEST_STAGE4_OK_SCIENCE)
        assert False
    except ScriptError:
        pass


# --- validators catch problems ---------------------------------------------
def test_validator_catches_missing_section():
    rec, script, _ = build("physics-001", "short", "explainer")
    script["sections"] = [s for s in script["sections"] if s["kind"] != "conclusion"]
    script["word_count"] = sum(len(s["narration"].split()) for s in script["sections"])
    assert any("conclusion" in e for e in validate_script(script, rec, TEST_STAGE4_rendering())["errors"])


def test_validator_catches_unknown_claim():
    rec, script, _ = build("physics-001", "short", "explainer")
    script["sections"][2]["claim_ids"] = ["c99"]
    assert any("c99" in e for e in validate_script(script, rec, TEST_STAGE4_rendering())["errors"])


def test_validator_catches_bad_storyboard():
    rec, script, board = build("physics-001", "short", "explainer")
    board = copy.deepcopy(board)
    board["scenes"][0]["animation_type"] = "magic"
    board["scenes"][1]["scene_number"] = 9
    errors = validate_storyboard(board, script, rec, TEST_STAGE4_rendering())["errors"]
    assert any("magic" in e for e in errors) and any("without gaps" in e for e in errors)


def test_storyboard_layout_matches_format():
    for fmt, aspect in (("short", "9:16"), ("long", "16:9")):
        _, _, board = build("physics-001", fmt, "explainer")
        assert all(sc["layout"]["aspect"] == aspect for sc in board["scenes"])


def test_storyboard_scene_details():
    _, script, board = build("physics-001", "short", "explainer")
    assert [sc["scene_number"] for sc in board["scenes"]] == list(range(1, len(board["scenes"]) + 1))
    assert board["scenes"][0]["transition"] == "fade in"
    assert board["scenes"][-1]["transition"] == "fade out"
    assert all(sc["duration_seconds"] >= 3 for sc in board["scenes"])


def test_chunk_splitting_keeps_all_words():
    text = "One two three. Four five six. Seven eight nine."
    chunks = split_into_chunks(text, 4)
    assert " ".join(chunks) == text and len(chunks) == 3


def test_text_export_lists_sources():
    _, script, _ = build("chem-001", "short", "explainer")
    assert "SOURCES" in script_to_text(script)


def test_complete_scenarios_in_real_records():
    for topic in TOPICS:
        assert len(complete_what_if_scenarios(TEST_STAGE4_record(topic))) == 2


# --- entry point -------------------------------------------------------------
def test_run_writes_files(tmp_path):
    ok, lines = run(str(TEST_STAGE4_ROOT), "chem-001", "both", str(tmp_path))
    assert ok, lines
    names = {p.name for p in (tmp_path / "chem-001").iterdir()}
    assert "short_explainer_script.json" in names and "long_what_if_storyboard.json" in names


def test_run_rejects_unknown_topic(tmp_path):
    ok, lines = run(str(TEST_STAGE4_ROOT), "nope-1", "short", str(tmp_path))
    assert not ok


def test_science_still_passes_after_record_update():
    for topic in TOPICS:
        assert validate_topic_id(str(TEST_STAGE4_ROOT), topic)["status"] == "passed_automated_checks"


def test_slower_voice_profiles_make_the_estimate_longer():
    import copy
    fast, slow = copy.deepcopy(TEST_STAGE4_rendering()), copy.deepcopy(TEST_STAGE4_rendering())
    fast["narration"]["profile"], slow["narration"]["profile"] = "smooth_american", "deep_american"
    fast["narration"]["speaking_speed"], slow["narration"]["speaking_speed"] = 1.0, 0.8
    rec = TEST_STAGE4_record("chem-001")
    quick = generate_script(rec, "short", "what_if", fast, TEST_STAGE4_OK_SCIENCE)
    slowly = generate_script(rec, "short", "what_if", slow, TEST_STAGE4_OK_SCIENCE)
    assert slowly["estimated_duration_seconds"] > quick["estimated_duration_seconds"]


def test_estimates_include_the_pause_after_every_scene():
    rec = TEST_STAGE4_record("chem-001")
    script = generate_script(rec, "short", "what_if", TEST_STAGE4_rendering(), TEST_STAGE4_OK_SCIENCE)
    from content.script_generator import SCENE_PADDING_SECONDS, effective_speed
    speaking = script["word_count"] / (2.5 * effective_speed(TEST_STAGE4_rendering()))
    assert script["estimated_duration_seconds"] >= speaking + SCENE_PADDING_SECONDS * len(script["sections"]) - 1


def test_short_scripts_finish_a_little_under_the_limit():
    for topic in ("physics-001", "chem-001"):
        for variant in ("explainer", "what_if"):
            rec = TEST_STAGE4_record(topic)
            script = generate_script(rec, "short", variant, TEST_STAGE4_rendering(), TEST_STAGE4_OK_SCIENCE)
            assert script["estimated_duration_seconds"] <= 90 - 2.0 + 0.05


# --- house voice: no source language in videos, credit people only when the record lists them ------
def test_no_video_talks_about_sources():
    from content.script_validator import check_house_voice
    for topic in TOPICS:
        for fmt in ("short", "long"):
            for variant in ("explainer", "what_if"):
                rec, script, _ = build(topic, fmt, variant)
                assert check_house_voice(script, rec) == [], (topic, fmt, variant)


def test_source_language_is_caught():
    from content.script_validator import check_house_voice
    rec, script, _ = build("physics-001", "short", "explainer")
    for bad in ("NASA describes the Moon as dry.", "Sources are listed below.", "Research shows this is true."):
        script["sections"][1]["narration"] = bad
        assert check_house_voice(script, rec), bad


def test_a_person_is_credited_only_when_the_record_lists_them():
    from content.script_validator import check_house_voice
    rec = TEST_STAGE4_record("physics-001")
    line = "Take the air away and they fall together."
    rec["attributions"] = [{"line": line, "by": "Galileo Galilei"}]
    script = generate_script(rec, "short", "explainer", TEST_STAGE4_rendering(), TEST_STAGE4_OK_SCIENCE)
    spoken = [s["narration"] for s in script["sections"] if "Galileo" in s["narration"]]
    assert spoken == ["According to Galileo Galilei: " + line]
    assert check_house_voice(script, rec) == []
    rec["attributions"] = []
    assert check_house_voice(script, rec)
