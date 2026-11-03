"""Save a private live-state handoff; claims, submits and approvals are untouched."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locpipe.orchestration import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main("save-progress"))
