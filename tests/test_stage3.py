import copy
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from content import topic_manager as tm  # noqa: E402
from research.claim_checker import check_claims  # noqa: E402
from research.equation_checker import check_equations, parse_units  # noqa: E402
from research.science_validator import validate_topic_id, validate_topic_science  # noqa: E402
from research.source_collector import validate_sources  # noqa: E402


def good_record():
    return tm.load_topic_record(str(ROOT), "physics-001")


def template():
    return tm.load_template(str(ROOT), "principle")


def make_copy(tmp_path):
    dest = tmp_path / "repo"
    for folder in ("config", "topics", "records", "templates"):
        shutil.copytree(ROOT / folder, dest / folder)
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
    assert errors == [] and ids == ["s1", "s2", "s3"]


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
    result = validate_topic_id(str(ROOT), "physics-001")
    assert result["status"] == "passed_automated_checks"
    assert result["human_review_required"] is True


def test_missing_field_fails():
    rec = good_record()
    del rec["assumptions"]
    assert validate_topic_science(rec, template())["status"] == "failed"


def test_high_risk_experiment_must_be_simulation_only():
    rec = copy.deepcopy(good_record())
    rec["template"] = "experiment"
    rec["risk_level"] = "high"
    rec["simulation_only"] = False
    errors = tm.validate_topic_record(rec, {"required_fields": []})
    assert any("simulation_only" in e for e in errors)


def test_all_templates_exist():
    for name in ("principle", "phenomenon", "experiment", "chemistry_experiment", "theory", "what_if", "engineering", "misconception"):
        assert "required_fields" in tm.load_template(str(ROOT), name)


# --- queue handling --------------------------------------------------
def test_next_topic_and_status_update(tmp_path):
    repo = make_copy(tmp_path)
    assert tm.select_next_topic(str(repo))["id"] == "physics-001"
    tm.set_status(str(repo), "physics-001", "researched")
    assert tm.select_next_topic(str(repo))["id"] == "chem-001"
    tm.set_status(str(repo), "chem-001", "researched")
    assert tm.select_next_topic(str(repo)) is None


def test_already_produced_topic_is_skipped(tmp_path):
    repo = make_copy(tmp_path)
    path = repo / "records" / "production_history.json"
    data = json.loads(path.read_text())
    data["productions"].append({"topic_id": "physics-001"})
    data["productions"].append({"topic_id": "chem-001"})
    path.write_text(json.dumps(data))
    assert tm.select_next_topic(str(repo)) is None


def test_approval_required_blocks_unapproved(tmp_path):
    repo = make_copy(tmp_path)
    assert tm.select_next_topic(str(repo), require_approval=True) is None


def test_bad_status_rejected(tmp_path):
    repo = make_copy(tmp_path)
    try:
        tm.set_status(str(repo), "physics-001", "banana")
        assert False, "should have raised"
    except ValueError:
        pass
