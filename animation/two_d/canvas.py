"""Drawing helpers: a canvas, colours, fonts and text layout (Pillow only)."""
import os
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont


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
}
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/truetype/freefont",
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

    def __init__(self, width, height):
        self.w, self.h = width, height
        self.u = min(width, height) / 1080.0
        self.portrait = height > width
        self.img = Image.new("RGB", (width, height), PALETTE["bg"])
        self.d = ImageDraw.Draw(self.img)

    # colours and sizes
    def px(self, units):
        return units * self.u

    def col(self, name, alpha=1.0):
        base = PALETTE[name] if isinstance(name, str) else name
        return mix(base, PALETTE["bg"], clamp(alpha))

    def font(self, kind, size):
        return load_font(kind, max(8, round(size * self.u)))

    def content_box(self):
        margin = 0.07 * self.w
        bottom = (0.80 if self.portrait else 0.92) * self.h
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
        return len(lines) * size * self.u * line_gap

    def paragraph(self, x, y, text, size, color="text", max_width=None, kind="sans", align="left",
                  alpha=1.0, line_gap=1.3):
        """Draw wrapped text; (x, y) is the top-left (or top-centre when align='center'). Returns bottom y."""
        font = self.font(kind, size)
        max_width = max_width or (self.w - x)
        lines = self.wrap(text, font, max_width)
        step = size * self.u * line_gap
        fill = self.col(color, alpha)
        for i, line in enumerate(lines):
            if align == "center":
                self.d.text((x, y + i * step), line, font=font, fill=fill, anchor="ma")
            else:
                self.d.text((x, y + i * step), line, font=font, fill=fill, anchor="la")
        return y + len(lines) * step

    def fit_size(self, text, max_width, max_height, max_size, min_size, kind="sans", line_gap=1.3):
        """Largest font size (units) whose wrapped text fits the box."""
        size = max_size
        while size > min_size:
            lines = self.wrap(text, self.font(kind, size), max_width)
            if self.text_height(lines, size, line_gap) <= max_height:
                return size
            size -= 2
        return min_size

    def label(self, xy, text, size, color="text", kind="sans", anchor="la", alpha=1.0):
        self.d.text(xy, text, font=self.font(kind, size), fill=self.col(color, alpha), anchor=anchor)

    # shapes
    def rect(self, box, fill=None, radius=0, outline=None, width=0, alpha=1.0):
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
