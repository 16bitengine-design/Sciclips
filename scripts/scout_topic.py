"""Scheduled topic scout: add one fully checked topic whenever the queue needs replenishing.

Needs GitHub Models permission (models: read) and GITHUB_TOKEN. Temporary model/API
failures are retried; topic_scout still rejects anything that fails source/science checks.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from content import ai_writer  # noqa: E402
from content import topic_scout  # noqa: E402

AI_REQUEST_ATTEMPTS = 3
AI_RETRY_DELAYS = (2, 5)


def make_ask():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise topic_scout.ScoutError("no GITHUB_TOKEN")
    model = os.environ.get("SCICLIPS_AI_MODEL", ai_writer.DEFAULT_MODEL)

    def ask(messages):
        payload = {"model": model, "temperature": 0.2, "max_tokens": 6000,
                   "response_format": {"type": "json_object"}, "messages": messages}
        last_error = None
        for attempt in range(1, AI_REQUEST_ATTEMPTS + 1):
            try:
                reply = ai_writer._post(payload, token, timeout=180)
                if not isinstance(reply, dict) or not isinstance(reply.get("choices"), list) or not reply["choices"]:
                    raise RuntimeError("the AI response had no choices array")
                message = reply["choices"][0].get("message", {}) if isinstance(reply["choices"][0], dict) else {}
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("the AI response had no message content")
                return content
            except Exception as error:
                last_error = error
                if attempt < AI_REQUEST_ATTEMPTS:
                    delay = AI_RETRY_DELAYS[min(attempt - 1, len(AI_RETRY_DELAYS) - 1)]
                    print(f"AI request attempt {attempt}/{AI_REQUEST_ATTEMPTS} failed; retrying in {delay}s: "
                          f"{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)
                    time.sleep(delay)
        raise topic_scout.ScoutError(
            f"the AI was unavailable after {AI_REQUEST_ATTEMPTS} attempts "
            f"({type(last_error).__name__}: {str(last_error)[:160]})"
        ) from last_error
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
        lines.append('The bank will be checked again on the next daily scout run.')
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
