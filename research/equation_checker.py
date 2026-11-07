"""Checks units, simple numeric properties and chemical equation balance.

Only functions listed in FUNCTIONS can be used, so a topic file can never
run arbitrary code. Chemical checks verify that atoms are conserved. They do
not check that a reaction really happens: that needs a source.
"""
import re

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
