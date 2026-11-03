"""Append a dispatch, reconciliation or acceptance receipt without changing harness state."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locpipe.orchestration import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main("record-batch"))
