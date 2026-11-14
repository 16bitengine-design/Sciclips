import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from content.script_generator import (  # noqa: E402
    ScriptError, available_variants, complete_what_if_scenarios, generate_script, script_to_text,
)
from content.script_validator import validate_script, validate_storyboard  # noqa: E402
from content.storyboard_generator import generate_storyboard, split_into_chunks  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from generate_content import run  # noqa: E402
from research.science_validator import validate_topic_id  # noqa: E402

TOPICS = ("physics-001", "chem-001")
OK_SCIENCE = {"status": "passed_automated_checks"}


def rendering():
    return json.loads((ROOT / "config" / "rendering.json").read_text())


def record(topic):
    return load_topic_record(str(ROOT), topic)


def build(topic, fmt, variant, rec=None):
    rec = rec or record(topic)
    script = generate_script(rec, fmt, variant, rendering(), OK_SCIENCE)
    return rec, script, generate_storyboard(script, rec, rendering())


# --- every topic, format and variant works -----------------------------
def test_all_combinations_validate_without_errors():
    for topic in TOPICS:
        for fmt in ("short", "long"):
            for variant in ("explainer", "what_if"):
                rec, script, board = build(topic, fmt, variant)
                assert validate_script(script, rec, rendering())["errors"] == [], (topic, fmt, variant)
                assert validate_storyboard(board, script, rec, rendering())["errors"] == [], (topic, fmt, variant)


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
            generate_script(record("physics-001"), "short", "explainer", rendering(), OK_SCIENCE)
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
        assert validate_script(script, rec, rendering())["warnings"] == [] or all(
            "under the" in w for w in validate_script(script, rec, rendering())["warnings"])


# --- safety stops --------------------------------------------------------
def test_failed_science_blocks_script():
    try:
        generate_script(record("physics-001"), "short", "explainer", rendering(), {"status": "failed"})
        assert False
    except ScriptError:
        pass


def test_unavailable_what_if_is_refused():
    rec = record("physics-001")
    rec["what_if_scenarios"] = [{"title": "x", "summary": "y"}]
    assert available_variants(rec) == ["explainer"]
    try:
        generate_script(rec, "short", "what_if", rendering(), OK_SCIENCE)
        assert False
    except ScriptError:
        pass


def test_overlong_short_script_is_refused():
    rec = record("physics-001")
    rec["central_question"] = "word " * 400 + "end?"
    try:
        generate_script(rec, "short", "explainer", rendering(), OK_SCIENCE)
        assert False
    except ScriptError:
        pass


# --- validators catch problems ---------------------------------------------
def test_validator_catches_missing_section():
    rec, script, _ = build("physics-001", "short", "explainer")
    script["sections"] = [s for s in script["sections"] if s["kind"] != "conclusion"]
    script["word_count"] = sum(len(s["narration"].split()) for s in script["sections"])
    assert any("conclusion" in e for e in validate_script(script, rec, rendering())["errors"])


def test_validator_catches_unknown_claim():
    rec, script, _ = build("physics-001", "short", "explainer")
    script["sections"][2]["claim_ids"] = ["c99"]
    assert any("c99" in e for e in validate_script(script, rec, rendering())["errors"])


def test_validator_catches_bad_storyboard():
    rec, script, board = build("physics-001", "short", "explainer")
    board = copy.deepcopy(board)
    board["scenes"][0]["animation_type"] = "magic"
    board["scenes"][1]["scene_number"] = 9
    errors = validate_storyboard(board, script, rec, rendering())["errors"]
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
        assert len(complete_what_if_scenarios(record(topic))) == 2


# --- entry point -------------------------------------------------------------
def test_run_writes_files(tmp_path):
    ok, lines = run(str(ROOT), "chem-001", "both", str(tmp_path))
    assert ok, lines
    names = {p.name for p in (tmp_path / "chem-001").iterdir()}
    assert "short_explainer_script.json" in names and "long_what_if_storyboard.json" in names


def test_run_rejects_unknown_topic(tmp_path):
    ok, lines = run(str(ROOT), "nope-1", "short", str(tmp_path))
    assert not ok


def test_science_still_passes_after_record_update():
    for topic in TOPICS:
        assert validate_topic_id(str(ROOT), topic)["status"] == "passed_automated_checks"


def test_slower_voice_profiles_make_the_estimate_longer():
    import copy
    fast, slow = copy.deepcopy(rendering()), copy.deepcopy(rendering())
    fast["narration"]["profile"], slow["narration"]["profile"] = "smooth_american", "deep_american"
    fast["narration"]["speaking_speed"], slow["narration"]["speaking_speed"] = 1.0, 0.8
    rec = record("chem-001")
    quick = generate_script(rec, "short", "what_if", fast, OK_SCIENCE)
    slowly = generate_script(rec, "short", "what_if", slow, OK_SCIENCE)
    assert slowly["estimated_duration_seconds"] > quick["estimated_duration_seconds"]


def test_estimates_include_the_pause_after_every_scene():
    rec = record("chem-001")
    script = generate_script(rec, "short", "what_if", rendering(), OK_SCIENCE)
    from content.script_generator import SCENE_PADDING_SECONDS, effective_speed
    speaking = script["word_count"] / (2.5 * effective_speed(rendering()))
    assert script["estimated_duration_seconds"] >= speaking + SCENE_PADDING_SECONDS * len(script["sections"]) - 1


def test_short_scripts_finish_a_little_under_the_limit():
    for topic in ("physics-001", "chem-001"):
        for variant in ("explainer", "what_if"):
            rec = record(topic)
            script = generate_script(rec, "short", variant, rendering(), OK_SCIENCE)
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
    rec = record("physics-001")
    line = "Take the air away and they fall together."
    rec["attributions"] = [{"line": line, "by": "Galileo Galilei"}]
    script = generate_script(rec, "short", "explainer", rendering(), OK_SCIENCE)
    spoken = [s["narration"] for s in script["sections"] if "Galileo" in s["narration"]]
    assert spoken == ["According to Galileo Galilei: " + line]
    assert check_house_voice(script, rec) == []
    rec["attributions"] = []
    assert check_house_voice(script, rec)

