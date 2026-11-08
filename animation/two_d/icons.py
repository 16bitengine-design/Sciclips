"""Simple animated icons drawn from basic shapes. No image files are used.

draw_icon(canvas, name, cx, cy, radius, secs, a): `secs` is seconds into the
scene (for looping motion) and `a` is the fade-in amount, 0 to 1.
"""
import math

from animation.two_d.canvas import PALETTE

ICON_NAMES = ("atom", "question", "bulb", "gear", "book", "document", "shield", "warning", "info",
              "rocket", "check")


def _rot(x, y, angle):
    return (x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle))


def _badge(c, cx, cy, r, color, a):
    c.circle((cx, cy), r, fill="panel2", alpha=a)
    c.circle((cx, cy), r, outline=color, width=5, alpha=a)


def _poly(c, cx, cy, r, points, fill, a, angle=0.0):
    c.polygon([(cx + r * px, cy + r * py) for px, py in (_rot(x, y, angle) for x, y in points)], fill, a)


def _atom(c, cx, cy, r, secs, a, color):
    c.circle((cx, cy), 0.15 * r, fill=color, alpha=a)
    for k in range(3):
        tilt = k * math.pi / 3
        pts = []
        for step in range(49):
            th = step / 48 * 2 * math.pi
            x, y = _rot(0.68 * r * math.cos(th), 0.25 * r * math.sin(th), tilt)
            pts.append((cx + x, cy + y))
        c.d.line(pts, fill=c.col(color, a * 0.8), width=max(1, round(3 * c.u)), joint="curve")
        th = secs * 1.6 + k * 2.1
        x, y = _rot(0.68 * r * math.cos(th), 0.25 * r * math.sin(th), tilt)
        c.circle((cx + x, cy + y), 0.08 * r, fill="text", alpha=a)


def _question(c, cx, cy, r, secs, a, color):
    pulse = 1.0 + 0.06 * math.sin(secs * 3)
    c.circle((cx, cy), r * 1.0 * pulse, outline=color, width=3, alpha=a * 0.35)
    c.d.text((cx, cy), "?", font=c.font("bold", r * 1.35 / c.u), fill=c.col(color, a), anchor="mm")


def _bulb(c, cx, cy, r, secs, a, color):
    c.circle((cx, cy - 0.08 * r), 0.36 * r, fill="warn", alpha=a)
    c.rect((cx - 0.17 * r, cy + 0.24 * r, cx + 0.17 * r, cy + 0.34 * r), fill="muted", alpha=a)
    c.rect((cx - 0.12 * r, cy + 0.36 * r, cx + 0.12 * r, cy + 0.44 * r), fill="muted", alpha=a)
    glow = 0.55 + 0.45 * math.sin(secs * 3) ** 2
    for k in range(9):
        ang = math.radians(-170 + k * 20)
        x0, y0 = cx + 0.46 * r * math.cos(ang), cy - 0.08 * r + 0.46 * r * math.sin(ang)
        x1, y1 = cx + (0.58 + 0.08 * glow) * r * math.cos(ang), cy - 0.08 * r + (0.58 + 0.08 * glow) * r * math.sin(ang)
        c.line((x0, y0), (x1, y1), "warn", 5, alpha=a * (0.5 + 0.5 * glow))


def _gear(c, cx, cy, r, secs, a, color):
    spin = secs * 0.6
    for k in range(8):
        ang = spin + k * math.pi / 4
        pts = [_rot(x, y, ang) for x, y in ((0.30, -0.09), (0.50, -0.07), (0.50, 0.07), (0.30, 0.09))]
        c.polygon([(cx + r * x, cy + r * y) for x, y in pts], color, a)
    c.circle((cx, cy), 0.36 * r, fill=color, alpha=a)
    c.circle((cx, cy), 0.16 * r, fill="panel2", alpha=a)


def _book(c, cx, cy, r, secs, a, color):
    left = [(-0.52, -0.30), (-0.02, -0.22), (-0.02, 0.38), (-0.52, 0.30)]
    right = [(0.52, -0.30), (0.02, -0.22), (0.02, 0.38), (0.52, 0.30)]
    _poly(c, cx, cy, r, left, color, a)
    _poly(c, cx, cy, r, right, "blue", a)
    for k in range(3):
        for sign in (-1, 1):
            c.line((cx + sign * 0.42 * r, cy + (-0.12 + k * 0.14) * r + sign * 0.0),
                   (cx + sign * 0.1 * r, cy + (-0.08 + k * 0.14) * r), "panel2", 3, alpha=a)


def _document(c, cx, cy, r, secs, a, color):
    pts = [(-0.30, -0.45), (0.12, -0.45), (0.32, -0.25), (0.32, 0.45), (-0.30, 0.45)]
    _poly(c, cx, cy, r, pts, "text", a)
    _poly(c, cx, cy, r, [(0.12, -0.45), (0.12, -0.25), (0.32, -0.25)], "muted", a)
    for k in range(4):
        c.line((cx - 0.18 * r, cy + (-0.12 + k * 0.14) * r), (cx + 0.2 * r, cy + (-0.12 + k * 0.14) * r),
               "panel2", 4, alpha=a)


def _shield(c, cx, cy, r, secs, a, color):
    pts = [(-0.38, -0.38), (0.0, -0.52), (0.38, -0.38), (0.38, 0.06), (0.0, 0.52), (-0.38, 0.06)]
    _poly(c, cx, cy, r, pts, color, a)
    c.d.line([(cx - 0.17 * r, cy), (cx - 0.04 * r, cy + 0.14 * r), (cx + 0.2 * r, cy - 0.14 * r)],
             fill=c.col("panel2", a), width=max(1, round(9 * c.u)), joint="curve")


def _warning(c, cx, cy, r, secs, a, color):
    shake = 0.04 * math.sin(secs * 9)
    pts = [(0.0, -0.5), (0.5, 0.38), (-0.5, 0.38)]
    _poly(c, cx, cy, r, pts, "warn", a, shake)
    c.d.text((cx, cy + 0.12 * r), "!", font=c.font("bold", r * 0.9 / c.u), fill=c.col("panel2", a), anchor="mm")


def _info(c, cx, cy, r, secs, a, color):
    c.circle((cx, cy), 0.5 * r, outline=color, width=6, alpha=a)
    c.d.text((cx, cy), "i", font=c.font("bold", r * 0.95 / c.u), fill=c.col(color, a), anchor="mm")


def _rocket(c, cx, cy, r, secs, a, color):
    lift = 0.03 * math.sin(secs * 4)
    cy = cy - lift * r
    flame = 0.20 + 0.10 * math.sin(secs * 18) ** 2
    _poly(c, cx, cy, r, [(-0.10, 0.30), (0.10, 0.30), (0.0, 0.30 + flame * 1.6)], "warn", a)
    _poly(c, cx, cy, r, [(0.0, -0.52), (0.17, -0.12), (0.17, 0.30), (-0.17, 0.30), (-0.17, -0.12)], "text", a)
    _poly(c, cx, cy, r, [(0.17, 0.05), (0.38, 0.32), (0.17, 0.30)], color, a)
    _poly(c, cx, cy, r, [(-0.17, 0.05), (-0.38, 0.32), (-0.17, 0.30)], color, a)
    c.circle((cx, cy - 0.12 * r), 0.09 * r, fill="blue", alpha=a)


def _check(c, cx, cy, r, secs, a, color):
    c.circle((cx, cy), 0.5 * r, fill="good", alpha=a)
    c.d.line([(cx - 0.22 * r, cy + 0.02 * r), (cx - 0.07 * r, cy + 0.18 * r), (cx + 0.24 * r, cy - 0.16 * r)],
             fill=c.col("panel2", a), width=max(1, round(11 * c.u)), joint="curve")


GLYPHS = {"atom": _atom, "question": _question, "bulb": _bulb, "gear": _gear, "book": _book,
          "document": _document, "shield": _shield, "warning": _warning, "info": _info,
          "rocket": _rocket, "check": _check}
BADGE_COLORS = {"atom": "accent", "question": "violet", "bulb": "warn", "gear": "blue", "book": "blue",
                "document": "muted", "shield": "good", "warning": "warn", "info": "accent",
                "rocket": "accent", "check": "good"}


def draw_icon(c, name, cx, cy, radius, secs=0.0, a=1.0):
    """Draw a badge with the named icon inside. Unknown names draw nothing."""
    glyph = GLYPHS.get(name)
    if glyph is None or a <= 0:
        return
    color = BADGE_COLORS[name]
    pop = 0.7 + 0.3 * min(1.0, a * 1.4)
    r = radius * pop
    _badge(c, cx, cy, r, color, a)
    glyph(c, cx, cy, r * 0.92, secs, a, color)
