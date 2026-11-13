"""Turns storyboard scenes into short MP4 clips (silent; audio arrives in Stage 7).

Frames are drawn with Pillow and piped straight into FFmpeg, so no files are
needed per frame and no desktop application is opened.
"""
import os
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

from animation.two_d import themes
from animation.two_d.canvas import PALETTE, Canvas, clamp, ease_in_out, load_font
from animation.two_d.scenes import SCENE_FUNCTIONS

BRAND = "SCICLIPS"
QUALITY = {"draft": {"scale": 0.5, "fps": 12}, "full": {"scale": 1.0, "fps": None}}


class RenderError(Exception):
    """Raised when a clip cannot be rendered."""


def even(value):
    value = int(round(value))
    return value if value % 2 == 0 else value + 1


def frame_size(storyboard, quality):
    width, height = (int(v) for v in storyboard["resolution"].split("x"))
    scale = QUALITY[quality]["scale"]
    return even(width * scale), even(height * scale)


def frame_rate(storyboard, quality):
    return QUALITY[quality]["fps"] or storyboard["fps"]


def draw_frame(scene, record, width, height, t):
    """Draw one frame of a scene at progress t (0 to 1) and return a Pillow image."""
    number = scene.get("scene_number", 1)
    scheme = themes.apply_to_palette(PALETTE, number)
    canvas = Canvas(width, height, scheme, seed=number)
    canvas.paint_background(t * scene.get("duration_seconds", 5))
    function = SCENE_FUNCTIONS.get(scene["animation_type"])
    if function is None:
        raise RenderError(f"No drawing function for animation type '{scene['animation_type']}'")
    function(canvas, t, {"scene": scene, "record": record})
    if scene.get("section_kind") != "outro":
        # The channel name sits at the top of every frame, above where the content starts.
        canvas.label((width / 2, canvas.px(26)), BRAND, 46, "text", kind="bold", anchor="ma")
    return canvas.img


def _backdrop(scene, size, secs):
    """The scene's own background with nothing on it, so fades and wipes start from the right colours."""
    if themes.current().background == "flat":
        return Image.new("RGB", size, PALETTE["bg"])
    number = scene.get("scene_number", 1)
    canvas = Canvas(size[0], size[1], themes.scheme_for(number), seed=number)
    canvas.paint_background(secs)
    return canvas.img


def apply_transition(image, scene, secs, total_secs):
    """Fade or wipe a frame in or out. `secs` is the time into the scene. Timing is unchanged, so audio stays in sync."""
    kind = scene.get("transition", "cut")
    width, height = image.size
    bg = _backdrop(scene, image.size, secs) if kind in ("fade", "fade out", "wipe") and secs < 0.5 else \
        Image.new("RGB", image.size, PALETTE["bg"])
    black = Image.new("RGB", image.size, (0, 0, 0))
    if kind == "fade in":
        image = Image.blend(black, image, clamp(secs / 0.6))
    elif kind in ("fade", "fade out"):
        image = Image.blend(bg, image, clamp(secs / 0.25))
        if kind == "fade out":
            image = Image.blend(black, image, clamp((total_secs - secs) / 0.8))
    elif kind == "wipe":
        reveal = int(width * ease_in_out(secs / 0.4))
        if reveal < width:
            bg.paste(image.crop((0, 0, reveal, height)), (0, 0))
            image = bg
    return image


def plan_frames(storyboard, fps):
    """Frame count for each scene, worked out from running totals so the video never drifts from the audio."""
    counts, clock, drawn = {}, 0.0, 0
    for scene in storyboard["scenes"]:
        clock += scene["duration_seconds"]
        end = round(clock * fps)
        counts[scene["scene_number"]] = max(2, end - drawn)
        drawn += counts[scene["scene_number"]]
    return counts


def render_scene(scene, record, out_path, width, height, fps, poster_path=None, frames=None):
    """Render one scene to an MP4. Returns a small report dict."""
    if shutil.which("ffmpeg") is None:
        raise RenderError("FFmpeg was not found. Install it (sudo apt-get install -y ffmpeg).")
    frames = frames or max(2, round(scene["duration_seconds"] * fps))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
               str(out_path)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    poster_index = int(0.85 * (frames - 1))
    try:
        for i in range(frames):
            image = draw_frame(scene, record, width, height, i / (frames - 1))
            image = apply_transition(image, scene, i / fps, frames / fps)
            if poster_path and i == poster_index:
                Path(poster_path).parent.mkdir(parents=True, exist_ok=True)
                image.save(poster_path)
            process.stdin.write(image.tobytes())
        process.stdin.close()
        error = process.stderr.read().decode("utf-8", "replace")
        code = process.wait()
    except BrokenPipeError:
        error = process.stderr.read().decode("utf-8", "replace")
        raise RenderError(f"FFmpeg stopped early: {error.strip()}")
    except Exception:
        process.kill()
        raise
    if code != 0:
        raise RenderError(f"FFmpeg failed (exit {code}): {error.strip()}")
    return {"scene_number": scene["scene_number"], "path": str(out_path),
            "poster": str(poster_path) if poster_path else None, "frames": frames, "fps": fps,
            "width": width, "height": height, "duration_seconds": scene["duration_seconds"],
            "clip_seconds": frames / fps}


def make_contact_sheet(poster_paths, out_path, columns=4, thumb_width=300):
    """One picture showing a thumbnail of every scene, so a person can review quickly."""
    images = [Image.open(p).convert("RGB") for p in poster_paths]
    if not images:
        return None
    ratio = images[0].height / images[0].width
    thumb_h = int(thumb_width * ratio)
    rows = (len(images) + columns - 1) // columns
    pad = 12
    sheet = Image.new("RGB", (columns * (thumb_width + pad) + pad, rows * (thumb_h + pad + 22) + pad), PALETTE["bg"])
    draw = ImageDraw.Draw(sheet)
    font = load_font("sans", 16)
    for index, image in enumerate(images):
        row, col = divmod(index, columns)
        x = pad + col * (thumb_width + pad)
        y = pad + row * (thumb_h + pad + 22)
        sheet.paste(image.resize((thumb_width, thumb_h)), (x, y + 22))
        draw.text((x, y), f"Scene {index + 1}", font=font, fill=PALETTE["muted"])
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return str(out_path)


def _render_job(job):
    scene, record, path, width, height, fps, poster, frames, theme_name = job
    themes.set_theme(theme_name)
    return render_scene(scene, record, path, width, height, fps, poster, frames)


def default_workers():
    """How many scenes to draw at once: the RENDER_WORKERS setting, else up to 4 (the CPUs the runner has)."""
    setting = os.environ.get("RENDER_WORKERS")
    if setting and setting.isdigit() and int(setting) > 0:
        return int(setting)
    return max(1, min(4, os.cpu_count() or 1))


def render_storyboard(storyboard, record, out_dir, quality="draft", only_scenes=None, workers=None):
    """Render every scene (or the numbers in only_scenes). Several scenes are drawn at once when workers > 1."""
    if quality not in QUALITY:
        raise RenderError(f"Unknown quality '{quality}'. Use draft or full.")
    width, height = frame_size(storyboard, quality)
    fps = frame_rate(storyboard, quality)
    out_dir = Path(out_dir)
    counts = plan_frames(storyboard, fps)
    jobs = []
    for scene in storyboard["scenes"]:
        if only_scenes and scene["scene_number"] not in only_scenes:
            continue
        number = scene["scene_number"]
        jobs.append((scene, record, str(out_dir / f"scene_{number:03d}.mp4"), width, height, fps,
                     str(out_dir / f"scene_{number:03d}.png"), counts[number], themes.current().name))
    workers = workers or default_workers()
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            reports = list(pool.map(_render_job, jobs))
    else:
        reports = [_render_job(job) for job in jobs]
    sheet = make_contact_sheet([r["poster"] for r in reports], out_dir / "contact_sheet.png")
    for report in reports:
        report["contact_sheet"] = sheet
    return reports


def save_thumbnail(storyboard, record, out_path, quality="draft", t=0.85):
    """A still picture from the opening scene, as a JPEG small enough for upload sites."""
    width, height = frame_size(storyboard, quality)
    image = draw_frame(storyboard["scenes"][0], record, width, height, t)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "JPEG", quality=90)
    return str(out_path)
