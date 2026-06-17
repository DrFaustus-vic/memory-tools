# Verification principles

These principles govern Phase 2 (semantic verify) and Phase 3 (judge & plan). They exist
to prevent two failure modes: **false positives** (flagging a correct claim as stale) and
**false negatives** (silently leaving wrong claims in place). The recall-first bias means
false positives are the worse failure.

## Read before you act (recall-first)

You must read the actual source — the file, function, git log entry, or live page — that
a claim describes BEFORE marking that claim stale. Reading it from memory of the codebase
does not count; the whole point of refresh-memory is that codebases drift. If you cannot
read the source this session, treat the entry as unverifiable and leave it alone.

Examples of "read the source":
- A memory note says a function is named `fetch_with_retry`. Before flagging it renamed,
  run `grep -r fetch_with_retry .` or use Grep to confirm it is absent, then check git log
  for a rename.
- A memory note says a config file lives at `config/defaults.yaml`. Before flagging it
  dangling, use Glob to search the repo for `defaults.yaml`.
- A memory note says a docs URL covers a specific topic. Before flagging it dead, fetch
  the URL (or at least check whether a redirect leads somewhere relevant).

## What the scan tells you (and what it doesn't)

The scan gives you deterministic evidence. Use it correctly:

| Status | Meaning | Correct response |
|--------|---------|-----------------|
| `resolved` | Path exists / symbol found in the repo | No action needed |
| `reachable` | URL responded 2xx/3xx | No action needed |
| `dangling` | Path not found under the project root | Investigate — may be a rename, wrong root, or genuine deletion |
| `dead` | URL returned 404 or 410 | Investigate — may be a redirect, page move, or genuine removal |
| `inconclusive` | Symbol absent or URL unreachable (network error, timeout, 5xx) | Low confidence — annotate at most; never correct or retire |

The scan does NOT read the prose of an entry and cannot tell you whether a factual claim
matches the codebase. That is your job in Phase 2.

## `dead` and `inconclusive` are not proof of staleness

A single dead URL or inconclusive symbol absence tells you something MAY have changed —
nothing more. Use it as a prompt to investigate, not as a conclusion.

- A 404 may be a temporary outage, a server-side redirect not followed by HEAD, or a URL
  that moved (check `301`/`302`).
- An inconclusive symbol may live in a dependency, a generated file, or a file type the
  search skipped.
- A network blip (timeout, 5xx) is definitively inconclusive.

**Rule:** `dead` or `inconclusive` alone may produce an `annotate` entry. They may NEVER
produce a `correct` or `retire` entry without corroborating evidence you read this turn.

## Unverifiable entries are always "ok"

Some memory entries record facts that have no ground truth in the repo: team decisions,
user preferences, external process notes, opinions, pipeline strategy, action items. These
cannot be verified or falsified by reading files or checking links. Leave them as `ok`.
Do not annotate them as UNVERIFIED just because you cannot find a file that confirms them.

## The wrong-root guard

If the scan returns `wrong_root_suspected: true` (dangling-path rate > 50%), stop the
entire refresh — the project root passed to the scan is almost certainly misaimed at the
wrong repo or an unrelated directory. A mass-dangling result in this state is meaningless:
nearly every path ref will appear dangling regardless of actual staleness.

Surface this to the user with the `dangling_rate` value and ask them to confirm the
correct `--project-root`. Only resume after re-running with a corrected root.

## Applying these principles to each action type

### `correct`
Use only when:
1. You read the file/function/config that the claim describes (this turn).
2. You found a specific string in the memory note that is factually wrong.
3. `correct.old` appears exactly once in the file (count before authoring the manifest).

Never use `correct` to rewrite a claim based on inference, analogy, or memory.

### `annotate`
Use when a ref is `dead`/`inconclusive` and you cannot confirm the claim is wrong — or
when a claim is plausibly outdated but you lack the read access to verify it. The
`> UNVERIFIED` banner is visible to future sessions without altering the underlying fact.

### `retire`
Use only when you have read ground truth that the entry's entire subject is gone or
superseded — not just one fact within it. Retirement is permanent (archive, then delete
from active store). When in doubt between `annotate` and `retire`, choose `annotate`.
