import json
import math
import os
import re
import shutil
import struct
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from audio import narration, pipeline, voice_style  # noqa: E402
from content.script_generator import generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402
import voice_samples  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
OK = {"status": "passed_automated_checks"}


class Style:
    def __init__(self, values):
        self.values = list(values)

    def __mul__(self, weight):
        return Style(v * weight for v in self.values)

    def __add__(self, other):
        return Style(a + b for a, b in zip(self.values, other.values))


class FakeEngine:
    def __init__(self, missing=()):
        self.calls = []
        self.missing = missing

    def get_voice_style(self, name):
        if name in self.missing:
            raise KeyError(name)
        return Style([1.0, 10.0 if name.startswith("am") else 20.0])

    def create(self, text, voice, speed, lang):
        self.calls.append((voice, speed))
        rate = 24000
        seconds = max(0.6, len(text.split()) * 0.3 / speed)
        return [0.25 * math.sin(2 * math.pi * 200 * i / rate) for i in range(int(seconds * rate))], rate


def rendering():
    return json.loads((ROOT / "config" / "rendering.json").read_text())


def make(topic="chem-001"):
    rec = load_topic_record(str(ROOT), topic)
    return rec, generate_storyboard(generate_script(rec, "short", "explainer", rendering(), OK), rec, rendering())


def tone_wav(path, hz=200, seconds=1.0, rate=24000):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * hz * i / rate)))
                                    for i in range(int(seconds * rate))))
    return path


def dominant_hz(path):
    """Pitch of a clean tone from its zero crossings."""
    with wave.open(str(path), "rb") as handle:
        rate, frames = handle.getframerate(), handle.readframes(handle.getnframes())
    samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
    crossings = sum(1 for a, b in zip(samples, samples[1:]) if a < 0 <= b)
    return crossings / (len(samples) / rate)


# --- the profiles ---------------------------------------------------------------------
def test_every_profile_is_a_valid_male_blend():
    voices = voice_style.load_voices()
    assert len(voices["profiles"]) >= 3
    for name in voices["profiles"]:
        profile = voice_style.get_profile(name, voices)
        assert profile["blend"] and all(w > 0 for w in profile["blend"].values())
        assert all(re.fullmatch(r"[ab]m_[a-z]+", voice) for voice in profile["blend"]), name
        assert 0.8 <= profile["speed"] <= 1.05
        assert 0.9 <= profile["post"]["pitch"] <= 1.0


def test_default_profile_exists_in_the_config():
    assert rendering()["narration"]["profile"] in voice_style.load_voices()["profiles"]


def test_unknown_profile_is_refused_with_a_helpful_message():
    try:
        voice_style.get_profile("nope")
        assert False
    except voice_style.VoiceStyleError as err:
        assert "smooth_american" in str(err)


def test_profile_gets_the_shared_radio_chain():
    post = voice_style.get_profile("deep_american")["post"]
    assert post["highpass_hz"] == 70 and post["pitch"] == 0.96 and post["compress"] is True


def test_blend_weights_are_normalised():
    assert abs(sum(voice_style.normalised_blend({"a": 3, "b": 1}).values()) - 1) < 1e-9


def test_blend_style_is_a_weighted_average():
    engine = FakeEngine()
    style = voice_style.blend_style(engine, {"am_michael": 0.6, "bm_george": 0.4})
    assert abs(style.values[0] - 1.0) < 1e-9
    assert abs(style.values[1] - (0.6 * 10 + 0.4 * 20)) < 1e-9


# --- the radio filter ---------------------------------------------------------------------
def test_filter_chain_contents():
    chain = voice_style.build_filter({"highpass_hz": 70, "warmth_db": 3, "presence_db": 1.5, "deess_db": -3,
                                      "compress": True, "pitch": 0.96}, 24000)
    for part in ("highpass=f=70", "asetrate=23040", "aresample=24000", "atempo=1.04167", "equalizer=f=140",
                 "equalizer=f=3000", "equalizer=f=7500", "acompressor", "alimiter"):
        assert part in chain, part


def test_no_pitch_change_means_no_pitch_filters():
    assert "asetrate" not in voice_style.build_filter({"pitch": 1.0}, 24000)


def test_radio_sound_lowers_the_pitch_and_keeps_the_length(tmp_path):
    if not HAVE_FFMPEG:
        return
    source = tone_wav(tmp_path / "in.wav", 200, 1.5)
    out = voice_style.apply_radio_sound(source, tmp_path / "out.wav", {"pitch": 0.9, "highpass_hz": 70})
    assert abs(narration.wav_duration(out) - 1.5) < 0.08
    ratio = dominant_hz(out) / dominant_hz(source)
    assert 0.86 < ratio < 0.94, ratio


def test_radio_sound_never_clips(tmp_path):
    if not HAVE_FFMPEG:
        return
    loud = tmp_path / "loud.wav"
    with wave.open(str(loud), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"".join(struct.pack("<h", int(32000 * math.sin(2 * math.pi * 300 * i / 24000)))
                                    for i in range(24000)))
    out = voice_style.apply_radio_sound(loud, tmp_path / "o.wav", voice_style.get_profile("smooth_american")["post"])
    with wave.open(str(out), "rb") as handle:
        data = handle.readframes(handle.getnframes())
    peak = max(abs(v) for v in struct.unpack("<" + "h" * (len(data) // 2), data))
    assert peak < 32767 * 0.95


# --- using a profile ------------------------------------------------------------------------------
def test_kokoro_speaks_with_the_blended_style(tmp_path):
    engine = FakeEngine()
    provider = narration.KokoroProvider(engine=engine, blend={"am_michael": 0.5, "bm_george": 0.5})
    provider.synthesize("hello there friend", tmp_path / "a.wav", 0.95)
    voice, speed = engine.calls[0]
    assert isinstance(voice, Style) and speed == 0.95 and provider.fell_back is False


def test_missing_voice_in_a_blend_is_noticed(tmp_path):
    engine = FakeEngine(missing=("bm_george",))
    provider = narration.KokoroProvider(engine=engine, blend={"am_michael": 0.5, "bm_george": 0.5})
    provider.synthesize("hello", tmp_path / "a.wav")
    assert provider.fell_back is True


def test_pipeline_uses_the_profile_end_to_end(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, board = make()
    provider = narration.KokoroProvider(engine=FakeEngine(), blend=voice_style.get_profile("smooth_american")["blend"])
    result = pipeline.produce(board, rec, rendering(), tmp_path, provider=provider)
    assert result["provider"] == "kokoro" and result["problems"] == [], result["problems"]
    assert (tmp_path / "audio" / "raw").is_dir()
    assert result["timeline"]["voice_profile"] == rendering()["narration"]["profile"]


def test_pipeline_applies_profile_speed(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, board = make()
    engine = FakeEngine()
    provider = narration.KokoroProvider(engine=engine)
    pipeline.produce(board, rec, rendering(), tmp_path, provider=provider)
    expected = rendering()["narration"]["speaking_speed"] * voice_style.get_profile(
        rendering()["narration"]["profile"])["speed"]
    assert all(abs(speed - expected) < 1e-9 for _, speed in engine.calls)


def test_profile_can_be_chosen_with_an_environment_setting(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, board = make()
    saved = os.environ.get("VOICE_PROFILE")
    os.environ["VOICE_PROFILE"] = "british_broadcaster"
    try:
        engine = FakeEngine()
        result = pipeline.produce(board, rec, rendering(), tmp_path, provider=narration.KokoroProvider(engine=engine))
    finally:
        if saved is None:
            del os.environ["VOICE_PROFILE"]
        else:
            os.environ["VOICE_PROFILE"] = saved
    assert result["timeline"]["voice_profile"] == "british_broadcaster"
    expected = voice_style.get_profile("british_broadcaster")["speed"]
    assert abs(engine.calls[0][1] - expected) < 1e-9


def test_unknown_profile_is_reported_as_a_problem(tmp_path):
    rec, board = make()
    cfg = rendering()
    cfg["narration"]["profile"] = "does_not_exist"
    result = pipeline.produce(board, rec, cfg, tmp_path, "none")
    assert any("could not be loaded" in p for p in result["problems"])


def test_a_blend_that_cannot_be_built_is_reported_not_hidden(tmp_path):
    if not HAVE_FFMPEG:
        return
    rec, board = make()
    provider = narration.KokoroProvider(engine=FakeEngine(missing=("am_michael",)),
                                        blend={"am_michael": 1.0})
    result = pipeline.produce(board, rec, rendering(), tmp_path, provider=provider)
    assert any("could not be built" in p for p in result["problems"])


# --- the sample maker -----------------------------------------------------------------------------
def test_voice_samples_are_made_for_every_profile(tmp_path):
    if not HAVE_FFMPEG:
        return
    ok, lines = voice_samples.run(str(ROOT), tmp_path, provider_factory=lambda blend: narration.KokoroProvider(
        engine=FakeEngine(), blend=blend))
    assert ok, lines
    names = set(voice_style.load_voices()["profiles"])
    for name in names:
        assert (tmp_path / f"{name}.m4a").exists() and (tmp_path / f"{name}_plain.m4a").exists()
    assert "Listen to them" in (tmp_path / "READ_ME.txt").read_text()


def test_voice_samples_can_be_limited_to_some_profiles(tmp_path):
    if not HAVE_FFMPEG:
        return
    ok, lines = voice_samples.run(str(ROOT), tmp_path, ["transatlantic"], lambda blend: narration.KokoroProvider(
        engine=FakeEngine(), blend=blend))
    assert ok and len(lines) == 1 and (tmp_path / "transatlantic.m4a").exists()
    assert not (tmp_path / "deep_american.m4a").exists()


def test_voice_samples_fail_clearly_without_kokoro(tmp_path):
    saved = {k: os.environ.pop(k, None) for k in ("KOKORO_MODEL", "KOKORO_VOICES")}
    try:
        ok, lines = voice_samples.run(str(ROOT), tmp_path, ["smooth_american"])
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
    assert not ok and "not installed" in lines[0]


def test_voice_samples_unknown_profile_is_reported(tmp_path):
    ok, lines = voice_samples.run(str(ROOT), tmp_path, ["nope"], lambda blend: None)
    assert not ok and "Unknown voice profile" in lines[0]
