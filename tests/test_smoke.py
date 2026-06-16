import analyze_memory as am


def test_module_imports_and_constants():
    assert am.INDEX_FILE == "MEMORY.md"
    assert am.INDEX_LINE_LIMIT == 200
    assert am.INDEX_BYTE_LIMIT == 25_000
