import pytest
import refresh_apply as ra


def _store(tmp_path):
    mem = tmp_path / "memory"; mem.mkdir()
    (mem / "MEMORY.md").write_text("# Index\n- [a.md](a.md) - hook\n", encoding="utf-8")
    (mem / "a.md").write_text("---\nname: a\ntype: project\n---\nThe firewall lives in core/old.py here.\n", encoding="utf-8")
    return mem


def test_rejects_unsafe_filename(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ra.apply_plan(mem, {"date": "d", "correct": [{"file": "../x.md", "old": "a", "new": "b"}]})


def test_rejects_missing_target(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ra.apply_plan(mem, {"date": "d", "annotate": [{"file": "nope.md", "note": "x"}]})


def test_empty_manifest_noop(tmp_path):
    mem = _store(tmp_path)
    before = {p.name: p.read_bytes() for p in mem.glob("*.md")}
    ra.apply_plan(mem, {})
    assert before == {p.name: p.read_bytes() for p in mem.glob("*.md")}


def test_correct_edits_exact_span(tmp_path):
    mem = _store(tmp_path)
    ra.apply_plan(mem, {"date": "d", "correct": [
        {"file": "a.md", "old": "core/old.py", "new": "core/new.py"}]})
    body = (mem / "a.md").read_text(encoding="utf-8")
    assert "core/new.py" in body and "core/old.py" not in body
    assert body.startswith("---\nname: a\n")          # frontmatter + rest intact


def test_correct_rejects_ambiguous_old(tmp_path):
    mem = tmp_path / "memory"; mem.mkdir()
    (mem / "MEMORY.md").write_text("# Index\n- [d.md](d.md) - d\n", encoding="utf-8")
    (mem / "d.md").write_text("---\nname: d\ntype: project\n---\nx and x again\n", encoding="utf-8")
    with pytest.raises(SystemExit):                    # 'x' appears twice -> reject
        ra.apply_plan(mem, {"date": "d", "correct": [{"file": "d.md", "old": "x", "new": "y"}]})


def test_annotate_inserts_after_frontmatter_idempotent(tmp_path):
    mem = _store(tmp_path)
    m = {"date": "2026-06-16", "annotate": [{"file": "a.md", "note": "dash URL 404"}]}
    ra.apply_plan(mem, m)
    body = (mem / "a.md").read_text(encoding="utf-8")
    assert "> UNVERIFIED 2026-06-16 — dash URL 404" in body
    assert body.index("---\nname") == 0                 # frontmatter still first
    assert "The firewall lives in" in body              # fact untouched
    ra.apply_plan(mem, m)                                # run again
    assert (mem / "a.md").read_text(encoding="utf-8").count("> UNVERIFIED") == 1  # no double


def test_retire_archives_drops_pointer_fixes_inbound(tmp_path):
    mem = tmp_path / "memory"; mem.mkdir()
    (mem / "MEMORY.md").write_text("# Index\n- [keep.md](keep.md) - k\n- [z.md](z.md) - z\n", encoding="utf-8")
    (mem / "keep.md").write_text("---\nname: keep\ntype: project\n---\nsee [[z]]\n", encoding="utf-8")
    (mem / "z.md").write_text("---\nname: z\ntype: project\n---\nthe deleted legacy subsystem\n", encoding="utf-8")
    ra.apply_plan(mem, {"date": "2026-06-16", "retire": [{"file": "z.md", "reason": "subsystem deleted"}]})
    arc = mem.parent / "memory-archive"
    assert not (mem / "z.md").exists() and (arc / "z.md").exists()
    assert (arc / "z.md").read_text(encoding="utf-8").startswith("> RETIRED 2026-06-16 — subsystem deleted")
    idx = (mem / "MEMORY.md").read_text(encoding="utf-8")
    assert "(z.md)" not in idx and "(keep.md)" in idx
    keep = (mem / "keep.md").read_text(encoding="utf-8")
    assert "z (archived)" in keep and "[[z]]" not in keep


def test_rejects_retire_with_edit_of_same_file(tmp_path):
    mem = _store(tmp_path)                              # has a.md with "core/old.py"
    before = {p.name: p.read_bytes() for p in mem.glob("*.md")}
    with pytest.raises(SystemExit):
        ra.apply_plan(mem, {"date": "d",
                            "correct": [{"file": "a.md", "old": "core/old.py", "new": "core/new.py"}],
                            "retire": [{"file": "a.md", "reason": "obsolete"}]})
    assert before == {p.name: p.read_bytes() for p in mem.glob("*.md")}   # nothing mutated
    assert not (mem.parent / "memory-archive").exists()


def test_multiple_annotates_on_one_file_stack(tmp_path):
    mem = _store(tmp_path)
    ra.apply_plan(mem, {"date": "2026-06-16", "annotate": [
        {"file": "a.md", "note": "first issue"},
        {"file": "a.md", "note": "second issue"}]})
    body = (mem / "a.md").read_text(encoding="utf-8")
    assert body.count("> UNVERIFIED") == 2
