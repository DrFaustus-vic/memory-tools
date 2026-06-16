import pytest
import analyze_memory as am


def test_explicit_arg_with_index(tmp_path):
    (tmp_path / "MEMORY.md").write_text("- [A](a.md)\n", encoding="utf-8")
    assert am.resolve_memory_dir(str(tmp_path)) == tmp_path


def test_explicit_arg_with_only_topic_files(tmp_path):
    (tmp_path / "a.md").write_text("x\n", encoding="utf-8")
    assert am.resolve_memory_dir(str(tmp_path)) == tmp_path


def test_explicit_arg_missing_raises(tmp_path):
    empty = tmp_path / "nope"
    empty.mkdir()
    with pytest.raises(SystemExit):
        am.resolve_memory_dir(str(empty))
