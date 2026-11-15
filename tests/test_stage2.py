import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_config import validate  # noqa: E402
from run_production import plan  # noqa: E402


def make_copy(tmp_path):
    dest = tmp_path / "repo"
    for folder in ("config", "topics", "records"):
        shutil.copytree(ROOT / folder, dest / folder)
    return dest


def make_test_config(tmp_path):
    """Give planner tests an isolated TEST-mode copy of production config."""
    repo = make_copy(tmp_path)
    path = repo / "config" / "settings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["operating_mode"] = "TEST"
    # TEST mode must not advertise automatic publishing as enabled.
    data["automatic_publishing_enabled"] = False
    path.write_text(json.dumps(data), encoding="utf-8")
    return repo


def test_real_config_is_valid():
    assert validate(str(ROOT)) == []


def test_missing_file_is_reported(tmp_path):
    repo = make_copy(tmp_path)
    (repo / "config" / "rendering.json").unlink()
    assert any("rendering.json" in p for p in validate(str(repo)))


def test_broken_json_is_reported(tmp_path):
    repo = make_copy(tmp_path)
    (repo / "topics" / "topic_queue.json").write_text("{ not json")
    assert any("Invalid JSON" in p for p in validate(str(repo)))


def test_paid_service_guard(tmp_path):
    repo = make_copy(tmp_path)
    path = repo / "config" / "settings.json"
    data = json.loads(path.read_text())
    data["never_switch_to_paid_service"] = False
    path.write_text(json.dumps(data))
    assert any("paid" in p for p in validate(str(repo)))


def test_plan_accepts_good_request(tmp_path):
    repo = make_test_config(tmp_path)
    ok, lines = plan(str(repo), "physics-001", "short", "low", "TEST")
    assert ok


def test_plan_rejects_unknown_topic(tmp_path):
    repo = make_test_config(tmp_path)
    ok, lines = plan(str(repo), "nope-999", "short", "low", "TEST")
    assert not ok and "not found" in lines[0]


def test_plan_refuses_non_test_modes(tmp_path):
    repo = make_test_config(tmp_path)
    for mode in ("APPROVAL", "AUTOMATIC"):
        ok, _ = plan(str(repo), "physics-001", "short", "low", mode)
        assert not ok
