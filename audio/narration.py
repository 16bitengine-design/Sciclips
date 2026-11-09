"""Narration voices. A voice turns text into a WAV file. Voices are chosen by name.

kokoro - Kokoro-82M, a natural-sounding open voice model (Apache 2.0 weights) run on the CPU through
         the kokoro-onnx package. This is the project's voice.
none   - no voice: videos get on-screen text and subtitles only.

There is deliberately no robotic fallback voice. If Kokoro cannot run, the video is made with
subtitles only and the run reports a problem, so the failure is never hidden.
"""
import importlib.util
import math
import os
import struct
import wave
from array import array
from pathlib import Path


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
                    from audio.voice_style import blend_style
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
