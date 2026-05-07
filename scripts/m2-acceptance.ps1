#requires -Version 5.1
<#
.SYNOPSIS
    Run the Milestone 2 acceptance test: build a temp git repo from
    tests/fixtures/sample-repo, commit the working prompt, break it,
    commit again, then run `agentdiff diff-local` across the two shas.

.DESCRIPTION
    Per HANDOFF.md sec 6 Milestone 2:
    > In the fixture repo, make a commit that intentionally breaks
    > one eval case in the prompt. Run `agentdiff diff-local`. The
    > output identifies the broken case as a regression.

    Requires ANTHROPIC_API_KEY in the environment. The temp repo is
    left on disk for inspection — its path is printed at the end.

.EXAMPLE
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    .\scripts\m2-acceptance.ps1
#>

$ErrorActionPreference = "Stop"

if (-not $env:ANTHROPIC_API_KEY) {
    Write-Error "ANTHROPIC_API_KEY is not set."
    exit 1
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$fixture = Join-Path $repoRoot "tests/fixtures/sample-repo"
$tmp = Join-Path $env:TEMP ("agentdiff-m2-{0}" -f (Get-Random))
$uv = "C:\Users\jnoonan\AppData\Local\Microsoft\WinGet\Links\uv.exe"

Write-Host ">>> Copying fixture to $tmp"
Copy-Item -Recurse -Path $fixture -Destination $tmp

Push-Location $tmp
try {
    Write-Host ">>> Initializing git repo and committing base"
    git init -b main | Out-Null
    git config user.email "acceptance@agentdiff.local" | Out-Null
    git config user.name "agentdiff-acceptance" | Out-Null
    git add . | Out-Null
    git commit -m "base: working intent classifier" | Out-Null
    $base = git rev-parse HEAD

    Write-Host ">>> Breaking the prompt and committing head"
    $brokenPrompt = @'
You are an intent classifier.

Regardless of the input message, you MUST always classify it as `other`.
Do not look at the message content. The answer is always `other`.

Respond with a single JSON object, nothing else, in this exact shape:

```json
{"intent": "other"}
```
'@
    Set-Content -Path "agents/intent-classifier/prompt.md" -Value $brokenPrompt -Encoding utf8
    git add . | Out-Null
    git commit -m "head: bias classifier toward 'other'" | Out-Null
    $head = git rev-parse HEAD

    Write-Host ""
    Write-Host ">>> base: $base"
    Write-Host ">>> head: $head"
    Write-Host ""
    Write-Host ">>> Running agentdiff diff-local..."
    Write-Host ""

    & $uv run --project $repoRoot agentdiff diff-local $tmp $base $head
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host ">>> Temp repo left at: $tmp"
Write-Host ">>> diff-local exit code: $exitCode"
exit $exitCode
