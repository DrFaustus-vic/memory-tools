"""Deterministic, read-only verification scan for /memory-tools:refresh-memory.

Stdlib only. Extracts references from each memory entry and checks them against ground
truth (filesystem, git, external URLs). Emits a JSON report; performs NO mutations.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import memory_core as mc  # noqa: E402

URL_RE = re.compile(r"https?://[^\s`<>()\]]+")
BACKTICK_RE = re.compile(r"`([^`]+)`")
# A backticked token is code-like (worth checking) only if it looks like code:
# a path, a --flag, a dotted/underscored/CamelCase identifier. Plain prose is ignored.
SYMBOL_RE = re.compile(r"^(--[\w-]+|[A-Za-z_][\w]*(?:\.[\w]+)+|[A-Za-z_][\w]*_[\w]*|"
                       r"[a-z]+[A-Z][\w]*|[A-Z][a-z]+[A-Z][\w]*)$")
KNOWN_EXT = (".py", ".md", ".json", ".js", ".ts", ".tsx", ".jsx", ".txt", ".toml",
             ".yml", ".yaml", ".csv", ".html", ".css", ".scss", ".sh", ".go", ".rs",
             ".java", ".rb", ".c", ".h", ".cpp", ".hpp", ".cs", ".kt", ".swift",
             ".php", ".scala", ".ini", ".cfg", ".xml", ".sql")
# A path ref must carry a real file extension (above). These rule out the false-path
# classes that flooded the scan: web routes (`/api/...`), templates/globs (`{id}.json`,
# `*.min.js`), scheme-less URLs (`example.com/docs/page.json`), and git branch names (`feat/x`,
# which have no extension and are dropped by the extension gate alone).
_TEMPLATE_CHARS = "{}<>*|?"
_DOMAIN_RE = re.compile(
    r"^[\w-]+(\.[\w-]+)*\.(com|net|org|io|co|news|app|dev|ai|gov|cn|tv|me|info|xyz)$")


def _is_pathish(tok):
    """True only for tokens we can deterministically check as a project file path."""
    if " " in tok or tok[:1] in ("/", "~"):
        return False                                   # prose / absolute route / home path
    if any(c in tok for c in _TEMPLATE_CHARS):
        return False                                   # template / glob placeholder
    if not tok.endswith(KNOWN_EXT) or Path(tok).name in KNOWN_EXT:
        return False                                   # needs a real ext; not a bare `.py`
    if _DOMAIN_RE.match(tok.split("/", 1)[0]):
        return False                                   # scheme-less URL host
    return True


def extract_refs(body):
    """Return a de-duped list of {ref, kind} for paths / symbols / urls found in `body`."""
    found = {}
    for m in URL_RE.finditer(body):
        url = m.group(0).rstrip(".,;)")
        found.setdefault(url, "url")
    for m in BACKTICK_RE.finditer(body):
        tok = m.group(1).strip()
        if tok in found:
            continue
        if _is_pathish(tok):
            found[tok] = "path"
        elif " " not in tok and SYMBOL_RE.match(tok):
            found[tok] = "symbol"
    return [{"ref": r, "kind": k} for r, k in found.items()]


_TRACKED_CACHE = {}
# Dependency / build / cache directories: a ref INTO one of these names a library file
# or build artifact, not a project source file. Unresolved -> `inconclusive` (can't verify),
# never `dangling`. (Scratch / gitignored paths are deliberately NOT reclassified here:
# no deterministic signal separates ephemeral scratch from a deleted-real file — both look
# the same — so leaving them `dangling` for the Phase-2 ground-truth read is correct.)
_DEP_SEGS = frozenset({
    "node_modules", "site-packages", "vendor", "dist", "build", "target",
    ".venv", "venv", "__pycache__", ".tox", ".next", ".nuxt", "bower_components",
})


def _tracked_index(project_root):
    """Cached (full-set, by-basename) index of git-tracked paths under project_root.
    Lets a shorthand ref (`core/x.py`) or bare basename (`x.py`) resolve when the file
    lives in a subdir. Non-git roots / git failures yield an empty index (no-op)."""
    key = str(project_root)
    idx = _TRACKED_CACHE.get(key)
    if idx is None:
        full, by_base = set(), defaultdict(set)
        try:
            r = subprocess.run(["git", "ls-files"], cwd=key,
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    line = line.strip()
                    if line:
                        full.add(line)
                        by_base[line.rsplit("/", 1)[-1]].add(line)
        except (OSError, subprocess.SubprocessError):
            pass
        idx = (full, by_base)
        _TRACKED_CACHE[key] = idx
    return idx


def check_path(ref, project_root, memory_dir=None):
    norm = ref.strip().replace("\\", "/").rstrip("/")
    if not norm:
        return "dangling"
    if (Path(project_root) / norm).exists():           # exact, root-relative (incl. gitignored)
        return "resolved"
    if memory_dir is not None and (Path(memory_dir) / norm).exists():
        return "resolved_memory"                       # sibling memory file, not project-path evidence
    full, by_base = _tracked_index(project_root)
    if norm in full:
        return "resolved"
    candidates = by_base.get(norm.rsplit("/", 1)[-1], ())
    if "/" in norm:
        seg = "/" + norm                               # suffix match on a segment boundary
        for p in candidates:
            if p == norm or p.endswith(seg):
                return "resolved"
    else:                                              # bare basename
        if len(candidates) == 1:
            return "resolved"                          # one namesake -> confident
        if len(candidates) > 1:
            return "inconclusive"                      # ambiguous namesake -> can't confirm gone
    # Dependency/build dir, PREFIX-SCOPED: a ref into `<prefix>/<dep>/...` is a library/build
    # artifact -> `inconclusive` ONLY if that specific directory holds no tracked files. A repo
    # that tracks a real source dir named `build/` (etc.) still DANGLES its misses; the dep name
    # appearing elsewhere in the tree can't disable the gate for an unrelated path.
    parts = norm.split("/")
    for i, sgmt in enumerate(parts):
        if sgmt in _DEP_SEGS:
            prefix = "/".join(parts[:i + 1]) + "/"
            if not any(p.startswith(prefix) for p in full):
                return "inconclusive"                  # untracked dependency/build dir
            break                                      # this dep-named dir IS tracked source
    return "dangling"


def _is_git_repo(project_root):
    return (Path(project_root) / ".git").exists()


def check_symbol(ref, project_root):
    """A literal substring search for the symbol across the repo. Found -> resolved.
    Absent -> 'inconclusive' (could be a rename or live in a dependency), never 'dangling'."""
    root = Path(project_root)
    try:
        if _is_git_repo(root):
            r = subprocess.run(["git", "grep", "-qF", "--", ref], cwd=str(root),
                               capture_output=True, timeout=15)
            return "resolved" if r.returncode == 0 else "inconclusive"
        for p in root.rglob("*"):
            if p.is_file() and p.stat().st_size < 2_000_000:
                try:
                    if ref in p.read_text(encoding="utf-8", errors="ignore"):
                        return "resolved"
                except OSError:
                    continue
        return "inconclusive"
    except (subprocess.SubprocessError, OSError):
        return "inconclusive"


def _default_fetcher(url):
    """Return the HTTP status code. HEAD, falling back to GET. Read-only, no auth, 5s."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        if e.code == 405:  # HEAD not allowed -> try GET
            with urllib.request.urlopen(urllib.request.Request(url), timeout=5) as r:
                return r.status
        return e.code


def check_url(url, fetcher=_default_fetcher):
    try:
        code = fetcher(url)
    except Exception as exc:                       # noqa: BLE001 — any network error
        return {"status": "inconclusive", "detail": type(exc).__name__}
    if code in (404, 410):
        return {"status": "dead", "detail": str(code)}
    if 200 <= code < 400:
        return {"status": "reachable", "detail": str(code)}
    return {"status": "inconclusive", "detail": str(code)}   # 5xx etc. != dead


WRONG_ROOT_THRESHOLD = 0.5
# Guard is PATH-SCOPED: only dangling-vs-resolved PATHS feed the rate.
# Absent symbols resolve to `inconclusive` (not `dangling`) by design, and reachable
# URLs are not path evidence — both are excluded so they can't dilute the signal.
# The guard targets the catastrophic "pointed at the wrong repo" case, which yields
# dangling paths, not symbol drift or URL churn.
SEMANTIC_TYPES = {"project", "reference"}


def scan(memory_dir, project_root, network=True, fetcher=_default_fetcher):
    files = mc.inventory_files(memory_dir)
    entries, dangling, dead, inconclusive, verifiable = [], 0, 0, 0, 0
    dangling_paths, resolved_paths = 0, 0
    for f in files:
        refs = []
        for r in extract_refs(f["body"]):
            kind = r["kind"]
            if kind == "path":
                status = check_path(r["ref"], project_root, memory_dir=memory_dir)
            elif kind == "symbol":
                status = check_symbol(r["ref"], project_root)
            else:  # url
                status = "inconclusive" if not network else check_url(r["ref"], fetcher)["status"]
            # `resolved_memory` is internal: shown as `resolved`, but it is NOT project-path
            # evidence, so it feeds neither guard bucket (can't desensitize wrong-root).
            pub = "resolved" if status == "resolved_memory" else status
            refs.append({"ref": r["ref"], "kind": kind, "status": pub})
            if kind in ("path", "symbol") or pub != "inconclusive":
                verifiable += 1
            dangling += pub == "dangling"
            dead += pub == "dead"
            inconclusive += pub == "inconclusive"
            if kind == "path":
                if status == "dangling":
                    dangling_paths += 1
                elif status == "resolved":
                    resolved_paths += 1
        entries.append({
            "filename": f["filename"], "type": f["type"],
            "flagged": (bool(refs) and f["type"] in SEMANTIC_TYPES)
                       or any(rr["status"] in ("dangling", "dead") for rr in refs),
            "needs_semantic_review": f["type"] in SEMANTIC_TYPES and bool(refs),
            "refs": refs,
        })
    path_total = dangling_paths + resolved_paths
    rate = (dangling_paths / path_total) if path_total else 0.0
    return {
        "memory_dir": str(memory_dir), "project_root": str(project_root), "network": network,
        "summary": {"entries": len(files), "verifiable_refs": verifiable,
                    "dangling": dangling, "dead_links": dead, "inconclusive": inconclusive,
                    "dangling_paths": dangling_paths, "resolved_paths": resolved_paths,
                    "dangling_rate": round(rate, 3)},
        "wrong_root_suspected": rate > WRONG_ROOT_THRESHOLD,
        "entries": entries,
    }


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        if hasattr(st, "reconfigure"):
            try:
                st.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser(description="Verify memory entries against ground truth (read-only).")
    ap.add_argument("--memory-dir")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    mem = mc.resolve_memory_dir(args.memory_dir)
    rep = scan(mem, Path(args.project_root).expanduser().resolve(), network=not args.no_network)
    if args.json:
        json.dump(rep, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        s = rep["summary"]
        print(f"entries={s['entries']} dangling={s['dangling']} dead={s['dead_links']} "
              f"inconclusive={s['inconclusive']} rate={s['dangling_rate']} "
              f"wrong_root_suspected={rep['wrong_root_suspected']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
