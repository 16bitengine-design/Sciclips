"""Switches on each topic's own pictures (its `scene_plan`) for the opening, simulation and diagram scenes.

A topic that has a scene_plan and no hand-built simulation is drawn from its plan. Every other topic,
for example free fall and gas release, is drawn exactly as before. If a plan cannot be drawn, the old
drawing is used, so a video is never lost because of this file.
"""
from animation.two_d import diagrams, scene_plan, sim_draw
from animation.two_d.canvas import appear
from animation.two_d.scenes import SCENE_FUNCTIONS, _text

_original = dict(SCENE_FUNCTIONS)


def _plan(ctx):
    record = ctx["record"]
    plan = record.get("scene_plan")
    if not plan or record.get("simulation"):
        return None
    try:
        scene_plan.validate(plan)
    except scene_plan.PlanError:
        return None
    return plan


def hook(c, t, ctx):
    plan = _plan(ctx)
    if plan is None:
        return _original["3d_scene"](c, t, ctx)
    x0, y0, x1, y1 = c.content_box()
    a = appear(t, 0.0, 0.2)
    text = _text(ctx["scene"])
    size = c.fit_size(text, x1 - x0, (y1 - y0) * 0.32, 76, 36, "bold")
    bottom = c.paragraph(x0, y0 + c.px(100) + (1 - a) * c.px(40), text, size, "text", x1 - x0, kind="bold", alpha=a)
    c.rect((x0, bottom + c.px(20), x0 + c.px(120), bottom + c.px(26)), fill="accent", alpha=a)
    scene_plan.draw(c, t, ctx["scene"], plan, (x0, bottom + c.px(50), x1, y1))


def simulation(c, t, ctx):
    plan = _plan(ctx)
    if plan is None:
        return _original["simulation"](c, t, ctx)
    x0, y0, x1, y1 = c.content_box()
    if scene_plan.draw(c, t, ctx["scene"], plan, (x0, y0 + c.px(10), x1, y1)):
        sim_draw._footer(c)
    else:
        _original["simulation"](c, t, ctx)


def diagram(c, t, ctx):
    plan = _plan(ctx)
    named = diagrams.DIAGRAMS.get((ctx["scene"].get("data") or {}).get("diagram"))
    if plan is None or named:
        return _original["2d_diagram"](c, t, ctx)
    x0, y0, x1, y1 = c.content_box()
    if not scene_plan.draw(c, t, ctx["scene"], plan, (x0, y0 + c.px(10), x1, y1)):
        _original["2d_diagram"](c, t, ctx)


SCENE_FUNCTIONS["3d_scene"] = hook
SCENE_FUNCTIONS["simulation"] = simulation
SCENE_FUNCTIONS["2d_diagram"] = diagram
