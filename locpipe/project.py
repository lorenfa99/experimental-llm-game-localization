"""Initialize isolated projects from copyright-safe, packaged templates."""
from pathlib import Path
import shutil

from .config import HarnessError


def initialize(directory):
    root = Path(directory).resolve()
    template = Path(__file__).resolve().parent / "templates/project"
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise HarnessError("Project initialization refuses nonempty directories; existing drafts are preserved")
    if not template.is_dir():
        raise HarnessError("Packaged project template is missing; reinstall the toolkit")
    root.mkdir(parents=True, exist_ok=True)
    for source in sorted(template.rglob("*")):
        if not source.is_file():
            continue
        destination = root / source.relative_to(template)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    for directory in ("data", "work", "reports", "build", "backups"):
        (root / directory).mkdir(exist_ok=True)
    return root
