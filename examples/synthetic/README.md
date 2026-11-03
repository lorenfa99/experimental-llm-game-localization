# Synthetic engineering example

source.json is an invented, engine-neutral source with two translatable UI entries
and two excluded source copies. It contains no game content or owner approvals.

`python scripts/run_synthetic_demo.py` creates a separate preparation template,
records synthetic fixture decisions, simulates all five linguistic stages and
verifies source-copy/candidate readback. It keeps runtime/release pending and never
calls a model, installs a game or claims real independent linguistic review.
