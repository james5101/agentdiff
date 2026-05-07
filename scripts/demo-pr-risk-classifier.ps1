#requires -Version 5.1
<#
.SYNOPSIS
    End-to-end demo of agentdiff against the PR risk classifier example.

.DESCRIPTION
    Copies examples/pr-risk-classifier to a temp git repo, commits the
    working prompt as base, applies a deliberately-bad prompt change
    (loosens the dep-CVE-history rule to only trigger on major-version
    bumps), commits as head, then runs `agentdiff diff-local`.

    The bad change should regress at least the deps-cve-history-001
    case: lodash patch upgrades will newly classify as
    `requires_security_review=false`, which the judge rubric flags
    as wrong.

    Requires ANTHROPIC_API_KEY in the environment. The temp repo is
    left on disk for inspection.

.EXAMPLE
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    .\scripts\demo-pr-risk-classifier.ps1
#>

$ErrorActionPreference = "Stop"

if (-not $env:ANTHROPIC_API_KEY) {
    Write-Error "ANTHROPIC_API_KEY is not set."
    exit 1
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$source = Join-Path $repoRoot "examples/pr-risk-classifier"
$tmp = Join-Path $env:TEMP ("agentdiff-pr-risk-{0}" -f (Get-Random))
$uv = "C:\Users\jnoonan\AppData\Local\Microsoft\WinGet\Links\uv.exe"
$promptPath = "agents/pr-risk-classifier/prompt.md"

Write-Host ">>> Copying example to $tmp"
Copy-Item -Recurse -Path $source -Destination $tmp

Push-Location $tmp
try {
    Write-Host ">>> Initializing git repo and committing base"
    git init -b main | Out-Null
    git config user.email "demo@agentdiff.local" | Out-Null
    git config user.name "agentdiff-demo" | Out-Null
    git add . | Out-Null
    git commit -m "base: production-quality PR risk classifier" | Out-Null
    $base = git rev-parse HEAD

    Write-Host ">>> Applying a bad prompt change (loosens dep-CVE rule)"
    # Realistic regression: an engineer "simplifies" the rules to reduce
    # false positives, but accidentally drops the CVE-history rule and
    # only flags major-version bumps for review. Lodash patch upgrades
    # used to require review (CVE history) - now they don't.
    $badPrompt = @'
You classify pull requests for routing by security risk.

Given a PR's title, list of changed files, and unified diff, respond with
ONLY a JSON object - no preamble, no markdown fences, no trailing text -
with three fields:

- `risk`: one of "critical", "high", "medium", "low"
- `requires_security_review`: boolean
- `reasoning`: one short sentence citing the specific file or pattern that
  drove the call

## Risk classification

- **critical**: Changes to auth flows, crypto primitives, secret rotation
  logic, signature/MAC algorithms.
- **high**: Changes to authz checks, IAM policies, network ACLs, RBAC rules.
- **medium**: Dependency upgrades (any version bump), build pipeline
  changes, CI/CD changes that affect what gets deployed.
- **low**: Docs, tests, refactors with no behavior change, comment-only
  edits.

## Security review requirement

`requires_security_review` is `true` when the change touches:

- Authentication, authorization, or session management
- Cryptography or secret handling
- IAM, RBAC, or network policy
- Major-version dependency upgrades (e.g., 3.x to 4.x)

`requires_security_review` is `false` for everything else, including
minor and patch dependency upgrades.
'@
    Set-Content -Path $promptPath -Value $badPrompt -Encoding utf8
    git add . | Out-Null
    git commit -m "head: simplify review rules - only flag major bumps" | Out-Null
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
