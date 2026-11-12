"""Visual themes: colours, outlines, backgrounds and fonts.

classic    the original dark look (kept so older work still renders the same)
vector_pop bold vector cartoon: colourful gradients, sunbursts, sticker cards with thick outlines
vintage    retro poster on cream paper with halftone dots and rust, teal and mustard inks
collage    cut-paper collage: torn edges, tape and kraft paper

Every scene gets its own colour scheme from the theme, so a video moves through many colours.
"""
from dataclasses import dataclass, field


def rgb(code):
    code = code.lstrip("#")
    return tuple(int(code[i:i + 2], 16) for i in (0, 2, 4))


@dataclass(frozen=True)
class Theme:
    name: str
    base: dict                      # colours that stay the same in every scene
    schemes: list                   # per-scene colours: bg_top, bg_bottom, panel, panel2, accent
    background: str = "flat"        # flat | sunburst | paper | kraft
    outline: tuple = None           # sticker outline colour
    outline_w: float = 0.0          # outline width in units
    shadow: tuple = None
    shadow_off: float = 0.0
    stroke: tuple = None            # text outline colour
    stroke_ratio: float = 0.0       # text outline as a share of the font size
    edge: str = "clean"             # clean | torn
    decor: list = field(default_factory=list)   # colours for drifting shapes
    display_font: str = "bold"      # bold (DejaVu) or display (Lilita One if present)
    hook: str = "3d"                # 3d | illustration
    caption_font: str = "DejaVu Sans"
    body_font: str = "sans"         # font kind used for normal text
    text_scale: float = 1.0         # makes all text bigger in themes that want chunky lettering


CLASSIC_BASE = {name: rgb(code) for name, code in {
    "text": "#F1F5F9", "muted": "#94A3B8", "good": "#34D399", "warn": "#F59E0B", "bad": "#F87171",
    "blue": "#60A5FA", "violet": "#A78BFA"}.items()}
CLASSIC_SCHEME = {"bg_top": rgb("#0B1220"), "bg_bottom": rgb("#0B1220"), "panel": rgb("#16213A"),
                  "panel2": rgb("#1E2B4A"), "accent": rgb("#2DD4BF")}


def _scheme(top, bottom, panel, accent):
    top, bottom, panel, accent = rgb(top), rgb(bottom), rgb(panel), rgb(accent)
    return {"bg_top": top, "bg_bottom": bottom, "panel": panel,
            "panel2": tuple(int(c * 0.72) for c in panel), "accent": accent}


VECTOR_SCHEMES = [
    _scheme("#4A2FA8", "#1D1257", "#6D4DE0", "#FFD60A"),   # indigo
    _scheme("#0B7F8F", "#06394A", "#0F9AA5", "#FF5CAA"),   # teal
    _scheme("#B02858", "#531038", "#E85A60", "#FFD60A"),   # sunset
    _scheme("#1F55C0", "#0E2466", "#3C82F0", "#FFA028"),   # blue
    _scheme("#128060", "#07403A", "#1FA066", "#FFEB46"),   # green
    _scheme("#96209A", "#3E0F56", "#D246BE", "#6EE6E6"),   # magenta
    _scheme("#C25F14", "#6E2814", "#DB6F22", "#4FDDC8"),   # orange
    _scheme("#1C3A9E", "#0A1650", "#2F66D0", "#FF6B6B"),   # royal blue
]
VECTOR_BASE = {**CLASSIC_BASE, "text": rgb("#FFFFFF"), "muted": rgb("#E4E1FF"), "good": rgb("#3CE08A"),
               "warn": rgb("#FFC21E"), "bad": rgb("#FF5560"), "blue": rgb("#5AB0FF"), "violet": rgb("#B08CFF")}

VINTAGE_BASE = {"text": rgb("#2B2118"), "muted": rgb("#6B5A47"), "good": rgb("#3E8E5A"), "warn": rgb("#D9822B"),
                "bad": rgb("#C8442F"), "blue": rgb("#2F6F8F"), "violet": rgb("#7A5A8C")}
VINTAGE_SCHEMES = [
    _scheme("#F3E3BC", "#E8CF9B", "#F7C98B", "#C8442F"),   # cream and peach
    _scheme("#EFE2BF", "#E0CC9C", "#9ED3C0", "#C8442F"),   # cream and mint
    _scheme("#F4E4BE", "#E7D09E", "#F0A98A", "#2F6F8F"),   # cream and salmon
    _scheme("#EEE0BC", "#DFC998", "#A9CBE0", "#D9822B"),   # cream and sky
    _scheme("#F2E2B8", "#E5CC98", "#F2D675", "#2F6F8F"),   # cream and mustard
    _scheme("#F0E1BB", "#E2CB9A", "#C9B5DC", "#C8442F"),   # cream and lilac
]

COLLAGE_SCHEMES = [
    _scheme("#C9A878", "#B8946A", "#F4EAD5", "#D2452D"),   # kraft with cream cards
    _scheme("#C2A070", "#B08A5E", "#BFE3D4", "#D2452D"),
    _scheme("#CDAE80", "#BC986C", "#F6C9A0", "#1F6F8B"),
    _scheme("#C6A576", "#B38F62", "#CFE0F0", "#E58A1F"),
    _scheme("#CAA97A", "#B7936A", "#F7E08A", "#1F6F8B"),
    _scheme("#C4A273", "#B28D60", "#E3CBEA", "#D2452D"),
]

THEMES = {
    "classic": Theme("classic", CLASSIC_BASE, [CLASSIC_SCHEME]),
    "vector_pop": Theme(
        "vector_pop", VECTOR_BASE, VECTOR_SCHEMES, background="sunburst",
        outline=rgb("#160E3A"), outline_w=6.0, shadow=rgb("#0C0626"), shadow_off=26.0,
        stroke=rgb("#160E3A"), stroke_ratio=0.085, decor=[rgb(c) for c in (
            "#FFD60A", "#FF5CAA", "#5AB0FF", "#3CE08A", "#FF8A3D", "#B08CFF", "#6EE6E6")],
        display_font="display", hook="illustration", caption_font="Lilita One", text_scale=1.12),
    "vintage": Theme(
        "vintage", VINTAGE_BASE, VINTAGE_SCHEMES, background="paper",
        outline=rgb("#2B2118"), outline_w=4.0, shadow=rgb("#9B7F57"), shadow_off=7.0,
        decor=[rgb(c) for c in ("#C8442F", "#2F6F8F", "#D9822B", "#3E8E5A", "#7A5A8C")],
        display_font="display", hook="illustration", caption_font="Lilita One"),
    "collage": Theme(
        "collage", VINTAGE_BASE, COLLAGE_SCHEMES, background="kraft",
        outline=rgb("#2B2118"), outline_w=3.0, shadow=rgb("#6E5233"), shadow_off=6.0, edge="torn",
        decor=[rgb(c) for c in ("#D2452D", "#1F6F8B", "#E58A1F", "#3E8E5A", "#7A5A8C")],
        display_font="display", hook="illustration", caption_font="Lilita One"),
}

_active = THEMES["classic"]


def set_theme(name):
    global _active
    if name not in THEMES:
        raise ValueError(f"Unknown theme '{name}'. Known themes: {', '.join(THEMES)}")
    _active = THEMES[name]
    return _active


def current():
    return _active


def scheme_for(scene_number, theme=None):
    theme = theme or _active
    return theme.schemes[(max(1, scene_number) - 1) % len(theme.schemes)]


def apply_to_palette(palette, scene_number, theme=None):
    """Write the theme's colours for this scene into the shared palette dictionary."""
    theme = theme or _active
    scheme = scheme_for(scene_number, theme)
    palette.update(theme.base)
    palette["accent"] = scheme["accent"]
    palette["panel"] = scheme["panel"]
    palette["panel2"] = scheme["panel2"]
    palette["bg"] = tuple((a + b) // 2 for a, b in zip(scheme["bg_top"], scheme["bg_bottom"]))
    return scheme
