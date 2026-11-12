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
