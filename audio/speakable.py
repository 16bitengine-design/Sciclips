"""Turns written text into text a voice can say well (equations, units and chemical formulas)."""
import json
import re
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "pronunciations.json"
POWERS = {"2": "squared", "3": "cubed"}


def load_pronunciations(path=None):
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        return {"phrases": {}, "words": {}}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {"phrases": data.get("phrases", {}), "words": data.get("words", {})}


def _power(match):
    base, exponent = match.group(1), match.group(2)
    if exponent in POWERS:
        spoken = POWERS[exponent]
    elif exponent.startswith("-"):
        spoken = f"to the power minus {exponent[1:]}"
    else:
        spoken = f"to the power {exponent}"
    return f"{base} {spoken}"


def _spell_formula(match):
    token = match.group(0)
    if not any(ch.isdigit() for ch in token):
        return token
    return " ".join(re.findall(r"[A-Z][a-z]?|\d+", token))


def speakable(text, pronunciations=None):
    """Return the text rewritten for speech. The written text itself is never changed."""
    pron = pronunciations if pronunciations is not None else load_pronunciations()
    out = text
    for phrase in sorted(pron["phrases"], key=len, reverse=True):
        out = re.sub(r"(?<![\w^])" + re.escape(phrase) + r"(?![\w^])", pron["phrases"][phrase], out)
    for word in sorted(pron["words"], key=len, reverse=True):
        out = re.sub(r"\b" + re.escape(word) + r"\b", pron["words"][word], out)
    out = re.sub(r"\b(?:[A-Z][a-z]?\d*){2,}\b", _spell_formula, out)
    out = re.sub(r"(\w)\^(-?\d+)", _power, out)
    if "=" in out:
        out = re.sub(r"\b[a-z]\b", lambda m: m.group(0).upper(), out)
    for symbol, spoken in (("->", " gives "), (" = ", " equals "), (" / ", " divided by "),
                           (" * ", " times "), (" + ", " plus ")):
        out = out.replace(symbol, spoken)
    return " ".join(out.split())
