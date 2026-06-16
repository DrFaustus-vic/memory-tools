import analyze_memory as am


def test_tokens_drop_stopwords_and_short():
    toks = am._tokens("the cache retry backoff", "use when")
    assert "cache" in toks and "retry" in toks and "backoff" in toks
    assert "the" not in toks and "use" not in toks and "is" not in toks


def test_cluster_groups_same_type_overlap():
    files = [
        {"filename": "cache-a.md", "name": "cache-ttl-config", "description": "cache ttl tuning", "type": "reference"},
        {"filename": "cache-b.md", "name": "cache-ttl-eviction", "description": "cache ttl eviction policy", "type": "reference"},
        {"filename": "unrelated.md", "name": "json-parser", "description": "parsing helper", "type": "project"},
    ]
    clusters = am.cluster_duplicates(files)
    assert len(clusters) == 1
    assert sorted(clusters[0]["members"]) == ["cache-a.md", "cache-b.md"]
    assert "cache" in clusters[0]["shared_tokens"]


def test_cluster_requires_same_type():
    files = [
        {"filename": "a.md", "name": "cache-ttl", "description": "cache ttl", "type": "reference"},
        {"filename": "b.md", "name": "cache-ttl", "description": "cache ttl", "type": "feedback"},
    ]
    assert am.cluster_duplicates(files) == []


def test_cluster_excludes_non_common_members_and_shared_tokens_never_empty():
    # The grouping EXCLUDES members without the common token set and shared_tokens
    # is never empty; it is NOT fully transitive — determinism comes from the
    # upstream filename sort in inventory_files.
    # Seed shares 2 tokens with each of two others, but those two share DIFFERENT
    # token pairs with the seed. They must NOT collapse into one mega-cluster with
    # empty shared_tokens (the degenerate behaviour dogfooding surfaced).
    files = [
        {"filename": "seed.md", "name": "alpha beta gamma delta", "description": "", "type": "project"},
        {"filename": "ab.md", "name": "alpha beta", "description": "", "type": "project"},
        {"filename": "gd.md", "name": "gamma delta", "description": "", "type": "project"},
    ]
    clusters = am.cluster_duplicates(files)
    for c in clusters:
        assert len(c["shared_tokens"]) >= 2  # never degenerate/empty
    assert any(set(c["members"]) == {"seed.md", "ab.md"} for c in clusters)
    # gd.md must not be swept into the same cluster as ab.md (no common thread)
    assert not any("gd.md" in c["members"] and "ab.md" in c["members"] for c in clusters)
