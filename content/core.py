"""content: merged module (was 6 files: ai_writer, topic_manager, script_generator, storyboard_generator, script_validator, topic_scout).

The old module names still work: the package __init__ registers each of them as an alias of this module.
"""
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio import voice_style
from research import science_validator as science
from research.source_collector import domain_tier


# ============================================================================
# from content/ai_writer.py
# ============================================================================
# Optional Gemini-powered visual sequence planner with strict safety checks.








GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_MODEL = "gemini-3.8-flash"
MIN_STEPS, MAX_STEPS = 3, 6

# What each picture shows, so the model can match a sentence to the right one.
SIM_VARIANTS = {
    "free_fall": {
        "vacuum": "hammer and feather fall together with no air",
        "with_air": "hammer and feather fall in air; the feather lags",
        "air_vs_vacuum": "air and vacuum side by side with a speed graph",
        "terminal_speed": "two people falling, air push growing until it equals gravity, small area versus big parachute",
        "wrong_mass_model": "a deliberately wrong model where heavier means faster",
    },
    "gas_release": {
        "open": "open container, gas bubbles escape",
        "sealed": "sealed container, pressure builds",
        "sealed_pop": "sealed container, the lid pops off",
        "balance_open": "open container on a balance, the reading falls",
        "balance_sealed": "balloon-sealed container on a balance, the reading stays the same",
    },
}


def ai_enabled():
    return os.environ.get("SCICLIPS_AI") == "1" and bool(os.environ.get("SCICLIPS_GEMINI_API_KEY"))


def sentences_of(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join(str(text).split())) if s]


class _KeepPost(urllib.request.HTTPRedirectHandler):
    """Follows redirects and keeps the request a POST with its body (the standard library would turn it into an empty GET)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code not in (301, 302, 303, 307, 308):
            return None
        same_host = urlparse(newurl).hostname == urlparse(req.full_url).hostname
        kept = {k: v for k, v in req.header_items() if k.lower() != "content-length" and (same_host or k.lower() != "authorization")}
        return urllib.request.Request(newurl, data=req.data, headers=kept, method=req.get_method())


def _post(payload, token, timeout=60, url=None):
    target_url = url or os.environ.get("SCICLIPS_GEMINI_ENDPOINT") or GEMINI_ENDPOINT
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    request = urllib.request.Request(
        target_url, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    opener = urllib.request.build_opener(_KeepPost)
    try:
        with opener.open(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
            response_url = response.geturl()
            content_type = response.headers.get("Content-Type", "unknown")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"the AI service said {error.code}: {error.read()[:200]!r}") from error
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as error:
        print(f"AI service diagnostic: HTTP {status}, content-type {content_type}, url {response_url}, "
              f"first 300 bytes: {raw[:300]!r}", file=sys.stderr)
        raise RuntimeError(
            f"the AI service at {response_url} answered {status} "
            f"(content-type: {content_type}) with something that is not JSON: {raw[:160]!r}"
        ) from error


def _parse(reply_text):
    text = reply_text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    steps = data["steps"] if isinstance(data, dict) else data
    return steps


def check_steps(steps, haystack, variants):
    """Return clean steps, or None if anything is not allowed."""
    if not isinstance(steps, list) or not MIN_STEPS <= len(steps) <= MAX_STEPS:
        return None
    clean, seen = [], set()
    for step in steps:
        if not isinstance(step, dict):
            return None
        line = " ".join(str(step.get("line", "")).split())
        variant = step.get("variant")
        if not line or line not in haystack or variant not in variants or line in seen:
            return None
        seen.add(line)
        clean.append({"line": line, "variant": variant})
    return clean


def propose_steps(record, haystack, kind, hook_line=None, model=None):
    """Ask the model for show steps. Returns a list of {line, variant}, or None if it did not work."""
    variants = SIM_VARIANTS.get(kind)
    token = os.environ.get("SCICLIPS_GEMINI_API_KEY")
    if not variants or not token:
        return None
    lines = sentences_of(haystack)
    prompt = {
        "topic": record.get("title"), "question": record.get("central_question"),
        "already_spoken_first": hook_line,
        "allowed_lines": lines, "pictures": variants,
        "rules": ["Choose 4 to 6 lines from allowed_lines and put them in the best teaching order.",
                  "Copy each line EXACTLY, word for word. Never write or change a line.",
                  "Together the lines should answer what, why, how, where, when and who, in plain words a "
                  "seven year old can follow, and show instead of explaining.",
                  "Pair every line with the picture (a key of `pictures`) that best matches what the line says.",
                  "Do not repeat a line. Do not use the line already spoken first.",
                  'Reply with JSON only: {"steps": [{"line": "...", "picture": "..."}]}'],
    }
    endpoint = os.environ.get("SCICLIPS_GEMINI_ENDPOINT") or GEMINI_ENDPOINT
    payload = {"model": model or os.environ.get("SCICLIPS_GEMINI_MODEL", DEFAULT_MODEL), "temperature": 0.2,
               "max_tokens": 900, "response_format": {"type": "json_object"},
               "messages": [
                   {"role": "system", "content": "You plan short science videos for children aged 7 to 10. "
                    "You only choose and order sentences that already exist. You never add science."},
                   {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]}
    try:
        reply = _post(payload, token)
        steps = _parse(reply["choices"][0]["message"]["content"])
        steps = [{"line": s.get("line"), "variant": s.get("picture", s.get("variant"))} for s in steps]
    except Exception as error:  # any problem at all means: use the normal writer
        print(f"AI writer skipped ({type(error).__name__}: {str(error)[:300]})", file=sys.stderr)
        return None
    clean = check_steps(steps, haystack, variants)
    if clean is None:
        print("AI writer skipped (its answer did not pass the safety checks)", file=sys.stderr)
    return clean


# ============================================================================
# from content/topic_manager.py
# ============================================================================
# Loads, checks and selects topics. Topic details live in topics/records/<id>.json.




ALLOWED_STATUSES = (
    "queued", "researched", "scripted", "storyboarded", "rendered",
    "awaiting_approval", "published", "failed",
)
EXPERIMENT_TEMPLATES = ("experiment", "chemistry_experiment")
LIST_FIELDS = ("sources", "claims", "equations", "assumptions", "variables",
               "practical_applications", "misconceptions", "what_if_scenarios")


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_template(root, name):
    return _load(Path(root) / "templates" / f"{name}.json")


def load_topic_record(root, topic_id):
    return _load(Path(root) / "topics" / "records" / f"{topic_id}.json")


def validate_topic_record(record, template):
    errors = []
    for field in template["required_fields"]:
        if field not in record or record[field] in (None, "", [], {}):
            errors.append(f"Topic is missing '{field}'.")
    for field in LIST_FIELDS:
        if field in record and not isinstance(record[field], list):
            errors.append(f"'{field}' must be a list.")
    if record.get("production_status") not in ALLOWED_STATUSES:
        errors.append(f"production_status must be one of {ALLOWED_STATUSES}.")
    if record.get("template") == "theory" and record.get("theory_status") not in ("theory", "hypothesis"):
        errors.append("theory_status must be 'theory' or 'hypothesis'.")
    if record.get("template") in EXPERIMENT_TEMPLATES:
        risk = record.get("risk_level")
        sim_only = record.get("simulation_only") is True
        if risk not in ("low", "medium", "high"):
            errors.append("risk_level must be low, medium or high.")
        if not sim_only and not record.get("procedure_steps"):
            errors.append("procedure_steps are required unless simulation_only is true.")
        if risk == "high":
            if not sim_only:
                errors.append("High-risk experiments must be simulation_only.")
            if record.get("procedure_steps"):
                errors.append("High-risk experiments must not include procedure_steps (animate only).")
    return errors


def select_next_topic(root, require_approval=False):
    """First queued topic that has not been produced yet. Returns the queue entry or None."""
    queue = _load(Path(root) / "topics" / "topic_queue.json")["topics"]
    produced = {p.get("topic_id") for p in
                _load(Path(root) / "records" / "production_history.json").get("productions", [])}
    approved = set(_load(Path(root) / "topics" / "approved_topics.json").get("approved_topic_ids", []))
    for entry in queue:
        if entry.get("status") != "queued" or entry.get("id") in produced:
            continue
        if require_approval and entry.get("id") not in approved:
            continue
        return entry
    return None


def set_status(root, topic_id, new_status):
    if new_status not in ALLOWED_STATUSES:
        raise ValueError(f"Unknown status '{new_status}'")
    path = Path(root) / "topics" / "topic_queue.json"
    data = _load(path)
    for entry in data["topics"]:
        if entry["id"] == topic_id:
            entry["status"] = new_status
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
            return
    raise KeyError(f"Topic '{topic_id}' not in queue")


def main(argv):
    root = "."
    command = argv[1] if len(argv) > 1 else "list"
    if command == "list":
        for entry in _load(Path(root) / "topics" / "topic_queue.json")["topics"]:
            print(f"{entry['id']}: {entry['title']} [{entry['status']}]")
    elif command == "next":
        entry = select_next_topic(root)
        print(entry["id"] if entry else "No eligible topic.")
    elif command == "validate":
        bad = 0
        for entry in _load(Path(root) / "topics" / "topic_queue.json")["topics"]:
            record = load_topic_record(root, entry["id"])
            problems = validate_topic_record(record, load_template(root, record.get("template", "principle")))
            print(f"{entry['id']}: {'OK' if not problems else 'PROBLEMS'}")
            for p in problems:
                print(f"  - {p}")
            bad += bool(problems)
        return 1 if bad else 0
    else:
        print("Usage: topic_manager.py [list|next|validate]")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))


# ============================================================================
# from content/script_generator.py
# ============================================================================
# Builds video scripts from a checked topic record using fixed templates.










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
    ("prevention", "What to do.", "prevention"),
)
AI_MAX_WORDS = 110  # keeps an AI-planned short video under the time limit
SHOW_STEPS_FILE = Path(__file__).resolve().parents[1] / "config" / "config.json"      # section "show_steps"
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
    for w in record.get("what_if_scenarios", []):
        parts += [w.get(k, "") for k in ("correct", "what_changes", "consequences", "why", "prevention")]
    return _squash(" ".join(str(p) for p in parts))


def _show_steps(record):
    """The 'say this while showing that' steps for a topic.

    They come from the show_steps section of config/config.json when the topic has an entry there. Every line must be
    copied word for word from the topic record, so no new science is introduced. Without an entry,
    the first explanation is simply split into sentences and each one is shown over the simulation.
    """
    steps = []
    try:
        with open(SHOW_STEPS_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
            if Path(SHOW_STEPS_FILE).name == "config.json":
                data = data.get("show_steps", {})
            steps = data.get(record.get("id"), [])
    except (OSError, ValueError, AttributeError):
        steps = []
    if steps:
        haystack = _reusable_text(record)
        for step in steps:
            if _squash(step.get("line", "")) not in haystack:
                raise ScriptError(f"show_steps line is not in the topic record: {step.get('line', '')[:60]}")
        return [{"line": _squash(x["line"]), "variant": x.get("variant")} for x in steps]
    if ai_enabled():
        kind = (record.get("simulation") or {}).get("kind")
        chosen = propose_steps(record, _reusable_text(record), kind, record.get("central_question"))
        if chosen and sum(len(x["line"].split()) for x in chosen) <= AI_MAX_WORDS:
            return chosen
    sentences = re.split(r"(?<=[.!?])\s+", _need(record, "scientific_explanation")["level_1"].strip())
    return [{"line": x, "variant": None} for x in sentences[:4]]


def _originator(record, line):
    """Name of the person to credit for a line, only when the topic record says so (record["attributions"])."""
    for item in record.get("attributions", []):
        if _squash(item.get("line", "")) and _squash(item["line"]) in line:
            return item.get("by")
    return None


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
        by = _originator(record, step["line"])
        s.add("demonstration", "Demonstration", step["line"], ids,
              data={"simulation_variant": step["variant"] or _default_variant(record)},
              lead=f"According to {by}:" if by else "")
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
        spoken = _equation_narration(eq) if eq.get("type") == "chemical" else f"{eq['name']}: {_eq_text(eq)}."
        s.add("equation", eq["name"], spoken, _equation_claim_ids(record, eq["id"]),
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


# ============================================================================
# from content/storyboard_generator.py
# ============================================================================
# Turns a script into a scene-by-scene storyboard.




ANIMATION_TYPES = ("2d_diagram", "2d_equation", "3d_scene", "simulation", "comparison",
                   "graph", "motion_graphics", "text_card")
TRANSITIONS = ("fade in", "fade", "cut", "wipe", "fade out")
MIN_SCENE_SECONDS = 3.0

KIND_TO_ANIMATION = {
    "hook": "3d_scene", "intro": "simulation", "question": "simulation", "answer": "2d_diagram",
    "explanation_l2": "2d_diagram", "explanation_l3": "2d_equation", "demonstration": "simulation",
    "terminology": "text_card", "equation": "2d_equation", "application": "motion_graphics",
    "misconception": "comparison", "limitation": "text_card", "safety": "text_card",
    "conclusion": "simulation", "sources": "text_card", "scenario_intro": "simulation",
    "correct_procedure": "simulation", "overlooked": "simulation", "what_changes": "comparison",
    "consequences": "simulation", "why": "2d_diagram", "prevention": "text_card", "outro": "text_card",
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
                "duration_seconds": max(MIN_SCENE_SECONDS, round(count_words(chunk) / wps + SCENE_PADDING_SECONDS, 1)),
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


# ============================================================================
# from content/script_validator.py
# ============================================================================
# Checks scripts and storyboards against the project's requirements.





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


# ============================================================================
# from content/topic_scout.py
# ============================================================================
# Finds and drafts new topics by itself, then lets the normal automatic checks decide whether to keep them.













PREFIX = {"physics": "physics", "chemistry": "chem", "biology": "bio", "earth-science": "earth", "astronomy": "astro"}
TEMPLATES = ("principle", "chemistry_experiment")
SUPPORTED_SIMULATIONS = {"free_fall": {"vacuum", "with_air", "air_vs_vacuum", "terminal_speed", "wrong_mass_model"},
                         "gas_release": {"open", "sealed", "sealed_pop", "balance_open", "balance_sealed"}}
REQUIRE_PICTURES = False   # scripts/scout_topic.py switches this on: every automatic topic must carry its own picture plan
MAX_REPAIRS = 2          # how many times the checks' complaints are fed back to the AI before an idea is dropped
MAX_QUEUED = 14        # a fortnight of topics is plenty; no AI calls are spent when the queue is this full
PAGE_CHARS = 7000
MIN_PAGE_CHARS = 1200


class ScoutError(Exception):
    """A reason this idea was dropped. Never stops the schedule."""


# ------------------------------------------------------------------ web pages
class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form"}

    def __init__(self):
        super().__init__()
        self.parts, self.depth = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth and data.strip():
            self.parts.append(data.strip())


def page_text(html):
    parser = _Text()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


def norm(text):
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).split())


def _json_from(reply):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip())
    try:
        return json.loads(text)
    except ValueError as error:
        raise ScoutError(f"the AI did not answer in the expected form ({error})") from error


# ------------------------------------------------------------------ ids and queue
def existing_titles(root):
    queue = json.loads((Path(root) / "topics" / "topic_queue.json").read_text(encoding="utf-8"))["topics"]
    return queue, [t.get("title", "") for t in queue]


def next_id(root, category):
    prefix = PREFIX[category]
    numbers = [int(m.group(1)) for p in (Path(root) / "topics" / "records").glob(f"{prefix}-*.json")
               if (m := re.match(rf"{prefix}-(\d+)$", p.stem))]
    return f"{prefix}-{max(numbers, default=0) + 1:03d}"


# ------------------------------------------------------------------ the AI steps
IDEA_RULES = (
    "Suggest ONE new science topic for short explainer videos for a general audience of all ages (a curious beginner can follow it, an adult still learns something) and that can be "
    "SHOWN with a simple demonstration (not just explained). It must be safe at home with everyday materials, and must "
    "not be about anything dangerous, medical or political. It must not repeat any title in `already_used`. "
    "Give 2 or 3 real web page addresses (https) from trusted sites that explain it (for example nasa.gov, noaa.gov, "
    "rsc.org, .edu, .gov, nature.com, aps.org). Reply with JSON only: "
    '{"title": "...", "central_question": "...", "category": "physics|chemistry|biology|earth-science|astronomy", '
    '"template": "principle|chemistry_experiment", "source_urls": ["https://..."]}')

DRAFT_RULES = """Write the topic record as ONE JSON object in exactly the same shape as `example_record`.
Rules, all checked automatically:
- Use ONLY facts stated on the pages in `pages`. Never add facts from memory. If the pages do not support a fact, leave it out.
- sources: one entry per page used (id s1, s2...), with the page's real title, publisher, url, date_published null, date_updated null,
  date_accessed = today, kind "education_resource". Every claim lists the source ids that support it.
- claims: 3 to 6 short claims, kind one of established_fact, law, theory, experimental_observation, mathematical_model. Plain wording, never "proven".
- equations: at least one. A non-chemical equation needs dimension_check {lhs, rhs} written ONLY with the units
  m kg s A K mol cd N J W Pa L g M (powers like m^-3), and the two sides must have the same units. Do NOT add numeric_checks.
  A chemical equation must have type "chemical" and balanced atoms, written with "->".
- Plain words anyone can follow in scientific_explanation.level_1 (no jargon, short sentences), more detail in level_2, precise in level_3.
- NEVER mention websites, organisations, 'sources', 'studies' or 'research shows' in any sentence a video could speak
  (scientific_explanation, supporting_evidence, practical_applications, misconceptions, what_if_scenarios, principle_statement).
- supporting_evidence and practical_applications are lists of plain sentences. principle_statement and domain_of_validity are required for the template 'principle'.
- what_if_scenarios: exactly 2 complete scenarios with all the fields shown in the example (omit their "simulation" and "diagram" keys).
- Safety: risk_level "low", hazards and safety_equipment lists, supervision_required true for experiments, production_status "queued".
- Include EVERY top-level key that example_record has (for example risk_level, hazards, safety_equipment, supervision_required, simulation_only, expected_results), filled in for this topic. The checks reject a record with any key missing.
- `template_requirements` is what the checks demand for this template. Include every field it requires, with exactly those key names, at the top level of the record.
- Do not include the keys simulation, scene3d, diagrams or attributions.
Reply with the JSON object only."""

VERIFY_RULES = (
    "For each claim, decide whether the page text of one of its listed sources states the same thing. Reply with JSON only: "
    '{"results": [{"id": "c1", "supported": true, "source_id": "s1", "quote": "an exact sentence copied word for word from that page"}]} '
    "The quote must be copied exactly from the page text and must be at least 8 words. If no page states it, set supported to false.")


def suggest_idea(ask, titles):
    reply = ask([{"role": "system", "content": "You plan a science education channel. Reply with JSON only."},
                 {"role": "user", "content": json.dumps({"already_used": titles, "task": IDEA_RULES}, ensure_ascii=False)}])
    idea = _json_from(reply)
    if idea.get("category") not in PREFIX or idea.get("template") not in TEMPLATES:
        raise ScoutError("the idea used an unknown category or template")
    if idea.get("template") == "chemistry_experiment" and idea.get("category") != "chemistry":
        raise ScoutError("only chemistry topics may use the chemistry template")
    urls = [u for u in idea.get("source_urls", []) if isinstance(u, str) and u.startswith("https://")]
    urls = [u for u in urls if domain_tier(u) == "preferred"][:3]
    if len(urls) < 2:
        raise ScoutError("fewer than 2 pages from trusted sites")
    if norm(idea.get("title", "")) in {norm(t) for t in titles}:
        raise ScoutError("that topic already exists")
    idea["source_urls"] = urls
    return idea


def download(fetch, urls, search=None, query=None):
    """Downloads the pages. Dead links are skipped; if fewer than 2 good pages remain, `search(query)` supplies trusted replacements."""
    pages, problems = {}, []

    def take(url):
        try:
            text = fetch(url)
        except Exception as error:
            problems.append(f"could not read {url} ({type(error).__name__}{' ' + str(error.code) if getattr(error, 'code', None) else ''})")
            return
        if len(text) < MIN_PAGE_CHARS:
            problems.append(f"the page at {url} had too little text")
            return
        pages[url] = text[:PAGE_CHARS]

    for url in urls:
        take(url)
    if len(pages) < 2 and search:
        try:
            found = list(search(query) or [])
        except Exception:
            found = []
        for url in found:
            if len(pages) >= 3:
                break
            if url not in pages and url not in urls and domain_tier(url) == "preferred":
                take(url)
    if len(pages) < 2:
        raise ScoutError(problems[0] if problems else "fewer than 2 readable pages")
    return pages


def pick_example(root, template):
    """An existing record that uses the same template, so the AI copies the right shape (chemistry needs safety keys)."""
    for path in sorted((Path(root) / "topics" / "records").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("template") == template:
            for key in ("simulation", "scene3d", "diagrams", "attributions", "scene_plan"):
                record.pop(key, None)
            return record
    return None


def template_requirements(root, name):
    """What the science checks demand for this template (shown to the AI so it includes every required field)."""
    try:
        return load_template(str(root), name)
    except Exception:
        return None


def draft_record(ask, idea, pages, example, today, requirements=None):
    payload = {"task": DRAFT_RULES, "today": today, "topic": {k: idea[k] for k in ("title", "central_question", "category", "template")},
               "pages": [{"url": u, "text": t} for u, t in pages.items()], "example_record": example}
    if requirements:
        payload["template_requirements"] = requirements
    return _json_from(ask([{"role": "system", "content": "You write careful, plain-spoken science records. Reply with JSON only."},
                           {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]))


TOPIC_SCOUT_ATTRIBUTION = re.compile(r"(^|(?<=[.!?]\s))(?:According to|As (?:stated|reported|explained|noted) by|As per)\s+[^:,;.]{1,80}[:,]\s+", re.I)


def _unattributed(text):
    return TOPIC_SCOUT_ATTRIBUTION.sub(r"\1", text) if isinstance(text, str) else text


def tidy(record, idea, new_id, pages, today):
    """Forces the fields the AI must not decide, supplies the fields it often forgets, and removes anything the pipeline cannot draw."""
    record["id"], record["title"] = new_id, idea["title"]
    record["central_question"] = idea["central_question"]
    record["category"], record["template"] = idea["category"], idea["template"]
    record["production_status"] = "queued"
    for key in ("simulation", "scene3d", "diagrams", "attributions", "scene_plan"):
        record.pop(key, None)
    for scenario in record.get("what_if_scenarios", []):
        scenario.pop("simulation", None)
        scenario.pop("diagram", None)
    for source in record.get("sources", []):
        source["date_accessed"] = today
    if not isinstance(record.get("short_video_potential"), dict) or not record["short_video_potential"].get("angle"):
        record["short_video_potential"] = {"suitable": True, "angle": idea["central_question"]}
    if not isinstance(record.get("long_video_potential"), dict) or not record["long_video_potential"].get("angle"):
        record["long_video_potential"] = {"suitable": True, "angle": "A deeper explanation of " + idea["title"].rstrip("?").strip()}
    # sentences a video can speak never name a source: "According to X, ..." is cut back to the plain statement
    explanation = record.get("scientific_explanation")
    if isinstance(explanation, dict):
        for key in explanation:
            explanation[key] = _unattributed(explanation[key])
    for key in ("supporting_evidence", "practical_applications"):
        if isinstance(record.get(key), list):
            record[key] = [_unattributed(item) for item in record[key]]
    record["principle_statement"] = _unattributed(record.get("principle_statement"))
    for item in record.get("misconceptions", []):
        if isinstance(item, dict):
            for key in ("statement", "correction"):
                item[key] = _unattributed(item.get(key))
    for scenario in record.get("what_if_scenarios", []):
        for key in ("summary", "correct", "overlooked", "what_changes", "consequences", "why", "prevention"):
            if key in scenario:
                scenario[key] = _unattributed(scenario[key])
    return record


def verify_claims(ask, record, pages):
    """A second AI pass must quote, word for word, a sentence from a downloaded page for every claim that cites sources."""
    by_id = {s["id"]: s.get("url") for s in record.get("sources", [])}
    payload = {"task": VERIFY_RULES,
               "claims": [{"id": c["id"], "text": c["text"], "source_ids": c.get("source_ids", [])} for c in record["claims"]],
               "pages": {sid: pages.get(url, "") for sid, url in by_id.items()}}
    answer = _json_from(ask([{"role": "system", "content": "You check claims against page text. Reply with JSON only."},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]))
    results = {r.get("id"): r for r in answer.get("results", []) if isinstance(r, dict)}
    for claim in record["claims"]:
        if not claim.get("source_ids") and claim.get("kind") == "mathematical_model":
            continue    # a model claim without a source is checked by the equation checks instead
        result = results.get(claim["id"], {})
        if not result.get("supported"):
            raise ScoutError(f"claim {claim['id']} is not supported by its pages")
        quote, claimed = result.get("quote", ""), result.get("source_id")
        found = None
        if len(norm(quote).split()) >= 8:
            for candidate in [claimed] + [sid for sid in by_id if sid != claimed]:
                if candidate in by_id and norm(quote) in norm(pages.get(by_id[candidate], "")):
                    found = candidate
                    break
        if found is None:
            raise ScoutError(f"claim {claim['id']}: the supporting sentence is not really on any downloaded page")
        if found not in claim.setdefault("source_ids", []):
            claim["source_ids"].append(found)    # the quote is real, it just came from another downloaded page


def check_everything(root, record, rendering):
    """The project's normal gates. Raises ScoutError with the reason."""
    template = load_template(str(root), record["template"])
    result = science.validate_topic_science(record, template)
    if result["status"] != "passed_automated_checks":
        problems = result["errors"] + result["needs_approval"]
        raise ScoutError("science checks: " + "; ".join(problems[:3]))
    if record.get("risk_level", "low") != "low" and record["template"] == "chemistry_experiment":
        raise ScoutError("only low-risk experiments are made automatically")
    ok = {"status": "passed_automated_checks"}
    for fmt in ("short", "long"):
        for variant in available_variants(record):
            try:
                script = generate_script(record, fmt, variant, rendering, ok)
                problems = validate_script(script, record, rendering)["errors"]
                problems += validate_storyboard(generate_storyboard(script, record, rendering), script, record, rendering)["errors"]
            except ScriptError as error:
                raise ScoutError(f"{fmt}/{variant} script: {error}") from error
            if problems:
                raise ScoutError(f"{fmt}/{variant}: {problems[0]}")


REPAIR_RULES = """The checks rejected your draft of the topic record. Fix ONLY what the problems list, keep everything else, and reply with the
complete corrected record as ONE JSON object in the same shape as `example_record`. Use only facts from `pages`. If a problem says a field is
missing, add it with the exact key name. Never mention websites or sources in spoken sentences."""

PLAN_RULES = """Design the pictures for a short science video about this topic, as JSON only:
{"views": {"intro": {"elements": [...]}, "demo": {...}, "problem": {...}, "result": {...}, "explain": {...}}}
Each view is ONE simple animated drawing on a stage 160 wide and 100 tall (x from 0 to 160, y from 0 to 100, y grows downward).
- Draw THIS topic's own objects and what happens to them (the real objects, liquids, forces, molecules), never generic boxes or only text.
- intro = the situation at the start. demo = the main thing happening. problem = the common mistake or what goes wrong.
  result = the outcome. explain = the idea made visible with arrows and short labels. Use all five views.
- 8 to 24 elements per view. Every view needs at least 2 elements that move or appear.
- Element types: rect and ellipse (x, y = centre, w, h), polygon (points = [[x, y], ...], 3 to 8 points),
  line and arrow (x, y = start, x2, y2 = end), text (x, y = centre, text of at most 24 characters, size 4 to 10).
- color is one of: blue, accent, good, warn, bad, violet, text, muted, panel2.
- Optional on any element: alpha (0.15 to 1), appear (0 to 0.9: when it shows up, default 0), dx and dy (how far it moves, at most 120),
  from and to (0 to 1: when the move starts and ends, default 0.1 and 0.9), bob (0 to 3: gentle up and down wobble).
- The list order is the drawing order, first = at the back. Put water or other backgrounds first.
- Everything must stay inside the stage, also after it has moved. Labels use plain words. Arrows for forces point the way the force pushes.
- Show only what the topic record says."""


def repair_record(ask, record, problem, idea, pages, example, today):
    payload = {"task": REPAIR_RULES, "problems": problem, "previous_draft": record, "today": today,
               "topic": {k: idea[k] for k in ("title", "central_question", "category", "template")},
               "pages": [{"url": u, "text": t} for u, t in pages.items()], "example_record": example}
    return _json_from(ask([{"role": "system", "content": "You fix careful, plain-spoken science records. Reply with JSON only."},
                           {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]))


def draft_scene_plan(ask, record, tries=2):
    """The topic's own pictures, checked by animation/two_d/scene_plan.py. Raises ScoutError if no valid plan comes back."""
    from animation.two_d import scene_plan    # imported here: the drawing package itself imports the science checks
    payload = {"task": PLAN_RULES,
               "topic": {"title": record["title"], "central_question": record["central_question"],
                         "explanation": record["scientific_explanation"],
                         "scenarios": [{k: sc.get(k) for k in ("title", "correct", "overlooked", "consequences")}
                                       for sc in record.get("what_if_scenarios", [])]},
               "example_view": {"elements": [
                   {"type": "rect", "x": 80, "y": 72, "w": 130, "h": 46, "color": "blue", "alpha": 0.55},
                   {"type": "ellipse", "x": 45, "y": 20, "w": 14, "h": 14, "color": "warn", "dy": 50, "from": 0.15, "to": 0.7},
                   {"type": "arrow", "x": 115, "y": 70, "x2": 115, "y2": 54, "color": "good", "appear": 0.5},
                   {"type": "text", "x": 80, "y": 10, "text": "Clay ball", "size": 6}]}}
    last = "no plan"
    for _ in range(tries):
        try:
            plan = _json_from(ask([{"role": "system", "content": "You design simple animated science pictures. Reply with JSON only."},
                                   {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]))
            scene_plan.validate(plan)
            return plan                                   # the original shape is what the renderer reads
        except (ScoutError, scene_plan.PlanError) as error:
            last = str(error)
            payload["previous_answer_was_rejected_because"] = last
    raise ScoutError(f"the picture plan was not valid ({last})")


def _own_pages_only(record, pages):
    for source in record.get("sources", []):
        if source.get("url") not in pages:
            raise ScoutError("a source is not one of the downloaded pages")


def scout(root, ask, fetch, rendering, today=None, tries=2, log=None, search=None, pictures=None):
    """Adds at most one new topic. Returns (topic_id or None, [report lines])."""
    today = today or date.today().isoformat()
    pictures = REQUIRE_PICTURES if pictures is None else pictures
    root = Path(root)
    queue, titles = existing_titles(root)
    if sum(1 for t in queue if t.get("status") == "queued") >= MAX_QUEUED:
        return None, [f"The queue already holds {MAX_QUEUED} topics. Nothing to do tonight."]
    example = json.loads((root / "topics" / "records" / "physics-001.json").read_text(encoding="utf-8")) if (root / "topics" / "records" / "physics-001.json").exists() else {}
    for key in ("simulation", "scene3d", "diagrams", "attributions", "scene_plan"):
        example.pop(key, None)
    report = []
    for attempt in range(1, tries + 1):
        idea_title = "?"
        try:
            idea = suggest_idea(ask, titles)
            idea_title = idea["title"]
            pages = download(fetch, idea["source_urls"], search=search, query=idea["title"])
            new_id = next_id(root, idea["category"])
            shape = pick_example(root, idea["template"]) or example
            record = tidy(draft_record(ask, idea, pages, shape, today, template_requirements(root, idea["template"])), idea, new_id, pages, today)
            for repair in range(MAX_REPAIRS + 1):
                try:
                    _own_pages_only(record, pages)
                    check_everything(root, record, rendering)
                    break
                except ScoutError as error:
                    if repair == MAX_REPAIRS:
                        raise
                    record = tidy(repair_record(ask, record, str(error), idea, pages, shape, today), idea, new_id, pages, today)
            verify_claims(ask, record, pages)
            if pictures:
                record["scene_plan"] = draft_scene_plan(ask, record)
        except ScoutError as error:
            report.append(f"Try {attempt}: dropped '{idea_title}' - {error}")
            titles = titles + [idea_title]
            continue
        (root / "topics" / "records" / f"{new_id}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        data = json.loads((root / "topics" / "topic_queue.json").read_text(encoding="utf-8"))
        data["topics"].append({"id": new_id, "title": record["title"], "category": record["category"],
                               "template": record["template"], "status": "queued"})
        (root / "topics" / "topic_queue.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        report.append(f"Added {new_id}: {record['title']}")
        return new_id, report
    return None, report + ["No topic passed every check tonight. Nothing was added."]
