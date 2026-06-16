import sys
from pathlib import Path

SCRIPTS = (Path(__file__).resolve().parent.parent
           / "plugins" / "memory-tools" / "skills" / "compact-memory" / "scripts")
sys.path.insert(0, str(SCRIPTS))
