"""Coarse automatic safety screening for topic records.

This is a safety NET, not a safety expert. A keyword list cannot judge real
risk. It exists to stop obviously unsuitable material and to force human
review of anything hazardous. Dangerous chemistry is shown only as a
simulation (animation), never as instructions to copy.
"""

RISK_RANK = {"low": 0, "medium": 1, "high": 2}

# Never produced, in any form.
BLOCKED_TERMS = (
    "explosive", "detonat", "bomb", "nerve agent", "sarin", "mustard gas",
    "ricin", "napalm", "methamphetamine", "fentanyl",
)

# Allowed only as a high-risk, simulation-only topic with no procedure steps.
HIGH_HAZARD_TERMS = (
    "toxic gas", "chlorine", "chloramine", "thermite", "sodium metal",
    "potassium metal", "lithium metal", "hydrofluoric", "cyanide",
    "mercury", "white phosphorus", "concentrated acid",
)


def _text_to_scan(record):
    parts = [record.get("title", ""), record.get("central_question", "")]
    for key in ("procedure_steps", "expected_results"):
        value = record.get(key) or []
        parts += [str(v) for v in value]
    for reagent in record.get("reagents") or []:
        if isinstance(reagent, dict):
            parts += [str(reagent.get("name", "")), str(reagent.get("formula", ""))]
    return " ".join(parts).lower()


def check_safety(record):
    """Returns {"errors": [...], "needs_approval": [...]}."""
    errors, needs_approval = [], []
    text = _text_to_scan(record)

    for term in BLOCKED_TERMS:
        if term in text:
            errors.append(f"Blocked subject ('{term}'): this project does not produce this content.")

    risk = record.get("risk_level")
    sim_only = record.get("simulation_only") is True
    has_steps = bool(record.get("procedure_steps"))

    hazard_hits = [t for t in HIGH_HAZARD_TERMS if t in text]
    if hazard_hits:
        if risk == "high" and sim_only and not has_steps:
            needs_approval.append(
                f"High-hazard subject ({', '.join(hazard_hits)}): simulation only, human safety review required."
            )
        else:
            errors.append(
                f"High-hazard subject ({', '.join(hazard_hits)}) must have risk_level 'high', "
                "simulation_only true and no procedure_steps."
            )

    template = record.get("template", "")
    if template in ("experiment", "chemistry_experiment"):
        if risk in ("medium", "high"):
            needs_approval.append(f"Risk level '{risk}': human safety review required.")
            if record.get("supervision_required") is not True:
                errors.append("Medium or high risk experiments need supervision_required true.")
        for reagent in record.get("reagents") or []:
            if not isinstance(reagent, dict):
                errors.append("Each reagent must be an object.")
                continue
            hazard = reagent.get("hazard_class")
            if hazard not in RISK_RANK:
                errors.append(f"Reagent {reagent.get('name', '?')}: hazard_class must be low, medium or high.")
            elif risk in RISK_RANK and RISK_RANK[hazard] > RISK_RANK[risk]:
                errors.append(
                    f"Reagent {reagent.get('name', '?')} is '{hazard}' hazard but the experiment risk_level is '{risk}'."
                )
    return {"errors": errors, "needs_approval": needs_approval}
