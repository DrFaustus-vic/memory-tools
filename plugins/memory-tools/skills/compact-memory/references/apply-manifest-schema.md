# Apply manifest schema

`apply.py` executes Phase 4 from a single JSON manifest you author from the approved plan.
The script **validates the entire manifest before any mutation** — if anything is wrong it
exits non-zero with an `apply: <reason>` message and changes nothing. Fix the manifest and
re-run; never hand-edit `memory/` to work around it.

## Shape

```json
{
  "date": "2026-06-15",
  "retire": [
    {"file": "old_thing.md", "reason": "superseded by the rewritten note"}
  ],
  "merge": [
    {
      "canonical_file": "caching.md",
      "canonical_body": "---\nname: caching\ntype: reference\n---\nCache TTL tuning and eviction policy in one place. See [[http_client]].\n",
      "canonical_index_line": "- [caching.md](caching.md) — cache TTL tuning + eviction policy",
      "absorbed": ["cache_ttl.md", "cache_eviction.md"]
    }
  ],
  "shorten": [
    {"file": "big_topic.md", "new_index_line": "- [big_topic.md](big_topic.md) — one-line hook; detail in the file"}
  ]
}
```

All four top-level keys are optional. Omit a section you aren't using. `{}` (or
`{"date": "…"}` with no actions) is a valid no-op.

## Fields

### `date` (string)
UTC date stamped into tombstones and the `memory-archive/README.md` audit block. Use the
session's current UTC date (`YYYY-MM-DD`).

### `retire` (list of objects)
Move an obsolete file out of the active store, lossless, to `memory-archive/`.
- `file` — **must exactly match** a current filename in `memory/`. The script compares
  against the live directory listing, so aliases are rejected: trailing space/dot, different
  case, path separators, `..`, absolute paths, `:` / control chars, reserved device names.
- `reason` — short string; goes into the tombstone (`> RETIRED <date> — <reason>`).

### `merge` (list of objects)
Consolidate several overlapping files into one new canonical file; archive the originals.
- `canonical_file` — the **new** filename. Must NOT already exist in `memory/` (case-insensitive),
  must not be `MEMORY.md`, and must be a bare safe filename. Two merges can't target the same
  canonical (even case-only differences).
- `canonical_body` — the full markdown of the consolidated file **including frontmatter**.
  YOU write this. Preserve the chosen source file's own frontmatter variant (flat `type:` vs
  nested `metadata.type:`; kebab vs human `name:`) — don't normalize schema across the store.
  Link related entries with `[[stem]]`. The script writes this body verbatim (it is not
  itself rewritten by the inbound-link pass).
- `canonical_index_line` — the `MEMORY.md` line for the new file. Must be a bullet (`-`/`*`)
  whose markdown link points at `canonical_file`. Keep it < 200 chars (one-line hook).
- `absorbed` — non-empty list of existing filenames (same exact-match rule as `retire.file`)
  that this merge replaces. Each is archived with a `> MERGED <date> into <canonical_stem>`
  tombstone.

### `shorten` (list of objects)
Trim an over-long index line to a one-line pointer; the detail stays in the (untouched) topic
file. Use for entries flagged as long in the analyzer report.
- `file` — existing filename (exact-match rule).
- `new_index_line` — replacement bullet linking to `file`, < 200 chars.

## What the script guarantees

- **Validate-all-then-mutate.** Types, keys, existence, collisions, and index-line targets are
  all checked first; a bad manifest mutates nothing (true on `--dry-run` too).
- **No file appears twice** across `retire`/`absorbed`; no file is both shortened and gone.
- **Archive-not-delete, verified.** Each original is written to `memory-archive/<file>` with a
  tombstone + the original RAW bytes, then re-read byte-for-byte; the original is deleted only
  if the copy matches. A same-named prior archive is never overwritten (`<stem>.1.md`, …).
- **Index edited surgically.** `MEMORY.md` is rewritten line-by-line preserving each line's
  exact bytes and the file's line endings; gone pointers drop, each merged line lands at the
  index slot of the first of its absorbed files (in listed order) that is indexed (else
  appended), shortened lines are replaced, and each managed target yields at most one line.
- **Inbound links fixed.** In every surviving file, `[[absorbed]]` → `[[canonical_stem]]` and
  `[[retired]]` → `retired (archived)`. A link that still resolves to a LIVE file (by stem OR
  frontmatter name) is left untouched, so no live reference is mislabeled.

## Invocation

```bash
# validate + preview only (no writes)
python "${CLAUDE_SKILL_DIR}/scripts/apply.py" --memory-dir "<memory_dir>" --manifest "<manifest>" --dry-run
# apply
python "${CLAUDE_SKILL_DIR}/scripts/apply.py" --memory-dir "<memory_dir>" --manifest "<manifest>"
```

The script prints a JSON summary: `{dry_run, merged, retired, absorbed, shortened, inbound_fixed}`.
Keep it for Phase 5 verification. On `--dry-run` the summary lists the planned
`retired`/`absorbed`/`merged`/`shortened`, but `inbound_fixed` is always `[]` — inbound
`[[wikilinks]]` are only rewritten during the real apply.
