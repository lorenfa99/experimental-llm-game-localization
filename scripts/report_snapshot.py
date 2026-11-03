"""Write a private, read-only evidence snapshot and bilingual pilot table; never assesses quality."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locpipe.orchestration import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main("snapshot"))
