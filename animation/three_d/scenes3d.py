"""Lightweight 3D scenes for opening shots. Each builder returns a PIL image for one moment (t = 0 to 1).

These are illustrations. Falling motion comes from the free-fall model used elsewhere in the project;
bubble motion comes from the gas-release model.
"""
import math
import random

from PIL import Image, ImageDraw

from animation.simulations import free_fall as ff
from animation.simulations import gas_release as gas
from animation.three_d import mesh
from animation.three_d.math3d import orbit_camera
from animation.three_d.rasterizer import render

STEEL, WOOD, FEATHER = (150, 156, 168), (176, 112, 52), (238, 236, 224)


def _clamp(x):
    return max(0.0, min(1.0, x))


def _smooth(x):
    x = _clamp(x)
    return x * x * (3 - 2 * x)


# ------------------------------------------------------------------ backgrounds
def _starry_sky(w, h):
    img = Image.new("RGB", (w, h), (4, 6, 12))
    draw = ImageDraw.Draw(img)
    rng = random.Random(11)
    for _ in range(70):
        x, y = rng.randrange(w), rng.randrange(int(h * 0.7))
        r = max(1, int(rng.uniform(0.6, 1.8) * w / 540))
        shade = rng.randrange(120, 255)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(shade, shade, shade))
    return img


def _lab_backdrop(w, h):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        k = y / max(1, h - 1)
        row = (int(14 + 18 * (1 - k)), int(22 + 24 * (1 - k)), int(40 + 36 * (1 - k)))
        for x in range(w):
            px[x, y] = row
    return img


# ------------------------------------------------------------------ objects
def hammer_faces(x, bottom):
    """A hammer drawn larger than life so it reads clearly on a phone screen."""
    handle = mesh.cylinder((x, bottom, 0.0), 0.024, 0.46, WOOD, segments=10)
    head = mesh.box((x, bottom + 0.52, 0.0), (0.30, 0.115, 0.115), STEEL)
    return handle + head


def feather_faces(x, bottom):
    quill = mesh.cylinder((x, bottom, 0.0), 0.006, 0.32, (250, 250, 245), segments=6)
    vane = mesh.ellipsoid((x, bottom + 0.18, 0.0), (0.04, 0.17, 0.009), FEATHER, lat=5, lon=8)
    return quill + vane


# ------------------------------------------------------------------ falling objects on the Moon
SUN = (0.55, 0.38, -0.35)


def object_heights(t):
    """(hammer_bottom, feather_bottom) in metres, from the vacuum free-fall model, slowed down."""
    hammer, feather = ff.simulate("hammer", False), ff.simulate("feather", False)
    t_end = max(hammer["t_land"], feather["t_land"]) + 0.3
    sim_t = _clamp((t - 0.30) / 0.55) * t_end
    return ff.state_at(hammer, sim_t)[0], ff.state_at(feather, sim_t)[0]


def drop_scene(record, t, width, height, ss=2):
    rng = random.Random(5)
    ground = mesh.disc((0, 0, 0), 90, (118, 118, 124), segments=36)
    craters = []
    for _ in range(14):
        cx, cz = rng.uniform(-7, 7), rng.uniform(-3, 9)
        r = rng.uniform(0.35, 1.4)
        craters += mesh.disc((cx, 0.003, cz), r, (92, 92, 99), segments=16)
        craters += mesh.disc((cx - r * 0.12, 0.004, cz - r * 0.12), r * 0.78, (104, 104, 111), segments=16)
    stones = []
    for _ in range(10):
        stones += mesh.ellipsoid((rng.uniform(-4, 4), 0.05, rng.uniform(-1, 6)), (0.12, 0.07, 0.1), (96, 96, 102),
                                 lat=3, lon=6)
    h_hammer, h_feather = object_heights(t)
    x_h, x_f = -0.55, 0.55
    objects = mesh.move(hammer_faces(0, 0), (x_h, h_hammer, 0)) + mesh.move(feather_faces(0, 0), (x_f, h_feather, 0))
    shadows = []
    sx, sy, sz = SUN
    for x, bottom, mid, rx in ((x_h, h_hammer, 0.28, 0.2), (x_f, h_feather, 0.17, 0.07)):
        h = bottom + mid
        shadows += mesh.ellipse_disc((x - sx / sy * h, 0.006, -sz / sy * h), rx, rx * 0.8, (62, 62, 68), shade=False)
    p = _smooth(t)
    camera = orbit_camera((0.0, 0.95, 0.0), 4.4 - 0.7 * p, 14 - 26 * p, 8, fov_deg=40)
    groups = [{"faces": ground, "sort": False}, {"faces": craters, "sort": False},
              {"faces": shadows, "sort": False}, {"faces": stones, "sort": True},
              {"faces": objects, "sort": True}]
    return render(groups, camera, (width, height), _starry_sky, light=SUN, ambient=0.30, ss=ss)


# ------------------------------------------------------------------ beaker with bubbles
RIM = 0.58
GLASS_HEIGHT = 1.35
LIQUID_TOP = 0.62


def bubble_position(bubble, t, index, total):
    h = gas.bubble_height(bubble, t)
    angle = (bubble["phase"] * 7.0 + index * 0.9) * math.pi * 2
    radius = 0.40 * ((index * 37) % 10) / 10 + 0.04
    return (radius * math.cos(angle), 0.08 + h * (GLASS_HEIGHT + 0.25), radius * math.sin(angle)), h


def beaker_scene(record, t, width, height, ss=2):
    table = mesh.disc((0, 0, 0), 3.2, (44, 58, 92), segments=32)
    liquid = (mesh.cylinder((0, 0.02, 0), RIM - 0.03, LIQUID_TOP, (56, 118, 205), segments=24, caps=True, alpha=150,
                            two_sided=True))
    p = gas.reaction_progress(t)
    bubbles = gas.make_bubbles()
    active = round(len(bubbles) * _clamp(0.35 + 1.0 * (1 - p)))
    bubble_faces = []
    for i, b in enumerate(bubbles[:active]):
        pos, h = bubble_position(b, t * 1.0, i, len(bubbles))
        fade = 1.0 - _clamp((h - 0.72) / 0.28)
        if fade > 0.05:
            ball = mesh.sphere(pos, 0.03 + b["radius"] * 2.2, (225, 240, 255), lat=4, lon=8, alpha=int(150 * fade))
            for face in ball:
                face.shade = False
            bubble_faces += ball
    glass = mesh.cylinder((0, 0.02, 0), RIM, GLASS_HEIGHT, (180, 220, 255), segments=28, caps=False, alpha=46,
                          two_sided=True)
    rim_lines = []
    for i in range(28):
        a0, a1 = 2 * math.pi * i / 28, 2 * math.pi * (i + 1) / 28
        rim_lines.append(((RIM * math.cos(a0), GLASS_HEIGHT + 0.02, RIM * math.sin(a0)),
                          (RIM * math.cos(a1), GLASS_HEIGHT + 0.02, RIM * math.sin(a1)), (225, 240, 255, 230), 2.5))
    p2 = _smooth(t)
    camera = orbit_camera((0.0, 0.7, 0.0), 3.9 - 0.4 * p2, -28 + 56 * p2, 14, fov_deg=36)
    groups = [{"faces": table, "sort": False}, {"faces": liquid, "sort": True},
              {"faces": bubble_faces, "sort": True}, {"faces": glass, "sort": True}]
    return render(groups, camera, (width, height), _lab_backdrop, light=(0.35, 0.8, 0.5), ambient=0.4, ss=ss,
                  lines=rim_lines)


BUILDERS = {"drop": drop_scene, "beaker": beaker_scene}


def render_viewport(record, t, width, height, ss=2):
    """A PIL image of the topic's opening 3D scene, or None if the topic has none."""
    builder = BUILDERS.get((record.get("scene3d") or {}).get("kind"))
    if builder is None:
        return None
    return builder(record, t, width, height, ss)
