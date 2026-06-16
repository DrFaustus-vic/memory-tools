# Frontmatter variants & the refresh seam

## Parse tolerantly, write conservatively
Claude Code memory frontmatter varies across versions. The analyzer tolerates all of:
- **Flat type** (de-facto standard): top-level `type: feedback`.
- **Nested type**: `metadata:` block with an indented `type: feedback`.
- **Name style**: kebab-case slugs (`feedback-retry-backoff`) OR human titles
  ("Visual QA protocol").

When rewriting or merging a file, **preserve that file's own variant** — the analyzer
reports per-file `schema_variant` (flat/nested) and `name_style` (kebab/human) in `files[]`.
Do NOT normalize to the store-wide majority (`store_convention`): real stores are frequently
mixed (e.g. roughly half nested / half flat), so majority-preservation would churn ~half the
files. Don't normalize schema unless the user explicitly asks — churn creates noisy diffs and
risks the harness's relevance selector.

## Recall & the archive guarantee
Recall scans files *in* `memory/` and selects by `description`. A file is guaranteed out of
recall only when it physically leaves `memory/` — dropping the `MEMORY.md` pointer alone is
not enough. Therefore the archive is a **sibling** `memory-archive/`, never `memory/_archive/`
(subdirectory recursion by the scanner is officially undocumented).

## Refresh seam (future `/refresh-memory`)
`compact-memory` only does internal consolidation (memory-vs-memory). A future
`/refresh-memory` will verify entries against ground truth (repo/git/files). It will reuse
`resolve_memory_dir()`, `parse_frontmatter()`, and `inventory_files()` from
`scripts/analyze_memory.py` unchanged; keep those functions free of compaction-specific
assumptions so both skills can share them.
