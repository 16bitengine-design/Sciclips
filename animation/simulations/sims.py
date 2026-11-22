"""simulations: merged module (was 3 files: free_fall, gas_release, reaction_layout).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""
import math
import random
import re


# ============================================================================
# from animation/simulations/free_fall.py
# ============================================================================
# A small free-fall model with optional air drag.



GRAVITY = 9.81       # m/s^2, model value
HEIGHT = 1.6         # m, drop height used in the animation
AIR_DENSITY = 1.2    # kg/m^3, rounded illustrative value

OBJECTS = {
    "hammer": {"mass": 1.3, "area": 0.01, "cd": 1.0},
    "feather": {"mass": 0.0005, "area": 0.01, "cd": 1.2},
}


def simulate(name, in_air, height=HEIGHT, g=GRAVITY, accel_scale=1.0, dt=0.001, t_max=20.0):
    """Drop one object and return its motion.

    Downward speed v changes by dv/dt = g*accel_scale - (k/m) v^2, where
    k = 0.5 * air_density * Cd * area (k = 0 in a vacuum).
    accel_scale other than 1 is used only to draw a deliberately WRONG model.
    """
    obj = OBJECTS[name]
    k = 0.5 * AIR_DENSITY * obj["cd"] * obj["area"] if in_air else 0.0
    mass = obj["mass"]
    y, v, t = height, 0.0, 0.0
    heights, speeds = [y], [v]
    t_land = None
    while t < t_max:
        a = g * accel_scale - (k / mass) * v * v
        v += a * dt
        y -= v * dt
        t += dt
        if y <= 0.0:
            y = 0.0
            t_land = t
            heights.append(y)
            speeds.append(v)
            break
        heights.append(y)
        speeds.append(v)
    return {"name": name, "dt": dt, "height": height, "y": heights, "v": speeds, "t_land": t_land}


def state_at(sim, t):
    """(height above ground in m, downward speed in m/s) at time t seconds."""
    index = min(int(max(t, 0.0) / sim["dt"]), len(sim["y"]) - 1)
    return sim["y"][index], sim["v"][index]


def landing_summary(first, second, tolerance=0.03):
    """'together', 'first' or 'second', based on the simulated landing times."""
    if first["t_land"] is None or second["t_land"] is None:
        return "unfinished"
    if abs(first["t_land"] - second["t_land"]) <= tolerance:
        return "together"
    return "first" if first["t_land"] < second["t_land"] else "second"


def drag_to_weight(name, speed, g=GRAVITY):
    """Drag force divided by weight for an object at a given speed (model values)."""
    obj = OBJECTS[name]
    drag = 0.5 * AIR_DENSITY * obj["cd"] * obj["area"] * speed * speed
    return drag / (obj["mass"] * g)


# Illustrative person falling with and without a parachute. Values are made up to show the idea.
PERSON = {"mass": 80.0, "small": {"area": 0.7, "cd": 1.0}, "big": {"area": 25.0, "cd": 1.5}}


def terminal_speed(mass, area, cd, g=GRAVITY):
    """Speed at which drag equals weight: sqrt(2 m g / (air_density Cd A))."""
    return (2.0 * mass * g / (AIR_DENSITY * cd * area)) ** 0.5


def speed_in_air(v_terminal, t, g=GRAVITY):
    """Downward speed t seconds after release when drag grows with speed squared (starting from rest)."""
    return v_terminal * math.tanh(g * t / v_terminal)


def terminal_curve(shape, t_end, dt=0.05):
    """The same kind of dictionary simulate() returns, for a person with a small or a big area."""
    spec = PERSON[shape]
    vt = terminal_speed(PERSON["mass"], spec["area"], spec["cd"])
    steps = int(t_end / dt) + 1
    speeds = [speed_in_air(vt, i * dt) for i in range(steps + 1)]
    return {"name": shape, "dt": dt, "height": None, "y": [0.0] * len(speeds), "v": speeds,
            "t_land": None, "v_terminal": vt}


# ============================================================================
# from animation/simulations/gas_release.py
# ============================================================================
# A qualitative model of a reaction that releases a gas.


VARIANTS = ("open", "sealed", "sealed_pop", "balance_open", "balance_sealed")
POP_AT = 0.82  # relative pressure at which the lid is shown popping


def reaction_progress(t):
    """Relative amount of gas made so far, 0 to 1, slowing as reactants run out."""
    t = min(max(t, 0.0), 1.0)
    return 1.0 - (1.0 - t) ** 2


def make_bubbles(count=28, seed=7):
    rng = random.Random(seed)
    return [{"x": rng.uniform(0.12, 0.88), "phase": rng.random(), "speed": rng.uniform(0.7, 1.4),
             "radius": rng.uniform(0.012, 0.03)} for _ in range(count)]


def bubble_height(bubble, t):
    """Height of a bubble as a fraction of the liquid-to-top rise (0 start, 1 top), repeating."""
    return (bubble["phase"] + t * 2.2 * bubble["speed"]) % 1.0


def pressure(variant, t):
    """Relative pressure in the container, 0 to 1."""
    p = reaction_progress(t)
    if variant == "sealed":
        return p
    if variant == "sealed_pop":
        return min(p, 1.0) if p < POP_AT else 0.12
    return 0.0


def lid_lift(variant, t):
    """How far the lid has lifted (0 to 1); only the popping variant lifts it."""
    if variant != "sealed_pop":
        return 0.0
    over = reaction_progress(t) - POP_AT
    return min(1.0, max(0.0, over / 0.12))


def scale_reading(variant, t):
    """Relative mass shown by a balance, 1.0 at the start. Drop is exaggerated for clarity."""
    if variant == "balance_open":
        return 1.0 - 0.12 * reaction_progress(t)
    return 1.0


# ============================================================================
# from animation/simulations/reaction_layout.py
# ============================================================================
# Layouts for the reaction and gas-escape diagrams. Pure functions: easy to test.


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
