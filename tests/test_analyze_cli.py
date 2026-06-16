import json
import subprocess
import sys
from pathlib import Path

import analyze_memory as am

SCRIPT = (Path(__file__).resolve().parent.parent
          / "plugins" / "memory-tools" / "skills" / "compact-memory" / "scripts" / "analyze_memory.py")


def _store(tmp_path):
    (tmp_path / "MEMORY.md").write_text(
        "# Index\n- [A](a.md) — hook\n- [Gone](gone.md) — orphan\n", encoding="utf-8")
    (tmp_path / "a.md").write_text(
        "---\nname: a\ndescription: cache ttl config\ntype: reference\n---\nsee [[ghost]]\n", encoding="utf-8")
    (tmp_path / "b.md").write_text(
        "---\nname: b\ndescription: cache ttl eviction\ntype: reference\n---\nSUPERSEDED\n", encoding="utf-8")
    return tmp_path


def test_analyze_report_shape(tmp_path):
    rpt = am.analyze(_store(tmp_path))
    assert rpt["file_count"] == 2
    assert rpt["index"]["over_lines"] is False
    assert [o["target"] for o in rpt["orphans"]] == ["gone.md"]
    assert "b.md" in rpt["unindexed"]
    assert rpt["broken_links"] == [{"from": "a.md", "to": "ghost"}]
    assert "b.md" in rpt["stale_files"]
    assert rpt["store_convention"]["type_style"] == "flat"
    # internal 'body' must not leak into the report
    assert all("body" not in f for f in rpt["files"])


def test_cli_emits_json(tmp_path):
    store = _store(tmp_path)
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--memory-dir", str(store), "--json"],
        capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    assert data["file_count"] == 2
    assert data["memory_dir"] == str(store)


def test_cli_json_handles_non_ascii(tmp_path):
    # Memory content can hold arrows / em-dashes / CJK. --json must emit UTF-8
    # regardless of the platform's default stdout encoding (Windows cp1252 crashed
    # on U+2192). Decode bytes explicitly so the test doesn't depend on the parent process encoding.
    (tmp_path / "MEMORY.md").write_text(
        "# Index\n- [Flow](a.md) — disk → memory cache\n", encoding="utf-8")
    (tmp_path / "a.md").write_text(
        "---\nname: a\ndescription: retry → backoff 你好\ntype: reference\n---\nbody\n",
        encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--memory-dir", str(tmp_path), "--json"],
        capture_output=True)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    data = json.loads(out.stdout.decode("utf-8"))
    assert data["file_count"] == 1


def test_analyze_empty_dir(tmp_path):
    # A brand-new / empty memory dir must not crash and must report a clean zero state.
    rpt = am.analyze(tmp_path)
    assert rpt["file_count"] == 0
    assert rpt["index_present"] is False
    assert rpt["index"]["lines"] == 0
    assert rpt["dup_clusters"] == []
    assert rpt["orphans"] == [] and rpt["unindexed"] == []
