# Hourly navmap updater (run by Windows Task Scheduler).
# 1. Import game data from the local Discovery Freelancer install
# 2. Rebuild docs/ (fetches fresh PoBs from the Discovery GC API)
# 3. Commit + push data/ and docs/ so GitHub Pages updates

$repo = 'C:\Users\Slimy\Documents\DiscoNavmap workspace\DiscoNavmap'
$log  = 'C:\Users\Slimy\Documents\DiscoNavmap workspace\navmap_update.log'
$python = 'C:\Program Files\Python314\python.exe'
$git = 'C:\Program Files\Git\cmd\git.exe'

Set-Location $repo

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

Log '=== update start ==='

# 1. Game data import (non-fatal: keep building from last good data if it fails)
& $python -m cmd_py.update -out data/v5.3p2h5 2>&1 | ForEach-Object { Log "import: $_" }
if ($LASTEXITCODE -ne 0) { Log "import FAILED (exit $LASTEXITCODE) - continuing with existing data" }

# 2. Static build (fresh PoBs)
& $python build.py 2>&1 | ForEach-Object { Log "build: $_" }
if ($LASTEXITCODE -ne 0) { Log "build FAILED (exit $LASTEXITCODE) - skipping commit"; Log '=== update end ==='; exit 1 }

# 3. Commit + push if anything changed
& $git add -A data docs 2>&1 | ForEach-Object { Log "git: $_" }
& $git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Log 'no changes to commit'
} else {
    & $git commit -m "Hourly navmap update $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | ForEach-Object { Log "git: $_" }
    & $git push origin main 2>&1 | ForEach-Object { Log "git: $_" }
    if ($LASTEXITCODE -ne 0) { Log "push FAILED (exit $LASTEXITCODE)" } else { Log 'pushed to GitHub' }
}

Log '=== update end ==='
