import analyze_memory as am

FLAT = "---\nname: feedback-retry-backoff\ndescription: Add jitter to retries\ntype: feedback\n---\nbody\n"
NESTED = "---\nname: Visual QA protocol\ndescription: steps\nmetadata:\n  type: feedback\n---\nbody\n"
NONE = "no frontmatter here\n"
UNTERMINATED = "---\nname: x\ndescription: y\n"
# FIX M2: all three fields nested under metadata:
FULLY_NESTED = "---\nmetadata:\n  name: nested-name\n  description: nested desc\n  type: project\n---\nbody\n"
# FIX M3: BOM before the opening ---
BOM_FM = "﻿---\nname: a\ntype: project\n---\nbody\n"


def test_flat_type_and_kebab_name():
    r = am.parse_frontmatter(FLAT)
    assert r["name"] == "feedback-retry-backoff"
    assert r["description"] == "Add jitter to retries"
    assert r["type"] == "feedback"
    assert r["schema_variant"] == "flat"
    assert r["name_style"] == "kebab"


def test_nested_type_and_human_name():
    r = am.parse_frontmatter(NESTED)
    assert r["type"] == "feedback"
    assert r["schema_variant"] == "nested"
    assert r["name_style"] == "human"


def test_no_frontmatter_warns():
    r = am.parse_frontmatter(NONE)
    assert r["schema_variant"] == "none"
    assert "no_frontmatter" in r["warnings"]


def test_unterminated_frontmatter_warns():
    r = am.parse_frontmatter(UNTERMINATED)
    assert "unterminated_frontmatter" in r["warnings"]


# FIX M2: name and description nested under metadata: are captured

def test_fully_nested_name_description_type_captured():
    r = am.parse_frontmatter(FULLY_NESTED)
    assert r["name"] == "nested-name"
    assert r["description"] == "nested desc"
    assert r["type"] == "project"
    assert r["schema_variant"] == "nested"


# FIX M3: BOM before --- is stripped so frontmatter parses correctly

def test_bom_stripped_before_frontmatter():
    r = am.parse_frontmatter(BOM_FM)
    assert r["type"] == "project"
    assert "no_frontmatter" not in r["warnings"]
