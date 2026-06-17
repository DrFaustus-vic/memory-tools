# memory-tools

A community [Claude Code](https://code.claude.com) plugin for maintaining the built-in file-based **memory** store (`~/.claude/projects/<project>/memory/` + its `MEMORY.md` index).

## Skills

### `/memory-tools:compact-memory`

The memory analog of `/compact`. It reads the whole memory store, **deduplicates and merges** overlapping entries, **retires obsolete ones to a sibling archive** (never deletes), and **shrinks the loaded `MEMORY.md` index** back under its size budget — behind a **preview-and-approve gate**. Lossy in the active store, lossless on disk.

### `/memory-tools:refresh-memory`

The memory analog of fact-checking your notes. It **verifies each memory entry against ground truth** — repo files, git history, and any external links it cites — and **corrects, annotates, or retires** what reality contradicts, behind a **preview-and-approve gate**. Lossless on disk, like compact-memory.

## Requirements

- Claude Code with the built-in file-based memory feature enabled.
- **Python 3** on your `PATH`. All scripts are **standard-library only** — no `pip install` needed to run the skills.

## Install

From a GitHub-hosted marketplace:

```
/plugin marketplace add DrFaustus-vic/memory-tools
/plugin install memory-tools@memory-tools
```

(For local use without a marketplace, copy a skill folder from `plugins/memory-tools/skills/` into your `~/.claude/skills/`; it then runs as a bare `/compact-memory` or `/refresh-memory`.)

## Usage

```
/memory-tools:compact-memory
```

Optional free-form steering:

| Argument | Effect |
|----------|--------|
| _(none)_ / `be conservative` | **Default.** Retire only obvious duplicates + explicitly-`SUPERSEDED` entries; shrink the index. |
| `be aggressive` | Also merge near-duplicates and retire stale-by-date / unreferenced entries. |
| `index only` | Only shrink the `MEMORY.md` index (relocate detail into topic files); don't retire or merge. |
| `keep <topic>` | Hard-protect entries matching `<topic>` from retirement. |

```
/memory-tools:refresh-memory
```

Optional steering: `--project-root <path>` (the repo to check against; default cwd), `no network` (skip external-link checks), `keep <topic>` (protect entries from retirement).

Both skills **always generate a snapshot and preview a plan for your approval** before writing anything.

## How it works

A small stdlib-only Python analyzer (`scripts/analyze_memory.py`) does the deterministic measurement — byte/line budget, duplicate-candidate clusters, stale markers, broken links, orphan pointers — and emits a JSON report. The model makes the judgment calls (what to merge, retire, shorten) and previews them; on approval a second stdlib-only script (`scripts/apply.py`) executes the whole apply in one validated pass — archiving losslessly, verifying each copy before it deletes the original, rewriting the index EOL-preserving, and repointing inbound links.

`refresh-memory` follows the same shape: `scripts/refresh_scan.py` checks every reference an entry makes — paths against the repo and git tree, symbols, and external links — and emits a JSON report; the model judges against ground truth; `scripts/refresh_apply.py` applies the approved corrections, annotations, and retirements in one validated pass.

## Safety & recovery

- **Archive, never delete.** Retired entries move to a **sibling** `memory-archive/` directory (next to `memory/`, never inside it) with a tombstone, and their `MEMORY.md` pointer is removed. The move *out of* `memory/` is what guarantees they can't be recalled again.
- **Snapshots.** Each run first snapshots the whole `memory/` dir into `memory-archive/_snapshots/<timestamp>/` (the 3 most recent are kept). Claude Code's own `file-history` is an additional backstop.
- **Recover** a retired entry by copying it from `memory-archive/` back into `memory/` and re-adding its `MEMORY.md` pointer.

## Development

```
pip install -r requirements-dev.txt
python -m pytest -q tests
```

## License

MIT
