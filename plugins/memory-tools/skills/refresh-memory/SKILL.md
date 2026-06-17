---
name: refresh-memory
description: Verify Claude Code memory entries against ground truth — repo files, git, code, external links — and correct/annotate/retire what reality contradicts, behind a preview-and-approve gate. The memory analog of fact-checking your notes against the codebase.
argument-hint: "[--project-root <path>] [no network] [keep <topic>]"
disable-model-invocation: true
allowed-tools: Read, Edit, Write, Glob, Grep, Bash
---

# Refresh Memory

You are fact-checking this project's built-in memory store against the live codebase and
external ground truth. **The scan script does the deterministic work — extracting references
and checking them (Phase 1); you judge (Phases 2–3); the apply script executes (Phase 5).**
Master rule: **only act on verified contradictions** — if you cannot confirm a claim is
wrong from real source material you read this turn, leave it alone.

Optional steering from the user (may be empty): **$ARGUMENTS**
- `--project-root <path>` → check references against this repo root (default: cwd).
- `no network` → pass `--no-network` to skip external URL checks (URLs stay `inconclusive`).
- `keep <topic>` → never retire entries matching that topic.

## Safety rules

This skill performs destructive file operations. The Phase-5 mutations (correcting text,
inserting banners, archiving and unlinking retired files) are executed in one pass by
`refresh_apply.py`, which validates the WHOLE manifest before touching anything, archives
losslessly, and edits files EOL-preserving. The rules below govern YOUR actions — the
read/judge phases and the hand-run Phase-0 snapshot:

- **Nothing mutates before the Phase-4 gate.** Phases 0–3 only read, analyze, and propose;
  the destructive apply (Phase 5) runs only after the user approves the plan.
- **Verifiable-only.** Never flag a claim stale unless you have read the actual file, git
  history, or live source that disproves it. Feedback notes, opinions, user guidance, and
  plans are unverifiable by design — leave them untouched. Entries typed `feedback` or `user`
  stay untouched **even when `flagged`**: a `dangling`/`dead` ref inside guidance flags it for
  a glance, never for a `correct`/`retire` — the lesson can outlive the file it cites.
- **`inconclusive` ≠ wrong.** A `dead` or `inconclusive` link or an unfound symbol is
  evidence of uncertainty, not of staleness. These may become `annotate` entries at most —
  NEVER a `correct` or `retire` based on a link probe alone. Note two benign-by-design
  `dangling`/`dead` classes that are NOT staleness: a path that exists but is **gitignored**
  and referenced by shorthand (the scan's index is git-tracked-only), and an **API root** that
  returns 404 to a bare probe. Confirm against ground truth before acting on either.
- **Wrong-root abort.** If the scan returns `wrong_root_suspected: true`, STOP and tell the
  user the project root looks misaimed (don't propose a mass retire on that basis). Ask
  them to confirm the correct `--project-root` and re-run. The guard is a heuristic backstop,
  not a proof: a *near*-wrong root (a parent/sibling that shares some on-disk paths) can dilute
  the rate below threshold — so sanity-check that the root is right even when it reads `false`.
- **Don't bypass the script.** If `refresh_apply.py` exits non-zero it failed BEFORE
  mutating (validation runs first); read its `memory-tools:` message, fix the manifest, and
  re-run. Never fall back to hand-editing `memory/` or passing `--force`.
- **One operation per command** in any hand-run step — never combine a snapshot copy with a
  delete. The Phase-0 snapshot is the whole-store backstop if anything fails mid-apply.

## Phase 0 — Locate & snapshot

1. Determine the memory dir. It is stated in the session's system context ("Memory" section);
   if unsure, run the scan without `--memory-dir` and let it auto-resolve.
2. Determine the project root to check references against. Default is cwd; use
   `--project-root <path>` if the user supplied one or if the memory dir lives inside a
   different repo.
3. Snapshot before any change: as its OWN command (never combined with a delete), copy the
   whole `memory/` dir to `<memory_parent>/memory-archive/_snapshots/<UTC-timestamp>/`.
   (`memory-archive/` is a SIBLING of `memory/`, never a subdir of it; the snapshot dir is
   shared with compact-memory.)

## Phase 1 — Scan

Run the scan script and capture its JSON output:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/refresh_scan.py" \
  --memory-dir "<memory_dir>" \
  --project-root "<project_root>" \
  [--no-network] \
  --json
```

Read the full JSON. Trust the deterministic statuses — do not re-derive them yourself.
Key top-level fields:
- `summary.dangling_rate` — the fraction of the project's *path* references that are
  dangling (`dangling_paths / (dangling_paths + resolved_paths)`). Symbols, URLs, and
  sibling-memory-file resolutions are all excluded so they can't dilute it. A high value
  with `wrong_root_suspected: true` means the project root is misaimed.
- `wrong_root_suspected` — if `true`, stop here (see Safety rules).
- `entries` — per-file results; each entry has `flagged`, `needs_semantic_review`, and
  `refs` (list of `{ref, kind, status}`).

A backticked token is checked as a `path` only when it carries a real file extension and
isn't a route (`/api/...`), template/glob (`{id}.json`, `*.min.js`), or scheme-less domain;
everything else is a `symbol` (substring-matched) or ignored. A `path` resolves against the
project root (incl. gitignored-but-present files), the git-tracked tree (a shorthand or
unique bare basename in a subdir), or a sibling memory file.

Ref statuses:
- `resolved` — path exists in the repo / git tree, names a sibling memory file, or a symbol
  matched. No action needed.
- `reachable` — URL responded 2xx/3xx. No action needed.
- `dangling` — path (with a real extension) not found in the repo, the tracked tree, or the
  memory dir.
- `dead` — URL returned 404 or 410.
- `inconclusive` — symbol absent (may live in a dependency); a path into an *untracked*
  dependency/build dir (`node_modules/`, `dist/`…) or an *ambiguous* bare filename (several
  namesakes); URL error (network blip, timeout, 5xx); or network skipped (`--no-network`).

## Phase 2 — Semantic verify

For every entry where `needs_semantic_review` is `true`, AND for any entry whose `refs`
contain a `dangling` or `dead` status, READ the actual source that the claim is about:
- For a `dangling` path ref: check whether the file was renamed or deleted — look in git log
  if this is a git repo (`git log --diff-filter=D -- <path>` / `git log --follow <path>`).
- For a `dead` URL ref: fetch the page title or check a redirect — a 404 may be a path
  change, not deletion.
- For a fact-claim in a `project`- or `reference`-type entry: Read the file or symbol the
  claim describes and verify whether the claim still matches.

You must read ground truth **this turn** before declaring a claim stale — never from memory
of the codebase.

## Phase 3 — Judge & plan (recall-first)

For each entry, decide one of:

| Decision | When |
|----------|------|
| **ok** | Claim verified correct, or unverifiable (feedback/opinions/plans). Leave as-is. |
| **correct** | You read the source AND found a specific, factually-wrong string you can fix precisely. |
| **annotate** | Claim is uncertain or a ref is dead/inconclusive but you cannot confirm it wrong. |
| **retire** | Entry is entirely superseded/obsolete AND you verified this from ground truth. |

Constraints:
- `correct.old` must be a string that appears **exactly once** in the file (the script
  rejects manifests where the count is not 1 — check first).
- A file may NOT be in both `retire` and `correct`/`annotate` in the same manifest.
- `inconclusive` refs alone never justify a `correct` or `retire`.
- Honor any `keep <topic>` directive from `$ARGUMENTS` as a hard constraint on retire.

## Phase 4 — Preview & approve (GATE)

Present ONE consolidated plan before writing anything:

- **Corrections:** for each, show the file, the exact `old` string (quoted), and the
  replacement `new` string.
- **Annotations:** for each, show the file and the note text that will appear in the banner.
- **Retires:** for each, show the file and the reason. For any file that has inbound
  `[[wikilinks]]` from other entries, note "(referenced by N — inbound links will be
  unlinked)".

**Do not write or run anything until the user approves.** A single approval covers the
whole plan.

## Phase 5 — Apply

1. **Author the manifest.** Turn the approved plan into a JSON file (full schema, rules, and
   a worked example in `references/refresh-manifest-schema.md`). Save it as an audit record
   at `<memory_parent>/memory-archive/_manifests/<UTC-timestamp>.json`.

2. **Dry-run** to validate the manifest and preview intent (writes nothing):
   ```bash
   python "${CLAUDE_SKILL_DIR}/scripts/refresh_apply.py" \
     --memory-dir "<memory_dir>" \
     --manifest "<manifest_path>" \
     --dry-run
   ```
   Confirm the reported `corrected` / `annotated` / `retired` match the approved plan.
   (`inbound_fixed` is always `[]` on a dry-run — inbound links are only rewritten on the
   real apply.)

3. **Apply:**
   ```bash
   python "${CLAUDE_SKILL_DIR}/scripts/refresh_apply.py" \
     --memory-dir "<memory_dir>" \
     --manifest "<manifest_path>"
   ```
   The script: replaces each `correct.old` with `correct.new` (exactly once); inserts an
   idempotent `> UNVERIFIED <date> — <note>` banner after the frontmatter of each `annotate`
   target; archives each `retire` target losslessly to `memory-archive/` with a tombstone,
   removes the original, drops the MEMORY.md pointer, and rewrites inbound `[[wikilinks]]`.
   It prints a JSON summary — keep it for Phase 6.

   If the script exits non-zero, read the `memory-tools:` error, fix the manifest, and
   re-run (see Safety rules).

## Phase 6 — Verify

Re-run the scan (`--json`). **From its output** confirm:
- The corrections introduced no NEW `dangling` refs.
- All retired entries have been dropped from `summary.entries` (they no longer appear in
  the active store).
- `wrong_root_suspected` is still `false`.

Separately — the scan only reads `memory/`, not the archive — Glob `memory-archive/` and
confirm every file listed under `retired` in the script's Phase-5 summary is present there
with a tombstone. Report measured before→after counts (`dangling`, `dead_links`,
`dangling_rate`). If any assertion fails, STOP and surface it — do not claim success.

## Track progress

Maintain a task checklist across the seven phases (locate → scan → semantic-verify → judge
→ preview → apply → verify) so progress is visible.
