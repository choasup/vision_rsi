Set-Location -LiteralPath $PSScriptRoot
if (-not $env:DEEPSEEK_API_KEY) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
}
$agentPython = $env:VISION_RSI_PYTHON
if ($agentPython -and -not (Test-Path -LiteralPath $agentPython -PathType Leaf)) {
    throw 'VISION_RSI_PYTHON must name an existing Python executable.'
}
if (-not $agentPython) {
    $agentPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $agentPython)) {
        $agentPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (-not (Test-Path -LiteralPath $agentPython)) { $agentPython = 'python' }
    }
}
& $agentPython -X utf8 -m vision_rsi serve --config config.local.json --run-dir runs/app --port 8767
