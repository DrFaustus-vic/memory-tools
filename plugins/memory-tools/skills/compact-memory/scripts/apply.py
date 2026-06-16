"""Deterministic, manifest-driven apply for the /compact-memory skill's Phase 4.

Stdlib only. Reuses analyze_memory for link / frontmatter helpers. Given a model-approved
plan (a JSON manifest) it executes the whole apply in ONE pass: write merged canonical
files; archive retired + absorbed files (tombstone) then delete the originals; fix inbound
[[wikilinks]] in survivors (retired -> "name (archived)"; absorbed -> "[[canonical_stem]]");
rewrite MEMORY.md (drop gone pointers, insert merged lines, shorten lines); append a
memory-archive/README.md audit block.

Safety:
  * Existing-file targets (retire/absorbed/shorten) must EXACTLY match a real file in
    memory/ (membership in the live directory listing) — this defeats filename-aliasing
    (trailing space/dot, case folding, NTFS ADS) that `.exists()` would silently resolve.
  * _safe_name additionally forbids path separators, "..", absolute paths, trailing
    space/dot, control chars / ":", and reserved device names — covering NEW canonical
    filenames (which by definition aren't in the listing).
  * Validate-all-then-mutate — the ENTIRE manifest (types, keys, existence, collisions,
    index-line targets) is checked before any write/delete, and on the --dry-run path too.
  * Verify-before-delete — each archive copy is read back and confirmed byte-for-byte equal
    before the original is unlinked. Archives store the original RAW bytes (lossless).
  * EOL-preserving / surgical — the index is edited line-by-line via splitlines(keepends),
    so unchanged lines keep their exact bytes and a mixed-EOL file is never re-normalized.
  * Partial-failure recovery still relies on the skill's Phase-0 snapshot (this script does
    NOT create it). Validate-all eliminates the manifest-error class of partial applies; an
    I/O error mid-apply falls back to that snapshot.

Manifest schema:
{
  "date": "2026-06-15",
  "retire": [{"file": "x.md", "reason": "..."}],
  "merge":  [{"canonical_file": "m.md", "canonical_body": "...full md...",
              "canonical_index_line": "- [m.md](m.md) - hook", "absorbed": ["a.md","b.md"]}],
  "shorten":[{"file": "y.md", "new_index_line": "- [y.md](y.md) - short hook"}]
}
canonical_file must be a NEW filename (not an existing entry). Each *_index_line must link
to its own file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_memory as am  # noqa: E402

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


def _line_target(line):
    # Mirror analyze_memory.parse_index exactly: a bullet line containing a markdown link;
    # target = the link's basename. Using the SAME matcher as the analyzer means apply drops
    # precisely what the analyzer counts as a pointer — so no dangling/orphan pointer is left.
    if not line or not line.lstrip().startswith(("-", "*")):
        return None
    m = am.INDEX_LINK_RE.search(line)
    return m.group(2).split("/")[-1] if m else None


def _file_norms(filename, body):
    norms = {am._norm_link(Path(filename).stem)}
    name = am.parse_frontmatter(body).get("name")
    if name:
        norms.add(am._norm_link(name))
    return norms


def _require(cond, msg):
    if not cond:
        raise SystemExit("apply: " + msg)


def _safe_name(name):
    """A manifest filename must be a bare, unambiguous filename — no path separators / '..'
    / absolute, no trailing space or dot (Windows strips these -> aliasing), no control
    chars or ':' (ADS / drive), and not a reserved device name."""
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise SystemExit("apply: unsafe filename: %r" % (name,))
    if name != Path(name).name:
        raise SystemExit("apply: filename must be bare (no path separators): %r" % (name,))
    if name != name.rstrip(" ."):
        raise SystemExit("apply: filename has a trailing space or dot: %r" % (name,))
    if ":" in name or any(ord(c) < 0x20 for c in name):
        raise SystemExit("apply: filename has an illegal character: %r" % (name,))
    if name.split(".")[0].lower() in _RESERVED:
        raise SystemExit("apply: reserved device name: %r" % (name,))
    return name


def _validate(memory_dir, manifest):
    """Validate the ENTIRE manifest before any mutation (and on the dry-run path)."""
    memory_dir = Path(memory_dir)
    _require(isinstance(manifest, dict), "manifest must be a JSON object")
    _require(isinstance(manifest.get("date", ""), str), "date must be a string")
    retire = manifest.get("retire", [])
    merges = manifest.get("merge", [])
    shorten = manifest.get("shorten", [])
    _require(all(isinstance(x, list) for x in (retire, merges, shorten)),
             "retire/merge/shorten must be lists")

    actual = {p.name for p in memory_dir.iterdir() if p.is_file()}
    actual_lower = {n.lower() for n in actual}
    idx_lower = am.INDEX_FILE.lower()

    def existing(fn, kind):
        _safe_name(fn)
        _require(fn.lower() != idx_lower, "cannot target the index file: %s" % fn)
        _require(fn in actual, "%s target not found (must exactly match a file in memory/): %s" % (kind, fn))
        return fn

    retired, absorbed, canon, sh_files = [], [], [], []
    for r in retire:
        _require(isinstance(r, dict), "each retire entry must be an object")
        _require(isinstance(r.get("reason", ""), str), "retire.reason must be a string")
        retired.append(existing(r.get("file"), "retire"))
    for m in merges:
        _require(isinstance(m, dict), "each merge entry must be an object")
        cf = _safe_name(m.get("canonical_file"))
        _require(cf.lower() != idx_lower, "canonical_file cannot be the index file")
        _require(cf.lower() not in actual_lower, "canonical_file %s already exists; use a NEW filename" % cf)
        _require(isinstance(m.get("canonical_body"), str) and m["canonical_body"].strip(),
                 "merge.canonical_body must be a non-empty string")
        cil = m.get("canonical_index_line")
        _require(isinstance(cil, str) and cil.strip(), "merge.canonical_index_line must be a non-empty string")
        _require(_line_target(cil) == cf, "merge.canonical_index_line must link to %s" % cf)
        ab = m.get("absorbed")
        _require(isinstance(ab, list) and ab, "merge.absorbed must be a non-empty list")
        for a in ab:
            absorbed.append(existing(a, "absorbed"))
        canon.append(cf)
    for s in shorten:
        _require(isinstance(s, dict), "each shorten entry must be an object")
        fn = existing(s.get("file"), "shorten")
        nil = s.get("new_index_line")
        _require(isinstance(nil, str) and nil.strip(), "shorten.new_index_line must be a non-empty string")
        _require(_line_target(nil) == fn, "shorten.new_index_line must link to %s" % fn)
        sh_files.append(fn)

    gone = retired + absorbed
    _require(len(gone) == len(set(gone)), "a file is listed more than once across retire/absorbed")
    _require(len(canon) == len(set(canon)), "duplicate canonical_file across merges")
    _require(len({c.lower() for c in canon}) == len(canon),
             "canonical_file names collide case-insensitively (same file on a case-insensitive FS)")
    _require(len(sh_files) == len(set(sh_files)), "duplicate shorten entry for a file")
    _require(not (set(sh_files) & set(gone)), "a file is both shortened and retired/absorbed")


def apply_plan(memory_dir, manifest, dry_run=False):
    memory_dir = Path(memory_dir)
    _validate(memory_dir, manifest)

    retire = manifest.get("retire", [])
    merges = manifest.get("merge", [])
    shorten = manifest.get("shorten", [])
    date = manifest.get("date", "")
    summary = {"dry_run": dry_run, "merged": [], "retired": [], "absorbed": [],
               "shortened": [], "inbound_fixed": []}

    if dry_run:
        summary["retired"] = [r["file"] for r in retire]
        summary["absorbed"] = [a for m in merges for a in m["absorbed"]]
        summary["merged"] = [m["canonical_file"] for m in merges]
        summary["shortened"] = [s["file"] for s in shorten]
        return summary

    if not (retire or merges or shorten):
        return summary  # nothing to do — no side effects

    # Read raw bytes (for lossless archive) + decoded text (for inbound norms) up front.
    gone = {}
    for r in retire:
        fn = r["file"]
        raw = read_bytes(memory_dir / fn)
        gone[fn] = {"action": "retire", "reason": r.get("reason", ""), "raw": raw,
                    "norms": _file_norms(fn, raw.decode("utf-8", "replace"))}
    for m in merges:
        cstem = Path(m["canonical_file"]).stem
        for a in m["absorbed"]:
            raw = read_bytes(memory_dir / a)
            gone[a] = {"action": "absorb", "canon_stem": cstem, "raw": raw,
                       "norms": _file_norms(a, raw.decode("utf-8", "replace"))}

    archive = memory_dir.parent / "memory-archive"
    archive.mkdir(parents=True, exist_ok=True)
    _require(archive.resolve() != memory_dir.resolve(), "memory-archive/ resolves to memory/ (refusing)")

    # 1. Write merged canonical files (validated to be NEW names).
    for m in merges:
        write_text(memory_dir / m["canonical_file"], m["canonical_body"])
        summary["merged"].append(m["canonical_file"])

    # 2. Archive each gone file (tombstone + RAW original bytes), VERIFY, THEN delete.
    readme_entries = []
    for fn, info in gone.items():
        dst = archive / fn
        if dst.exists():   # never overwrite an older archived copy of a same-named file
            stem, suf, i = Path(fn).stem, Path(fn).suffix, 1
            while (archive / ("%s.%d%s" % (stem, i, suf))).exists():
                i += 1
            dst = archive / ("%s.%d%s" % (stem, i, suf))
        _require(not dst.is_symlink(), "archive target is a symlink: %s (refusing)" % dst.name)
        orig_note = "" if dst.name == fn else " (orig %s)" % fn
        if info["action"] == "retire":
            tomb = "> RETIRED %s — %s\n\n" % (date, info["reason"])
            readme_entries.append("- `%s` — retired %s%s" % (dst.name, date, orig_note))
            summary["retired"].append(fn)
        else:
            tomb = "> MERGED %s into %s. Original preserved below.\n\n" % (date, info["canon_stem"])
            readme_entries.append("- `%s` — merged into %s %s%s" % (dst.name, info["canon_stem"], date, orig_note))
            summary["absorbed"].append(fn)
        content = tomb.encode("utf-8") + info["raw"]
        write_bytes(dst, content)
        _require(read_bytes(dst) == content and dst.resolve() != (memory_dir / fn).resolve(),
                 "archive copy invalid for %s; original NOT deleted" % fn)
        (memory_dir / fn).unlink()

    # 3. Fix inbound [[wikilinks]] in surviving files. Two passes over memory/: first gather
    #    the live-link norm set (which INCLUDES the just-written canonical files), then rewrite
    #    each survivor's body (skipping the canonical files, whose author-written bodies stay).
    canon_files = {m["canonical_file"] for m in merges}
    # A link that still resolves to a LIVE file must never be rewritten, even if a gone file
    # normalizes to the same key (hyphen/underscore/case collision, OR a shared frontmatter
    # name). Resolve against stem AND frontmatter name — the SAME keys analyze_memory uses to
    # resolve links — so this survivor set matches the analyzer's link model exactly.
    survivor_norms = set()
    for p in memory_dir.glob("*.md"):
        if p.name == am.INDEX_FILE or p.name in gone:
            continue
        survivor_norms |= _file_norms(p.name, read_text(p))

    def _repl(mo):
        n = am._norm_link(mo.group(1))
        if n in survivor_norms:
            return mo.group(0)
        for info in gone.values():
            if n in info["norms"]:
                return ("%s (archived)" % mo.group(1)) if info["action"] == "retire" \
                    else ("[[%s]]" % info["canon_stem"])
        return mo.group(0)

    for p in sorted(memory_dir.glob("*.md")):
        if p.name == am.INDEX_FILE or p.name in canon_files:
            continue
        t = read_text(p)
        nt = am.WIKILINK_RE.sub(_repl, t)
        if nt != t:
            write_text(p, nt)
            summary["inbound_fixed"].append(p.name)

    # 4. Rewrite MEMORY.md — surgical, per-line, EOL-preserving.
    index_path = memory_dir / am.INDEX_FILE
    if index_path.exists():
        raw = read_text(index_path)
        lines = raw.splitlines(keepends=True)
        default_nl = "\r\n" if "\r\n" in raw else "\n"
        present = [_line_target(ln) for ln in lines]
        # place each merge's canonical line at the EARLIEST absorbed present in the index; else append
        merge_anchor, appended = {}, []
        for m in merges:
            anchor = next((a for a in m["absorbed"] if a in present), None)
            if anchor is not None:
                merge_anchor[anchor] = m["canonical_index_line"]
            else:
                appended.append(m["canonical_index_line"])
        shorten_map = {s["file"]: s["new_index_line"] for s in shorten}
        out, emitted = [], set()
        for ln in lines:
            tgt = _line_target(ln)
            term = ln[len(ln.rstrip("\r\n")):] or default_nl
            if tgt in merge_anchor:
                if tgt not in emitted:           # emit each canonical line once; a duplicate
                    out.append(merge_anchor[tgt] + term)   # pointer to the same absorbed file
                    emitted.add(tgt)             # is dropped (its file is gone) — no dup line
            elif tgt in gone:
                continue
            elif tgt in shorten_map:
                if tgt not in emitted:           # shorten each pointer once; a duplicate
                    out.append(shorten_map[tgt] + term)   # pointer to the same live file is
                    summary["shortened"].append(tgt)      # dropped (one pointer per file)
                    emitted.add(tgt)
            else:
                out.append(ln)
        if appended and out and not out[-1].endswith(("\n", "\r")):
            out[-1] = out[-1] + default_nl   # terminate the last retained line before appending
        for cl in appended:
            out.append(cl + default_nl)
        write_text(index_path, "".join(out))

    # 5. Append the archive README audit block.
    readme = archive / "README.md"
    prior = read_text(readme) if readme.exists() \
        else "# Memory Archive\n\nRetired/merged memory entries (recoverable). Each file carries a tombstone.\n"
    write_text(readme, prior.rstrip("\n") + "\n\n" + "\n".join(readme_entries) + "\n")

    return summary


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        if hasattr(st, "reconfigure"):
            try:
                st.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser(
        description="Apply a /compact-memory plan manifest deterministically (Phase 4).")
    ap.add_argument("--memory-dir", required=True, help="Path to the memory/ dir.")
    ap.add_argument("--manifest", required=True, help="Path to the approved plan JSON.")
    ap.add_argument("--dry-run", action="store_true", help="Validate + report the plan; write nothing.")
    args = ap.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_bytes().decode("utf-8"))
    summary = apply_plan(args.memory_dir, manifest, dry_run=args.dry_run)
    json.dump(summary, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
