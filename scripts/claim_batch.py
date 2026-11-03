"""Claim a bounded batch of related packets for one worker and prepare its verified rule views."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locpipe.orchestration import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main("claim-batch"))
