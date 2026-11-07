"""Runs all automated science checks on topic records.

IMPORTANT: these are automated consistency checks only. They are NOT expert
peer review. Every result keeps human_review_required = True.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from content.topic_manager import load_template, load_topic_record, validate_topic_record  # noqa: E402
from research.claim_checker import check_claims  # noqa: E402
from research.equation_checker import check_equations  # noqa: E402
from research.source_collector import validate_sources  # noqa: E402

DISCLAIMER = "Automated checks only. This is not expert peer review."


def validate_topic_science(record, template):
    errors = list(validate_topic_record(record, template))
    needs_approval, warnings = [], []

    src_errors, src_warnings, source_ids = validate_sources(record.get("sources"))
    errors += src_errors
    warnings += src_warnings
    needs_approval += [w for w in src_warnings]

    equation_ids = [e.get("id") for e in record.get("equations", [])]
    claim_result = check_claims(record.get("claims", []), source_ids, equation_ids)
    errors += claim_result["errors"]
    needs_approval += claim_result["needs_approval"]

    eq_result = check_equations(record.get("equations", []))
    errors += eq_result["errors"]
    needs_approval += eq_result["needs_approval"]

    if not record.get("assumptions"):
        errors.append("No assumptions stated.")
    if not record.get("safety_considerations"):
        errors.append("No safety considerations stated.")

    status = "failed" if errors else ("needs_human_approval" if needs_approval else "passed_automated_checks")
    return {
        "topic_id": record.get("id"),
        "status": status,
        "errors": errors,
        "needs_approval": needs_approval,
        "warnings": warnings,
        "equations_unit_checked": eq_result["checked"],
        "human_review_required": True,
        "disclaimer": DISCLAIMER,
    }


def validate_topic_id(root, topic_id):
    record = load_topic_record(root, topic_id)
    template = load_template(root, record.get("template", "principle"))
    return validate_topic_science(record, template)


def format_report(result):
    lines = [f"Topic {result['topic_id']}: {result['status']}"]
    for key in ("errors", "needs_approval", "warnings"):
        for item in result[key]:
            lines.append(f"  [{key}] {item}")
    lines.append(f"  Unit-checked equations: {', '.join(result['equations_unit_checked']) or 'none'}")
    lines.append(f"  {result['disclaimer']} Human review is still required.")
    return "\n".join(lines)


def main(argv):
    root = "."
    if len(argv) > 1:
        topic_ids = [argv[1]]
    else:
        with open(Path(root) / "topics" / "topic_queue.json", encoding="utf-8") as handle:
            topic_ids = [t["id"] for t in json.load(handle)["topics"]]

    failed = False
    reports = []
    for topic_id in topic_ids:
        try:
            result = validate_topic_id(root, topic_id)
        except FileNotFoundError:
            reports.append(f"Topic {topic_id}: no record file at topics/records/{topic_id}.json")
            failed = True
            continue
        reports.append(format_report(result))
        failed = failed or result["status"] == "failed"

    text = "\n\n".join(reports)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Science validation\n\n```\n" + text + "\n```\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
