"""Turns a script into a scene-by-scene storyboard.

The storyboard describes WHAT to show. Later stages draw it. Vertical and
horizontal versions are composed separately (layout notes differ), not
cropped from one another.
"""
import re

from content.script_generator import count_words, words_per_second

ANIMATION_TYPES = ("2d_diagram", "2d_equation", "3d_scene", "simulation", "comparison",
                   "graph", "motion_graphics", "text_card")
TRANSITIONS = ("fade in", "fade", "cut", "wipe", "fade out")
MIN_SCENE_SECONDS = 3.0

KIND_TO_ANIMATION = {
    "hook": "3d_scene", "intro": "text_card", "question": "text_card", "answer": "2d_diagram",
    "explanation_l2": "2d_diagram", "explanation_l3": "2d_equation", "demonstration": "simulation",
    "terminology": "text_card", "equation": "2d_equation", "application": "motion_graphics",
    "misconception": "comparison", "limitation": "text_card", "safety": "text_card",
    "conclusion": "text_card", "sources": "text_card", "scenario_intro": "text_card",
    "correct_procedure": "simulation", "overlooked": "simulation", "what_changes": "comparison",
    "consequences": "simulation", "why": "2d_diagram", "prevention": "text_card",
}

LAYOUTS = {
    "short": ("9:16", "stack elements vertically; keep key objects in the central 60% of the frame; "
                      "captions in the lower third, above the platform interface area"),
    "long": ("16:9", "use side-by-side layouts; captions along the bottom; leave room for labels beside objects"),
}


def split_into_chunks(text, max_words):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], []
    for sentence in sentences:
        if current and count_words(" ".join(current + [sentence])) > max_words:
            chunks.append(" ".join(current))
            current = []
        current.append(sentence)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _visuals(section, record):
    kind = section["kind"]
    hints = record.get("visual_hints") or {}
    if kind == "hook":
        return hints.get("hook") or ["title card showing the central question"]
    if kind in ("demonstration", "correct_procedure", "overlooked", "consequences"):
        base = list(hints.get("demonstration") or ["labelled diagram of the main observation"])
        if kind == "correct_procedure":
            base.append("label: correct condition")
        if kind == "overlooked":
            base.append("label: overlooked or incorrect condition")
        if kind == "consequences":
            base.append("highlight the resulting difference")
        return base
    if kind == "equation":
        return [section["on_screen_text"], "variable labels with units"]
    if kind == "terminology":
        return [f"label: {v['symbol']} = {v['name']} ({v['unit']})" for v in record.get("variables", [])][:6] \
            or ["term list"]
    if kind in ("what_changes", "misconception"):
        return ["left panel: correct condition", "right panel: overlooked or incorrect condition",
                "highlight what differs"]
    if kind == "sources":
        return ["list of source titles and publishers"]
    return ["title text with a simple labelled diagram"]


def _camera(animation):
    if animation == "3d_scene":
        return "slow push-in on the main object (lightweight low-poly 3D)"
    if animation == "simulation":
        return "fixed camera; split screen when comparing two conditions"
    return "none (2D layout)"


def _claims(record, claim_ids):
    texts = {c["id"]: c["text"] for c in record.get("claims", [])}
    return [{"id": cid, "text": texts[cid]} for cid in claim_ids if cid in texts]


def generate_storyboard(script, record, rendering):
    video_format = script["format"]
    wps = words_per_second(rendering)
    max_words = 30 if video_format == "short" else 40
    aspect, composition = LAYOUTS[video_format]
    cfg = rendering[video_format]

    scenes = []
    sections = script["sections"]
    for s_index, section in enumerate(sections):
        animation = KIND_TO_ANIMATION[section["kind"]]
        chunks = split_into_chunks(section["narration"], max_words)
        for c_index, chunk in enumerate(chunks):
            number = len(scenes) + 1
            is_first = number == 1
            is_last = s_index == len(sections) - 1 and c_index == len(chunks) - 1
            if is_first:
                transition = "fade in"
            elif is_last:
                transition = "fade out"
            elif animation == "comparison":
                transition = "wipe"
            elif c_index > 0:
                transition = "cut"
            else:
                transition = "fade"
            sound = "narration"
            if animation in ("3d_scene", "simulation"):
                sound += "; one subtle sound-effect cue (self-made or royalty-free only)"
            scenes.append({
                "scene_number": number,
                "section_id": section["id"],
                "section_kind": section["kind"],
                "section_title": section["title"],
                "data": section.get("data", {}),
                "narration": chunk,
                "on_screen_text": section["on_screen_text"] if c_index == 0 else "",
                "subtitles": True,
                "animation_type": animation,
                "visual_elements": _visuals(section, record),
                "camera": _camera(animation),
                "duration_seconds": max(MIN_SCENE_SECONDS, round(count_words(chunk) / wps, 1)),
                "transition": transition,
                "sound": sound,
                "claims_illustrated": _claims(record, section["claim_ids"]),
                "layout": {"aspect": aspect, "resolution": f"{cfg['width']}x{cfg['height']}",
                           "composition": composition},
            })
    return {
        "topic_id": script["topic_id"],
        "format": video_format,
        "variant": script["variant"],
        "resolution": f"{cfg['width']}x{cfg['height']}",
        "fps": cfg["fps"],
        "scenes": scenes,
        "total_duration_seconds": round(sum(sc["duration_seconds"] for sc in scenes), 1),
        "human_review_required": True,
    }
