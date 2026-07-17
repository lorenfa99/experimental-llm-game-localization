from __future__ import annotations

from pathlib import Path


DEFAULT_CONFIG = '''[project]
name = "My game localization"
source_root = "input/source"
baseline_root = "input/baseline"
release_root = "release"
work_root = "work"
reports_root = "reports"
references = ["reference/glossary.tsv", "reference/rules.md"]
delimiter = "|"
markers = ["<<", ">>", "[[", "]]", "((", "))", "##", "#", "@@", "%%", "&&"]
locked_values = ["", "null"]

[[pairs]]
key = "dialogue"
source = "dialogue_en.txt"
baseline = "dialogue_target.txt"
output = "dialogue_target.txt"
schema = "dialogue"
id_field = 0
translatable_fields = [1]
field_labels = ["text"]
confidence = "explicit"
opaque_reference = "source"
'''

DEFAULT_RULES = '''# Binding localization rules

Replace this template with project-specific rules for source authority,
terminology, capitalization, forms of address, player gender, character and
faction voices, markers, placeholders, runtime fragments, UI length, subtitles,
and content that must remain unchanged.
'''

DEFAULT_IGNORE = '''input/
release/
work/
reports/
package/
.env
__pycache__/
*.pyc
'''


def initialize_project(path: str | Path) -> Path:
    root = Path(path).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"Refusing to initialize non-empty directory: {root}")
    for directory in (
        root / "input" / "source",
        root / "input" / "baseline",
        root / "release",
        root / "work",
        root / "reports",
        root / "reference",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (root / "project.toml").write_text(DEFAULT_CONFIG, encoding="utf-8", newline="\n")
    (root / "reference" / "rules.md").write_text(DEFAULT_RULES, encoding="utf-8", newline="\n")
    (root / "reference" / "glossary.tsv").write_text("source\ttarget\tnote\n", encoding="utf-8", newline="\n")
    (root / "work" / "CORRECTIONS.jsonl").write_text("", encoding="utf-8", newline="\n")
    (root / ".gitignore").write_text(DEFAULT_IGNORE, encoding="utf-8", newline="\n")
    return root
