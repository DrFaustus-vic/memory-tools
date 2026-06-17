# Refresh manifest schema

`refresh_apply.py` executes Phase 5 from a single JSON manifest you author from the
approved plan. The script **validates the entire manifest before any mutation** — if
anything is wrong it exits non-zero with a `memory-tools: <reason>` message and changes
nothing. Fix the manifest and re-run; never hand-edit `memory/` to work around it.

## Shape

```json
{
  "date": "2026-06-17",
  "correct": [
    {"file": "http_client.md", "old": "retry budget is 3 attempts", "new": "retry budget is 5 attempts"}
  ],
  "annotate": [
    {"file": "cache_policy.md", "note": "eviction docs URL returned 404 — verify the current endpoint"}
  ],
  "retire": [
    {"file": "legacy_auth.md", "reason": "superseded by oauth_flow.md (confirmed in codebase)"}
  ]
}
```

All four top-level keys are optional. Omit a section you aren't using. `{}` (or
`{"date": "…"}` with no actions) is a valid no-op.

## Fields

### `date` (string)
UTC date stamped into UNVERIFIED banners, tombstones, and the `memory-archive/README.md`
audit block. Use the session's current UTC date (`YYYY-MM-DD`).

### `correct` (list of objects)
Apply an exact, targeted text replacement inside a memory file.
- `file` — **must exactly match** a current filename in `memory/`. The script compares
  against the live directory listing; aliases are rejected: trailing space/dot, different
  case, path separators, `..`, absolute paths, and reserved device names.
- `old` — the string to replace. **Must appear exactly once** in the file; the script
  counts occurrences and rejects the whole manifest if the count is not 1. Choose a long
  enough excerpt to be unambiguous.
- `new` — the replacement string. May be empty (to delete the passage). The replacement is
  applied exactly once with `str.replace(old, new, 1)`.

A file may appear in `correct` multiple times (to fix several distinct facts), but each
entry's `old` must still match exactly once across the whole file. A file targeted by
`correct` may NOT also appear in `retire` in the same manifest.

### `annotate` (list of objects)
Insert an idempotent uncertainty banner into a file — use when a reference is dead or
inconclusive but you cannot confirm the claim is wrong.
- `file` — existing filename (same exact-match rule as `correct.file`).
- `note` — non-empty string; describes the uncertainty. The banner inserted after the
  closing `---` of the frontmatter (or at the top of the file if there is no frontmatter)
  takes the form:

  ```
  > UNVERIFIED <date> — <note>
  ```

  Insertion is idempotent: if the exact banner string is already present, the file is not
  changed and it is NOT listed in `annotated` in the summary.

A file may appear in `annotate` multiple times (for multiple uncertainty notes). A file
targeted by `annotate` may NOT also appear in `retire`.

### `retire` (list of objects)
Archive an obsolete file out of the active store, lossless.
- `file` — existing filename (same exact-match rule).
- `reason` — non-empty string; goes into the tombstone (`> RETIRED <date> — <reason>`).

Each filename may appear at most once in `retire`. A file targeted by `retire` may NOT
also appear in `correct` or `annotate`.

## What the script guarantees

- **Validate-all-then-mutate.** Types, keys, existence, uniqueness of `correct.old`, and
  retire-vs-edit conflicts are all checked first; a bad manifest mutates nothing (true on
  `--dry-run` too).
- **`correct.old` must match exactly once.** The script counts occurrences; 0 or ≥2 is a
  validation error that leaves the file untouched.
- **Idempotent annotation.** If the exact banner is already present the file is skipped —
  re-running the same `annotate` entry is always safe.
- **Archive-not-delete, verified.** Each retired original is copied to `memory-archive/`
  with a tombstone prepended, re-read to verify the copy, then deleted. A same-named prior
  archive is never overwritten (disambiguated as `<stem>.1.md`, …).
- **Index pruned and inbound links fixed.** For each retired file: its pointer is dropped
  from `MEMORY.md`; in every surviving file, `[[<stem>]]` wikilinks are replaced with
  `retired (archived)`.

## Invocation

```bash
# validate + preview only (no writes)
python "${CLAUDE_SKILL_DIR}/scripts/refresh_apply.py" \
  --memory-dir "<memory_dir>" \
  --manifest "<manifest_path>" \
  --dry-run

# apply
python "${CLAUDE_SKILL_DIR}/scripts/refresh_apply.py" \
  --memory-dir "<memory_dir>" \
  --manifest "<manifest_path>"
```

The script prints a JSON summary:

```json
{
  "dry_run": false,
  "corrected": ["http_client.md"],
  "annotated": ["cache_policy.md"],
  "retired": ["legacy_auth.md"],
  "inbound_fixed": ["api_overview.md"]
}
```

On `--dry-run` the summary lists the planned `corrected` / `annotated` / `retired`, but
`inbound_fixed` is always `[]` — inbound `[[wikilinks]]` are only rewritten during the
real apply.

## Worked example

### Scenario

Your scan found:
1. `http_client.md` claims the retry budget is 3 attempts; you read the actual retry
   module and it is now 5.
2. `cache_policy.md` references a docs URL that returned 404 — you can't confirm the page
   is gone permanently (might be a redirect in progress).
3. `legacy_auth.md` is entirely superseded by `oauth_flow.md`; you confirmed no current
   code imports or references the old approach.
4. `api_overview.md` has `[[legacy_auth]]` linking to the file you are retiring.

### Manifest

```json
{
  "date": "2026-06-17",
  "correct": [
    {
      "file": "http_client.md",
      "old": "retry budget is 3 attempts",
      "new": "retry budget is 5 attempts"
    }
  ],
  "annotate": [
    {
      "file": "cache_policy.md",
      "note": "eviction docs URL (https://docs.example.com/cache) returned 404 — verify the current endpoint"
    }
  ],
  "retire": [
    {
      "file": "legacy_auth.md",
      "reason": "superseded by oauth_flow.md — legacy OAuth 1 flow removed in v3.0"
    }
  ]
}
```

### What the script does

1. Validates: `legacy_auth.md` is not in `correct` or `annotate`; `http_client.md`'s
   `old` string appears exactly once; `cache_policy.md` exists.
2. Replaces the retry-budget sentence in `http_client.md`.
3. Inserts `> UNVERIFIED 2026-06-17 — eviction docs URL … returned 404 — verify the current endpoint`
   after `cache_policy.md`'s frontmatter.
4. Archives `legacy_auth.md` to `memory-archive/` with a `> RETIRED 2026-06-17 — …`
   tombstone, verifies the copy, deletes the original.
5. Drops the `legacy_auth.md` pointer from `MEMORY.md`.
6. Rewrites `[[legacy_auth]]` in `api_overview.md` to `retired (archived)`.

### Summary output

```json
{
  "dry_run": false,
  "corrected": ["http_client.md"],
  "annotated": ["cache_policy.md"],
  "retired": ["legacy_auth.md"],
  "inbound_fixed": ["api_overview.md"]
}
```
