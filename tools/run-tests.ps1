param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $TestArguments
)

$ErrorActionPreference = 'Stop'

$repoRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$scratchRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot '.test-tmp'))
$runDirectory = Join-Path $scratchRoot ("run-{0}" -f [guid]::NewGuid().ToString('N'))

New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:TEMP = $runDirectory
$env:TMP = $runDirectory
$env:TMPDIR = $runDirectory
$env:GIT_CEILING_DIRECTORIES = $scratchRoot

$exitCode = 1
Push-Location -LiteralPath $repoRoot
try {
    if ($TestArguments.Count -eq 0) {
        & python -X utf8 -m unittest discover -s tests
    }
    else {
        & python -X utf8 -m unittest @TestArguments
    }
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    try {
        [System.IO.Directory]::Delete($runDirectory, $false)
    }
    catch {
        # A failed test may leave diagnostic files. They stay in the ignored scratch root.
    }
    try {
        [System.IO.Directory]::Delete($scratchRoot, $false)
    }
    catch {
        # Other or failed test runs may still be present.
    }
}

exit $exitCode
