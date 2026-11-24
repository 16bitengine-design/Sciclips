"""Scheduled topic scout using Google's Gemini API, with Groq and Cloudflare Workers AI as back-ups.

Topic generation tries Gemini first (its OpenAI-compatible endpoint). If every Gemini model fails, it tries Groq,
then Cloudflare, but only for the providers whose keys are set. Model output still passes the
existing source, science, claim, script and storyboard validation pipeline.
"""
import json
import os
import sys
import time
import re
import html
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from content import ai_writer  # noqa: E402
from content import topic_scout  # noqa: E402

AI_REQUEST_ATTEMPTS = 1
AI_RETRY_DELAYS = (3, 8)
AI_REQUEST_TIMEOUT = 30
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_PRIMARY_MODEL = "gemini-3.8-flash"
GEMINI_FALLBACK_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash")
# Back-up providers. Secrets: GROQ_API_KEY, CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID.
# Optional repository variables SCICLIPS_GROQ_MODEL / SCICLIPS_CLOUDFLARE_MODEL change the model.
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
CLOUDFLARE_ENDPOINT = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions"
CLOUDFLARE_DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


def _message_content(reply):
    if not isinstance(reply, dict) or not isinstance(reply.get("choices"), list) or not reply["choices"]:
        raise RuntimeError("the AI response had no choices array")
    choice = reply["choices"][0]
    message = choice.get("message", {}) if isinstance(choice, dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("the AI response had no message content")
    return content


def _normalise_model(value, default):
    """Accept bare Gemini IDs and API-style models/<id> values."""
    model = str(value or default).strip()
    while model.startswith("models/"):
        model = model[len("models/"):]
    if not model or "/" in model or any(ch.isspace() for ch in model):
        raise topic_scout.ScoutError(f"invalid Gemini model identifier: {model!r}")
    return model


def _backup_model(value, default):
    """Groq and Cloudflare model names can contain '/' and '@', so only blanks and spaces are rejected."""
    model = str(value or default).strip()
    if not model or any(ch.isspace() for ch in model):
        raise topic_scout.ScoutError(f"invalid model identifier: {model!r}")
    return model


def _providers():
    """The AI services to try, in order. Only services whose keys are set are included."""
    providers = []
    gemini_key = os.environ.get("SCICLIPS_GEMINI_API_KEY")
    if gemini_key:
        endpoint = os.environ.get("SCICLIPS_GEMINI_ENDPOINT") or GEMINI_ENDPOINT
        primary_model = _normalise_model(os.environ.get("SCICLIPS_GEMINI_MODEL"), GEMINI_PRIMARY_MODEL)
        configured_fallback = os.environ.get("SCICLIPS_GEMINI_FALLBACK_MODEL")
        fallback_models = [
            _normalise_model(configured_fallback, GEMINI_FALLBACK_MODELS[0]),
            *GEMINI_FALLBACK_MODELS,
        ]
        models = []
        for model in (primary_model, *fallback_models):
            if model not in models:
                models.append(model)
        providers.append({"name": "Google Gemini", "endpoint": endpoint, "key": gemini_key,
                          "models": models, "json_mode": True})
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        providers.append({"name": "Groq", "endpoint": GROQ_ENDPOINT, "key": groq_key,
                          "models": [_backup_model(os.environ.get("SCICLIPS_GROQ_MODEL"), GROQ_DEFAULT_MODEL)],
                          "json_mode": False})
    cloudflare_key = os.environ.get("CLOUDFLARE_API_TOKEN")
    cloudflare_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if cloudflare_key and cloudflare_account:
        providers.append({"name": "Cloudflare", "endpoint": CLOUDFLARE_ENDPOINT.format(account=cloudflare_account.strip()),
                          "key": cloudflare_key,
                          "models": [_backup_model(os.environ.get("SCICLIPS_CLOUDFLARE_MODEL"), CLOUDFLARE_DEFAULT_MODEL)],
                          "json_mode": False})
    return providers


def make_ask():
    providers = _providers()
    if not providers:
        raise topic_scout.ScoutError(
            "Gemini API key is not configured; set SCICLIPS_GEMINI_API_KEY"
        )

    def ask(messages):
        errors = []
        for provider in providers:
            for model in provider["models"]:
                payload = {"temperature": 0.2, "max_tokens": 6000, "messages": messages, "model": model}
                if provider["json_mode"]:
                    payload["response_format"] = {"type": "json_object"}
                for attempt in range(1, AI_REQUEST_ATTEMPTS + 1):
                    try:
                        reply = ai_writer._post(payload, provider["key"], timeout=AI_REQUEST_TIMEOUT,
                                                url=provider["endpoint"])
                        content = _message_content(reply)
                        print(f"AI provider succeeded: {provider['name']} ({model})", file=sys.stderr)
                        return content
                    except Exception as error:
                        errors.append((f"{provider['name']} {model}", error))
                        # Invalid model/configuration and malformed protocol responses
                        # will not improve by repeating the same request.
                        message = str(error).casefold()
                        permanent = (
                            "404" in message or "not found" in message
                            or "not json" in message or "invalid" in message
                            or "400" in message or "401" in message or "403" in message
                        )
                        if permanent:
                            print(
                                f"{provider['name']} model {model} is unavailable/configuration-invalid; "
                                "moving to the next model or provider.",
                                file=sys.stderr,
                            )
                            break
                        if attempt < AI_REQUEST_ATTEMPTS:
                            delay = AI_RETRY_DELAYS[min(attempt - 1, len(AI_RETRY_DELAYS) - 1)]
                            print(
                                f"{provider['name']} {model} attempt {attempt}/{AI_REQUEST_ATTEMPTS} "
                                f"failed; retrying in {delay}s: {type(error).__name__}: {str(error)[:180]}",
                                file=sys.stderr,
                            )
                            time.sleep(delay)
                            continue
                        break

        details = "; ".join(
            f"{name}: {type(error).__name__}: {str(error)[:140]}"
            for name, error in errors
        )
        if len(providers) == 1 and providers[0]["name"] == "Google Gemini":
            raise topic_scout.ScoutError(
                "Google Gemini primary and alternate models were unavailable (" + details + ")"
            ) from (errors[-1][1] if errors else None)
        raise topic_scout.ScoutError(
            "All AI providers were unavailable (" + details + ")"
        ) from (errors[-1][1] if errors else None)

    return ask


def fetch(url):
    import urllib.request
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 SciclipsScout/1.0",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
    })
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type and not any(kind in content_type for kind in ("html", "xhtml", "text/plain")):
                    raise ValueError(f"unsupported page content type: {content_type}")
                return topic_scout.page_text(response.read(2_000_000).decode("utf-8", errors="ignore"))
        except Exception as error:
            last_error = error
            status = getattr(error, "code", None)
            if status not in (None, 408, 425, 429, 500, 502, 503, 504) or attempt == 2:
                break
            time.sleep((2, 5)[attempt])
    raise last_error


def search_trusted_sources(query):
    """Find replacement pages when model-suggested trusted URLs are stale or unavailable."""
    found = []
    lowered = query.casefold()
    water_terms = ("water", "float", "sink", "buoyancy", "density", "insect", "strider", "surface tension")
    if any(term in lowered for term in water_terms):
        # Stable, first-party science education pages, ordered by topic relevance.
        if any(term in lowered for term in ("insect", "strider", "surface tension")):
            found.extend([
                "https://www.usgs.gov/water-science-school/science/surface-tension-and-water",
                "https://www.nps.gov/articles/pecies-spotlight-water-strider.htm",
                "https://serc.carleton.edu/sp/mnstep/activities/26468.html",
                "https://www.usgs.gov/water-science-school/science/water-density",
            ])
        else:
            found.extend([
                "https://www.usgs.gov/water-science-school/science/water-density",
                "https://www.noaa.gov/office-education/outreach-communication/hands-on-science-activities/build-a-boat",
                "https://www.usgs.gov/water-science-school/science/surface-tension-and-water",
                "https://www.nps.gov/articles/pecies-spotlight-water-strider.htm",
            ])
    search_queries = (
        f"{query} science explanation buoyancy density",
        f"{query} site:usgs.gov OR site:noaa.gov OR site:nasa.gov",
        f"{query} site:.edu physics science education",
    )
    for search_query in search_queries:
        params = urllib.parse.urlencode({"q": search_query})
        request = urllib.request.Request(
            "https://html.duckduckgo.com/html/?" + params,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SciclipsScout/1.0)", "Accept": "text/html"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                document = response.read(2_000_000).decode("utf-8", errors="ignore")
        except Exception:
            continue
        for raw in re.findall(r"""href=['"]([^'"]+)['"]""", document):
            link = html.unescape(raw)
            parsed = urllib.parse.urlparse(urllib.parse.urljoin("https://html.duckduckgo.com", link))
            if "duckduckgo.com" in (parsed.hostname or ""):
                link = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
            link = urllib.parse.urldefrag(urllib.parse.unquote(link))[0]
            if link.startswith("https://") and topic_scout.domain_tier(link) == "preferred" and link not in found:
                found.append(link)
            if len(found) >= 9:
                return found
    return found

# Rolling reserve policy: two scheduled videos consume two topics each day.
TOPIC_BANK_TARGET = 14
TOPIC_BANK_LOW_WATERMARK = 8
MAX_TOPICS_PER_RUN = 4


def queued_count(root):
    queue = json.loads((Path(root) / 'topics' / 'topic_queue.json').read_text(encoding='utf-8'))
    return sum(1 for item in queue.get('topics', []) if item.get('status') == 'queued')


def replenish_topic_bank(root, ask, fetch_page, rendering, tries=4, search=None):
    root = Path(root)
    count = queued_count(root)
    if count >= TOPIC_BANK_LOW_WATERMARK:
        return [f'Topic bank healthy: {count} queued; refill starts below {TOPIC_BANK_LOW_WATERMARK}.']
    lines = [f'Topic bank low: {count} queued. Target: {TOPIC_BANK_TARGET}.']
    added = 0
    while count < TOPIC_BANK_TARGET and added < MAX_TOPICS_PER_RUN:
        try:
            if search:
                topic_id, report = topic_scout.scout(root, ask, fetch_page, rendering, tries=tries, search=search)
            else:
                topic_id, report = topic_scout.scout(root, ask, fetch_page, rendering, tries=tries)
        except topic_scout.ScoutError as error:
            lines.append(f'Scout unavailable: {error}')
            break
        lines.extend(report)
        if not topic_id:
            break
        added += 1
        count = queued_count(root)
    lines.append(f'Topic bank after refill: {count} queued; added {added} topic(s).')
    if count < TOPIC_BANK_TARGET:
        lines.append('The bank will be checked again on the next six-hour scout run.')
    return lines


def queue_summary(root):
    """One line per status, with the topic ids, so the log shows exactly what the queue holds."""
    try:
        topics = json.loads((Path(root) / 'topics' / 'topic_queue.json').read_text(encoding='utf-8'))['topics']
    except (OSError, ValueError, KeyError):
        return 'Queue: could not be read.'
    records = sorted(p.stem for p in (Path(root) / 'topics' / 'records').glob('*.json'))
    groups = {}
    for item in topics:
        groups.setdefault(item.get('status', '?'), []).append(item.get('id', '?'))
    parts = [f"{status} {len(ids)} ({', '.join(ids)})" for status, ids in sorted(groups.items())]
    missing = [r for r in records if r not in {t.get('id') for t in topics}]
    return f"Queue: {'; '.join(parts)}. Records on disk: {len(records)}. Records not in the queue: {', '.join(missing) or 'none'}."


def main():
    root = Path('.')
    rendering = json.loads((root / 'config' / 'config.json').read_text(encoding='utf-8'))['rendering']
    topic_scout.REQUIRE_PICTURES = True    # automatic topics must come with their own picture plan
    from scripts import sync_queue          # records written by hand count too: queue them before counting
    synced = sync_queue.sync(root)
    print(queue_summary(root))
    if synced and (synced[0] or synced[1]):
        print('Queue synced with the topic records: added ' + (', '.join(synced[0]) or 'nothing') + '; marked published: ' + (', '.join(synced[1]) or 'nothing'))
    try:
        lines = replenish_topic_bank(root, make_ask(), fetch, rendering, tries=2, search=search_trusted_sources)
    except topic_scout.ScoutError as error:
        lines = [f'Scout skipped: {error}']
    text = '\n'.join(lines)
    print(text)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as handle:
            handle.write('## Topic scout\n\n' + text + '\n')
    # A low/empty bank that could not be replenished is an operational failure,
    # not a successful scout run. This makes provider outages visible in Actions.
    failed = any(
        line.startswith(("Scout unavailable:", "Scout skipped:"))
        for line in lines
    ) or (
        queued_count(root) < TOPIC_BANK_LOW_WATERMARK
        and any("added 0 topic(s)" in line for line in lines)
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
