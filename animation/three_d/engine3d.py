"""three_d: merged module (was 4 files: math3d, mesh, rasterizer, scenes3d).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""
import math
import random
from PIL import Image, ImageDraw
from dataclasses import dataclass
from animation.simulations import free_fall as ff
from animation.simulations import gas_release as gas


# ============================================================================
# from animation/three_d/math3d.py
# ============================================================================
# Small 3D maths helpers (plain Python, no extra packages).



def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a):
    return math.sqrt(dot(a, a))


def norm(a):
    n = length(a)
    return (0.0, 0.0, 0.0) if n == 0 else (a[0] / n, a[1] / n, a[2] / n)


def rot_y(p, angle, origin=(0.0, 0.0, 0.0)):
    x, y, z = sub(p, origin)
    c, s = math.cos(angle), math.sin(angle)
    return add((x * c + z * s, y, -x * s + z * c), origin)


class Camera:
    """A pinhole camera looking from `position` at `target`."""

    def __init__(self, position, target, fov_deg=40.0, up=(0.0, 1.0, 0.0)):
        self.position = position
        self.forward = norm(sub(target, position))
        self.right = norm(cross(self.forward, up))
        self.up = cross(self.right, self.forward)
        self.fov = math.radians(fov_deg)

    def to_view(self, p):
        """World point -> (x, y, depth) in camera space. Depth is positive in front of the camera."""
        d = sub(p, self.position)
        return (dot(d, self.right), dot(d, self.up), dot(d, self.forward))

    def project(self, view, width, height):
        focal = (height / 2.0) / math.tan(self.fov / 2.0)
        x, y, z = view
        return (width / 2.0 + x / z * focal, height / 2.0 - y / z * focal)


def orbit_camera(target, distance, azimuth_deg, elevation_deg, fov_deg=40.0):
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    position = (target[0] + distance * math.cos(el) * math.sin(az),
                target[1] + distance * math.sin(el),
                target[2] - distance * math.cos(el) * math.cos(az))
    return Camera(position, target, fov_deg)


def clip_near(points, near=0.05):
    """Clip a polygon given in camera space so every point is at least `near` in front."""
    out = []
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        a_in, b_in = a[2] >= near, b[2] >= near
        if a_in:
            out.append(a)
        if a_in != b_in:
            k = (near - a[2]) / (b[2] - a[2])
            out.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, near))
    return out


# ============================================================================
# from animation/three_d/mesh.py
# ============================================================================
# Simple solid shapes made of flat faces. Faces are listed counter-clockwise seen from outside.






@dataclass
class Face:
    points: list
    color: tuple
    two_sided: bool = False
    alpha: int = 255
    shade: bool = True


def normal(face):
    p = face.points
    return norm(cross(sub(p[1], p[0]), sub(p[2], p[0])))


def centroid(points):
    n = len(points)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n, sum(p[2] for p in points) / n)


def move(faces, offset):
    return [Face([add(p, offset) for p in f.points], f.color, f.two_sided, f.alpha, f.shade) for f in faces]


def box(center, size, color, alpha=255):
    cx, cy, cz = center
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    v = {(i, j, k): (cx + i * hx, cy + j * hy, cz + k * hz) for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)}
    quads = [
        [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)],      # front (+z)
        [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)],  # back (-z)
        [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)],      # right (+x)
        [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)],  # left (-x)
        [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)],      # top (+y)
        [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)],  # bottom (-y)
    ]
    return [Face([v[q] for q in quad], color, alpha=alpha) for quad in quads]


def cylinder(base_center, radius, height, color, segments=12, caps=True, alpha=255, two_sided=False):
    """An upright cylinder (axis along y) standing on base_center."""
    bx, by, bz = base_center
    ring = [(bx + radius * math.cos(2 * math.pi * i / segments), bz + radius * math.sin(2 * math.pi * i / segments))
            for i in range(segments)]
    faces = []
    for i in range(segments):
        (x0, z0), (x1, z1) = ring[i], ring[(i + 1) % segments]
        faces.append(Face([(x1, by, z1), (x0, by, z0), (x0, by + height, z0), (x1, by + height, z1)], color,
                          two_sided=two_sided, alpha=alpha))
    if caps:
        faces.append(Face([(x, by + height, z) for x, z in reversed(ring)], color, two_sided=two_sided, alpha=alpha))
        faces.append(Face([(x, by, z) for x, z in ring], color, two_sided=two_sided, alpha=alpha))
    return faces


def ellipsoid(center, radii, color, lat=6, lon=10, alpha=255):
    cx, cy, cz = center
    rx, ry, rz = radii

    def pt(i, j):
        phi = math.pi * i / lat
        theta = 2 * math.pi * j / lon
        return (cx + rx * math.sin(phi) * math.cos(theta), cy + ry * math.cos(phi), cz + rz * math.sin(phi) * math.sin(theta))

    faces = []
    for i in range(lat):
        for j in range(lon):
            a, b, c, d = pt(i, j), pt(i, j + 1), pt(i + 1, j + 1), pt(i + 1, j)
            if i == 0:
                faces.append(Face([a, c, d], color, alpha=alpha))
            elif i == lat - 1:
                faces.append(Face([a, b, c], color, alpha=alpha))
            else:
                faces.append(Face([a, b, c, d], color, alpha=alpha))
    return faces


def sphere(center, radius, color, lat=6, lon=10, alpha=255):
    return ellipsoid(center, (radius, radius, radius), color, lat, lon, alpha)


def disc(center, radius, color, segments=28, shade=True, alpha=255):
    """A flat circle facing up, visible from both sides."""
    cx, cy, cz = center
    pts = [(cx + radius * math.cos(2 * math.pi * i / segments), cy, cz + radius * math.sin(2 * math.pi * i / segments))
           for i in range(segments)]
    return [Face(list(reversed(pts)), color, two_sided=True, shade=shade, alpha=alpha)]


def ellipse_disc(center, rx, rz, color, segments=20, shade=False, alpha=255):
    cx, cy, cz = center
    pts = [(cx + rx * math.cos(2 * math.pi * i / segments), cy, cz + rz * math.sin(2 * math.pi * i / segments))
           for i in range(segments)]
    return [Face(list(reversed(pts)), color, two_sided=True, shade=shade, alpha=alpha)]


def outward(faces, mesh_center):
    """True if every face points away from mesh_center (used to check closed convex shapes)."""
    return all(dot(normal(f), sub(centroid(f.points), mesh_center)) > -1e-9 for f in faces)


# ============================================================================
# from animation/three_d/rasterizer.py
# ============================================================================
# A small software renderer: perspective, depth sorting, flat lighting and transparency.





NEAR = 0.05


def shade_color(color, n, light, ambient):
    k = ambient + (1.0 - ambient) * max(0.0, dot(n, light))
    return tuple(min(255, int(c * k)) for c in color)


def visible_faces(faces, camera, light, ambient):
    """Faces that face the camera, as (depth, view_points, rgba) tuples."""
    out = []
    for face in faces:
        n = normal(face)
        facing = dot(n, sub(camera.position, centroid(face.points)))
        if facing <= 0:
            if not face.two_sided:
                continue
            n = (-n[0], -n[1], -n[2])
        view = [camera.to_view(p) for p in face.points]
        depth = sum(v[2] for v in view) / len(view)
        rgb = shade_color(face.color, n, light, ambient) if face.shade else face.color
        out.append((depth, view, rgb + (face.alpha,)))
    return out


def render(groups, camera, size, background, light=(0.4, 0.8, 0.45), ambient=0.35, ss=2, lines=None):
    """Draw groups of faces. Each group is {"faces": [...], "sort": bool}; groups are drawn in order.

    `background` is a function (width, height) -> PIL RGB image. `lines` is a list of
    (point_a, point_b, colour, width) drawn on top. Returns a PIL RGB image of `size`.
    """
    width, height = size
    w, h = width * ss, height * ss
    img = background(w, h).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    light = norm(light)
    for group in groups:
        items = visible_faces(group["faces"], camera, light, ambient)
        if group.get("sort", True):
            items.sort(key=lambda item: -item[0])
        for _, view, rgba in items:
            clipped = clip_near(view, NEAR)
            if len(clipped) < 3:
                continue
            draw.polygon([camera.project(v, w, h) for v in clipped], fill=rgba)
    for a, b, color, line_width in lines or []:
        va, vb = camera.to_view(a), camera.to_view(b)
        if va[2] < NEAR and vb[2] < NEAR:
            continue
        pair = clip_near([va, vb, vb], NEAR)[:2]
        if len(pair) == 2:
            draw.line([camera.project(pair[0], w, h), camera.project(pair[1], w, h)], fill=color,
                      width=max(1, round(line_width * ss)))
    return img.resize((width, height), Image.LANCZOS) if ss > 1 else img


# ============================================================================
# from animation/three_d/scenes3d.py
# ============================================================================
# Lightweight 3D scenes for opening shots. Each builder returns a PIL image for one moment (t = 0 to 1).











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
    """A dark blue vertical gradient. Built as one column and stretched, which is fast."""
    column = Image.new("RGB", (1, h))
    for y in range(h):
        k = y / max(1, h - 1)
        column.putpixel((0, y), (int(14 + 18 * (1 - k)), int(22 + 24 * (1 - k)), int(40 + 36 * (1 - k))))
    return column.resize((w, h))


# ------------------------------------------------------------------ objects
def hammer_faces(x, bottom):
    """A hammer drawn larger than life so it reads clearly on a phone screen."""
    handle = cylinder((x, bottom, 0.0), 0.024, 0.46, WOOD, segments=10)
    head = box((x, bottom + 0.52, 0.0), (0.30, 0.115, 0.115), STEEL)
    return handle + head


def feather_faces(x, bottom):
    quill = cylinder((x, bottom, 0.0), 0.006, 0.32, (250, 250, 245), segments=6)
    vane = ellipsoid((x, bottom + 0.18, 0.0), (0.04, 0.17, 0.009), FEATHER, lat=5, lon=8)
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
    ground = disc((0, 0, 0), 90, (118, 118, 124), segments=36)
    craters = []
    for _ in range(14):
        cx, cz = rng.uniform(-7, 7), rng.uniform(-3, 9)
        r = rng.uniform(0.35, 1.4)
        craters += disc((cx, 0.003, cz), r, (92, 92, 99), segments=16)
        craters += disc((cx - r * 0.12, 0.004, cz - r * 0.12), r * 0.78, (104, 104, 111), segments=16)
    stones = []
    for _ in range(10):
        stones += ellipsoid((rng.uniform(-4, 4), 0.05, rng.uniform(-1, 6)), (0.12, 0.07, 0.1), (96, 96, 102),
                                 lat=3, lon=6)
    h_hammer, h_feather = object_heights(t)
    x_h, x_f = -0.55, 0.55
    objects = move(hammer_faces(0, 0), (x_h, h_hammer, 0)) + move(feather_faces(0, 0), (x_f, h_feather, 0))
    shadows = []
    sx, sy, sz = SUN
    for x, bottom, mid, rx in ((x_h, h_hammer, 0.28, 0.2), (x_f, h_feather, 0.17, 0.07)):
        h = bottom + mid
        shadows += ellipse_disc((x - sx / sy * h, 0.006, -sz / sy * h), rx, rx * 0.8, (62, 62, 68), shade=False)
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
    table = disc((0, 0, 0), 3.2, (44, 58, 92), segments=32)
    liquid = (cylinder((0, 0.02, 0), RIM - 0.03, LIQUID_TOP, (56, 118, 205), segments=24, caps=True, alpha=150,
                            two_sided=True))
    p = gas.reaction_progress(t)
    bubbles = gas.make_bubbles()
    active = round(len(bubbles) * _clamp(0.35 + 1.0 * (1 - p)))
    bubble_faces = []
    for i, b in enumerate(bubbles[:active]):
        pos, h = bubble_position(b, t * 1.0, i, len(bubbles))
        fade = 1.0 - _clamp((h - 0.72) / 0.28)
        if fade > 0.05:
            ball = sphere(pos, 0.03 + b["radius"] * 2.2, (225, 240, 255), lat=4, lon=8, alpha=int(150 * fade))
            for face in ball:
                face.shade = False
            bubble_faces += ball
    glass = cylinder((0, 0.02, 0), RIM, GLASS_HEIGHT, (180, 220, 255), segments=28, caps=False, alpha=46,
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
