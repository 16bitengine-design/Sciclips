"""A topic's own pictures: shapes, arrows and labels that move, drawn on the canvas.

Each topic can carry a `scene_plan` (written by the topic scout from that topic's own explanation).
A plan has a few "views" (intro, demo, problem, result, explain). A view is a list of simple elements
placed on a stage 160 wide and 100 tall (y grows downward). The video code picks the view that fits the
scene's section, and draws it, so every topic is illustrated with its own objects and not with a fixed template.

This file only needs the standard library to check a plan, so the scout can use `validate` cheaply.
Drawing imports the canvas only when it runs.
"""
import math

STAGE_W, STAGE_H = 160.0, 100.0
COLORS = ("blue", "accent", "good", "warn", "bad", "violet", "text", "muted", "panel2")
TYPES = ("rect", "ellipse", "polygon", "line", "arrow", "text")
VIEWS = ("intro", "demo", "problem", "result", "explain")
VIEW_FOR_KIND = {
    "hook": "intro", "intro": "intro", "question": "intro", "scenario_intro": "intro",
    "demonstration": "demo", "correct_procedure": "demo", "application": "demo",
    "overlooked": "problem", "what_changes": "problem", "misconception": "problem",
    "consequences": "result", "conclusion": "result", "answer": "result",
    "explanation_l2": "explain", "explanation_l3": "explain", "why": "explain",
}
# Which views may illustrate a section. Long narration is split into several scenes, and consecutive scenes
# take turns among the choices, so the picture keeps changing while the explanation moves on.
VIEW_CHOICES = {
    "hook": ("intro",), "intro": ("intro", "demo"), "question": ("intro", "demo"), "scenario_intro": ("intro", "demo"),
    "demonstration": ("demo", "explain", "demo", "result"), "correct_procedure": ("demo", "explain"), "application": ("demo", "explain", "result"),
    "overlooked": ("problem",), "what_changes": ("problem",), "misconception": ("problem",),
    "consequences": ("result", "explain"), "conclusion": ("result", "explain"), "answer": ("result", "demo"),
    "explanation_l2": ("explain", "demo"), "explanation_l3": ("explain", "demo"), "why": ("explain", "demo"),
}
MIN_ELEMENTS, MAX_ELEMENTS = 3, 30
MIN_ANIMATED = 2
X_RANGE, Y_RANGE = (-10.0, 170.0), (-10.0, 110.0)


class PlanError(ValueError):
    """Why a scene plan was rejected."""


def _num(value, low, high, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not low <= value <= high:
        raise PlanError(f"{what} must be a number from {low:g} to {high:g}")
    return float(value)


def _in_stage(x, y, what):
    _num(x, *X_RANGE, f"{what} x")
    _num(y, *Y_RANGE, f"{what} y")


def _element(raw, where):
    if not isinstance(raw, dict) or raw.get("type") not in TYPES:
        raise PlanError(f"{where}: unknown element type")
    kind = raw["type"]
    e = {"type": kind}
    e["color"] = raw.get("color", "text" if kind == "text" else "accent")
    if e["color"] not in COLORS:
        raise PlanError(f"{where}: unknown colour '{e['color']}'")
    e["alpha"] = _num(raw.get("alpha", 1.0), 0.15, 1.0, f"{where} alpha")
    e["appear"] = _num(raw.get("appear", 0.0), 0.0, 0.9, f"{where} appear")
    e["dx"] = _num(raw.get("dx", 0.0), -120.0, 120.0, f"{where} dx")
    e["dy"] = _num(raw.get("dy", 0.0), -120.0, 120.0, f"{where} dy")
    e["from"] = _num(raw.get("from", 0.1), 0.0, 0.9, f"{where} from")
    e["to"] = _num(raw.get("to", 0.9), 0.1, 1.0, f"{where} to")
    if e["to"] <= e["from"]:
        raise PlanError(f"{where}: 'to' must come after 'from'")
    e["bob"] = _num(raw.get("bob", 0.0), 0.0, 3.0, f"{where} bob")
    if kind in ("rect", "ellipse"):
        for key in ("x", "y", "w", "h"):
            e[key] = _num(raw.get(key), -10.0 if key in "xy" else 1.0, 200.0, f"{where} {key}")
        _in_stage(e["x"], e["y"], where)
        _in_stage(e["x"] + e["dx"], e["y"] + e["dy"], where)
    elif kind == "polygon":
        points = raw.get("points")
        if not isinstance(points, list) or not 3 <= len(points) <= 8:
            raise PlanError(f"{where}: a polygon needs 3 to 8 points")
        e["points"] = []
        for p in points:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                raise PlanError(f"{where}: each point must be [x, y]")
            _in_stage(p[0], p[1], where)
            _in_stage(p[0] + e["dx"], p[1] + e["dy"], where)
            e["points"].append([float(p[0]), float(p[1])])
    elif kind in ("line", "arrow"):
        for key in ("x", "y", "x2", "y2"):
            e[key] = _num(raw.get(key), -10.0, 170.0, f"{where} {key}")
        _in_stage(e["x"], e["y"], where)
        _in_stage(e["x2"], e["y2"], where)
        _in_stage(e["x"] + e["dx"], e["y"] + e["dy"], where)
        _in_stage(e["x2"] + e["dx"], e["y2"] + e["dy"], where)
    else:  # text
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 24 or not text.isprintable():
            raise PlanError(f"{where}: text must be 1 to 24 plain characters")
        e["text"] = text.strip()
        e["x"], e["y"] = _num(raw.get("x"), *X_RANGE, f"{where} x"), _num(raw.get("y"), *Y_RANGE, f"{where} y")
        e["size"] = _num(raw.get("size", 6), 4.0, 10.0, f"{where} size")
        _in_stage(e["x"] + e["dx"], e["y"] + e["dy"], where)
    return e


def _animated(e):
    return e["appear"] > 0 or e["dx"] != 0 or e["dy"] != 0 or e["bob"] > 0


def validate(plan):
    """Returns a clean copy of the plan, or raises PlanError with the reason."""
    if not isinstance(plan, dict) or not isinstance(plan.get("views"), dict):
        raise PlanError("the plan needs a 'views' object")
    views = {}
    for name in VIEWS:
        raw = plan["views"].get(name)
        if raw is None:
            continue
        items = raw.get("elements") if isinstance(raw, dict) else None
        if not isinstance(items, list) or not MIN_ELEMENTS <= len(items) <= MAX_ELEMENTS:
            raise PlanError(f"view '{name}' needs {MIN_ELEMENTS} to {MAX_ELEMENTS} elements")
        elements = [_element(item, f"{name}[{i}]") for i, item in enumerate(items)]
        if sum(_animated(e) for e in elements) < MIN_ANIMATED:
            raise PlanError(f"view '{name}' needs at least {MIN_ANIMATED} moving or appearing elements")
        views[name] = elements
    if "demo" not in views or len(views) < 2:
        raise PlanError("the plan needs a 'demo' view and at least one more view")
    return {"views": views}


def view_for(scene):
    """The name of the view that illustrates this scene."""
    choices = VIEW_CHOICES.get(scene.get("section_kind"), ("demo",))
    return choices[(int(scene.get("scene_number", 1)) - 1) % len(choices)]


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 3 * x * x - 2 * x ** 3


def draw(c, t, scene, plan, box):
    """Draw the right view of the plan for this scene inside `box`. Returns False if it could not."""
    try:
        clean = validate(plan)
    except PlanError:
        return False
    from animation.two_d.canvas import appear
    elements = clean["views"].get(view_for(scene)) or clean["views"]["demo"]
    x0, y0, x1, y1 = box
    scale = min((x1 - x0) / STAGE_W, (y1 - y0) / STAGE_H)
    if scale * STAGE_W < c.px(300):
        return False
    ox, oy = x0 + ((x1 - x0) - STAGE_W * scale) / 2, y0 + ((y1 - y0) - STAGE_H * scale) / 2
    secs = t * scene.get("duration_seconds", 5)
    base = appear(t, 0.0, 0.12)
    c.rect((ox, oy, ox + STAGE_W * scale, oy + STAGE_H * scale), fill="panel", radius=26, alpha=base)

    def X(v):
        return ox + v * scale

    def Y(v):
        return oy + v * scale

    for index, e in enumerate(elements):
        alpha = e["alpha"] * base
        if e["appear"] > 0:
            alpha *= appear(t, e["appear"], 0.1)
        if alpha <= 0:
            continue
        p = _ease((t - e["from"]) / (e["to"] - e["from"]))
        dx, dy = e["dx"] * p, e["dy"] * p
        if e["bob"]:
            dy += e["bob"] * math.sin(secs * 5.0 + index)
        kind = e["type"]
        if kind in ("rect", "ellipse"):
            half_w, half_h = e["w"] / 2, e["h"] / 2
            shape = (X(e["x"] + dx - half_w), Y(e["y"] + dy - half_h), X(e["x"] + dx + half_w), Y(e["y"] + dy + half_h))
            if kind == "rect":
                c.rect(shape, fill=e["color"], alpha=alpha, sticker=False)
            else:
                c.d.ellipse(shape, fill=c.col(e["color"], alpha))
        elif kind == "polygon":
            c.polygon([(X(px + dx), Y(py + dy)) for px, py in e["points"]], fill=e["color"], alpha=alpha)
        elif kind in ("line", "arrow"):
            start, end = (X(e["x"] + dx), Y(e["y"] + dy)), (X(e["x2"] + dx), Y(e["y2"] + dy))
            (c.arrow if kind == "arrow" else c.line)(start, end, e["color"], 6, alpha)
        else:
            c.label((X(e["x"] + dx), Y(e["y"] + dy)), e["text"], e["size"] * scale / c.u, e["color"],
                    kind="bold", anchor="mm", alpha=alpha)
    return True
