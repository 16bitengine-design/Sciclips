import math
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from animation.simulations import free_fall as ff  # noqa: E402
from animation.three_d import mesh, scenes3d  # noqa: E402
from animation.three_d.math3d import Camera, clip_near, length, orbit_camera, sub  # noqa: E402
from animation.three_d.rasterizer import render, visible_faces  # noqa: E402
from animation.two_d import renderer  # noqa: E402
from content.script_generator import generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
import json  # noqa: E402

OK = {"status": "passed_automated_checks"}


def solid(colour):
    return lambda w, h: Image.new("RGB", (w, h), colour)


def front_camera(distance=6.0):
    return Camera((0.0, 0.0, -distance), (0.0, 0.0, 0.0), 40)


# --- maths -----------------------------------------------------------------------
def test_camera_axes_are_perpendicular_unit_vectors():
    cam = Camera((3.0, 2.0, -5.0), (0.0, 1.0, 0.0), 40)
    for v in (cam.forward, cam.right, cam.up):
        assert abs(length(v) - 1) < 1e-9
    assert abs(sum(a * b for a, b in zip(cam.forward, cam.right))) < 1e-9
    assert abs(sum(a * b for a, b in zip(cam.forward, cam.up))) < 1e-9


def test_target_projects_to_screen_centre():
    cam = Camera((1.0, 2.0, -6.0), (0.0, 1.0, 0.0), 40)
    sx, sy = cam.project(cam.to_view((0.0, 1.0, 0.0)), 400, 600)
    assert abs(sx - 200) < 1e-6 and abs(sy - 300) < 1e-6


def test_points_behind_camera_have_negative_depth():
    cam = front_camera()
    assert cam.to_view((0, 0, -10))[2] < 0
    assert cam.to_view((0, 0, 3))[2] > 0


def test_clip_near_removes_points_behind_camera():
    clipped = clip_near([(0, 0, 2.0), (1, 0, -2.0), (-1, 0, -2.0)], 0.05)
    assert len(clipped) >= 3 and all(p[2] >= 0.05 - 1e-9 for p in clipped)
    assert clip_near([(0, 0, -1), (1, 0, -1), (0, 1, -1)], 0.05) == []


def test_orbit_camera_keeps_its_distance():
    cam = orbit_camera((0, 1, 0), 5.0, 30, 10)
    assert abs(length(sub(cam.position, (0, 1, 0))) - 5.0) < 1e-9


# --- shapes ------------------------------------------------------------------------
def test_closed_shapes_face_outward():
    assert mesh.outward(mesh.box((0, 0, 0), (1, 2, 3), (1, 1, 1)), (0, 0, 0))
    assert mesh.outward(mesh.sphere((0, 0, 0), 1, (1, 1, 1)), (0, 0, 0))
    assert mesh.outward(mesh.cylinder((0, -1, 0), 1, 2, (1, 1, 1)), (0, 0, 0))


def test_shape_face_counts():
    assert len(mesh.box((0, 0, 0), (1, 1, 1), (1, 1, 1))) == 6
    assert len(mesh.cylinder((0, 0, 0), 1, 1, (1, 1, 1), segments=8)) == 10


def test_move_shifts_every_point():
    faces = mesh.move(mesh.box((0, 0, 0), (1, 1, 1), (9, 9, 9)), (0, 5, 0))
    assert all(p[1] >= 4.5 for f in faces for p in f.points)


# --- renderer ------------------------------------------------------------------------
def test_back_faces_are_skipped_for_solid_shapes():
    cam = front_camera()
    faces = mesh.box((0, 0, 0), (1, 1, 1), (200, 200, 200))
    seen = visible_faces(faces, cam, (0, 1, 0), 0.3)
    assert 1 <= len(seen) <= 3


def test_faces_toward_the_light_are_brighter():
    cam = Camera((0, 5, -0.001), (0, 0, 0), 40)
    top = mesh.box((0, 0, 0), (1, 1, 1), (200, 200, 200))
    lit = visible_faces(top, cam, (0, 1, 0), 0.2)
    dark = visible_faces(top, cam, (0, -1, 0), 0.2)
    assert max(c[2][0] for c in lit) > max(c[2][0] for c in dark)


def test_nearer_object_covers_farther_object_in_any_order():
    cam = front_camera()
    near = mesh.box((0, 0, -1.0), (1.2, 1.2, 0.5), (230, 40, 40))
    far = mesh.box((0, 0, 1.0), (2.4, 2.4, 0.5), (40, 40, 230))
    results = []
    for order in ([far, near], [near, far]):
        faces = [f for shape in order for f in shape]
        img = render([{"faces": faces, "sort": True}], cam, (120, 120), solid((0, 0, 0)), ss=1)
        results.append(img.getpixel((60, 60)))
    assert results[0] == results[1]
    assert results[0][0] > results[0][2]


def test_ground_crossing_the_camera_plane_does_not_crash():
    ground = mesh.disc((0, 0, 0), 90, (120, 120, 120), segments=24)
    cam = Camera((0, 1.0, 0.0), (0, 0.9, 5), 40)
    img = render([{"faces": ground, "sort": False}], cam, (100, 100), solid((0, 0, 0)), ss=1)
    assert img.size == (100, 100)


def test_rendering_is_repeatable():
    cam = front_camera()
    faces = mesh.sphere((0, 0, 0), 1, (180, 180, 40))
    a = render([{"faces": faces}], cam, (80, 80), solid((0, 0, 0)), ss=2).tobytes()
    b = render([{"faces": faces}], cam, (80, 80), solid((0, 0, 0)), ss=2).tobytes()
    assert a == b


def test_transparent_faces_blend_with_what_is_behind():
    cam = front_camera()
    glass = mesh.box((0, 0, 0), (2, 2, 0.2), (255, 255, 255), alpha=100)
    img = render([{"faces": glass}], cam, (80, 80), solid((0, 0, 0)), ss=1)
    pixel = img.getpixel((40, 40))
    assert 0 < pixel[0] < 255


# --- the topic scenes ------------------------------------------------------------------
def record(topic):
    return load_topic_record(str(ROOT), topic)


def test_both_topics_have_a_3d_opening_scene():
    for topic, size in (("physics-001", (270, 300)), ("chem-001", (270, 300))):
        image = scenes3d.render_viewport(record(topic), 0.5, size[0], size[1], ss=1)
        assert image is not None and image.size == size


def test_topic_without_3d_scene_returns_none():
    rec = record("physics-001")
    rec["scene3d"] = None
    assert scenes3d.render_viewport(rec, 0.5, 100, 100) is None


def test_hammer_and_feather_fall_together_in_vacuum():
    for t in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        h, f = scenes3d.object_heights(t)
        assert abs(h - f) < 1e-9
    assert scenes3d.object_heights(0.0)[0] == ff.HEIGHT
    assert scenes3d.object_heights(1.0)[0] == 0.0


def test_3d_frames_change_over_time():
    rec = record("physics-001")
    a = scenes3d.render_viewport(rec, 0.1, 160, 200, ss=1).tobytes()
    b = scenes3d.render_viewport(rec, 0.7, 160, 200, ss=1).tobytes()
    assert a != b
    rec = record("chem-001")
    assert scenes3d.render_viewport(rec, 0.1, 160, 200, ss=1).tobytes() != scenes3d.render_viewport(
        rec, 0.7, 160, 200, ss=1).tobytes()


def test_bubbles_stay_inside_the_glass():
    for i, bubble in enumerate(scenes3d.gas.make_bubbles()):
        for t in (0.0, 0.3, 0.9):
            (x, y, z), _ = scenes3d.bubble_position(bubble, t, i, 28)
            assert math.hypot(x, z) < scenes3d.RIM - 0.05


def test_opening_scene_draws_in_both_formats():
    rendering = json.loads((ROOT / "config" / "rendering.json").read_text())
    for topic in ("physics-001", "chem-001"):
        rec = record(topic)
        for fmt, size in (("short", (270, 480)), ("long", (480, 270))):
            for variant in ("explainer", "what_if"):
                board = generate_storyboard(generate_script(rec, fmt, variant, rendering, OK), rec, rendering)
                hook = board["scenes"][0]
                assert hook["animation_type"] == "3d_scene"
                for t in (0.0, 0.5, 1.0):
                    assert renderer.draw_frame(hook, rec, size[0], size[1], t).size == size


def test_one_frame_renders_quickly():
    start = time.time()
    scenes3d.render_viewport(record("chem-001"), 0.5, 270, 300, ss=2)
    scenes3d.render_viewport(record("physics-001"), 0.5, 270, 300, ss=2)
    assert time.time() - start < 5


def test_long_opening_title_is_the_topic_title_not_an_outline_note():
    rendering = json.loads((ROOT / "config" / "rendering.json").read_text())
    for topic in ("physics-001", "chem-001"):
        rec = record(topic)
        script = generate_script(rec, "long", "explainer", rendering, OK)
        hook = [s for s in script["sections"] if s["kind"] == "hook"][0]
        assert hook["on_screen_text"] == rec["title"]
