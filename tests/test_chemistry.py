import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from content import topic_manager as tm  # noqa: E402
from research.equation_checker import check_chemical_equation, parse_formula  # noqa: E402
from research.safety_checker import check_safety  # noqa: E402
from research.science_validator import validate_topic_id, validate_topic_science  # noqa: E402


def chem():
    return tm.load_topic_record(str(ROOT), "chem-001")


def template():
    return tm.load_template(str(ROOT), "chemistry_experiment")


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
    result = validate_topic_id(str(ROOT), "chem-001")
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
