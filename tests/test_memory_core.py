import memory_core as mc


def _w(p, s): p.write_bytes(s.encode("utf-8"))
def _r(p): return p.read_bytes().decode("utf-8")


def test_archive_file_lossless_and_collision_safe(tmp_path):
    arc = tmp_path / "memory-archive"
    n1 = mc.archive_file(arc, "a.md", "> RETIRED 2026-06-16 — x\n\n", b"ONE", tmp_path / "a.md")
    n2 = mc.archive_file(arc, "a.md", "> RETIRED 2026-06-16 — y\n\n", b"TWO", tmp_path / "a.md")
    assert n1 == "a.md" and n2 == "a.1.md"               # collision-safe
    assert (arc / "a.md").read_bytes().endswith(b"ONE")  # lossless raw bytes
    assert (arc / "a.1.md").read_bytes().endswith(b"TWO")


def test_rewrite_index_drop_replace_append_eol(tmp_path):
    idx = tmp_path / "MEMORY.md"
    idx.write_bytes(b"# Index\r\n- [a.md](a.md) - a\n- [b.md](b.md) - b\n")
    mc.rewrite_index(idx, drop={"b.md"}, replace={"a.md": "- [a.md](a.md) - short"},
                     append=["- [c.md](c.md) - new"])
    out = idx.read_bytes().decode("utf-8")
    assert b"\r\n" in idx.read_bytes()          # CRLF header preserved
    assert "(b.md)" not in out and "short" in out and "(c.md)" in out


def test_fix_inbound_links_repoint_and_unlink(tmp_path):
    (tmp_path / "keep.md").write_bytes(b"---\nname: keep\n---\nsee [[old]] and [[gone]]\n")
    gone = {"old.md": {"action": "absorb", "norms": {"old"}, "canon_stem": "merged"},
            "gone.md": {"action": "retire", "norms": {"gone"}}}
    edited = mc.fix_inbound_links(tmp_path, gone, survivor_norms=set(), skip_files=set())
    body = _r(tmp_path / "keep.md")
    assert "keep.md" in edited
    assert "[[merged]]" in body and "gone (archived)" in body


def test_safe_name_rejects_traversal(tmp_path):
    import pytest
    for bad in ("../x.md", "a/b.md", "x.md ", "NUL.md", "x:ads"):
        with pytest.raises(SystemExit):
            mc._safe_name(bad)
