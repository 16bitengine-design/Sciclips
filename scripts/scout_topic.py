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


def main():
    root = Path(".")
    rendering = json.loads((root / "config" / "rendering.json").read_text(encoding="utf-8"))
    try:
        topic_id, lines = topic_scout.scout(root, make_ask(), fetch, rendering, tries=4)
    except topic_scout.ScoutError as error:
        topic_id, lines = None, [f"Scout skipped: {error}"]
    text = "\\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Topic scout\\n\\n```\\n" + text + "\\n```\\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
