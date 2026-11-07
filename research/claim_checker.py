"""Checks that each scientific claim is labelled, worded and sourced properly."""
import re

KINDS = (
    "established_fact", "law", "theory", "hypothesis", "mathematical_model",
    "experimental_observation", "prediction", "speculation",
)
NEEDS_SOURCE = ("established_fact", "law", "theory", "experimental_observation")
UNCERTAIN_KINDS = ("hypothesis", "prediction", "speculation")

OVERCONFIDENT = ("proven", "proves", "proved", "definitely", "certainly", "undeniable")
BELITTLING_THEORY = ("just a theory", "only a theory", "merely a theory", "just a guess")


def _contains_word(text, word):
    return re.search(r"\b" + re.escape(word) + r"\b", text.lower()) is not None


def check_claims(claims, source_ids, equation_ids):
    """Returns {"errors": [...], "needs_approval": [...]}."""
    errors, needs_approval = [], []
    if not claims:
        return {"errors": ["No claims recorded."], "needs_approval": []}

    seen = set()
    for claim in claims:
        cid = claim.get("id", "?")
        text = claim.get("text", "")
        kind = claim.get("kind")
        if cid in seen:
            errors.append(f"Claim {cid}: duplicate id.")
        seen.add(cid)
        if not text:
            errors.append(f"Claim {cid}: no text.")
        if kind not in KINDS:
            errors.append(f"Claim {cid}: unknown kind '{kind}'.")
            continue

        for sid in claim.get("source_ids", []):
            if sid not in source_ids:
                errors.append(f"Claim {cid}: refers to unknown source '{sid}'.")
        for eid in claim.get("equation_ids", []):
            if eid not in equation_ids:
                errors.append(f"Claim {cid}: refers to unknown equation '{eid}'.")

        if kind in UNCERTAIN_KINDS:
            for word in OVERCONFIDENT:
                if _contains_word(text, word):
                    errors.append(f"Claim {cid}: a {kind} must not be worded as proven ('{word}').")
        if kind == "theory":
            lowered = text.lower()
            for phrase in BELITTLING_THEORY:
                if phrase in lowered:
                    errors.append(f"Claim {cid}: a scientific theory must not be called '{phrase}'.")

        if kind in NEEDS_SOURCE and not claim.get("source_ids"):
            needs_approval.append(f"Claim {cid}: a {kind} has no source; a person must confirm it.")
        if kind == "mathematical_model" and not (claim.get("source_ids") or claim.get("equation_ids")):
            needs_approval.append(f"Claim {cid}: model has neither a source nor a checked equation.")

    return {"errors": errors, "needs_approval": needs_approval}
