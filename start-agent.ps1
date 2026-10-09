Set-Location -LiteralPath $PSScriptRoot
if (-not $env:DEEPSEEK_API_KEY) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
}
$agentPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $agentPython)) { $agentPython = 'python' }
& $agentPython -m vision_rsi serve --config config.local.json --run-dir runs/app --port 8767
