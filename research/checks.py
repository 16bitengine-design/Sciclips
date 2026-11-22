"""research: merged module (was 5 files: claim_checker, equation_checker, safety_checker, source_collector, science_validator).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))



# ============================================================================
# from research/claim_checker.py
# ============================================================================
# Checks that each scientific claim is labelled, worded and sourced properly.


KINDS = (
    "established_fact", "law", "theory", "hypothesis", "mathematical_model",
    "experimental_observation", "prediction", "speculation",
)
NEEDS_SOURCE = ("established_fact", "law", "theory", "experimental_observation")
UNCERTAIN_KINDS = ("hypothesis", "prediction", "speculation")

OVERCONFIDENT = ("proven", "proves", "proved", "definitely", "certainly", "undeniable")
BELITTLING_THEORY = ("just a theory", "only a theory", "merely a theory", "just a guess")


def _contains_word(text, word):
    return re.search(r"\b" + re.escape(word) + r"\b", text.lower()) is not None


def check_claims(claims, source_ids, equation_ids):
    """Returns {"errors": [...], "needs_approval": [...]}."""
    errors, needs_approval = [], []
    if not claims:
        return {"errors": ["No claims recorded."], "needs_approval": []}

    seen = set()
    for claim in claims:
        cid = claim.get("id", "?")
        text = claim.get("text", "")
        kind = claim.get("kind")
        if cid in seen:
            errors.append(f"Claim {cid}: duplicate id.")
        seen.add(cid)
        if not text:
            errors.append(f"Claim {cid}: no text.")
        if kind not in KINDS:
            errors.append(f"Claim {cid}: unknown kind '{kind}'.")
            continue

        for sid in claim.get("source_ids", []):
            if sid not in source_ids:
                errors.append(f"Claim {cid}: refers to unknown source '{sid}'.")
        for eid in claim.get("equation_ids", []):
            if eid not in equation_ids:
                errors.append(f"Claim {cid}: refers to unknown equation '{eid}'.")

        if kind in UNCERTAIN_KINDS:
            for word in OVERCONFIDENT:
                if _contains_word(text, word):
                    errors.append(f"Claim {cid}: a {kind} must not be worded as proven ('{word}').")
        if kind == "theory":
            lowered = text.lower()
            for phrase in BELITTLING_THEORY:
                if phrase in lowered:
                    errors.append(f"Claim {cid}: a scientific theory must not be called '{phrase}'.")

        if kind in NEEDS_SOURCE and not claim.get("source_ids"):
            needs_approval.append(f"Claim {cid}: a {kind} has no source; a person must confirm it.")
        if kind == "mathematical_model" and not (claim.get("source_ids") or claim.get("equation_ids")):
            needs_approval.append(f"Claim {cid}: model has neither a source nor a checked equation.")

    return {"errors": errors, "needs_approval": needs_approval}


# ============================================================================
# from research/equation_checker.py
# ============================================================================
# Checks units, simple numeric properties and chemical equation balance.


BASE = ("m", "kg", "s", "A", "K", "mol", "cd")
DERIVED = {
    "N": {"kg": 1, "m": 1, "s": -2},
    "J": {"kg": 1, "m": 2, "s": -2},
    "W": {"kg": 1, "m": 2, "s": -3},
    "Pa": {"kg": 1, "m": -1, "s": -2},
    "L": {"m": 3},
    "g": {"kg": 1},
    "M": {"mol": 1, "m": -3},
}
TOKEN = re.compile(r"([A-Za-z]+)(?:\^(-?\d+))?")
STATE = re.compile(r"\((?:s|l|g|aq)\)")


def parse_units(expression):
    """'m^3 kg^-1 s^-2' -> {'m': 3, 'kg': -1, 's': -2}. Raises ValueError."""
    dims = {}
    leftover = TOKEN.sub(" ", expression.replace("*", " "))
    if leftover.strip():
        raise ValueError(f"Cannot read units: '{expression}'")
    for name, exp in TOKEN.findall(expression.replace("*", " ")):
        power = int(exp) if exp else 1
        if name in BASE:
            parts = {name: 1}
        elif name in DERIVED:
            parts = DERIVED[name]
        else:
            raise ValueError(f"Unknown unit '{name}'")
        for base, value in parts.items():
            dims[base] = dims.get(base, 0) + value * power
    return {k: v for k, v in dims.items() if v != 0}


def parse_formula(formula):
    """'Ca(OH)2' -> {'Ca': 1, 'O': 2, 'H': 2}. Raises ValueError."""
    formula = STATE.sub("", formula.strip())
    stack = [{}]
    i = 0
    while i < len(formula):
        ch = formula[i]
        if ch == "(":
            stack.append({})
            i += 1
        elif ch == ")":
            if len(stack) == 1:
                raise ValueError(f"Unbalanced brackets in '{formula}'")
            group = stack.pop()
            j = i + 1
            while j < len(formula) and formula[j].isdigit():
                j += 1
            mult = int(formula[i + 1:j] or 1)
            for el, n in group.items():
                stack[-1][el] = stack[-1].get(el, 0) + n * mult
            i = j
        else:
            match = re.match(r"([A-Z][a-z]?)(\d*)", formula[i:])
            if not match:
                raise ValueError(f"Cannot read formula '{formula}'")
            el, n = match.group(1), int(match.group(2) or 1)
            stack[-1][el] = stack[-1].get(el, 0) + n
            i += len(match.group(0))
    if len(stack) != 1:
        raise ValueError(f"Unbalanced brackets in '{formula}'")
    return stack[0]


def _side_atoms(side):
    totals = {}
    for term in side.split("+"):
        term = term.strip()
        if not term:
            raise ValueError("Empty term in equation")
        match = re.match(r"^(\d+)\s*(.+)$", term)
        coeff, formula = (int(match.group(1)), match.group(2)) if match else (1, term)
        for el, n in parse_formula(formula).items():
            totals[el] = totals.get(el, 0) + coeff * n
    return totals


def check_chemical_equation(equation):
    """Returns a list of problems (empty if atoms balance)."""
    text = equation.replace("\u2192", "->").replace("=", "->")
    if "->" not in text:
        return ["No arrow found (use '->')."]
    left, right = text.split("->", 1)
    try:
        lhs, rhs = _side_atoms(left), _side_atoms(right)
    except ValueError as err:
        return [str(err)]
    problems = []
    for el in sorted(set(lhs) | set(rhs)):
        if lhs.get(el, 0) != rhs.get(el, 0):
            problems.append(f"{el}: {lhs.get(el, 0)} on the left, {rhs.get(el, 0)} on the right")
    return problems


def gravity_acceleration(G, M, m, r):
    force = G * M * m / r ** 2
    return force / m


FUNCTIONS = {"gravity_acceleration": gravity_acceleration}


def check_equations(equations):
    """Returns {"errors": [...], "needs_approval": [...], "checked": [ids]}."""
    errors, needs_approval, checked = [], [], []
    if not equations:
        return {"errors": [], "needs_approval": ["No equations recorded."], "checked": []}
    for eq in equations:
        eid = eq.get("id", "?")

        if eq.get("type") == "chemical":
            problems = check_chemical_equation(eq.get("equation", ""))
            if problems:
                errors.append(f"Equation {eid}: not balanced ({'; '.join(problems)}).")
            else:
                checked.append(eid)
            continue

        dim = eq.get("dimension_check")
        if not dim:
            needs_approval.append(f"Equation {eid}: no unit check recorded.")
        else:
            try:
                if parse_units(dim["lhs"]) != parse_units(dim["rhs"]):
                    errors.append(f"Equation {eid}: units do not match ({dim['lhs']} vs {dim['rhs']}).")
                else:
                    checked.append(eid)
            except (ValueError, KeyError) as err:
                errors.append(f"Equation {eid}: {err}")

        for check in eq.get("numeric_checks", []):
            func = FUNCTIONS.get(check.get("function"))
            if func is None:
                errors.append(f"Equation {eid}: unknown check function '{check.get('function')}'.")
                continue
            if check.get("type") == "independence":
                results = [func(m=value, **check["fixed"]) for value in check["values"]]
                spread = (max(results) - min(results)) / abs(max(results))
                if spread > check.get("max_relative_spread", 1e-9):
                    errors.append(f"Equation {eid}: result changes with '{check['vary']}' (spread {spread:.2e}).")
            elif check.get("type") == "expected_value":
                value = func(**check["inputs"])
                if abs(value - check["expected"]) > check["tolerance"]:
                    errors.append(f"Equation {eid}: expected about {check['expected']}, got {value:.4f}.")
            else:
                errors.append(f"Equation {eid}: unknown numeric check type '{check.get('type')}'.")
    return {"errors": errors, "needs_approval": needs_approval, "checked": checked}


# ============================================================================
# from research/safety_checker.py
# ============================================================================
# Coarse automatic safety screening for topic records.

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


# ============================================================================
# from research/source_collector.py
# ============================================================================
# Checks source records attached to a topic.



REQUIRED_FIELDS = ("id", "title", "publisher", "url", "date_accessed")

PREFERRED_SUFFIXES = (
    "nasa.gov", "nist.gov", "noaa.gov", "cern.ch", "home.cern", "esa.int",
    "nature.com", "science.org", "aps.org", "iop.org", "royalsociety.org",
    "nobelprize.org", "rsc.org", "acs.org", "iupac.org", ".edu", ".gov", ".ac.uk",
)

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def domain_tier(url):
    host = (urlparse(url).hostname or "").lower()
    for suffix in PREFERRED_SUFFIXES:
        trusted_domain = suffix.lstrip(".")
        if host == trusted_domain or host.endswith("." + trusted_domain):
            return "preferred"
    return "needs_review"


def validate_sources(sources):
    """Returns (errors, warnings, known_ids)."""
    errors, warnings, ids = [], [], []
    if not isinstance(sources, list) or not sources:
        return ["No sources recorded."], warnings, ids

    for index, source in enumerate(sources):
        label = source.get("id", f"#{index + 1}") if isinstance(source, dict) else f"#{index + 1}"
        if not isinstance(source, dict):
            errors.append(f"Source {label}: must be an object.")
            continue
        for field in REQUIRED_FIELDS:
            if not source.get(field):
                errors.append(f"Source {label}: missing '{field}'.")
        url = source.get("url", "")
        if url and not url.startswith("https://"):
            errors.append(f"Source {label}: url must start with https://")
        for date_field in ("date_published", "date_updated", "date_accessed"):
            value = source.get(date_field)
            if value is not None and not DATE_PATTERN.match(str(value)):
                errors.append(f"Source {label}: {date_field} must look like YYYY-MM-DD.")
        if url.startswith("https://") and domain_tier(url) == "needs_review":
            warnings.append(f"Source {label}: not on the preferred list; needs human review.")
        if source.get("id"):
            ids.append(source["id"])

    if len(ids) != len(set(ids)):
        errors.append("Duplicate source ids.")
    return errors, warnings, ids


# ============================================================================
# from research/science_validator.py
# ============================================================================
# Runs all automated science checks on topic records.







  # noqa: E402
  # noqa: E402
  # noqa: E402
  # noqa: E402

DISCLAIMER = "Automated checks only. This is not expert peer review."


def validate_topic_science(record, template):
    from content.topic_manager import validate_topic_record    # imported here: content imports research too
    errors = list(validate_topic_record(record, template))
    needs_approval, warnings = [], []

    src_errors, src_warnings, source_ids = validate_sources(record.get("sources"))
    errors += src_errors
    warnings += src_warnings
    needs_approval += [w for w in src_warnings]

    equation_ids = [e.get("id") for e in record.get("equations", [])]
    claim_result = check_claims(record.get("claims", []), source_ids, equation_ids)
    errors += claim_result["errors"]
    needs_approval += claim_result["needs_approval"]

    eq_result = check_equations(record.get("equations", []))
    errors += eq_result["errors"]
    needs_approval += eq_result["needs_approval"]

    safety = check_safety(record)
    errors += safety["errors"]
    needs_approval += safety["needs_approval"]

    if not record.get("assumptions"):
        errors.append("No assumptions stated.")
    if not record.get("safety_considerations"):
        errors.append("No safety considerations stated.")

    status = "failed" if errors else ("needs_human_approval" if needs_approval else "passed_automated_checks")
    return {
        "topic_id": record.get("id"),
        "status": status,
        "errors": errors,
        "needs_approval": needs_approval,
        "warnings": warnings,
        "equations_unit_checked": eq_result["checked"],
        "human_review_required": True,
        "disclaimer": DISCLAIMER,
    }


def validate_topic_id(root, topic_id):
    from content.topic_manager import load_template, load_topic_record    # imported here: content imports research too
    record = load_topic_record(root, topic_id)
    template = load_template(root, record.get("template", "principle"))
    return validate_topic_science(record, template)


def format_report(result):
    lines = [f"Topic {result['topic_id']}: {result['status']}"]
    for key in ("errors", "needs_approval", "warnings"):
        for item in result[key]:
            if key == "warnings" and item in result["needs_approval"]:
                continue
            lines.append(f"  [{key}] {item}")
    lines.append(f"  Unit-checked equations: {', '.join(result['equations_unit_checked']) or 'none'}")
    lines.append(f"  {result['disclaimer']} Human review is still required.")
    return "\n".join(lines)


def main(argv):
    root = "."
    if len(argv) > 1:
        topic_ids = [argv[1]]
    else:
        with open(Path(root) / "topics" / "topic_queue.json", encoding="utf-8") as handle:
            topic_ids = [t["id"] for t in json.load(handle)["topics"]]

    failed = False
    reports = []
    for topic_id in topic_ids:
        try:
            result = validate_topic_id(root, topic_id)
        except FileNotFoundError:
            reports.append(f"Topic {topic_id}: no record file at topics/records/{topic_id}.json")
            failed = True
            continue
        reports.append(format_report(result))
        failed = failed or result["status"] == "failed"

    text = "\n\n".join(reports)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Science validation\n\n```\n" + text + "\n```\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
