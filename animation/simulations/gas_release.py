"""A qualitative model of a reaction that releases a gas.

Everything here is relative (0 to 1) and exaggerated for clarity. It shows
the idea (gas leaves an open container, builds pressure in a sealed one), not
measured values.
"""
import random

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
