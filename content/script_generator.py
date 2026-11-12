"""Builds video scripts from a checked topic record using fixed templates.

No AI service is used and no new scientific facts are added: every sentence
of narration is taken from the topic record. If the record is thin, the
script is thin. Quality comes from the research record, not from this code.
"""
import json
import math
import os
import re
from pathlib import Path

from audio import voice_style
from content.topic_manager import EXPERIMENT_TEMPLATES

BASE_WORDS_PER_SECOND = 2.5  # about 150 spoken words per minute at normal speed
SCENE_PADDING_SECONDS = 0.5  # a short pause is added after every scene
CHUNK_WORDS = {"short": 30, "long": 40}  # how many words go into one scene
TIMING_MARGIN_SECONDS = 2.0  # short videos are trimmed to finish this far under the limit
WHAT_IF_KEYS = ("title", "correct", "overlooked", "what_changes", "consequences", "why",
                "prevention", "claim_ids")
WHAT_IF_PARTS = (
    ("correct_procedure", "The correct approach.", "correct"),
    ("overlooked", "What is overlooked.", "overlooked"),
    ("what_changes", "What changes scientifically.", "what_changes"),
    ("consequences", "The consequences.", "consequences"),
    ("why", "Why this happens.", "why"),
    ("prevention", "How to prevent it.", "prevention"),
)
SHOW_STEPS_FILE = Path(__file__).resolve().parents[1] / "config" / "show_steps.json"
SHORT_TRIM_ORDER = ("terminology", "application", "intro")
VARIANTS = ("explainer", "what_if")
FORMATS = ("short", "long")


class ScriptError(Exception):
    """Raised when a script cannot be built safely."""


def count_words(text):
    return len(text.split())


def effective_speed(rendering):
    """Speaking speed from the config, times the chosen voice profile's pace."""
    settings = rendering.get("narration", {})
    speed = float(settings.get("speaking_speed", 1.0))
    name = os.environ.get("VOICE_PROFILE") or settings.get("profile")
    if name:
        try:
            speed *= float(voice_style.get_profile(name)["speed"])
        except (voice_style.VoiceStyleError, FileNotFoundError, KeyError):
            pass
    return speed


def words_per_second(rendering):
    return BASE_WORDS_PER_SECOND * effective_speed(rendering)


def first_sentence(text):
    text = text.strip()
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


def join_names(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def complete_what_if_scenarios(record):
    return [s for s in record.get("what_if_scenarios", [])
            if isinstance(s, dict) and all(k in s for k in WHAT_IF_KEYS)]


def available_variants(record):
    variants = ["explainer"]
    if complete_what_if_scenarios(record):
        variants.append("what_if")
    return variants


# ---- claim helpers --------------------------------------------------------
def _is_model_claim(claim):
    if claim["kind"] in ("law", "mathematical_model"):
        return True
    return claim["kind"] == "established_fact" and bool(claim.get("equation_ids"))


def _model_claim_ids(record):
    return [c["id"] for c in record.get("claims", []) if _is_model_claim(c)]


def _evidence_claim_ids(record):
    return [c["id"] for c in record.get("claims", []) if not _is_model_claim(c)]


def _equation_claim_ids(record, equation_id):
    return [c["id"] for c in record.get("claims", []) if equation_id in c.get("equation_ids", [])]


def _eq_text(eq):
    return eq.get("latex") or eq.get("equation", "")


def _key_equation(record):
    eqs = record.get("equations", [])
    if not eqs:
        return None
    wanted = record.get("key_equation_id")
    for eq in eqs:
        if eq.get("id") == wanted:
            return eq
    return eqs[-1]


def _default_variant(record):
    return (record.get("simulation") or {}).get("default_variant")


def _scenario_variant(record, scenario, kind):
    chosen = (scenario.get("simulation") or {}).get(kind)
    return chosen or _default_variant(record)


def _equation_narration(eq):
    """Spoken form of an equation. Chemical arrows are spoken as 'gives'."""
    if eq.get("type") == "chemical":
        return "The reaction: " + eq["equation"].replace("->", "gives") + "."
    return f"The key relationship, {eq['name']}: {_eq_text(eq)}."


def _diagram_for(record, kind, scenario=None):
    chosen = ((scenario or {}).get("diagram") or {}).get(kind)
    return chosen or (record.get("diagrams") or {}).get(kind)


def _term_cards(record, limit=None):
    cards = [{"term": v["name"], "symbol": v["symbol"], "unit": v["unit"]} for v in record.get("variables", [])]
    return cards[:limit] if limit else cards


def _terminology(record):
    return [{"term": v["name"],
             "definition": f"{v['name']}, symbol {v['symbol']}, measured in {v['unit']}."}
            for v in record.get("variables", [])]


# ---- section builder ----------------------------------------------------
class _Sections:
    def __init__(self):
        self.items = []
        self.counts = {}

    def add(self, kind, title, narration, claim_ids=None, on_screen=None, data=None, lead=""):
        """`lead` is a spoken lead-in ("The consequences."). It is spoken but not shown as the caption."""
        number = self.counts.get(kind, 0) + 1
        self.counts[kind] = number
        content = " ".join(narration.split())
        narration = (lead + " " + content).strip() if lead else content
        self.items.append({
            "id": f"{kind}-{number}",
            "kind": kind,
            "title": title,
            "narration": narration,
            "on_screen_text": on_screen if on_screen is not None else first_sentence(content),
            "claim_ids": list(claim_ids or []),
            "data": dict(data or {}),
        })


def _add_safety(s, record):
    if record.get("template") in EXPERIMENT_TEMPLATES and record.get("safety_considerations"):
        s.add("safety", "Safety", record["safety_considerations"], lead="Safety.",
              data={"items": record.get("hazards", [])})


def _need(record, field):
    if not record.get(field):
        raise ScriptError(f"Topic record has no '{field}', which this script needs.")
    return record[field]


# ---- explainer scripts --------------------------------------------------
def _squash(text):
    return " ".join(str(text).split())


def _reusable_text(record):
    """All record text that narration is allowed to quote word for word."""
    parts = list((record.get("scientific_explanation") or {}).values())
    parts += list(record.get("supporting_evidence", []))
    parts += [record.get("principle_statement", ""), record.get("central_question", "")]
    parts += list(record.get("practical_applications", []))
    for m in record.get("misconceptions", []):
        parts += [m.get("statement", ""), m.get("correction", "")]
    return _squash(" ".join(str(p) for p in parts))


def _show_steps(record):
    """The 'say this while showing that' steps for a topic.

    They come from config/show_steps.json when the topic has an entry there. Every line must be
    copied word for word from the topic record, so no new science is introduced. Without an entry,
    the first explanation is simply split into sentences and each one is shown over the simulation.
    """
    steps = []
    try:
        with open(SHOW_STEPS_FILE, encoding="utf-8") as handle:
            steps = json.load(handle).get(record.get("id"), [])
    except (OSError, ValueError, AttributeError):
        steps = []
    if steps:
        haystack = _reusable_text(record)
        for step in steps:
            if _squash(step.get("line", "")) not in haystack:
                raise ScriptError(f"show_steps line is not in the topic record: {step.get('line', '')[:60]}")
        return [{"line": _squash(x["line"]), "variant": x.get("variant")} for x in steps]
    sentences = re.split(r"(?<=[.!?])\s+", _need(record, "scientific_explanation")["level_1"].strip())
    return [{"line": x, "variant": None} for x in sentences[:4]]


def _short_explainer(record):
    """Show, don't explain: the question, a few short lines spoken over the simulation, then the takeaway."""
    s = _Sections()
    expl = _need(record, "scientific_explanation")
    angle = (record.get("short_video_potential") or {}).get("angle") or record["title"]
    s.add("hook", "Opening question", _need(record, "central_question"), on_screen=angle)
    steps = _show_steps(record)
    for index, step in enumerate(steps):
        ids = []
        if index == 0:
            ids += _model_claim_ids(record)
        if index == len(steps) - 1:
            ids += _evidence_claim_ids(record)
        s.add("demonstration", "Demonstration", step["line"], ids,
              data={"simulation_variant": step["variant"] or _default_variant(record)})
    _add_safety(s, record)
    closing = record.get("principle_statement") or first_sentence(expl["level_2"])
    s.add("conclusion", "Conclusion", closing, lead="In short:")
    return s.items


def _long_explainer(record):
    s = _Sections()
    expl = _need(record, "scientific_explanation")
    s.add("hook", "Opening question", _need(record, "central_question"), on_screen=record["title"])
    s.add("intro", "Introduction",
          f"In this video we answer one question from {_need(record, 'subject_area')}. We start with a simple "
          "explanation, then add the science, then the technical details, and finish with applications and limits.")
    s.add("question", "The question", record["central_question"], lead="Let us state the question clearly.")
    model_ids = _model_claim_ids(record)
    s.add("answer", "Simple explanation", expl["level_1"], model_ids, lead="Simple explanation.",
          data={"diagram": _diagram_for(record, "answer")})
    s.add("explanation_l2", "Scientific explanation", expl["level_2"], model_ids, lead="Now the scientific explanation.",
          data={"diagram": _diagram_for(record, "explanation_l2")})
    s.add("explanation_l3", "Technical explanation", expl["level_3"], model_ids, lead="Now the technical explanation.")
    for item in _need(record, "supporting_evidence"):
        s.add("demonstration", "Evidence", item, _evidence_claim_ids(record),
              data={"simulation_variant": _default_variant(record)}, lead="Evidence.")
    terms = _terminology(record)
    if not terms:
        raise ScriptError("Topic record has no variables to define.")
    s.add("terminology", "Key terms", "Key terms. " + " ".join(t["definition"] for t in terms),
          on_screen="Key terms and units", data={"terms": _term_cards(record)})
    for eq in record.get("equations", []):
        s.add("equation", eq["name"], f"{eq['name']}: {_eq_text(eq)}.", _equation_claim_ids(record, eq["id"]),
              on_screen=_eq_text(eq))
    s.add("application", "Real-world use", " ".join(_need(record, "practical_applications")), lead="Where this matters.")
    for m in record.get("misconceptions", []):
        s.add("misconception", "Common misconception",
              f'A common misconception is: "{m["statement"]}" Here is the correction. {m["correction"]}',
              on_screen=m["statement"], data={"statement": m["statement"], "correction": m["correction"]})
    s.add("limitation", "Assumptions and limits", " ".join(_need(record, "assumptions")), lead="Assumptions and limits.",
          data={"items": list(record["assumptions"])})
    _add_safety(s, record)
    closing = record.get("principle_statement") or first_sentence(expl["level_2"])
    s.add("conclusion", "Conclusion", closing, lead="To summarise:")
    return s.items


# ---- what-if scripts ------------------------------------------------------
def _add_what_if_parts(s, scenario, record):
    for kind, lead, key in WHAT_IF_PARTS:
        data = {"scenario_title": scenario["title"], "correct": scenario["correct"],
                "overlooked": scenario["overlooked"],
                "simulation_variant": _scenario_variant(record, scenario, kind),
                "diagram": _diagram_for(record, kind, scenario)}
        s.add(kind, lead.rstrip("."), scenario[key], scenario["claim_ids"], data=data, lead=lead)


def _short_what_if(record):
    scenarios = complete_what_if_scenarios(record)
    if not scenarios:
        raise ScriptError("No complete what-if scenario in the topic record.")
    scenario = scenarios[0]
    s = _Sections()
    s.add("hook", "What if we overlook this?", scenario["title"], on_screen="What happens if we overlook this?")
    _add_what_if_parts(s, scenario, record)
    _add_safety(s, record)
    return s.items


def _long_what_if(record):
    scenarios = complete_what_if_scenarios(record)
    if not scenarios:
        raise ScriptError("No complete what-if scenario in the topic record.")
    s = _Sections()
    s.add("hook", "What if we overlook something?",
          f"What happens if we overlook something? Today's topic: {record['title']}",
          on_screen="What happens if we overlook something?")
    for scenario in scenarios:
        s.add("scenario_intro", "Scenario", scenario["title"])
        _add_what_if_parts(s, scenario, record)
    s.add("limitation", "Assumptions and limits", " ".join(_need(record, "assumptions")), lead="Assumptions and limits.",
          data={"items": list(record["assumptions"])})
    _add_safety(s, record)
    s.add("conclusion", "Conclusion", scenarios[-1]["prevention"], lead="To summarise:")
    return s.items


BUILDERS = {
    ("explainer", "short"): _short_explainer,
    ("explainer", "long"): _long_explainer,
    ("what_if", "short"): _short_what_if,
    ("what_if", "long"): _long_what_if,
}


# ---- final assembly ---------------------------------------------------------
def _duration(sections, wps, video_format="short"):
    """Estimated running time: speaking time plus the pause after each scene."""
    words = sum(count_words(x["narration"]) for x in sections)
    scenes = sum(max(1, math.ceil(count_words(x["narration"]) / CHUNK_WORDS[video_format])) for x in sections)
    return round(words / wps + scenes * SCENE_PADDING_SECONDS, 1)


def generate_script(record, video_format, variant, rendering, science_result):
    """Returns a script dict, or raises ScriptError."""
    if science_result.get("status") == "failed":
        raise ScriptError("Science validation failed; no script is produced for this topic.")
    if video_format not in FORMATS:
        raise ScriptError(f"Unknown format '{video_format}'.")
    if variant not in available_variants(record):
        raise ScriptError(f"Variant '{variant}' is not available for topic {record.get('id')}.")

    sections = BUILDERS[(variant, video_format)](record)
    wps = words_per_second(rendering)
    limits = rendering[video_format]

    branding = rendering.get("branding", {})
    if video_format == "long" and branding.get("outro", {}).get("long"):
        sections.append({
            "id": "outro-1", "kind": "outro", "title": "Outro", "narration": "Thanks for watching.",
            "on_screen_text": branding.get("channel_name", ""), "claim_ids": [],
            "data": {"channel": branding.get("channel_name", ""), "line": branding.get("outro_line", "")}})
    if video_format == "short":
        for kind in SHORT_TRIM_ORDER:
            if _duration(sections, wps, video_format) > limits["max_duration_seconds"] - TIMING_MARGIN_SECONDS:
                sections = [x for x in sections if x["kind"] != kind]
    estimate = _duration(sections, wps, video_format)
    if estimate > limits["max_duration_seconds"]:
        raise ScriptError(f"Script would run about {estimate:.0f} s, over the {limits['max_duration_seconds']} s limit.")

    by_kind = lambda *kinds: [x for x in sections if x["kind"] in kinds]  # noqa: E731
    hook = by_kind("hook")[0]
    intro = by_kind("intro")
    scenarios = complete_what_if_scenarios(record)
    key = _key_equation(record)
    title = record["title"]
    if variant == "what_if" and video_format == "short":
        title = scenarios[0]["title"]

    return {
        "topic_id": record["id"],
        "format": video_format,
        "variant": variant,
        "title": title,
        "hook": hook["narration"],
        "introduction": intro[0]["narration"] if intro else f"A look at {record['subject_area']}.",
        "scientific_question": record["central_question"],
        "explanation_section_ids": [x["id"] for x in by_kind("answer", "explanation_l2", "explanation_l3")],
        "visual_demonstration": (record.get("visual_hints") or {}).get("demonstration", []),
        "terminology": _terminology(record),
        "equations": [{"id": e["id"], "name": e["name"], "text": _eq_text(e)} for e in record.get("equations", [])],
        "key_equation_id": key["id"] if key else None,
        "applications": record.get("practical_applications", []),
        "assumptions_limitations": record.get("assumptions", []),
        "safety_notice": record.get("safety_considerations", ""),
        "conclusion": by_kind("conclusion", "prevention")[-1]["narration"],
        "sources": [{k: s.get(k) for k in ("id", "title", "publisher", "url", "date_accessed")}
                    for s in record.get("sources", [])],
        "sections": sections,
        "word_count": sum(count_words(x["narration"]) for x in sections),
        "estimated_duration_seconds": estimate,
        "science_status": science_result.get("status"),
        "human_review_required": True,
        "generated_by": "deterministic templates (no AI service)",
        "disclaimer": "Automated checks only. This is not expert peer review.",
    }


def script_to_text(script):
    lines = [f"TITLE: {script['title']}",
             f"FORMAT: {script['format']}   VARIANT: {script['variant']}",
             f"ESTIMATED LENGTH: {script['estimated_duration_seconds']} seconds ({script['word_count']} words)",
             f"SCIENCE CHECK STATUS: {script['science_status']} (human review still required)", ""]
    for section in script["sections"]:
        lines += [f"[{section['id']}] {section['title']}",
                  f"  Narration: {section['narration']}",
                  f"  On screen: {section['on_screen_text']}",
                  f"  Claims: {', '.join(section['claim_ids']) or 'none'}", ""]
    lines.append("SOURCES")
    for src in script["sources"]:
        lines.append(f"- {src['title']} ({src['publisher']}) {src['url']} accessed {src['date_accessed']}")
    return "\n".join(lines) + "\n"
