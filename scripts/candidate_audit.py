"""Write read-only evidence for one built candidate: closure, QA, artifact content, formats and fonts."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locpipe.orchestration import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main("candidate-audit"))
