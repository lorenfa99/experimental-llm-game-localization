"""Build an offline external-review kit, parse the reviewers' answers and export triaged findings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locpipe.review_kit import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
