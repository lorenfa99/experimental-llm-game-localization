# Contributing

Use synthetic fixtures. Never commit game corpora, official references, game binaries,
local settings, credentials or checkpoints. Keep linguistic generation in actual
agent contexts and deterministic state/validation in Python.

For substantive code or adapter changes run `python -m unittest discover -s tests -v`
and `python scripts/run_synthetic_demo.py`. Add tests for meaningful failure modes:
stale versions, identity collisions, atomic rollback, recovery, independence input
boundaries, source copies, unknown metadata and actual artifact readback.

Document implemented capabilities and unsupported formats honestly. Preserve stage
requirements and owner authority. A proposed optimization should remove duplication
while retaining full rule/context reads and genuine independent rereview.
