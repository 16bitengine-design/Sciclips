"""audio: merged module (was 6 files: audio_mixer, narration, speakable, subtitles, voice_style, pipeline).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""
import copy
import importlib.util
import json
import math
import os
import re
import shutil
import struct
import subprocess
import textwrap
import wave
from array import array
from pathlib import Path
from animation.two_d import themes


# ============================================================================
# from audio/audio_mixer.py
# ============================================================================
# Builds the narration track, an original background pad, the final mix and checks them (FFmpeg).






SAMPLE_RATE = 44100
TARGET_LUFS = -16.0


class AudioError(Exception):
    """Raised when audio cannot be built."""


def _run(command):
    if shutil.which("ffmpeg") is None:
        raise AudioError("FFmpeg was not found. Install it (sudo apt-get install -y ffmpeg).")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioError(f"FFmpeg failed: {result.stderr.strip()[-300:]}")
    return result


def build_narration_track(items, out_path):
    """Join scene audio files, each padded or cut to its scene length. items = [(wav_path, seconds)]."""
    if not items:
        raise AudioError("No scene audio to join.")
    command = ["ffmpeg", "-y", "-loglevel", "error"]
    filters, labels = [], []
    for i, (path, seconds) in enumerate(items):
        command += ["-i", str(path)]
        filters.append(f"[{i}:a]aresample={SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=mono,"
                       f"apad=whole_dur={seconds:.3f},atrim=0:{seconds:.3f},asetpts=N/SR/TB[a{i}]")
        labels.append(f"[a{i}]")
    filters.append("".join(labels) + f"concat=n={len(items)}:v=0:a=1[out]")
    command += ["-filter_complex", ";".join(filters), "-map", "[out]", str(out_path)]
    _run(command)
    return Path(out_path)


def make_music(seconds, out_path):
    """A soft, original background pad made from four sine tones. Created here, so no licence issues."""
    seconds = max(4.0, float(seconds))
    tones = [110.0, 164.81, 220.0, 261.63]
    command = ["ffmpeg", "-y", "-loglevel", "error"]
    for freq in tones:
        command += ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate={SAMPLE_RATE}:duration={seconds:.3f}"]
    chain = ("amix=inputs=4:normalize=0,lowpass=f=900,tremolo=f=0.15:d=0.4,volume=0.6,"
             f"afade=t=in:d=2,afade=t=out:st={seconds - 3:.3f}:d=3")
    command += ["-filter_complex", "[0:a][1:a][2:a][3:a]" + chain + "[out]", "-map", "[out]", "-ac", "1",
                str(out_path)]
    _run(command)
    return Path(out_path)


def mix(narration_wav, out_m4a, music_wav=None, music_db=-26.0, lufs=TARGET_LUFS):
    """Mix narration with optional music, normalise loudness and save as AAC."""
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(narration_wav)]
    norm = f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    if music_wav:
        command += ["-i", str(music_wav), "-filter_complex",
                    f"[1:a]volume={music_db}dB[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,{norm}[out]",
                    "-map", "[out]"]
    else:
        command += ["-af", norm]
    command += ["-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "aac", "-b:a", "160k", str(out_m4a)]
    _run(command)
    return Path(out_m4a)


def measure_loudness(path):
    """Integrated loudness in LUFS, or None if it cannot be measured."""
    result = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                             f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                            capture_output=True, text=True)
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr, re.S)
    if not match:
        return None
    try:
        return float(json.loads(match.group(0))["input_i"])
    except (ValueError, KeyError):
        return None


def validate_audio(path, duration, tolerance=0.4, lufs=TARGET_LUFS, lufs_tolerance=3.0):
    """Returns a list of problems; empty means the audio looks fine."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return [f"Audio file missing or empty: {path}"]
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return ["Cannot read audio file."]
    info = json.loads(result.stdout)
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if audio is None:
        return ["No audio stream."]
    problems = []
    if audio.get("codec_name") != "aac":
        problems.append(f"Audio codec is {audio.get('codec_name')}, expected aac.")
    actual = float(info.get("format", {}).get("duration") or 0)
    if abs(actual - duration) > tolerance:
        problems.append(f"Audio is {actual:.2f} s, expected about {duration:.2f} s.")
    loudness = measure_loudness(path)
    if loudness is None:
        problems.append("Could not measure loudness.")
    elif abs(loudness - lufs) > lufs_tolerance:
        problems.append(f"Loudness is {loudness:.1f} LUFS, expected about {lufs:.0f}.")
    return problems


# ============================================================================
# from audio/narration.py
# ============================================================================
# Narration voices. A voice turns text into a WAV file. Voices are chosen by name.









class NarrationError(Exception):
    """Raised when a voice cannot produce audio."""


def wav_duration(path):
    """Length of a PCM WAV file in seconds."""
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    except (wave.Error, EOFError, FileNotFoundError) as err:
        raise NarrationError(f"Cannot read audio file {path}: {err}")


def write_wav(path, samples, sample_rate):
    """Save samples (floats from -1 to 1, as a list or array) as a 16-bit mono WAV. No extra packages needed."""
    values = samples.tolist() if hasattr(samples, "tolist") else list(samples)
    if not values:
        raise NarrationError("The voice returned no audio.")
    if any(not math.isfinite(v) for v in values):
        raise NarrationError("The voice returned invalid audio values.")
    pcm = array("h", (max(-32768, min(32767, int(v * 32767))) for v in values))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())
    return Path(path)


class Provider:
    name = "base"
    publishable = True
    licence_note = ""

    def available(self):
        return True

    def synthesize(self, text, out_path, speed=1.0):
        raise NotImplementedError


class KokoroProvider(Provider):
    name = "kokoro"
    publishable = True
    licence_note = ("Kokoro-82M weights are released under Apache 2.0 and the kokoro-onnx code under MIT. "
                    "Read the current model card before earning money from videos: "
                    "https://huggingface.co/hexgrad/Kokoro-82M")
    FALLBACK_VOICE = "af_sarah"  # the voice used in Kokoro's own example

    def __init__(self, model=None, voices=None, voice="af_heart", language="en-us", engine=None, blend=None):
        self.model = model or os.environ.get("KOKORO_MODEL")
        self.voices_file = voices or os.environ.get("KOKORO_VOICES")
        self.voice = voice
        self.language = language
        self.blend = blend  # {"voice_name": weight, ...} makes one voice out of several
        self.fell_back = False  # True if the blend could not be built and a plain voice was used
        self._engine = engine  # a stand-in can be passed in for tests

    def available(self):
        if self._engine is not None:
            return True
        files = bool(self.model and self.voices_file and Path(self.model).exists()
                     and Path(self.voices_file).exists())
        return files and importlib.util.find_spec("kokoro_onnx") is not None

    def _load(self):
        if self._engine is None:
            from kokoro_onnx import Kokoro
            self._engine = Kokoro(self.model, self.voices_file)
        return self._engine

    def synthesize(self, text, out_path, speed=1.0):
        if not self.available():
            raise NarrationError("Kokoro is not installed or its voice files were not found.")
        try:
            engine = self._load()
        except Exception as err:  # the library may raise many kinds of error while loading
            raise NarrationError(f"Kokoro could not start: {err}")
        last_error = None
        choices = []
        if self.blend:
            choices.append("blend")
        choices += list(dict.fromkeys([self.voice, self.FALLBACK_VOICE]))
        for choice in choices:
            try:
                if choice == "blend":
                    pass
                    voice = blend_style(engine, self.blend)
                else:
                    voice = choice
                samples, rate = engine.create(text, voice=voice, speed=speed, lang=self.language)
                if self.blend and choice != "blend":
                    self.fell_back = True
                return write_wav(out_path, samples, rate)
            except NarrationError:
                raise
            except Exception as err:
                last_error = err
        raise NarrationError(f"Kokoro failed: {last_error}")


class ToneProvider(Provider):
    """For tests only: writes a quiet tone whose length follows the word count. Never publishable."""
    name = "test_tone"
    publishable = False
    licence_note = "Test tone, not speech."

    def __init__(self, seconds_per_word=0.4, rate=22050):
        self.seconds_per_word = seconds_per_word
        self.rate = rate

    def synthesize(self, text, out_path, speed=1.0):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        seconds = max(0.5, len(text.split()) * self.seconds_per_word / speed)
        frames = int(seconds * self.rate)
        with wave.open(str(out_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.rate)
            handle.writeframes(b"".join(
                struct.pack("<h", int(6000 * math.sin(2 * math.pi * 220 * i / self.rate))) for i in range(frames)))
        return out_path


def get_provider(name, voice="af_heart", language="en-us", blend=None):
    """Provider for a name, or None for 'none'. Unknown names raise NarrationError."""
    if name in (None, "", "none"):
        return None
    if name == "kokoro":
        return KokoroProvider(voice=voice, language=language, blend=blend)
    raise NarrationError(f"Unknown narration provider '{name}'. Use kokoro or none.")


# ============================================================================
# from audio/speakable.py
# ============================================================================
# Turns written text into text a voice can say well (equations, units and chemical formulas).




DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "config.json"      # section "pronunciations"
POWERS = {"2": "squared", "3": "cubed"}


def load_pronunciations(path=None):
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        return {"phrases": {}, "words": {}}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if path.name == "config.json":
        data = data.get("pronunciations", {})
    return {"phrases": data.get("phrases", {}), "words": data.get("words", {})}


def _power(match):
    base, exponent = match.group(1), match.group(2)
    if exponent in POWERS:
        spoken = POWERS[exponent]
    elif exponent.startswith("-"):
        spoken = f"to the power minus {exponent[1:]}"
    else:
        spoken = f"to the power {exponent}"
    return f"{base} {spoken}"


def _spell_formula(match):
    token = match.group(0)
    if not any(ch.isdigit() for ch in token):
        return token
    return " ".join(re.findall(r"[A-Z][a-z]?|\d+", token))


def speakable(text, pronunciations=None):
    """Return the text rewritten for speech. The written text itself is never changed."""
    pron = pronunciations if pronunciations is not None else load_pronunciations()
    out = text
    for phrase in sorted(pron["phrases"], key=len, reverse=True):
        out = re.sub(r"(?<![\w^])" + re.escape(phrase) + r"(?![\w^])", pron["phrases"][phrase], out)
    for word in sorted(pron["words"], key=len, reverse=True):
        out = re.sub(r"\b" + re.escape(word) + r"\b", pron["words"][word], out)
    out = re.sub(r"\b(?:[A-Z][a-z]?\d*){2,}\b", _spell_formula, out)
    out = re.sub(r"(\w)\^(-?\d+)", _power, out)
    if "=" in out:
        out = re.sub(r"\b[a-z]\b", lambda m: m.group(0).upper(), out)
    for symbol, spoken in (("->", " gives "), (" = ", " equals "), (" / ", " divided by "),
                           (" * ", " times "), (" + ", " plus ")):
        out = out.replace(symbol, spoken)
    return " ".join(out.split())


# ============================================================================
# from audio/subtitles.py
# ============================================================================
# Builds subtitle cues from a timed storyboard and writes them as SRT and ASS files.




def _clock_srt(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _clock_ass(seconds):
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _fits(text, max_chars, max_lines):
    return len(textwrap.wrap(text, max_chars) or [text]) <= max_lines


def _balanced(text, max_chars, max_lines):
    """Split one long sentence into cues of similar size, each fitting max_lines lines."""
    words = text.split()
    parts = -(-len(textwrap.wrap(text, max_chars)) // max_lines)
    while True:
        size = -(-len(words) // parts)
        pieces = [" ".join(words[i:i + size]) for i in range(0, len(words), size)]
        if all(_fits(p, max_chars, max_lines) for p in pieces):
            return pieces
        parts += 1


def _chunks(text, max_chars, max_lines):
    """Split text into pieces that wrap to at most max_lines lines of max_chars, preferring sentence ends."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        trial = (current + " " + sentence).strip()
        if current and not _fits(trial, max_chars, max_lines):
            pieces.append(current)
            current = ""
            trial = sentence
        if _fits(trial, max_chars, max_lines):
            current = trial
            continue
        pieces.extend(_balanced(trial, max_chars, max_lines))
        current = ""
    if current:
        pieces.append(current)
    return pieces


def build_cues(scenes, max_chars=34, max_lines=2):
    """One cue per piece of narration. `scenes` need start_seconds, end_seconds and narration."""
    cues = []
    for scene in scenes:
        text = scene.get("narration", "").strip()
        if not text:
            continue
        pieces = _chunks(text, max_chars, max_lines)
        start = scene["start_seconds"] + 0.10
        end = max(start + 0.5, scene["end_seconds"] - 0.20)
        total = sum(len(p) for p in pieces)
        cursor = start
        for piece in pieces:
            span = (end - start) * len(piece) / total
            lines = textwrap.wrap(piece, max_chars) or [piece]
            cues.append({"index": len(cues) + 1, "start": round(cursor, 3), "end": round(cursor + span, 3),
                         "text": "\n".join(lines), "scene_number": scene["scene_number"]})
            cursor += span
    return cues


def to_srt(cues):
    blocks = [f"{c['index']}\n{_clock_srt(c['start'])} --> {_clock_srt(c['end'])}\n{c['text']}\n" for c in cues]
    return "\n".join(blocks)


def to_ass(cues, width, height, portrait, font="DejaVu Sans", outlined=False):
    """An ASS file with a readable style. The bottom margin keeps captions above the phone interface."""
    font_size = round(height * (0.030 if portrait else 0.045))
    margin_v = round(height * (0.085 if portrait else 0.045))
    if outlined:
        style = (f"Style: Default,{font},{font_size},&H00FFFFFF,&H000000FF,&H003A0E16,&H00000000,-1,0,0,0,100,100,0,0,1,"
                 f"{round(font_size * 0.16)},{round(font_size * 0.07)},2,{round(width * 0.06)},{round(width * 0.06)},"
                 f"{margin_v},1\n\n")
    else:
        style = (f"Style: Default,{font},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,"
                 f"{round(font_size * 0.25)},0,2,{round(width * 0.06)},{round(width * 0.06)},{margin_v},1\n\n")
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        + style +
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for cue in cues:
        text = cue["text"].replace("{", "(").replace("}", ")").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{_clock_ass(cue['start'])},{_clock_ass(cue['end'])},Default,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"


# ============================================================================
# from audio/voice_style.py
# ============================================================================
# Voice profiles: blended voices plus a 'radio' sound added with FFmpeg.






VOICE_STYLE_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "config.json"      # section "voices"


class VoiceStyleError(Exception):
    """Raised for a missing profile or a failed audio filter."""


def load_voices(path=None):
    path = Path(path) if path else VOICE_STYLE_DEFAULT_PATH
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data["voices"] if path.name == "config.json" else data


def get_profile(name, voices=None):
    """Profile settings for a name, with the shared radio chain filled in. Raises VoiceStyleError."""
    voices = voices or load_voices()
    profiles = voices.get("profiles", {})
    if name not in profiles:
        raise VoiceStyleError(f"Unknown voice profile '{name}'. Known profiles: {', '.join(sorted(profiles))}")
    profile = dict(profiles[name])
    profile["name"] = name
    profile["post"] = {**voices.get("radio_chain", {}), **profile.get("post", {})}
    blend = profile.get("blend") or {}
    if not blend or any(w <= 0 for w in blend.values()):
        raise VoiceStyleError(f"Profile '{name}' needs a blend with positive weights.")
    return profile


def normalised_blend(blend):
    total = float(sum(blend.values()))
    return {name: weight / total for name, weight in blend.items()}


def blend_style(engine, blend):
    """Weighted average of the voice styles, as one style the engine can speak with."""
    parts = normalised_blend(blend)
    style = None
    for name, weight in parts.items():
        piece = engine.get_voice_style(name) * weight
        style = piece if style is None else style + piece
    return style


def _rate(path):
    with wave.open(str(path), "rb") as handle:
        return handle.getframerate()


def build_filter(post, sample_rate):
    """The FFmpeg filter chain for the radio sound. Pitch below 1 lowers the voice without changing its speed."""
    chain = []
    if post.get("highpass_hz"):
        chain.append(f"highpass=f={post['highpass_hz']}")
    pitch = float(post.get("pitch", 1.0))
    if abs(pitch - 1.0) > 0.001:
        chain += [f"asetrate={round(sample_rate * pitch)}", f"aresample={sample_rate}", f"atempo={1.0 / pitch:.5f}"]
    if post.get("warmth_db"):
        chain.append(f"equalizer=f=140:t=o:w=1.5:g={post['warmth_db']}")
    if post.get("presence_db"):
        chain.append(f"equalizer=f=3000:t=o:w=1.5:g={post['presence_db']}")
    if post.get("deess_db"):
        chain.append(f"equalizer=f=7500:t=o:w=1:g={post['deess_db']}")
    if post.get("compress"):
        chain.append("acompressor=threshold=-20dB:ratio=3:attack=8:release=120:makeup=4")
    chain.append("alimiter=limit=0.9:level=0")
    return ",".join(chain)


def apply_radio_sound(in_path, out_path, post):
    """Filter one WAV file. Returns the output path."""
    if shutil.which("ffmpeg") is None:
        raise VoiceStyleError("FFmpeg was not found. Install it (sudo apt-get install -y ffmpeg).")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(in_path), "-af", build_filter(post, _rate(in_path)),
               str(out_path)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not Path(out_path).exists():
        raise VoiceStyleError(f"The radio filter failed: {result.stderr.strip()[-300:]}")
    return Path(out_path)


# ============================================================================
# from audio/pipeline.py
# ============================================================================
# Narration, timing, subtitles and audio mix for one storyboard.









PADDING_SECONDS = 0.5
MIN_SCENE_SECONDS = 3.0


def _candidates(requested, provider_object):
    """Voices to try, in order. The last resort is no voice, never a robotic one."""
    if provider_object is not None:
        return [provider_object]
    return [] if requested in (None, "", "none") else [requested]


def _speak_all(provider, scenes, rendering, out_dir, pronunciations, speed_factor=1.0, post=None):
    """Speak every scene with one provider. Returns {scene_number: (path, seconds)}; raises NarrationError."""
    speed = float(rendering.get("narration", {}).get("speaking_speed", 1.0)) * speed_factor
    results = {}
    for scene in scenes:
        text = scene.get("narration", "").strip()
        if not text:
            continue
        number = scene["scene_number"]
        final = Path(out_dir) / "audio" / f"scene_{number:03d}.wav"
        raw = Path(out_dir) / "audio" / "raw" / f"scene_{number:03d}.wav" if post else final
        provider.synthesize(speakable(text, pronunciations), raw, speed)
        if post:
            try:
                apply_radio_sound(raw, final, post)
            except VoiceStyleError as err:
                raise NarrationError(str(err))
        results[number] = (final, wav_duration(final))
    return results


def apply_timing(storyboard, audio=None):
    """A copy of the storyboard with scene lengths and start/end times filled in."""
    timed = copy.deepcopy(storyboard)
    clock = 0.0
    for scene in timed["scenes"]:
        if audio and scene["scene_number"] in audio:
            path, seconds = audio[scene["scene_number"]]
            scene["duration_seconds"] = round(max(MIN_SCENE_SECONDS, seconds + PADDING_SECONDS), 2)
            scene["audio_file"] = str(path)
            scene["audio_seconds"] = round(seconds, 2)
        scene["start_seconds"] = round(clock, 2)
        clock += scene["duration_seconds"]
        scene["end_seconds"] = round(clock, 2)
    timed["total_duration_seconds"] = round(clock, 2)
    return timed


def produce(storyboard, record, rendering, out_dir, provider_name="none", provider=None, music=True):
    """Make audio, timing and subtitles. Returns a dict: storyboard, provider, notes, problems, files."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pronunciations = load_pronunciations()
    notes, problems = [], []
    settings = rendering.get("narration", {})
    voice, language = settings.get("voice", "af_heart"), settings.get("language", "en-us")
    scenes = storyboard["scenes"]
    profile, profile_name = None, os.environ.get("VOICE_PROFILE") or settings.get("profile")
    if profile_name:
        try:
            profile = get_profile(profile_name)
        except (VoiceStyleError, FileNotFoundError, KeyError) as err:
            notes.append(f"Voice profile problem: {err}")
            problems.append(f"The voice profile '{profile_name}' could not be loaded, so the standard voice was used.")
            profile_name = None

    audio, used, used_object = None, "none", None
    for candidate in _candidates(provider_name, provider):
        try:
            impl = candidate if isinstance(candidate, Provider) else get_provider(
                candidate, voice, language, profile["blend"] if profile else None)
        except NarrationError as err:
            notes.append(str(err))
            continue
        if not impl.available():
            notes.append(f"{impl.name}: not available here (is it installed, and are its voice files downloaded?).")
            continue
        try:
            audio = _speak_all(impl, scenes, rendering, out_dir, pronunciations,
                               profile["speed"] if profile else 1.0, profile["post"] if profile else None)
            used, used_object = impl.name, impl
            if getattr(impl, "fell_back", False):
                problems.append(f"The voice profile '{profile_name}' could not be built, so a standard voice was "
                                "used instead.")
            break
        except NarrationError as err:
            notes.append(f"{impl.name}: failed ({err}).")
            audio = None

    requested_name = provider.name if provider is not None else (provider_name or "none")
    if requested_name != "none" and used == "none":
        problems.append(f"The requested voice '{requested_name}' could not be used, so this video has subtitles "
                        "only. No fallback voice is used.")

    timed = apply_timing(storyboard, audio)
    limit = rendering[timed["format"]]["max_duration_seconds"]
    if timed["total_duration_seconds"] > limit:
        notes.append(f"warning: with this voice the video runs {timed['total_duration_seconds']:.0f} s, over the "
                     f"{limit} s limit for {timed['format']} videos. Shorten the topic text or use a faster voice.")
    files = {}
    cues = build_cues(timed["scenes"], 34 if timed["format"] == "short" else 52)
    width, height = (int(v) for v in timed["resolution"].split("x"))
    srt = out_dir / "subtitles.srt"
    ass = out_dir / "subtitles.ass"
    srt.write_text(to_srt(cues), encoding="utf-8")
    theme = themes.current()
    styled = theme.name != "classic"
    ass.write_text(to_ass(cues, width, height, timed["format"] == "short",
                                    theme.caption_font if styled else "DejaVu Sans", styled), encoding="utf-8")
    files.update({"srt": str(srt), "ass": str(ass)})

    loudness = None
    if audio:
        try:
            # Scenes without narration still take time, so build the track on the full timeline.
            track_items = []
            for s in timed["scenes"]:
                if s["scene_number"] in audio:
                    track_items.append((audio[s["scene_number"]][0], s["duration_seconds"]))
                else:
                    silent = out_dir / "audio" / f"silence_{s['scene_number']:03d}.wav"
                    _silence(silent, s["duration_seconds"])
                    track_items.append((silent, s["duration_seconds"]))
            track = build_narration_track(track_items, out_dir / "audio" / "narration_track.wav")
            music_path = None
            if music and rendering.get("narration", {}).get("music", True):
                music_path = make_music(timed["total_duration_seconds"], out_dir / "audio" / "music.wav")
            mixed = mix(track, out_dir / "audio" / "audio_mix.m4a", music_path,
                                    float(rendering.get("narration", {}).get("music_volume_db", -26)))
            problems += validate_audio(mixed, timed["total_duration_seconds"])
            loudness = measure_loudness(mixed)
            files["audio_mix"] = str(mixed)
        except AudioError as err:
            problems.append(f"Audio mix failed: {err}")

    impl = used_object
    timeline = {
        "provider": used, "requested": requested_name, "voice_profile": profile_name if used != "none" else None,
        "publishable": True if impl is None else impl.publishable,
        "licence_note": "" if impl is None else impl.licence_note,
        "total_duration_seconds": timed["total_duration_seconds"],
        "loudness_lufs": loudness, "notes": notes, "problems": problems,
        "scenes": [{k: s.get(k) for k in ("scene_number", "section_id", "start_seconds", "end_seconds",
                                          "audio_file", "audio_seconds")} for s in timed["scenes"]],
        "subtitle_cues": len(cues),
    }
    (out_dir / "timeline.json").write_text(json.dumps(timeline, indent=2) + "\n", encoding="utf-8")
    (out_dir / "storyboard_timed.json").write_text(json.dumps(timed, indent=2, ensure_ascii=False) + "\n",
                                                   encoding="utf-8")
    files["timeline"] = str(out_dir / "timeline.json")
    return {"storyboard": timed, "provider": used, "notes": notes, "problems": problems, "files": files,
            "cues": cues, "timeline": timeline}


def _silence(path, seconds, rate=22050):
    import wave
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
