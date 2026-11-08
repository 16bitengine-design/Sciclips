"""Small 3D maths helpers (plain Python, no extra packages)."""
import math


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
