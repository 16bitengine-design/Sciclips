import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import apply_update as au  # noqa: E402


def make_zip(path, files, manifest=None):
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
        if manifest is not None:
            archive.writestr("MANIFEST.json", json.dumps(manifest))


def test_files_are_written_and_listed_files_are_deleted(tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "gone.py").write_text("x")
    make_zip(tmp_path / "update.zip", {"new/a.py": "A", "b.txt": "B"}, {"delete": ["old/gone.py"]})
    written, deleted, manual, refused = au.apply(tmp_path)
    assert sorted(written) == ["b.txt", "new/a.py"] and deleted == ["old/gone.py"] and not manual and not refused
    assert (tmp_path / "new" / "a.py").read_text() == "A" and not (tmp_path / "old").exists()
    assert not (tmp_path / "update.zip").exists()           # it cannot be applied twice


def test_unsafe_paths_are_refused_and_workflow_files_are_left_for_hand_copying(tmp_path):
    make_zip(tmp_path / "update.zip", {"../evil.py": "x", "/abs.py": "x", ".git/config": "x", ".github/workflows/w.yml": "w", "ok.py": "ok"})
    written, deleted, manual, refused = au.apply(tmp_path)
    assert written == ["ok.py"] and manual == [".github/workflows/w.yml"]
    assert set(refused) == {"../evil.py", "/abs.py", ".git/config"}
    assert not (tmp_path.parent / "evil.py").exists() and not (tmp_path / ".git").exists() and not (tmp_path / ".github").exists()


def test_state_files_and_workflows_can_never_be_deleted(tmp_path):
    (tmp_path / "records").mkdir()
    (tmp_path / "records" / "auto_state.json").write_text("{}")
    make_zip(tmp_path / "update.zip", {"a.txt": "a"}, {"delete": ["records/auto_state.json", ".github/workflows/x.yml", "../x"]})
    written, deleted, manual, refused = au.apply(tmp_path)
    assert deleted == [] and len(refused) == 3 and (tmp_path / "records" / "auto_state.json").exists()


def test_a_zip_without_a_manifest_still_works(tmp_path):
    make_zip(tmp_path / "update.zip", {"only.txt": "1"})
    assert au.apply(tmp_path)[0] == ["only.txt"]
