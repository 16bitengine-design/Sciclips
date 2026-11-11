"""Asset Designer: invents the characters, props and settings for a video, instead of using a fixed set.

Every character is built from simple parts (a body shape, a face, an accessory, legs) and every prop from a few
recipes, so ANY name gives a new, consistent design. The same name always gets the same look, so a character stays
the same all through a video, and across videos when the library file is saved.

A topic record can describe its scene by hand:
    "scene3d": {"kind": "designed", "spec": {"background": "space", "actors": [{"name": "Hammer"}], "props": ["planet"]}}
or leave "spec" out and let design_scene() work it out from the title and central question.
"""
import hashlib
import json
import math
import random
import re
from pathlib import Path

from PIL import Image

from animation.two_d.backgrounds import _gradient

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
    actor.update({k: v for k, v in overrides.items() if k in actor or k in ("x", "label")})
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
    props = [invent_prop(p) for p in (given.get("props") or PROPS_FOR[background])]
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
    if kind == "planet":
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
    from animation.two_d.canvas import Canvas
    canvas = Canvas(width * ss, height * ss)
    designed_scene(canvas, (0, 0, width * ss, height * ss), t, secs, record, library)
    return canvas.img.resize((width, height), Image.LANCZOS) if ss > 1 else canvas.img
