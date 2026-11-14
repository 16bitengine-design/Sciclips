"""Checks scripts and storyboards against the project's requirements."""
import re

from content.script_generator import EXPERIMENT_TEMPLATES, count_words
from content.storyboard_generator import ANIMATION_TYPES, MIN_SCENE_SECONDS, TRANSITIONS

WHAT_IF_KINDS = {"correct_procedure", "overlooked", "what_changes", "consequences", "why", "prevention"}
REQUIRED_KINDS = {
    ("explainer", "short"): {"hook", "demonstration", "conclusion"},
    ("explainer", "long"): {"hook", "intro", "question", "answer", "explanation_l2", "explanation_l3",
                             "demonstration", "terminology", "application", "limitation", "conclusion"},
    ("what_if", "short"): {"hook"} | WHAT_IF_KINDS,
    ("what_if", "long"): {"hook", "scenario_intro", "limitation", "conclusion"} | WHAT_IF_KINDS,
}
TOP_LEVEL_TEXT = ("title", "hook", "introduction", "scientific_question", "conclusion")
TOP_LEVEL_LISTS = ("terminology", "applications", "assumptions_limitations", "sources")
# Short explainer sections that may be trimmed to fit the time limit.
TRIMMABLE = {"terminology", "application", "intro"}


# --- house voice: videos speak in our own plain words and never talk about sources ------------------
BANNED_PHRASES = [
    r"\bsources?\b", r"\bcitations?\b", r"\bcite[sd]?\b", r"\breferences?\b", r"\bteaching materials\b",
    r"\b(studies|research|experts?) (shows?|says?|found|finds?)\b",
    r"\baccording to (the )?(sources?|studies|study|article|page|report|research)\b",
    r"\b(NASA|NIST|RSC|Royal Society of Chemistry|Wikipedia)\s+(describes|explains|says|states|reports|shows|notes)\b",
]
ATTRIBUTION = re.compile(r"According to ([A-Z][^:,.]{1,60})[:,]")


def check_house_voice(script, record):
    """Errors for any spoken or shown text that cites sources, or credits a person the record does not list."""
    errors = []
    allowed = {a.get("by") for a in record.get("attributions", [])}
    for section in script.get("sections", []):
        for field in ("narration", "on_screen_text"):
            text = str(section.get(field, ""))
            for name in ATTRIBUTION.findall(text):
                if name.strip() not in allowed:
                    errors.append(f"{section.get('id')}: credits '{name.strip()}', who is not listed in the record's attributions.")
            plain = ATTRIBUTION.sub("", text)
            for pattern in BANNED_PHRASES:
                if re.search(pattern, plain, re.IGNORECASE):
                    errors.append(f"{section.get('id')}: {field} uses source language. Say it in plain words.")
                    break
    return errors


def validate_script(script, record, rendering):
    """Returns {"errors": [...], "warnings": [...]}."""
    errors, warnings = [], []
    for field in TOP_LEVEL_TEXT:
        if not script.get(field):
            errors.append(f"Script is missing '{field}'.")
    for field in TOP_LEVEL_LISTS:
        if not script.get(field):
            errors.append(f"Script is missing '{field}'.")
    if record.get("equations") and not script.get("equations"):
        errors.append("Script is missing the equations.")

    errors.extend(check_house_voice(script, record))

    kinds = {s["kind"] for s in script.get("sections", [])}
    required = set(REQUIRED_KINDS[(script["variant"], script["format"])])
    if script["format"] == "short" and script["variant"] == "explainer":
        required -= TRIMMABLE
    if record.get("equations") and script["variant"] == "explainer" and script["format"] == "long":
        required.add("equation")
    if record.get("template") in EXPERIMENT_TEMPLATES and record.get("safety_considerations"):
        required.add("safety")
    for kind in sorted(required - kinds):
        errors.append(f"Script is missing a '{kind}' section.")

    known_claims = {c["id"] for c in record.get("claims", [])}
    used = set()
    for section in script.get("sections", []):
        if not section.get("narration"):
            errors.append(f"Section {section.get('id')} has no narration.")
        for cid in section.get("claim_ids", []):
            used.add(cid)
            if cid not in known_claims:
                errors.append(f"Section {section['id']} refers to unknown claim '{cid}'.")
    if script["variant"] == "explainer":
        for cid in sorted(known_claims - used):
            warnings.append(f"Claim {cid} is not illustrated by any section.")

    if script["word_count"] != sum(count_words(s["narration"]) for s in script.get("sections", [])):
        errors.append("word_count does not match the narration.")

    limits = rendering[script["format"]]
    duration = script["estimated_duration_seconds"]
    if duration > limits["max_duration_seconds"]:
        errors.append(f"Estimated {duration} s is over the {limits['max_duration_seconds']} s limit.")
    if duration < limits["min_duration_seconds"]:
        warnings.append(f"Estimated {duration} s is under the {limits['min_duration_seconds']} s target; "
                        "add more material to the topic record for a fuller video.")
    if not script.get("human_review_required"):
        errors.append("human_review_required must stay true.")
    return {"errors": errors, "warnings": warnings}


def validate_storyboard(storyboard, script, record, rendering):
    errors, warnings = [], []
    scenes = storyboard.get("scenes", [])
    if not scenes:
        return {"errors": ["Storyboard has no scenes."], "warnings": []}
    known_claims = {c["id"] for c in record.get("claims", [])}
    section_ids = {s["id"] for s in script["sections"]}
    scene_sections = set()
    expected_aspect = "9:16" if script["format"] == "short" else "16:9"

    for index, scene in enumerate(scenes, start=1):
        label = f"Scene {scene.get('scene_number', index)}"
        if scene.get("scene_number") != index:
            errors.append(f"{label}: scene numbers must run 1, 2, 3... without gaps.")
        for field in ("narration", "animation_type", "visual_elements", "camera", "duration_seconds",
                      "transition", "sound", "layout"):
            if field not in scene or scene[field] in ("", None, []):
                errors.append(f"{label}: missing '{field}'.")
        if scene.get("animation_type") not in ANIMATION_TYPES:
            errors.append(f"{label}: unknown animation type '{scene.get('animation_type')}'.")
        if scene.get("transition") not in TRANSITIONS:
            errors.append(f"{label}: unknown transition '{scene.get('transition')}'.")
        if scene.get("duration_seconds", 0) < MIN_SCENE_SECONDS:
            errors.append(f"{label}: shorter than {MIN_SCENE_SECONDS} seconds.")
        if scene.get("layout", {}).get("aspect") != expected_aspect:
            errors.append(f"{label}: layout aspect must be {expected_aspect}.")
        for claim in scene.get("claims_illustrated", []):
            if claim["id"] not in known_claims:
                errors.append(f"{label}: unknown claim '{claim['id']}'.")
        scene_sections.add(scene.get("section_id"))

    for missing in sorted(section_ids - scene_sections):
        errors.append(f"Section {missing} has no scene.")

    estimate = script["estimated_duration_seconds"]
    total = storyboard.get("total_duration_seconds", 0)
    if total < estimate * 0.95 or total > estimate * 1.5 + 10:
        errors.append(f"Storyboard length {total} s does not fit the script estimate {estimate} s.")
    limit = rendering[script["format"]]["max_duration_seconds"]
    if total > limit:
        errors.append(f"Storyboard length {total} s is over the {limit} s limit.")
    return {"errors": errors, "warnings": warnings}
