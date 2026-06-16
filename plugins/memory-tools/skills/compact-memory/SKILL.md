---
name: compact-memory
description: Consolidate Claude Code's file-based memory store — the memory analog of /compact. Deduplicate and merge overlapping entries, retire obsolete ones to an archive (never delete), and shrink the MEMORY.md index back under its size budget. Use when memory is bloated, the index is over its limit, or entries are stale or duplicated.
argument-hint: "[be aggressive | be conservative | index only | keep <topic>]"
disable-model-invocation: true
allowed-tools: Read, Edit, Write, Glob, Grep, Bash
---

# Compact Memory

You are consolidating this project's built-in memory store. **The scripts do the
deterministic work — measuring (Phase 1) and applying (Phase 4); you judge (Phases 2–3).**
Master rule: **maximize recall first, then precision** — bias to keep. Be lossy in the
*active* store, never on disk: retire by archiving, never by deleting.

Optional steering from the user (may be empty): **$ARGUMENTS**
- `be aggressive` → also merge near-duplicates and retire stale-by-date/unreferenced entries.
- `be conservative` (default) → only obvious duplicates + explicitly-SUPERSEDED entries.
- `index only` → only shrink the index; do not retire or merge files.
- `keep <topic>` → never retire entries matching that topic.

## Safety rules
This skill performs destructive file operations. The Phase-4 mutations (archiving files,
deleting the originals, rewriting the index, fixing inbound links) are executed in one pass
by `apply.py`, which validates the WHOLE plan before touching anything, archives each
original losslessly and re-reads it byte-for-byte before deleting, and edits the index
surgically (line-by-line, EOL-preserving). The rules below govern YOUR actions — the
read/judge phases and the hand-run Phase-0 snapshot:
- **Never mutate before the Phase 3 gate.** Phases 0–2 only read, analyze, and snapshot; the
  destructive apply (Phase 4) runs only after the user approves the plan.
- **No wildcards in the hand-run snapshot/prune (Phase 0).** Every copy/delete there targets
  an exact, single, fully-resolved path — never `rm -rf *`, `Remove-Item *`, a bare or empty
  path, or `-Recurse -Force` on an unresolved target. If a path variable could be empty,
  don't run it. **Never hand-delete from `memory/`** — Phase-4 deletes are the script's job.
- **Don't bypass the script.** If `apply.py` exits non-zero, it failed BEFORE mutating
  (validation runs first); read its `apply:` message, fix the manifest, and re-run. Never
  fall back to hand-editing `memory/` or passing `--force`.
- **One operation per command** in any hand-run step — never combine a copy/create with a
  delete. The Phase-0 snapshot is the whole-store backstop if anything fails mid-apply.

## Phase 0 — Locate & snapshot
1. Determine the memory dir. It is stated in the session's system context ("Memory"
   section); if unsure, run the analyzer without `--memory-dir` to auto-resolve.
2. Snapshot before any change: as its OWN command (never combined with a delete), copy the
   whole `memory/` dir to `<memory_parent>/memory-archive/_snapshots/<UTC-timestamp>/`.
   (`memory-archive/` is a SIBLING of `memory/`, never a subdir of it.)
3. Prune snapshots in a SEPARATE step, and ONLY if more than 3 snapshot dirs exist: list
   them, then delete the specific oldest dirs **by full explicit path, one at a time**. If
   there are ≤3, skip pruning entirely — never delete with a wildcard/`*`, an empty path, or
   `-Recurse -Force` on an unresolved target (that exact pattern gets blocked, or worse hits
   the wrong path). The snapshot/prune touches only the archive, never the active `memory/`
   store; if the user declines at Phase 3, the store is left untouched.

## Phase 1 — Analyze (deterministic)
Run the analyzer and read its JSON:
```bash
python "${CLAUDE_SKILL_DIR}/scripts/analyze_memory.py" --memory-dir "<memory_dir>" --json
```
This returns measured facts: index lines/bytes + over-budget flags, long index entries,
orphan pointers, unindexed files, broken `[[wikilinks]]`, stale-marked files, and
duplicate-candidate clusters. **Trust these numbers; do not estimate sizes yourself.**

## Phase 2 — Judge (recall-first)
For each flagged item, decide: merge / retire / shorten / fix-link / keep. Apply
`references/consolidation-principles.md` (recency-wins conflicts; durable-AND-actionable
gate; dedupe-to-canonical; clear regenerable noise first; preserve UNVERIFIED tags;
structured—not prose—consolidation). Default conservative; widen only if `$ARGUMENTS` says
so. Honor any `keep <topic>` directive as a hard constraint. `dup_clusters` are *candidates*
— confirm a real overlap before merging. **Before retiring a file, check `inbound_links[file]`**
(survivors that still `[[link]]` to it): if non-empty, either keep it, or retire it AND fix
those referrers in Phase 4 — never leave a dangling link.

## Phase 3 — Preview & approve (GATE)
Present ONE consolidated plan and the measured before→after index size (lines + bytes):
- archive: <files + one-line reason each; for any file with `inbound_links`, add "(referenced by N: …) — those links will be unlinked">
- merge: <cluster → canonical file>
- shorten: <index lines whose detail moves into the linked topic file>
- fix: <orphan pointers / broken links>
**Do not write anything until the user approves.** A single approval covers the whole plan.

## Phase 4 — Apply (scripted, deterministic)
The destructive work runs in ONE pass via `apply.py` — NOT by hand. This is what keeps apply
fast (one call, not dozens of edits) and safe (it validates the whole plan first, archives
losslessly, verifies each copy byte-for-byte before deleting, edits the index EOL-preserving,
and repoints/unlinks inbound links for you). Your job is to turn the approved plan into
a manifest, then run the script.

1. **Author the manifest.** Write the approved plan as a JSON file (full schema, rules, and a
   worked example in `references/apply-manifest-schema.md`). Save it as an audit record at
   `<memory_parent>/memory-archive/_manifests/<UTC-timestamp>.json`. Shape:
   ```json
   {
     "date": "<UTC-date>",
     "retire":  [{"file": "x.md", "reason": "why"}],
     "merge":   [{"canonical_file": "m.md", "canonical_body": "<full md incl. frontmatter>",
                  "canonical_index_line": "- [m.md](m.md) — hook", "absorbed": ["a.md","b.md"]}],
     "shorten": [{"file": "y.md", "new_index_line": "- [y.md](y.md) — short hook"}]
   }
   ```
   - For each `merge`, YOU author `canonical_body` — the consolidated topic file, preserving
     **the chosen source file's own** frontmatter variant (its `schema_variant` / `name_style`
     in the analyzer report), NOT the store-wide majority (real stores are mixed — see
     `references/frontmatter-variants.md`; don't churn schema). `canonical_file` must be a NEW
     filename. Each `*_index_line` must be a bullet that links to its own file, < 200 chars.
   - For `retire` / `shorten` / each `absorbed`, `file` must EXACTLY match a current filename
     in `memory/` (the script rejects aliases — trailing space/dot, case, path separators).
   - Omit any section you aren't using. An empty manifest is a safe no-op.

2. **Dry-run** to validate the manifest and preview intent (writes nothing):
   ```bash
   python "${CLAUDE_SKILL_DIR}/scripts/apply.py" --memory-dir "<memory_dir>" --manifest "<manifest>" --dry-run
   ```
   Confirm the reported `retired` / `absorbed` / `merged` / `shortened` match the approved plan.
   (`inbound_fixed` is always `[]` on a dry-run — inbound links are only rewritten on the real apply.)

3. **Apply:**
   ```bash
   python "${CLAUDE_SKILL_DIR}/scripts/apply.py" --memory-dir "<memory_dir>" --manifest "<manifest>"
   ```
   The script writes each canonical file; archives every retired + absorbed file to
   `memory-archive/<file>` (tombstone + original raw bytes), verifies the copy, then deletes
   the original; rewrites `MEMORY.md` (drops gone pointers, places each merged line at the index
   slot of the first of its absorbed files — in listed order — that is indexed, else appends;
   applies shortens) preserving recency order and line endings; repoints inbound `[[absorbed]]` → `[[canonical]]` and unlinks inbound `[[retired]]`
   → `retired (archived)` (so Phase 5 finds `broken_links == 0`); appends an audit block to
   `memory-archive/README.md`. It prints a JSON summary — keep it for Phase 5.

If the script exits non-zero it failed before mutating; read the `apply:` message, fix the
manifest, and re-run (see the Safety rules — don't hand-edit `memory/`).

## Phase 5 — Verify (no silent loss)
Re-run the analyzer (`--json`). **From its output** confirm: index now under BOTH limits;
no `MEMORY.md` pointer dangles (`orphans == []`); every inbound reference was repointed or
unlinked (`broken_links == []`); no surviving file lost its frontmatter. Cross-check the
script's summary counts against your approved plan. **Separately** — the analyzer only scans
`memory/`, so it cannot see the archive — Glob `memory-archive/` and confirm every file the
summary listed under `retired` / `absorbed` is present there with a tombstone. Report measured
before→after. If any assertion fails, stop and surface it — do not claim success.

## Track progress
Maintain a task checklist across the six phases (locate → analyze → judge → preview →
apply → verify) so progress is visible.
