import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_plugin_manifest_valid():
    data = json.loads((ROOT / "plugins" / "memory-tools" / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert data["name"] == "memory-tools"
    assert "version" in data


def test_marketplace_manifest_lists_plugin():
    data = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text("utf-8"))
    names = [p["name"] for p in data["plugins"]]
    assert "memory-tools" in names
