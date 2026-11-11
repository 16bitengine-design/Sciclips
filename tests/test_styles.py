import json
import os
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from animation.two_d import backgrounds, illustrations, renderer, themes  # noqa: E402
from animation.two_d.canvas import PALETTE, Canvas, load_font, use_theme  # noqa: E402
from animation.two_d.thumbnail import SIZES, make_thumbnail  # noqa: E402
from audio import subtitles  # noqa: E402
from content.script_generator import available_variants, generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
import produce_video  # noqa: E402
import style_samples  # noqa: E402

OK = {"status": "passed_automated_checks"}
TOPICS = ("physics-001", "chem-001")
FANCY = ("vector_pop", "vintage", "collage")


def rendering():
    return json.loads((ROOT / "config" / "rendering.json").read_text())


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
    rec = load_topic_record(str(ROOT), topic)
    return rec, generate_storyboard(generate_script(rec, fmt, variant, rendering(), OK), rec, rendering())


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
    for topic in TOPICS:
        rec = load_topic_record(str(ROOT), topic)
        for t in (0.0, 0.5, 1.0):
            assert illustrations.render_illustration(rec, t, 300, 260, secs=t * 5, ss=1).size == (300, 260)


def test_illustrations_move_over_time():
    for topic in TOPICS:
        rec = load_topic_record(str(ROOT), topic)
        a = illustrations.render_illustration(rec, 0.1, 200, 180, ss=1).tobytes()
        b = illustrations.render_illustration(rec, 0.7, 200, 180, ss=1).tobytes()
        assert a != b


def test_cartoon_hammer_and_feather_still_fall_together():
    for t in (0.0, 0.3, 0.5, 0.7, 1.0):
        hammer, feather = illustrations._moon_heights(t)
        assert abs(hammer - feather) < 1e-9


def test_unknown_illustration_returns_none():
    rec = load_topic_record(str(ROOT), "physics-001")
    rec["scene3d"] = None
    assert illustrations.render_illustration(rec, 0.5, 100, 100) is None


# --- scenes in every style ------------------------------------------------------------------------------
def test_every_scene_draws_in_every_style():
    for name in FANCY:
        with use_theme(name):
            for topic in TOPICS:
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
        for topic in TOPICS:
            rec = load_topic_record(str(ROOT), topic)
            with use_theme("vector_pop"):
                path = make_thumbnail(rec, fmt, tmp_path / f"{topic}_{fmt}.jpg")
            image = Image.open(path)
            assert image.size == SIZES[fmt] and Path(path).stat().st_size < 2_000_000


def test_thumbnails_are_colourful_and_not_blank(tmp_path):
    rec = load_topic_record(str(ROOT), "physics-001")
    with use_theme("vector_pop"):
        image = Image.open(make_thumbnail(rec, "long", tmp_path / "t.jpg")).convert("RGB").resize((64, 36))
    colours = {(r // 32, g // 32, b // 32) for r, g, b in image.getdata()}
    assert len(colours) >= 15


def test_thumbnails_differ_between_styles(tmp_path):
    rec = load_topic_record(str(ROOT), "chem-001")
    images = []
    for name in FANCY:
        with use_theme(name):
            images.append(Image.open(make_thumbnail(rec, "long", tmp_path / f"{name}.jpg")).tobytes())
    assert len(set(images)) == 3


def test_thumbnail_copes_with_a_very_long_headline(tmp_path):
    rec = load_topic_record(str(ROOT), "physics-001")
    rec["thumbnail"] = dict(rec["thumbnail"], headline="Why do absolutely every kind of object fall together")
    with use_theme("vector_pop"):
        assert make_thumbnail(rec, "short", tmp_path / "long.jpg")


def test_thumbnail_without_a_spec_uses_the_title(tmp_path):
    rec = load_topic_record(str(ROOT), "physics-001")
    rec.pop("thumbnail")
    with use_theme("vector_pop"):
        assert make_thumbnail(rec, "long", tmp_path / "t.jpg")


def test_every_topic_has_a_thumbnail_spec():
    for topic in TOPICS:
        spec = load_topic_record(str(ROOT), topic)["thumbnail"]
        assert spec["headline"] and len(spec["headline"].split()) <= 4


# --- captions and pipeline ------------------------------------------------------------------------------------------
def test_cartoon_captions_use_an_outline_and_the_display_font():
    cues = [{"index": 1, "start": 0, "end": 2, "text": "Hello", "scene_number": 1}]
    ass = subtitles.to_ass(cues, 1080, 1920, True, "Lilita One", True)
    assert "Lilita One" in ass and ",1," in ass.split("Style: Default,")[1].split("\n")[0]
    plain = subtitles.to_ass(cues, 1080, 1920, True)
    assert "DejaVu Sans" in plain


def test_config_picks_a_known_style():
    assert rendering()["style"]["theme"] in themes.THEMES


def test_a_whole_video_can_be_made_in_a_cartoon_style(tmp_path):
    import shutil
    from rendering.assembler import subtitles_filter_available
    if not (shutil.which("ffmpeg") and subtitles_filter_available()):
        return
    saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    try:
        ok, lines = produce_video.run(str(ROOT), "chem-001", "short", str(tmp_path), "draft", "none")
    finally:
        renderer.QUALITY["draft"] = saved
    assert ok, lines
    report = json.loads((tmp_path / "chem-001" / "short_explainer" / "final" / "final_report.json").read_text())
    assert report["theme"] == rendering()["style"]["theme"]
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
        ok, lines = produce_video.run(str(ROOT), "chem-001", "short", str(tmp_path), "draft", "none")
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
        ok, lines = produce_video.run(str(ROOT), "chem-001", "short", str(tmp_path), "draft", "none")
    finally:
        if saved_env is None:
            del os.environ["THEME_OVERRIDE"]
        else:
            os.environ["THEME_OVERRIDE"] = saved_env
    assert not ok and "Unknown theme" in lines[0]


# --- the sample maker --------------------------------------------------------------------------------------------------
def test_style_samples_for_every_style(tmp_path):
    ok, lines = style_samples.run(str(ROOT), tmp_path)
    assert ok, lines
    for name in themes.THEMES:
        assert (tmp_path / name / "physics-001" / "thumbnail_youtube.jpg").exists()
        assert (tmp_path / name / "chem-001" / "scenes.png").exists()
    assert (tmp_path / "COMPARE.png").exists() and (tmp_path / "READ_ME.txt").exists()
    assert themes.current().name == "classic"


def test_style_samples_can_be_limited_and_reject_unknown_names(tmp_path):
    ok, lines = style_samples.run(str(ROOT), tmp_path, ["vintage"])
    assert ok and not (tmp_path / "collage").exists()
    ok, lines = style_samples.run(str(ROOT), tmp_path / "b", ["nope"])
    assert not ok and "unknown style" in lines[0]
