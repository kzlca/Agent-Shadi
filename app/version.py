"""Single source of truth for the Agent Shadi application version."""
import os
from pathlib import Path

_VERSION_FILE = Path(os.environ.get("AGENT_SHADI_RESOURCE_DIR") or Path(__file__).resolve().parents[1]) / "VERSION"
__version__ = _VERSION_FILE.read_text(encoding="utf-8").strip()

if not __version__:
    raise RuntimeError("VERSION file is empty")
