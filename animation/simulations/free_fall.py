"""A small free-fall model with optional air drag.

This is an ILLUSTRATIVE model with made-up object values (hammer and feather
sizes and masses are assumptions, not measurements). It shows how drag, not
gravity, makes a feather lag in air. It is not experimental evidence.
"""

import math

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
