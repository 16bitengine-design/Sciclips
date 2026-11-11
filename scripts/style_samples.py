"""Makes sample thumbnails and scene pictures in every visual style, so you can compare them and choose.

Writes output/style-samples/<style>/... and one picture, COMPARE.png, with every thumbnail side by side.
Nothing is published. Set STYLES to a comma-separated list to try only some styles.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from animation.two_d import themes  # noqa: E402
from animation.two_d.canvas import use_theme  # noqa: E402
from animation.two_d.renderer import draw_frame, make_contact_sheet  # noqa: E402
from animation.two_d.thumbnail import make_thumbnail  # noqa: E402
from content.script_generator import generate_script  # noqa: E402
from content.storyboard_generator import generate_storyboard  # noqa: E402
from content.topic_manager import load_topic_record  # noqa: E402

TOPICS = ("physics-001", "chem-001")
NOTE = {"vector_pop": "bold vector cartoon", "vintage": "retro poster on paper", "collage": "cut-paper collage",
        "classic": "the original dark look"}


def run(root, out_dir, styles=None, topics=TOPICS):
    """Returns (ok, report_lines)."""
    with open(Path(root) / "config" / "rendering.json", encoding="utf-8") as handle:
        rendering = json.load(handle)
    out = Path(out_dir)
    lines, ok, compare = [], True, []
    for style in styles or list(themes.THEMES):
        if style not in themes.THEMES:
            lines.append(f"{style}: FAILED - unknown style. Known styles: {', '.join(themes.THEMES)}")
            ok = False
            continue
        with use_theme(style):
            for topic in topics:
                record = load_topic_record(root, topic)
                folder = out / style / topic
                folder.mkdir(parents=True, exist_ok=True)
                long_path = make_thumbnail(record, "long", folder / "thumbnail_youtube.jpg")
                make_thumbnail(record, "short", folder / "thumbnail_vertical.jpg")
                compare.append((style, topic, long_path))
                script = generate_script(record, "short", "explainer", rendering, {"status": "passed_automated_checks"})
                board = generate_storyboard(script, record, rendering)
                posters = []
                for scene in board["scenes"][:8]:
                    path = folder / f"scene_{scene['scene_number']:02d}.png"
                    draw_frame(scene, record, 540, 960, 0.8).save(path)
                    posters.append(str(path))
                make_contact_sheet(posters, folder / "scenes.png", columns=4)
        lines.append(f"{style}: OK - {NOTE.get(style, '')}")
    if compare:
        width, height, pad = 640, 360, 12
        sheet = Image.new("RGB", (len(TOPICS) * (width + pad) + pad,
                                  (len(compare) // len(TOPICS)) * (height + pad) + pad), (30, 30, 36))
        for i, (_, _, path) in enumerate(compare):
            row, col = divmod(i, len(TOPICS))
            sheet.paste(Image.open(path).resize((width, height)), (pad + col * (width + pad), pad + row * (height + pad)))
        out.mkdir(parents=True, exist_ok=True)
        sheet.save(out / "COMPARE.png")
    (out / "READ_ME.txt").write_text(
        "Style samples\n\nEach folder is one visual style. Open COMPARE.png first: every style's YouTube thumbnail "
        "side by side (rows follow this order: " + ", ".join(sorted({c[0] for c in compare}, key=lambda n: [c[0] for c in compare].index(n)))
        + ").\nThen look at each style's scenes.png to see how the video looks.\nTo choose one, set \"theme\" in the "
        "\"style\" section of config/rendering.json.\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return ok, lines


def main():
    chosen = [n.strip() for n in os.environ.get("STYLES", "").split(",") if n.strip()] or None
    ok, lines = run(".", os.environ.get("OUTPUT_DIR", "output") + "/style-samples", chosen)
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Style samples\n\n```\n" + text + "\n```\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
