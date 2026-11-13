"""Animated explanatory diagrams and list cards. Each function returns True if it drew something,
or False if the topic has no data for it (the caller then uses a plain card)."""
from animation.simulations import free_fall as ff
from animation.simulations import reaction_layout as rl
from animation.two_d.canvas import appear, clamp, pretty_math
from animation.two_d.icons import draw_icon
from animation.two_d import sim_draw


def _label(c, box, scene, color="accent"):
    """Section names (Demonstration, Conclusion...) are no longer shown. This only keeps the spacing."""
    return box[1] + c.px(80)


def _objects(c, x_hammer, x_feather, bottom, a=1.0):
    sim_draw._draw_hammer(c, x_hammer, bottom)
    sim_draw._draw_feather(c, x_feather, bottom)


# ------------------------------------------------------------------ physics diagrams
def mass_cancels(c, t, ctx):
    """Why mass cancels: more pull and more resistance, so the same acceleration."""
    scene = ctx["scene"]
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene)
    w = x1 - x0
    xh, xf = x0 + 0.27 * w, x0 + 0.73 * w
    head = top + c.px(100)
    _objects(c, xh, xf, head)
    c.label((xh, head + c.px(12)), "heavy", 24, "muted", anchor="ma")
    c.label((xf, head + c.px(12)), "light", 24, "muted", anchor="ma")
    row_h = (y1 - head - c.px(90)) / 3
    rows = [("Gravity pulls harder on the heavy object", "warn"),
            ("It is also harder to get moving", "blue"),
            ("Result: the same acceleration", "good")]
    for k, (title, color) in enumerate(rows):
        a = appear(t, 0.10 + 0.27 * k, 0.14)
        if a <= 0:
            continue
        ry = head + c.px(60) + k * row_h
        c.paragraph((x0 + x1) / 2, ry, title, 30, color, w, kind="bold", align="center", alpha=a)
        base = ry + c.px(52)
        span = row_h - c.px(80)
        if k == 0:
            for x, frac in ((xh, 0.95), (xf, 0.25)):
                c.arrow((x, base), (x, base + span * frac * a), "warn", 10, alpha=a)
        elif k == 1:
            for x, frac in ((xh, 0.36), (xf, 0.10)):
                half = w * frac * a / 2
                c.rect((x - half, base + span * 0.3, x + half, base + span * 0.3 + c.px(36)), fill="blue", radius=10,
                       alpha=a)
        else:
            for x in (xh, xf):
                c.arrow((x, base), (x, base + span * 0.6 * a), "good", 10, alpha=a)
    c.label(((x0 + x1) / 2, y1 - c.px(20)), "Symbolic diagram, not to scale.", 22, "muted", anchor="ms",
            alpha=appear(t, 0.8))
    return True


def drag_vs_gravity(c, t, ctx):
    """Drag compared with weight for the hammer and the feather moving at the same speed (model values)."""
    scene = ctx["scene"]
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene, "warn")
    w = x1 - x0
    speed = 0.8
    mid = top + (y1 - top) * 0.46
    length = (y1 - top) * 0.26
    a = appear(t, 0.05, 0.2)
    c.paragraph((x0 + x1) / 2, top + c.px(6), f"Both moving at {speed} m/s (model)", 28, "muted", w, align="center",
                alpha=a)
    for name, x in (("hammer", x0 + 0.27 * w), ("feather", x0 + 0.73 * w)):
        ratio = ff.drag_to_weight(name, speed)
        grow = appear(t, 0.25, 0.3)
        (sim_draw._draw_hammer if name == "hammer" else sim_draw._draw_feather)(c, x, mid + c.px(40))
        c.arrow((x, mid + c.px(50)), (x, mid + c.px(50) + length * grow), "warn", 10, alpha=a)
        up = max(c.px(8), length * min(ratio, 1.0)) * grow
        c.arrow((x, mid - c.px(62)), (x, mid - c.px(62) - up), "accent", 10, alpha=a)
        c.label((x, mid + c.px(60) + length + c.px(14)), "weight", 24, "warn", anchor="ma", alpha=a)
        c.label((x, mid - c.px(72) - length - c.px(14)), "air resistance", 24, "accent", anchor="md", alpha=a)
        pct = "less than 1%" if ratio < 0.01 else f"{ratio * 100:.0f}%"
        note = f"drag is {pct} of its weight"
        b = appear(t, 0.6)
        c.paragraph(x, mid + c.px(100) + length + c.px(30), name.upper(), 28, "text", w * 0.42, kind="bold",
                    align="center", alpha=b)
        c.paragraph(x, mid + c.px(100) + length + c.px(70), note, 24, "muted", w * 0.42, align="center", alpha=b)
    verdict = "The light object's forces nearly balance, so it speeds up slowly."
    c.paragraph((x0 + x1) / 2, y1 - c.px(140), verdict, 28, "warn", w, kind="bold", align="center",
                alpha=appear(t, 0.75))
    c.label(((x0 + x1) / 2, y1 - c.px(4)), "Illustrative model with assumed values.", 20, "muted", anchor="ms")
    return True


# ------------------------------------------------------------------ chemistry diagrams
def _chem_equation(record):
    for eq in record.get("equations", []):
        if eq.get("type") == "chemical":
            return eq["equation"]
    return None


def reaction_particles(c, t, ctx):
    scene, record = ctx["scene"], ctx["record"]
    equation = _chem_equation(record)
    if not equation:
        return False
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene)
    ax0, ay0, ax1, ay1 = x0, top + c.px(20), x1, y1 - c.px(110)
    aw, ah = ax1 - ax0, ay1 - ay0
    c.rect((ax0, ay0, ax1, ay1), fill=c.inner, radius=24)
    c.label((ax0 + aw * 0.12, ay0 + c.px(24)), "BEFORE", 24, "muted", kind="bold", anchor="mm")
    c.label((ax0 + aw * 0.88, ay0 + c.px(24)), "AFTER", 24, "muted", kind="bold", anchor="mm")
    arrow_a = appear(t, 0.3, 0.2)
    if arrow_a > 0:
        c.arrow((ax0 + aw * 0.40, ay0 + ah * 0.5), (ax0 + aw * 0.60, ay0 + ah * 0.5), "muted", 8, alpha=arrow_a * 0.6)
    flash = clamp((t - 0.38) / 0.17)
    if 0 < flash < 1:
        c.circle((ax0 + aw * 0.5, ay0 + ah * 0.5), aw * 0.22 * flash, outline="warn", width=6, alpha=1 - flash)
    size = 34 if c.portrait else 36
    for token in rl.reaction_tokens(equation, t):
        a = clamp(token["alpha"])
        if a <= 0.02:
            continue
        text = ("" if token["coeff"] == 1 else f"{token['coeff']} ") + pretty_math(token["label"])
        font = c.font("bold", size)
        tw = font.getlength(text) + c.px(40)
        cx, cy = ax0 + token["x"] * aw, ay0 + token["y"] * ah
        color = "accent" if token["gas"] else ("warn" if token["side"] == "reactant" else "good")
        c.rect((cx - tw / 2, cy - c.px(34), cx + tw / 2, cy + c.px(34)), fill="panel2", radius=30, alpha=a)
        c.rect((cx - tw / 2, cy - c.px(34), cx + tw / 2, cy + c.px(34)), outline=color, width=4, radius=30, alpha=a)
        c.d.text((cx, cy), text, font=font, fill=c.col("text", a), anchor="mm")
        if token["gas"] and a > 0.3:
            c.label((cx, cy - c.px(48)), "gas", 22, "accent", anchor="md", alpha=a)
    c.paragraph((x0 + x1) / 2, y1 - c.px(90), "Atoms rearrange into new substances.", 32, "text", x1 - x0,
                kind="bold", align="center", alpha=appear(t, 0.62))
    c.label(((x0 + x1) / 2, y1 - c.px(8)), "Illustration of the idea, not a simulation of real molecules.", 20, "muted",
            anchor="ms")
    return True


def _container_panel(c, box, title, open_container, t, color):
    px0, py0, px1, py1 = box
    pw, ph = px1 - px0, py1 - py0
    c.rect(box, fill=c.inner, radius=20)
    c.label(((px0 + px1) / 2, py0 + c.px(14)), title, 28, color, kind="bold", anchor="ma")
    cx0, cy0, cx1, cy1 = px0 + pw * 0.22, py0 + ph * 0.28, px1 - pw * 0.22, py1 - ph * 0.12
    cw, ch = cx1 - cx0, cy1 - cy0
    c.d.line([(cx0, cy0), (cx0, cy1), (cx1, cy1), (cx1, cy0)], fill=c.col("text"), width=max(2, round(6 * c.u)),
             joint="curve")
    if not open_container:
        c.rect((cx0 - c.px(10), cy0 - c.px(16), cx1 + c.px(10), cy0 - c.px(2)), fill="muted", radius=6)
    atoms = rl.gas_escape_atoms(open_container, t)
    for i, (x, y, inside) in enumerate(atoms):
        ax, ay = cx0 + x * cw, cy0 + y * ch
        is_liquid = i < rl.ATOM_COUNT // 3
        fade = 1.0 if y > -0.1 else clamp(1 + (y + 0.1) / 0.4)
        if fade > 0.02:
            c.circle((ax, ay), c.px(11), fill="blue" if is_liquid else "accent", alpha=fade)
    inside = rl.atoms_inside(open_container, t)
    c.label(((px0 + px1) / 2, py1 + c.px(10)), f"Atoms inside the container: {inside} of {rl.ATOM_COUNT}", 24,
            "text", anchor="ma")


def gas_escape(c, t, ctx):
    scene = ctx["scene"]
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene, "warn")
    gap = c.px(70)
    foot = c.px(120)
    if c.portrait:
        h = (y1 - top - foot - gap) / 2
        panels = [(x0, top, x1, top + h), (x0, top + h + gap, x1, top + h + gap + h)]
    else:
        w = (x1 - x0 - gap) / 2
        panels = [(x0, top, x0 + w, y1 - foot), (x0 + w + gap, top, x1, y1 - foot)]
    _container_panel(c, panels[0], "OPEN CONTAINER", True, t, "warn")
    _container_panel(c, panels[1], "SEALED CONTAINER", False, t, "good")
    c.paragraph((x0 + x1) / 2, y1 - c.px(72), "Gas that escapes carries its mass with it.", 30, "text", x1 - x0,
                kind="bold", align="center", alpha=appear(t, 0.65))
    c.label(((x0 + x1) / 2, y1 - c.px(4)), "Illustration of the idea; atom counts are for clarity.", 20, "muted",
            anchor="ms")
    return True


# ------------------------------------------------------------------ list cards
def _rows_area(c):
    x0, y0, x1, y1 = c.content_box()
    return x0, x1, y1


def term_chips(c, t, ctx):
    scene = ctx["scene"]
    terms = scene.get("data", {}).get("terms") or []
    if not terms:
        return False
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene)
    n = len(terms)
    row = min(c.px(150), (y1 - top - c.px(20)) / n)
    colors = ["accent", "blue", "violet", "good", "warn", "bad"]
    for i, term in enumerate(terms):
        a = appear(t, 0.08 + 0.14 * i, 0.15)
        if a <= 0:
            continue
        y = top + c.px(10) + i * row
        chip = c.px(120)
        c.rect((x0, y, x0 + chip, y + row - c.px(18)), fill="panel", radius=22, alpha=a)
        c.rect((x0, y, x0 + chip, y + row - c.px(18)), outline=colors[i % 6], width=4, radius=22, alpha=a)
        c.d.text((x0 + chip / 2, y + (row - c.px(18)) / 2), term["symbol"], font=c.font("bold", 54),
                 fill=c.col(colors[i % 6], a), anchor="mm")
        size = c.fit_size(term["term"], x1 - x0 - chip - c.px(50), row * 0.5, 40, 24, "bold")
        c.paragraph(x0 + chip + c.px(30), y + c.px(6), term["term"], size, "text", x1 - x0 - chip - c.px(50),
                    kind="bold", alpha=a)
        c.paragraph(x0 + chip + c.px(30), y + (row - c.px(18)) * 0.62, "unit: " + pretty_math(term["unit"]), 26,
                    "muted", x1 - x0 - chip - c.px(50), alpha=a)
    return True


def checklist(c, t, ctx):
    scene = ctx["scene"]
    items = scene.get("data", {}).get("items") or []
    if not items:
        return False
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene, "blue")
    n = len(items)
    avail = y1 - top - c.px(10)
    row = min(c.px(190), avail / n)
    for i, item in enumerate(items):
        a = appear(t, 0.08 + 0.18 * i, 0.15)
        if a <= 0:
            continue
        y = top + c.px(10) + i * row
        c.rect((x0, y, x1, y + row - c.px(16)), fill="panel", radius=20, alpha=a)
        c.circle((x0 + c.px(52), y + (row - c.px(16)) / 2), c.px(28), fill="good", alpha=a)
        c.d.line([(x0 + c.px(40), y + (row - c.px(16)) / 2), (x0 + c.px(49), y + (row - c.px(16)) / 2 + c.px(9)),
                  (x0 + c.px(66), y + (row - c.px(16)) / 2 - c.px(10))], fill=c.col("panel2", a),
                 width=max(1, round(6 * c.u)), joint="curve")
        size = c.fit_size(item, x1 - x0 - c.px(140), (row - c.px(30)) * 0.9, 36, 22)
        th = c.text_height(c.wrap(item, c.font("sans", size), x1 - x0 - c.px(140)), size)
        c.paragraph(x0 + c.px(100), y + (row - c.px(16) - th) / 2, item, size, "text", x1 - x0 - c.px(140), alpha=a)
    return True


def sources_list(c, t, ctx):
    scene = ctx["scene"]
    sources = scene.get("data", {}).get("sources") or []
    if not sources:
        return False
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene, "muted")
    n = len(sources)
    row = min(c.px(190), (y1 - top - c.px(10)) / n)
    for i, src in enumerate(sources):
        a = appear(t, 0.08 + 0.16 * i, 0.15)
        if a <= 0:
            continue
        y = top + c.px(10) + i * row
        c.rect((x0, y, x1, y + row - c.px(16)), fill="panel", radius=20, alpha=a)
        draw_icon(c, "document", x0 + c.px(64), y + (row - c.px(16)) / 2, c.px(44), 0.0, a)
        size = c.fit_size(src["title"], x1 - x0 - c.px(170), (row - c.px(30)) * 0.55, 32, 20, "bold")
        bottom = c.paragraph(x0 + c.px(130), y + c.px(14), src["title"], size, "text", x1 - x0 - c.px(170),
                             kind="bold", alpha=a)
        c.paragraph(x0 + c.px(130), bottom + c.px(2), src["publisher"], 24, "muted", x1 - x0 - c.px(170), alpha=a)
    return True


def safety_card(c, t, ctx):
    scene = ctx["scene"]
    items = scene.get("data", {}).get("items") or []
    if not items:
        return False
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _label(c, box, scene, "warn")
    secs = t * scene.get("duration_seconds", 5)
    a = appear(t, 0.0, 0.2)
    radius = c.px(100)
    draw_icon(c, "warning", (x0 + x1) / 2 if c.portrait else x0 + radius + c.px(20), top + radius + c.px(20), radius,
              secs, a)
    left = x0 if c.portrait else x0 + 2 * radius + c.px(80)
    start = top + 2 * radius + c.px(70) if c.portrait else top + c.px(30)
    n = len(items)
    row = min(c.px(150), (y1 - start) / n)
    for i, item in enumerate(items):
        b = appear(t, 0.2 + 0.18 * i, 0.15)
        if b <= 0:
            continue
        y = start + i * row
        c.circle((left + c.px(16), y + c.px(24)), c.px(12), fill="warn", alpha=b)
        size = c.fit_size(item, x1 - left - c.px(60), row - c.px(20), 34, 22)
        c.paragraph(left + c.px(48), y, item, size, "text", x1 - left - c.px(60), alpha=b)
    return True


def outro_card(c, t, ctx):
    """End card: channel name, a line of text and an honest note about the voice and animations."""
    scene = ctx["scene"]
    data = scene.get("data", {})
    channel = data.get("channel") or scene.get("on_screen_text", "")
    if not channel:
        return False
    box = c.content_box()
    x0, y0, x1, y1 = box
    a = appear(t, 0.0, 0.3)
    mid = (y0 + y1) / 2
    draw_icon(c, "atom", (x0 + x1) / 2, mid - c.px(210), c.px(100), t * scene.get("duration_seconds", 3), a)
    size = c.fit_size(channel, x1 - x0, c.px(200), 80, 34, "bold")
    bottom = c.paragraph((x0 + x1) / 2, mid - c.px(70), channel, size, "text", x1 - x0, kind="bold", align="center",
                         alpha=a)
    c.rect(((x0 + x1) / 2 - c.px(70), bottom + c.px(14), (x0 + x1) / 2 + c.px(70), bottom + c.px(20)), fill="accent",
           alpha=a)
    if data.get("line"):
        c.paragraph((x0 + x1) / 2, bottom + c.px(46), data["line"], 36, "muted", x1 - x0, align="center",
                    alpha=appear(t, 0.25, 0.3))
    c.paragraph((x0 + x1) / 2, y1 - c.px(60), "Narration is a synthetic voice. Animations are illustrations.", 24,
                "muted", x1 - x0, align="center", alpha=appear(t, 0.4, 0.3))
    return True


DIAGRAMS = {
    "mass_cancels": mass_cancels,
    "drag_vs_gravity": drag_vs_gravity,
    "reaction_particles": reaction_particles,
    "gas_escape": gas_escape,
}
