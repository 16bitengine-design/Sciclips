"""Narration voices. Every provider turns text into a WAV file. Providers can be swapped by name.

espeak  - eSpeak NG (installed with apt). Plain but reliable voice. The default.
piper   - Piper neural voice (optional). Sounds better, but the licence of its voices is unresolved for
          commercial use, so it is marked not publishable.
none    - no voice: videos get on-screen text and subtitles only.
"""
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

BASE_WORDS_PER_MINUTE = 150  # matches the timing estimates used when scripts are written


class NarrationError(Exception):
    """Raised when a voice cannot produce audio."""


def wav_duration(path):
    """Length of a PCM WAV file in seconds."""
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    except (wave.Error, EOFError, FileNotFoundError) as err:
        raise NarrationError(f"Cannot read audio file {path}: {err}")


class Provider:
    name = "base"
    publishable = True
    licence_note = ""

    def available(self):
        return True

    def synthesize(self, text, out_path, speed=1.0):
        raise NotImplementedError


class EspeakProvider(Provider):
    name = "espeak"
    licence_note = "eSpeak NG is free software (GPL). Check its terms if you have licensing concerns."

    def __init__(self, voice="en-us", binary=None):
        self.voice = voice
        self.binary = binary or shutil.which("espeak-ng") or shutil.which("espeak")

    def available(self):
        return bool(self.binary)

    def synthesize(self, text, out_path, speed=1.0):
        if not self.binary:
            raise NarrationError("espeak-ng is not installed (sudo apt-get install -y espeak-ng).")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(text)
            text_file = handle.name
        try:
            command = [self.binary, "-v", self.voice, "-s", str(round(BASE_WORDS_PER_MINUTE * speed)),
                       "-w", str(out_path), "-f", text_file]
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise NarrationError("espeak-ng timed out.")
        finally:
            os.unlink(text_file)
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise NarrationError(f"espeak-ng failed: {result.stderr.strip()[:200]}")
        return out_path


class PiperProvider(Provider):
    name = "piper"
    publishable = False
    licence_note = ("The Piper voice models carry an unresolved licence question for commercial use. "
                    "Use for testing only, not for published videos.")

    def __init__(self, binary=None, model=None):
        self.binary = binary or os.environ.get("PIPER_BIN") or shutil.which("piper")
        self.model = model or os.environ.get("PIPER_MODEL")

    def available(self):
        return bool(self.binary and self.model and Path(self.binary).exists() and Path(self.model).exists())

    def synthesize(self, text, out_path, speed=1.0):
        if not self.available():
            raise NarrationError("Piper or its voice file was not found.")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        command = [self.binary, "--model", self.model, "--output_file", str(out_path)]
        if abs(speed - 1.0) > 0.01:
            command += ["--length_scale", f"{1.0 / speed:.3f}"]
        try:
            result = subprocess.run(command, input=text, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise NarrationError("Piper timed out.")
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise NarrationError(f"Piper failed: {result.stderr.strip()[:200]}")
        return out_path


class ToneProvider(Provider):
    """For tests only: writes a quiet tone whose length follows the word count. Never publishable."""
    name = "test_tone"
    publishable = False
    licence_note = "Test tone, not speech."

    def __init__(self, seconds_per_word=0.4, rate=22050):
        self.seconds_per_word = seconds_per_word
        self.rate = rate

    def synthesize(self, text, out_path, speed=1.0):
        import math
        import struct
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


def get_provider(name, voice="en-us"):
    """Provider for a name, or None for 'none'. Unknown names raise NarrationError."""
    if name in (None, "", "none"):
        return None
    if name == "espeak":
        return EspeakProvider(voice=voice)
    if name == "piper":
        return PiperProvider()
    raise NarrationError(f"Unknown narration provider '{name}'. Use espeak, piper or none.")
