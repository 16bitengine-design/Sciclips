"""Nightly topic scout: tries to add one new, fully checked topic to the queue. Never publishes anything.

Needs the GitHub Models permission (`models: read`) and the GITHUB_TOKEN. If anything goes wrong it adds nothing.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from content import ai_writer  # noqa: E402
from content import topic_scout  # noqa: E402


def make_ask():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise topic_scout.ScoutError("no GITHUB_TOKEN")
    model = os.environ.get("SCICLIPS_AI_MODEL", ai_writer.DEFAULT_MODEL)

    def ask(messages):
        payload = {"model": model, "temperature": 0.2, "max_tokens": 6000,
                   "response_format": {"type": "json_object"}, "messages": messages}
        try:
            reply = ai_writer._post(payload, token, timeout=180)
            return reply["choices"][0]["message"]["content"]
        except Exception as error:
            raise topic_scout.ScoutError(f"the AI was not available ({type(error).__name__}: {str(error)[:100]})") from error
    return ask


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SciclipsScout/1.0)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if "html" not in response.headers.get("Content-Type", "html"):
            raise ValueError("not a web page")
        return topic_scout.page_text(response.read(2_000_000).decode("utf-8", errors="ignore"))


def main():
    root = Path(".")
    rendering = json.loads((root / "config" / "rendering.json").read_text(encoding="utf-8"))
    try:
        topic_id, lines = topic_scout.scout(root, make_ask(), fetch, rendering)
    except topic_scout.ScoutError as error:
        topic_id, lines = None, [f"Scout skipped: {error}"]
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Topic scout\n\n```\n" + text + "\n```\n")
    return 0  # a night with no new topic is normal, not a failure


if __name__ == "__main__":
    sys.exit(main())
