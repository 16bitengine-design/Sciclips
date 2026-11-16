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

PREFIX = {"physics": "physics", "chemistry": "chem", "biology": "bio", "earth-science": "earth", "astronomy": "astro"}
TEMPLATES = ("principle", "chemistry_experiment")
SUPPORTED_SIMULATIONS = {"free_fall": {"vacuum", "with_air", "air_vs_vacuum", "terminal_speed", "wrong_mass_model"},
                         "gas_release": {"open", "sealed", "sealed_pop", "balance_open", "balance_sealed"}}
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
    "Suggest ONE new science topic for short explainer videos that a curious seven year old can follow and that can be "
    "SHOWN with a simple demonstration (not just explained). It must be safe at home with everyday materials, and must "
    "not be about anything dangerous, medical or political. It must not repeat any title in `already_used`. "
    "Give 3 real web page addresses (https) from trusted sites that explain it (for example nasa.gov, noaa.gov, "
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
- Plain words for a seven year old in scientific_explanation.level_1, a little more in level_2, precise in level_3.
- NEVER mention websites, organisations, 'sources', 'studies' or 'research shows' in any sentence a video could speak
  (scientific_explanation, supporting_evidence, practical_applications, misconceptions, what_if_scenarios, principle_statement).
- supporting_evidence and practical_applications are lists of plain sentences. principle_statement and domain_of_validity are required for the template 'principle'.
- what_if_scenarios: exactly 2 complete scenarios with all the fields shown in the example (omit their "simulation" and "diagram" keys).
- Required video-planning fields: short_video_potential and long_video_potential, each with suitable true and a clear angle.
- Safety: risk_level "low", hazards and safety_equipment lists, supervision_required true for experiments, production_status "queued".
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
    # Source links are suggestions, not a hard dependency: the trusted-source
    # search fallback can replace missing or stale links before any draft is made.
    if norm(idea.get("title", "")) in {norm(t) for t in titles}:
        raise ScoutError("that topic already exists")
    idea["source_urls"] = urls
    return idea


def download(fetch, urls, search=None, query=""):
    """Read trusted pages, searching for replacements when model-suggested links are stale."""
    pages, failures = {}, []
    for url in urls:
        try:
            text = fetch(url)
            if len(text) < MIN_PAGE_CHARS:
                failures.append(f"{url} (too little readable text)")
                continue
            pages[url] = text[:PAGE_CHARS]
        except Exception as error:
            failures.append(f"could not read {url} ({type(error).__name__})")
    if len(pages) < 2 and search:
        try:
            alternatives = search(query)
        except Exception as error:
            alternatives = []
            failures.append(f"trusted-source search failed ({type(error).__name__})")
        for url in alternatives:
            if not isinstance(url, str) or url in urls or url in pages or domain_tier(url) != "preferred":
                continue
            try:
                text = fetch(url)
                if len(text) >= MIN_PAGE_CHARS:
                    pages[url] = text[:PAGE_CHARS]
            except Exception as error:
                failures.append(f"replacement source unavailable {url} ({type(error).__name__})")
            if len(pages) >= 2:
                break
    if len(pages) < 2:
        detail = "; ".join(failures[:4]) or "fewer than two source pages were supplied"
        raise ScoutError(f"only {len(pages)} trusted source page(s) could be read; at least 2 are required: {detail}")
    return pages


def draft_record(ask, idea, pages, example, today):
    payload = {"task": DRAFT_RULES, "today": today, "topic": {k: idea[k] for k in ("title", "central_question", "category", "template")},
               "pages": [{"url": u, "text": t} for u, t in pages.items()], "example_record": example}
    return _json_from(ask([{"role": "system", "content": "You write careful, plain-spoken science records. Reply with JSON only."},
                           {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]))


def tidy(record, idea, new_id, pages, today):
    """Forces the fields the AI must not decide, and removes anything the pipeline cannot draw."""
    record["id"], record["title"] = new_id, idea["title"]
    record["central_question"] = idea["central_question"]
    record["category"], record["template"] = idea["category"], idea["template"]
    record["production_status"] = "queued"
    if not isinstance(record.get("short_video_potential"), dict):
        record["short_video_potential"] = {}
    record["short_video_potential"].setdefault("suitable", True)
    record["short_video_potential"].setdefault("angle", idea["central_question"])
    if not isinstance(record.get("long_video_potential"), dict):
        record["long_video_potential"] = {}
    record["long_video_potential"].setdefault("suitable", True)
    record["long_video_potential"].setdefault(
        "angle",
        "Explore the science behind " + idea["title"] + " with a deeper explanation and safe what-if comparisons.",
    )
    for key in ("simulation", "scene3d", "diagrams", "attributions"):
        record.pop(key, None)
    for scenario in record.get("what_if_scenarios", []):
        scenario.pop("simulation", None)
        scenario.pop("diagram", None)
    for source in record.get("sources", []):
        source["date_accessed"] = today
    return record


def verify_claims(ask, record, pages):
    by_id = {s["id"]: s.get("url") for s in record.get("sources", [])}
    payload = {"task": VERIFY_RULES,
               "claims": [{"id": c["id"], "text": c["text"], "source_ids": c.get("source_ids", [])} for c in record["claims"]],
               "pages": {sid: pages.get(url, "") for sid, url in by_id.items()}}
    answer = _json_from(ask([{"role": "system", "content": "You check claims against page text. Reply with JSON only."},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]))
    results = {r.get("id"): r for r in answer.get("results", []) if isinstance(r, dict)}
    for claim in record["claims"]:
        result = results.get(claim["id"], {})
        quote, sid = result.get("quote", ""), result.get("source_id")
        if not result.get("supported") or sid not in claim.get("source_ids", []):
            raise ScoutError(f"claim {claim['id']} is not supported by its pages")
        if len(norm(quote).split()) < 8 or norm(quote) not in norm(pages.get(by_id.get(sid), "")):
            raise ScoutError(f"claim {claim['id']}: the supporting sentence is not really on the page")


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


def scout(root, ask, fetch, rendering, today=None, tries=2, log=None, search=None):
    """Adds at most one new topic. Returns (topic_id or None, [report lines])."""
    today = today or date.today().isoformat()
    root = Path(root)
    queue, titles = existing_titles(root)
    if sum(1 for t in queue if t.get("status") == "queued") >= MAX_QUEUED:
        return None, [f"The queue already holds {MAX_QUEUED} topics. Nothing to do tonight."]
    example = json.loads((root / "topics" / "records" / "physics-001.json").read_text(encoding="utf-8")) if (root / "topics" / "records" / "physics-001.json").exists() else {}
    for key in ("simulation", "scene3d", "diagrams", "attributions"):
        example.pop(key, None)
    report = []
    for attempt in range(1, tries + 1):
        idea_title = "?"
        try:
            idea = suggest_idea(ask, titles)
            idea_title = idea["title"]
            pages = download(fetch, idea["source_urls"], search=search, query=idea["title"] + " " + idea["central_question"])
            new_id = next_id(root, idea["category"])
            record = tidy(draft_record(ask, idea, pages, example, today), idea, new_id, pages, today)
            # the AI names pages by url; make sure each source url is one we actually downloaded
            for source in record.get("sources", []):
                if source.get("url") not in pages:
                    raise ScoutError("a source is not one of the downloaded pages")
            check_everything(root, record, rendering)
            verify_claims(ask, record, pages)
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
