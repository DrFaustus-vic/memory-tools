"""Deterministic, read-only measurement of a Claude Code file-based memory store.

Stdlib only. Emits a JSON report; performs NO mutations. Consumed by the
/memory-tools:compact-memory skill. The script measures; the model judges.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

INDEX_FILE = "MEMORY.md"
INDEX_LINE_LIMIT = 200          # harness loads first 200 lines of MEMORY.md
INDEX_BYTE_LIMIT = 25_000       # ...or first ~25KB, whichever comes first
LONG_ENTRY_CHARS = 200          # index lines longer than this are flagged
LONG_ENTRY_BYTES = 300          # index lines with more UTF-8 bytes than this are flagged
STALE_MARKERS = ("SUPERSEDED", "DEPRECATED", "OBSOLETE")
MIN_SHARED_TOKENS = 2
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "with", "via", "not", "use", "when", "md", "new", "old",
}

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INDEX_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TOKEN_RE = re.compile(r"[a-z0-9]+")


def parse_frontmatter(text):
    result = {"name": None, "description": None, "type": None,
              "schema_variant": "none", "name_style": None, "warnings": []}
    # FIX M3: strip a leading UTF-8 BOM so "---" detection works
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith("---"):
        result["warnings"].append("no_frontmatter")
        return result
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        result["warnings"].append("unterminated_frontmatter")
        return result
    in_metadata = False
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        indented = raw[:1].isspace()
        stripped = raw.strip()
        if stripped[:-1].strip() == "metadata" and stripped.endswith(":"):
            in_metadata = True
            continue
        if ":" not in stripped:
            result["warnings"].append("unparsed_line:" + stripped[:40])
            continue
        key, _, val = stripped.partition(":")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if indented and in_metadata:
            # FIX M2: capture name and description from nested block too
            if key == "type" and result["type"] is None:
                result["type"] = val
                result["schema_variant"] = "nested"
            elif key == "name" and result["name"] is None:
                result["name"] = val
            elif key == "description" and result["description"] is None:
                result["description"] = val
            continue
        in_metadata = False
        if key == "name":
            result["name"] = val
        elif key == "description":
            result["description"] = val
        elif key == "type":
            result["type"] = val
            result["schema_variant"] = "flat"
    if result["name"]:
        result["name_style"] = "kebab" if KEBAB_RE.match(result["name"]) else "human"
    if result["type"] is None:
        result["warnings"].append("no_type")
    return result


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


def inventory_files(memory_dir):
    memory_dir = Path(memory_dir)
    files = []
    for p in sorted(memory_dir.glob("*.md")):
        if p.name == INDEX_FILE:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        stale = sorted({mk for mk in STALE_MARKERS if mk in text.upper()})
        files.append({
            "filename": p.name,
            "name": fm["name"] or p.stem,
            "path": str(p),
            "bytes": len(text.encode("utf-8")),
            "type": fm["type"],
            "schema_variant": fm["schema_variant"],
            "name_style": fm["name_style"],
            "description": fm["description"],
            "stale_markers": stale,
            "warnings": fm["warnings"],
            "body": text,
        })
    return files


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


def _norm_link(s):
    """Normalize a wikilink target or filename stem for comparison:
    lowercase, hyphens and underscores are equivalent."""
    return s.strip().lower().replace("-", "_")


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


def build_inbound_links(files):
    # Map each file to the survivors that reference it via [[wikilinks]] (resolved +
    # normalized). Lets the skill see which retire-candidates are still linked, so a
    # retire can unlink its referrers instead of leaving a dangling pointer.
    name_to_file = {}
    for f in files:
        if f["name"]:
            name_to_file[_norm_link(f["name"])] = f["filename"]
        name_to_file[_norm_link(Path(f["filename"]).stem)] = f["filename"]
    inbound = {}
    for f in files:
        for m in WIKILINK_RE.finditer(f.get("body", "")):
            target = name_to_file.get(_norm_link(m.group(1).strip()))
            if target and target != f["filename"]:
                inbound.setdefault(target, set()).add(f["filename"])
    return {k: sorted(v) for k, v in inbound.items()}


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


def _has_memory(p):
    return (p / INDEX_FILE).exists() or any(p.glob("*.md"))


def resolve_memory_dir(arg=None):
    """Resolve the active memory dir. Priority: explicit arg > settings.json
    autoMemoryDirectory > cwd-slug heuristic. The skill normally passes --memory-dir
    (it knows the path from the session); auto-resolution is a fallback."""
    if arg:
        p = Path(arg).expanduser()
        if _has_memory(p):
            return p
        raise SystemExit(f"No memory store at --memory-dir: {p}")
    settings = Path.home() / ".claude" / "settings.json"
    if settings.exists():
        try:
            amd = json.loads(settings.read_text(encoding="utf-8")).get("autoMemoryDirectory")
            if amd:
                p = Path(os.path.expanduser(amd))
                if p.exists() and _has_memory(p):
                    return p
        except (json.JSONDecodeError, OSError):
            pass
    slug = re.sub(r"[:\\/ ]", "-", str(Path.cwd()))
    p = Path.home() / ".claude" / "projects" / slug / "memory"
    if p.exists() and _has_memory(p):
        return p
    raise SystemExit("Could not locate a memory dir; pass --memory-dir explicitly.")


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
