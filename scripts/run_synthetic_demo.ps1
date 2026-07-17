param(
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $root 'src'
$config = Join-Path $root 'examples\synthetic\project.toml'

& $Python -m locpipe inventory $config
if ($LASTEXITCODE -ne 0) { throw 'Inventory failed' }
& $Python -m locpipe validate $config --mode baseline
if ($LASTEXITCODE -ne 0) { throw 'Baseline validation failed' }
& $Python -m locpipe apply $config 'work\CORRECTIONS.jsonl'
if ($LASTEXITCODE -ne 0) { throw 'Correction application failed' }
& $Python -m locpipe validate $config --mode release
if ($LASTEXITCODE -ne 0) { throw 'Release validation failed' }
& $Python -m locpipe index $config
if ($LASTEXITCODE -ne 0) { throw 'Index generation failed' }
& $Python -m locpipe checksums $config
if ($LASTEXITCODE -ne 0) { throw 'Checksum generation failed' }

Write-Host 'Synthetic localization pipeline: PASS' -ForegroundColor Green
