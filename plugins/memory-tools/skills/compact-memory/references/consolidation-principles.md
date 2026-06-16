# Consolidation principles

Master rule: **maximize recall first, then improve precision.** Over-aggressive compaction
loses context whose importance only shows up later. Bias to keep; archive, never delete.

1. **Recency wins conflicts, deterministically.** On contradiction, keep the entry with the
   most recent date; tie-break by an explicit, stated rule.
2. **Dedupe to a single canonical version.** Collapse exact and near-duplicate facts into
   one best-worded entry.
3. **Durable-AND-actionable gate.** Keep an entry only if it is true across sessions AND
   would change future behavior. Retire ephemeral/one-off notes.
4. **Supersede, don't delete.** Stale entries are archived with a tombstone (retired-on date
   + reason + merged-into link).
5. **Cap the loaded index, not the whole store.** The always-loaded `MEMORY.md` stays under
   budget; detail lives in topic files pulled in on demand.
6. **Clear regenerable noise first.** Run-logs / raw outputs are the safest cuts; do them
   before touching semantic facts.
7. **Preserve uncertainty.** Carry `UNVERIFIED`/hedged tags through merges; never launder a
   hedge into a hard fact.
8. **Structured consolidation, not prose summary.** Merge into canonical entries; do not
   re-summarize a fact store into prose.
9. **Normalize expired time references** during merge (e.g. "going to X in July" → settled
   fact) so re-reads don't mislead.
10. **Timestamps as a relevance/staleness proxy.** Old + unreferenced entries are retirement
    candidates.
11. **No silent loss.** After applying, verify no load-bearing fact disappeared.
12. **Never eyeball a metric.** All byte/line/count figures come from `analyze_memory.py`.
