"""Checks units (dimensional analysis) and simple numeric properties.

Only functions listed in FUNCTIONS can be used, so a topic file can never
run arbitrary code.
"""
import re

BASE = ("m", "kg", "s", "A", "K", "mol", "cd")
DERIVED = {
    "N": {"kg": 1, "m": 1, "s": -2},
    "J": {"kg": 1, "m": 2, "s": -2},
    "W": {"kg": 1, "m": 2, "s": -3},
    "Pa": {"kg": 1, "m": -1, "s": -2},
}
TOKEN = re.compile(r"([A-Za-z]+)(?:\^(-?\d+))?")


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
