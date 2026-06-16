import analyze_memory as am


def test_broken_wikilink_detected():
    files = [
        {"filename": "a.md", "name": "alpha", "body": "see [[beta]] and [[ghost]]"},
        {"filename": "b.md", "name": "beta", "body": "no links"},
    ]
    r = am.find_broken_links(files)
    assert r == [{"from": "a.md", "to": "ghost"}]


def test_wikilink_matches_filename_stem():
    files = [
        {"filename": "a.md", "name": "alpha", "body": "see [[b]]"},
        {"filename": "b.md", "name": "beta-long-name", "body": ""},
    ]
    r = am.find_broken_links(files)
    assert r == []  # 'b' matches stem of b.md


# FIX C1: hyphen/underscore normalization + case-insensitive matching

def test_hyphen_link_matches_underscore_filename():
    # [[project-retry-backoff]] should match project_retry_backoff.md
    files = [
        {"filename": "project_retry_backoff.md", "name": "project_retry_backoff", "body": ""},
        {"filename": "ref.md", "name": "ref", "body": "see [[project-retry-backoff]]"},
    ]
    r = am.find_broken_links(files)
    assert r == []  # NOT broken — hyphen == underscore after normalization


def test_genuinely_missing_link_still_broken():
    # [[nope-xyz]] should still be reported broken when no such file exists
    files = [
        {"filename": "ref.md", "name": "ref", "body": "see [[nope-xyz]]"},
    ]
    r = am.find_broken_links(files)
    assert r == [{"from": "ref.md", "to": "nope-xyz"}]


def test_case_insensitive_link_matching():
    # [[ALPHA]] should match a file named alpha.md / name "alpha"
    files = [
        {"filename": "alpha.md", "name": "alpha", "body": ""},
        {"filename": "ref.md", "name": "ref", "body": "see [[ALPHA]]"},
    ]
    r = am.find_broken_links(files)
    assert r == []  # NOT broken — case-insensitive


def test_inbound_links_maps_referrers():
    files = [
        {"filename": "a.md", "name": "alpha", "body": "see [[beta]] and [[beta]]"},
        {"filename": "b.md", "name": "beta", "body": "no links"},
        {"filename": "c.md", "name": "gamma", "body": "ref [[beta]] and [[alpha]]"},
    ]
    inbound = am.build_inbound_links(files)
    assert inbound["b.md"] == ["a.md", "c.md"]  # beta referenced by a and c (deduped)
    assert inbound["a.md"] == ["c.md"]          # alpha referenced by c
    assert "c.md" not in inbound                # gamma referenced by nobody


def test_inbound_links_normalize_and_skip_self():
    files = [
        {"filename": "feedback_retry_policy.md", "name": "feedback retry policy", "body": ""},
        {"filename": "gw.md", "name": "gw", "body": "superseded; see [[feedback-retry-policy]]; self [[gw]]"},
    ]
    inbound = am.build_inbound_links(files)
    assert inbound["feedback_retry_policy.md"] == ["gw.md"]  # hyphen link resolves to underscore file
    assert "gw.md" not in inbound                          # self-link excluded
