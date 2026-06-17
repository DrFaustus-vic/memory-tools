import refresh_scan as rs


def test_extract_refs_classifies_paths_symbols_urls():
    body = ("See `core/cache_client.py` and the `fetch_by_id` helper. "
            "Pass `--force`. Docs: https://docs.example.com/x . "
            "Plain words and `e g` are not symbols. Version 1.2.3 is not a ref. "
            "Also `s3_bucket` is a symbol.")
    refs = rs.extract_refs(body)
    kinds = {r["ref"]: r["kind"] for r in refs}
    assert kinds.get("core/cache_client.py") == "path"
    assert kinds.get("fetch_by_id") == "symbol"
    assert kinds.get("--force") == "symbol"
    assert kinds.get("https://docs.example.com/x") == "url"
    assert kinds.get("s3_bucket") == "symbol"
    assert "e g" not in kinds          # backticked prose with a space is not code-like
    assert "1.2.3" not in kinds        # bare version is not a ref


def test_extract_refs_excludes_routes_templates_branches_domains():
    body = ("Route `/api/users` and `/blog/post/...`. "
            "Template `data/{id}.json` and glob `*.min.js`. "
            "Branch `feat/new-thing`. Scheme-less `example.com/docs/page.json`. "
            "Bare ext `.py`. "
            "Real `src/core/client.py` stays a path.")
    refs = {r["ref"]: r["kind"] for r in rs.extract_refs(body)}
    for noise in ("/api/users", "/blog/post/...", "data/{id}.json",
                  "*.min.js", "feat/new-thing", "example.com/docs/page.json", ".py"):
        assert noise not in refs, f"{noise} should not be a path ref"
    assert refs.get("src/core/client.py") == "path"


def test_extract_refs_excludes_home_paths():
    refs = {r["ref"]: r["kind"] for r in rs.extract_refs("config at `~/.claude/settings.json`")}
    assert "~/.claude/settings.json" not in refs  # home-relative, not project-relative


import subprocess


def _git_repo(tmp_path):
    from pathlib import Path
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "client.py").write_text("def fetch_by_id():\n    pass\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "x"], cwd=tmp_path, check=True)
    return tmp_path


def test_check_path(tmp_path):
    root = _git_repo(tmp_path)
    assert rs.check_path("core/client.py", root) == "resolved"
    assert rs.check_path("core/missing.py", root) == "dangling"


def test_check_path_resolves_basename_in_subdir(tmp_path):
    root = _git_repo(tmp_path)                               # tracks core/client.py
    assert rs.check_path("client.py", root) == "resolved"    # bare basename lives in a subdir
    assert rs.check_path("core/client.py", root) == "resolved"  # exact
    assert rs.check_path("nope_xyz.py", root) == "dangling"  # genuinely absent


def test_check_path_dependency_dir_is_inconclusive(tmp_path):
    root = _git_repo(tmp_path)                              # tracks core/client.py only
    # an unresolved ref INTO a dependency/build dir is a library claim, not a project file:
    # inconclusive (can't verify), never dangling.
    assert rs.check_path("node_modules/leftpad/index.js", root) == "inconclusive"
    assert rs.check_path("dist/bundle.js", root) == "inconclusive"
    # an ordinary project miss still dangles.
    assert rs.check_path("src/missing.py", root) == "dangling"


def test_check_path_resolves_sibling_memory_file(tmp_path):
    root = _git_repo(tmp_path / "proj")                      # repo has core/client.py only
    mem = tmp_path / "memory"; mem.mkdir()
    (mem / "project_status.md").write_text("x", encoding="utf-8")
    # a ref naming another memory file isn't a repo file: distinct status so the wrong-root
    # guard can't be desensitized by sibling-memory resolutions (mapped to "resolved" in output).
    assert rs.check_path("project_status.md", root, memory_dir=mem) == "resolved_memory"
    assert rs.check_path("project_status.md", root) == "dangling"   # no memory context -> absent


def test_check_symbol_git_and_fallback(tmp_path):
    root = _git_repo(tmp_path)
    assert rs.check_symbol("fetch_by_id", root) == "resolved"
    assert rs.check_symbol("no_such_symbol_xyz", root) == "inconclusive"  # absent != deleted


def test_check_url_classification():
    assert rs.check_url("http://x", fetcher=lambda _: 200)["status"] == "reachable"
    assert rs.check_url("http://x", fetcher=lambda _: 404)["status"] == "dead"
    assert rs.check_url("http://x", fetcher=lambda _: 410)["status"] == "dead"
    assert rs.check_url("http://x", fetcher=lambda _: 503)["status"] == "inconclusive"
    assert rs.check_url("http://x", fetcher=lambda _: (_ for _ in ()).throw(TimeoutError()))["status"] == "inconclusive"


def _mem(tmp_path, body):
    mem = tmp_path / "memory"; mem.mkdir()
    (mem / "MEMORY.md").write_text("# Index\n- [e.md](e.md) - e\n", encoding="utf-8")
    (mem / "e.md").write_text("---\nname: e\ntype: project\n---\n" + body + "\n", encoding="utf-8")
    return mem


def test_scan_reports_refs_and_rate(tmp_path):
    root = _git_repo(tmp_path / "proj")           # has core/client.py
    mem = _mem(tmp_path, "uses `core/client.py` and `core/missing.py`")
    rep = rs.scan(mem, root, network=False)
    e = rep["entries"][0]
    statuses = {r["ref"]: r["status"] for r in e["refs"]}
    assert statuses["core/client.py"] == "resolved"
    assert statuses["core/missing.py"] == "dangling"
    assert rep["summary"]["dangling"] == 1
    assert rep["wrong_root_suspected"] is False


def test_scan_wrong_root_guard(tmp_path):
    root = _git_repo(tmp_path / "proj")
    mem = _mem(tmp_path, "needs `a/x.py` and `b/y.py` and `c/z.py`")  # none exist
    rep = rs.scan(mem, root, network=False)
    assert rep["summary"]["dangling_rate"] > 0.5
    assert rep["wrong_root_suspected"] is True


def test_wrong_root_guard_not_diluted_by_symbols_and_urls(tmp_path):
    root = _git_repo(tmp_path / "proj")          # repo has core/client.py only
    mem = tmp_path / "memory"; mem.mkdir()
    (mem / "MEMORY.md").write_text("# Index\n- [e.md](e.md) - e\n", encoding="utf-8")
    (mem / "e.md").write_text(
        "---\nname: e\ntype: project\n---\n"
        "needs `a/x.py` and `b/y.py`; calls `absent_one`, `absent_two`, `absent_three`; "
        "see https://ok.example/d\n", encoding="utf-8")
    rep = rs.scan(mem, root, network=True, fetcher=lambda _: 200)   # url reachable, symbols absent, paths dangling
    assert rep["summary"]["dangling_paths"] == 2 and rep["summary"]["resolved_paths"] == 0
    assert rep["wrong_root_suspected"] is True      # path-scoped: 2/2 = 1.0, NOT diluted to 2/6


def _mkrepo(tmp_path, files):
    """Create a git repo at tmp_path with the given {relpath: content} and commit it."""
    from pathlib import Path as _P
    tmp_path = _P(tmp_path); tmp_path.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "x"], cwd=tmp_path, check=True)
    return tmp_path


def test_extract_refs_includes_common_source_extensions():
    refs = {r["ref"]: r["kind"] for r in rs.extract_refs(
        "see `cmd/main.go`, `src/lib.rs`, and `Service.java`")}
    assert refs.get("cmd/main.go") == "path"
    assert refs.get("src/lib.rs") == "path"
    assert refs.get("Service.java") == "path"   # not mis-routed to a substring symbol grep


def test_dep_dir_rule_skips_tracked_source_dir(tmp_path):
    # a project may legitimately have a SOURCE dir named build/ — a stale ref there must
    # dangle (not be hidden as inconclusive); only an UNtracked dependency dir is inconclusive.
    root = _mkrepo(tmp_path, {"build/compiler.py": "x\n", "src/app.py": "y\n"})
    assert rs.check_path("build/gone.py", root) == "dangling"        # build/ is tracked source
    assert rs.check_path("node_modules/leftpad/i.js", root) == "inconclusive"  # untracked dep dir


def test_dep_dir_rule_is_prefix_scoped_not_global(tmp_path):
    # a tracked web/dist/ source dir must NOT disable the dep-gate for a DIFFERENT, untracked
    # top-level dist/ — the gate is scoped to the ref's own directory prefix, not a global name.
    root = _mkrepo(tmp_path, {"web/dist/keep.js": "x\n", "src/app.py": "y\n"})
    assert rs.check_path("web/dist/old.js", root) == "dangling"      # this dist/ IS tracked source
    assert rs.check_path("dist/bundle.js", root) == "inconclusive"   # a different, untracked dist/


def test_single_segment_dotted_ref_is_path_not_symbol():
    # regression-pin: single-segment dotted tokens with a known ext are PATHS (filesystem-checked),
    # not symbols (substring-grepped) — so an absent one DANGLES rather than reads resolved-by-grep.
    refs = {r["ref"]: r["kind"] for r in rs.extract_refs("config `app.ini` and schema `db.sql`")}
    assert refs.get("app.ini") == "path"
    assert refs.get("db.sql") == "path"


def test_bare_name_ambiguous_is_inconclusive(tmp_path):
    root = _mkrepo(tmp_path, {"a/dup.py": "x\n", "b/dup.py": "y\n", "a/uniq.py": "z\n"})
    assert rs.check_path("uniq.py", root) == "resolved"       # exactly one namesake
    assert rs.check_path("dup.py", root) == "inconclusive"    # ambiguous — can't confirm
    assert rs.check_path("absent.py", root) == "dangling"     # no namesake


def test_check_path_non_git_fallback(tmp_path):
    from pathlib import Path as _P
    root = _P(tmp_path) / "plain"; (root / "a").mkdir(parents=True)
    (root / "a" / "b.py").write_text("x\n", encoding="utf-8")   # not a git repo
    assert rs.check_path("a/b.py", root) == "resolved"          # root-relative .exists() still works
    assert rs.check_path("a/missing.py", root) == "dangling"


def test_check_path_normalizes_backslashes(tmp_path):
    root = _git_repo(tmp_path)                                  # tracks core/client.py
    assert rs.check_path("core\\client.py", root) == "resolved"


def test_memory_dir_hit_does_not_desensitize_guard(tmp_path):
    root = _git_repo(tmp_path / "proj")                         # tracks core/client.py only
    mem = tmp_path / "memory"; mem.mkdir()
    (mem / "MEMORY.md").write_text("# Index\n- [e.md](e.md) - e\n", encoding="utf-8")
    (mem / "sib_one.md").write_text("---\nname: sib_one\ntype: project\n---\nx\n", encoding="utf-8")
    (mem / "sib_two.md").write_text("---\nname: sib_two\ntype: project\n---\nx\n", encoding="utf-8")
    (mem / "e.md").write_text(
        "---\nname: e\ntype: project\n---\n"
        "needs `gone/missing.py`; see `sib_one.md` and `sib_two.md`\n", encoding="utf-8")
    rep = rs.scan(mem, root, network=False)
    statuses = {r["ref"]: r["status"] for e in rep["entries"] for r in e["refs"]}
    assert statuses["sib_one.md"] == "resolved"                 # mapped to resolved in output
    s = rep["summary"]
    # the two memory-file hits are NOT project-path evidence -> they don't pad resolved_paths
    assert s["dangling_paths"] == 1 and s["resolved_paths"] == 0
    assert rep["wrong_root_suspected"] is True                  # 1/1 = 1.0, not diluted to 1/3
