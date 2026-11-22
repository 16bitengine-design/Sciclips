"""two_d: merged module (was 12 files: backgrounds, asset_designer, themes, canvas, icons, illustrations, sim_draw, diagrams, scene_plan, scenes, renderer, thumbnail).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
from PIL import Image
from PIL import Image, ImageDraw
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from animation.simulations import free_fall as ff
from animation.simulations import gas_release as gas
from animation.simulations import reaction_layout as rl
from animation.three_d.scenes3d import render_viewport


# ============================================================================
# from animation/two_d/backgrounds.py
# ============================================================================
# Animated theme backgrounds: gradients, sunbursts, halftone dots, drifting shapes, paper and kraft.







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


BACKGROUNDS_SHAPES = (_star, _plus, _triangle, _ring, _dot, _squiggle)


def _decor(c, secs, alpha, count=16):
    """Small coloured shapes that drift upward and turn slowly, different in every scene."""
    colors = c.theme.decor
    rng = random.Random(c.seed * 977)
    for _ in range(count):
        shape = rng.choice(BACKGROUNDS_SHAPES)
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


# ============================================================================
# from animation/two_d/asset_designer.py
# ============================================================================
# Asset Designer: invents the characters, props and settings for a video, instead of using a fixed set.











INK = (22, 14, 58)
COLOURS = [((255, 120, 170), (255, 196, 218)), ((90, 176, 255), (180, 220, 255)), ((60, 224, 138), (170, 244, 200)),
           ((255, 194, 30), (255, 230, 140)), ((176, 140, 255), (214, 196, 255)), ((255, 138, 61), (255, 190, 140)),
           ((110, 230, 230), (190, 244, 244))]
SHAPES = ("round", "tall", "box", "drop", "star", "blob")
ACCESSORIES = ("goggles", "hat", "antenna", "bow", "none", "none")
MOTIONS = ("bob", "hop", "float")
MOODS = ("happy", "happy", "curious")
PROP_KINDS = ("planet", "sun", "cloud", "bubbles", "gem")

BACKGROUNDS = {  # top colour, bottom colour, ground colour
    "space": ((30, 20, 92), (96, 52, 168), (214, 216, 238)),
    "lab": ((24, 150, 160), (60, 40, 150), (255, 196, 84)),
    "sky": ((70, 170, 255), (190, 235, 255), (96, 206, 130)),
    "ocean": ((20, 110, 200), (10, 40, 120), (240, 214, 140)),
    "forest": ((60, 170, 110), (20, 80, 70), (150, 104, 60)),
}
KEYWORDS = {
    "space": ("moon", "space", "planet", "gravity", "orbit", "star", "sun", "galaxy", "rocket", "vacuum", "fall"),
    "lab": ("acid", "reaction", "gas", "chemical", "beaker", "bubble", "solution", "mix", "baking", "soda",
            "vinegar", "atom", "molecule", "energy", "electric"),
    "ocean": ("water", "ocean", "sea", "wave", "fish", "tide", "sink", "dive"),
    "sky": ("sky", "cloud", "rain", "weather", "wind", "air", "flight", "fly", "bird", "sound", "light"),
    "forest": ("plant", "tree", "leaf", "animal", "cell", "seed", "grow", "bee", "food"),
}
PROPS_FOR = {"space": ("planet", "sun"), "lab": ("bubbles", "gem"), "sky": ("cloud", "sun"),
             "ocean": ("bubbles", "gem"), "forest": ("sun", "gem")}
STOP_WORDS = set("""about above after again against also because been before being between both can could did does
doing down during each from further have having here how into just more most not now off once only other over same
make makes made fall falls float floats work works thing things happen happens cause causes together faster slower heavy bigger smaller really every kind
should some such than that their them then there these they this those through under until very was were what when
where which while who whom why will with would your you the and for are but its out why""".split())


def _seed(name):
    return int(hashlib.md5(str(name).lower().encode("utf-8")).hexdigest()[:8], 16)


# ------------------------------------------------------------------ inventing
def invent_actor(name, **overrides):
    """A character with a look of its own, always the same for the same name."""
    rng = random.Random(_seed(name))
    actor = {"name": name, "shape": rng.choice(SHAPES), "colour": rng.randrange(len(COLOURS)),
             "accessory": rng.choice(ACCESSORIES), "motion": rng.choice(MOTIONS), "legs": rng.random() < 0.6,
             "mood": rng.choice(MOODS)}
    actor.update({k: v for k, v in overrides.items() if k in actor or k in ("x", "label", "face")})
    if overrides.get("parts"):
        actor["parts"] = clean_parts(overrides["parts"])
    return actor


def invent_prop(name):
    """A prop: a recognised name gives that prop; any other name gives a coloured gem."""
    rng = random.Random(_seed(name))
    kind = str(name).lower()
    if kind not in PROP_KINDS:
        kind = "gem"
    return {"name": str(name), "kind": kind, "colour": rng.randrange(len(COLOURS))}


def pick_background(text, fallback_name=""):
    words = set(re.findall(r"[a-z]+", text.lower()))
    scores = {name: sum(1 for w in words if any(w.startswith(k) for k in keys)) for name, keys in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return sorted(BACKGROUNDS)[_seed(fallback_name or text) % len(BACKGROUNDS)]


def design_scene(record, library=None):
    """The scene design for a topic record: {"background", "actors", "props"}.

    `library` is a dict of characters already invented (name -> design). New characters are added to it, so that
    saving it with save_library() lets later videos reuse them.
    """
    record = record or {}
    given = (record.get("scene3d") or {}).get("spec") or {}
    text = f"{record.get('title', '')} {record.get('central_question', '')}"
    background = given.get("background") or pick_background(text, record.get("title", ""))
    if background not in BACKGROUNDS:
        background = pick_background(text)
    names = [a["name"] if isinstance(a, dict) else str(a) for a in given.get("actors", [])]
    if not names:
        seen = []
        for word in re.findall(r"[A-Za-z]+", text):
            low = word.lower()
            if len(low) > 3 and low not in STOP_WORDS and low not in seen:
                seen.append(low)
        names = [w.capitalize() for w in seen[:3]] or ["Spark"]
    actors = []
    for item, name in zip(given.get("actors", []) + [None] * len(names), names):
        overrides = {k: v for k, v in item.items() if k != "name"} if isinstance(item, dict) else {}
        if library is not None and name in library and not overrides:
            actors.append(dict(library[name]))
            continue
        actor = invent_actor(name, **overrides)
        if library is not None:
            library[name] = dict(actor)
        actors.append(actor)
    props = [_prop_from(p) for p in (given.get("props") or PROPS_FOR[background])]
    return {"background": background, "actors": actors, "props": props}


def load_library(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_library(path, library):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(library, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ free-form objects
# Anything can be described as a short list of simple shapes drawn on a 0-100 square (y points down).
# A rocket, a magnet, a microscope: whoever writes the scene (the AI script writer, or a person) lists the parts.
PART_SHAPES = ("ellipse", "circle", "rect", "rrect", "polygon", "line", "arc")
NAMED_COLOURS = {"red": "#E8434B", "blue": "#3C82F0", "green": "#26AA6E", "yellow": "#FFD60A", "orange": "#FF8A3D",
                 "pink": "#FF78AA", "purple": "#8E63E0", "white": "#FFFFFF", "grey": "#9AA5B8", "gray": "#9AA5B8",
                 "black": "#2A2342", "teal": "#14A5B0", "brown": "#A06A3C", "steel": "#94A6CC", "glass": "#DDF4FF",
                 "wood": "#DE9A54", "gold": "#F5B823", "silver": "#CDD5E4"}
OBJECT_PROMPT = (
    "Describe each new object as JSON: {\"name\": \"rocket\", \"parts\": [ ... ], \"face\": {\"x\": 50, \"y\": 45, "
    "\"size\": 30} or null}. Every part is {\"shape\": one of ellipse, circle, rect, rrect, polygon, line, arc, "
    "\"fill\": a colour name or #rrggbb, \"box\": [x0, y0, x1, y1] for ellipse, circle, rect, rrect, arc, or "
    "\"points\": [[x, y], ...] for polygon and line}. Optional: \"alpha\" 0 to 1, \"outline\" true or false, "
    "\"width\" 1 to 12, and \"start\" and \"end\" degrees for arc. Draw on a 0 to 100 square with y pointing down. "
    "Use 4 to 25 parts, back to front. Keep it simple, bold and cartoon-like.")


def _num(value, low=-20.0, high=120.0):
    return max(low, min(high, float(value)))


def _hex(value):
    text = str(value or "").strip().lower()
    if text in NAMED_COLOURS:
        return NAMED_COLOURS[text]
    if re.fullmatch(r"#[0-9a-f]{6}", text):
        return text.upper()
    return "#9AA5B8"


def clean_parts(parts, limit=40):
    """Keep only well-formed parts, with numbers in range, so a badly written description never breaks a video."""
    out = []
    for part in list(parts or [])[:limit]:
        try:
            shape = part.get("shape")
            if shape not in PART_SHAPES:
                continue
            clean = {"shape": shape, "fill": _hex(part.get("fill")), "outline": part.get("outline", True) is not False,
                     "width": _num(part.get("width", 4), 1, 12), "alpha": _num(part.get("alpha", 1), 0, 1)}
            if shape in ("polygon", "line"):
                points = [[_num(x), _num(y)] for x, y in part["points"]][:40]
                if len(points) < (3 if shape == "polygon" else 2):
                    continue
                clean["points"] = points
            else:
                box = [_num(v) for v in part["box"]]
                if len(box) != 4:
                    continue
                clean["box"] = [min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3])]
            if shape == "arc":
                clean["start"], clean["end"] = _num(part.get("start", 0), -720, 720), _num(part.get("end", 180), -720, 720)
            out.append(clean)
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return out


def _prop_from(item):
    if isinstance(item, dict) and item.get("parts"):
        parts = clean_parts(item["parts"])
        if parts:
            return {"name": str(item.get("name", "object")), "kind": "custom", "colour": 0, "parts": parts}
    return invent_prop(item.get("name", "gem") if isinstance(item, dict) else item)


def draw_parts(d, parts, cx, bottom, size, s):
    """Draw a free-form object so that it stands on `bottom`, `size` pixels tall and wide, centred on cx."""
    def px(v):
        return cx - size / 2 + v * size / 100

    def py(v):
        return bottom - size + v * size / 100

    for part in parts:
        rgb = tuple(int(part["fill"][i:i + 2], 16) for i in (1, 3, 5))
        fill = rgb + (int(255 * part.get("alpha", 1)),)
        ink = INK if part.get("outline", True) else None
        width = _ow(s, part.get("width", 4))
        shape = part["shape"]
        if shape == "line":
            d.line([(px(x), py(y)) for x, y in part["points"]], fill=ink or fill, width=width, joint="curve")
        elif shape == "polygon":
            d.polygon([(px(x), py(y)) for x, y in part["points"]], fill=fill, outline=ink, width=width)
        else:
            x0, y0, x1, y1 = part["box"]
            box = (px(x0), py(y0), px(x1), py(y1))
            if shape in ("ellipse", "circle"):
                d.ellipse(box, fill=fill, outline=ink, width=width)
            elif shape == "rect":
                d.rectangle(box, fill=fill, outline=ink, width=width)
            elif shape == "rrect":
                d.rounded_rectangle(box, radius=min(box[2] - box[0], box[3] - box[1]) * 0.25, fill=fill, outline=ink,
                                    width=width)
            else:
                d.arc(box, part.get("start", 0), part.get("end", 180), fill=ink or fill, width=width)


# ------------------------------------------------------------------ drawing parts
def _ow(s, width=6):
    return max(3, round(width * s))


def _face(d, cx, cy, size, s, look, mood):
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
                   cy + size * 0.24), fill=(255, 120, 140, 150))
    if mood == "curious":
        d.ellipse((cx - size * 0.07, cy + size * 0.12, cx + size * 0.07, cy + size * 0.26), fill=INK)
    else:
        mw = size * 0.26
        d.arc((cx - mw, cy + size * 0.02, cx + mw, cy + size * 0.30), 15, 165, fill=INK, width=_ow(s, 5))


def _body(d, shape, cx, bottom, k, fill, light, s, seed):
    """Draw the body. Returns its box (x0, y0, x1, y1)."""
    ow = _ow(s)
    if shape == "round":
        box = (cx - 115 * k, bottom - 250 * k, cx + 115 * k, bottom)
        d.ellipse(box, fill=fill, outline=INK, width=ow)
    elif shape == "tall":
        box = (cx - 80 * k, bottom - 300 * k, cx + 80 * k, bottom)
        d.rounded_rectangle(box, radius=50 * k, fill=fill, outline=INK, width=ow)
    elif shape == "box":
        box = (cx - 110 * k, bottom - 240 * k, cx + 110 * k, bottom)
        d.rounded_rectangle(box, radius=26 * k, fill=fill, outline=INK, width=ow)
    elif shape == "drop":
        r, cy = 112 * k, bottom - 112 * k
        pts = [(cx, bottom - 330 * k)]
        for i in range(0, 25):
            a = math.radians(-35 + i * 10.4)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        d.polygon(pts, fill=fill, outline=INK, width=ow)
        box = (cx - r, bottom - 330 * k, cx + r, bottom)
    elif shape == "star":
        cy = bottom - 150 * k
        pts = []
        for i in range(10):
            r = 150 * k if i % 2 == 0 else 68 * k
            a = -math.pi / 2 + i * math.pi / 5
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        d.polygon(pts, fill=fill, outline=INK, width=ow)
        box = (cx - 150 * k, cy - 150 * k, cx + 150 * k, cy + 150 * k)
    else:  # blob
        rng = random.Random(seed)
        phase = [rng.uniform(0, 6.28) for _ in range(3)]
        cy = bottom - 125 * k
        pts = []
        for i in range(28):
            a = i * 2 * math.pi / 28
            r = 122 * k * (1 + 0.10 * math.sin(2 * a + phase[0]) + 0.07 * math.sin(3 * a + phase[1]))
            pts.append((cx + r * math.cos(a), cy + 0.95 * r * math.sin(a)))
        d.polygon(pts, fill=fill, outline=INK, width=ow)
        box = (cx - 130 * k, cy - 125 * k, cx + 130 * k, cy + 120 * k)
    hx, hy = box[0] + (box[2] - box[0]) * 0.28, box[1] + (box[3] - box[1]) * 0.22
    d.ellipse((hx - 22 * k, hy - 14 * k, hx + 22 * k, hy + 14 * k), fill=light)
    return box


def _accessory(d, kind, box, face_y, k, s):
    cx, top = (box[0] + box[2]) / 2, box[1]
    ow = _ow(s, 5)
    if kind == "goggles":
        for sign in (-1, 1):
            gx = cx + sign * 30 * k
            d.ellipse((gx - 24 * k, face_y - 28 * k, gx + 24 * k, face_y + 20 * k), outline=INK, width=ow,
                      fill=(200, 240, 255, 110))
        d.line([(cx - 6 * k, face_y - 4 * k), (cx + 6 * k, face_y - 4 * k)], fill=INK, width=ow)
    elif kind == "hat":
        d.polygon([(cx - 70 * k, top + 6 * k), (cx + 70 * k, top + 6 * k), (cx + 46 * k, top - 70 * k),
                   (cx - 46 * k, top - 70 * k)], fill=(70, 50, 150), outline=INK, width=_ow(s))
        d.rectangle((cx - 46 * k, top - 28 * k, cx + 46 * k, top - 10 * k), fill=(255, 214, 10))
    elif kind == "antenna":
        d.line([(cx, top + 4 * k), (cx + 14 * k, top - 70 * k)], fill=INK, width=ow)
        d.ellipse((cx + 14 * k - 15 * k, top - 70 * k - 30 * k, cx + 14 * k + 15 * k, top - 70 * k), fill=(255, 92, 170),
                  outline=INK, width=_ow(s, 4))
    elif kind == "bow":
        bx, by = cx + 52 * k, top + 26 * k
        for sign in (-1, 1):
            d.polygon([(bx, by), (bx + sign * 44 * k, by - 24 * k), (bx + sign * 44 * k, by + 24 * k)],
                      fill=(255, 92, 170), outline=INK, width=_ow(s, 4))


def _legs(d, cx, bottom, k, s):
    for sign in (-1, 1):
        x = cx + sign * 46 * k
        d.line([(x, bottom - 10 * k), (x, bottom + 34 * k)], fill=INK, width=_ow(s, 9))
        d.ellipse((x - 24 * k, bottom + 22 * k, x + 24 * k, bottom + 44 * k), fill=INK)


def draw_actor(d, actor, cx, bottom, k, s, look=(0.0, 0.3)):
    if actor.get("parts"):
        size = 300 * k
        draw_parts(d, actor["parts"], cx, bottom, size, s)
        face = actor.get("face")
        if face:
            _face(d, cx - size / 2 + face.get("x", 50) * size / 100, bottom - size + face.get("y", 45) * size / 100,
                  face.get("size", 30) * size / 100, s, look, actor.get("mood", "happy"))
        return
    fill, light = COLOURS[actor["colour"] % len(COLOURS)]
    if actor.get("legs"):
        _legs(d, cx, bottom, k, s)
    box = _body(d, actor["shape"], cx, bottom, k, fill, light, s, _seed(actor["name"]))
    face_y = box[1] + (box[3] - box[1]) * (0.46 if actor["shape"] != "drop" else 0.62)
    _face(d, cx, face_y, 120 * k, s, look, actor.get("mood", "happy"))
    _accessory(d, actor.get("accessory", "none"), box, face_y, k, s)


# ------------------------------------------------------------------ props
def draw_prop(d, prop, cx, cy, r, s, secs):
    fill, light = COLOURS[prop["colour"] % len(COLOURS)]
    ow = _ow(s)
    kind = prop["kind"]
    if kind == "custom":
        draw_parts(d, prop["parts"], cx, cy + 1.2 * r, 2.4 * r, s)
    elif kind == "planet":
        d.ellipse((cx - r * 1.7, cy - r * 0.35, cx + r * 1.7, cy + r * 0.35), outline=INK, width=ow)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=INK, width=ow)
        d.ellipse((cx - r * 0.55, cy - r * 0.6, cx - r * 0.15, cy - r * 0.3), fill=light)
        d.arc((cx - r * 1.7, cy - r * 0.35, cx + r * 1.7, cy + r * 0.35), 0, 180, fill=INK, width=ow)
    elif kind == "sun":
        for i in range(12):
            a = i * math.pi / 6 + secs * 0.3
            d.line([(cx + r * 1.2 * math.cos(a), cy + r * 1.2 * math.sin(a)),
                    (cx + r * 1.6 * math.cos(a), cy + r * 1.6 * math.sin(a))], fill=(255, 226, 60), width=_ow(s, 9))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 214, 10), outline=INK, width=ow)
    elif kind == "cloud":
        for dx, dy, rr in ((-0.8, 0.1, 0.7), (0.0, -0.3, 0.95), (0.85, 0.1, 0.7)):
            d.ellipse((cx + dx * r - rr * r, cy + dy * r - rr * r, cx + dx * r + rr * r, cy + dy * r + rr * r),
                      fill=(255, 255, 255), outline=INK, width=ow)
        d.rectangle((cx - 1.2 * r, cy - 0.05 * r, cx + 1.3 * r, cy + 0.75 * r), fill=(255, 255, 255))
    elif kind == "bubbles":
        for i in range(4):
            by = cy - ((secs * 30 + i * 60) % 240) * s
            bx, br = cx + (i - 1.5) * r * 0.7, r * (0.35 + 0.12 * (i % 3))
            d.ellipse((bx - br, by - br, bx + br, by + br), fill=(255, 255, 255, 110), outline=INK, width=_ow(s, 4))
            d.ellipse((bx - br * 0.55, by - br * 0.6, bx - br * 0.15, by - br * 0.2), fill=(255, 255, 255))
    else:  # gem
        d.polygon([(cx, cy - r), (cx + r * 0.8, cy), (cx, cy + r), (cx - r * 0.8, cy)], fill=fill, outline=INK, width=ow)
        d.polygon([(cx, cy - r * 0.7), (cx - r * 0.3, cy - r * 0.1), (cx, cy + r * 0.1)], fill=light)


def _sparkle(d, cx, cy, r, color):
    pts = []
    for i in range(8):
        rr = r if i % 2 == 0 else r * 0.28
        a = i * math.pi / 4 - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=color)


# ------------------------------------------------------------------ the scene
def designed_scene(c, box, t, secs, record=None, library=None):
    """Draw the whole designed scene into box (x0, y0, x1, y1) on canvas c, at progress t (0 to 1)."""
    d = c.d
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0, y1 - y0
    s = min(w, h) / 1000.0
    spec = design_scene(record, library)
    top, bottom, ground = BACKGROUNDS[spec["background"]]
    c.img.paste(_gradient(w, h, top, bottom), (x0, y0))
    rng = random.Random(_seed(spec["background"]))
    for i in range(22):
        _sparkle(d, x0 + rng.uniform(0.03, 0.97) * w, y0 + rng.uniform(0.03, 0.55) * h,
                 rng.uniform(7, 18) * s * (0.75 + 0.25 * math.sin(secs * 3 + i)),
                 rng.choice([(255, 236, 130), (255, 255, 255), (170, 230, 255)]))
    ground_y = y0 + 0.80 * h
    d.ellipse((x0 - 0.15 * w, y0 + 0.70 * h, x1 + 0.15 * w, y0 + 1.50 * h), fill=ground, outline=INK, width=_ow(s, 7))
    d.arc((x0 - 0.05 * w, y0 + 0.73 * h, x1 + 0.05 * w, y0 + 1.1 * h), 205, 335, fill=(255, 255, 255), width=_ow(s, 9))
    for i, prop in enumerate(spec["props"]):
        px = x0 + (0.84 if i == 0 else 0.14) * w
        py = y0 + (0.20 if i == 0 else 0.30) * h
        draw_prop(d, prop, px, py + 8 * s * math.sin(secs * 1.5 + i), 0.075 * min(w, h), s, secs)
    actors = spec["actors"]
    n = max(1, len(actors))
    k = min(0.42 * h / 330.0, 0.80 * w / (n * 290.0))
    for i, actor in enumerate(actors):
        cx = x0 + (actor.get("x") or (i + 1) / (n + 1)) * w
        phase = (_seed(actor["name"]) % 628) / 100.0
        lift = 0.0
        look = (0.0, 0.3)
        motion = actor.get("motion", "bob")
        if motion == "hop":
            lift = abs(math.sin(secs * 3 + phase)) * 70 * k
        elif motion == "float":
            lift = 60 * k + 18 * k * math.sin(secs * 2 + phase)
        else:
            lift = 14 * k * (1 + math.sin(secs * 2.2 + phase))
        rise = lift
        sw = 0.11 * w * max(0.35, 1 - rise / (260 * k))
        d.ellipse((cx - sw, ground_y + 6 * s, cx + sw, ground_y + 6 * s + sw * 0.28), fill=(60, 40, 100, 110))
        draw_actor(d, actor, cx, ground_y - rise - 30 * k, k, s, look)


def render_designed(record, width, height, t=0.5, secs=0.0, ss=1, library=None):
    """A PIL image of a designed scene (handy for tests and previews)."""
    pass
    canvas = Canvas(width * ss, height * ss)
    designed_scene(canvas, (0, 0, width * ss, height * ss), t, secs, record, library)
    return canvas.img.resize((width, height), Image.LANCZOS) if ss > 1 else canvas.img


# ============================================================================
# from animation/two_d/themes.py
# ============================================================================
# Visual themes: colours, outlines, backgrounds and fonts.



def rgb(code):
    code = code.lstrip("#")
    return tuple(int(code[i:i + 2], 16) for i in (0, 2, 4))


@dataclass(frozen=True)
class Theme:
    name: str
    base: dict                      # colours that stay the same in every scene
    schemes: list                   # per-scene colours: bg_top, bg_bottom, panel, panel2, accent
    background: str = "flat"        # flat | sunburst | paper | kraft
    outline: tuple = None           # sticker outline colour
    outline_w: float = 0.0          # outline width in units
    shadow: tuple = None
    shadow_off: float = 0.0
    stroke: tuple = None            # text outline colour
    stroke_ratio: float = 0.0       # text outline as a share of the font size
    edge: str = "clean"             # clean | torn
    decor: list = field(default_factory=list)   # colours for drifting shapes
    display_font: str = "bold"      # bold (DejaVu) or display (Lilita One if present)
    hook: str = "3d"                # 3d | illustration
    caption_font: str = "DejaVu Sans"
    body_font: str = "sans"         # font kind used for normal text
    text_scale: float = 1.0         # makes all text bigger in themes that want chunky lettering


CLASSIC_BASE = {name: rgb(code) for name, code in {
    "text": "#F1F5F9", "muted": "#94A3B8", "good": "#34D399", "warn": "#F59E0B", "bad": "#F87171",
    "blue": "#60A5FA", "violet": "#A78BFA"}.items()}
CLASSIC_SCHEME = {"bg_top": rgb("#0B1220"), "bg_bottom": rgb("#0B1220"), "panel": rgb("#16213A"),
                  "panel2": rgb("#1E2B4A"), "accent": rgb("#2DD4BF")}


def _scheme(top, bottom, panel, accent):
    top, bottom, panel, accent = rgb(top), rgb(bottom), rgb(panel), rgb(accent)
    return {"bg_top": top, "bg_bottom": bottom, "panel": panel,
            "panel2": tuple(int(c * 0.72) for c in panel), "accent": accent}


VECTOR_SCHEMES = [
    _scheme("#4A2FA8", "#1D1257", "#6D4DE0", "#FFD60A"),   # indigo
    _scheme("#0B7F8F", "#06394A", "#0F9AA5", "#FF5CAA"),   # teal
    _scheme("#B02858", "#531038", "#E85A60", "#FFD60A"),   # sunset
    _scheme("#1F55C0", "#0E2466", "#3C82F0", "#FFA028"),   # blue
    _scheme("#128060", "#07403A", "#1FA066", "#FFEB46"),   # green
    _scheme("#96209A", "#3E0F56", "#D246BE", "#6EE6E6"),   # magenta
    _scheme("#C25F14", "#6E2814", "#DB6F22", "#4FDDC8"),   # orange
    _scheme("#1C3A9E", "#0A1650", "#2F66D0", "#FF6B6B"),   # royal blue
]
VECTOR_BASE = {**CLASSIC_BASE, "text": rgb("#FFFFFF"), "muted": rgb("#E4E1FF"), "good": rgb("#3CE08A"),
               "warn": rgb("#FFC21E"), "bad": rgb("#FF5560"), "blue": rgb("#5AB0FF"), "violet": rgb("#B08CFF")}

VINTAGE_BASE = {"text": rgb("#2B2118"), "muted": rgb("#6B5A47"), "good": rgb("#3E8E5A"), "warn": rgb("#D9822B"),
                "bad": rgb("#C8442F"), "blue": rgb("#2F6F8F"), "violet": rgb("#7A5A8C")}
VINTAGE_SCHEMES = [
    _scheme("#F3E3BC", "#E8CF9B", "#F7C98B", "#C8442F"),   # cream and peach
    _scheme("#EFE2BF", "#E0CC9C", "#9ED3C0", "#C8442F"),   # cream and mint
    _scheme("#F4E4BE", "#E7D09E", "#F0A98A", "#2F6F8F"),   # cream and salmon
    _scheme("#EEE0BC", "#DFC998", "#A9CBE0", "#D9822B"),   # cream and sky
    _scheme("#F2E2B8", "#E5CC98", "#F2D675", "#2F6F8F"),   # cream and mustard
    _scheme("#F0E1BB", "#E2CB9A", "#C9B5DC", "#C8442F"),   # cream and lilac
]

COLLAGE_SCHEMES = [
    _scheme("#C9A878", "#B8946A", "#F4EAD5", "#D2452D"),   # kraft with cream cards
    _scheme("#C2A070", "#B08A5E", "#BFE3D4", "#D2452D"),
    _scheme("#CDAE80", "#BC986C", "#F6C9A0", "#1F6F8B"),
    _scheme("#C6A576", "#B38F62", "#CFE0F0", "#E58A1F"),
    _scheme("#CAA97A", "#B7936A", "#F7E08A", "#1F6F8B"),
    _scheme("#C4A273", "#B28D60", "#E3CBEA", "#D2452D"),
]

THEMES = {
    "classic": Theme("classic", CLASSIC_BASE, [CLASSIC_SCHEME]),
    "vector_pop": Theme(
        "vector_pop", VECTOR_BASE, VECTOR_SCHEMES, background="sunburst",
        outline=rgb("#160E3A"), outline_w=6.0, shadow=rgb("#0C0626"), shadow_off=26.0,
        stroke=rgb("#160E3A"), stroke_ratio=0.085, decor=[rgb(c) for c in (
            "#FFD60A", "#FF5CAA", "#5AB0FF", "#3CE08A", "#FF8A3D", "#B08CFF", "#6EE6E6")],
        display_font="display", hook="illustration", caption_font="Lilita One", text_scale=1.12),
    "vintage": Theme(
        "vintage", VINTAGE_BASE, VINTAGE_SCHEMES, background="paper",
        outline=rgb("#2B2118"), outline_w=4.0, shadow=rgb("#9B7F57"), shadow_off=7.0,
        decor=[rgb(c) for c in ("#C8442F", "#2F6F8F", "#D9822B", "#3E8E5A", "#7A5A8C")],
        display_font="display", hook="illustration", caption_font="Lilita One"),
    "collage": Theme(
        "collage", VINTAGE_BASE, COLLAGE_SCHEMES, background="kraft",
        outline=rgb("#2B2118"), outline_w=3.0, shadow=rgb("#6E5233"), shadow_off=6.0, edge="torn",
        decor=[rgb(c) for c in ("#D2452D", "#1F6F8B", "#E58A1F", "#3E8E5A", "#7A5A8C")],
        display_font="display", hook="illustration", caption_font="Lilita One"),
}

_active = THEMES["classic"]


def set_theme(name):
    global _active
    if name not in THEMES:
        raise ValueError(f"Unknown theme '{name}'. Known themes: {', '.join(THEMES)}")
    _active = THEMES[name]
    return _active


def current():
    return _active


def scheme_for(scene_number, theme=None):
    theme = theme or _active
    return theme.schemes[(max(1, scene_number) - 1) % len(theme.schemes)]


def apply_to_palette(palette, scene_number, theme=None):
    """Write the theme's colours for this scene into the shared palette dictionary."""
    theme = theme or _active
    scheme = scheme_for(scene_number, theme)
    palette.update(theme.base)
    palette["accent"] = scheme["accent"]
    palette["panel"] = scheme["panel"]
    palette["panel2"] = scheme["panel2"]
    palette["bg"] = tuple((a + b) // 2 for a, b in zip(scheme["bg_top"], scheme["bg_bottom"]))
    return scheme


# ============================================================================
# from animation/two_d/canvas.py
# ============================================================================
# Drawing helpers: a canvas, colours, fonts and text layout (Pillow only).













def hexrgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


PALETTE = {name: hexrgb(code) for name, code in {
    "bg": "#0B1220", "panel": "#16213A", "panel2": "#1E2B4A", "text": "#F1F5F9",
    "muted": "#94A3B8", "accent": "#2DD4BF", "good": "#34D399", "warn": "#F59E0B",
    "bad": "#F87171", "blue": "#60A5FA", "violet": "#A78BFA",
}.items()}

@contextmanager
def use_theme(name):
    """Switch to the theme `name` for a `with` block, then put the old theme and colours back."""
    previous = current()
    saved_palette = dict(PALETTE)
    set_theme(name)
    try:
        yield current()
    finally:
        set_theme(previous.name)
        PALETTE.clear()
        PALETTE.update(saved_palette)


FONT_FILES = {
    "sans": ["DejaVuSans.ttf", "FreeSans.ttf", "LiberationSans-Regular.ttf"],
    "bold": ["DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "LiberationSans-Bold.ttf"],
    "mono": ["DejaVuSansMono.ttf", "FreeMono.ttf", "LiberationMono-Regular.ttf"],
    "strong": ["DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "LiberationSans-Bold.ttf"],
    "display": ["LilitaOne-Regular.ttf", "DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "LiberationSans-Bold.ttf"],
}
FONT_DIRS = [str(Path(__file__).resolve().parents[2] / "assets" / "fonts"), "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/truetype/freefont",
             "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/TTF", "/Library/Fonts"]


@lru_cache(maxsize=None)
def load_font(kind, size):
    for name in FONT_FILES[kind]:
        for folder in FONT_DIRS:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def mix(color, background, amount):
    """Blend `color` toward `background`; amount 1 = full colour, 0 = invisible."""
    return tuple(round(background[i] + (color[i] - background[i]) * amount) for i in range(3))


def clamp(x, low=0.0, high=1.0):
    return max(low, min(high, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp(x)
    return 3 * x * x - 2 * x ** 3


def appear(t, start, length=0.15):
    """0 before `start`, rising to 1 over `length` (all in scene progress 0..1)."""
    return ease_out((t - start) / length)


SUPERSCRIPT = str.maketrans("0123456789-", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207b")
SUBSCRIPT = str.maketrans("0123456789", "\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089")


def pretty_math(text):
    """'m^3 kg^-1' -> 'm³ kg⁻¹', 'CH3COOH' -> 'CH₃COOH', '->' -> '→'."""
    text = text.replace("->", " \u2192 ")
    text = re.sub(r"\^(-?\d+)", lambda m: m.group(1).translate(SUPERSCRIPT), text)
    text = re.sub(r"(?<=[A-Za-z)])(\d+)", lambda m: m.group(1).translate(SUBSCRIPT), text)
    return " ".join(text.split())


class Canvas:
    """One frame. Sizes are given in 'units' where the shorter side is 1080 units."""

    def __init__(self, width, height, scheme=None, seed=1):
        self.w, self.h = width, height
        self.u = min(width, height) / 1080.0
        self.portrait = height > width
        self.theme = current()
        self.scheme = scheme
        self.seed = seed
        self.img = Image.new("RGB", (width, height), PALETTE["bg"])
        self.d = ImageDraw.Draw(self.img, "RGBA")

    def paint_background(self, secs=0.0):
        """Draw the theme's background (gradient, rays, shapes or paper). The classic theme stays flat."""
        if self.theme.background != "flat" and self.scheme is not None:
            pass
            paint(self, secs)

    # colours and sizes
    def px(self, units):
        return units * self.u

    def col(self, name, alpha=1.0):
        base = PALETTE[name] if isinstance(name, str) else name
        return mix(base, PALETTE["bg"], clamp(alpha))

    def font(self, kind, size):
        if kind == "bold":
            kind = self.theme.display_font
        elif kind == "sans":
            kind = self.theme.body_font
        return load_font(kind, max(8, round(size * getattr(self.theme, "text_scale", 1.0) * self.u)))

    @property
    def inner(self):
        """Colour name for panels drawn on top of cards: darker than the card in themed looks."""
        return "panel" if self.theme.name == "classic" else "panel2"

    @staticmethod
    def kind_for(text, kind):
        """The display font only has plain letters. Text with symbols (subscripts, arrows) uses a full font."""
        if kind == "bold" and any(not (0x20 <= ord(ch) <= 0x7E) for ch in text):
            return "strong"
        return kind

    def _text(self, xy, text, font, color, alpha, anchor, size):
        """Draw text, with an outline in themes that ask for one."""
        th = self.theme
        stroke = {}
        if getattr(th, "stroke", None) and size >= 30:
            stroke = {"stroke_width": max(2, round(size * getattr(th, "text_scale", 1.0) * self.u * getattr(th, "stroke_ratio", 0.06))),
                      "stroke_fill": self.col(getattr(th, "stroke", None), alpha)}
        self.d.text(xy, text, font=font, fill=self.col(color, alpha), anchor=anchor, **stroke)

    def content_box(self):
        margin = 0.07 * self.w
        bottom = 0.80 * self.h
        return (margin, 0.07 * self.h, self.w - margin, bottom)

    # text
    def wrap(self, text, font, max_width):
        lines, current = [], ""
        for word in text.split():
            trial = (current + " " + word).strip()
            if current and font.getlength(trial) > max_width:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        return lines

    def text_height(self, lines, size, line_gap=1.3):
        return len(lines) * size * getattr(self.theme, "text_scale", 1.0) * self.u * line_gap

    def paragraph(self, x, y, text, size, color="text", max_width=None, kind="sans", align="left",
                  alpha=1.0, line_gap=1.3):
        """Draw wrapped text; (x, y) is the top-left (or top-centre when align='center'). Returns bottom y."""
        font = self.font(self.kind_for(text, kind), size)
        max_width = max_width or (self.w - x)
        lines = self.wrap(text, font, max_width)
        step = size * getattr(self.theme, "text_scale", 1.0) * self.u * line_gap
        for i, line in enumerate(lines):
            self._text((x, y + i * step), line, font, color, alpha, "ma" if align == "center" else "la", size)
        return y + len(lines) * step

    def paragraph_rich(self, x, y, text, size, color_for_word, max_width, kind="sans", align="left",
                       alpha=1.0, line_gap=1.3):
        """Like paragraph, but each word can have its own colour: color_for_word(word) -> colour name."""
        font = self.font(self.kind_for(text, kind), size)
        space = font.getlength(" ")
        lines, current, width = [], [], 0.0
        for word in text.split():
            w = font.getlength(word)
            if current and width + space + w > max_width:
                lines.append((current, width))
                current, width = [word], w
            else:
                width += (space if current else 0) + w
                current.append(word)
        if current:
            lines.append((current, width))
        step = size * getattr(self.theme, "text_scale", 1.0) * self.u * line_gap
        for i, (words, line_w) in enumerate(lines):
            cursor = x - line_w / 2 if align == "center" else x
            for word in words:
                self._text((cursor, y + i * step), word, font, color_for_word(word), alpha, "la", size)
                cursor += font.getlength(word) + space
        return y + len(lines) * step

    def fit_size(self, text, max_width, max_height, max_size, min_size, kind="sans", line_gap=1.3):
        """Largest font size (units) whose wrapped text fits the box."""
        size = max_size
        kind = self.kind_for(text, kind)
        while size > min_size:
            lines = self.wrap(text, self.font(kind, size), max_width)
            if self.text_height(lines, size, line_gap) <= max_height:
                return size
            size -= 2
        return min_size

    def label(self, xy, text, size, color="text", kind="sans", anchor="la", alpha=1.0):
        self._text(xy, text, self.font(self.kind_for(text, kind), size), color, alpha, anchor, size)

    # shapes
    def _torn(self, box, jitter):
        """A rectangle outline with a rough, torn-paper edge (the same box always tears the same way)."""
        x0, y0, x1, y1 = box
        rng = random.Random(int(x0 * 7 + y0 * 13 + x1 * 17 + y1 * 19) + self.seed)
        step = max(14.0, 26 * self.u)
        pts = []
        for x in range(int(x0), int(x1), int(step)):
            pts.append((x, y0 + rng.uniform(-jitter, jitter)))
        for y in range(int(y0), int(y1), int(step)):
            pts.append((x1 + rng.uniform(-jitter, jitter), y))
        for x in range(int(x1), int(x0), -int(step)):
            pts.append((x, y1 + rng.uniform(-jitter, jitter)))
        for y in range(int(y1), int(y0), -int(step)):
            pts.append((x0 + rng.uniform(-jitter, jitter), y))
        return pts

    def rect(self, box, fill=None, radius=0, outline=None, width=0, alpha=1.0, sticker=None):
        """A rectangle. In themes with outlines, larger rounded boxes become 'stickers' with a shadow."""
        th = self.theme
        wide = (box[2] - box[0]) >= 40 * self.u and (box[3] - box[1]) >= 30 * self.u
        if sticker is None:
            sticker = bool(th.outline and fill and outline is None and radius and wide)
        if sticker:
            off = th.shadow_off * self.u
            shadow_box = (box[0] + off, box[1] + off, box[2] + off, box[3] + off)
            ow = max(2, round(th.outline_w * self.u))
            if th.edge == "torn":
                jitter = 4.5 * self.u
                self.d.polygon(self._torn(shadow_box, jitter), fill=self.col(th.shadow, alpha))
                pts = self._torn(box, jitter)
                self.d.polygon(pts, fill=self.col(fill, alpha), outline=self.col(th.outline, alpha), width=ow)
                tape = self.col((235, 222, 170), alpha * 0.85)
                for cx in (box[0] + 40 * self.u, box[2] - 40 * self.u):
                    self.d.polygon([(cx - 26 * self.u, box[1] - 10 * self.u), (cx + 26 * self.u, box[1] - 4 * self.u),
                                    (cx + 22 * self.u, box[1] + 14 * self.u), (cx - 30 * self.u, box[1] + 8 * self.u)],
                                   fill=tape)
            else:
                self.d.rounded_rectangle(shadow_box, radius=radius * self.u, fill=self.col(th.shadow, alpha))
                self.d.rounded_rectangle(box, radius=radius * self.u, fill=self.col(fill, alpha),
                                         outline=self.col(th.outline, alpha), width=ow)
            return
        fill = self.col(fill, alpha) if fill else None
        outline = self.col(outline, alpha) if outline else None
        if radius:
            self.d.rounded_rectangle(box, radius=radius * self.u, fill=fill, outline=outline,
                                     width=max(0, round(width * self.u)))
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=max(0, round(width * self.u)))

    def circle(self, center, radius, fill=None, outline=None, width=0, alpha=1.0):
        x, y = center
        box = (x - radius, y - radius, x + radius, y + radius)
        self.d.ellipse(box, fill=self.col(fill, alpha) if fill else None,
                       outline=self.col(outline, alpha) if outline else None,
                       width=max(0, round(width * self.u)))

    def line(self, p0, p1, color="text", width=4, alpha=1.0):
        self.d.line([p0, p1], fill=self.col(color, alpha), width=max(1, round(width * self.u)))

    def arrow(self, p0, p1, color="text", width=6, alpha=1.0):
        """A line with an arrow head at p1 (used for force vectors and flow)."""
        import math
        self.line(p0, p1, color, width, alpha)
        angle = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        head = 26 * self.u
        spread = math.radians(26)
        pts = [p1,
               (p1[0] - head * math.cos(angle - spread), p1[1] - head * math.sin(angle - spread)),
               (p1[0] - head * math.cos(angle + spread), p1[1] - head * math.sin(angle + spread))]
        self.d.polygon(pts, fill=self.col(color, alpha))

    def polygon(self, points, fill, alpha=1.0):
        self.d.polygon(points, fill=self.col(fill, alpha))


# ============================================================================
# from animation/two_d/icons.py
# ============================================================================
# Simple animated icons drawn from basic shapes. No image files are used.




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


# ============================================================================
# from animation/two_d/illustrations.py
# ============================================================================
# Cartoon illustrations drawn from flat shapes with thick outlines: hammer and feather characters on the











ILLUSTRATIONS_INK = (22, 14, 58)
STEEL, STEEL_LIGHT = (148, 166, 204), (206, 220, 248)
WOOD, WOOD_DARK = (222, 154, 84), (176, 112, 52)
PINK, PINK_LIGHT = (255, 120, 170), (255, 196, 218)
CHEEK = (255, 120, 140, 150)


def _clamp(x):
    return max(0.0, min(1.0, x))


def _illustrations_ow(s, width=6):
    return max(3, round(width * s))


# ------------------------------------------------------------------ small drawing helpers
def _illustrations_poly(d, pts, fill, s, width=6):
    d.polygon(pts, fill=fill, outline=ILLUSTRATIONS_INK, width=_illustrations_ow(s, width))


def _ellipse(d, box, fill, s, width=6):
    d.ellipse(box, fill=fill, outline=ILLUSTRATIONS_INK, width=_illustrations_ow(s, width))


def _rrect(d, box, radius, fill, s, width=6):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=ILLUSTRATIONS_INK, width=_illustrations_ow(s, width))


def _illustrations_sparkle(d, cx, cy, r, color):
    pts = []
    for i in range(8):
        rr = r if i % 2 == 0 else r * 0.28
        a = i * math.pi / 4 - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=color)


def _illustrations_face(d, cx, cy, size, s, look=(0.0, 0.3), mood="happy"):
    """Two eyes, rosy cheeks and a smile. `look` moves the pupils (-1 to 1)."""
    eye_dx, eye_r = size * 0.24, size * 0.13
    for sign in (-1, 1):
        ex = cx + sign * eye_dx
        d.ellipse((ex - eye_r, cy - eye_r * 1.25, ex + eye_r, cy + eye_r * 1.25), fill=(255, 255, 255), outline=ILLUSTRATIONS_INK,
                  width=_illustrations_ow(s, 4))
        px, py = ex + look[0] * eye_r * 0.45, cy + look[1] * eye_r * 0.5
        pr = eye_r * 0.55
        d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=ILLUSTRATIONS_INK)
        d.ellipse((px - pr * 0.1, py - pr * 0.75, px + pr * 0.5, py - pr * 0.15), fill=(255, 255, 255))
        d.ellipse((cx + sign * size * 0.42 - size * 0.07, cy + size * 0.12, cx + sign * size * 0.42 + size * 0.07,
                   cy + size * 0.24), fill=CHEEK)
    mw = size * (0.26 if mood == "happy" else 0.18)
    d.arc((cx - mw, cy + size * 0.02, cx + mw, cy + size * 0.30), 15, 165, fill=ILLUSTRATIONS_INK, width=_illustrations_ow(s, 5))


# ------------------------------------------------------------------ characters
def draw_hammer(d, cx, bottom, k, s, look=(0.0, 0.4)):
    """A hammer character. k scales it (the whole figure is about 380 * k tall)."""
    handle = (cx - 22 * k, bottom - 270 * k, cx + 22 * k, bottom)
    _rrect(d, handle, 16 * k, WOOD, s)
    for i in range(4):
        y = bottom - (60 + i * 55) * k
        d.line([(cx - 10 * k, y), (cx + 10 * k, y - 14 * k)], fill=WOOD_DARK, width=_illustrations_ow(s, 4))
    head = (cx - 120 * k, bottom - 390 * k, cx + 120 * k, bottom - 262 * k)
    _rrect(d, head, 34 * k, STEEL, s)
    d.rounded_rectangle((head[0] + 18 * k, head[1] + 14 * k, head[2] - 18 * k, head[1] + 34 * k), radius=10 * k,
                        fill=STEEL_LIGHT)
    _illustrations_face(d, cx, head[1] + 66 * k, 120 * k, s, look)


def draw_feather(d, cx, bottom, k, s, look=(0.0, 0.4)):
    """A feather character with a face. About 380 * k tall."""
    length = 340 * k
    spine = lambda t: (cx + 38 * k * math.sin(t * math.pi * 0.9), bottom - 40 * k - t * length)  # noqa: E731
    width = lambda t: 66 * k * (math.sin(math.pi * min(1.0, max(0.0, t))) ** 0.7)  # noqa: E731
    d.line([(cx, bottom), spine(0.1)], fill=ILLUSTRATIONS_INK, width=_illustrations_ow(s, 12))
    d.line([(cx, bottom), spine(0.1)], fill=(255, 250, 240), width=_illustrations_ow(s, 5))
    left, right = [], []
    for i in range(0, 21):
        t = 0.08 + 0.92 * i / 20
        x, y = spine(t)
        left.append((x - width(t), y))
        right.append((x + width(t), y))
    outline = left + right[::-1]
    _illustrations_poly(d, outline, PINK, s)
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
            d.line([(x + sign * width(t) * 0.55, y + 8 * k), (x + sign * width(t) * 0.95, y - 6 * k)], fill=ILLUSTRATIONS_INK,
                   width=_illustrations_ow(s, 3))
    fx, fy = spine(0.52)
    _illustrations_face(d, fx, fy - 6 * k, 96 * k, s, look)


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
        _illustrations_sparkle(d, sx, sy, r, rng.choice([(255, 236, 130), (255, 255, 255), (170, 230, 255)]))
    ex, ey, er = x0 + 0.82 * w, y0 + 0.20 * h, 0.12 * min(w, h)
    _ellipse(d, (ex - er, ey - er, ex + er, ey + er), (70, 156, 242), s)
    for blob in ([(-0.5, -0.3), (-0.1, -0.55), (0.25, -0.2), (-0.1, 0.1)], [(0.1, 0.35), (0.5, 0.2), (0.45, 0.6)]):
        d.polygon([(ex + bx * er * 0.85, ey + by * er * 0.85) for bx, by in blob], fill=(96, 206, 130))
    d.arc((ex - er * 0.8, ey - er * 0.8, ex + er * 0.8, ey + er * 0.8), 200, 260, fill=(255, 255, 255), width=_illustrations_ow(s, 6))
    ground_y = y0 + 0.80 * h
    _ellipse(d, (x0 - 0.15 * w, y0 + 0.70 * h, x1 + 0.15 * w, y0 + 1.50 * h), (214, 216, 238), s, 7)
    d.arc((x0 - 0.05 * w, y0 + 0.73 * h, x1 + 0.05 * w, y0 + 1.1 * h), 205, 335, fill=(255, 255, 255), width=_illustrations_ow(s, 9))
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
                       fill=(255, 255, 255, 190), width=_illustrations_ow(s, 6))
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
        _illustrations_sparkle(d, x0 + rng.uniform(0.04, 0.96) * w, y0 + rng.uniform(0.04, 0.5) * h,
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
    d.polygon(liquid, fill=(255, 92, 170), outline=ILLUSTRATIONS_INK, width=_illustrations_ow(s, 5))
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
        d.ellipse((bx - r, by - r, bx + r, by + r), fill=(255, 255, 255, int(a * 0.55)), outline=ILLUSTRATIONS_INK + (a,),
                  width=_illustrations_ow(s, 4))
        d.ellipse((bx - r * 0.55, by - r * 0.6, bx - r * 0.1, by - r * 0.2), fill=(255, 255, 255, a))
        if r > 30 * s and labelled < 2 and fade > 0.8:
            c.label((bx, by), "CO\u2082", max(14, r / s * 0.5), "text", kind="bold", anchor="mm")
            labelled += 1
    glass_line = glass + [glass[0]]
    d.line(glass_line, fill=ILLUSTRATIONS_INK, width=_illustrations_ow(s, 8), joint="curve")
    d.line([(cx - top_w / 2 - 10 * s, top_y), (cx + top_w / 2 + 10 * s, top_y)], fill=ILLUSTRATIONS_INK, width=_illustrations_ow(s, 10))
    d.line([(cx - top_w / 2 + 30 * s, top_y + 40 * s), (cx - bot_w / 2 + 30 * s, bot_y - 40 * s)],
           fill=(255, 255, 255, 170), width=_illustrations_ow(s, 9))
    _illustrations_face(d, cx, surface + 120 * s, 150 * s, s, (0.0, -0.5 if p < 0.7 else 0.0))


BUILDERS = {"drop": moon_scene, "beaker": beaker_scene, "designed": None}  # "designed" is drawn by asset_designer


def render_illustration(record, t, width, height, secs=0.0, ss=2):
    """A PIL image of the topic's cartoon scene, or None if the topic has none."""
    kind = (record.get("scene3d") or {}).get("kind")
    if kind not in BUILDERS:
        return None
    canvas = Canvas(width * ss, height * ss)
    if kind == "designed":
        designed_scene(canvas, (0, 0, width * ss, height * ss), t, secs, record)
    else:
        BUILDERS[kind](canvas, (0, 0, width * ss, height * ss), t, secs)
    return canvas.img.resize((width, height), Image.LANCZOS) if ss > 1 else canvas.img


# ============================================================================
# from animation/two_d/sim_draw.py
# ============================================================================
# Draws the simulations (free fall and gas release) as 2D frames.







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
        draw_hammer(c.d, x, bottom, c.px(112) / 390.0, c.u * 0.75)
        return
    c.rect((x - c.px(7), bottom - c.px(52), x + c.px(7), bottom), fill="warn", radius=4)
    c.rect((x - c.px(40), bottom - c.px(84), x + c.px(40), bottom - c.px(48)), fill="muted", radius=6)


def _draw_feather(c, x, bottom):
    if c.theme.name != "classic":
        draw_feather(c.d, x, bottom, c.px(112) / 390.0, c.u * 0.75)
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
    if variant == "terminal_speed":
        return _terminal_scene(c, t)
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


# ------------------------------------------------------------------ terminal speed
TERMINAL_SECONDS = 14.0


def _person(c, cx, cy, big):
    """A simple falling person; with a big area a parachute canopy is drawn above."""
    c.circle((cx, cy - c.px(52)), c.px(15), fill="text")
    c.line((cx, cy - c.px(36)), (cx, cy + c.px(22)), "text", 7)
    c.line((cx, cy - c.px(22)), (cx - c.px(26), cy - c.px(4)), "text", 6)
    c.line((cx, cy - c.px(22)), (cx + c.px(26), cy - c.px(4)), "text", 6)
    c.line((cx, cy + c.px(22)), (cx - c.px(16), cy + c.px(58)), "text", 6)
    c.line((cx, cy + c.px(22)), (cx + c.px(16), cy + c.px(58)), "text", 6)
    if big:
        r = c.px(64)
        top = cy - c.px(130)
        c.d.pieslice((cx - r, top, cx + r, top + 2 * r * 0.8), 180, 360, fill=c.col("accent"))
        c.line((cx - r, top + r * 0.8), (cx, cy - c.px(36)), "muted", 3)
        c.line((cx + r, top + r * 0.8), (cx, cy - c.px(36)), "muted", 3)


def _terminal_panel(c, box, title, color, curve, secs):
    x0, y0, x1, y1 = box
    c.rect(box, fill=c.inner, radius=18)
    c.label(((x0 + x1) / 2, y0 + c.px(20)), title, 26, color, kind="bold", anchor="ma")
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2 + c.px(30)
    vt = curve["v_terminal"]
    v = ff.speed_in_air(vt, secs)
    share = clamp(v / vt)
    # streaks rushing past show the speed
    for i in range(7):
        sx = x0 + (x1 - x0) * (0.12 + 0.76 * ((i * 0.37) % 1.0))
        base = ((secs * share * 3.0 + i * 0.19) % 1.0)
        sy = y0 + c.px(80) + base * (y1 - y0 - c.px(160))
        c.line((sx, sy), (sx, sy + c.px(10) + c.px(60) * share), "muted", 3)
    _person(c, cx, cy, curve["name"] == "big")
    unit = min(c.px(120), (y1 - y0) * 0.22)
    arrow_x = c.px(86)
    pull_start = cy + c.px(30)
    c.arrow((cx + arrow_x, pull_start), (cx + arrow_x, pull_start + unit), "warn", 8)
    c.label((cx + arrow_x, pull_start + unit + c.px(8)), "gravity pulls", 20, "warn", anchor="ma")
    push = unit * share * share
    top_start = cy + c.px(30)
    if push > c.px(6):
        c.arrow((cx - arrow_x, top_start), (cx - arrow_x, top_start - push), "accent", 8)
    c.label((cx - arrow_x, top_start + c.px(8)), "air pushes", 20, "accent", anchor="ma")
    c.label((cx, y1 - c.px(44)), f"{v:.0f} m/s", 34, "text", kind="bold", anchor="ma")
    if share > 0.97:
        c.label((cx, y1 - c.px(84)), "steady speed", 24, "good", kind="bold", anchor="ma")


def _terminal_scene(c, t):
    """Two falls side by side: the push of the air grows until it matches gravity, then the speed stops growing."""
    x0, y0, x1, y1 = c.content_box()
    secs = clamp((t - 0.08) / 0.75) * TERMINAL_SECONDS
    small = ff.terminal_curve("small", TERMINAL_SECONDS)
    big = ff.terminal_curve("big", TERMINAL_SECONDS)
    area_top = y0 + c.px(10)
    area_bottom = y1 - (c.px(400) if c.portrait else c.px(330))
    gap = c.px(20)
    width = (x1 - x0 - gap) / 2
    _terminal_panel(c, (x0, area_top, x0 + width, area_bottom), "SMALL AREA", "warn", small, secs)
    _terminal_panel(c, (x0 + width + gap, area_top, x1, area_bottom), "BIG AREA", "accent", big, secs)
    curves = [("small area", "warn", small, False), ("big area", "accent", big, False)]
    _graph(c, (x0, area_bottom + c.px(16), x1, y1), curves, secs, TERMINAL_SECONDS)
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


# ============================================================================
# from animation/two_d/diagrams.py
# ============================================================================
# Animated explanatory diagrams and list cards. Each function returns True if it drew something,







def _label(c, box, scene, color="accent"):
    """Section names (Demonstration, Conclusion...) are no longer shown. This only keeps the spacing."""
    return box[1] + c.px(80)


def _objects(c, x_hammer, x_feather, bottom, a=1.0):
    _draw_hammer(c, x_hammer, bottom)
    _draw_feather(c, x_feather, bottom)


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
        (_draw_hammer if name == "hammer" else _draw_feather)(c, x, mid + c.px(40))
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


# ============================================================================
# from animation/two_d/scene_plan.py
# ============================================================================
# A topic's own pictures: shapes, arrows and labels that move, drawn on the canvas.


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


def _scene_plan_num(value, low, high, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not low <= value <= high:
        raise PlanError(f"{what} must be a number from {low:g} to {high:g}")
    return float(value)


def _in_stage(x, y, what):
    _scene_plan_num(x, *X_RANGE, f"{what} x")
    _scene_plan_num(y, *Y_RANGE, f"{what} y")


def _element(raw, where):
    if not isinstance(raw, dict) or raw.get("type") not in TYPES:
        raise PlanError(f"{where}: unknown element type")
    kind = raw["type"]
    e = {"type": kind}
    e["color"] = raw.get("color", "text" if kind == "text" else "accent")
    if e["color"] not in COLORS:
        raise PlanError(f"{where}: unknown colour '{e['color']}'")
    e["alpha"] = _scene_plan_num(raw.get("alpha", 1.0), 0.15, 1.0, f"{where} alpha")
    e["appear"] = _scene_plan_num(raw.get("appear", 0.0), 0.0, 0.9, f"{where} appear")
    e["dx"] = _scene_plan_num(raw.get("dx", 0.0), -120.0, 120.0, f"{where} dx")
    e["dy"] = _scene_plan_num(raw.get("dy", 0.0), -120.0, 120.0, f"{where} dy")
    e["from"] = _scene_plan_num(raw.get("from", 0.1), 0.0, 0.9, f"{where} from")
    e["to"] = _scene_plan_num(raw.get("to", 0.9), 0.1, 1.0, f"{where} to")
    if e["to"] <= e["from"]:
        raise PlanError(f"{where}: 'to' must come after 'from'")
    e["bob"] = _scene_plan_num(raw.get("bob", 0.0), 0.0, 3.0, f"{where} bob")
    if kind in ("rect", "ellipse"):
        for key in ("x", "y", "w", "h"):
            e[key] = _scene_plan_num(raw.get(key), -10.0 if key in "xy" else 1.0, 200.0, f"{where} {key}")
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
            e[key] = _scene_plan_num(raw.get(key), -10.0, 170.0, f"{where} {key}")
        _in_stage(e["x"], e["y"], where)
        _in_stage(e["x2"], e["y2"], where)
        _in_stage(e["x"] + e["dx"], e["y"] + e["dy"], where)
        _in_stage(e["x2"] + e["dx"], e["y2"] + e["dy"], where)
    else:  # text
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 24 or not text.isprintable():
            raise PlanError(f"{where}: text must be 1 to 24 plain characters")
        e["text"] = text.strip()
        e["x"], e["y"] = _scene_plan_num(raw.get("x"), *X_RANGE, f"{where} x"), _scene_plan_num(raw.get("y"), *Y_RANGE, f"{where} y")
        e["size"] = _scene_plan_num(raw.get("size", 6), 4.0, 10.0, f"{where} size")
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
    pass
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


# ============================================================================
# from animation/two_d/scenes.py
# ============================================================================
# One drawing function per animation type. Each draws a single frame at progress t (0 to 1).












def _text(scene):
    """What to show on screen. Continuation scenes have no caption, so they show their narration."""
    return scene.get("on_screen_text") or scene.get("narration", "") or ""


def _scenes_label(c, box, scene, color="accent"):
    """Section names (Demonstration, Conclusion...) are no longer shown. This only keeps the spacing."""
    return box[1] + c.px(80)


# --------------------------------------------------------------------- text
KIND_ICON = {
    "intro": "atom", "question": "question", "answer": "bulb", "explanation_l2": "bulb", "explanation_l3": "gear",
    "terminology": "book", "limitation": "info", "safety": "warning", "application": "rocket", "conclusion": "check",
    "sources": "document", "scenario_intro": "question", "prevention": "shield", "why": "bulb",
    "correct_procedure": "check", "what_changes": "gear", "consequences": "warning", "demonstration": "atom",
    "overlooked": "warning", "misconception": "question",
}
SCENES_STOP_WORDS = {"from", "with", "that", "this", "body", "large", "centre", "whole", "have", "than"}


def backdrop(c, secs, seed=3):
    """Faint dots drifting upward, so text cards are never completely still."""
    rng = random.Random(seed)
    for _ in range(16):
        x, y0 = rng.random() * c.w, rng.random() * c.h
        speed, radius, alpha = rng.uniform(8, 22) * c.u, rng.uniform(3, 9) * c.u, rng.uniform(0.07, 0.16)
        c.circle((x, (y0 - secs * speed) % c.h), radius, fill="accent", alpha=alpha)


def highlight_words(record):
    words = set()
    for variable in record.get("variables", []):
        for word in re.findall(r"[A-Za-z]+", variable.get("name", "")):
            if len(word) >= 4 and word.lower() not in SCENES_STOP_WORDS:
                words.add(word.lower())
    return words


def icon_text_card(c, t, ctx):
    """A text card with an animated icon and the topic's key words in colour."""
    scene, record = ctx["scene"], ctx["record"]
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _scenes_label(c, box, scene)
    secs = t * scene.get("duration_seconds", 5)
    a = appear(t, 0.0, 0.18)
    icon = KIND_ICON.get(scene.get("section_kind"))
    text_x, text_w, text_top, align = x0, x1 - x0, top, "left"
    if icon:
        r = c.px(105)
        if c.portrait:
            draw_icon(c, icon, (x0 + x1) / 2, top + r + c.px(20), r, secs, a)
            text_top, align = top + 2 * r + c.px(70), "center"
            text_x = (x0 + x1) / 2
        else:
            draw_icon(c, icon, x0 + r + c.px(40), (top + y1) / 2, r, secs, a)
            text_x = x0 + 2 * r + c.px(120)
            text_w = x1 - text_x
    text = _text(scene)
    avail = y1 - text_top - c.px(20)
    size = c.fit_size(text, text_w, avail * 0.9, 70, 32, "bold")
    lines = c.wrap(text, c.font("bold", size), text_w)
    start = text_top + max(0, (avail - c.text_height(lines, size)) / 2) + (1 - a) * c.px(30)
    marked = highlight_words(record)
    colour = lambda word: "accent" if re.sub(r"[^A-Za-z]", "", word).lower() in marked else "text"  # noqa: E731
    c.paragraph_rich(text_x, start, text, size, colour, text_w, "bold", align, a)


def text_card(c, t, ctx):
    """Chooses the right card for a text scene: a list card where the topic has data, else icon plus text."""
    scene = ctx["scene"]
    backdrop(c, t * scene.get("duration_seconds", 5))
    special = {"terminology": term_chips, "limitation": checklist,
               "sources": sources_list, "safety": safety_card, "outro": outro_card}
    function = special.get(scene.get("section_kind"))
    if function and function(c, t, ctx):
        return
    icon_text_card(c, t, ctx)


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
            (_draw_hammer if name == "hammer" else _draw_feather)(c, x, held)
        c.rect((c.w * 0.12, bottom - c.px(14), c.w * 0.88, bottom - c.px(6)), fill="muted", alpha=a)
    elif kind == "gas_release":
        width, height = c.px(300), min(c.px(340), bottom - top - c.px(40))
        box = (c.w / 2 - width / 2, bottom - height - drop, c.w / 2 + width / 2, bottom - drop)
        _draw_beaker(c, box, 0.35, 0.6, "open", gas.make_bubbles())


def _hook_3d(c, t, ctx, top, bottom):
    """Paste the topic's 3D opening shot into a rounded window. Returns False if the topic has none."""
    x0, _, x1, _ = c.content_box()
    width, height = int(x1 - x0), int(bottom - top)
    if height < c.px(300) or width < 50:
        return False
    ss = 2 if width * height < 1_200_000 else 1
    image = render_viewport(ctx["record"], t, width, height, ss)
    if image is None:
        return False
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=int(c.px(26)), fill=255)
    a = appear(t, 0.0, 0.15)
    c.img.paste(image, (int(x0), int(top)), mask.point(lambda v: int(v * a)))
    c.label((x0 + c.px(20), bottom - c.px(14)), "Illustrative 3D model", 22, "muted", anchor="lb", alpha=a)
    return True


def _hook_illustration(c, t, ctx, top, bottom):
    """The cartoon opening picture in a sticker frame. Returns False if the topic has none."""
    x0, _, x1, _ = c.content_box()
    width, height = int(x1 - x0), int(bottom - top)
    if height < c.px(300) or width < 50:
        return False
    secs = t * ctx["scene"].get("duration_seconds", 5)
    image = render_illustration(ctx["record"], t, width, height, secs, 2 if width * height < 1_200_000 else 1)
    if image is None:
        return False
    th = c.theme
    radius = int(c.px(30))
    off = th.shadow_off * c.u
    c.d.rounded_rectangle((x0 + off, top + off, x1 + off, bottom + off), radius=radius, fill=c.col(th.shadow or (0, 0, 0)))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    a = appear(t, 0.0, 0.15)
    c.img.paste(image, (int(x0), int(top)), mask.point(lambda v: int(v * a)))
    c.d.rounded_rectangle((x0, top, x1, bottom), radius=radius, outline=c.col(th.outline or (0, 0, 0), a),
                          width=max(3, round(max(th.outline_w, 4) * c.u)))
    return True


def hook_card(c, t, ctx):
    """Opening card: the title plus a lightweight 3D shot (a 2D picture if the topic has no 3D scene)."""
    scene = ctx["scene"]
    x0, y0, x1, y1 = c.content_box()
    a = appear(t, 0.0, 0.2)
    text = _text(scene)
    size = c.fit_size(text, x1 - x0, (y1 - y0) * 0.32, 76, 36, "bold")
    bottom = c.paragraph(x0, y0 + c.px(100) + (1 - a) * c.px(40), text, size, "text", x1 - x0, kind="bold", alpha=a)
    c.rect((x0, bottom + c.px(20), x0 + c.px(120), bottom + c.px(26)), fill="accent", alpha=a)
    top = bottom + c.px(50)
    if c.theme.hook == "illustration" and _hook_illustration(c, t, ctx, top, y1):
        return
    if not _hook_3d(c, t, ctx, top, y1):
        _hook_preview(c, t, ctx, top, y1)


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
    from research.equation_checker import _side_atoms    # imported here so the drawing package has no import of the science checks at load time
    scene, record = ctx["scene"], ctx["record"]
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _scenes_label(c, box, scene)
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
    named = DIAGRAMS.get(scene.get("data", {}).get("diagram"))
    if named and named(c, t, ctx):
        return
    box = c.content_box()
    x0, y0, x1, y1 = box
    top = _scenes_label(c, box, scene)
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
    top = _scenes_label(c, box, scene, "warn")
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
    top = _scenes_label(c, box, scene, "good")
    text = _text(scene)
    a = appear(t, 0.0, 0.25)
    slide = (1 - a) * c.px(160)
    h = min(c.px(420), (y1 - top) * 0.7)
    cx0 = x0 + slide
    c.rect((cx0, top + c.px(20), x1 + slide, top + c.px(20) + h), fill="panel", radius=26, alpha=a)
    draw_icon(c, "rocket", cx0 + c.px(100), top + c.px(20) + c.px(100), c.px(70), t * scene.get("duration_seconds", 5), a)
    size = c.fit_size(text, x1 - x0 - c.px(80), h - c.px(220), 52, 26, "bold")
    c.paragraph(cx0 + c.px(40), top + c.px(20) + c.px(190), text, size, "text", x1 - x0 - c.px(80), kind="bold", alpha=a)


# ---------------------------------------------------------------- simulation
def simulation_scene(c, t, ctx):
    kind = (ctx["record"].get("simulation") or {}).get("kind")
    if kind == "free_fall":
        return free_fall_scene(c, t, ctx)
    if kind == "gas_release":
        return gas_scene(c, t, ctx)
    # A topic without its own simulation still gets a moving picture instead of plain text cards.
    x0, y0, x1, y1 = c.content_box()
    if c.theme.hook == "illustration" and _hook_illustration(c, t, ctx, y0 + c.px(10), y1):
        return
    diagram_cards(c, t, ctx)
    _footer(c)


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


# ------------------------------------------------------- each topic's own pictures
# A topic that has a scene_plan and no hand-built simulation is drawn from its plan. Every other topic (free fall,
# gas release, ...) is drawn exactly as before. If a plan cannot be drawn, the old drawing is used instead.
_ORIGINAL = dict(SCENE_FUNCTIONS)


def _plan_of(ctx):
    record = ctx["record"]
    plan = record.get("scene_plan")
    if not plan or record.get("simulation"):
        return None
    try:
        validate(plan)
    except PlanError:
        return None
    return plan


def _plan_hook(c, t, ctx):
    plan = _plan_of(ctx)
    if plan is None:
        return _ORIGINAL["3d_scene"](c, t, ctx)
    x0, y0, x1, y1 = c.content_box()
    a = appear(t, 0.0, 0.2)
    text = _text(ctx["scene"])
    size = c.fit_size(text, x1 - x0, (y1 - y0) * 0.32, 76, 36, "bold")
    bottom = c.paragraph(x0, y0 + c.px(100) + (1 - a) * c.px(40), text, size, "text", x1 - x0, kind="bold", alpha=a)
    c.rect((x0, bottom + c.px(20), x0 + c.px(120), bottom + c.px(26)), fill="accent", alpha=a)
    draw(c, t, ctx["scene"], plan, (x0, bottom + c.px(50), x1, y1))


def _plan_simulation(c, t, ctx):
    plan = _plan_of(ctx)
    if plan is None:
        return _ORIGINAL["simulation"](c, t, ctx)
    x0, y0, x1, y1 = c.content_box()
    if draw(c, t, ctx["scene"], plan, (x0, y0 + c.px(10), x1, y1)):
        _footer(c)
    else:
        _ORIGINAL["simulation"](c, t, ctx)


def _plan_diagram(c, t, ctx):
    plan = _plan_of(ctx)
    named = DIAGRAMS.get((ctx["scene"].get("data") or {}).get("diagram"))
    if plan is None or named:
        return _ORIGINAL["2d_diagram"](c, t, ctx)
    x0, y0, x1, y1 = c.content_box()
    if not draw(c, t, ctx["scene"], plan, (x0, y0 + c.px(10), x1, y1)):
        _ORIGINAL["2d_diagram"](c, t, ctx)


SCENE_FUNCTIONS["3d_scene"] = _plan_hook
SCENE_FUNCTIONS["simulation"] = _plan_simulation
SCENE_FUNCTIONS["2d_diagram"] = _plan_diagram


# ============================================================================
# from animation/two_d/renderer.py
# ============================================================================
# Turns storyboard scenes into short MP4 clips (silent; audio arrives in Stage 7).












BRAND = "SCICLIPS"
QUALITY = {"draft": {"scale": 0.5, "fps": 12}, "full": {"scale": 1.0, "fps": None}}


class RenderError(Exception):
    """Raised when a clip cannot be rendered."""


def even(value):
    value = int(round(value))
    return value if value % 2 == 0 else value + 1


def frame_size(storyboard, quality):
    width, height = (int(v) for v in storyboard["resolution"].split("x"))
    scale = QUALITY[quality]["scale"]
    return even(width * scale), even(height * scale)


def frame_rate(storyboard, quality):
    return QUALITY[quality]["fps"] or storyboard["fps"]


def draw_frame(scene, record, width, height, t):
    """Draw one frame of a scene at progress t (0 to 1) and return a Pillow image."""
    number = scene.get("scene_number", 1)
    scheme = apply_to_palette(PALETTE, number)
    canvas = Canvas(width, height, scheme, seed=number)
    canvas.paint_background(t * scene.get("duration_seconds", 5))
    function = SCENE_FUNCTIONS.get(scene["animation_type"])
    if function is None:
        raise RenderError(f"No drawing function for animation type '{scene['animation_type']}'")
    function(canvas, t, {"scene": scene, "record": record})
    if scene.get("section_kind") != "outro":
        # The channel name sits at the top of every frame, above where the content starts.
        canvas.label((width / 2, canvas.px(26)), BRAND, 46, "text", kind="bold", anchor="ma")
    return canvas.img


def _backdrop(scene, size, secs):
    """The scene's own background with nothing on it, so fades and wipes start from the right colours."""
    if current().background == "flat":
        return Image.new("RGB", size, PALETTE["bg"])
    number = scene.get("scene_number", 1)
    canvas = Canvas(size[0], size[1], scheme_for(number), seed=number)
    canvas.paint_background(secs)
    return canvas.img


def apply_transition(image, scene, secs, total_secs):
    """Fade or wipe a frame in or out. `secs` is the time into the scene. Timing is unchanged, so audio stays in sync."""
    kind = scene.get("transition", "cut")
    width, height = image.size
    bg = _backdrop(scene, image.size, secs) if kind in ("fade", "fade out", "wipe") and secs < 0.5 else \
        Image.new("RGB", image.size, PALETTE["bg"])
    black = Image.new("RGB", image.size, (0, 0, 0))
    if kind == "fade in":
        image = Image.blend(black, image, clamp(secs / 0.6))
    elif kind in ("fade", "fade out"):
        image = Image.blend(bg, image, clamp(secs / 0.25))
        if kind == "fade out":
            image = Image.blend(black, image, clamp((total_secs - secs) / 0.8))
    elif kind == "wipe":
        reveal = int(width * ease_in_out(secs / 0.4))
        if reveal < width:
            bg.paste(image.crop((0, 0, reveal, height)), (0, 0))
            image = bg
    return image


def plan_frames(storyboard, fps):
    """Frame count for each scene, worked out from running totals so the video never drifts from the audio."""
    counts, clock, drawn = {}, 0.0, 0
    for scene in storyboard["scenes"]:
        clock += scene["duration_seconds"]
        end = round(clock * fps)
        counts[scene["scene_number"]] = max(2, end - drawn)
        drawn += counts[scene["scene_number"]]
    return counts


def render_scene(scene, record, out_path, width, height, fps, poster_path=None, frames=None):
    """Render one scene to an MP4. Returns a small report dict."""
    if shutil.which("ffmpeg") is None:
        raise RenderError("FFmpeg was not found. Install it (sudo apt-get install -y ffmpeg).")
    frames = frames or max(2, round(scene["duration_seconds"] * fps))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
               str(out_path)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    poster_index = int(0.85 * (frames - 1))
    try:
        for i in range(frames):
            image = draw_frame(scene, record, width, height, i / (frames - 1))
            image = apply_transition(image, scene, i / fps, frames / fps)
            if poster_path and i == poster_index:
                Path(poster_path).parent.mkdir(parents=True, exist_ok=True)
                image.save(poster_path)
            process.stdin.write(image.tobytes())
        process.stdin.close()
        error = process.stderr.read().decode("utf-8", "replace")
        code = process.wait()
    except BrokenPipeError:
        error = process.stderr.read().decode("utf-8", "replace")
        raise RenderError(f"FFmpeg stopped early: {error.strip()}")
    except Exception:
        process.kill()
        raise
    if code != 0:
        raise RenderError(f"FFmpeg failed (exit {code}): {error.strip()}")
    return {"scene_number": scene["scene_number"], "path": str(out_path),
            "poster": str(poster_path) if poster_path else None, "frames": frames, "fps": fps,
            "width": width, "height": height, "duration_seconds": scene["duration_seconds"],
            "clip_seconds": frames / fps}


def make_contact_sheet(poster_paths, out_path, columns=4, thumb_width=300):
    """One picture showing a thumbnail of every scene, so a person can review quickly."""
    images = [Image.open(p).convert("RGB") for p in poster_paths]
    if not images:
        return None
    ratio = images[0].height / images[0].width
    thumb_h = int(thumb_width * ratio)
    rows = (len(images) + columns - 1) // columns
    pad = 12
    sheet = Image.new("RGB", (columns * (thumb_width + pad) + pad, rows * (thumb_h + pad + 22) + pad), PALETTE["bg"])
    draw = ImageDraw.Draw(sheet)
    font = load_font("sans", 16)
    for index, image in enumerate(images):
        row, col = divmod(index, columns)
        x = pad + col * (thumb_width + pad)
        y = pad + row * (thumb_h + pad + 22)
        sheet.paste(image.resize((thumb_width, thumb_h)), (x, y + 22))
        draw.text((x, y), f"Scene {index + 1}", font=font, fill=PALETTE["muted"])
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return str(out_path)


def _render_job(job):
    scene, record, path, width, height, fps, poster, frames, theme_name = job
    set_theme(theme_name)
    return render_scene(scene, record, path, width, height, fps, poster, frames)


def default_workers():
    """How many scenes to draw at once: the RENDER_WORKERS setting, else up to 4 (the CPUs the runner has)."""
    setting = os.environ.get("RENDER_WORKERS")
    if setting and setting.isdigit() and int(setting) > 0:
        return int(setting)
    return max(1, min(4, os.cpu_count() or 1))


def render_storyboard(storyboard, record, out_dir, quality="draft", only_scenes=None, workers=None):
    """Render every scene (or the numbers in only_scenes). Several scenes are drawn at once when workers > 1."""
    if quality not in QUALITY:
        raise RenderError(f"Unknown quality '{quality}'. Use draft or full.")
    width, height = frame_size(storyboard, quality)
    fps = frame_rate(storyboard, quality)
    out_dir = Path(out_dir)
    counts = plan_frames(storyboard, fps)
    jobs = []
    for scene in storyboard["scenes"]:
        if only_scenes and scene["scene_number"] not in only_scenes:
            continue
        number = scene["scene_number"]
        jobs.append((scene, record, str(out_dir / f"scene_{number:03d}.mp4"), width, height, fps,
                     str(out_dir / f"scene_{number:03d}.png"), counts[number], current().name))
    workers = workers or default_workers()
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            reports = list(pool.map(_render_job, jobs))
    else:
        reports = [_render_job(job) for job in jobs]
    sheet = make_contact_sheet([r["poster"] for r in reports], out_dir / "contact_sheet.png")
    for report in reports:
        report["contact_sheet"] = sheet
    return reports


def save_thumbnail(storyboard, record, out_path, quality="draft", t=0.85):
    """A still picture from the opening scene, as a JPEG small enough for upload sites."""
    width, height = frame_size(storyboard, quality)
    image = draw_frame(storyboard["scenes"][0], record, width, height, t)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "JPEG", quality=90)
    return str(out_path)


# ============================================================================
# from animation/two_d/thumbnail.py
# ============================================================================
# Thumbnails: a bold headline, a cartoon illustration in a sticker frame, a question badge and a ribbon.








SIZES = {"long": (1280, 720), "short": (1080, 1920)}
SS = 2
THUMBNAIL_INK = (22, 14, 58)
LINE_COLOURS = [(255, 226, 60), (255, 255, 255), (255, 110, 175)]


def _headline_text(record):
    spec = record.get("thumbnail") or {}
    if spec.get("headline"):
        return spec["headline"].upper()
    words = record["title"].rstrip("?.! ").upper().split()
    return " ".join(words[:5])


def _font(px):
    return load_font(current().display_font, max(8, int(px)))


def _wrap(text, font, max_width):
    lines, current = [], ""
    for word in text.split():
        trial = (current + " " + word).strip()
        if current and font.getlength(trial) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _fit(text, max_w, max_h, max_px, min_px, max_lines=3):
    px = max_px
    while px > min_px:
        font = _font(px)
        lines = _wrap(text, font, max_w)
        if len(lines) <= max_lines and len(lines) * px * 1.08 <= max_h:
            return px, lines
        px -= 4
    return min_px, _wrap(text, _font(min_px), max_w)


def _outlined_text(d, xy, text, px, fill, anchor="la", stroke=0.13, shadow=True):
    font = _font(px)
    sw = max(3, round(px * stroke))
    if shadow:
        off = round(px * 0.07)
        d.text((xy[0] + off, xy[1] + off), text, font=font, fill=THUMBNAIL_INK, anchor=anchor, stroke_width=sw, stroke_fill=THUMBNAIL_INK)
    d.text(xy, text, font=font, fill=fill, anchor=anchor, stroke_width=sw, stroke_fill=THUMBNAIL_INK)


def _burst(d, cx, cy, r, points, fill, width):
    pts = []
    for i in range(points * 2):
        rr = r if i % 2 == 0 else r * 0.78
        a = math.pi * i / points - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=fill, outline=THUMBNAIL_INK, width=width)


def _sticker_frame(c, box, image, radius, outline_px):
    x0, y0, x1, y1 = (int(v) for v in box)
    d = c.d
    off = round(outline_px * 1.6)
    d.rounded_rectangle((x0 + off, y0 + off, x1 + off, y1 + off), radius=radius, fill=THUMBNAIL_INK)
    d.rounded_rectangle((x0 - outline_px, y0 - outline_px, x1 + outline_px, y1 + outline_px), radius=radius + outline_px,
                        fill=(255, 255, 255))
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.size[0] - 1, image.size[1] - 1), radius=radius, fill=255)
    c.img.paste(image, (x0, y0), mask)
    d.rounded_rectangle((x0 - outline_px, y0 - outline_px, x1 + outline_px, y1 + outline_px), radius=radius + outline_px,
                        outline=THUMBNAIL_INK, width=max(3, outline_px // 2))


def _ribbon(d, cx, cy, text, px, fill, max_width=None):
    font = _font(px)
    if max_width:
        while px > 20 and font.getlength(text) + px * 2.3 > max_width:
            px -= 3
            font = _font(px)
    tw = font.getlength(text)
    hh = px * 0.72
    pad = px * 0.8
    pts = [(cx - tw / 2 - pad, cy - hh), (cx + tw / 2 + pad, cy - hh + px * 0.08), (cx + tw / 2 + pad + px * 0.35, cy),
           (cx + tw / 2 + pad, cy + hh), (cx - tw / 2 - pad, cy + hh - px * 0.08), (cx - tw / 2 - pad - px * 0.35, cy)]
    d.polygon([(x + px * 0.07, y + px * 0.07) for x, y in pts], fill=THUMBNAIL_INK)
    d.polygon(pts, fill=fill, outline=THUMBNAIL_INK, width=max(3, round(px * 0.09)))
    d.text((cx, cy), text, font=font, fill=(255, 255, 255), anchor="mm", stroke_width=max(2, round(px * 0.07)),
           stroke_fill=THUMBNAIL_INK)


def make_thumbnail(record, fmt, out_path, quality=90):
    """Save a thumbnail as a JPEG and return its path."""
    spec = record.get("thumbnail") or {}
    w, h = SIZES[fmt]
    scheme_no = spec.get("scheme", 3)
    scheme = apply_to_palette(PALETTE, scheme_no)
    c = Canvas(w * SS, h * SS, scheme, seed=scheme_no)
    c.paint_background(0.0)
    d = c.d
    W, H = w * SS, h * SS
    headline, subline, badge = _headline_text(record), spec.get("subline", ""), spec.get("badge", "?")
    landscape = fmt == "long"
    if landscape:
        box = (0.515 * W, 0.07 * H, 0.97 * W, 0.93 * H)
        text_box = (0.045 * W, 0.08 * H, 0.475 * W, 0.66 * H)
    else:
        box = (0.07 * W, 0.37 * H, 0.93 * W, 0.80 * H)
        text_box = (0.07 * W, 0.045 * H, 0.93 * W, 0.33 * H)
    bw, bh = int(box[2] - box[0]), int(box[3] - box[1])
    art = render_illustration(record, spec.get("moment", 0.55), bw, bh, secs=1.4, ss=1)
    if art is not None:
        _sticker_frame(c, box, art, radius=int(0.05 * min(W, H)), outline_px=int(0.012 * min(W, H)))
    px, lines = _fit(headline, text_box[2] - text_box[0], text_box[3] - text_box[1],
                     int(0.20 * H) if landscape else int(0.115 * H), 40)
    y = text_box[1]
    for i, line in enumerate(lines):
        x = text_box[0] if landscape else (text_box[0] + text_box[2]) / 2
        _outlined_text(d, (x, y), line, px, LINE_COLOURS[i % 3], "la" if landscape else "ma")
        y += px * 1.08
    if subline:
        sub_px = int(0.062 * H) if landscape else int(0.036 * H)
        cx = (text_box[0] + text_box[2]) / 2 if landscape else W / 2
        cy = min(y + sub_px * 1.1, 0.88 * H) if landscape else 0.865 * H
        _ribbon(d, cx, cy, subline.upper(), sub_px, (255, 92, 170),
                (text_box[2] - text_box[0]) if landscape else 0.86 * W)
    if badge:
        bx, by = (box[2] - 0.05 * W, box[1] + 0.02 * H) if landscape else (box[2] - 0.02 * W, box[1] - 0.01 * H)
        br = 0.085 * min(W, H) if landscape else 0.10 * W
        _burst(d, bx, by, br, 12, (255, 226, 60), max(4, round(br * 0.07)))
        d.text((bx, by + br * 0.03), badge, font=_font(br * 1.25), fill=THUMBNAIL_INK, anchor="mm")
    tag = "SCIENCE ANIMATION STUDIO"
    _outlined_text(d, (0.045 * W if landscape else W / 2, 0.955 * H if landscape else 0.945 * H), tag,
                   0.03 * H if landscape else 0.0185 * H, (255, 255, 255), "lm" if landscape else "mm", 0.10, False)
    image = c.img.resize((w, h), Image.LANCZOS).convert("RGB")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "JPEG", quality=quality)
    return str(out_path)
