"""Deterministic, read-only measurement of a Claude Code file-based memory store.

Stdlib only. Emits a JSON report; performs NO mutations. Consumed by the
/memory-tools:compact-memory skill. The script measures; the model judges.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Ensure the plugin-level lib/ dir is importable when this script is run
# directly as a subprocess (conftest adds it for in-process pytest runs).
_LIB = Path(__file__).resolve().parent.parent.parent.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from memory_core import (
    INDEX_FILE, KEBAB_RE, INDEX_LINK_RE, WIKILINK_RE, TOKEN_RE, STOPWORDS,
    MIN_SHARED_TOKENS, STALE_MARKERS, LONG_ENTRY_CHARS, LONG_ENTRY_BYTES,
    INDEX_LINE_LIMIT, INDEX_BYTE_LIMIT,
    parse_frontmatter, inventory_files, _norm_link, build_inbound_links,
    _has_memory, resolve_memory_dir,
)


def parse_index(text):
    raw_bytes = len(text.encode("utf-8"))
    lines = text.splitlines()
    entries = []
    for n, line in enumerate(lines, start=1):
        if not line.lstrip().startswith(("-", "*")):
            continue
        m = INDEX_LINK_RE.search(line)
        if not m:
            continue
        entries.append({"line": n, "title": m.group(1).strip(),
                        "target": m.group(2).strip(), "chars": len(line),
                        "bytes": len(line.encode("utf-8"))})
    return {
        "lines": len(lines),
        "bytes": raw_bytes,
        "over_lines": len(lines) > INDEX_LINE_LIMIT,
        "over_bytes": raw_bytes > INDEX_BYTE_LIMIT,
        "entries": entries,
        "long_entries": [e for e in entries
                         if e["chars"] > LONG_ENTRY_CHARS or e["bytes"] > LONG_ENTRY_BYTES],
    }


def reconcile(index, files):
    file_names = {f["filename"] for f in files}
    referenced = set()
    orphans = []
    for e in index["entries"]:
        target = e["target"].split("/")[-1]
        referenced.add(target)
        if target.endswith(".md") and target not in file_names:
            orphans.append({"target": e["target"], "line": e["line"]})
    unindexed = sorted(fn for fn in file_names if fn not in referenced)
    return {"orphans": orphans, "unindexed": unindexed}


def find_broken_links(files):
    known = set()
    for f in files:
        if f["name"]:
            known.add(_norm_link(f["name"]))
        known.add(_norm_link(Path(f["filename"]).stem))
    broken = []
    for f in files:
        for m in WIKILINK_RE.finditer(f.get("body", "")):
            target = m.group(1).strip()
            if _norm_link(target) not in known:
                broken.append({"from": f["filename"], "to": target})
    return broken


def _tokens(*parts):
    toks = set()
    for part in parts:
        if not part:
            continue
        for t in TOKEN_RE.findall(part.lower()):
            if len(t) >= 3 and t not in STOPWORDS:
                toks.add(t)
    return toks


def cluster_duplicates(files, min_shared=MIN_SHARED_TOKENS):
    # A cluster requires a COMMON set of >= min_shared tokens shared by ALL members,
    # not just pairwise-with-seed overlap. The running `common` intersection shrinks as
    # members join and each candidate must keep it >= min_shared. This prevents
    # degenerate mega-clusters with no common thread (shared_tokens is never empty).
    sigs = [(f, _tokens((f.get("name") or "").replace("-", " "),
                        f.get("description") or "")) for f in files]
    clusters = []
    used = set()
    for i, (fi, ti) in enumerate(sigs):
        if i in used or len(ti) < min_shared:
            continue
        members = [fi["filename"]]
        group = [i]
        common = set(ti)
        for j in range(i + 1, len(sigs)):
            if j in used:
                continue
            fj, tj = sigs[j]
            if fi.get("type") != fj.get("type"):
                continue
            merged = common & tj
            if len(merged) >= min_shared:
                members.append(fj["filename"])
                group.append(j)
                common = merged
        if len(members) > 1:
            used.update(group)
            clusters.append({"members": members,
                             "shared_tokens": sorted(common),
                             "type": fi.get("type")})
    return clusters


def _majority(items):
    return Counter(items).most_common(1)[0][0] if items else None


def analyze(memory_dir):
    memory_dir = Path(memory_dir)
    index_path = memory_dir / INDEX_FILE
    index_text = (index_path.read_text(encoding="utf-8", errors="replace")
                  if index_path.exists() else "")
    index = parse_index(index_text)
    files = inventory_files(memory_dir)
    recon = reconcile(index, files)
    public_files = [{k: v for k, v in f.items() if k != "body"} for f in files]
    return {
        "memory_dir": str(memory_dir),
        "index_present": index_path.exists(),
        "index": {k: index[k] for k in
                  ("lines", "bytes", "over_lines", "over_bytes", "long_entries")},
        "limits": {"line_limit": INDEX_LINE_LIMIT, "byte_limit": INDEX_BYTE_LIMIT,
                   "long_entry_chars": LONG_ENTRY_CHARS,
                   "long_entry_bytes": LONG_ENTRY_BYTES},
        "file_count": len(files),
        "files": public_files,
        "orphans": recon["orphans"],
        "unindexed": recon["unindexed"],
        "broken_links": find_broken_links(files),
        "inbound_links": build_inbound_links(files),
        "dup_clusters": cluster_duplicates(files),
        "stale_files": [f["filename"] for f in files if f["stale_markers"]],
        "store_convention": {
            "type_style": _majority([f["schema_variant"] for f in files
                                     if f["schema_variant"] != "none"]),
            "name_style": _majority([f["name_style"] for f in files if f["name_style"]]),
        },
    }


def main(argv=None):
    # Emit UTF-8 regardless of the platform's default stdout encoding (Windows
    # cp1252 cannot encode arrows / em-dashes / CJK that appear in real memory content).
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser(
        description="Analyze a Claude Code memory store (read-only; no mutations).")
    ap.add_argument("--memory-dir", help="Path to the memory/ dir; auto-resolved if omitted.")
    ap.add_argument("--json", action="store_true", help="Emit the full report as JSON to stdout.")
    args = ap.parse_args(argv)
    report = analyze(resolve_memory_dir(args.memory_dir))
    if args.json:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        idx = report["index"]
        print(f"memory_dir: {report['memory_dir']}", file=sys.stderr)
        print(f"files: {report['file_count']}", file=sys.stderr)
        print(f"index: {idx['lines']} lines / {idx['bytes']} bytes "
              f"(over_lines={idx['over_lines']} over_bytes={idx['over_bytes']})", file=sys.stderr)
        print(f"long_entries={len(idx['long_entries'])} orphans={len(report['orphans'])} "
              f"unindexed={len(report['unindexed'])} broken_links={len(report['broken_links'])} "
              f"dup_clusters={len(report['dup_clusters'])} stale={len(report['stale_files'])}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
