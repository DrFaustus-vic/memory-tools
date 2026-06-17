import subprocess

import refresh_scan as rs
import refresh_apply as ra


def test_end_to_end_scan_then_apply(tmp_path):
    proj = tmp_path / "proj"; (proj / "core").mkdir(parents=True)
    (proj / "core" / "client.py").write_text("def live_symbol(): pass\n")
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    subprocess.run(["git", "add", "-A"], cwd=proj, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], cwd=proj, check=True)

    mem = tmp_path / "memory"; mem.mkdir()
    (mem / "MEMORY.md").write_text(
        "# Index\n- [good.md](good.md) - g\n- [stale.md](stale.md) - s\n- [dead.md](dead.md) - d\n", encoding="utf-8")
    (mem / "good.md").write_text("---\nname: good\ntype: project\n---\nuses `core/client.py` and `live_symbol`\n", encoding="utf-8")
    (mem / "stale.md").write_text("---\nname: stale\ntype: project\n---\nlives in `core/deleted.py`\n", encoding="utf-8")
    (mem / "dead.md").write_text("---\nname: dead\ntype: reference\n---\nsee https://gone.example/x\n", encoding="utf-8")

    rep = rs.scan(mem, proj, network=True, fetcher=lambda _: 404)
    assert rep["wrong_root_suspected"] is False
    # apply the decisions a model would make from the report:
    ra.apply_plan(mem, {"date": "2026-06-16",
        "correct": [{"file": "stale.md", "old": "core/deleted.py", "new": "core/client.py"}],
        "annotate": [{"file": "dead.md", "note": "link 404 on 2026-06-16"}]})

    rep2 = rs.scan(mem, proj, network=False)          # re-scan
    statuses = [r["status"] for e in rep2["entries"] for r in e["refs"] if r["kind"] == "path"]
    assert "dangling" not in statuses                 # correction removed the dangling path
    assert "> UNVERIFIED" in (mem / "dead.md").read_text(encoding="utf-8")
