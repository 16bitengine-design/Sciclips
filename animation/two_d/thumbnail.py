"""Thumbnails: a bold headline, a cartoon illustration in a sticker frame, a question badge and a ribbon.

Made for YouTube (1280x720) and for vertical covers (1080x1920). Uses the active theme's colours and fonts.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

from animation.two_d import illustrations, themes
from animation.two_d.canvas import PALETTE, Canvas, load_font

SIZES = {"long": (1280, 720), "short": (1080, 1920)}
SS = 2
INK = (22, 14, 58)
LINE_COLOURS = [(255, 226, 60), (255, 255, 255), (255, 110, 175)]


def _headline_text(record):
    spec = record.get("thumbnail") or {}
    if spec.get("headline"):
        return spec["headline"].upper()
    words = record["title"].rstrip("?.! ").upper().split()
    return " ".join(words[:5])


def _font(px):
    return load_font(themes.current().display_font, max(8, int(px)))


def _wrap(text, font, max_width):
    lines, current = [], ""
    for word in text.split():
        trial = (current + " " + word).strip()
        if current and font.getlength(trial) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _fit(text, max_w, max_h, max_px, min_px, max_lines=3):
    px = max_px
    while px > min_px:
        font = _font(px)
        lines = _wrap(text, font, max_w)
        if len(lines) <= max_lines and len(lines) * px * 1.08 <= max_h:
            return px, lines
        px -= 4
    return min_px, _wrap(text, _font(min_px), max_w)


def _outlined_text(d, xy, text, px, fill, anchor="la", stroke=0.13, shadow=True):
    font = _font(px)
    sw = max(3, round(px * stroke))
    if shadow:
        off = round(px * 0.07)
        d.text((xy[0] + off, xy[1] + off), text, font=font, fill=INK, anchor=anchor, stroke_width=sw, stroke_fill=INK)
    d.text(xy, text, font=font, fill=fill, anchor=anchor, stroke_width=sw, stroke_fill=INK)


def _burst(d, cx, cy, r, points, fill, width):
    pts = []
    for i in range(points * 2):
        rr = r if i % 2 == 0 else r * 0.78
        a = math.pi * i / points - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=fill, outline=INK, width=width)


def _sticker_frame(c, box, image, radius, outline_px):
    x0, y0, x1, y1 = (int(v) for v in box)
    d = c.d
    off = round(outline_px * 1.6)
    d.rounded_rectangle((x0 + off, y0 + off, x1 + off, y1 + off), radius=radius, fill=INK)
    d.rounded_rectangle((x0 - outline_px, y0 - outline_px, x1 + outline_px, y1 + outline_px), radius=radius + outline_px,
                        fill=(255, 255, 255))
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.size[0] - 1, image.size[1] - 1), radius=radius, fill=255)
    c.img.paste(image, (x0, y0), mask)
    d.rounded_rectangle((x0 - outline_px, y0 - outline_px, x1 + outline_px, y1 + outline_px), radius=radius + outline_px,
                        outline=INK, width=max(3, outline_px // 2))


def _ribbon(d, cx, cy, text, px, fill, max_width=None):
    font = _font(px)
    if max_width:
        while px > 20 and font.getlength(text) + px * 2.3 > max_width:
            px -= 3
            font = _font(px)
    tw = font.getlength(text)
    hh = px * 0.72
    pad = px * 0.8
    pts = [(cx - tw / 2 - pad, cy - hh), (cx + tw / 2 + pad, cy - hh + px * 0.08), (cx + tw / 2 + pad + px * 0.35, cy),
           (cx + tw / 2 + pad, cy + hh), (cx - tw / 2 - pad, cy + hh - px * 0.08), (cx - tw / 2 - pad - px * 0.35, cy)]
    d.polygon([(x + px * 0.07, y + px * 0.07) for x, y in pts], fill=INK)
    d.polygon(pts, fill=fill, outline=INK, width=max(3, round(px * 0.09)))
    d.text((cx, cy), text, font=font, fill=(255, 255, 255), anchor="mm", stroke_width=max(2, round(px * 0.07)),
           stroke_fill=INK)


def make_thumbnail(record, fmt, out_path, quality=90):
    """Save a thumbnail as a JPEG and return its path."""
    spec = record.get("thumbnail") or {}
    w, h = SIZES[fmt]
    scheme_no = spec.get("scheme", 3)
    scheme = themes.apply_to_palette(PALETTE, scheme_no)
    c = Canvas(w * SS, h * SS, scheme, seed=scheme_no)
    c.paint_background(0.0)
    d = c.d
    W, H = w * SS, h * SS
    headline, subline, badge = _headline_text(record), spec.get("subline", ""), spec.get("badge", "?")
    landscape = fmt == "long"
    if landscape:
        box = (0.515 * W, 0.07 * H, 0.97 * W, 0.93 * H)
        text_box = (0.045 * W, 0.08 * H, 0.475 * W, 0.66 * H)
    else:
        box = (0.07 * W, 0.37 * H, 0.93 * W, 0.80 * H)
        text_box = (0.07 * W, 0.045 * H, 0.93 * W, 0.33 * H)
    bw, bh = int(box[2] - box[0]), int(box[3] - box[1])
    art = illustrations.render_illustration(record, spec.get("moment", 0.55), bw, bh, secs=1.4, ss=1)
    if art is not None:
        _sticker_frame(c, box, art, radius=int(0.05 * min(W, H)), outline_px=int(0.012 * min(W, H)))
    px, lines = _fit(headline, text_box[2] - text_box[0], text_box[3] - text_box[1],
                     int(0.20 * H) if landscape else int(0.115 * H), 40)
    y = text_box[1]
    for i, line in enumerate(lines):
        x = text_box[0] if landscape else (text_box[0] + text_box[2]) / 2
        _outlined_text(d, (x, y), line, px, LINE_COLOURS[i % 3], "la" if landscape else "ma")
        y += px * 1.08
    if subline:
        sub_px = int(0.062 * H) if landscape else int(0.036 * H)
        cx = (text_box[0] + text_box[2]) / 2 if landscape else W / 2
        cy = min(y + sub_px * 1.1, 0.88 * H) if landscape else 0.865 * H
        _ribbon(d, cx, cy, subline.upper(), sub_px, (255, 92, 170),
                (text_box[2] - text_box[0]) if landscape else 0.86 * W)
    if badge:
        bx, by = (box[2] - 0.05 * W, box[1] + 0.02 * H) if landscape else (box[2] - 0.02 * W, box[1] - 0.01 * H)
        br = 0.085 * min(W, H) if landscape else 0.10 * W
        _burst(d, bx, by, br, 12, (255, 226, 60), max(4, round(br * 0.07)))
        d.text((bx, by + br * 0.03), badge, font=_font(br * 1.25), fill=INK, anchor="mm")
    tag = "SCIENCE ANIMATION STUDIO"
    _outlined_text(d, (0.045 * W if landscape else W / 2, 0.955 * H if landscape else 0.945 * H), tag,
                   0.03 * H if landscape else 0.0185 * H, (255, 255, 255), "lm" if landscape else "mm", 0.10, False)
    image = c.img.resize((w, h), Image.LANCZOS).convert("RGB")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "JPEG", quality=quality)
    return str(out_path)
