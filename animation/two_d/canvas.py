"""Drawing helpers: a canvas, colours, fonts and text layout (Pillow only)."""
import math
import os
import random
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from animation.two_d import themes


def hexrgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


PALETTE = {name: hexrgb(code) for name, code in {
    "bg": "#0B1220", "panel": "#16213A", "panel2": "#1E2B4A", "text": "#F1F5F9",
    "muted": "#94A3B8", "accent": "#2DD4BF", "good": "#34D399", "warn": "#F59E0B",
    "bad": "#F87171", "blue": "#60A5FA", "violet": "#A78BFA",
}.items()}

FONT_FILES = {
    "sans": ["DejaVuSans.ttf", "FreeSans.ttf", "LiberationSans-Regular.ttf"],
    "bold": ["DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "LiberationSans-Bold.ttf"],
    "mono": ["DejaVuSansMono.ttf", "FreeMono.ttf", "LiberationMono-Regular.ttf"],
    "strong": ["DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "LiberationSans-Bold.ttf"],
    "display": ["LilitaOne-Regular.ttf", "DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "LiberationSans-Bold.ttf"],
}
FONT_DIRS = [str(Path(__file__).resolve().parents[2] / "assets" / "fonts"), "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/truetype/freefont",
             "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/TTF", "/Library/Fonts"]


@lru_cache(maxsize=None)
def load_font(kind, size):
    for name in FONT_FILES[kind]:
        for folder in FONT_DIRS:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def mix(color, background, amount):
    """Blend `color` toward `background`; amount 1 = full colour, 0 = invisible."""
    return tuple(round(background[i] + (color[i] - background[i]) * amount) for i in range(3))


def clamp(x, low=0.0, high=1.0):
    return max(low, min(high, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp(x)
    return 3 * x * x - 2 * x ** 3


def appear(t, start, length=0.15):
    """0 before `start`, rising to 1 over `length` (all in scene progress 0..1)."""
    return ease_out((t - start) / length)


SUPERSCRIPT = str.maketrans("0123456789-", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207b")
SUBSCRIPT = str.maketrans("0123456789", "\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089")


def pretty_math(text):
    """'m^3 kg^-1' -> 'm³ kg⁻¹', 'CH3COOH' -> 'CH₃COOH', '->' -> '→'."""
    text = text.replace("->", " \u2192 ")
    text = re.sub(r"\^(-?\d+)", lambda m: m.group(1).translate(SUPERSCRIPT), text)
    text = re.sub(r"(?<=[A-Za-z)])(\d+)", lambda m: m.group(1).translate(SUBSCRIPT), text)
    return " ".join(text.split())


class Canvas:
    """One frame. Sizes are given in 'units' where the shorter side is 1080 units."""

    def __init__(self, width, height, scheme=None, seed=1):
        self.w, self.h = width, height
        self.u = min(width, height) / 1080.0
        self.portrait = height > width
        self.theme = themes.current()
        self.scheme = scheme
        self.seed = seed
        self.img = Image.new("RGB", (width, height), PALETTE["bg"])
        self.d = ImageDraw.Draw(self.img, "RGBA")

    def paint_background(self, secs=0.0):
        """Draw the theme's background (gradient, rays, shapes or paper). The classic theme stays flat."""
        if self.theme.background != "flat" and self.scheme is not None:
            from animation.two_d import backgrounds
            backgrounds.paint(self, secs)

    # colours and sizes
    def px(self, units):
        return units * self.u

    def col(self, name, alpha=1.0):
        base = PALETTE[name] if isinstance(name, str) else name
        return mix(base, PALETTE["bg"], clamp(alpha))

    def font(self, kind, size):
        if kind == "bold":
            kind = self.theme.display_font
        elif kind == "sans":
            kind = self.theme.body_font
        return load_font(kind, max(8, round(size * self.theme.text_scale * self.u)))

    @property
    def inner(self):
        """Colour name for panels drawn on top of cards: darker than the card in themed looks."""
        return "panel" if self.theme.name == "classic" else "panel2"

    @staticmethod
    def kind_for(text, kind):
        """The display font only has plain letters. Text with symbols (subscripts, arrows) uses a full font."""
        if kind == "bold" and any(not (0x20 <= ord(ch) <= 0x7E) for ch in text):
            return "strong"
        return kind

    def _text(self, xy, text, font, color, alpha, anchor, size):
        """Draw text, with an outline in themes that ask for one."""
        th = self.theme
        stroke = {}
        if th.stroke and size >= 30:
            stroke = {"stroke_width": max(2, round(size * th.text_scale * self.u * th.stroke_ratio)),
                      "stroke_fill": self.col(th.stroke, alpha)}
        self.d.text(xy, text, font=font, fill=self.col(color, alpha), anchor=anchor, **stroke)

    def content_box(self):
        margin = 0.07 * self.w
        bottom = 0.80 * self.h
        return (margin, 0.07 * self.h, self.w - margin, bottom)

    # text
    def wrap(self, text, font, max_width):
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

    def text_height(self, lines, size, line_gap=1.3):
        return len(lines) * size * self.theme.text_scale * self.u * line_gap

    def paragraph(self, x, y, text, size, color="text", max_width=None, kind="sans", align="left",
                  alpha=1.0, line_gap=1.3):
        """Draw wrapped text; (x, y) is the top-left (or top-centre when align='center'). Returns bottom y."""
        font = self.font(self.kind_for(text, kind), size)
        max_width = max_width or (self.w - x)
        lines = self.wrap(text, font, max_width)
        step = size * self.theme.text_scale * self.u * line_gap
        for i, line in enumerate(lines):
            self._text((x, y + i * step), line, font, color, alpha, "ma" if align == "center" else "la", size)
        return y + len(lines) * step

    def paragraph_rich(self, x, y, text, size, color_for_word, max_width, kind="sans", align="left",
                       alpha=1.0, line_gap=1.3):
        """Like paragraph, but each word can have its own colour: color_for_word(word) -> colour name."""
        font = self.font(self.kind_for(text, kind), size)
        space = font.getlength(" ")
        lines, current, width = [], [], 0.0
        for word in text.split():
            w = font.getlength(word)
            if current and width + space + w > max_width:
                lines.append((current, width))
                current, width = [word], w
            else:
                width += (space if current else 0) + w
                current.append(word)
        if current:
            lines.append((current, width))
        step = size * self.theme.text_scale * self.u * line_gap
        for i, (words, line_w) in enumerate(lines):
            cursor = x - line_w / 2 if align == "center" else x
            for word in words:
                self._text((cursor, y + i * step), word, font, color_for_word(word), alpha, "la", size)
                cursor += font.getlength(word) + space
        return y + len(lines) * step

    def fit_size(self, text, max_width, max_height, max_size, min_size, kind="sans", line_gap=1.3):
        """Largest font size (units) whose wrapped text fits the box."""
        size = max_size
        kind = self.kind_for(text, kind)
        while size > min_size:
            lines = self.wrap(text, self.font(kind, size), max_width)
            if self.text_height(lines, size, line_gap) <= max_height:
                return size
            size -= 2
        return min_size

    def label(self, xy, text, size, color="text", kind="sans", anchor="la", alpha=1.0):
        self._text(xy, text, self.font(self.kind_for(text, kind), size), color, alpha, anchor, size)

    # shapes
    def _torn(self, box, jitter):
        """A rectangle outline with a rough, torn-paper edge (the same box always tears the same way)."""
        x0, y0, x1, y1 = box
        rng = random.Random(int(x0 * 7 + y0 * 13 + x1 * 17 + y1 * 19) + self.seed)
        step = max(14.0, 26 * self.u)
        pts = []
        for x in range(int(x0), int(x1), int(step)):
            pts.append((x, y0 + rng.uniform(-jitter, jitter)))
        for y in range(int(y0), int(y1), int(step)):
            pts.append((x1 + rng.uniform(-jitter, jitter), y))
        for x in range(int(x1), int(x0), -int(step)):
            pts.append((x, y1 + rng.uniform(-jitter, jitter)))
        for y in range(int(y1), int(y0), -int(step)):
            pts.append((x0 + rng.uniform(-jitter, jitter), y))
        return pts

    def rect(self, box, fill=None, radius=0, outline=None, width=0, alpha=1.0, sticker=None):
        """A rectangle. In themes with outlines, larger rounded boxes become 'stickers' with a shadow."""
        th = self.theme
        wide = (box[2] - box[0]) >= 40 * self.u and (box[3] - box[1]) >= 30 * self.u
        if sticker is None:
            sticker = bool(th.outline and fill and outline is None and radius and wide)
        if sticker:
            off = th.shadow_off * self.u
            shadow_box = (box[0] + off, box[1] + off, box[2] + off, box[3] + off)
            ow = max(2, round(th.outline_w * self.u))
            if th.edge == "torn":
                jitter = 4.5 * self.u
                self.d.polygon(self._torn(shadow_box, jitter), fill=self.col(th.shadow, alpha))
                pts = self._torn(box, jitter)
                self.d.polygon(pts, fill=self.col(fill, alpha), outline=self.col(th.outline, alpha), width=ow)
                tape = self.col((235, 222, 170), alpha * 0.85)
                for cx in (box[0] + 40 * self.u, box[2] - 40 * self.u):
                    self.d.polygon([(cx - 26 * self.u, box[1] - 10 * self.u), (cx + 26 * self.u, box[1] - 4 * self.u),
                                    (cx + 22 * self.u, box[1] + 14 * self.u), (cx - 30 * self.u, box[1] + 8 * self.u)],
                                   fill=tape)
            else:
                self.d.rounded_rectangle(shadow_box, radius=radius * self.u, fill=self.col(th.shadow, alpha))
                self.d.rounded_rectangle(box, radius=radius * self.u, fill=self.col(fill, alpha),
                                         outline=self.col(th.outline, alpha), width=ow)
            return
        fill = self.col(fill, alpha) if fill else None
        outline = self.col(outline, alpha) if outline else None
        if radius:
            self.d.rounded_rectangle(box, radius=radius * self.u, fill=fill, outline=outline,
                                     width=max(0, round(width * self.u)))
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=max(0, round(width * self.u)))

    def circle(self, center, radius, fill=None, outline=None, width=0, alpha=1.0):
        x, y = center
        box = (x - radius, y - radius, x + radius, y + radius)
        self.d.ellipse(box, fill=self.col(fill, alpha) if fill else None,
                       outline=self.col(outline, alpha) if outline else None,
                       width=max(0, round(width * self.u)))

    def line(self, p0, p1, color="text", width=4, alpha=1.0):
        self.d.line([p0, p1], fill=self.col(color, alpha), width=max(1, round(width * self.u)))

    def arrow(self, p0, p1, color="text", width=6, alpha=1.0):
        """A line with an arrow head at p1 (used for force vectors and flow)."""
        import math
        self.line(p0, p1, color, width, alpha)
        angle = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        head = 26 * self.u
        spread = math.radians(26)
        pts = [p1,
               (p1[0] - head * math.cos(angle - spread), p1[1] - head * math.sin(angle - spread)),
               (p1[0] - head * math.cos(angle + spread), p1[1] - head * math.sin(angle + spread))]
        self.d.polygon(pts, fill=self.col(color, alpha))

    def polygon(self, points, fill, alpha=1.0):
        self.d.polygon(points, fill=self.col(fill, alpha))
