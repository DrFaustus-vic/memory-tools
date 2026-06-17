import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "memory-tools"
for p in (PLUGIN / "lib",
          PLUGIN / "skills" / "compact-memory" / "scripts",
          PLUGIN / "skills" / "refresh-memory" / "scripts"):
    sys.path.insert(0, str(p))
