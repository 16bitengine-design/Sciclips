"""One drawing function per animation type. Each draws a single frame at progress t (0 to 1)."""
import re

from animation.two_d.canvas import appear, clamp, pretty_math
from animation.simulations import gas_release as gas
from animation.two_d import sim_draw
from research.equation_checker import _side_atoms


def _text(scene):
    """What to show on screen. Continuation scenes have no caption, so they show their narration."""
    return scene.get("on_screen_text") or scene.get("narration", "") or ""


def _label(c, box, scene, color="accent"):
    x0, y0, _, _ = box
    c.label((x0, y0), (scene.get("section_title") or "").upper(), 30, color, kind="bold")
    c.rect((x0, y0 + c.px(44), x0 + c.px(120), y0 + c.px(50)), fill=color)
    return y0 + c.px(80)


# --------------------------------------------------------------------- text
def text_card(c, t, ctx):
    scene = ctx["scene"]
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene)
    text = _text(scene)
    a = appear(t, 0.0, 0.18)
    size = c.fit_size(text, x1 - x0, (y1 - top) * 0.85, 76, 34, "bold")
    height = c.text_height(c.wrap(text, c.font("bold", size), x1 - x0), size)
    start = top + max(0, (y1 - top - height) / 2) + (1 - a) * c.px(30)
    c.paragraph(x0, start, text, size, "text", x1 - x0, kind="bold", alpha=a)


def _hook_preview(c, t, ctx, top, bottom):
    """A small still picture for the opening card (the 3D version arrives in Stage 6)."""
    kind = (ctx["record"].get("simulation") or {}).get("kind")
    if bottom - top < c.px(300):
        return
    a = appear(t, 0.3, 0.25)
    drop = (1 - a) * c.px(40)
    if kind == "free_fall":
        for name, x in (("hammer", c.w * 0.35), ("feather", c.w * 0.65)):
            held = top + c.px(110) - drop
            for k in range(8):
                y = held + c.px(30) + k * c.px(34)
                if y < bottom - c.px(20):
                    c.line((x, y), (x, y + c.px(16)), "muted", 4, alpha=a * 0.8)
            (sim_draw._draw_hammer if name == "hammer" else sim_draw._draw_feather)(c, x, held)
        c.rect((c.w * 0.12, bottom - c.px(14), c.w * 0.88, bottom - c.px(6)), fill="muted", alpha=a)
    elif kind == "gas_release":
        width, height = c.px(300), min(c.px(340), bottom - top - c.px(40))
        box = (c.w / 2 - width / 2, bottom - height - drop, c.w / 2 + width / 2, bottom - drop)
        sim_draw._draw_beaker(c, box, 0.35, 0.6, "open", gas.make_bubbles())


def hook_card(c, t, ctx):
    """Opening card: the title plus a still picture. A lightweight 3D version arrives in Stage 6."""
    scene = ctx["scene"]
    x0, y0, x1, y1 = c.content_box()
    a = appear(t, 0.0, 0.2)
    c.label((x0, y0), "SCIENCE ANIMATION STUDIO", 26, "muted", kind="bold", alpha=a)
    text = _text(scene)
    size = c.fit_size(text, x1 - x0, (y1 - y0) * 0.4, 84, 40, "bold")
    bottom = c.paragraph(x0, y0 + c.px(120) + (1 - a) * c.px(40), text, size, "text", x1 - x0, kind="bold", alpha=a)
    c.rect((x0, bottom + c.px(24), x0 + c.px(120), bottom + c.px(30)), fill="accent", alpha=a)
    _hook_preview(c, t, ctx, bottom + c.px(50), y1)


# ---------------------------------------------------------------- equation
def _find_equation(record, scene):
    shown = _text(scene)
    for eq in record.get("equations", []):
        if shown in (eq.get("latex"), eq.get("equation")):
            return eq
    eqs = record.get("equations", [])
    wanted = record.get("key_equation_id")
    for eq in eqs:
        if eq.get("id") == wanted:
            return eq
    return eqs[-1] if eqs else None


def equation_card(c, t, ctx):
    scene, record = ctx["scene"], ctx["record"]
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene)
    eq = _find_equation(record, scene)
    if eq is None:
        return text_card(c, t, ctx)
    width = x1 - x0
    a = appear(t, 0.0, 0.2)
    is_chem = eq.get("type") == "chemical"
    if is_chem:
        raw = eq["equation"].replace("\u2192", "->")
        left, right = [part.strip() for part in raw.split("->", 1)]
        size = c.fit_size(pretty_math(left), width, c.px(220), 64, 30, "bold")
        y = top + c.px(20)
        y = c.paragraph(x0, y, pretty_math(left), size, "warn", width, kind="bold", alpha=a)
        c.label((x0, y + c.px(6)), "\u2193 reacts to give", 34, "muted", alpha=a)
        y = c.paragraph(x0, y + c.px(60), pretty_math(right), size, "good", width, kind="bold", alpha=a)
        y += c.px(40)
        lhs, rhs = _side_atoms(left), _side_atoms(raw.split("->", 1)[1])
        c.label((x0, y), "Atoms are conserved", 32, "accent", kind="bold", alpha=appear(t, 0.35))
        y += c.px(56)
        for i, element in enumerate(sorted(set(lhs) | set(rhs))):
            b = appear(t, 0.4 + 0.07 * i, 0.12)
            if b > 0 and y < y1 - c.px(40):
                c.label((x0, y), f"{element}:  {lhs.get(element, 0)}  on the left,  {rhs.get(element, 0)}  on the right",
                        32, "text", alpha=b)
                y += c.px(46)
        return
    text = pretty_math(eq.get("latex") or eq.get("equation", ""))
    size = c.fit_size(text, width, c.px(260), 96, 40, "bold")
    y = c.paragraph(x0, top + c.px(30) + (1 - a) * c.px(30), text, size, "text", width, kind="bold", alpha=a)
    c.label((x0, y + c.px(18)), eq.get("name", ""), 30, "muted", alpha=appear(t, 0.15))
    y += c.px(100)
    tokens = set(re.findall(r"[A-Za-z]+", eq.get("latex", "")))
    shown = [v for v in record.get("variables", []) if v["symbol"] in tokens]
    for i, v in enumerate(shown):
        b = appear(t, 0.3 + 0.1 * i, 0.12)
        if b > 0 and y < y1 - c.px(40):
            c.label((x0, y), v["symbol"], 40, "accent", kind="bold", alpha=b)
            c.paragraph(x0 + c.px(90), y + c.px(4), f"{v['name']} ({pretty_math(v['unit'])})", 30, "text",
                        width - c.px(90), alpha=b)
            y += c.px(64)


# ------------------------------------------------------------------ diagram
GENERIC_VISUALS = {"title text with a simple labelled diagram", "labelled diagram of the main observation",
                   "title card showing the central question", "list of source titles and publishers", "term list"}


def _clean(item):
    return re.sub(r"^(label|caption|left panel|right panel):\s*", "", item)


def diagram_cards(c, t, ctx):
    scene = ctx["scene"]
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene)
    items = [_clean(i) for i in scene.get("visual_elements", []) if i not in GENERIC_VISUALS][:4]
    if not items:
        return text_card(c, t, ctx)
    n = len(items)
    colors = ["accent", "blue", "violet", "good"]
    if c.portrait:
        gap = c.px(46)
        h = min(c.px(190), (y1 - top - gap * (n - 1)) / n)
        y = top
        for i, item in enumerate(items):
            a = appear(t, 0.08 + 0.2 * i)
            if a > 0:
                c.rect((x0, y, x1, y + h), fill="panel", radius=20, alpha=a)
                c.rect((x0, y, x0 + c.px(12), y + h), fill=colors[i], alpha=a)
                size = c.fit_size(item, x1 - x0 - c.px(70), h * 0.8, 40, 22)
                th = c.text_height(c.wrap(item, c.font("sans", size), x1 - x0 - c.px(70)), size)
                c.paragraph(x0 + c.px(40), y + (h - th) / 2, item, size, "text", x1 - x0 - c.px(70), alpha=a)
                if i < n - 1 and appear(t, 0.2 + 0.2 * i) > 0:
                    c.arrow(((x0 + x1) / 2, y + h + c.px(4)), ((x0 + x1) / 2, y + h + gap - c.px(4)), "muted", 5)
            y += h + gap
    else:
        gap = c.px(60)
        w = (x1 - x0 - gap * (n - 1)) / n
        h = c.px(300)
        y = top + c.px(40)
        for i, item in enumerate(items):
            left = x0 + i * (w + gap)
            a = appear(t, 0.08 + 0.2 * i)
            if a > 0:
                c.rect((left, y, left + w, y + h), fill="panel", radius=20, alpha=a)
                c.rect((left, y, left + w, y + c.px(10)), fill=colors[i], alpha=a)
                size = c.fit_size(item, w - c.px(50), h * 0.75, 38, 22)
                c.paragraph(left + c.px(25), y + c.px(40), item, size, "text", w - c.px(50), alpha=a)
                if i < n - 1 and appear(t, 0.2 + 0.2 * i) > 0:
                    c.arrow((left + w + c.px(4), y + h / 2), (left + w + gap - c.px(4), y + h / 2), "muted", 5)


# --------------------------------------------------------------- comparison
def comparison_panels(c, t, ctx):
    scene = ctx["scene"]
    data = scene.get("data", {})
    kind = scene.get("section_kind")
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene, "warn")
    if kind == "misconception":
        left = ("MISCONCEPTION", "bad", data.get("statement", _text(scene)))
        right = ("CORRECTION", "good", data.get("correction", ""))
        footer = ""
    elif kind == "what_changes":
        left = ("CORRECT", "good", data.get("correct", ""))
        right = ("OVERLOOKED", "warn", data.get("overlooked", ""))
        footer = _text(scene)
    else:
        items = [_clean(i) for i in scene.get("visual_elements", [])]
        left = ("CORRECT", "good", items[0] if items else "")
        right = ("OVERLOOKED", "warn", items[1] if len(items) > 1 else "")
        footer = ""
    foot_h = c.px(160) if footer else 0
    gap = c.px(24)
    area = (x0, top, x1, y1 - foot_h)
    panels = []
    if c.portrait:
        h = (area[3] - area[1] - gap) / 2
        panels = [(x0, area[1], x1, area[1] + h), (x0, area[1] + h + gap, x1, area[3])]
    else:
        w = (x1 - x0 - gap) / 2
        panels = [(x0, area[1], x0 + w, area[3]), (x0 + w + gap, area[1], x1, area[3])]
    for i, ((title, color, text), pbox) in enumerate(zip((left, right), panels)):
        a = appear(t, 0.05 + 0.25 * i)
        if a <= 0:
            continue
        px0, py0, px1, py1 = pbox
        c.rect(pbox, fill="panel", radius=20, alpha=a)
        c.rect((px0, py0, px1, py0 + c.px(60)), fill=color, radius=20, alpha=a * 0.9)
        c.label((px0 + c.px(26), py0 + c.px(30)), title, 30, "bg", kind="bold", anchor="lm", alpha=a)
        size = c.fit_size(text, px1 - px0 - c.px(60), py1 - py0 - c.px(110), 44, 22)
        c.paragraph(px0 + c.px(30), py0 + c.px(84), text, size, "text", px1 - px0 - c.px(60), alpha=a)
    if footer:
        a = appear(t, 0.55)
        c.rect((x0, y1 - foot_h + c.px(16), x1, y1), fill="panel2", radius=20, alpha=a)
        size = c.fit_size(footer, x1 - x0 - c.px(60), foot_h * 0.6, 36, 22, "bold")
        c.paragraph(x0 + c.px(30), y1 - foot_h + c.px(40), footer, size, "text", x1 - x0 - c.px(60), kind="bold", alpha=a)


# ---------------------------------------------------------- motion graphics
def motion_cards(c, t, ctx):
    scene = ctx["scene"]
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene, "good")
    text = _text(scene)
    a = appear(t, 0.0, 0.25)
    slide = (1 - a) * c.px(160)
    h = min(c.px(420), (y1 - top) * 0.7)
    cx0 = x0 + slide
    c.rect((cx0, top + c.px(20), x1 + slide, top + c.px(20) + h), fill="panel", radius=26, alpha=a)
    c.circle((cx0 + c.px(80), top + c.px(20) + c.px(80)), c.px(44), fill="good", alpha=a)
    c.label((cx0 + c.px(80), top + c.px(20) + c.px(80)), "\u2713", 52, "bg", kind="bold", anchor="mm", alpha=a)
    size = c.fit_size(text, x1 - x0 - c.px(80), h - c.px(180), 52, 26, "bold")
    c.paragraph(cx0 + c.px(40), top + c.px(20) + c.px(150), text, size, "text", x1 - x0 - c.px(80), kind="bold", alpha=a)


# ---------------------------------------------------------------- simulation
def simulation_scene(c, t, ctx):
    kind = (ctx["record"].get("simulation") or {}).get("kind")
    if kind == "free_fall":
        return sim_draw.free_fall_scene(c, t, ctx)
    if kind == "gas_release":
        return sim_draw.gas_scene(c, t, ctx)
    diagram_cards(c, t, ctx)
    sim_draw._footer(c)


SCENE_FUNCTIONS = {
    "text_card": text_card,
    "3d_scene": hook_card,
    "2d_equation": equation_card,
    "2d_diagram": diagram_cards,
    "comparison": comparison_panels,
    "motion_graphics": motion_cards,
    "simulation": simulation_scene,
    "graph": diagram_cards,
}
