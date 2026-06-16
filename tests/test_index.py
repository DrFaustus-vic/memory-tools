import analyze_memory as am

INDEX = (
    "# Memory Index\n"
    "\n"
    "- [Short](a.md) — hook\n"
    "- [Long](b.md) — " + ("x" * 250) + "\n"
    "* [Star bullet](c.md) — alt bullet\n"
    "plain line, not an entry\n"
)


def test_counts_lines_and_bytes():
    r = am.parse_index(INDEX)
    assert r["lines"] == 6
    assert r["bytes"] == len(INDEX.encode("utf-8"))


def test_extracts_entries_and_targets():
    r = am.parse_index(INDEX)
    targets = [e["target"] for e in r["entries"]]
    assert targets == ["a.md", "b.md", "c.md"]


def test_flags_long_entries():
    r = am.parse_index(INDEX)
    long_targets = [e["target"] for e in r["long_entries"]]
    assert long_targets == ["b.md"]


def test_budget_flags_small_index_under_limits():
    r = am.parse_index(INDEX)
    assert r["over_lines"] is False
    assert r["over_bytes"] is False


# FIX I1: byte-aware long entry detection for multibyte characters

def test_cjk_line_under_char_limit_but_over_byte_limit_flagged():
    # 150 CJK chars = 150 chars (under LONG_ENTRY_CHARS=200)
    # but 150 * 3 = 450 bytes (over LONG_ENTRY_BYTES=300)
    cjk_line = "- [CJK](cjk.md) — " + ("本" * 150) + "\n"
    index_text = "# Memory\n" + cjk_line
    r = am.parse_index(index_text)
    assert len(r["entries"]) == 1
    entry = r["entries"][0]
    # Confirm it's under the char limit
    assert entry["chars"] <= 200
    # Confirm it's over the byte limit
    assert entry["bytes"] > 300
    # Confirm it IS flagged as a long entry
    assert entry["target"] in [e["target"] for e in r["long_entries"]]
