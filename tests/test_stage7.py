import json
import shutil
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from audio import audio_mixer, narration, pipeline, subtitles  # noqa: E402
from audio.speakable import load_pronunciations, speakable  # noqa: E402
from content.script_generator import generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
from animation.two_d import renderer  # noqa: E402
from rendering.video_validator import validate_video  # noqa: E402
import render_scenes  # noqa: E402

OK = {"status": "passed_automated_checks"}
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def rendering():
    return json.loads((ROOT / "config" / "rendering.json").read_text())


def make(topic="physics-001", fmt="short", variant="explainer"):
    rec = load_topic_record(str(ROOT), topic)
    script = generate_script(rec, fmt, variant, rendering(), OK)
    return rec, generate_storyboard(script, rec, rendering())


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
    result = pipeline.produce(board, rec, rendering(), tmp_path, "none")
    assert result["provider"] == "none" and Path(result["files"]["srt"]).exists()
    assert "audio_mix" not in result["files"]
    assert result["timeline"]["publishable"] is True


def test_failing_voice_falls_back_without_stopping(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, rendering(), tmp_path, provider=BrokenProvider())
    assert result["provider"] == "none"
    assert any("voice exploded" in n for n in result["notes"])
    assert Path(result["files"]["srt"]).exists()


def test_missing_kokoro_means_subtitles_only_and_a_reported_problem(tmp_path):
    import os
    saved = {k: os.environ.pop(k, None) for k in ("KOKORO_MODEL", "KOKORO_VOICES")}
    try:
        rec, board = make("chem-001")
        result = pipeline.produce(board, rec, rendering(), tmp_path, "kokoro")
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
    result = pipeline.produce(board, rec, rendering(), tmp_path, "espeak")
    assert result["provider"] == "none"
    assert any("Unknown narration provider" in n for n in result["notes"])
    assert result["problems"]


def test_a_failing_voice_is_reported_as_a_problem(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, rendering(), tmp_path, provider=BrokenProvider())
    assert any("could not be used" in p for p in result["problems"])


def test_kokoro_end_to_end_with_a_stand_in_engine(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, board = make("chem-001")
    provider = narration.KokoroProvider(engine=FakeEngine())
    result = pipeline.produce(board, rec, rendering(), tmp_path, provider=provider)
    assert result["provider"] == "kokoro" and result["problems"] == [], result["problems"]
    assert result["timeline"]["publishable"] is True
    assert audio_mixer.validate_audio(result["files"]["audio_mix"], result["storyboard"]["total_duration_seconds"]) == []


def test_tone_voice_sets_scene_lengths_from_audio(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, board = make()
    result = pipeline.produce(board, rec, rendering(), tmp_path, provider=narration.ToneProvider(0.3))
    assert result["provider"] == "test_tone" and result["problems"] == [], result["problems"]
    for scene in result["storyboard"]["scenes"]:
        expected = max(3.0, scene["audio_seconds"] + 0.5)
        assert abs(scene["duration_seconds"] - expected) < 0.02
    assert result["timeline"]["publishable"] is False


def test_final_mix_is_valid_and_quiet_enough(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, board = make("chem-001")
    result = pipeline.produce(board, rec, rendering(), tmp_path, provider=narration.ToneProvider(0.3))
    mix = result["files"]["audio_mix"]
    assert audio_mixer.validate_audio(mix, result["storyboard"]["total_duration_seconds"]) == []
    assert abs(result["timeline"]["loudness_lufs"] - (-16)) < 3


def test_music_is_made_and_has_the_right_length(tmp_path):
    if not HAVE_FFMPEG:
        return
    path = audio_mixer.make_music(10, tmp_path / "m.wav")
    with wave.open(str(path), "rb") as handle:
        assert abs(handle.getnframes() / handle.getframerate() - 10) < 0.05


def test_audio_validator_catches_problems(tmp_path):
    if not HAVE_FFMPEG:
        return
    assert audio_mixer.validate_audio(tmp_path / "missing.m4a", 5)
    fake = tmp_path / "fake.m4a"
    fake.write_text("nope")
    assert audio_mixer.validate_audio(fake, 5)
    rec, board = make()
    result = pipeline.produce(board, rec, rendering(), tmp_path, provider=narration.ToneProvider(0.3))
    assert audio_mixer.validate_audio(result["files"]["audio_mix"], 999)


# --- end to end ------------------------------------------------------------------------------------
def test_render_run_with_no_voice_matches_before(tmp_path):
    if not HAVE_FFMPEG:
        return
    saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    try:
        ok, lines = render_scenes.run(str(ROOT), "chem-001", "short", str(tmp_path), "draft")
    finally:
        renderer.QUALITY["draft"] = saved
    assert ok, lines
    base = tmp_path / "chem-001" / "short_explainer"
    assert (base / "subtitles.srt").exists() and (base / "timeline.json").exists()


def test_render_run_with_unavailable_kokoro_still_renders_but_reports_failure(tmp_path):
    if not HAVE_FFMPEG:
        return
    import os
    saved = {k: os.environ.pop(k, None) for k in ("KOKORO_MODEL", "KOKORO_VOICES")}
    renderer_saved = dict(renderer.QUALITY["draft"])
    renderer.QUALITY["draft"] = {"scale": 0.25, "fps": 4}
    try:
        ok, lines = render_scenes.run(str(ROOT), "chem-001", "short", str(tmp_path), "draft", "kokoro")
    finally:
        renderer.QUALITY["draft"] = renderer_saved
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
    assert ok is False
    assert any("could not be used" in line for line in lines)
    assert (tmp_path / "chem-001" / "short_explainer" / "scenes" / "scene_001.mp4").exists()


def test_rendering_config_names_a_known_voice():
    assert rendering()["narration"]["provider"] in ("kokoro", "none")
    assert rendering()["narration"]["voice"]


def test_over_length_video_is_warned_about(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, rendering(), tmp_path, provider=narration.ToneProvider(2.0), music=False)
    assert any(n.startswith("warning:") and "limit" in n for n in result["notes"])


def test_normal_length_video_has_no_length_warning(tmp_path):
    rec, board = make()
    result = pipeline.produce(board, rec, rendering(), tmp_path, "none")
    assert not any(n.startswith("warning:") for n in result["notes"])
