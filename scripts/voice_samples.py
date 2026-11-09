"""Makes short audio samples of every voice profile so you can listen and choose.

Writes output/voice-samples/<profile>.m4a (with the radio sound) and <profile>_plain.m4a (without it).
Nothing here is published. Set VOICE_PROFILES to a comma-separated list to hear only some profiles.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio import narration, voice_style  # noqa: E402
from audio.speakable import load_pronunciations, speakable  # noqa: E402


def _to_m4a(wav, out):
    result = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "128k",
                             str(out)], capture_output=True, text=True)
    if result.returncode != 0:
        raise narration.NarrationError(f"Could not save {out}: {result.stderr.strip()[-200:]}")


def run(root, out_dir, names=None, provider_factory=None):
    """Returns (ok, report_lines). provider_factory(blend) -> provider; the default is real Kokoro."""
    voices = voice_style.load_voices(Path(root) / "config" / "voices.json")
    factory = provider_factory or (lambda blend: narration.KokoroProvider(blend=blend))
    pron = load_pronunciations(Path(root) / "config" / "pronunciations.json")
    text = speakable(voices["sample_text"], pron)
    wanted = names or sorted(voices["profiles"])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lines, ok = [], True
    for name in wanted:
        try:
            profile = voice_style.get_profile(name, voices)
            provider = factory(profile["blend"])
            if not provider.available():
                raise narration.NarrationError("Kokoro is not installed or its voice files were not found.")
            raw = out / "work" / f"{name}_raw.wav"
            provider.synthesize(text, raw, profile["speed"])
            if provider.fell_back:
                raise narration.NarrationError("the blend could not be built (check the voice names).")
            styled = voice_style.apply_radio_sound(raw, out / "work" / f"{name}.wav", profile["post"])
            _to_m4a(styled, out / f"{name}.m4a")
            _to_m4a(raw, out / f"{name}_plain.m4a")
            lines.append(f"{name}: OK - {profile['description']}")
        except (narration.NarrationError, voice_style.VoiceStyleError) as err:
            lines.append(f"{name}: FAILED - {err}")
            ok = False
    (out / "READ_ME.txt").write_text(
        "Voice samples\n\nEach profile has two files: NAME.m4a (the voice with the radio sound) and NAME_plain.m4a "
        "(the same voice without it).\nListen to them, pick one, then set \"profile\" in the narration section of "
        "config/rendering.json to its name.\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return ok, lines


def main():
    chosen = [n.strip() for n in os.environ.get("VOICE_PROFILES", "").split(",") if n.strip()] or None
    ok, lines = run(".", os.environ.get("OUTPUT_DIR", "output") + "/voice-samples", chosen)
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Voice samples\n\n```\n" + text + "\n```\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
