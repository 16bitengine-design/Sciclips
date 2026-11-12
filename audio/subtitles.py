"""Builds subtitle cues from a timed storyboard and writes them as SRT and ASS files."""
import re
import textwrap


def _clock_srt(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _clock_ass(seconds):
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _fits(text, max_chars, max_lines):
    return len(textwrap.wrap(text, max_chars) or [text]) <= max_lines


def _balanced(text, max_chars, max_lines):
    """Split one long sentence into cues of similar size, each fitting max_lines lines."""
    words = text.split()
    parts = -(-len(textwrap.wrap(text, max_chars)) // max_lines)
    while True:
        size = -(-len(words) // parts)
        pieces = [" ".join(words[i:i + size]) for i in range(0, len(words), size)]
        if all(_fits(p, max_chars, max_lines) for p in pieces):
            return pieces
        parts += 1


def _chunks(text, max_chars, max_lines):
    """Split text into pieces that wrap to at most max_lines lines of max_chars, preferring sentence ends."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        trial = (current + " " + sentence).strip()
        if current and not _fits(trial, max_chars, max_lines):
            pieces.append(current)
            current = ""
            trial = sentence
        if _fits(trial, max_chars, max_lines):
            current = trial
            continue
        pieces.extend(_balanced(trial, max_chars, max_lines))
        current = ""
    if current:
        pieces.append(current)
    return pieces


def build_cues(scenes, max_chars=34, max_lines=2):
    """One cue per piece of narration. `scenes` need start_seconds, end_seconds and narration."""
    cues = []
    for scene in scenes:
        text = scene.get("narration", "").strip()
        if not text:
            continue
        pieces = _chunks(text, max_chars, max_lines)
        start = scene["start_seconds"] + 0.10
        end = max(start + 0.5, scene["end_seconds"] - 0.20)
        total = sum(len(p) for p in pieces)
        cursor = start
        for piece in pieces:
            span = (end - start) * len(piece) / total
            lines = textwrap.wrap(piece, max_chars) or [piece]
            cues.append({"index": len(cues) + 1, "start": round(cursor, 3), "end": round(cursor + span, 3),
                         "text": "\n".join(lines), "scene_number": scene["scene_number"]})
            cursor += span
    return cues


def to_srt(cues):
    blocks = [f"{c['index']}\n{_clock_srt(c['start'])} --> {_clock_srt(c['end'])}\n{c['text']}\n" for c in cues]
    return "\n".join(blocks)


def to_ass(cues, width, height, portrait, font="DejaVu Sans", outlined=False):
    """An ASS file with a readable style. The bottom margin keeps captions above the phone interface."""
    font_size = round(height * (0.030 if portrait else 0.045))
    margin_v = round(height * (0.085 if portrait else 0.045))
    if outlined:
        style = (f"Style: Default,{font},{font_size},&H00FFFFFF,&H000000FF,&H003A0E16,&H00000000,-1,0,0,0,100,100,0,0,1,"
                 f"{round(font_size * 0.16)},{round(font_size * 0.07)},2,{round(width * 0.06)},{round(width * 0.06)},"
                 f"{margin_v},1\n\n")
    else:
        style = (f"Style: Default,{font},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,"
                 f"{round(font_size * 0.25)},0,2,{round(width * 0.06)},{round(width * 0.06)},{margin_v},1\n\n")
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        + style +
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for cue in cues:
        text = cue["text"].replace("{", "(").replace("}", ")").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{_clock_ass(cue['start'])},{_clock_ass(cue['end'])},Default,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"
