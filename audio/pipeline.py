"""Narration, timing, subtitles and audio mix for one storyboard.

Order of work: speak every scene, set each scene's length from its audio, write subtitles from the new timing,
then build the narration track and the final mix. If a voice fails, the next one is tried; the last resort is
no voice at all (on-screen text and subtitles only). A failure here never stops a video from being made.
"""
import copy
import json
import os
from pathlib import Path

from audio import audio_mixer, narration, subtitles, voice_style
from audio.speakable import load_pronunciations, speakable

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
                voice_style.apply_radio_sound(raw, final, post)
            except voice_style.VoiceStyleError as err:
                raise narration.NarrationError(str(err))
        results[number] = (final, narration.wav_duration(final))
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
            profile = voice_style.get_profile(profile_name)
        except (voice_style.VoiceStyleError, FileNotFoundError, KeyError) as err:
            notes.append(f"Voice profile problem: {err}")
            problems.append(f"The voice profile '{profile_name}' could not be loaded, so the standard voice was used.")
            profile_name = None

    audio, used, used_object = None, "none", None
    for candidate in _candidates(provider_name, provider):
        try:
            impl = candidate if isinstance(candidate, narration.Provider) else narration.get_provider(
                candidate, voice, language, profile["blend"] if profile else None)
        except narration.NarrationError as err:
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
        except narration.NarrationError as err:
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
    cues = subtitles.build_cues(timed["scenes"], 34 if timed["format"] == "short" else 52)
    width, height = (int(v) for v in timed["resolution"].split("x"))
    srt = out_dir / "subtitles.srt"
    ass = out_dir / "subtitles.ass"
    srt.write_text(subtitles.to_srt(cues), encoding="utf-8")
    ass.write_text(subtitles.to_ass(cues, width, height, timed["format"] == "short"), encoding="utf-8")
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
            track = audio_mixer.build_narration_track(track_items, out_dir / "audio" / "narration_track.wav")
            music_path = None
            if music and rendering.get("narration", {}).get("music", True):
                music_path = audio_mixer.make_music(timed["total_duration_seconds"], out_dir / "audio" / "music.wav")
            mixed = audio_mixer.mix(track, out_dir / "audio" / "audio_mix.m4a", music_path,
                                    float(rendering.get("narration", {}).get("music_volume_db", -26)))
            problems += audio_mixer.validate_audio(mixed, timed["total_duration_seconds"])
            loudness = audio_mixer.measure_loudness(mixed)
            files["audio_mix"] = str(mixed)
        except audio_mixer.AudioError as err:
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
