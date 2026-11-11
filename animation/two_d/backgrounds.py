"""Animated theme backgrounds: gradients, sunbursts, halftone dots, drifting shapes, paper and kraft."""
import math
import random
from functools import lru_cache

from PIL import Image


@lru_cache(maxsize=8)
def _gradient(width, height, top, bottom):
    column = Image.new("RGB", (1, height))
    for y in range(height):
        k = y / max(1, height - 1)
        column.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * k) for i in range(3)))
    return column.resize((width, height))


@lru_cache(maxsize=6)
def _grain(width, height, seed, strength):
    """Fine paper grain, the same every frame."""
    rng = random.Random(seed)
    small = Image.frombytes("L", (width // 3 + 1, height // 3 + 1),
                            bytes(rng.randrange(256) for _ in range((width // 3 + 1) * (height // 3 + 1))))
    return small.resize((width, height)).point(lambda v: int(strength * (v - 128) / 128) + 128)


def _lighter(color, amount):
    return tuple(min(255, round(c + (255 - c) * amount)) for c in color)


def _rays(c, secs, tint, alpha, count=16, center=(0.5, 0.30)):
    cx, cy = c.w * center[0], c.h * center[1]
    radius = math.hypot(c.w, c.h)
    step = 2 * math.pi / count
    turn = secs * 0.05
    for i in range(0, count, 2):
        a0, a1 = turn + i * step, turn + (i + 1) * step
        c.d.polygon([(cx, cy), (cx + radius * math.cos(a0), cy + radius * math.sin(a0)),
                     (cx + radius * math.cos(a1), cy + radius * math.sin(a1))], fill=tint + (alpha,))


def _halftone(c, corner, tint, alpha, spacing=34, max_r=11):
    reach = 0.5 * min(c.w, c.h)
    sp, mr = spacing * c.u, max_r * c.u
    cx, cy = (0, 0) if corner == "tl" else (c.w, c.h)
    y = 0.0
    while y < reach:
        x = 0.0
        while x < reach:
            d = math.hypot(x, y)
            r = mr * max(0.0, 1 - d / reach)
            if r > 1:
                px = cx + x if corner == "tl" else cx - x
                py = cy + y if corner == "tl" else cy - y
                c.d.ellipse((px - r, py - r, px + r, py + r), fill=tint + (alpha,))
            x += sp
        y += sp


def _star(c, cx, cy, size, angle, color):
    pts = []
    for i in range(8):
        r = size if i % 2 == 0 else size * 0.38
        a = angle + i * math.pi / 4
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    c.d.polygon(pts, fill=color)


def _plus(c, cx, cy, size, angle, color):
    for k in (0, 1):
        a = angle + k * math.pi / 2
        dx, dy = math.cos(a) * size, math.sin(a) * size
        c.d.line([(cx - dx, cy - dy), (cx + dx, cy + dy)], fill=color, width=max(2, round(size * 0.38)))


def _triangle(c, cx, cy, size, angle, color):
    c.d.polygon([(cx + size * math.cos(angle + k * 2.094), cy + size * math.sin(angle + k * 2.094))
                 for k in range(3)], fill=color)


def _ring(c, cx, cy, size, angle, color):
    c.d.ellipse((cx - size, cy - size, cx + size, cy + size), outline=color, width=max(2, round(size * 0.28)))


def _dot(c, cx, cy, size, angle, color):
    c.d.ellipse((cx - size * 0.6, cy - size * 0.6, cx + size * 0.6, cy + size * 0.6), fill=color)


def _squiggle(c, cx, cy, size, angle, color):
    pts = []
    for i in range(13):
        t = i / 12
        x = (t - 0.5) * size * 2.4
        y = math.sin(t * 6.28 * 1.5) * size * 0.35
        pts.append((cx + x * math.cos(angle) - y * math.sin(angle), cy + x * math.sin(angle) + y * math.cos(angle)))
    c.d.line(pts, fill=color, width=max(2, round(size * 0.22)), joint="curve")


SHAPES = (_star, _plus, _triangle, _ring, _dot, _squiggle)


def _decor(c, secs, alpha, count=16):
    """Small coloured shapes that drift upward and turn slowly, different in every scene."""
    colors = c.theme.decor
    rng = random.Random(c.seed * 977)
    for _ in range(count):
        shape = rng.choice(SHAPES)
        side = rng.random()
        x = rng.uniform(0.02, 0.10) * c.w if side < 0.5 else rng.uniform(0.90, 0.98) * c.w
        y0 = rng.random() * c.h
        size = rng.uniform(14, 36) * c.u
        speed = rng.uniform(5, 14) * c.u
        spin = rng.uniform(-0.5, 0.5)
        color = rng.choice(colors) + (alpha,)
        base = rng.random() * 6.28
        shape(c, x + 12 * c.u * math.sin(secs * 0.7 + base), (y0 - secs * speed) % c.h, size, base + secs * spin, color)


def _paper(c, secs, strength):
    scheme = c.scheme
    c.img.paste(_gradient(c.w, c.h, scheme["bg_top"], scheme["bg_bottom"]))
    grain = _grain(c.w, c.h, c.seed, strength)
    c.img.paste(Image.blend(c.img, Image.merge("RGB", (grain, grain, grain)), 0.10))


def paint(c, secs):
    theme, scheme = c.theme, c.scheme
    if theme.background == "sunburst":
        c.img.paste(_gradient(c.w, c.h, scheme["bg_top"], scheme["bg_bottom"]))
        _rays(c, secs, (255, 255, 255), 20)
        _halftone(c, "tl", (255, 255, 255), 34)
        _halftone(c, "br", (0, 0, 0), 34)
        _decor(c, secs, 190, 14)
    elif theme.background == "paper":
        _paper(c, secs, 60)
        ink = theme.outline
        m = 20 * c.u
        c.d.rectangle((m, m, c.w - m, c.h - m), outline=ink + (255,), width=max(2, round(4 * c.u)))
        c.d.rectangle((m * 1.6, m * 1.6, c.w - m * 1.6, c.h - m * 1.6), outline=ink + (160,), width=max(1, round(2 * c.u)))
        _halftone(c, "tl", scheme["accent"], 70, 30, 9)
        _halftone(c, "br", theme.decor[1], 60, 30, 9)
        _decor(c, secs, 150, 12)
    elif theme.background == "kraft":
        _paper(c, secs, 90)
        _rays(c, secs, (255, 255, 255), 14, count=12, center=(0.5, 0.35))
        for i in range(5):   # strips of coloured paper behind the cards
            y = (0.12 + 0.2 * i) * c.h + 14 * c.u * math.sin(secs * 0.5 + i)
            colour = theme.decor[i % len(theme.decor)] + (120,)
            c.d.polygon([(-10, y), (c.w + 10, y - 40 * c.u), (c.w + 10, y + 8 * c.u), (-10, y + 48 * c.u)], fill=colour)
        _decor(c, secs, 170, 10)
