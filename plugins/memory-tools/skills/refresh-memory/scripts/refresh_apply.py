"""Deterministic, manifest-driven apply for /memory-tools:refresh-memory.

Stdlib only. Reuses lib/memory_core for IO, safe-name, archive, index, inbound primitives.
Actions: correct (exact unique edit), annotate (UNVERIFIED banner), retire (archive).
Validate-all-then-mutate; --dry-run; JSON summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import memory_core as mc  # noqa: E402

BANNER_PREFIX = "> UNVERIFIED"


def _validate(memory_dir, manifest):
    mc._require(isinstance(manifest, dict), "manifest must be a JSON object")
    mc._require(isinstance(manifest.get("date", ""), str), "date must be a string")
    memory_dir = Path(memory_dir)
    actual = {p.name for p in memory_dir.iterdir() if p.is_file()}
    idx_lower = mc.INDEX_FILE.lower()
    seen = set()
    for kind in ("correct", "annotate", "retire"):
        items = manifest.get(kind, [])
        mc._require(isinstance(items, list), f"{kind} must be a list")
        for it in items:
            mc._require(isinstance(it, dict), f"each {kind} entry must be an object")
            fn = mc._safe_name(it.get("file"))
            mc._require(fn.lower() != idx_lower, "cannot target the index file")
            mc._require(fn in actual, f"{kind} target not found: {fn}")
            if kind == "correct":
                mc._require(isinstance(it.get("old"), str) and it["old"], "correct.old must be non-empty")
                mc._require(isinstance(it.get("new"), str), "correct.new must be a string")
                text = mc.read_text(memory_dir / fn)
                mc._require(text.count(it["old"]) == 1,
                            f"correct.old must match exactly once in {fn} "
                            f"(found {text.count(it['old'])})")
            elif kind == "annotate":
                mc._require(isinstance(it.get("note"), str) and it["note"], "annotate.note must be non-empty")
            else:
                mc._require(isinstance(it.get("reason"), str) and it["reason"], "retire.reason must be non-empty")
            # (kind, fn) key allows multiple annotate notes on one file but
            # prevents duplicate correct/retire entries for the same file.
            mc._require((kind, fn) not in seen or kind == "annotate",
                        f"{fn} targeted twice by {kind}")
            seen.add((kind, fn))

    # Forbid retiring a file that is also corrected/annotated this run: retire archives then
    # deletes, so an edit would be archived-then-lost and the live file removed. (correct +
    # annotate on the same file is fine — fix a fact and flag it.)
    edit_files = ({c["file"] for c in manifest.get("correct", [])}
                  | {a["file"] for a in manifest.get("annotate", [])})
    retire_files = {r["file"] for r in manifest.get("retire", [])}
    overlap = retire_files & edit_files
    mc._require(not overlap, "file(s) targeted by both retire and correct/annotate: %s" % sorted(overlap))


def apply_plan(memory_dir, manifest, dry_run=False):
    memory_dir = Path(memory_dir)
    _validate(memory_dir, manifest)
    summary = {"dry_run": dry_run, "corrected": [], "annotated": [], "retired": [], "inbound_fixed": []}
    if dry_run or not any(manifest.get(k) for k in ("correct", "annotate", "retire")):
        summary["corrected"] = [c["file"] for c in manifest.get("correct", [])]
        summary["annotated"] = [a["file"] for a in manifest.get("annotate", [])]
        summary["retired"] = [r["file"] for r in manifest.get("retire", [])]
        return summary
    for c in manifest.get("correct", []):
        p = memory_dir / c["file"]
        text = mc.read_text(p)
        mc.write_text(p, text.replace(c["old"], c["new"], 1))
        summary["corrected"].append(c["file"])
    for a in manifest.get("annotate", []):
        p = memory_dir / a["file"]
        text = mc.read_text(p)
        banner = "%s %s — %s" % (BANNER_PREFIX, manifest.get("date", ""), a["note"])
        if banner in text:
            continue                                     # idempotent
        nl = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines(keepends=True)
        # insert after the closing '---' of frontmatter, else at top
        insert_at = 0
        if lines and lines[0].lstrip("﻿").startswith("---"):
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    insert_at = i + 1
                    break
        lines.insert(insert_at, banner + nl)
        mc.write_text(p, "".join(lines))
        summary["annotated"].append(a["file"])
    retire = manifest.get("retire", [])
    if retire:
        archive = memory_dir.parent / "memory-archive"
        mc._require(archive.resolve() != memory_dir.resolve(), "memory-archive resolves to memory/")
        gone, readme = {}, []
        survivor_norms = set()
        retire_names = {r["file"] for r in retire}
        for p in memory_dir.glob("*.md"):
            if p.name == mc.INDEX_FILE or p.name in retire_names:
                continue
            survivor_norms |= mc._file_norms(p.name, mc.read_text(p))
        for r in retire:
            fn = r["file"]
            raw = mc.read_bytes(memory_dir / fn)
            gone[fn] = {"action": "retire", "norms": mc._file_norms(fn, raw.decode("utf-8", "replace"))}
            tomb = "> RETIRED %s — %s\n\n" % (manifest.get("date", ""), r["reason"])
            stored = mc.archive_file(archive, fn, tomb, raw, memory_dir / fn)
            (memory_dir / fn).unlink()
            readme.append("- `%s` — retired %s" % (stored, manifest.get("date", "")))
            summary["retired"].append(fn)
        summary["inbound_fixed"] = mc.fix_inbound_links(memory_dir, gone, survivor_norms, skip_files=set())
        mc.rewrite_index(memory_dir / mc.INDEX_FILE, drop=set(retire_names))
        readme_path = archive / "README.md"
        prior = mc.read_text(readme_path) if readme_path.exists() \
            else "# Memory Archive\n\nRetired/refreshed entries (recoverable).\n"
        mc.write_text(readme_path, prior.rstrip("\n") + "\n\n" + "\n".join(readme) + "\n")
    return summary


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        if hasattr(st, "reconfigure"):
            try:
                st.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser(
        description="Apply a /memory-tools:refresh-memory plan manifest deterministically.")
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
