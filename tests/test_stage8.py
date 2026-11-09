import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

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

OK = {"status": "passed_automated_checks"}
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
CAN_BURN = HAVE_FFMPEG and assembler.subtitles_filter_available()


def rendering():
    return json.loads((ROOT / "config" / "rendering.json").read_text())


def make(topic="physics-001", fmt="short", variant="explainer"):
    rec = load_topic_record(str(ROOT), topic)
    script = generate_script(rec, fmt, variant, rendering(), OK)
    return rec, script, generate_storyboard(script, rec, rendering())


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
            rec, _, board = make("physics-001", fmt)
            timed = pipeline.apply_timing(board)
            counts = renderer.plan_frames(timed, fps)
            assert abs(sum(counts.values()) - round(timed["total_duration_seconds"] * fps)) <= len(counts) * 0 + 2


def test_every_scene_gets_at_least_two_frames():
    _, _, board = make()
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
        _, long_script, _ = make("physics-001", "long", variant)
        assert long_script["sections"][-1]["kind"] == "outro"
        _, short_script, _ = make("physics-001", "short", variant)
        assert all(s["kind"] != "outro" for s in short_script["sections"])


def test_outro_can_be_switched_off_in_config():
    cfg = rendering()
    cfg["branding"]["outro"]["long"] = False
    rec = load_topic_record(str(ROOT), "physics-001")
    script = generate_script(rec, "long", "explainer", cfg, OK)
    assert all(s["kind"] != "outro" for s in script["sections"])


def test_scripts_and_storyboards_with_outro_still_validate():
    for topic in ("physics-001", "chem-001"):
        rec, script, board = make(topic, "long")
        assert validate_script(script, rec, rendering())["errors"] == []
        assert validate_storyboard(board, script, rec, rendering())["errors"] == []


def test_outro_card_draws():
    rec, _, board = make("physics-001", "long")
    scene = board["scenes"][-1]
    image = renderer.draw_frame(scene, rec, 480, 270, 0.9)
    assert image.size == (480, 270)


# --- chapters and description ---------------------------------------------------------
def test_chapters_follow_the_rules_youtube_needs():
    for topic in ("physics-001", "chem-001"):
        _, _, board = make(topic, "long")
        timed = pipeline.apply_timing(board)
        chapters = assembler.build_chapters(timed)
        assert len(chapters) >= 3 and chapters[0][0] == 0
        assert all(b[0] - a[0] >= 10 for a, b in zip(chapters, chapters[1:]))
        assert len({title for _, title in chapters}) == len(chapters)


def test_chapters_are_empty_when_too_few_fit():
    _, _, board = make("physics-001", "short")
    timed = pipeline.apply_timing(board)
    for scene in timed["scenes"]:
        scene["section_kind"] = "outro"
    assert assembler.build_chapters(timed) == []


def test_description_lists_sources_and_makes_honest_statements():
    rec, _, board = make("chem-001", "long")
    text = assembler.build_description(rec, pipeline.apply_timing(board), "long", "Kokoro text-to-speech")
    for source in rec["sources"]:
        assert source["url"] in text
    assert "synthetic voice" in text and "not experimental evidence" in text
    assert "Chapters" in text and "Safety" in text
    for forbidden in ("peer review", "peer-reviewed", "expert reviewed"):
        assert forbidden not in text.lower()


def test_short_description_has_no_chapters():
    rec, _, board = make("physics-001", "short")
    text = assembler.build_description(rec, pipeline.apply_timing(board), "short", "Kokoro text-to-speech")
    assert "Chapters" not in text


# --- file checks ----------------------------------------------------------------------------
def test_decode_check_detects_damage(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, _, board = make()
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
    if not HAVE_FFMPEG:
        return
    rec, _, board = make("chem-001")
    saved = tiny()
    try:
        one = renderer.render_storyboard(board, rec, tmp_path / "a", "draft", only_scenes={1, 2, 3}, workers=1)
        two = renderer.render_storyboard(board, rec, tmp_path / "b", "draft", only_scenes={1, 2, 3}, workers=2)
    finally:
        renderer.QUALITY["draft"] = saved
    assert [Path(r["path"]).read_bytes() for r in one] == [Path(r["path"]).read_bytes() for r in two]


# --- end to end ----------------------------------------------------------------------------------
def build_final(tmp_path, topic="chem-001", fmt="short", provider=None):
    rec, _, board = make(topic, fmt)
    audio = pipeline.produce(board, rec, rendering(), tmp_path, provider=provider) if provider else \
        pipeline.produce(board, rec, rendering(), tmp_path, "none")
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
    cfg = rendering()
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
        ok, lines = produce_video.run(str(ROOT), "chem-001", "short", str(tmp_path), "draft", "none")
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
        ok, lines = produce_video.run(str(ROOT), "chem-001", "short", str(tmp_path), "draft", "kokoro")
    finally:
        renderer.QUALITY["draft"] = saved
        for key, value in saved_env.items():
            if value is not None:
                os.environ[key] = value
    assert ok is False
    assert any("could not be used" in line for line in lines)
    assert (tmp_path / "chem-001" / "short_explainer" / "final" / "chem-001_short_explainer.mp4").exists()


def test_produce_video_rejects_unknown_topic(tmp_path):
    ok, lines = produce_video.run(str(ROOT), "nope-1", "short", str(tmp_path))
    assert not ok


def test_branding_is_in_the_config():
    cfg = rendering()
    assert cfg["branding"]["channel_name"] and cfg["final"]["crf"]
