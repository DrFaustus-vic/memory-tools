import analyze_memory as am


def _write(d, name, text):
    (d / name).write_text(text, encoding="utf-8")


def test_inventory_parses_and_skips_index(tmp_path):
    _write(tmp_path, "MEMORY.md", "- [A](a.md) — x\n")
    _write(tmp_path, "a.md", "---\nname: a\ndescription: d\ntype: project\n---\nbody\n")
    _write(tmp_path, "b.md", "---\nname: b\ndescription: d2\nmetadata:\n  type: feedback\n---\nSUPERSEDED later\n")
    files = am.inventory_files(tmp_path)
    names = sorted(f["filename"] for f in files)
    assert names == ["a.md", "b.md"]  # MEMORY.md excluded


def test_inventory_captures_type_variant_and_stale(tmp_path):
    _write(tmp_path, "b.md", "---\nname: b\ndescription: d2\nmetadata:\n  type: feedback\n---\nSUPERSEDED later\n")
    files = am.inventory_files(tmp_path)
    b = files[0]
    assert b["type"] == "feedback"
    assert b["schema_variant"] == "nested"
    assert b["stale_markers"] == ["SUPERSEDED"]
    assert b["bytes"] > 0


def test_inventory_falls_back_to_stem_when_no_name(tmp_path):
    _write(tmp_path, "c.md", "no frontmatter\n")
    files = am.inventory_files(tmp_path)
    assert files[0]["name"] == "c"
