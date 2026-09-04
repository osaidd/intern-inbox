# intern-inbox bootstrap (Windows) — one paste from PowerShell to a running app.
#   irm https://raw.githubusercontent.com/osaidd/intern-inbox/main/bootstrap.ps1 | iex
$ErrorActionPreference = "Stop"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host "git is missing. Install it first:  winget install --id Git.Git -e"
  Write-Host "Then close this window, open a new PowerShell, and paste the command again."
  return
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "Installing uv (the Python tool this project uses)..."
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$HOME\.local\bin;$env:Path"
}

$dir = Join-Path $HOME "intern-inbox"
if (Test-Path (Join-Path $dir ".git")) {
  Write-Host "Already cloned at $dir - pulling updates."
  git -C $dir pull --ff-only
  if ($LASTEXITCODE -ne 0) {
    Write-Host "git pull failed - check your internet connection and try again."
    return
  }
} else {
  git clone https://github.com/osaidd/intern-inbox.git $dir
  if ($LASTEXITCODE -ne 0) {
    Write-Host "git clone failed - check your internet connection and try again."
    return
  }
}

Set-Location $dir
Write-Host "Installing dependencies (well under a minute on a normal connection)..."
uv sync
if ($LASTEXITCODE -ne 0) {
  Write-Host "Dependency install failed - re-run this command; if it keeps failing, paste the output to Claude or open a GitHub issue."
  return
}

# Claude Code is optional depth, not the default path - ask, never hijack.
$useClaude = $false
if (Get-Command claude -ErrorAction SilentlyContinue) {
  $ans = Read-Host "Found Claude Code. Open the project there for guided setup instead of the browser app? [y/N]"
  if ($ans -match '^[Yy]') { $useClaude = $true }
}
if ($useClaude) {
  Write-Host ""
  Write-Host "Opening in Claude Code - type /setup when it loads."
  claude
} else {
  Write-Host ""
  Write-Host "Starting Intern Inbox - your browser will open with a 3-step setup."
  Write-Host "To stop: Ctrl+C.  To start again later:  cd $dir; uv run intern-inbox --open"
  uv run intern-inbox --open
}
