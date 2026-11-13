import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

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
    return json.loads((ROOT / "config" / "rendering.json").read_text())


def storyboard(topic, fmt, variant):
    rec = load_topic_record(str(ROOT), topic)
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
        rec = load_topic_record(str(ROOT), topic)
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
        ok, lines = render_scenes.run(str(ROOT), "chem-001", "short", str(tmp_path), "draft")
    finally:
        renderer.QUALITY["draft"] = saved
    assert ok, lines
    assert (tmp_path / "chem-001" / "short_explainer" / "scenes" / "contact_sheet.png").exists()
    assert any("OK" in line for line in lines)


def test_render_scenes_rejects_unknown_topic(tmp_path):
    ok, lines = render_scenes.run(str(ROOT), "nope-1", "short", str(tmp_path))
    assert not ok
