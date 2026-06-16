import pytest

import apply as ap


def _w(p, s):
    p.write_bytes(s.encode("utf-8"))


def _r(p):
    return p.read_bytes().decode("utf-8")


def _store(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    _w(mem / "MEMORY.md",
       "# Index\n"
       "- [keep.md](keep.md) — kept entry, links to others\n"
       "- [old.md](old.md) — SUPERSEDED old thing\n"
       "- [cache_ttl.md](cache_ttl.md) — cache ttl\n"
       "- [cache_evict.md](cache_evict.md) — cache eviction\n"
       "- [fat.md](fat.md) — " + ("x" * 250) + "\n")
    _w(mem / "keep.md", "---\nname: keep\ntype: project\n---\nsee [[old]] and [[cache_ttl]] and [[cache_evict]]\n")
    _w(mem / "old.md", "---\nname: old\ntype: feedback\n---\nSUPERSEDED body content\n")
    _w(mem / "cache_ttl.md", "---\nname: cache_ttl\ntype: feedback\n---\nttl tuning\n")
    _w(mem / "cache_evict.md", "---\nname: cache_evict\ntype: feedback\n---\neviction policy\n")
    _w(mem / "fat.md", "---\nname: fat\ntype: project\n---\nfull detail lives here\n")
    return mem


def _manifest():
    return {
        "date": "2026-06-15",
        "retire": [{"file": "old.md", "reason": "superseded by the canonical note"}],
        "merge": [{
            "canonical_file": "caching.md",
            "canonical_body": "---\nname: caching\ntype: feedback\n---\nttl + eviction\n",
            "canonical_index_line": "- [caching.md](caching.md) — cache ttl + eviction",
            "absorbed": ["cache_ttl.md", "cache_evict.md"],
        }],
        "shorten": [{"file": "fat.md", "new_index_line": "- [fat.md](fat.md) — short pointer"}],
    }


def test_retire_archives_tombstones_and_removes(tmp_path):
    mem = _store(tmp_path)
    ap.apply_plan(mem, _manifest())
    arc = mem.parent / "memory-archive"
    assert not (mem / "old.md").exists()                       # removed from active store
    assert (arc / "old.md").exists()                           # archived
    body = _r(arc / "old.md")
    assert body.startswith("> RETIRED 2026-06-15 — superseded by the canonical note")  # tombstone
    assert "SUPERSEDED body content" in body                   # original content preserved


def test_merge_writes_canonical_and_archives_absorbed(tmp_path):
    mem = _store(tmp_path)
    ap.apply_plan(mem, _manifest())
    arc = mem.parent / "memory-archive"
    assert (mem / "caching.md").exists()
    assert not (mem / "cache_ttl.md").exists() and not (mem / "cache_evict.md").exists()
    assert _r(arc / "cache_ttl.md").startswith("> MERGED 2026-06-15 into caching")


def test_index_rewrite(tmp_path):
    mem = _store(tmp_path)
    ap.apply_plan(mem, _manifest())
    idx = _r(mem / "MEMORY.md")
    assert "(old.md)" not in idx and "(cache_ttl.md)" not in idx and "(cache_evict.md)" not in idx  # gone
    assert "(caching.md)" in idx                                            # merged line added
    assert "short pointer" in idx and ("x" * 250) not in idx                        # shortened


def test_inbound_unlink_and_repoint(tmp_path):
    mem = _store(tmp_path)
    ap.apply_plan(mem, _manifest())
    keep = _r(mem / "keep.md")
    assert "old (archived)" in keep and "[[old]]" not in keep        # retired -> unlinked
    assert "[[caching]]" in keep                              # absorbed -> repointed
    assert "[[cache_ttl]]" not in keep and "[[cache_evict]]" not in keep


def test_preserves_crlf(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(b"# Index\r\n- [keep.md](keep.md) - x\r\n- [old.md](old.md) - y\r\n")
    (mem / "keep.md").write_bytes(b"---\r\nname: keep\r\ntype: project\r\n---\r\nsee [[old]]\r\n")
    (mem / "old.md").write_bytes(b"---\nname: old\ntype: feedback\n---\nbody\n")
    ap.apply_plan(mem, {"date": "2026-06-15", "retire": [{"file": "old.md", "reason": "x"}]})
    keep_raw = (mem / "keep.md").read_bytes()
    assert b"\r\n" in keep_raw and b"old (archived)" in keep_raw      # CRLF preserved on edit
    idx_raw = (mem / "MEMORY.md").read_bytes()
    assert b"\r\n" in idx_raw and b"(old.md)" not in idx_raw          # CRLF preserved on rewrite


def test_dry_run_mutates_nothing(tmp_path):
    mem = _store(tmp_path)
    before = {p.name: p.read_bytes() for p in mem.glob("*.md")}
    summary = ap.apply_plan(mem, _manifest(), dry_run=True)
    after = {p.name: p.read_bytes() for p in mem.glob("*.md")}
    assert before == after
    assert not (mem.parent / "memory-archive").exists()
    assert "old.md" in summary["retired"] and "caching.md" in summary["merged"]


def test_missing_file_errors_before_any_mutation(tmp_path):
    mem = _store(tmp_path)
    before = {p.name: p.read_bytes() for p in mem.glob("*.md")}
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "2026-06-15",
                            "retire": [{"file": "nonexistent.md", "reason": "x"}]})
    after = {p.name: p.read_bytes() for p in mem.glob("*.md")}
    assert before == after                                           # validate-all-then-mutate
    assert not (mem.parent / "memory-archive").exists()


# --- security / robustness (audit-driven) ---

def test_rejects_path_traversal_and_leaves_external_file(tmp_path):
    mem = _store(tmp_path)
    (tmp_path / "victim.txt").write_bytes(b"precious")
    before = {p.name: p.read_bytes() for p in mem.glob("*.md")}
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "retire": [{"file": "../../victim.txt", "reason": "x"}]})
    assert (tmp_path / "victim.txt").read_bytes() == b"precious"     # external file untouched
    assert before == {p.name: p.read_bytes() for p in mem.glob("*.md")}


def test_rejects_absolute_canonical(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "merge": [{
            "canonical_file": str(tmp_path / "out.md"), "canonical_body": "x",
            "canonical_index_line": "- [x](x.md)", "absorbed": ["cache_ttl.md"]}]})
    assert not (tmp_path / "out.md").exists()


def test_rejects_slash_in_name(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "retire": [{"file": "sub/old.md", "reason": "x"}]})


def test_rejects_canonical_clobbering_a_survivor(tmp_path):
    mem = _store(tmp_path)
    keep_before = (mem / "keep.md").read_bytes()
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "merge": [{
            "canonical_file": "keep.md", "canonical_body": "CLOBBER",
            "canonical_index_line": "- [keep.md](keep.md)", "absorbed": ["cache_ttl.md"]}]})
    assert (mem / "keep.md").read_bytes() == keep_before             # survivor intact, not overwritten


def test_rejects_retire_absorbed_overlap(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d",
                            "retire": [{"file": "cache_ttl.md", "reason": "x"}],
                            "merge": [{"canonical_file": "new.md", "canonical_body": "x",
                                       "canonical_index_line": "- [new.md](new.md)", "absorbed": ["cache_ttl.md"]}]})


def test_rejects_index_file_as_target(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "retire": [{"file": "MEMORY.md", "reason": "x"}]})


def test_rejects_missing_required_key_no_partial_apply(tmp_path):
    mem = _store(tmp_path)
    before = {p.name: p.read_bytes() for p in mem.glob("*.md")}
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "merge": [{
            "canonical_file": "new.md", "canonical_body": "x",
            "absorbed": ["cache_ttl.md"]}]})                                # missing canonical_index_line
    assert before == {p.name: p.read_bytes() for p in mem.glob("*.md")}
    assert not (mem / "new.md").exists()                             # nothing written


def test_rejects_empty_absorbed(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "merge": [{
            "canonical_file": "new.md", "canonical_body": "x",
            "canonical_index_line": "- [new.md](new.md)", "absorbed": []}]})


def test_dry_run_validates_too(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):                                  # bad manifest fails even in dry-run
        ap.apply_plan(mem, {"date": "d", "retire": [{"file": "../escape.md", "reason": "x"}]}, dry_run=True)


def test_canonical_body_not_self_rewritten(tmp_path):
    mem = _store(tmp_path)
    body = "---\nname: caching\ntype: feedback\n---\nsupersedes [[cache_ttl]] and [[cache_evict]]\n"
    ap.apply_plan(mem, {"date": "2026-06-15", "merge": [{
        "canonical_file": "caching.md", "canonical_body": body,
        "canonical_index_line": "- [caching.md](caching.md) — x",
        "absorbed": ["cache_ttl.md", "cache_evict.md"]}]})
    assert _r(mem / "caching.md") == body                    # author's body left intact


def test_empty_manifest_is_noop(tmp_path):
    mem = _store(tmp_path)
    before = {p.name: p.read_bytes() for p in mem.glob("*.md")}
    ap.apply_plan(mem, {})
    assert before == {p.name: p.read_bytes() for p in mem.glob("*.md")}
    assert not (mem.parent / "memory-archive").exists()              # no side effects


# --- round-2 audit: Windows filename aliasing, EOL regression, canonical placement, raw archive ---

def test_rejects_trailing_space_alias(tmp_path):
    mem = _store(tmp_path)
    keep_before = (mem / "keep.md").read_bytes()
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "retire": [{"file": "keep.md ", "reason": "x"}]})
    assert (mem / "keep.md").read_bytes() == keep_before             # real file untouched (no NTFS aliasing)


def test_rejects_trailing_space_on_index_name(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "retire": [{"file": "MEMORY.md ", "reason": "x"}]})
    assert (mem / "MEMORY.md").exists()


def test_rejects_case_alias_not_in_listing(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):       # real file is keep.md; "Keep.md" is not an exact listing entry
        ap.apply_plan(mem, {"date": "d", "retire": [{"file": "Keep.md", "reason": "x"}]})
    assert (mem / "keep.md").exists()


def test_rejects_reserved_device_name(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d", "merge": [{
            "canonical_file": "NUL.md", "canonical_body": "x",
            "canonical_index_line": "- [NUL.md](NUL.md)", "absorbed": ["cache_ttl.md"]}]})


def test_mixed_eol_index_preserves_all_survivors(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(   # CRLF header + LF body lines (mixed)
        b"# Index\r\n- [keep.md](keep.md) - k\n- [old.md](old.md) - gone\n- [more.md](more.md) - m\n")
    for n in ("keep", "old", "more"):
        (mem / (n + ".md")).write_bytes(("---\nname: %s\ntype: project\n---\nb\n" % n).encode("utf-8"))
    ap.apply_plan(mem, {"date": "d", "retire": [{"file": "old.md", "reason": "x"}]})
    idx = (mem / "MEMORY.md").read_bytes().decode("utf-8")
    assert "(keep.md)" in idx and "(more.md)" in idx                 # survivors NOT dropped by EOL glueing
    assert "(old.md)" not in idx                                     # only the retired one is gone


def test_canonical_line_appended_when_no_absorbed_indexed(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(b"# Index\n- [top.md](top.md) - t\n")   # uix.md not in index
    for n in ("top", "uix"):
        (mem / (n + ".md")).write_bytes(("---\nname: %s\ntype: project\n---\nb\n" % n).encode("utf-8"))
    ap.apply_plan(mem, {"date": "d", "merge": [{
        "canonical_file": "m.md", "canonical_body": "---\nname: m\ntype: project\n---\nb\n",
        "canonical_index_line": "- [m.md](m.md) - merged", "absorbed": ["uix.md"]}]})
    idx = (mem / "MEMORY.md").read_bytes().decode("utf-8")
    assert "(m.md)" in idx                                           # canonical pointer present (appended), not vanished


def test_archive_preserves_non_utf8_bytes(tmp_path):
    mem = _store(tmp_path)
    (mem / "old.md").write_bytes(b"---\nname: old\ntype: feedback\n---\ncaf\xe9 latin1\n")  # 0xE9 = invalid utf-8
    ap.apply_plan(mem, {"date": "d", "retire": [{"file": "old.md", "reason": "x"}]})
    arc = (mem.parent / "memory-archive" / "old.md").read_bytes()
    assert b"\xe9" in arc                                            # original bytes preserved verbatim


def test_rejects_retire_shorten_overlap(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):
        ap.apply_plan(mem, {"date": "d",
                            "retire": [{"file": "fat.md", "reason": "x"}],
                            "shorten": [{"file": "fat.md", "new_index_line": "- [fat.md](fat.md) - s"}]})


def test_rejects_index_line_wrong_target(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):       # shorten line links to a different file than `file`
        ap.apply_plan(mem, {"date": "d", "shorten": [{
            "file": "fat.md", "new_index_line": "- [keep.md](keep.md) - oops"}]})


def test_rejects_non_dict_entry(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):       # clean error, not AttributeError
        ap.apply_plan(mem, {"date": "d", "retire": ["old.md"]})


# --- round-3 audit: terminator-less append glue, case-colliding canonicals ---

def test_append_onto_terminatorless_index_keeps_both(tmp_path):
    import analyze_memory as am
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(b"# Index\n- [keep.md](keep.md) - kept")   # NO trailing newline
    for n in ("keep", "uix"):
        (mem / (n + ".md")).write_bytes(("---\nname: %s\ntype: project\n---\nb\n" % n).encode("utf-8"))
    ap.apply_plan(mem, {"date": "d", "merge": [{
        "canonical_file": "m.md", "canonical_body": "---\nname: m\ntype: project\n---\nb\n",
        "canonical_index_line": "- [m.md](m.md) - merged", "absorbed": ["uix.md"]}]})
    idx = (mem / "MEMORY.md").read_bytes().decode("utf-8")
    assert "kept- [m.md]" not in idx                                 # NOT glued onto the prior line
    targets = [e["target"] for e in am.parse_index(idx)["entries"]]
    assert "keep.md" in targets and "m.md" in targets                # both pointers parseable


def test_rejects_case_colliding_canonicals(tmp_path):
    mem = _store(tmp_path)
    with pytest.raises(SystemExit):       # Merged.md + merged.md = same file on a case-insensitive FS
        ap.apply_plan(mem, {"date": "d", "merge": [
            {"canonical_file": "Merged.md", "canonical_body": "one",
             "canonical_index_line": "- [Merged.md](Merged.md)", "absorbed": ["cache_ttl.md"]},
            {"canonical_file": "merged.md", "canonical_body": "two",
             "canonical_index_line": "- [merged.md](merged.md)", "absorbed": ["cache_evict.md"]}]})


# --- round-4 audit: matcher alignment, archive collision, inbound norm collision ---

def test_text_before_link_pointer_dropped_no_orphan(tmp_path):
    import analyze_memory as am
    mem = tmp_path / "memory"
    mem.mkdir()
    # 'g.md' line has text between the bullet and the link — the analyzer counts it as an
    # entry, so apply must too (else a dangling pointer survives -> orphan).
    (mem / "MEMORY.md").write_bytes(b"# Index\n- [keep.md](keep.md) - k\n- See also [g.md](g.md) - gone\n")
    for n in ("keep", "g"):
        (mem / (n + ".md")).write_bytes(("---\nname: %s\ntype: project\n---\nb\n" % n).encode("utf-8"))
    ap.apply_plan(mem, {"date": "d", "retire": [{"file": "g.md", "reason": "x"}]})
    idx = (mem / "MEMORY.md").read_bytes().decode("utf-8")
    assert "(g.md)" not in idx
    assert am.analyze(mem)["orphans"] == []                          # Phase-5 contract upheld


def test_archive_collision_keeps_both_versions(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(b"# Index\n- [a.md](a.md) - a\n")
    (mem / "a.md").write_bytes(b"---\nname: a\ntype: project\n---\nVERSION ONE\n")
    ap.apply_plan(mem, {"date": "d", "retire": [{"file": "a.md", "reason": "v1"}]})
    (mem / "MEMORY.md").write_bytes(b"# Index\n- [a.md](a.md) - a\n")     # a.md recreated + re-indexed
    (mem / "a.md").write_bytes(b"---\nname: a\ntype: project\n---\nVERSION TWO\n")
    ap.apply_plan(mem, {"date": "d", "retire": [{"file": "a.md", "reason": "v2"}]})
    arc = mem.parent / "memory-archive"
    both = (arc / "a.md").read_bytes() + (arc / "a.1.md").read_bytes()
    assert b"VERSION ONE" in both and b"VERSION TWO" in both          # neither archived copy lost


def test_inbound_link_to_surviving_collision_not_rewritten(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(
        b"# Index\n- [foo-bar.md](foo-bar.md) - s\n- [foo_bar.md](foo_bar.md) - g\n- [ref.md](ref.md) - r\n")
    (mem / "foo-bar.md").write_bytes(b"---\nname: foo-bar\ntype: project\n---\nsurvivor\n")
    (mem / "foo_bar.md").write_bytes(b"---\nname: foo_bar\ntype: project\n---\ngone\n")
    (mem / "ref.md").write_bytes(b"---\nname: ref\ntype: project\n---\nsee [[foo-bar]]\n")
    ap.apply_plan(mem, {"date": "d", "retire": [{"file": "foo_bar.md", "reason": "x"}]})
    ref = (mem / "ref.md").read_bytes().decode("utf-8")
    assert "[[foo-bar]]" in ref and "(archived)" not in ref           # link to the SURVIVOR untouched


# --- round-5 audit: survivor frontmatter-name collision, duplicate absorbed pointer ---

def test_inbound_link_to_surviving_frontmatter_name_not_rewritten(tmp_path):
    # A retired file and a SURVIVING file share the same frontmatter `name`. The analyzer
    # resolves [[shared_topic]] to the live file (name wins), so apply must leave it intact —
    # survivor resolution must mirror the analyzer's stem-AND-name link model, not stem only.
    import analyze_memory as am
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(
        b"# Index\n- [surv.md](surv.md) - s\n- [gone.md](gone.md) - g\n- [ref.md](ref.md) - r\n")
    (mem / "surv.md").write_bytes(b"---\nname: shared_topic\ntype: project\n---\nsurvivor\n")
    (mem / "gone.md").write_bytes(b"---\nname: shared_topic\ntype: feedback\n---\nretired\n")
    (mem / "ref.md").write_bytes(b"---\nname: ref\ntype: project\n---\nsee [[shared_topic]]\n")
    ap.apply_plan(mem, {"date": "d", "retire": [{"file": "gone.md", "reason": "x"}]})
    ref = (mem / "ref.md").read_bytes().decode("utf-8")
    assert "[[shared_topic]]" in ref and "(archived)" not in ref      # live link not mislabeled
    assert am.analyze(mem)["broken_links"] == []                      # Phase-5 contract upheld


def test_genuinely_dangling_link_still_archived(tmp_path):
    # Guard the inverse: a link to a gone file with NO live namesake must still be rewritten.
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(b"# Index\n- [gone.md](gone.md) - g\n- [ref.md](ref.md) - r\n")
    (mem / "gone.md").write_bytes(b"---\nname: only_here\ntype: feedback\n---\nretired\n")
    (mem / "ref.md").write_bytes(b"---\nname: ref\ntype: project\n---\nsee [[only_here]]\n")
    ap.apply_plan(mem, {"date": "d", "retire": [{"file": "gone.md", "reason": "x"}]})
    ref = (mem / "ref.md").read_bytes().decode("utf-8")
    assert "only_here (archived)" in ref and "[[only_here]]" not in ref


def test_duplicate_absorbed_pointer_emits_canonical_once(tmp_path):
    # The index points at an absorbed file on TWO lines. The merge must emit its canonical
    # line exactly once (not duplicate it), and drop the redundant pointer.
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(
        b"# Index\n- [cache_ttl.md](cache_ttl.md) - first\n- [cache_evict.md](cache_evict.md) - t\n- [cache_ttl.md](cache_ttl.md) - dup pointer\n")
    for n in ("cache_ttl", "cache_evict"):
        (mem / (n + ".md")).write_bytes(("---\nname: %s\ntype: feedback\n---\nb\n" % n).encode("utf-8"))
    ap.apply_plan(mem, {"date": "d", "merge": [{
        "canonical_file": "m.md", "canonical_body": "---\nname: m\ntype: feedback\n---\nb\n",
        "canonical_index_line": "- [m.md](m.md) - merged", "absorbed": ["cache_ttl.md", "cache_evict.md"]}]})
    idx = (mem / "MEMORY.md").read_bytes().decode("utf-8")
    assert idx.count("(m.md)") == 1                                   # canonical line emitted once
    assert "(cache_ttl.md)" not in idx                                       # redundant pointer dropped


def test_duplicate_shorten_pointer_emits_short_line_once(tmp_path):
    # Symmetric to the merge case: a file pointed at by two index lines, both shortened,
    # yields exactly one short line (one pointer per file), not two.
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_bytes(
        b"# Index\n- [fat.md](fat.md) - " + b"x" * 250 + b"\n- [fat.md](fat.md) - " + b"y" * 250 + b"\n")
    (mem / "fat.md").write_bytes(b"---\nname: fat\ntype: project\n---\nbody\n")
    ap.apply_plan(mem, {"date": "d", "shorten": [
        {"file": "fat.md", "new_index_line": "- [fat.md](fat.md) - short hook"}]})
    idx = (mem / "MEMORY.md").read_bytes().decode("utf-8")
    assert idx.count("(fat.md)") == 1 and "short hook" in idx         # one short pointer, not two
    assert ("x" * 250) not in idx and ("y" * 250) not in idx          # both long lines gone
