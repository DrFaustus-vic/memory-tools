import analyze_memory as am


def test_reconcile_finds_orphans_and_unindexed():
    index = {"entries": [
        {"line": 1, "title": "A", "target": "a.md", "chars": 10},
        {"line": 2, "title": "Gone", "target": "gone.md", "chars": 10},
    ]}
    files = [
        {"filename": "a.md"},
        {"filename": "b.md"},  # exists but not referenced
    ]
    r = am.reconcile(index, files)
    assert [o["target"] for o in r["orphans"]] == ["gone.md"]
    assert r["unindexed"] == ["b.md"]


def test_reconcile_handles_path_prefixed_targets():
    index = {"entries": [{"line": 1, "title": "A", "target": "./a.md", "chars": 10}]}
    files = [{"filename": "a.md"}]
    r = am.reconcile(index, files)
    assert r["orphans"] == []
    assert r["unindexed"] == []
