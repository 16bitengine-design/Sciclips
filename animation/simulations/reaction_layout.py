"""Layouts for the reaction and gas-escape diagrams. Pure functions: easy to test.

Positions are fractions of the drawing area (0 to 1). Everything here is an
illustration of the idea, not a simulation of real molecules.
"""
import re

GASES = {"CO2", "H2", "O2", "N2", "Cl2", "NH3", "CH4", "SO2", "NO2"}


def _ease(x):
    x = min(1.0, max(0.0, x))
    return 3 * x * x - 2 * x ** 3


def split_equation(equation):
    text = equation.replace("\u2192", "->").replace("=", "->")
    left, right = text.split("->", 1)
    return [_species(side) for side in (left, right)]


def _species(side):
    out = []
    for term in side.split("+"):
        term = term.strip()
        match = re.match(r"^(\d+)\s*(.+)$", term)
        out.append((int(match.group(1)), match.group(2)) if match else (1, term))
    return out


def reaction_tokens(equation, t):
    """Where each substance is drawn at progress t (0 to 1).

    Reactants drift together (0 to 0.4), there is a brief change (0.4 to 0.5),
    then products move apart (0.5 to 0.9). Gases rise and leave the top.
    """
    reactants, products = split_equation(equation)
    tokens = []
    for i, (coeff, formula) in enumerate(reactants):
        y = (i + 1) / (len(reactants) + 1)
        move = _ease(t / 0.4)
        fade = 1.0 - _ease((t - 0.4) / 0.1)
        tokens.append({"label": formula, "coeff": coeff, "side": "reactant", "gas": False,
                       "x": 0.12 + (0.38 - 0.12) * move, "y": y, "alpha": fade})
    for i, (coeff, formula) in enumerate(products):
        y_slot = (i + 1) / (len(products) + 1)
        gas = formula in GASES
        move = _ease((t - 0.5) / 0.4)
        appear = _ease((t - 0.45) / 0.1)
        x = 0.5 + (0.86 - 0.5) * move
        y = 0.5 + (y_slot - 0.5) * move
        alpha = appear
        if gas:
            y = 0.5 + (0.12 - 0.5) * _ease((t - 0.55) / 0.45)
            x = 0.5 + (0.80 - 0.5) * _ease((t - 0.5) / 0.4)
            alpha = appear * (1.0 - _ease((t - 0.85) / 0.15))
        tokens.append({"label": formula, "coeff": coeff, "side": "product", "gas": gas,
                       "x": x, "y": y, "alpha": alpha})
    return tokens


ATOM_COUNT = 12


def _slot(i):
    cols = 4
    return (0.18 + 0.64 * ((i % cols) / (cols - 1)), 0.55 + 0.35 * ((i // cols) / 2.0))


def gas_escape_atoms(open_container, t):
    """Positions of ATOM_COUNT dots. In an open container the gas dots leave; in a sealed one they stay.

    Returns a list of (x, y, inside) with x and y relative to the container (inside is 0..1 box).
    """
    atoms = []
    leaving_from = ATOM_COUNT // 3  # the first third of the dots stay as liquid; the rest are gas
    for i in range(ATOM_COUNT):
        x, y = _slot(i)
        if i < leaving_from:
            atoms.append((x, 0.78 + 0.1 * (i / leaving_from), True))
            continue
        if not open_container:
            wobble = 0.03 * ((i * 7) % 5 - 2) / 2
            atoms.append((x + wobble, 0.2 + 0.4 * ((i * 3) % 7) / 7, True))
            continue
        start = (i - leaving_from) / (ATOM_COUNT - leaving_from)
        progress = _ease((t - 0.15 - 0.35 * start) / 0.4)
        y_in = 0.2 + 0.4 * ((i * 3) % 7) / 7
        y_now = y_in + (-0.55 - y_in) * progress
        atoms.append((x, y_now, y_now >= 0.0))
    return atoms


def atoms_inside(open_container, t):
    return sum(1 for _, _, inside in gas_escape_atoms(open_container, t) if inside)
