import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from animation.simulations import free_fall as ff  # noqa: E402
from animation.simulations import reaction_layout as rl  # noqa: E402
from animation.two_d import diagrams, renderer  # noqa: E402
from animation.two_d.canvas import Canvas  # noqa: E402
from animation.two_d.icons import ICON_NAMES, draw_icon  # noqa: E402
from animation.two_d.scenes import KIND_ICON, highlight_words  # noqa: E402
from content.script_generator import available_variants, generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402

TOPICS = ("physics-001", "chem-001")
OK_SCIENCE = {"status": "passed_automated_checks"}
EQ = "CH3COOH + NaHCO3 -> CH3COONa + H2O + CO2"


def rendering():
    return json.loads((ROOT / "config" / "rendering.json").read_text())


def board(topic, fmt, variant):
    rec = load_topic_record(str(ROOT), topic)
    script = generate_script(rec, fmt, variant, rendering(), OK_SCIENCE)
    return rec, script, generate_storyboard(script, rec, rendering())


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
    rec = load_topic_record(str(ROOT), "physics-001")
    canvas = Canvas(270, 480)
    ctx = {"scene": {"section_title": "x", "data": {}, "duration_seconds": 5}, "record": rec}
    assert diagrams.reaction_particles(canvas, 0.5, ctx) is False
    assert diagrams.term_chips(canvas, 0.5, ctx) is False
    assert diagrams.checklist(canvas, 0.5, ctx) is False
    assert diagrams.sources_list(canvas, 0.5, ctx) is False
    assert diagrams.safety_card(canvas, 0.5, ctx) is False


def test_scenes_carry_list_data():
    _, script, _ = board("chem-001", "long", "explainer")
    by_kind = {s["kind"]: s for s in script["sections"]}
    assert by_kind["terminology"]["data"]["terms"]
    assert by_kind["limitation"]["data"]["items"]
    assert by_kind["sources"]["data"]["sources"]
    assert by_kind["safety"]["data"]["items"]


def test_diagram_choice_per_scene():
    _, script, _ = board("physics-001", "short", "what_if")
    why = [s for s in script["sections"] if s["kind"] == "why"][0]
    assert why["data"]["diagram"] == "drag_vs_gravity"
    _, script, _ = board("physics-001", "short", "explainer")
    answer = [s for s in script["sections"] if s["kind"] == "answer"][0]
    assert answer["data"]["diagram"] == "mass_cancels"


def test_all_scenes_still_draw_with_new_visuals():
    for topic in TOPICS:
        rec = load_topic_record(str(ROOT), topic)
        for fmt, size in (("short", (270, 480)), ("long", (480, 270))):
            for variant in available_variants(rec):
                _, _, storyboard = board(topic, fmt, variant)
                for scene in storyboard["scenes"]:
                    for t in (0.0, 0.3, 0.6, 1.0):
                        assert renderer.draw_frame(scene, rec, size[0], size[1], t).size == size


def test_frames_change_over_time_for_diagrams():
    rec, _, storyboard = board("physics-001", "short", "explainer")
    scene = [s for s in storyboard["scenes"] if s["section_kind"] == "answer"][0]
    early = renderer.draw_frame(scene, rec, 270, 480, 0.15).tobytes()
    late = renderer.draw_frame(scene, rec, 270, 480, 0.9).tobytes()
    assert early != late


def test_highlight_words_come_from_the_topic():
    words = highlight_words(load_topic_record(str(ROOT), "physics-001"))
    assert "mass" in words and "gravitational" in words
    assert "from" not in words
