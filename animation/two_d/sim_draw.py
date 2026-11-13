"""Draws the simulations (free fall and gas release) as 2D frames."""
import math

from animation.simulations import free_fall as ff
from animation.two_d import illustrations
from animation.simulations import gas_release as gas
from animation.two_d.canvas import appear, clamp, pretty_math

NOTE = "Illustrative model with assumed values. Not experimental evidence."


# ------------------------------------------------------------------ helpers
def _banner(c, box, text, color):
    x0, y0, x1, _ = box
    c.rect((x0, y0, x1, y0 + c.px(64)), fill=c.inner, radius=14)
    c.rect((x0, y0, x0 + c.px(10), y0 + c.px(64)), fill=color)
    c.label((x0 + c.px(30), y0 + c.px(32)), text, 34, color, kind="bold", anchor="lm")


def _footer(c, extra=""):
    y = 0.805 * c.h
    c.paragraph(c.w / 2, y, NOTE + (" " + extra if extra else ""), 24, "muted", max_width=c.w * 0.88,
                align="center", line_gap=1.2)


ROLE_BANNER = {
    "correct_procedure": ("CORRECT", "good"), "overlooked": ("OVERLOOKED / INCORRECT", "warn"),
    "consequences": ("CONSEQUENCE", "bad"), "demonstration": ("DEMONSTRATION", "accent"),
}


def _role_banner(c, box, role, extra=None):
    """Only the right / wrong / consequence markers are shown. Plain demonstrations carry no label.
    Returns True if a banner was drawn."""
    if role not in ("correct_procedure", "overlooked", "consequences"):
        return False
    text, color = ROLE_BANNER[role]
    if extra:
        text += "  -  " + extra
    _banner(c, box, text, color)
    return True


# ------------------------------------------------------------------ free fall
def _draw_hammer(c, x, bottom):
    if c.theme.name != "classic":
        illustrations.draw_hammer(c.d, x, bottom, c.px(112) / 390.0, c.u * 0.75)
        return
    c.rect((x - c.px(7), bottom - c.px(52), x + c.px(7), bottom), fill="warn", radius=4)
    c.rect((x - c.px(40), bottom - c.px(84), x + c.px(40), bottom - c.px(48)), fill="muted", radius=6)


def _draw_feather(c, x, bottom):
    if c.theme.name != "classic":
        illustrations.draw_feather(c.d, x, bottom, c.px(112) / 390.0, c.u * 0.75)
        return
    c.line((x, bottom - c.px(86)), (x, bottom), "text", 3)
    c.d.ellipse((x - c.px(13), bottom - c.px(86), x + c.px(13), bottom - c.px(14)), fill=c.col("accent"))


def _panel(c, box, title, color, sims, t_sim, accent_note=None, wrong=False):
    x0, y0, x1, y1 = box
    c.rect(box, fill=c.inner, radius=18)
    c.label(((x0 + x1) / 2, y0 + c.px(22)), title, 28, color, kind="bold", anchor="ma")
    ground = y1 - c.px(46)
    top = y0 + c.px(160)
    c.rect((x0 + c.px(14), ground, x1 - c.px(14), ground + c.px(8)), fill="muted")
    positions = {"hammer": x0 + (x1 - x0) * 0.32, "feather": x0 + (x1 - x0) * 0.68}
    done = True
    for name in ("hammer", "feather"):
        sim = sims[name]
        height_m, _ = ff.state_at(sim, t_sim)
        bottom = ground - (height_m / sim["height"]) * (ground - top - c.px(90))
        (_draw_hammer if name == "hammer" else _draw_feather)(c, positions[name], bottom)
        landed = sim["t_land"] is not None and t_sim >= sim["t_land"]
        done = done and landed
        c.label((positions[name], ground + c.px(20)), name, 24, "muted", anchor="ma")
    times = [f"{n} lands at {sims[n]['t_land']:.2f} s" for n in ("hammer", "feather")
             if sims[n]["t_land"] is not None and t_sim >= sims[n]["t_land"]]
    for i, line in enumerate(times):
        c.label(((x0 + x1) / 2, y0 + c.px(98) + i * c.px(26)), line, 22, "text", anchor="ma")
    if done:
        result = ff.landing_summary(sims["hammer"], sims["feather"])
        if result == "together":
            text, tone = "Both land together", "good"
        else:
            text, tone = "Hammer lands first", "bad" if wrong else "warn"
        c.label(((x0 + x1) / 2, y0 + c.px(60)), text, 30, tone, kind="bold", anchor="ma")


def _graph(c, box, curves, t_sim, t_end):
    """Speed against time. curves = [(label, color, sim, dashed)]."""
    x0, y0, x1, y1 = box
    c.rect(box, fill=c.inner, radius=18)
    left, right = x0 + c.px(90), x1 - c.px(30)
    top, bottom = y0 + c.px(46), y1 - c.px(50)
    c.line((left, top), (left, bottom), "muted", 3)
    c.line((left, bottom), (right, bottom), "muted", 3)
    v_max = max(max(sim["v"]) for _, _, sim, _ in curves) * 1.08
    c.label(((x0 + x1) / 2, y0 + c.px(12)), "Speed against time (model)", 24, "muted", anchor="ma")
    c.label((left - c.px(10), top), f"{v_max:.1f}", 20, "muted", anchor="rm")
    c.label((left - c.px(10), bottom), "0", 20, "muted", anchor="rm")
    c.label((left, bottom + c.px(10)), "0", 20, "muted", anchor="ma")
    c.label((right, bottom + c.px(10)), f"{t_end:.1f} s", 20, "muted", anchor="ma")
    c.label((left - c.px(60), (top + bottom) / 2), "m/s", 20, "muted", anchor="mm")
    for index, (label, color, sim, dashed) in enumerate(curves):
        pts, step = [], 0.01
        steps = int(min(t_sim, sim["t_land"] or t_sim) / step) + 1
        for i in range(steps + 1):
            tt = min(i * step, t_sim)
            _, v = ff.state_at(sim, tt)
            pts.append((left + (tt / t_end) * (right - left), bottom - (v / v_max) * (bottom - top)))
        if len(pts) > 1:
            if dashed:
                for a, b in list(zip(pts, pts[1:]))[::2]:
                    c.line(a, b, color, 7)
            else:
                c.d.line(pts, fill=c.col(color), width=max(1, round(5 * c.u)), joint="curve")
        ly = top + c.px(10) + index * c.px(30)
        c.line((right - c.px(330), ly), (right - c.px(290), ly), color, 7)
        c.label((right - c.px(278), ly), label, 22, color, anchor="lm")


def free_fall_scene(c, t, ctx):
    scene, record = ctx["scene"], ctx["record"]
    data = scene.get("data", {})
    variant = data.get("simulation_variant") or "air_vs_vacuum"
    x0, y0, x1, y1 = c.content_box()
    role = scene.get("section_kind", "demonstration")
    wrong = variant == "wrong_mass_model"
    has_banner = _role_banner(c, (x0, y0, x1, y1), role, "slow motion")

    if variant == "air_vs_vacuum":
        specs = [("VACUUM (no air)", "good", False, 1.0), ("WITH AIR", "warn", True, 1.0)]
    elif variant == "vacuum":
        specs = [("VACUUM (no air)", "good", False, 1.0)]
    elif variant == "with_air":
        specs = [("WITH AIR", "warn", True, 1.0)]
    else:  # wrong_mass_model
        specs = [("INCORRECT MODEL: heavier = faster", "bad", False, 1.0)]

    panels = []
    for title, color, in_air, _ in specs:
        sims = {"hammer": ff.simulate("hammer", in_air, accel_scale=1.7 if wrong else 1.0),
                "feather": ff.simulate("feather", in_air)}
        panels.append((title, color, sims))
    t_end = max(s["t_land"] for _, _, sims in panels for s in sims.values()) + 0.25
    t_sim = clamp((t - 0.10) / 0.70) * t_end

    area_top = y0 + c.px(84 if has_banner else 10)
    area_bottom = y1 - (c.px(400) if c.portrait else c.px(330))
    gap = c.px(20)
    width = (x1 - x0 - gap * (len(panels) - 1)) / len(panels)
    for i, (title, color, sims) in enumerate(panels):
        left = x0 + i * (width + gap)
        _panel(c, (left, area_top, left + width, area_bottom), title, color, sims, t_sim, wrong=wrong)

    curves = []
    for title, color, sims in panels:
        if "AIR" in title and "VACUUM" not in title:
            curves += [("hammer in air", "warn", sims["hammer"], False), ("feather in air", "accent", sims["feather"], False)]
        elif len(panels) > 1:
            curves.append(("vacuum (both objects)", "text", sims["hammer"], True))
        else:
            curves += [("hammer", "warn", sims["hammer"], False), ("feather", "accent", sims["feather"], True)]
    _graph(c, (x0, area_bottom + c.px(16), x1, y1 + (0 if c.portrait else c.px(0))), curves, t_sim, t_end)
    _footer(c)


# ------------------------------------------------------------------ gas release
def _container(c, cx, bottom, width, height):
    return (cx - width / 2, bottom - height, cx + width / 2, bottom)


def _draw_beaker(c, box, p, t, variant, bubbles):
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    liquid_top = y1 - height * 0.42
    c.rect((x0, liquid_top, x1, y1), fill="blue", alpha=0.35)
    sealed = variant in ("sealed", "sealed_pop", "balance_sealed")
    if sealed and p > 0:
        rng_x = [0.15, 0.4, 0.65, 0.85, 0.28, 0.52, 0.74, 0.2, 0.6, 0.45, 0.8, 0.33]
        rng_y = [0.2, 0.5, 0.3, 0.7, 0.8, 0.15, 0.6, 0.4, 0.9, 0.65, 0.25, 0.55]
        count = int(len(rng_x) * clamp(p))
        for i in range(count):
            gx = x0 + width * rng_x[i]
            gy = y0 + (liquid_top - y0) * rng_y[i]
            c.circle((gx, gy), c.px(9), outline="accent", width=3, alpha=0.9)
        c.rect((x0 + c.px(4), y0 + c.px(4), x1 - c.px(4), liquid_top), fill="accent", alpha=0.06 + 0.12 * clamp(p))
    active = round(len(bubbles) * clamp(0.35 + 1.0 * (1 - p)))
    for b in bubbles[:active]:
        h = gas.bubble_height(b, t)
        bx = x0 + width * b["x"]
        if sealed:
            by = y1 - c.px(10) - h * (y1 - liquid_top - c.px(10))
            alpha = 0.85
        else:
            rise = (y1 - y0) * 1.25
            by = y1 - c.px(10) - h * rise
            alpha = 0.85 * (1 - clamp((h - 0.75) / 0.25))
        if alpha > 0.05:
            c.circle((bx, by), b["radius"] * width * 1.15, outline="text", width=3, alpha=alpha)
    c.d.line([(x0, y0), (x0, y1), (x1, y1), (x1, y0)], fill=c.col("text"), width=max(2, round(6 * c.u)), joint="curve")


def _gauge_bar(c, box, value, label, color="warn"):
    x0, y0, x1, y1 = box
    c.rect(box, outline="muted", width=3, radius=8)
    fill_top = y1 - (y1 - y0) * clamp(value)
    if value > 0.01:
        c.rect((x0 + c.px(4), fill_top, x1 - c.px(4), y1 - c.px(4)), fill=color, radius=4)
    c.label(((x0 + x1) / 2, y0 - c.px(14)), label, 22, "muted", anchor="md")


def _draw_scale(c, cx, y, reading):
    """A balance: platform plus a dial with a needle that swings left as the reading drops."""
    c.rect((cx - c.px(230), y, cx + c.px(230), y + c.px(34)), fill="muted", radius=12)
    dial_c = (cx, y + c.px(150))
    r = c.px(110)
    c.d.arc((dial_c[0] - r, dial_c[1] - r, dial_c[0] + r, dial_c[1] + r), 180, 360, fill=c.col("muted"),
            width=max(2, round(6 * c.u)))
    swing = (1.0 - reading) / 0.12 * 40.0
    angle = math.radians(-90 - swing)
    tip = (dial_c[0] + r * 0.92 * math.cos(angle), dial_c[1] + r * 0.92 * math.sin(angle))
    c.line(dial_c, tip, "warn", 8)
    c.circle(dial_c, c.px(10), fill="text")
    c.label((cx, dial_c[1] + c.px(26)), "Balance reading (relative)", 22, "muted", anchor="ma")


def gas_scene(c, t, ctx):
    scene = ctx["scene"]
    data = scene.get("data", {})
    variant = data.get("simulation_variant") or "open"
    if variant not in gas.VARIANTS:
        variant = "open"
    x0, y0, x1, y1 = c.content_box()
    role = scene.get("section_kind", "demonstration")
    _role_banner(c, (x0, y0, x1, y1), role)

    bubbles = gas.make_bubbles()
    p = gas.reaction_progress(t)
    cx = (x0 + x1) / 2 - (c.px(60) if variant in ("sealed", "sealed_pop") else 0)
    balance = variant.startswith("balance")
    bottom = y1 - (c.px(250) if balance else c.px(70))
    box = _container(c, cx, bottom, c.px(360), c.px(430 if c.portrait else 400))
    bx0, by0, bx1, by1 = box

    if balance:
        _draw_scale(c, cx, bottom, gas.scale_reading(variant, t))
    _draw_beaker(c, box, p, t, variant, bubbles)

    if variant in ("sealed", "sealed_pop", "balance_sealed"):
        lift = gas.lid_lift(variant, t)
        if variant == "balance_sealed":
            radius = c.px(46) + c.px(70) * p
            c.rect((cx - c.px(40), by0 - c.px(30), cx + c.px(40), by0 + c.px(4)), fill="muted", radius=6)
            c.circle((cx, by0 - c.px(30) - radius), radius, fill="accent", alpha=0.35 + 0.3 * p)
            c.circle((cx, by0 - c.px(30) - radius), radius, outline="accent", width=4)
            c.label((cx + radius + c.px(16), by0 - c.px(30) - radius), "balloon catches the gas", 24, "accent", anchor="lm")
        else:
            lid_y = by0 - c.px(26) - lift * c.px(230)
            c.rect((bx0 - c.px(14), lid_y, bx1 + c.px(14), lid_y + c.px(26)), fill="muted", radius=8)
            if lift > 0:
                for k in range(7):
                    ang = math.radians(200 + k * 23)
                    c.line((cx + c.px(140) * math.cos(ang), by0 - c.px(20) + c.px(60) * math.sin(ang)),
                           (cx + c.px(210) * math.cos(ang), by0 - c.px(20) + c.px(110) * math.sin(ang)), "warn", 6)
                c.label((cx, lid_y - c.px(40)), "Lid pops off!", 36, "bad", kind="bold", anchor="ma")
        if variant in ("sealed", "sealed_pop"):
            gx0 = bx1 + c.px(70)
            _gauge_bar(c, (gx0, by0, gx0 + c.px(54), by1), gas.pressure(variant, t), "Pressure (relative)")
    elif variant == "open":
        c.arrow((cx, by0 - c.px(14)), (cx, by0 - c.px(110)), "accent", 8, alpha=appear(t, 0.2))
        c.label((cx, by0 - c.px(130)), "CO\u2082 escapes into the air", 28, "accent", kind="bold", anchor="md",
                alpha=appear(t, 0.2))
    elif variant == "balance_open":
        c.arrow((cx, by0 - c.px(14)), (cx, by0 - c.px(100)), "warn", 8, alpha=appear(t, 0.2))
        c.label((cx, by0 - c.px(118)), "gas leaves: reading falls", 28, "warn", kind="bold", anchor="md",
                alpha=appear(t, 0.2))

    c.label((cx, by1 + c.px(16 if not balance else 190)), {
        "open": "open container", "sealed": "sealed container", "sealed_pop": "sealed container",
        "balance_open": "open container on a balance", "balance_sealed": "balloon-sealed container on a balance",
    }[variant], 26, "muted", anchor="ma")
    extra = "Exaggerated for clarity." if balance or variant.startswith("sealed") else ""
    _footer(c, extra)
