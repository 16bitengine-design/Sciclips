"""Scheduled topic scout using Google's supported Gemini API.

GitHub Models was retired in July 2026. Topic generation now uses the
Gemini OpenAI-compatible endpoint directly. Model output still passes the
existing source, science, claim, script and storyboard validation pipeline.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from content import ai_writer  # noqa: E402
from content import topic_scout  # noqa: E402

AI_REQUEST_ATTEMPTS = 2
AI_RETRY_DELAYS = (2,)
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_PRIMARY_MODEL = "gemini-3.8-flash"
GEMINI_FALLBACK_MODEL = "gemini-3.5-flash-lite"


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


def make_ask():
    # Keep the existing secret name for backwards compatibility with the
    # repository, while exposing Gemini-specific names for future cleanup.
    api_key = (os.environ.get("SCICLIPS_GEMINI_API_KEY")
               or os.environ.get("SCICLIPS_FALLBACK_AI_API_KEY"))
    if not api_key:
        raise topic_scout.ScoutError(
            "Gemini API key is not configured; set SCICLIPS_FALLBACK_AI_API_KEY"
        )

    endpoint = (os.environ.get("SCICLIPS_GEMINI_ENDPOINT")
                or os.environ.get("SCICLIPS_FALLBACK_AI_ENDPOINT")
                or GEMINI_ENDPOINT)
    primary_model = _normalise_model(
        os.environ.get("SCICLIPS_GEMINI_MODEL"), GEMINI_PRIMARY_MODEL
    )
    fallback_model = _normalise_model(
        os.environ.get("SCICLIPS_GEMINI_FALLBACK_MODEL")
        or os.environ.get("SCICLIPS_FALLBACK_AI_MODEL"),
        GEMINI_FALLBACK_MODEL,
    )
    if primary_model == fallback_model:
        fallback_model = GEMINI_FALLBACK_MODEL if primary_model != GEMINI_FALLBACK_MODEL else GEMINI_PRIMARY_MODEL

    def ask(messages):
        base_payload = {
            "temperature": 0.2,
            "max_tokens": 6000,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        errors = []
        for model in (primary_model, fallback_model):
            payload = dict(base_payload, model=model)
            for attempt in range(1, AI_REQUEST_ATTEMPTS + 1):
                try:
                    reply = ai_writer._post(payload, api_key, timeout=180, url=endpoint)
                    content = _message_content(reply)
                    print(f"AI provider succeeded: Google Gemini ({model})", file=sys.stderr)
                    return content
                except Exception as error:
                    errors.append((model, error))
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
                            f"Gemini model {model} is unavailable/configuration-invalid; "
                            "moving to the alternate model.",
                            file=sys.stderr,
                        )
                        break
                    if attempt < AI_REQUEST_ATTEMPTS:
                        delay = AI_RETRY_DELAYS[min(attempt - 1, len(AI_RETRY_DELAYS) - 1)]
                        print(
                            f"Gemini {model} attempt {attempt}/{AI_REQUEST_ATTEMPTS} "
                            f"failed; retrying in {delay}s: {type(error).__name__}: {str(error)[:180]}",
                            file=sys.stderr,
                        )
                        time.sleep(delay)
                        continue
                    break

        details = "; ".join(
            f"{model}: {type(error).__name__}: {str(error)[:140]}"
            for model, error in errors
        )
        raise topic_scout.ScoutError(
            "Google Gemini primary and alternate models were unavailable (" + details + ")"
        ) from (errors[-1][1] if errors else None)

    return ask


def fetch(url):
    import urllib.request
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SciclipsScout/1.0)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if "html" not in response.headers.get("Content-Type", "html"):
            raise ValueError("not a web page")
        return topic_scout.page_text(response.read(2_000_000).decode("utf-8", errors="ignore"))


# Rolling reserve policy: two scheduled videos consume two topics each day.
TOPIC_BANK_TARGET = 14
TOPIC_BANK_LOW_WATERMARK = 8
MAX_TOPICS_PER_RUN = 4


def queued_count(root):
    queue = json.loads((Path(root) / 'topics' / 'topic_queue.json').read_text(encoding='utf-8'))
    return sum(1 for item in queue.get('topics', []) if item.get('status') == 'queued')


def replenish_topic_bank(root, ask, fetch_page, rendering, tries=4):
    root = Path(root)
    count = queued_count(root)
    if count >= TOPIC_BANK_LOW_WATERMARK:
        return [f'Topic bank healthy: {count} queued; refill starts below {TOPIC_BANK_LOW_WATERMARK}.']
    lines = [f'Topic bank low: {count} queued. Target: {TOPIC_BANK_TARGET}.']
    added = 0
    while count < TOPIC_BANK_TARGET and added < MAX_TOPICS_PER_RUN:
        try:
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


def main():
    root = Path('.')
    rendering = json.loads((root / 'config' / 'rendering.json').read_text(encoding='utf-8'))
    try:
        lines = replenish_topic_bank(root, make_ask(), fetch, rendering, tries=4)
    except topic_scout.ScoutError as error:
        lines = [f'Scout skipped: {error}']
    text = '\n'.join(lines)
    print(text)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as handle:
            handle.write('## Topic scout\n\n' + text + '\n')
    return 0


if __name__ == "__main__":
    sys.exit(main())
