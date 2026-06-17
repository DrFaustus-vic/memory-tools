"""Shared primitives for the memory-tools plugin (compact-memory + refresh-memory).

Stdlib only. Read helpers, shared regexes/constants, and mutation primitives (archive,
index-rewrite, inbound-link fix) — all factored out so safety-critical code has one home.
"""
from __future__ import annotations

import json
import os
import re
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


def _norm_link(s):
    """Normalize a wikilink target or filename stem for comparison:
    lowercase, hyphens and underscores are equivalent."""
    return s.strip().lower().replace("-", "_")


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


# ---------------------------------------------------------------------------
# IO + safe-name primitives (moved verbatim from apply.py)
# ---------------------------------------------------------------------------

_RESERVED = ({"con", "prn", "aux", "nul"}
             | {"com%d" % i for i in range(1, 10)} | {"lpt%d" % i for i in range(1, 10)})


def read_bytes(p):
    return Path(p).read_bytes()


def read_text(p):
    return Path(p).read_bytes().decode("utf-8", errors="replace")


def write_text(p, s):
    Path(p).write_bytes(s.encode("utf-8"))  # bytes I/O -> no platform newline conversion


def write_bytes(p, b):
    Path(p).write_bytes(b)


def _require(cond, msg):
    if not cond:
        raise SystemExit("memory-tools: " + msg)


def _safe_name(name):
    """A manifest filename must be a bare, unambiguous filename — no path separators / '..'
    / absolute, no trailing space or dot (Windows strips these -> aliasing), no control
    chars or ':' (ADS / drive), and not a reserved device name."""
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise SystemExit("memory-tools: unsafe filename: %r" % (name,))
    if name != Path(name).name:
        raise SystemExit("memory-tools: filename must be bare (no path separators): %r" % (name,))
    if name != name.rstrip(" ."):
        raise SystemExit("memory-tools: filename has a trailing space or dot: %r" % (name,))
    if ":" in name or any(ord(c) < 0x20 for c in name):
        raise SystemExit("memory-tools: filename has an illegal character: %r" % (name,))
    if name.split(".")[0].lower() in _RESERVED:
        raise SystemExit("memory-tools: reserved device name: %r" % (name,))
    return name


def _file_norms(filename, body):
    norms = {_norm_link(Path(filename).stem)}
    name = parse_frontmatter(body).get("name")
    if name:
        norms.add(_norm_link(name))
    return norms


# ---------------------------------------------------------------------------
# Archive primitive
# ---------------------------------------------------------------------------

def archive_file(archive_dir, filename, tombstone, raw, original_path):
    """Write a tombstoned, lossless copy of `filename` (raw bytes) into archive_dir,
    collision-safe, verified byte-for-byte. Returns the stored filename. Does NOT delete
    the original (caller does that only after this returns successfully).
    `original_path` is the live path of the file being archived; the copy is rejected if
    it resolves to the same inode."""
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    dst = archive_dir / filename
    if dst.exists():
        stem, suf, i = Path(filename).stem, Path(filename).suffix, 1
        while (archive_dir / ("%s.%d%s" % (stem, i, suf))).exists():
            i += 1
        dst = archive_dir / ("%s.%d%s" % (stem, i, suf))
    _require(not dst.is_symlink(), "archive target is a symlink: %s (refusing)" % dst.name)
    content = tombstone.encode("utf-8") + raw
    write_bytes(dst, content)
    _require(read_bytes(dst) == content and dst.resolve() != Path(original_path).resolve(),
             "archive copy invalid for %s; original NOT deleted" % filename)
    return dst.name


# ---------------------------------------------------------------------------
# Index-rewrite + inbound-fix primitives
# ---------------------------------------------------------------------------

def _line_target(line):
    # Mirror analyze_memory.parse_index exactly: a bullet line containing a markdown link;
    # target = the link's basename. Using the SAME matcher as the analyzer means apply drops
    # precisely what the analyzer counts as a pointer — so no dangling/orphan pointer is left.
    if not line or not line.lstrip().startswith(("-", "*")):
        return None
    m = INDEX_LINK_RE.search(line)
    return m.group(2).split("/")[-1] if m else None


def rewrite_index(index_path, drop=None, replace=None, append=None):
    """EOL-preserving, surgical MEMORY.md rewrite. `drop`: set of target filenames whose
    pointer lines are removed. `replace`: {target_filename: new_line} (emitted once, at the
    first matching line). `append`: list of new lines for targets not already present."""
    index_path = Path(index_path)
    drop = set(drop or ())
    replace = dict(replace or {})
    append = list(append or ())
    if not index_path.exists():
        return
    raw = read_text(index_path)
    lines = raw.splitlines(keepends=True)
    default_nl = "\r\n" if "\r\n" in raw else "\n"
    out, emitted = [], set()
    for ln in lines:
        tgt = _line_target(ln)
        term = ln[len(ln.rstrip("\r\n")):] or default_nl
        if tgt in replace:
            if tgt not in emitted:
                out.append(replace[tgt] + term)
                emitted.add(tgt)
        elif tgt in drop:
            continue
        else:
            out.append(ln)
    to_append = [a for a in append if a is not None]
    if to_append and out and not out[-1].endswith(("\n", "\r")):
        out[-1] = out[-1] + default_nl
    for line in to_append:
        out.append(line + default_nl)
    write_text(index_path, "".join(out))


def fix_inbound_links(memory_dir, gone, survivor_norms, skip_files):
    """For each surviving .md (excluding skip_files and INDEX_FILE), rewrite [[wikilinks]]:
    a link whose normalized target matches a `gone` entry becomes that entry's replacement
    ('[[canon]]' for an absorb, 'name (archived)' for a retire). A link that still resolves
    to a live file (survivor_norms) is left untouched. Returns the list of edited filenames.
    `gone` is {filename: {"action": "retire"|"absorb", "norms": set, "canon_stem": str?}}."""
    edited = []
    def _repl(mo):
        n = _norm_link(mo.group(1))
        if n in survivor_norms:
            return mo.group(0)
        for info in gone.values():
            if n in info["norms"]:
                return ("%s (archived)" % mo.group(1)) if info["action"] == "retire" \
                    else ("[[%s]]" % info["canon_stem"])
        return mo.group(0)
    for p in sorted(Path(memory_dir).glob("*.md")):
        if p.name == INDEX_FILE or p.name in skip_files:
            continue
        t = read_text(p)
        nt = WIKILINK_RE.sub(_repl, t)
        if nt != t:
            write_text(p, nt)
            edited.append(p.name)
    return edited
