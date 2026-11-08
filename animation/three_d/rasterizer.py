"""A small software renderer: perspective, depth sorting, flat lighting and transparency."""
from PIL import Image, ImageDraw

from animation.three_d.math3d import clip_near, dot, norm, sub
from animation.three_d.mesh import centroid, normal

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
