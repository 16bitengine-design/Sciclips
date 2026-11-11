"""Cartoon illustrations drawn from flat shapes with thick outlines: hammer and feather characters on the
Moon, and a beaker full of bubbles. Used for opening scenes and thumbnails.

Everything is drawn twice as large and shrunk afterwards, which smooths the edges.
"""
import math
import random

from PIL import Image, ImageDraw

from animation.simulations import free_fall as ff
from animation.simulations import gas_release as gas
from animation.two_d.backgrounds import _gradient
from animation.two_d import asset_designer
from animation.two_d.canvas import Canvas

INK = (22, 14, 58)
STEEL, STEEL_LIGHT = (148, 166, 204), (206, 220, 248)
WOOD, WOOD_DARK = (222, 154, 84), (176, 112, 52)
PINK, PINK_LIGHT = (255, 120, 170), (255, 196, 218)
CHEEK = (255, 120, 140, 150)


def _clamp(x):
    return max(0.0, min(1.0, x))


def _ow(s, width=6):
    return max(3, round(width * s))


# ------------------------------------------------------------------ small drawing helpers
def _poly(d, pts, fill, s, width=6):
    d.polygon(pts, fill=fill, outline=INK, width=_ow(s, width))


def _ellipse(d, box, fill, s, width=6):
    d.ellipse(box, fill=fill, outline=INK, width=_ow(s, width))


def _rrect(d, box, radius, fill, s, width=6):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=INK, width=_ow(s, width))


def _sparkle(d, cx, cy, r, color):
    pts = []
    for i in range(8):
        rr = r if i % 2 == 0 else r * 0.28
        a = i * math.pi / 4 - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=color)


def _face(d, cx, cy, size, s, look=(0.0, 0.3), mood="happy"):
    """Two eyes, rosy cheeks and a smile. `look` moves the pupils (-1 to 1)."""
    eye_dx, eye_r = size * 0.24, size * 0.13
    for sign in (-1, 1):
        ex = cx + sign * eye_dx
        d.ellipse((ex - eye_r, cy - eye_r * 1.25, ex + eye_r, cy + eye_r * 1.25), fill=(255, 255, 255), outline=INK,
                  width=_ow(s, 4))
        px, py = ex + look[0] * eye_r * 0.45, cy + look[1] * eye_r * 0.5
        pr = eye_r * 0.55
        d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=INK)
        d.ellipse((px - pr * 0.1, py - pr * 0.75, px + pr * 0.5, py - pr * 0.15), fill=(255, 255, 255))
        d.ellipse((cx + sign * size * 0.42 - size * 0.07, cy + size * 0.12, cx + sign * size * 0.42 + size * 0.07,
                   cy + size * 0.24), fill=CHEEK)
    mw = size * (0.26 if mood == "happy" else 0.18)
    d.arc((cx - mw, cy + size * 0.02, cx + mw, cy + size * 0.30), 15, 165, fill=INK, width=_ow(s, 5))


# ------------------------------------------------------------------ characters
def draw_hammer(d, cx, bottom, k, s, look=(0.0, 0.4)):
    """A hammer character. k scales it (the whole figure is about 380 * k tall)."""
    handle = (cx - 22 * k, bottom - 270 * k, cx + 22 * k, bottom)
    _rrect(d, handle, 16 * k, WOOD, s)
    for i in range(4):
        y = bottom - (60 + i * 55) * k
        d.line([(cx - 10 * k, y), (cx + 10 * k, y - 14 * k)], fill=WOOD_DARK, width=_ow(s, 4))
    head = (cx - 120 * k, bottom - 390 * k, cx + 120 * k, bottom - 262 * k)
    _rrect(d, head, 34 * k, STEEL, s)
    d.rounded_rectangle((head[0] + 18 * k, head[1] + 14 * k, head[2] - 18 * k, head[1] + 34 * k), radius=10 * k,
                        fill=STEEL_LIGHT)
    _face(d, cx, head[1] + 66 * k, 120 * k, s, look)


def draw_feather(d, cx, bottom, k, s, look=(0.0, 0.4)):
    """A feather character with a face. About 380 * k tall."""
    length = 340 * k
    spine = lambda t: (cx + 38 * k * math.sin(t * math.pi * 0.9), bottom - 40 * k - t * length)  # noqa: E731
    width = lambda t: 66 * k * (math.sin(math.pi * min(1.0, max(0.0, t))) ** 0.7)  # noqa: E731
    d.line([(cx, bottom), spine(0.1)], fill=INK, width=_ow(s, 12))
    d.line([(cx, bottom), spine(0.1)], fill=(255, 250, 240), width=_ow(s, 5))
    left, right = [], []
    for i in range(0, 21):
        t = 0.08 + 0.92 * i / 20
        x, y = spine(t)
        left.append((x - width(t), y))
        right.append((x + width(t), y))
    outline = left + right[::-1]
    _poly(d, outline, PINK, s)
    mid_l, mid_r = [], []
    for i in range(0, 21):
        t = 0.12 + 0.8 * i / 20
        x, y = spine(t)
        mid_l.append((x - width(t) * 0.32, y))
        mid_r.append((x + width(t) * 0.32, y))
    d.polygon(mid_l + mid_r[::-1], fill=PINK_LIGHT)
    for i in range(1, 8):
        t = 0.12 + 0.11 * i
        x, y = spine(t)
        for sign in (-1, 1):
            d.line([(x + sign * width(t) * 0.55, y + 8 * k), (x + sign * width(t) * 0.95, y - 6 * k)], fill=INK,
                   width=_ow(s, 3))
    fx, fy = spine(0.52)
    _face(d, fx, fy - 6 * k, 96 * k, s, look)


# ------------------------------------------------------------------ the Moon scene
SUN = (0.55, 0.38, -0.35)


def _moon_heights(t):
    hammer, feather = ff.simulate("hammer", False), ff.simulate("feather", False)
    t_end = max(hammer["t_land"], feather["t_land"]) + 0.3
    sim_t = _clamp((t - 0.30) / 0.55) * t_end
    return ff.state_at(hammer, sim_t)[0], ff.state_at(feather, sim_t)[0]


def moon_scene(c, box, t, secs):
    d = c.d
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0, y1 - y0
    s = min(w, h) / 1000.0
    c.img.paste(_gradient(w, h, (30, 20, 92), (96, 52, 168)), (x0, y0))
    rng = random.Random(7)
    for i in range(28):
        sx, sy = x0 + rng.uniform(0.03, 0.97) * w, y0 + rng.uniform(0.03, 0.62) * h
        r = rng.uniform(7, 20) * s * (0.75 + 0.25 * math.sin(secs * 3 + i))
        _sparkle(d, sx, sy, r, rng.choice([(255, 236, 130), (255, 255, 255), (170, 230, 255)]))
    ex, ey, er = x0 + 0.82 * w, y0 + 0.20 * h, 0.12 * min(w, h)
    _ellipse(d, (ex - er, ey - er, ex + er, ey + er), (70, 156, 242), s)
    for blob in ([(-0.5, -0.3), (-0.1, -0.55), (0.25, -0.2), (-0.1, 0.1)], [(0.1, 0.35), (0.5, 0.2), (0.45, 0.6)]):
        d.polygon([(ex + bx * er * 0.85, ey + by * er * 0.85) for bx, by in blob], fill=(96, 206, 130))
    d.arc((ex - er * 0.8, ey - er * 0.8, ex + er * 0.8, ey + er * 0.8), 200, 260, fill=(255, 255, 255), width=_ow(s, 6))
    ground_y = y0 + 0.80 * h
    _ellipse(d, (x0 - 0.15 * w, y0 + 0.70 * h, x1 + 0.15 * w, y0 + 1.50 * h), (214, 216, 238), s, 7)
    d.arc((x0 - 0.05 * w, y0 + 0.73 * h, x1 + 0.05 * w, y0 + 1.1 * h), 205, 335, fill=(255, 255, 255), width=_ow(s, 9))
    for cxr, cyr, rr in ((0.18, 0.90, 0.10), (0.80, 0.93, 0.13), (0.55, 0.97, 0.08), (0.36, 0.85, 0.05)):
        ccx, ccy, crx = x0 + cxr * w, y0 + cyr * h, rr * w
        _ellipse(d, (ccx - crx, ccy - crx * 0.32, ccx + crx, ccy + crx * 0.32), (178, 180, 212), s, 5)
        d.ellipse((ccx - crx * 0.7, ccy - crx * 0.18, ccx + crx * 0.7, ccy + crx * 0.22), fill=(150, 152, 190))
    hm, hf = _moon_heights(t)
    top_bottom = y0 + 0.54 * h
    k = 0.37 * h / 390.0
    falling = 0.30 < t < 0.88
    for name, cx, hh, drawer in (("hammer", x0 + 0.34 * w, hm, draw_hammer), ("feather", x0 + 0.66 * w, hf, draw_feather)):
        frac = hh / ff.HEIGHT
        bottom = ground_y - frac * (ground_y - top_bottom)
        shade = 0.55 + 0.45 * (1 - frac)
        sw = (0.13 if name == "hammer" else 0.09) * w * shade
        d.ellipse((cx - sw, ground_y + 6 * s, cx + sw, ground_y + 6 * s + sw * 0.28), fill=(120, 122, 160, 200))
        if falling and hh > 0.02:
            for j in range(3):
                off = (j - 1) * 46 * k
                d.line([(cx + off, bottom - 400 * k - 60 * k - j * 10 * k), (cx + off, bottom - 400 * k - 120 * k)],
                       fill=(255, 255, 255, 190), width=_ow(s, 6))
        look = (0.0, 0.7) if falling else (0.0, 0.0)
        drawer(d, cx, bottom, k, s, look)
        if t > 0.86 and hh < 0.05:
            for dx, rad in ((-0.1, 16), (0.12, 22), (0.0, 12)):
                px, py = cx + dx * w, ground_y + 4 * s
                d.ellipse((px - rad * s, py - rad * s * 1.4, px + rad * s, py), fill=(255, 255, 255, 200))


# ------------------------------------------------------------------ the beaker scene
def beaker_scene(c, box, t, secs):
    d = c.d
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0, y1 - y0
    s = min(w, h) / 1000.0
    c.img.paste(_gradient(w, h, (24, 150, 160), (60, 40, 150)), (x0, y0))
    rng = random.Random(3)
    for i in range(18):
        _sparkle(d, x0 + rng.uniform(0.04, 0.96) * w, y0 + rng.uniform(0.04, 0.5) * h,
                 rng.uniform(8, 18) * s * (0.75 + 0.25 * math.sin(secs * 3 + i)),
                 rng.choice([(255, 236, 130), (255, 255, 255), (255, 150, 200)]))
    table_y = y0 + 0.84 * h
    _rrect(d, (x0 - 20, table_y, x1 + 20, y1 + 20), 26 * s, (255, 196, 84), s, 7)
    cx = x0 + 0.5 * w
    top_w, bot_w, glass_h = 0.50 * w, 0.42 * w, 0.66 * h
    top_y, bot_y = table_y - glass_h, table_y
    glass = [(cx - top_w / 2, top_y), (cx - bot_w / 2, bot_y), (cx + bot_w / 2, bot_y), (cx + top_w / 2, top_y)]
    d.polygon(glass, fill=(235, 250, 255, 90))
    p = gas.reaction_progress(t)
    surface = top_y + glass_h * 0.38
    wobble = 7 * s * math.sin(secs * 4)
    half = lambda y: (top_w + (bot_w - top_w) * ((y - top_y) / glass_h)) / 2 - 8 * s  # noqa: E731
    liquid = [(cx - half(surface), surface + wobble)]
    for i in range(1, 8):
        x = cx - half(surface) + 2 * half(surface) * i / 8
        liquid.append((x, surface + wobble * (1 if i % 2 else -1)))
    liquid += [(cx + half(surface), surface - wobble), (cx + half(bot_y), bot_y - 8 * s), (cx - half(bot_y), bot_y - 8 * s)]
    d.polygon(liquid, fill=(255, 92, 170), outline=INK, width=_ow(s, 5))
    d.polygon([(cx - half(surface) + 12 * s, surface + 34 * s), (cx + half(surface) - 12 * s, surface + 34 * s),
               (cx + half(bot_y) - 12 * s, bot_y - 20 * s), (cx - half(bot_y) + 12 * s, bot_y - 20 * s)],
              fill=(255, 128, 190, 140))
    bubbles = gas.make_bubbles()
    active = round(len(bubbles) * _clamp(0.35 + 1.0 * (1 - p)))
    labelled = 0
    for i, b in enumerate(bubbles[:active]):
        hh = gas.bubble_height(b, t)
        bx = cx + (b["x"] - 0.5) * (bot_w * 0.78)
        by = bot_y - 30 * s - hh * (glass_h * 1.42)
        fade = 1.0 - _clamp((hh - 0.78) / 0.22)
        if fade < 0.06:
            continue
        r = (14 + b["radius"] * 1400) * s
        a = int(235 * fade)
        d.ellipse((bx - r, by - r, bx + r, by + r), fill=(255, 255, 255, int(a * 0.55)), outline=INK + (a,),
                  width=_ow(s, 4))
        d.ellipse((bx - r * 0.55, by - r * 0.6, bx - r * 0.1, by - r * 0.2), fill=(255, 255, 255, a))
        if r > 30 * s and labelled < 2 and fade > 0.8:
            c.label((bx, by), "CO\u2082", max(14, r / s * 0.5), "text", kind="bold", anchor="mm")
            labelled += 1
    glass_line = glass + [glass[0]]
    d.line(glass_line, fill=INK, width=_ow(s, 8), joint="curve")
    d.line([(cx - top_w / 2 - 10 * s, top_y), (cx + top_w / 2 + 10 * s, top_y)], fill=INK, width=_ow(s, 10))
    d.line([(cx - top_w / 2 + 30 * s, top_y + 40 * s), (cx - bot_w / 2 + 30 * s, bot_y - 40 * s)],
           fill=(255, 255, 255, 170), width=_ow(s, 9))
    _face(d, cx, surface + 120 * s, 150 * s, s, (0.0, -0.5 if p < 0.7 else 0.0))


BUILDERS = {"drop": moon_scene, "beaker": beaker_scene, "designed": None}  # "designed" is drawn by asset_designer


def render_illustration(record, t, width, height, secs=0.0, ss=2):
    """A PIL image of the topic's cartoon scene, or None if the topic has none."""
    kind = (record.get("scene3d") or {}).get("kind")
    if kind not in BUILDERS:
        return None
    canvas = Canvas(width * ss, height * ss)
    if kind == "designed":
        asset_designer.designed_scene(canvas, (0, 0, width * ss, height * ss), t, secs, record)
    else:
        BUILDERS[kind](canvas, (0, 0, width * ss, height * ss), t, secs)
    return canvas.img.resize((width, height), Image.LANCZOS) if ss > 1 else canvas.img
