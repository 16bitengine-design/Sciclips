"""Lets a free GitHub AI model plan the order of a short video, with strict safety checks.

The model never writes science. It only CHOOSES and ORDERS sentences that already exist in the topic
record and pairs each one with a picture (simulation variant) from a fixed list. Every choice is checked
here, and if anything looks wrong, or the model is unavailable, the caller falls back to the ordinary
template writer. Nothing here can stop a video from being made.

It only runs when the environment variable SCICLIPS_AI is "1" and a GITHUB_TOKEN is available (inside a
GitHub Actions run with `permissions: models: read`).
"""
import json
import os
import re
import sys
import urllib.request

ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4.1"
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
    return os.environ.get("SCICLIPS_AI") == "1" and bool(os.environ.get("GITHUB_TOKEN"))


def sentences_of(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join(str(text).split())) if s]


def _post(payload, token, timeout=60):
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/vnd.github+json",
                 "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


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
    token = os.environ.get("GITHUB_TOKEN")
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
    payload = {"model": model or os.environ.get("SCICLIPS_AI_MODEL", DEFAULT_MODEL), "temperature": 0.2,
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
        print(f"AI writer skipped ({type(error).__name__}: {str(error)[:120]})", file=sys.stderr)
        return None
    clean = check_steps(steps, haystack, variants)
    if clean is None:
        print("AI writer skipped (its answer did not pass the safety checks)", file=sys.stderr)
    return clean
