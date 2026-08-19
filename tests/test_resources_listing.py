"""Resource listing helper tests."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.resources.listing import (  # noqa: E402
    _dir_entry_count,
    _mtime_iso,
    _read_json_dict,
    list_agents,
    list_hooks,
    list_missions,
    list_reports,
    list_subagents,
    show_mission,
)


def test_list_missions_and_show(tmp_path):
    d = tmp_path / "missions"
    d.mkdir()
    (d / "demo.md").write_text("hello", encoding="utf-8")
    missions = list_missions(d)
    assert missions[0]["name"] == "demo"
    shown = show_mission(d, "demo")
    assert shown["ok"] is True
    assert shown["content"] == "hello"
    assert show_mission(d, "../x")["ok"] is False


def test_list_reports(tmp_path):
    d = tmp_path / "reports"
    shots = d / "shots"
    shots.mkdir(parents=True)
    (d / "a.txt").write_text("a", encoding="utf-8")
    (shots / "b.png").write_text("b", encoding="utf-8")
    names = {r["name"] for r in list_reports(d)}
    assert "a.txt" in names
    assert "shots/b.png" in names


def test_list_hooks_agents_subagents(tmp_path):
    hooks = tmp_path / "hooks"
    agents = tmp_path / "agents"
    subs = tmp_path / "subagents"
    hooks.mkdir()
    agents.mkdir()
    subs.mkdir()
    (hooks / "h.json").write_text(json.dumps({"event": "x", "description": "desc"}), encoding="utf-8")
    (agents / "a.json").write_text(json.dumps({"description": "agent", "model": "m"}), encoding="utf-8")
    (subs / "s.json").write_text(json.dumps({"status": "ok", "cmd": "run"}), encoding="utf-8")
    assert list_hooks(hooks)["hooks"][0]["event"] == "x"
    assert list_agents(agents)["agents"][0]["model"] == "m"
    assert list_subagents(subs)["subagents"][0]["status"] == "ok"


def test_list_subagents_skips_gitkeep_and_dotfiles(tmp_path):
    subs = tmp_path / "subagents"
    subs.mkdir()
    (subs / ".gitkeep").write_text("", encoding="utf-8")
    (subs / ".DS_Store").write_text("junk", encoding="utf-8")
    (subs / "valid_worker.json").write_text(json.dumps({"status": "idle", "cmd": "eval"}), encoding="utf-8")

    result = list_subagents(subs)

    assert result["ok"] is True
    assert result["count"] == 1
    assert [s["file"] for s in result["subagents"]] == ["valid_worker.json"]
    assert result["subagents"][0]["status"] == "idle"


def test_list_subagents_skips_hidden_directories(tmp_path):
    subs = tmp_path / "subagents"
    hidden = subs / ".ipynb_checkpoints"
    hidden.mkdir(parents=True)
    (hidden / "meta.json").write_text(json.dumps({"id": "x", "name": "ghost", "status": "ok"}), encoding="utf-8")
    real = subs / "run01"
    real.mkdir()
    (real / "meta.json").write_text(json.dumps({"id": "run01", "name": "real", "status": "ok"}), encoding="utf-8")

    result = list_subagents(subs)

    assert result["count"] == 1
    assert result["subagents"][0]["name"] == "real"


def test_list_subagents_skips_non_descriptor_files(tmp_path):
    subs = tmp_path / "subagents"
    subs.mkdir()
    (subs / "stdout.log").write_text("noise", encoding="utf-8")
    (subs / "pid").write_text("4242", encoding="utf-8")
    (subs / "keep.md").write_text("# note", encoding="utf-8")

    result = list_subagents(subs)

    assert [s["file"] for s in result["subagents"]] == ["keep.md"]
    assert result["count"] == 1


def test_list_subagents_reports_spawned_run_directories(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "721ed61b0b"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(
        json.dumps({"id": "721ed61b0b", "name": "probe", "cmd": "echo hi", "status": "ok",
                    "exit": 0, "created": "2026-08-19T00:00:00+00:00"}),
        encoding="utf-8",
    )
    (run / "stdout.log").write_text("hi", encoding="utf-8")

    result = list_subagents(subs)

    assert result["count"] == 1
    entry = result["subagents"][0]
    assert entry["id"] == "721ed61b0b"
    assert entry["name"] == "probe"
    assert entry["status"] == "ok"
    assert entry["cmd"] == "echo hi"
    assert entry["exit"] == 0
    assert entry["ext"] == "[dir]"
    assert entry["file"] == "721ed61b0b/"
    assert entry["created"] == "2026-08-19T00:00:00+00:00"
    assert "modified" in entry


def test_list_subagents_run_directory_falls_back_to_summary(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "abc123"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(
        json.dumps({"id": "abc123", "name": "later", "status": "timeout", "cmd": "sleep 999"}),
        encoding="utf-8",
    )

    entry = list_subagents(subs)["subagents"][0]

    assert entry["status"] == "timeout"
    assert entry["name"] == "later"


def test_list_subagents_run_directory_without_meta_is_still_listed(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "orphan"
    run.mkdir(parents=True)
    (run / "stdout.log").write_text("x", encoding="utf-8")

    entry = list_subagents(subs)["subagents"][0]

    assert entry["name"] == "orphan"
    assert entry["ext"] == "[dir]"
    assert entry["size"] == 1
    assert "status" not in entry


def test_list_subagents_tolerates_corrupt_meta(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "broken"
    run.mkdir(parents=True)
    (run / "meta.json").write_text("{not json", encoding="utf-8")
    (subs / "bad.json").write_text("[]", encoding="utf-8")

    result = list_subagents(subs)

    assert result["count"] == 2
    by_name = {s["name"]: s for s in result["subagents"]}
    assert "status" not in by_name["broken"]
    assert "status" not in by_name["bad"]


def test_list_subagents_empty_descriptor_is_listed_without_status(tmp_path):
    subs = tmp_path / "subagents"
    subs.mkdir()
    (subs / "empty_agent.json").write_text("", encoding="utf-8")

    result = list_subagents(subs)

    assert result["count"] == 1
    assert result["subagents"][0]["name"] == "empty_agent"
    assert result["subagents"][0]["size"] == 0
    assert "status" not in result["subagents"][0]


def test_list_subagents_missing_dir(tmp_path):
    assert list_subagents(tmp_path / "nope") == {"ok": True, "count": 0, "subagents": []}


@pytest.mark.parametrize("suffix", [".json", ".yaml", ".yml", ".toml", ".md"])
def test_list_subagents_accepts_every_allowlisted_suffix(tmp_path, suffix):
    subs = tmp_path / "subagents"
    subs.mkdir()
    (subs / f"desc{suffix}").write_text("{}", encoding="utf-8")

    result = list_subagents(subs)

    assert result["count"] == 1
    assert result["subagents"][0]["ext"] == suffix
    assert result["subagents"][0]["file"] == f"desc{suffix}"


def test_list_subagents_file_entry_has_exact_shape(tmp_path):
    subs = tmp_path / "subagents"
    subs.mkdir()
    (subs / "w.json").write_text(json.dumps({"status": "ok", "cmd": "run"}), encoding="utf-8")

    entry = list_subagents(subs)["subagents"][0]

    assert set(entry) == {"name", "file", "ext", "size", "modified", "status", "cmd"}
    assert entry["modified"].endswith("+00:00")


def test_list_subagents_file_missing_fields_default_to_empty_string(tmp_path):
    subs = tmp_path / "subagents"
    subs.mkdir()
    (subs / "w.json").write_text(json.dumps({"other": 1}), encoding="utf-8")

    entry = list_subagents(subs)["subagents"][0]

    assert entry["status"] == ""
    assert entry["cmd"] == ""


def test_list_subagents_truncates_long_cmd_to_200_chars(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "run"
    run.mkdir(parents=True)
    long_cmd = "x" * 500
    (run / "meta.json").write_text(json.dumps({"cmd": long_cmd, "status": "ok"}), encoding="utf-8")
    (subs / "flat.json").write_text(json.dumps({"cmd": long_cmd, "status": "ok"}), encoding="utf-8")

    by_name = {s["name"]: s for s in list_subagents(subs)["subagents"]}

    assert len(by_name["run"]["cmd"]) == 200
    assert len(by_name["flat"]["cmd"]) == 200


def test_list_subagents_run_dir_entry_has_exact_shape(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "r1"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(
        json.dumps({"id": "r1", "name": "n", "status": "ok", "cmd": "c", "created": "t", "exit": 0}),
        encoding="utf-8",
    )

    entry = list_subagents(subs)["subagents"][0]

    assert set(entry) == {"name", "file", "ext", "size", "modified", "id", "status", "cmd", "created", "exit"}
    assert entry["modified"].endswith("+00:00")


def test_list_subagents_run_dir_meta_defaults(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "r2"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"unrelated": True}), encoding="utf-8")

    entry = list_subagents(subs)["subagents"][0]

    assert entry["id"] == "r2"
    assert entry["name"] == "r2"
    assert entry["status"] == ""
    assert entry["cmd"] == ""
    assert "created" not in entry
    assert "exit" not in entry


def test_list_subagents_meta_json_wins_over_summary_json(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "r3"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"id": "r3", "name": "from_meta", "status": "running"}), encoding="utf-8")
    (run / "summary.json").write_text(json.dumps({"id": "r3", "name": "from_summary", "status": "ok"}), encoding="utf-8")

    entry = list_subagents(subs)["subagents"][0]

    assert entry["name"] == "from_meta"
    assert entry["status"] == "running"


def test_list_subagents_run_dir_size_counts_entries(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "r4"
    run.mkdir(parents=True)
    for n in ("meta.json", "stdout.log", "stderr.log"):
        (run / n).write_text("{}", encoding="utf-8")

    assert list_subagents(subs)["subagents"][0]["size"] == 3


def test_list_subagents_empty_run_dir_size_is_zero(tmp_path):
    subs = tmp_path / "subagents"
    (subs / "r5").mkdir(parents=True)

    assert list_subagents(subs)["subagents"][0]["size"] == 0


def test_list_subagents_non_object_json_yields_no_status(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "r6"
    run.mkdir(parents=True)
    (run / "meta.json").write_text("[1, 2]", encoding="utf-8")
    (run / "summary.json").write_text(json.dumps({"id": "r6", "name": "fallback", "status": "ok"}), encoding="utf-8")

    entry = list_subagents(subs)["subagents"][0]

    assert entry["name"] == "fallback"
    assert entry["status"] == "ok"


def test_list_subagents_lists_all_run_dirs_and_files(tmp_path):
    subs = tmp_path / "subagents"
    subs.mkdir()
    for name in ("aaa", "bbb"):
        d = subs / name
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"id": name, "name": name, "status": "ok"}), encoding="utf-8")
    (subs / "ccc.json").write_text(json.dumps({"status": "idle"}), encoding="utf-8")
    (subs / "skip.log").write_text("x", encoding="utf-8")

    result = list_subagents(subs)

    assert result["count"] == 3
    assert [s["name"] for s in result["subagents"]] == ["aaa", "bbb", "ccc"]


def test_list_subagents_keeps_scanning_after_a_rejected_file(tmp_path):
    """A non-descriptor file must be skipped, not end the scan."""
    subs = tmp_path / "subagents"
    subs.mkdir()
    (subs / "aaa.log").write_text("noise", encoding="utf-8")  # sorts before zzz.json
    (subs / "zzz.json").write_text(json.dumps({"status": "idle"}), encoding="utf-8")

    result = list_subagents(subs)

    assert [s["file"] for s in result["subagents"]] == ["zzz.json"]


def test_list_subagents_run_dir_id_comes_from_meta_not_dirname(tmp_path):
    subs = tmp_path / "subagents"
    run = subs / "dirname_differs"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"id": "meta_id_7", "name": "n"}), encoding="utf-8")

    entry = list_subagents(subs)["subagents"][0]

    assert entry["id"] == "meta_id_7"


def test_dir_entry_count_is_zero_when_directory_cannot_be_read(tmp_path):
    assert _dir_entry_count(tmp_path / "does_not_exist") == 0


def test_mtime_iso_is_empty_when_stat_fails(tmp_path):
    assert _mtime_iso(tmp_path / "does_not_exist") == ""


def test_mtime_iso_returns_utc_isoformat(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")

    stamp = _mtime_iso(target)

    assert stamp.endswith("+00:00")
    assert datetime.fromisoformat(stamp).tzinfo is not None


def test_list_subagents_json_nulls_do_not_become_the_string_none(tmp_path):
    """An explicit `null` must degrade to "", never to the literal 'None'."""
    subs = tmp_path / "subagents"
    run = subs / "run"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(
        json.dumps({"id": None, "name": None, "status": None, "cmd": None}), encoding="utf-8"
    )
    (subs / "flat.json").write_text(json.dumps({"status": None, "cmd": None}), encoding="utf-8")

    by_file = {s["file"]: s for s in list_subagents(subs)["subagents"]}

    run_entry = by_file["run/"]
    assert run_entry["id"] == "run"
    assert run_entry["name"] == "run"
    assert run_entry["status"] == ""
    assert run_entry["cmd"] == ""

    flat_entry = by_file["flat.json"]
    assert flat_entry["status"] == ""
    assert flat_entry["cmd"] == ""


def test_mtime_iso_reuses_supplied_stat_result(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    stat_result = target.stat()

    assert _mtime_iso(target, stat_result) == _mtime_iso(target)


def test_read_json_dict_rejects_non_objects(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2]", encoding="utf-8")
    broken = tmp_path / "broken.json"
    broken.write_text("{oops", encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"a": 1}), encoding="utf-8")

    assert _read_json_dict(arr) is None
    assert _read_json_dict(broken) is None
    assert _read_json_dict(tmp_path / "missing.json") is None
    assert _read_json_dict(good) == {"a": 1}


def test_unified_bridge_resource_wrappers():
    assert isinstance(ub._list_reports_sync(), list)
    assert ub._hooks_list_sync()["ok"] is True
