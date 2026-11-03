"""Audit the glossary against the in-scope corpus (read-only) and write reports/glossary-audit.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from locpipe.glossary_audit import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
