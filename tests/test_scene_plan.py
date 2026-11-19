"""Checks for the per-topic picture plans (animation/two_d/scene_plan.py). Pure Python, no drawing."""
import copy

import pytest

from animation.two_d import scene_plan as sp


def _view(extra=None):
    elements = [{"type": "rect", "x": 80, "y": 72, "w": 130, "h": 46, "color": "blue", "alpha": 0.5},
                {"type": "ellipse", "x": 45, "y": 20, "w": 14, "h": 14, "color": "warn", "dy": 40},
                {"type": "arrow", "x": 115, "y": 70, "x2": 115, "y2": 54, "color": "good", "appear": 0.5}]
    return {"elements": elements + (extra or [])}


GOOD = {"views": {"demo": _view(), "intro": _view()}}


def test_a_good_plan_is_accepted():
    clean = sp.validate(GOOD)
    assert set(clean["views"]) == {"demo", "intro"}


def test_needs_a_demo_view_and_one_more():
    with pytest.raises(sp.PlanError):
        sp.validate({"views": {"demo": _view()}})
    with pytest.raises(sp.PlanError):
        sp.validate({"views": {"intro": _view(), "result": _view()}})


def test_rejects_unknown_type_colour_and_long_text():
    for bad in ({"type": "star", "x": 1, "y": 1},
                {"type": "rect", "x": 1, "y": 1, "w": 5, "h": 5, "color": "pink"},
                {"type": "text", "x": 1, "y": 1, "text": "x" * 25}):
        plan = copy.deepcopy(GOOD)
        plan["views"]["demo"]["elements"].append(bad)
        with pytest.raises(sp.PlanError):
            sp.validate(plan)


def test_rejects_things_that_leave_the_stage():
    plan = copy.deepcopy(GOOD)
    plan["views"]["demo"]["elements"].append({"type": "ellipse", "x": 150, "y": 50, "w": 10, "h": 10, "dx": 60})
    with pytest.raises(sp.PlanError):
        sp.validate(plan)


def test_a_view_must_have_moving_elements():
    still = {"elements": [{"type": "rect", "x": 10 * i, "y": 10, "w": 5, "h": 5} for i in range(1, 4)]}
    with pytest.raises(sp.PlanError):
        sp.validate({"views": {"demo": still, "intro": _view()}})


def test_junk_is_rejected():
    for junk in (None, [], {}, {"views": []}, {"views": {"demo": {"elements": "x"}}}):
        with pytest.raises(sp.PlanError):
            sp.validate(junk)
