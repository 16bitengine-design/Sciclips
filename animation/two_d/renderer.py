"""Turns storyboard scenes into short MP4 clips (silent; audio arrives in Stage 7).

Frames are drawn with Pillow and piped straight into FFmpeg, so no files are
needed per frame and no desktop application is opened.
"""
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from animation.two_d.canvas import PALETTE, Canvas, load_font
from animation.two_d.scenes import SCENE_FUNCTIONS

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
    canvas = Canvas(width, height)
    function = SCENE_FUNCTIONS.get(scene["animation_type"])
    if function is None:
        raise RenderError(f"No drawing function for animation type '{scene['animation_type']}'")
    function(canvas, t, {"scene": scene, "record": record})
    return canvas.img


def render_scene(scene, record, out_path, width, height, fps, poster_path=None):
    """Render one scene to an MP4. Returns a small report dict."""
    if shutil.which("ffmpeg") is None:
        raise RenderError("FFmpeg was not found. Install it (sudo apt-get install -y ffmpeg).")
    frames = max(2, round(scene["duration_seconds"] * fps))
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
            "width": width, "height": height, "duration_seconds": scene["duration_seconds"]}


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


def render_storyboard(storyboard, record, out_dir, quality="draft", only_scenes=None):
    """Render every scene (or the numbers in only_scenes). Returns a list of reports."""
    if quality not in QUALITY:
        raise RenderError(f"Unknown quality '{quality}'. Use draft or full.")
    width, height = frame_size(storyboard, quality)
    fps = frame_rate(storyboard, quality)
    out_dir = Path(out_dir)
    reports = []
    for scene in storyboard["scenes"]:
        if only_scenes and scene["scene_number"] not in only_scenes:
            continue
        number = scene["scene_number"]
        reports.append(render_scene(scene, record, out_dir / f"scene_{number:03d}.mp4", width, height, fps,
                                    out_dir / f"scene_{number:03d}.png"))
    sheet = make_contact_sheet([r["poster"] for r in reports], out_dir / "contact_sheet.png")
    for report in reports:
        report["contact_sheet"] = sheet
    return reports
