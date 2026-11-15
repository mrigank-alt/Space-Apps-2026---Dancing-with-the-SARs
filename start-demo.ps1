$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'SIMULATED demo: http://127.0.0.1:5173/rafsanjan-demo.html'
Write-Host 'No backend or npm installation required. Press Ctrl+C to stop.'
$demoPython = Get-Command python -ErrorAction SilentlyContinue
if ($demoPython) {
    & $demoPython.Source -m http.server 5173 --bind 127.0.0.1 --directory public
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m http.server 5173 --bind 127.0.0.1 --directory public
} else {
    $demoRuntime = Get-AppxPackage -Name 'OpenAI.CodexPrimaryRuntime*' -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty InstallLocation
    if ($demoRuntime) {
        $demoRuntimePython = Join-Path $demoRuntime 'dependencies\python\python.exe'
        if (Test-Path -LiteralPath $demoRuntimePython) {
            & $demoRuntimePython -m http.server 5173 --bind 127.0.0.1 --directory public
        } else {
            throw 'Python 3 is required. Alternatively run pnpm install, then pnpm dev.'
        }
    } else {
        throw 'Python 3 is required. Alternatively run pnpm install, then pnpm dev.'
    }
}
