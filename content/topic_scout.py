"""Finds and drafts new topics by itself, then lets the normal automatic checks decide whether to keep them.

How a night goes (all steps must pass, otherwise nothing is added):
  1. The AI suggests a topic that is not already in the queue, with web pages from trusted science sites.
  2. The pages are downloaded. A page that cannot be read means the idea is dropped.
  3. The AI drafts the topic record using ONLY what those pages say.
  4. The project's own science checks run (sources, claims, units, balanced equations, safety, plain language).
  5. A second AI pass must quote, word for word, the sentence on the cited page that supports every claim.
     A quote that is not really on the page means the topic is dropped.
  6. Scripts for every video type are generated and checked.
The AI and the web are reached through two small functions (`ask` and `fetch`) so tests can fake them.
"""
import json
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from content import script_generator as gen
from content import script_validator as sv
from content import topic_manager as tm
from content.storyboard_generator import generate_storyboard
from research import science_validator as science
from research.source_collector import domain_tier
from animation.two_d import scene_plan

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
            problems.append(f"could not read {url} ({type(error).__name__})")
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
        return tm.load_template(str(root), name)
    except Exception:
        return None


def draft_record(ask, idea, pages, example, today, requirements=None):
    payload = {"task": DRAFT_RULES, "today": today, "topic": {k: idea[k] for k in ("title", "central_question", "category", "template")},
               "pages": [{"url": u, "text": t} for u, t in pages.items()], "example_record": example}
    if requirements:
        payload["template_requirements"] = requirements
    return _json_from(ask([{"role": "system", "content": "You write careful, plain-spoken science records. Reply with JSON only."},
                           {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]))


ATTRIBUTION = re.compile(r"(^|(?<=[.!?]\s))(?:According to|As (?:stated|reported|explained|noted) by|As per)\s+[^:,;.]{1,80}[:,]\s+", re.I)


def _unattributed(text):
    return ATTRIBUTION.sub(r"\1", text) if isinstance(text, str) else text


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
    template = tm.load_template(str(root), record["template"])
    result = science.validate_topic_science(record, template)
    if result["status"] != "passed_automated_checks":
        problems = result["errors"] + result["needs_approval"]
        raise ScoutError("science checks: " + "; ".join(problems[:3]))
    if record.get("risk_level", "low") != "low" and record["template"] == "chemistry_experiment":
        raise ScoutError("only low-risk experiments are made automatically")
    ok = {"status": "passed_automated_checks"}
    for fmt in ("short", "long"):
        for variant in gen.available_variants(record):
            try:
                script = gen.generate_script(record, fmt, variant, rendering, ok)
                problems = sv.validate_script(script, record, rendering)["errors"]
                problems += sv.validate_storyboard(generate_storyboard(script, record, rendering), script, record, rendering)["errors"]
            except gen.ScriptError as error:
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
