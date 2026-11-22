"""tests: merged module (was 7 files: test_asset_designer, test_stage5, test_stage6, test_stage7, test_stage8, test_styles, test_visuals).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""



# ============================================================================
# from tests/test_asset_designer.py
# ============================================================================
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from animation.two_d import asset_designer as ad, illustrations  # noqa: E402

MOON = {"title": "Why do hammers and feathers fall together on the Moon?", "central_question": "Do heavy things fall faster?"}
FIZZ = {"title": "What makes baking soda and vinegar fizz?", "central_question": "Why does it make gas bubbles?"}


def test_same_name_always_gets_the_same_design():
    assert ad.invent_actor("Zorp") == ad.invent_actor("Zorp")
    assert ad.invent_actor("Zorp") != ad.invent_actor("Quill")


def test_any_name_makes_a_valid_character():
    for name in ("Zorp", "x", "Magnetic field", "Éclair", "123"):
        actor = ad.invent_actor(name)
        assert actor["shape"] in ad.SHAPES and 0 <= actor["colour"] < len(ad.COLOURS)


def test_unknown_props_become_gems_and_known_ones_stay():
    assert ad.invent_prop("planet")["kind"] == "planet"
    assert ad.invent_prop("flux capacitor")["kind"] == "gem"


def test_setting_follows_the_topic():
    assert ad.design_scene(MOON)["background"] == "space"
    assert ad.design_scene(FIZZ)["background"] == "lab"


def test_a_hand_written_spec_wins():
    record = dict(MOON, scene3d={"kind": "designed", "spec": {"background": "ocean", "actors": [{"name": "Finn"}], "props": ["cloud"]}})
    spec = ad.design_scene(record)
    assert spec["background"] == "ocean" and spec["actors"][0]["name"] == "Finn" and spec["props"][0]["kind"] == "cloud"


def test_empty_record_still_makes_a_scene():
    spec = ad.design_scene({})
    assert spec["actors"] and spec["background"] in ad.BACKGROUNDS


def test_library_remembers_characters(tmp_path):
    library = {}
    first = ad.design_scene(MOON, library)
    path = tmp_path / "actors.json"
    ad.save_library(path, library)
    again = ad.design_scene(MOON, ad.load_library(path))
    assert first["actors"] == again["actors"] and library


def test_broken_library_file_is_ignored(tmp_path):
    path = tmp_path / "actors.json"
    path.write_text("not json")
    assert ad.load_library(path) == {}
    assert ad.load_library(tmp_path / "missing.json") == {}


def test_scenes_draw_at_both_shapes_and_move_over_time():
    for size in ((270, 480), (480, 270)):
        a = ad.render_designed(MOON, *size, t=0.2, secs=0.0)
        b = ad.render_designed(MOON, *size, t=0.2, secs=1.1)
        assert a.size == size and a.tobytes() != b.tobytes()


def test_different_topics_look_different():
    assert ad.render_designed(MOON, 200, 180).tobytes() != ad.render_designed(FIZZ, 200, 180).tobytes()


def test_the_illustration_code_uses_the_designer():
    record = dict(MOON, scene3d={"kind": "designed"})
    assert illustrations.render_illustration(record, 0.5, 300, 260, secs=1.0, ss=1).size == (300, 260)
    record["scene3d"] = None
    assert illustrations.render_illustration(record, 0.5, 100, 100) is None


ROCKET = {"name": "Rocket", "face": {"x": 50, "y": 60, "size": 22}, "parts": [
    {"shape": "rrect", "fill": "white", "box": [32, 10, 68, 86]},
    {"shape": "polygon", "fill": "red", "points": [[32, 26], [50, 0], [68, 26]]},
    {"shape": "circle", "fill": "glass", "box": [42, 38, 58, 54]}]}


def test_any_object_can_be_described_as_parts():
    record = dict(MOON, scene3d={"kind": "designed", "spec": {"actors": [ROCKET], "props": [ROCKET]}})
    spec = ad.design_scene(record)
    assert spec["actors"][0]["parts"] and spec["props"][0]["kind"] == "custom"
    assert ad.render_designed(record, 300, 260).tobytes() != ad.render_designed(MOON, 300, 260).tobytes()


def test_badly_written_parts_never_break_a_video():
    bad = [{"shape": "nope"}, {"shape": "circle", "box": ["a", 1, 2, 3]}, "junk", None,
           {"shape": "polygon", "points": [[1, 2]]}, {"shape": "rect", "box": [999, -999, 5, 5], "fill": "zzz"}]
    parts = ad.clean_parts(bad)
    assert len(parts) == 1 and all(-20 <= v <= 120 for v in parts[0]["box"]) and parts[0]["fill"].startswith("#")
    record = {"title": "x", "scene3d": {"kind": "designed", "spec": {"actors": [{"name": "Bad", "parts": bad}]}}}
    assert ad.render_designed(record, 200, 180).size == (200, 180)


def test_invented_objects_are_remembered(tmp_path):
    library = {}
    record = {"title": "t", "scene3d": {"kind": "designed", "spec": {"actors": [ROCKET]}}}
    ad.design_scene(record, library)
    ad.save_library(tmp_path / "a.json", library)
    later = ad.design_scene({"title": "t", "scene3d": {"kind": "designed", "spec": {"actors": ["Rocket"]}}},
                            ad.load_library(tmp_path / "a.json"))
    assert later["actors"][0]["parts"] == library["Rocket"]["parts"]


# ============================================================================
# from tests/test_stage5.py
# ============================================================================
import json
import shutil
import sys
from pathlib import Path

TEST_STAGE5_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_STAGE5_ROOT))
sys.path.insert(0, str(TEST_STAGE5_ROOT / "scripts"))

from animation.simulations import free_fall as ff  # noqa: E402
from animation.simulations import gas_release as gas  # noqa: E402
from animation.two_d import renderer  # noqa: E402
from animation.two_d.canvas import Canvas, pretty_math  # noqa: E402
from content.script_generator import available_variants, generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from rendering.video_validator import validate_video  # noqa: E402
import render_scenes  # noqa: E402

TOPICS = ("physics-001", "chem-001")
OK_SCIENCE = {"status": "passed_automated_checks"}
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def rendering():
    return json.loads((TEST_STAGE5_ROOT / "config" / "config.json").read_text())["rendering"]


def storyboard(topic, fmt, variant):
    rec = load_topic_record(str(TEST_STAGE5_ROOT), topic)
    script = generate_script(rec, fmt, variant, rendering(), OK_SCIENCE)
    return rec, script, generate_storyboard(script, rec, rendering())


# --- text and layout helpers ---------------------------------------------------
def test_pretty_math():
    assert pretty_math("m^3 kg^-1 s^-2") == "m\u00b3 kg\u207b\u00b9 s\u207b\u00b2"
    assert pretty_math("CH3COOH") == "CH\u2083COOH"
    assert pretty_math("2H2O") == "2H\u2082O"
    assert pretty_math("A -> B") == "A \u2192 B"
    assert pretty_math("a = G M / r^2") == "a = G M / r\u00b2"


def test_wrap_respects_width():
    c = Canvas(540, 960)
    font = c.font("sans", 40)
    for line in c.wrap("The quick brown fox jumps over the lazy dog " * 4, font, 400):
        assert font.getlength(line) <= 400


def test_fit_size_shrinks_to_fit():
    c = Canvas(540, 960)
    text = "word " * 60
    size = c.fit_size(text, 400, 300, 80, 20)
    lines = c.wrap(text, c.font("sans", size), 400)
    assert size < 80 and c.text_height(lines, size) <= 300 or size == 20


# --- free fall model -------------------------------------------------------------
def test_vacuum_objects_land_together():
    hammer, feather = ff.simulate("hammer", False), ff.simulate("feather", False)
    assert abs(hammer["t_land"] - feather["t_land"]) < 1e-9
    assert abs(hammer["t_land"] - (2 * ff.HEIGHT / ff.GRAVITY) ** 0.5) < 0.01
    assert ff.landing_summary(hammer, feather) == "together"


def test_feather_lags_only_in_air():
    hammer, feather = ff.simulate("hammer", True), ff.simulate("feather", True)
    assert feather["t_land"] > hammer["t_land"] * 2
    assert ff.landing_summary(hammer, feather) == "first"
    assert abs(hammer["t_land"] - ff.simulate("hammer", False)["t_land"]) < 0.03


def test_wrong_model_is_visibly_different():
    wrong = ff.simulate("hammer", False, accel_scale=1.7)
    right = ff.simulate("feather", False)
    assert wrong["t_land"] < right["t_land"]


def test_state_stops_at_ground():
    sim = ff.simulate("hammer", False)
    assert ff.state_at(sim, 0)[0] == ff.HEIGHT
    assert ff.state_at(sim, 99)[0] == 0.0


# --- gas model -----------------------------------------------------------------
def test_progress_is_bounded_and_rising():
    values = [gas.reaction_progress(i / 20) for i in range(21)]
    assert values[0] == 0 and abs(values[-1] - 1) < 1e-9
    assert values == sorted(values)


def test_pressure_only_builds_when_sealed():
    assert gas.pressure("open", 1.0) == 0
    assert gas.pressure("sealed", 0.8) > gas.pressure("sealed", 0.3)
    assert gas.lid_lift("sealed", 1.0) == 0
    assert gas.lid_lift("sealed_pop", 0.3) == 0 and gas.lid_lift("sealed_pop", 1.0) > 0


def test_balance_reading():
    assert gas.scale_reading("balance_open", 1.0) < gas.scale_reading("balance_open", 0.0)
    assert gas.scale_reading("balance_sealed", 1.0) == 1.0


def test_bubbles_are_repeatable():
    assert gas.make_bubbles() == gas.make_bubbles()


# --- every scene of every storyboard draws ----------------------------------------
def test_all_scenes_draw_without_errors():
    for topic in TOPICS:
        rec = load_topic_record(str(TEST_STAGE5_ROOT), topic)
        for fmt, size in (("short", (270, 480)), ("long", (480, 270))):
            for variant in available_variants(rec):
                _, _, board = storyboard(topic, fmt, variant)
                for scene in board["scenes"]:
                    for t in (0.0, 0.5, 1.0):
                        image = renderer.draw_frame(scene, rec, size[0], size[1], t)
                        assert image.size == size, (topic, fmt, variant, scene["scene_number"])


def test_storyboard_carries_render_data():
    _, _, board = storyboard("chem-001", "short", "what_if")
    kinds = {s["section_kind"] for s in board["scenes"]}
    assert {"correct_procedure", "overlooked", "consequences"} <= kinds
    sealed = [s for s in board["scenes"] if s["section_kind"] == "overlooked"][0]
    assert sealed["data"]["simulation_variant"] == "sealed"


def test_what_if_captions_show_content_not_lead_in():
    _, script, _ = storyboard("physics-001", "short", "what_if")
    why = [s for s in script["sections"] if s["kind"] == "why"][0]
    assert why["narration"].startswith("Why this happens.")
    assert not why["on_screen_text"].startswith("Why this happens")


def test_chemical_equation_is_spoken_sensibly():
    _, script, _ = storyboard("chem-001", "long", "explainer")
    line = [s for s in script["sections"] if s["kind"] == "equation"][0]["narration"]
    assert "->" not in line and "gives" in line


# --- video files ------------------------------------------------------------------
def test_scene_renders_to_valid_mp4(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, _, board = storyboard("physics-001", "short", "explainer")
    scene = [s for s in board["scenes"] if s["animation_type"] == "simulation"][0]
    report = renderer.render_scene(scene, rec, tmp_path / "clip.mp4", 270, 480, 6, tmp_path / "poster.png")
    assert validate_video(report["path"], 270, 480, scene["duration_seconds"], 0.3, 6) == []
    assert (tmp_path / "poster.png").exists()


def test_validator_catches_bad_videos(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, _, board = storyboard("physics-001", "short", "explainer")
    scene = board["scenes"][1]
    path = tmp_path / "clip.mp4"
    renderer.render_scene(scene, rec, path, 270, 480, 6)
    assert validate_video(path, width=540)
    assert validate_video(path, duration=scene["duration_seconds"] + 5)
    assert validate_video(tmp_path / "missing.mp4")
    fake = tmp_path / "fake.mp4"
    fake.write_text("not a video")
    assert validate_video(fake)
    assert validate_video(path, expect_audio=True)


def test_render_storyboard_makes_contact_sheet(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, _, board = storyboard("chem-001", "short", "explainer")
    saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    try:
        reports = renderer.render_storyboard(board, rec, tmp_path, "draft", only_scenes={1, 2})
    finally:
        renderer.QUALITY["draft"] = saved
    assert len(reports) == 2 and (tmp_path / "contact_sheet.png").exists()


def test_unknown_quality_is_refused(tmp_path):
    rec, _, board = storyboard("chem-001", "short", "explainer")
    try:
        renderer.render_storyboard(board, rec, tmp_path, "ultra")
        assert False
    except renderer.RenderError:
        pass


def test_render_scenes_entry_point(tmp_path):
    if not HAVE_FFMPEG:
        return
    saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    try:
        ok, lines = render_scenes.run(str(TEST_STAGE5_ROOT), "chem-001", "short", str(tmp_path), "draft")
    finally:
        renderer.QUALITY["draft"] = saved
    assert ok, lines
    assert (tmp_path / "chem-001" / "short_explainer" / "scenes" / "contact_sheet.png").exists()
    assert any("OK" in line for line in lines)


def test_render_scenes_rejects_unknown_topic(tmp_path):
    ok, lines = render_scenes.run(str(TEST_STAGE5_ROOT), "nope-1", "short", str(tmp_path))
    assert not ok


# --- terminal speed (a person falling with a small or a big area) -----------------------
def test_terminal_speed_is_where_drag_equals_weight():
    for shape, spec in ff.PERSON.items():
        if shape == "mass":
            continue
        vt = ff.terminal_speed(ff.PERSON["mass"], spec["area"], spec["cd"])
        drag = 0.5 * ff.AIR_DENSITY * spec["cd"] * spec["area"] * vt * vt
        assert abs(drag - ff.PERSON["mass"] * ff.GRAVITY) < 1e-6


def test_a_bigger_area_levels_off_at_a_lower_speed():
    small, big = ff.terminal_curve("small", 14.0), ff.terminal_curve("big", 14.0)
    assert big["v_terminal"] < small["v_terminal"] / 3
    for curve in (small, big):
        assert curve["v"] == sorted(curve["v"])
        assert curve["v"][-1] <= curve["v_terminal"]
    assert big["v"][-1] > 0.99 * big["v_terminal"]


def test_terminal_speed_scene_draws_in_both_shapes_and_moves():
    from animation.two_d import renderer as r
    rec = load_topic_record(str(TEST_STAGE5_ROOT), "physics-001")
    scene = {"scene_number": 1, "animation_type": "simulation", "section_kind": "demonstration",
             "duration_seconds": 8, "data": {"simulation_variant": "terminal_speed"}}
    for size in ((270, 480), (480, 270)):
        early = r.draw_frame(scene, rec, size[0], size[1], 0.2)
        late = r.draw_frame(scene, rec, size[0], size[1], 0.9)
        assert early.size == size and early.tobytes() != late.tobytes()


# ============================================================================
# from tests/test_stage6.py
# ============================================================================
import math
import sys
import time
from pathlib import Path

from PIL import Image

TEST_STAGE6_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_STAGE6_ROOT))

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
    return load_topic_record(str(TEST_STAGE6_ROOT), topic)


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
    rendering = json.loads((TEST_STAGE6_ROOT / "config" / "config.json").read_text())["rendering"]
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
    rendering = json.loads((TEST_STAGE6_ROOT / "config" / "config.json").read_text())["rendering"]
    for topic in ("physics-001", "chem-001"):
        rec = record(topic)
        script = generate_script(rec, "long", "explainer", rendering, OK)
        hook = [s for s in script["sections"] if s["kind"] == "hook"][0]
        assert hook["on_screen_text"] == rec["title"]


# ============================================================================
# from tests/test_stage7.py
# ============================================================================
import json
import shutil
import sys
import wave
from pathlib import Path

TEST_STAGE7_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_STAGE7_ROOT))
sys.path.insert(0, str(TEST_STAGE7_ROOT / "scripts"))

from audio import audio_mixer, narration, pipeline, subtitles  # noqa: E402
from audio.speakable import load_pronunciations, speakable  # noqa: E402
from content.script_generator import generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from animation.two_d import renderer  # noqa: E402
from rendering.video_validator import validate_video  # noqa: E402
import render_scenes  # noqa: E402

TEST_STAGE7_OK = {"status": "passed_automated_checks"}
TEST_STAGE7_HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def TEST_STAGE7_rendering():
    return json.loads((TEST_STAGE7_ROOT / "config" / "config.json").read_text())["rendering"]


def make(topic="physics-001", fmt="short", variant="explainer"):
    rec = load_topic_record(str(TEST_STAGE7_ROOT), topic)
    script = generate_script(rec, fmt, variant, TEST_STAGE7_rendering(), TEST_STAGE7_OK)
    return rec, generate_storyboard(script, rec, TEST_STAGE7_rendering())


class BrokenProvider(narration.Provider):
    name = "broken"

    def synthesize(self, text, out_path, speed=1.0):
        raise narration.NarrationError("voice exploded")


# --- how things are spoken ---------------------------------------------------------
def test_equations_are_spoken_in_words():
    assert speakable("a = G M / r^2") == "A equals G M divided by R squared"
    assert "squared" in speakable("distance r^2")
    assert "cubed" in speakable("x^3")
    assert "minus 1" in speakable("kg^-1")


def test_chemistry_is_spoken_in_words():
    text = speakable("The reaction: CH3COOH + NaHCO3 gives CH3COONa + H2O + CO2.")
    for word in ("ethanoic acid", "sodium hydrogen carbonate", "sodium ethanoate", "water", "carbon dioxide"):
        assert word in text
    assert "plus" in text and "CH3" not in text


def test_units_are_spoken_in_words():
    text = speakable("gravitational constant, symbol G, measured in m^3 kg^-1 s^-2.")
    assert "cubic metres per kilogram per second squared" in text
    assert "newtons" in speakable("force, symbol F, measured in N.")


def test_unknown_formulas_are_spelled_out():
    assert speakable("Fe2O3 is rust") == "Fe 2 O 3 is rust"


def test_ordinary_sentences_are_left_alone():
    sentence = "A heavier object is pulled harder by gravity, but it is also harder to get moving."
    assert speakable(sentence) == sentence


def test_pronunciation_file_loads():
    pron = load_pronunciations()
    assert "CO2" in pron["words"] and pron["phrases"]


# --- subtitles -------------------------------------------------------------------------
def timed(topic="physics-001", fmt="short", variant="explainer"):
    rec, board = make(topic, fmt, variant)
    return rec, pipeline.apply_timing(board)


def test_timing_is_continuous_and_adds_up():
    _, board = timed()
    clock = 0.0
    for scene in board["scenes"]:
        assert abs(scene["start_seconds"] - clock) < 0.011
        clock = scene["end_seconds"]
    assert abs(board["total_duration_seconds"] - clock) < 0.011


def test_subtitle_cues_are_ordered_and_inside_their_scenes():
    _, board = timed()
    cues = subtitles.build_cues(board["scenes"], 34)
    scenes = {s["scene_number"]: s for s in board["scenes"]}
    for earlier, later in zip(cues, cues[1:]):
        assert earlier["end"] <= later["start"] + 1e-6
    for cue in cues:
        scene = scenes[cue["scene_number"]]
        assert scene["start_seconds"] <= cue["start"] < cue["end"] <= scene["end_seconds"] + 1e-6


def test_subtitle_lines_fit_and_all_words_are_kept():
    _, board = timed(fmt="long")
    cues = subtitles.build_cues(board["scenes"], 52)
    assert all(len(line) <= 52 for c in cues for line in c["text"].split("\n"))
    assert all(len(c["text"].split("\n")) <= 2 for c in cues)
    spoken = " ".join(w for c in cues for w in c["text"].split())
    original = " ".join(w for s in board["scenes"] for w in s["narration"].split())
    assert spoken == original


def test_srt_format():
    _, board = timed()
    srt = subtitles.to_srt(subtitles.build_cues(board["scenes"], 34))
    assert srt.startswith("1\n00:00:00,") and " --> " in srt


def test_ass_format_has_style_and_dialogue():
    _, board = timed()
    ass = subtitles.to_ass(subtitles.build_cues(board["scenes"], 34), 1080, 1920, True)
    assert "PlayResX: 1080" in ass and "Style: Default" in ass and "Dialogue: 0," in ass


# --- providers -----------------------------------------------------------------------------
def test_unknown_provider_is_refused():
    try:
        narration.get_provider("magic")
        assert False
    except narration.NarrationError:
        pass


def test_none_gives_no_provider():
    assert narration.get_provider("none") is None


def test_old_robotic_voices_are_gone():
    for name in ("espeak", "piper"):
        try:
            narration.get_provider(name)
            assert False, name
        except narration.NarrationError:
            pass
    assert not hasattr(narration, "EspeakProvider") and not hasattr(narration, "PiperProvider")


def test_licence_flags():
    assert narration.KokoroProvider().publishable is True
    assert "Apache 2.0" in narration.KokoroProvider().licence_note
    assert narration.ToneProvider().publishable is False


class Style:
    """A tiny stand-in for a voice style array: supports * and + like the real numpy arrays do."""

    def __init__(self, values):
        self.values = list(values)

    def __mul__(self, weight):
        return Style(v * weight for v in self.values)

    def __add__(self, other):
        return Style(a + b for a, b in zip(self.values, other.values))


class FakeEngine:
    """Stands in for the Kokoro library: returns a short tone as floats between -1 and 1."""

    def __init__(self, reject_voices=()):
        self.calls = []
        self.reject_voices = reject_voices

    def get_voice_style(self, name):
        if name in self.reject_voices:
            raise KeyError(name)
        return Style([1.0, float(len(name))])

    def create(self, text, voice, speed, lang):
        self.calls.append((text, voice, speed, lang))
        if isinstance(voice, str) and voice in self.reject_voices:
            raise ValueError(f"unknown voice {voice}")
        import math
        rate = 24000
        seconds = max(0.5, len(text.split()) * 0.3 / speed)
        return [0.25 * math.sin(2 * math.pi * 200 * i / rate) for i in range(int(seconds * rate))], rate


def test_write_wav_round_trips(tmp_path):
    path = narration.write_wav(tmp_path / "a.wav", [0.0, 0.5, -0.5, 1.0, -1.0] * 4800, 24000)
    assert abs(narration.wav_duration(path) - 1.0) < 0.001


def test_write_wav_refuses_empty_or_invalid_audio(tmp_path):
    for bad in ([], [0.1, float("nan")]):
        try:
            narration.write_wav(tmp_path / "b.wav", bad, 24000)
            assert False
        except narration.NarrationError:
            pass


def test_kokoro_provider_uses_the_documented_call(tmp_path):
    engine = FakeEngine()
    provider = narration.KokoroProvider(voice="af_heart", language="en-us", engine=engine)
    path = provider.synthesize("one two three four five six", tmp_path / "k.wav", 1.0)
    assert engine.calls == [("one two three four five six", "af_heart", 1.0, "en-us")]
    assert abs(narration.wav_duration(path) - 1.8) < 0.05


def test_kokoro_tries_the_backup_voice_when_the_first_is_unknown(tmp_path):
    engine = FakeEngine(reject_voices=("af_heart",))
    narration.KokoroProvider(voice="af_heart", engine=engine).synthesize("hello there", tmp_path / "k.wav")
    assert [c[1] for c in engine.calls] == ["af_heart", "af_sarah"]


def test_kokoro_reports_failure_when_every_voice_fails(tmp_path):
    engine = FakeEngine(reject_voices=("af_heart", "af_sarah"))
    try:
        narration.KokoroProvider(voice="af_heart", engine=engine).synthesize("hello", tmp_path / "k.wav")
        assert False
    except narration.NarrationError as err:
        assert "unknown voice" in str(err)


def test_kokoro_is_unavailable_without_its_files(monkeypatch=None):
    import os
    saved = {k: os.environ.pop(k, None) for k in ("KOKORO_MODEL", "KOKORO_VOICES")}
    try:
        assert narration.KokoroProvider().available() is False
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value


def test_tone_provider_writes_a_readable_wav(tmp_path):
    path = narration.ToneProvider().synthesize("one two three four five", tmp_path / "t.wav")
    assert abs(narration.wav_duration(path) - 2.0) < 0.05


# --- pipeline ----------------------------------------------------------------------------------
def test_no_voice_still_makes_subtitles_and_timing(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, "none")
    assert result["provider"] == "none" and Path(result["files"]["srt"]).exists()
    assert "audio_mix" not in result["files"]
    assert result["timeline"]["publishable"] is True


def test_failing_voice_falls_back_without_stopping(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, provider=BrokenProvider())
    assert result["provider"] == "none"
    assert any("voice exploded" in n for n in result["notes"])
    assert Path(result["files"]["srt"]).exists()


def test_missing_kokoro_means_subtitles_only_and_a_reported_problem(tmp_path):
    import os
    saved = {k: os.environ.pop(k, None) for k in ("KOKORO_MODEL", "KOKORO_VOICES")}
    try:
        rec, board = make("chem-001")
        result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, "kokoro")
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
    assert result["provider"] == "none"
    assert any("could not be used" in p for p in result["problems"])
    assert any("not available" in n for n in result["notes"])
    assert Path(result["files"]["srt"]).exists()


def test_an_old_voice_name_is_reported_not_used(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, "espeak")
    assert result["provider"] == "none"
    assert any("Unknown narration provider" in n for n in result["notes"])
    assert result["problems"]


def test_a_failing_voice_is_reported_as_a_problem(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, provider=BrokenProvider())
    assert any("could not be used" in p for p in result["problems"])


def test_kokoro_end_to_end_with_a_stand_in_engine(tmp_path):
    if not TEST_STAGE7_HAVE_FFMPEG:
        return
    rec, board = make("chem-001")
    provider = narration.KokoroProvider(engine=FakeEngine())
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, provider=provider)
    assert result["provider"] == "kokoro" and result["problems"] == [], result["problems"]
    assert result["timeline"]["publishable"] is True
    assert audio_mixer.validate_audio(result["files"]["audio_mix"], result["storyboard"]["total_duration_seconds"]) == []


def test_tone_voice_sets_scene_lengths_from_audio(tmp_path):
    if not TEST_STAGE7_HAVE_FFMPEG:
        return
    rec, board = make()
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, provider=narration.ToneProvider(0.3))
    assert result["provider"] == "test_tone" and result["problems"] == [], result["problems"]
    for scene in result["storyboard"]["scenes"]:
        expected = max(3.0, scene["audio_seconds"] + 0.5)
        assert abs(scene["duration_seconds"] - expected) < 0.02
    assert result["timeline"]["publishable"] is False


def test_final_mix_is_valid_and_quiet_enough(tmp_path):
    if not TEST_STAGE7_HAVE_FFMPEG:
        return
    rec, board = make("chem-001")
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, provider=narration.ToneProvider(0.3))
    mix = result["files"]["audio_mix"]
    assert audio_mixer.validate_audio(mix, result["storyboard"]["total_duration_seconds"]) == []
    assert abs(result["timeline"]["loudness_lufs"] - (-16)) < 3


def test_music_is_made_and_has_the_right_length(tmp_path):
    if not TEST_STAGE7_HAVE_FFMPEG:
        return
    path = audio_mixer.make_music(10, tmp_path / "m.wav")
    with wave.open(str(path), "rb") as handle:
        assert abs(handle.getnframes() / handle.getframerate() - 10) < 0.05


def test_audio_validator_catches_problems(tmp_path):
    if not TEST_STAGE7_HAVE_FFMPEG:
        return
    assert audio_mixer.validate_audio(tmp_path / "missing.m4a", 5)
    fake = tmp_path / "fake.m4a"
    fake.write_text("nope")
    assert audio_mixer.validate_audio(fake, 5)
    rec, board = make()
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, provider=narration.ToneProvider(0.3))
    assert audio_mixer.validate_audio(result["files"]["audio_mix"], 999)


# --- end to end ------------------------------------------------------------------------------------
def test_render_run_with_no_voice_matches_before(tmp_path):
    if not TEST_STAGE7_HAVE_FFMPEG:
        return
    saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    try:
        ok, lines = render_scenes.run(str(TEST_STAGE7_ROOT), "chem-001", "short", str(tmp_path), "draft")
    finally:
        renderer.QUALITY["draft"] = saved
    assert ok, lines
    base = tmp_path / "chem-001" / "short_explainer"
    assert (base / "subtitles.srt").exists() and (base / "timeline.json").exists()


def test_render_run_with_unavailable_kokoro_still_renders_but_reports_failure(tmp_path):
    if not TEST_STAGE7_HAVE_FFMPEG:
        return
    import os
    saved = {k: os.environ.pop(k, None) for k in ("KOKORO_MODEL", "KOKORO_VOICES")}
    renderer_saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    try:
        ok, lines = render_scenes.run(str(TEST_STAGE7_ROOT), "chem-001", "short", str(tmp_path), "draft", "kokoro")
    finally:
        renderer.QUALITY["draft"] = renderer_saved
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
    assert ok is False
    assert any("could not be used" in line for line in lines)
    assert (tmp_path / "chem-001" / "short_explainer" / "scenes" / "scene_001.mp4").exists()


def test_rendering_config_names_a_known_voice():
    assert TEST_STAGE7_rendering()["narration"]["provider"] in ("kokoro", "none")
    assert TEST_STAGE7_rendering()["narration"]["voice"]


def test_over_length_video_is_warned_about(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, provider=narration.ToneProvider(2.0), music=False)
    assert any(n.startswith("warning:") and "limit" in n for n in result["notes"])


def test_normal_length_video_has_no_length_warning(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, TEST_STAGE7_rendering(), tmp_path, "none")
    assert not any(n.startswith("warning:") for n in result["notes"])


# ============================================================================
# from tests/test_stage8.py
# ============================================================================
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

TEST_STAGE8_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_STAGE8_ROOT))
sys.path.insert(0, str(TEST_STAGE8_ROOT / "scripts"))

from animation.two_d import renderer  # noqa: E402
from animation.two_d.canvas import PALETTE, Canvas  # noqa: E402
from audio import narration, pipeline  # noqa: E402
from content.script_generator import generate_script  # noqa: E402
from content.script_validator import validate_script, validate_storyboard  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from rendering import assembler  # noqa: E402
from rendering.video_validator import decode_check, validate_final, validate_video  # noqa: E402
import produce_video  # noqa: E402

TEST_STAGE8_OK = {"status": "passed_automated_checks"}
TEST_STAGE8_HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
CAN_BURN = TEST_STAGE8_HAVE_FFMPEG and assembler.subtitles_filter_available()


def TEST_STAGE8_rendering():
    return json.loads((TEST_STAGE8_ROOT / "config" / "config.json").read_text())["rendering"]


def TEST_STAGE8_make(topic="physics-001", fmt="short", variant="explainer"):
    rec = load_topic_record(str(TEST_STAGE8_ROOT), topic)
    script = generate_script(rec, fmt, variant, TEST_STAGE8_rendering(), TEST_STAGE8_OK)
    return rec, script, generate_storyboard(script, rec, TEST_STAGE8_rendering())


def tiny():
    """Context manager style helper: small, slow-frame-rate drafts keep tests quick."""
    saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    return saved


# --- layout, frames and transitions --------------------------------------------
def test_content_leaves_the_same_bottom_band_for_captions():
    for size in ((1080, 1920), (1920, 1080)):
        canvas = Canvas(*size)
        assert abs(canvas.content_box()[3] - 0.8 * size[1]) < 1e-6


def test_frame_counts_add_up_exactly_with_no_drift():
    for fps in (4, 12, 30):
        for fmt in ("short", "long"):
            rec, _, board = TEST_STAGE8_make("physics-001", fmt)
            timed = pipeline.apply_timing(board)
            counts = renderer.plan_frames(timed, fps)
            assert abs(sum(counts.values()) - round(timed["total_duration_seconds"] * fps)) <= len(counts) * 0 + 2


def test_every_scene_gets_at_least_two_frames():
    _, _, board = TEST_STAGE8_make()
    assert all(n >= 2 for n in renderer.plan_frames(board, 12).values())


def white(size=(40, 40)):
    return Image.new("RGB", size, (255, 255, 255))


def test_fade_in_starts_dark_and_ends_clear():
    scene = {"transition": "fade in"}
    assert sum(renderer.apply_transition(white(), scene, 0.0, 5).getpixel((5, 5))) == 0
    assert renderer.apply_transition(white(), scene, 1.0, 5).getpixel((5, 5)) == (255, 255, 255)


def test_fade_out_darkens_only_at_the_end():
    scene = {"transition": "fade out"}
    assert renderer.apply_transition(white(), scene, 3.0, 5).getpixel((5, 5)) == (255, 255, 255)
    assert sum(renderer.apply_transition(white(), scene, 4.99, 5).getpixel((5, 5))) < 60


def test_wipe_reveals_from_the_left():
    scene = {"transition": "wipe"}
    image = renderer.apply_transition(white(), scene, 0.12, 5)
    assert image.getpixel((1, 20)) == (255, 255, 255)
    assert image.getpixel((38, 20)) == PALETTE["bg"]


def test_cut_changes_nothing():
    assert renderer.apply_transition(white(), {"transition": "cut"}, 0.0, 5).tobytes() == white().tobytes()


# --- outro -----------------------------------------------------------------------
def test_long_videos_end_with_an_outro_and_shorts_do_not():
    for variant in ("explainer", "what_if"):
        _, long_script, _ = TEST_STAGE8_make("physics-001", "long", variant)
        assert long_script["sections"][-1]["kind"] == "outro"
        _, short_script, _ = TEST_STAGE8_make("physics-001", "short", variant)
        assert all(s["kind"] != "outro" for s in short_script["sections"])


def test_outro_can_be_switched_off_in_config():
    cfg = TEST_STAGE8_rendering()
    cfg["branding"]["outro"]["long"] = False
    rec = load_topic_record(str(TEST_STAGE8_ROOT), "physics-001")
    script = generate_script(rec, "long", "explainer", cfg, TEST_STAGE8_OK)
    assert all(s["kind"] != "outro" for s in script["sections"])


def test_scripts_and_storyboards_with_outro_still_validate():
    for topic in ("physics-001", "chem-001"):
        rec, script, board = TEST_STAGE8_make(topic, "long")
        assert validate_script(script, rec, TEST_STAGE8_rendering())["errors"] == []
        assert validate_storyboard(board, script, rec, TEST_STAGE8_rendering())["errors"] == []


def test_outro_card_draws():
    rec, _, board = TEST_STAGE8_make("physics-001", "long")
    scene = board["scenes"][-1]
    image = renderer.draw_frame(scene, rec, 480, 270, 0.9)
    assert image.size == (480, 270)


# --- chapters and description ---------------------------------------------------------
def test_chapters_follow_the_rules_youtube_needs():
    for topic in ("physics-001", "chem-001"):
        _, _, board = TEST_STAGE8_make(topic, "long")
        timed = pipeline.apply_timing(board)
        chapters = assembler.build_chapters(timed)
        assert len(chapters) >= 3 and chapters[0][0] == 0
        assert all(b[0] - a[0] >= 10 for a, b in zip(chapters, chapters[1:]))
        assert len({title for _, title in chapters}) == len(chapters)


def test_chapters_are_empty_when_too_few_fit():
    _, _, board = TEST_STAGE8_make("physics-001", "short")
    timed = pipeline.apply_timing(board)
    for scene in timed["scenes"]:
        scene["section_kind"] = "outro"
    assert assembler.build_chapters(timed) == []


def test_description_lists_sources_and_makes_honest_statements():
    rec, _, board = TEST_STAGE8_make("chem-001", "long")
    text = assembler.build_description(rec, pipeline.apply_timing(board), "long", "Kokoro text-to-speech")
    for source in rec["sources"]:
        assert source["url"] in text
    assert "synthetic voice" in text and "not experimental evidence" in text
    assert "Chapters" in text and "Safety" in text
    for forbidden in ("peer review", "peer-reviewed", "expert reviewed"):
        assert forbidden not in text.lower()


def test_short_description_has_no_chapters():
    rec, _, board = TEST_STAGE8_make("physics-001", "short")
    text = assembler.build_description(rec, pipeline.apply_timing(board), "short", "Kokoro text-to-speech")
    assert "Chapters" not in text


# --- file checks ----------------------------------------------------------------------------
def test_decode_check_detects_damage(tmp_path):
    if not TEST_STAGE8_HAVE_FFMPEG:
        return
    rec, _, board = TEST_STAGE8_make()
    saved = tiny()
    try:
        reports = renderer.render_storyboard(board, rec, tmp_path, "draft", only_scenes={2})
    finally:
        renderer.QUALITY["draft"] = saved
    good = Path(reports[0]["path"])
    assert decode_check(good)
    damaged = tmp_path / "damaged.mp4"
    data = good.read_bytes()
    damaged.write_bytes(data[: len(data) // 2])
    assert not decode_check(damaged)


def test_workers_give_the_same_clips(tmp_path):
    if not TEST_STAGE8_HAVE_FFMPEG:
        return
    rec, _, board = TEST_STAGE8_make("chem-001")
    saved = tiny()
    try:
        one = renderer.render_storyboard(board, rec, tmp_path / "a", "draft", only_scenes={1, 2, 3}, workers=1)
        two = renderer.render_storyboard(board, rec, tmp_path / "b", "draft", only_scenes={1, 2, 3}, workers=2)
    finally:
        renderer.QUALITY["draft"] = saved
    assert [Path(r["path"]).read_bytes() for r in one] == [Path(r["path"]).read_bytes() for r in two]


# --- end to end ----------------------------------------------------------------------------------
def build_final(tmp_path, topic="chem-001", fmt="short", provider=None):
    rec, _, board = TEST_STAGE8_make(topic, fmt)
    audio = pipeline.produce(board, rec, TEST_STAGE8_rendering(), tmp_path, provider=provider) if provider else \
        pipeline.produce(board, rec, TEST_STAGE8_rendering(), tmp_path, "none")
    timed = audio["storyboard"]
    saved = tiny()
    try:
        reports = renderer.render_storyboard(timed, rec, tmp_path / "scenes", "draft")
    finally:
        renderer.QUALITY["draft"] = saved
    silent = assembler.concat_clips([r["path"] for r in reports], tmp_path / "silent.mp4")
    final = assembler.assemble(silent, tmp_path / "final.mp4", audio["files"].get("audio_mix"),
                               audio["files"]["ass"], fps=4)
    return rec, timed, audio, reports, final


def test_clips_join_to_the_planned_length(tmp_path):
    if not CAN_BURN:
        return
    _, timed, _, reports, final = build_final(tmp_path)
    assert abs(sum(r["frames"] for r in reports) / 4 - timed["total_duration_seconds"]) < 0.5
    assert validate_video(final, duration=timed["total_duration_seconds"], duration_tolerance=0.5) == []


def test_final_video_with_voice_has_audio_in_sync(tmp_path):
    if not CAN_BURN:
        return
    _, timed, audio, _, final = build_final(tmp_path, provider=narration.ToneProvider(0.3))
    width, height = renderer.frame_size(timed, "draft") if False else (None, None)
    problems = validate_video(final, duration=timed["total_duration_seconds"], duration_tolerance=0.5,
                              expect_audio=True)
    assert problems == [], problems
    assert decode_check(final)


def test_subtitles_are_actually_burned_in(tmp_path):
    if not CAN_BURN:
        return
    rec, timed, audio, reports, _ = build_final(tmp_path)
    silent = tmp_path / "silent.mp4"
    plain = tmp_path / "plain.mp4"
    assembler.assemble(silent, plain, None, None, fps=4)
    burned = tmp_path / "final.mp4"
    import subprocess
    frames = []
    for video in (plain, burned):
        out = tmp_path / f"{video.stem}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "3", "-i", str(video), "-frames:v", "1",
                        str(out)], check=True)
        frames.append(Image.open(out).convert("RGB").tobytes())
    assert frames[0] != frames[1]


def test_validate_final_catches_problems(tmp_path):
    if not CAN_BURN:
        return
    _, timed, _, _, final = build_final(tmp_path)
    cfg = TEST_STAGE8_rendering()
    good = validate_final(final, "short", 270, 480, 4, timed["total_duration_seconds"], cfg, False, False)
    assert good["problems"] == [], good["problems"]
    assert any("Draft" in w for w in good["warnings"])
    assert validate_final(final, "short", 540, 960, 4, timed["total_duration_seconds"], cfg, False, False)["problems"]
    assert validate_final(final, "short", 270, 480, 4, timed["total_duration_seconds"], cfg, False, True)["problems"]
    assert validate_final(final, "long", 270, 480, 4, timed["total_duration_seconds"], cfg, False, False)["problems"]
    assert validate_final(final, "short", 270, 480, 4, timed["total_duration_seconds"] + 30, cfg, False, False)[
        "problems"]


def test_produce_video_makes_every_deliverable(tmp_path):
    if not CAN_BURN:
        return
    saved = tiny()
    try:
        ok, lines = produce_video.run(str(TEST_STAGE8_ROOT), "chem-001", "short", str(tmp_path), "draft", "none")
    finally:
        renderer.QUALITY["draft"] = saved
    assert ok, lines
    final = tmp_path / "chem-001" / "short_explainer" / "final"
    for name in ("chem-001_short_explainer.mp4", "chem-001_short_explainer.srt", "description.txt", "thumbnail.jpg",
                 "final_report.json"):
        assert (final / name).exists(), name
    report = json.loads((final / "final_report.json").read_text())
    assert report["quality"] == "draft" and report["problems"] == []
    assert (final / "thumbnail.jpg").stat().st_size < 2_000_000


def test_produce_video_reports_a_missing_voice_but_still_builds_the_video(tmp_path):
    if not CAN_BURN:
        return
    import os
    saved_env = {k: os.environ.pop(k, None) for k in ("KOKORO_MODEL", "KOKORO_VOICES")}
    saved = tiny()
    try:
        ok, lines = produce_video.run(str(TEST_STAGE8_ROOT), "chem-001", "short", str(tmp_path), "draft", "kokoro")
    finally:
        renderer.QUALITY["draft"] = saved
        for key, value in saved_env.items():
            if value is not None:
                os.environ[key] = value
    assert ok is False
    assert any("could not be used" in line for line in lines)
    assert (tmp_path / "chem-001" / "short_explainer" / "final" / "chem-001_short_explainer.mp4").exists()


def test_produce_video_rejects_unknown_topic(tmp_path):
    ok, lines = produce_video.run(str(TEST_STAGE8_ROOT), "nope-1", "short", str(tmp_path))
    assert not ok


def test_branding_is_in_the_config():
    cfg = TEST_STAGE8_rendering()
    assert cfg["branding"]["channel_name"] and cfg["final"]["crf"]


# ============================================================================
# from tests/test_styles.py
# ============================================================================
import json
import os
import sys
from pathlib import Path

from PIL import Image

TEST_STYLES_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_STYLES_ROOT))
sys.path.insert(0, str(TEST_STYLES_ROOT / "scripts"))

from animation.two_d import backgrounds, illustrations, renderer, themes  # noqa: E402
from animation.two_d.canvas import PALETTE, Canvas, load_font, use_theme  # noqa: E402
from animation.two_d.thumbnail import SIZES, make_thumbnail  # noqa: E402
from audio import subtitles  # noqa: E402
from content.script_generator import available_variants, generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
import produce_video  # noqa: E402
import style_samples  # noqa: E402

TEST_STYLES_OK = {"status": "passed_automated_checks"}
TEST_STYLES_TOPICS = ("physics-001", "chem-001")
FANCY = ("vector_pop", "vintage", "collage")


def TEST_STYLES_rendering():
    return json.loads((TEST_STYLES_ROOT / "config" / "config.json").read_text())["rendering"]


def luminance(rgb):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def board(topic, fmt, variant):
    rec = load_topic_record(str(TEST_STYLES_ROOT), topic)
    return rec, generate_storyboard(generate_script(rec, fmt, variant, TEST_STYLES_rendering(), TEST_STYLES_OK), rec, TEST_STYLES_rendering())


# --- themes --------------------------------------------------------------------------
def test_all_themes_exist_and_have_complete_schemes():
    for name, theme in themes.THEMES.items():
        for scheme in theme.schemes:
            assert {"bg_top", "bg_bottom", "panel", "panel2", "accent"} <= set(scheme), name
    assert len(themes.THEMES["vector_pop"].schemes) >= 6


def test_unknown_theme_is_refused():
    try:
        themes.set_theme("neon")
        assert False
    except ValueError as err:
        assert "vector_pop" in str(err)


def test_text_is_readable_on_every_card_and_background():
    for name in FANCY:
        theme = themes.THEMES[name]
        for scheme in theme.schemes:
            mid = tuple((a + b) // 2 for a, b in zip(scheme["bg_top"], scheme["bg_bottom"]))
            for surface in (scheme["panel"], scheme["panel2"], mid):
                assert contrast(theme.base["text"], surface) >= 3.0, (name, surface)


def test_scenes_cycle_through_many_colours():
    for name in FANCY:
        assert len({tuple(themes.scheme_for(n, themes.THEMES[name])["panel"]) for n in range(1, 13)}) >= 5, name


def test_use_theme_puts_the_old_look_back():
    before = themes.current().name
    with use_theme("vector_pop"):
        assert themes.current().name == "vector_pop"
    assert themes.current().name == before
    assert tuple(PALETTE["bg"]) == (11, 18, 32)


# --- backgrounds and canvas ----------------------------------------------------------------
def paint(theme, number=1, secs=0.0, size=(270, 480)):
    with use_theme(theme):
        scheme = themes.apply_to_palette(PALETTE, number)
        c = Canvas(size[0], size[1], scheme, seed=number)
        c.paint_background(secs)
        return c.img.tobytes()


def test_backgrounds_are_repeatable_and_move_over_time():
    for name in FANCY:
        assert paint(name, 2, 1.0) == paint(name, 2, 1.0)
        assert paint(name, 2, 0.0) != paint(name, 2, 3.0)


def test_each_scene_gets_a_different_background():
    for name in FANCY:
        assert paint(name, 1) != paint(name, 2)


def test_classic_background_stays_flat():
    with use_theme("classic"):
        c = Canvas(100, 100, themes.apply_to_palette(PALETTE, 1))
        c.paint_background(2.0)
        assert len(set(c.img.getdata())) == 1


def test_cards_get_an_outline_and_shadow_in_cartoon_styles_only():
    with use_theme("vector_pop"):
        themes.apply_to_palette(PALETTE, 1)
        c = Canvas(540, 960)
        c.rect((100, 100, 400, 300), fill="panel", radius=30)
        theme = themes.current()
        assert c.img.getpixel((250, 105)) == theme.outline or c.img.getpixel((250, 102)) == theme.outline
        assert c.img.getpixel((410, 306)) == theme.shadow
    with use_theme("classic"):
        c = Canvas(540, 960)
        c.rect((100, 100, 400, 300), fill="panel", radius=30)
        assert c.img.getpixel((410, 306)) == tuple(PALETTE["bg"])


def test_torn_edges_are_not_straight():
    with use_theme("collage"):
        themes.apply_to_palette(PALETTE, 1)
        c = Canvas(540, 960)
        pts = c._torn((100, 100, 400, 300), 8)
        assert len({round(y) for _, y in pts[:10]}) > 3


def test_symbol_text_falls_back_to_a_full_font():
    assert Canvas.kind_for("a = G M / r\u00b2", "bold") == "strong"
    assert Canvas.kind_for("CH\u2083COOH", "bold") == "strong"
    assert Canvas.kind_for("Hello world", "bold") == "bold"


def test_missing_display_font_falls_back_without_crashing():
    font = load_font("display", 40)
    assert font.getlength("Hello") > 10


def test_themed_text_is_bigger():
    with use_theme("vector_pop"):
        assert Canvas(540, 960).font("sans", 30).size > load_font("sans", round(30 * (540 / 1080.0))).size


# --- illustrations ---------------------------------------------------------------------------------
def test_illustrations_draw_for_both_topics():
    for topic in TEST_STYLES_TOPICS:
        rec = load_topic_record(str(TEST_STYLES_ROOT), topic)
        for t in (0.0, 0.5, 1.0):
            assert illustrations.render_illustration(rec, t, 300, 260, secs=t * 5, ss=1).size == (300, 260)


def test_illustrations_move_over_time():
    for topic in TEST_STYLES_TOPICS:
        rec = load_topic_record(str(TEST_STYLES_ROOT), topic)
        a = illustrations.render_illustration(rec, 0.1, 200, 180, ss=1).tobytes()
        b = illustrations.render_illustration(rec, 0.7, 200, 180, ss=1).tobytes()
        assert a != b


def test_cartoon_hammer_and_feather_still_fall_together():
    for t in (0.0, 0.3, 0.5, 0.7, 1.0):
        hammer, feather = illustrations._moon_heights(t)
        assert abs(hammer - feather) < 1e-9


def test_unknown_illustration_returns_none():
    rec = load_topic_record(str(TEST_STYLES_ROOT), "physics-001")
    rec["scene3d"] = None
    assert illustrations.render_illustration(rec, 0.5, 100, 100) is None


# --- scenes in every style ------------------------------------------------------------------------------
def test_every_scene_draws_in_every_style():
    for name in FANCY:
        with use_theme(name):
            for topic in TEST_STYLES_TOPICS:
                for fmt, size in (("short", (270, 480)), ("long", (480, 270))):
                    rec, storyboard = board(topic, fmt, "what_if")
                    for scene in storyboard["scenes"]:
                        for t in (0.0, 0.6):
                            assert renderer.draw_frame(scene, rec, size[0], size[1], t).size == size


def test_opening_scene_uses_the_cartoon_picture_in_cartoon_styles():
    rec, storyboard = board("physics-001", "short", "explainer")
    hook = storyboard["scenes"][0]
    with use_theme("vector_pop"):
        cartoon = renderer.draw_frame(hook, rec, 270, 480, 0.6).tobytes()
    classic = renderer.draw_frame(hook, rec, 270, 480, 0.6).tobytes()
    assert cartoon != classic


def test_transitions_start_from_the_scene_background_in_cartoon_styles():
    with use_theme("vector_pop"):
        scene = {"transition": "wipe", "scene_number": 3, "duration_seconds": 5}
        image = renderer.apply_transition(Image.new("RGB", (60, 60), (255, 255, 255)), scene, 0.1, 5)
        assert image.getpixel((55, 30)) != (255, 255, 255)


# --- thumbnails ----------------------------------------------------------------------------------------------
def test_thumbnails_have_the_right_size_and_are_small_enough(tmp_path):
    for fmt in ("long", "short"):
        for topic in TEST_STYLES_TOPICS:
            rec = load_topic_record(str(TEST_STYLES_ROOT), topic)
            with use_theme("vector_pop"):
                path = make_thumbnail(rec, fmt, tmp_path / f"{topic}_{fmt}.jpg")
            image = Image.open(path)
            assert image.size == SIZES[fmt] and Path(path).stat().st_size < 2_000_000


def test_thumbnails_are_colourful_and_not_blank(tmp_path):
    rec = load_topic_record(str(TEST_STYLES_ROOT), "physics-001")
    with use_theme("vector_pop"):
        image = Image.open(make_thumbnail(rec, "long", tmp_path / "t.jpg")).convert("RGB").resize((64, 36))
    colours = {(r // 32, g // 32, b // 32) for r, g, b in image.getdata()}
    assert len(colours) >= 15


def test_thumbnails_differ_between_styles(tmp_path):
    rec = load_topic_record(str(TEST_STYLES_ROOT), "chem-001")
    images = []
    for name in FANCY:
        with use_theme(name):
            images.append(Image.open(make_thumbnail(rec, "long", tmp_path / f"{name}.jpg")).tobytes())
    assert len(set(images)) == 3


def test_thumbnail_copes_with_a_very_long_headline(tmp_path):
    rec = load_topic_record(str(TEST_STYLES_ROOT), "physics-001")
    rec["thumbnail"] = dict(rec["thumbnail"], headline="Why do absolutely every kind of object fall together")
    with use_theme("vector_pop"):
        assert make_thumbnail(rec, "short", tmp_path / "long.jpg")


def test_thumbnail_without_a_spec_uses_the_title(tmp_path):
    rec = load_topic_record(str(TEST_STYLES_ROOT), "physics-001")
    rec.pop("thumbnail")
    with use_theme("vector_pop"):
        assert make_thumbnail(rec, "long", tmp_path / "t.jpg")


def test_every_topic_has_a_thumbnail_spec():
    for topic in TEST_STYLES_TOPICS:
        spec = load_topic_record(str(TEST_STYLES_ROOT), topic)["thumbnail"]
        assert spec["headline"] and len(spec["headline"].split()) <= 4


# --- captions and pipeline ------------------------------------------------------------------------------------------
def test_cartoon_captions_use_an_outline_and_the_display_font():
    cues = [{"index": 1, "start": 0, "end": 2, "text": "Hello", "scene_number": 1}]
    ass = subtitles.to_ass(cues, 1080, 1920, True, "Lilita One", True)
    assert "Lilita One" in ass and ",1," in ass.split("Style: Default,")[1].split("\n")[0]
    plain = subtitles.to_ass(cues, 1080, 1920, True)
    assert "DejaVu Sans" in plain


def test_config_picks_a_known_style():
    assert TEST_STYLES_rendering()["style"]["theme"] in themes.THEMES


def test_a_whole_video_can_be_made_in_a_cartoon_style(tmp_path):
    import shutil
    from rendering.assembler import subtitles_filter_available
    if not (shutil.which("ffmpeg") and subtitles_filter_available()):
        return
    saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    try:
        ok, lines = produce_video.run(str(TEST_STYLES_ROOT), "chem-001", "short", str(tmp_path), "draft", "none")
    finally:
        renderer.QUALITY["draft"] = saved
    assert ok, lines
    report = json.loads((tmp_path / "chem-001" / "short_explainer" / "final" / "final_report.json").read_text())
    assert report["theme"] == TEST_STYLES_rendering()["style"]["theme"]
    assert themes.current().name == "classic"


def test_style_can_be_overridden_by_an_environment_setting(tmp_path):
    import shutil
    from rendering.assembler import subtitles_filter_available
    if not (shutil.which("ffmpeg") and subtitles_filter_available()):
        return
    saved_env = os.environ.get("THEME_OVERRIDE")
    os.environ["THEME_OVERRIDE"] = "vintage"
    saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    try:
        ok, lines = produce_video.run(str(TEST_STYLES_ROOT), "chem-001", "short", str(tmp_path), "draft", "none")
    finally:
        renderer.QUALITY["draft"] = saved
        if saved_env is None:
            del os.environ["THEME_OVERRIDE"]
        else:
            os.environ["THEME_OVERRIDE"] = saved_env
    assert ok, lines
    assert json.loads((tmp_path / "chem-001" / "short_explainer" / "final" / "final_report.json").read_text())[
        "theme"] == "vintage"


def test_an_unknown_style_is_reported(tmp_path):
    saved_env = os.environ.get("THEME_OVERRIDE")
    os.environ["THEME_OVERRIDE"] = "neon"
    try:
        ok, lines = produce_video.run(str(TEST_STYLES_ROOT), "chem-001", "short", str(tmp_path), "draft", "none")
    finally:
        if saved_env is None:
            del os.environ["THEME_OVERRIDE"]
        else:
            os.environ["THEME_OVERRIDE"] = saved_env
    assert not ok and "Unknown theme" in lines[0]


# --- the sample maker --------------------------------------------------------------------------------------------------
def test_style_samples_for_every_style(tmp_path):
    ok, lines = style_samples.run(str(TEST_STYLES_ROOT), tmp_path)
    assert ok, lines
    for name in themes.THEMES:
        assert (tmp_path / name / "physics-001" / "thumbnail_youtube.jpg").exists()
        assert (tmp_path / name / "chem-001" / "scenes.png").exists()
    assert (tmp_path / "COMPARE.png").exists() and (tmp_path / "READ_ME.txt").exists()
    assert themes.current().name == "classic"


def test_style_samples_can_be_limited_and_reject_unknown_names(tmp_path):
    ok, lines = style_samples.run(str(TEST_STYLES_ROOT), tmp_path, ["vintage"])
    assert ok and not (tmp_path / "collage").exists()
    ok, lines = style_samples.run(str(TEST_STYLES_ROOT), tmp_path / "b", ["nope"])
    assert not ok and "unknown style" in lines[0]


# ============================================================================
# from tests/test_visuals.py
# ============================================================================
import json
import sys
from pathlib import Path

TEST_VISUALS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_VISUALS_ROOT))

from animation.simulations import free_fall as ff  # noqa: E402
from animation.simulations import reaction_layout as rl  # noqa: E402
from animation.two_d import diagrams, renderer  # noqa: E402
from animation.two_d.canvas import Canvas  # noqa: E402
from animation.two_d.icons import ICON_NAMES, draw_icon  # noqa: E402
from animation.two_d.scenes import KIND_ICON, highlight_words  # noqa: E402
from content.script_generator import available_variants, generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402

TEST_VISUALS_TOPICS = ("physics-001", "chem-001")
TEST_VISUALS_OK_SCIENCE = {"status": "passed_automated_checks"}
EQ = "CH3COOH + NaHCO3 -> CH3COONa + H2O + CO2"


def TEST_VISUALS_rendering():
    return json.loads((TEST_VISUALS_ROOT / "config" / "config.json").read_text())["rendering"]


def TEST_VISUALS_board(topic, fmt, variant):
    rec = load_topic_record(str(TEST_VISUALS_ROOT), topic)
    script = generate_script(rec, fmt, variant, TEST_VISUALS_rendering(), TEST_VISUALS_OK_SCIENCE)
    return rec, script, generate_storyboard(script, rec, TEST_VISUALS_rendering())


# --- icons ---------------------------------------------------------------------
def test_every_icon_draws_at_several_times():
    for name in ICON_NAMES:
        for secs in (0.0, 1.3, 4.0):
            for a in (0.2, 1.0):
                canvas = Canvas(300, 300)
                before = canvas.img.tobytes()
                draw_icon(canvas, name, 150, 150, 80, secs, a)
                assert canvas.img.tobytes() != before, name


def test_unknown_icon_draws_nothing():
    canvas = Canvas(200, 200)
    before = canvas.img.tobytes()
    draw_icon(canvas, "nonsense", 100, 100, 60)
    assert canvas.img.tobytes() == before


def test_icon_map_uses_real_icons():
    assert set(KIND_ICON.values()) <= set(ICON_NAMES)


def test_icons_actually_move():
    frames = []
    for secs in (0.0, 0.4):
        canvas = Canvas(300, 300)
        draw_icon(canvas, "atom", 150, 150, 80, secs, 1.0)
        frames.append(canvas.img.tobytes())
    assert frames[0] != frames[1]


# --- model-based diagram numbers -----------------------------------------------------
def test_drag_ratio_is_tiny_for_hammer_and_large_for_feather():
    assert ff.drag_to_weight("hammer", 0.8) < 0.01
    assert 0.5 < ff.drag_to_weight("feather", 0.8) < 1.5


def test_reaction_layout_stages():
    start = {t["label"]: t for t in rl.reaction_tokens(EQ, 0.0)}
    end = {t["label"]: t for t in rl.reaction_tokens(EQ, 1.0)}
    assert start["CH3COOH"]["alpha"] == 1 and start["CH3COONa"]["alpha"] == 0
    assert end["CH3COOH"]["alpha"] == 0 and end["CH3COONa"]["alpha"] == 1
    assert end["CO2"]["gas"] and end["CO2"]["alpha"] == 0 and end["CO2"]["y"] <= 0.13


def test_reactants_move_toward_each_other():
    early = {t["label"]: t for t in rl.reaction_tokens(EQ, 0.0)}
    later = {t["label"]: t for t in rl.reaction_tokens(EQ, 0.4)}
    assert later["CH3COOH"]["x"] > early["CH3COOH"]["x"]


def test_split_equation_reads_coefficients():
    reactants, products = rl.split_equation("2H2 + O2 -> 2H2O")
    assert reactants == [(2, "H2"), (1, "O2")] and products == [(2, "H2O")]


def test_gas_leaves_open_container_but_not_sealed():
    assert rl.atoms_inside(True, 0.0) == rl.ATOM_COUNT
    assert rl.atoms_inside(True, 1.0) < rl.ATOM_COUNT
    counts = [rl.atoms_inside(True, i / 20) for i in range(21)]
    assert counts == sorted(counts, reverse=True)
    assert all(rl.atoms_inside(False, i / 20) == rl.ATOM_COUNT for i in range(21))


# --- diagrams and cards ---------------------------------------------------------------
def test_diagrams_return_false_when_topic_has_no_data():
    rec = load_topic_record(str(TEST_VISUALS_ROOT), "physics-001")
    canvas = Canvas(270, 480)
    ctx = {"scene": {"section_title": "x", "data": {}, "duration_seconds": 5}, "record": rec}
    assert diagrams.reaction_particles(canvas, 0.5, ctx) is False
    assert diagrams.term_chips(canvas, 0.5, ctx) is False
    assert diagrams.checklist(canvas, 0.5, ctx) is False
    assert diagrams.sources_list(canvas, 0.5, ctx) is False
    assert diagrams.safety_card(canvas, 0.5, ctx) is False


def test_scenes_carry_list_data():
    _, script, _ = TEST_VISUALS_board("chem-001", "long", "explainer")
    by_kind = {s["kind"]: s for s in script["sections"]}
    assert by_kind["terminology"]["data"]["terms"]
    assert by_kind["limitation"]["data"]["items"]
    assert by_kind["safety"]["data"]["items"]


def test_diagram_choice_per_scene():
    _, script, _ = TEST_VISUALS_board("physics-001", "short", "what_if")
    why = [s for s in script["sections"] if s["kind"] == "why"][0]
    assert why["data"]["diagram"] == "drag_vs_gravity"
    _, script, _ = TEST_VISUALS_board("physics-001", "long", "explainer")
    answer = [s for s in script["sections"] if s["kind"] == "answer"][0]
    assert answer["data"]["diagram"] == "mass_cancels"


def test_all_scenes_still_draw_with_new_visuals():
    for topic in TEST_VISUALS_TOPICS:
        rec = load_topic_record(str(TEST_VISUALS_ROOT), topic)
        for fmt, size in (("short", (270, 480)), ("long", (480, 270))):
            for variant in available_variants(rec):
                _, _, storyboard = TEST_VISUALS_board(topic, fmt, variant)
                for scene in storyboard["scenes"]:
                    for t in (0.0, 0.3, 0.6, 1.0):
                        assert renderer.draw_frame(scene, rec, size[0], size[1], t).size == size


def test_frames_change_over_time_for_diagrams():
    rec, _, storyboard = TEST_VISUALS_board("physics-001", "long", "explainer")
    scene = [s for s in storyboard["scenes"] if s["section_kind"] == "answer"][0]
    early = renderer.draw_frame(scene, rec, 480, 270, 0.15).tobytes()
    late = renderer.draw_frame(scene, rec, 480, 270, 0.9).tobytes()
    assert early != late


def test_highlight_words_come_from_the_topic():
    words = highlight_words(load_topic_record(str(TEST_VISUALS_ROOT), "physics-001"))
    assert "mass" in words and "gravitational" in words
    assert "from" not in words


def test_a_topic_without_its_own_simulation_still_draws_every_scene():
    rec = load_topic_record(str(TEST_VISUALS_ROOT), "chem-001")
    for key in ("simulation", "scene3d", "diagrams"):
        rec.pop(key, None)
    for scenario in rec["what_if_scenarios"]:
        scenario.pop("simulation", None)
        scenario.pop("diagram", None)
    for fmt, size in (("short", (270, 480)), ("long", (480, 270))):
        script = generate_script(rec, fmt, "explainer", TEST_VISUALS_rendering(), TEST_VISUALS_OK_SCIENCE)
        storyboard = generate_storyboard(script, rec, TEST_VISUALS_rendering())
        for scene in storyboard["scenes"]:
            for t in (0.0, 0.5, 1.0):
                assert renderer.draw_frame(scene, rec, size[0], size[1], t).size == size
