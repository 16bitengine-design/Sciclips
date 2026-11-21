"""Applies an update.zip placed at the repository root, so many files can be changed with one upload and one click.

The zip holds the new or changed files under their normal paths, plus an optional MANIFEST.json:
    {"delete": ["old/file.py", ...], "note": "what this update does"}
Safety rules:
 - nothing outside the repository is ever written, and nothing in .git is touched;
 - files under .github/ are NOT applied (a workflow's own token may not change workflow files): they are listed so they can be copied by hand;
 - the state files in records/ are never deleted.
After applying, update.zip is removed so it cannot be applied twice. The workflow then runs the tests and saves only if they all pass.
"""
import json
import os
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANUAL_PREFIX = ".github/"


def _clean(name):
    """A safe relative path (as text), or None."""
    path = PurePosixPath(name.replace("\\", "/"))
    if not name or path.is_absolute() or ".." in path.parts or path.parts[:1] in ((".git",), ()):
        return None
    return str(path)


def apply(root=ROOT, zip_path=None):
    """Returns (written, deleted, manual, refused)."""
    root = Path(root)
    zip_path = Path(zip_path) if zip_path else root / "update.zip"
    written, deleted, manual, refused = [], [], [], []
    with zipfile.ZipFile(zip_path) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        manifest = json.loads(archive.read("MANIFEST.json")) if "MANIFEST.json" in names else {}
        for name in names:
            if name == "MANIFEST.json":
                continue
            target = _clean(name)
            if target is None:
                refused.append(name)
            elif target.startswith(MANUAL_PREFIX):
                manual.append(target)
            else:
                destination = root / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(name))
                written.append(target)
    for name in manifest.get("delete", []):
        target = _clean(name)
        if target is None or target.startswith(MANUAL_PREFIX) or target.startswith("records/"):
            refused.append(name)
            continue
        path = root / target
        if path.is_file():
            path.unlink()
            deleted.append(target)
            for parent in path.parents:            # tidy up folders that became empty
                if parent == root or any(parent.iterdir()):
                    break
                parent.rmdir()
    zip_path.unlink()
    return written, deleted, manual, refused


def main():
    zip_path = ROOT / "update.zip"
    if not zip_path.exists():
        print("No update.zip at the repository root: nothing to apply.")
        return 1
    written, deleted, manual, refused = apply(ROOT, zip_path)
    lines = [f"Applied update.zip: {len(written)} file(s) written, {len(deleted)} deleted."]
    if manual:
        lines.append("Copy these by hand (workflow files cannot be changed by the workflow): " + ", ".join(manual))
    if refused:
        lines.append("Refused for safety: " + ", ".join(refused))
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Apply update\n\n" + text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
