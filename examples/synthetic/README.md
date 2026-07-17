# Synthetic example

This miniature project contains no game content. It demonstrates a pipe-
delimited dialogue table with IDs, protected narration markers, numbers,
placeholders, and opaque metadata.

From the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m locpipe inventory examples/synthetic/project.toml
python -m locpipe validate examples/synthetic/project.toml --mode baseline
python -m locpipe apply examples/synthetic/project.toml work/CORRECTIONS.jsonl
python -m locpipe validate examples/synthetic/project.toml --mode release
python -m locpipe index examples/synthetic/project.toml
python -m locpipe checksums examples/synthetic/project.toml
```

The correction file repairs one deliberately literal baseline sentence. The
script applies only that authored decision; it does not translate anything.
