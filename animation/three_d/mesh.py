"""Simple solid shapes made of flat faces. Faces are listed counter-clockwise seen from outside."""
import math
from dataclasses import dataclass

from animation.three_d.math3d import add, cross, dot, norm, sub


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
