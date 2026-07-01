# Soft Yeti coordinator - SECONDARY node (3060 Ti)
# Run this on the 3060 Ti when the primary (9070 XT) coordinator is down.
# Requires: synced coordinator.key + yeti-chain.jsonl from the primary via Syncthing.
#
# Syncthing sync required (add to jclaw-training or a dedicated folder):
#   FROM  9070 XT:  <soft-yeti-root>\coordinator\coordinator.key
#   FROM  9070 XT:  <soft-yeti-root>\coordinator\coordinator.pub
#   FROM  9070 XT:  <soft-yeti-root>\coordinator\yeti-chain.jsonl
#   TO    3060 Ti:  any local path (set SYNC_DIR below or pass as arg)
#
# Usage:
#   .\start_coordinator_secondary.ps1                      # uses default SYNC_DIR
#   .\start_coordinator_secondary.ps1 -SyncDir "C:\yetiSync"
#
# After starting: update the Cloudflare Tunnel config on THIS machine to serve
#   api.soft-yeti.com -> http://localhost:8900
# OR use the Tailscale IP of this machine in J-Claw's YETI_COORDINATOR_FALLBACK_URL.
#
# IMPORTANT: Do NOT run the secondary while the primary is healthy - split-brain will
# corrupt the chain if both coordinators accept blocks simultaneously.

param(
    [string]$SyncDir = "$env:USERPROFILE\yetiSync"
)

$ErrorActionPreference = "Stop"
$Root     = $PSScriptRoot
$CoordDir = Join-Path $Root "coordinator"
$Venv     = Join-Path $Root ".venv"
$Python   = Join-Path $Venv "Scripts\python.exe"
$Pip      = Join-Path $Venv "Scripts\pip.exe"

Write-Host ""
Write-Host "=== Soft Yeti SECONDARY coordinator (3060 Ti failover) ==="
Write-Host ""

# -- 0. Locate synced key and chain from primary -------------------------------
# Prefer synced copies in SyncDir; fall back to coordinator/ (if already present)
$KeySrc   = if (Test-Path "$SyncDir\coordinator.key") { "$SyncDir\coordinator.key" }
            elseif (Test-Path "$CoordDir\coordinator.key") { "$CoordDir\coordinator.key" }
            else { $null }
$PubSrc   = if (Test-Path "$SyncDir\coordinator.pub") { "$SyncDir\coordinator.pub" }
            elseif (Test-Path "$CoordDir\coordinator.pub") { "$CoordDir\coordinator.pub" }
            else { $null }
$ChainSrc = if (Test-Path "$SyncDir\yeti-chain.jsonl") { "$SyncDir\yeti-chain.jsonl" }
            elseif (Test-Path "$CoordDir\yeti-chain.jsonl") { "$CoordDir\yeti-chain.jsonl" }
            else { $null }

if (-not $KeySrc) {
    Write-Error @"
coordinator.key not found.
Sync it from the primary (9070 XT) via Syncthing or copy it manually:
  Primary path: <soft-yeti-root>\coordinator\coordinator.key
  Sync target:  $SyncDir\coordinator.key
"@
    exit 1
}
Write-Host "[key]   $KeySrc"
if ($ChainSrc) {
    Write-Host "[chain] $ChainSrc"
} else {
    Write-Host "[chain] No synced chain found - starting fresh (will re-sync on primary restart)"
}

# -- 1. Copy synced files into coordinator/ (coordinator reads from $CoordDir) --
$KeyDst   = Join-Path $CoordDir "coordinator.key"
$PubDst   = Join-Path $CoordDir "coordinator.pub"
$ChainDst = Join-Path $CoordDir "yeti-chain.jsonl"

if ($KeySrc -ne $KeyDst)   { Copy-Item $KeySrc   $KeyDst   -Force; Write-Host "[copied] coordinator.key" }
if ($PubSrc -and $PubSrc -ne $PubDst) { Copy-Item $PubSrc $PubDst -Force; Write-Host "[copied] coordinator.pub" }
if ($ChainSrc -and $ChainSrc -ne $ChainDst) {
    Copy-Item $ChainSrc $ChainDst -Force
    $lineCount = (Get-Content $ChainDst | Measure-Object -Line).Lines
    Write-Host "[copied] yeti-chain.jsonl ($lineCount blocks)"
}

# -- 2. Venv -------------------------------------------------------------------
if (-not (Test-Path $Python)) {
    Write-Host "[setup] Creating .venv..."
    python -m venv $Venv
}

# -- 3. Install requirements ---------------------------------------------------
$Req = Join-Path $CoordDir "requirements.txt"
if (Test-Path $Req) {
    Write-Host "[setup] Installing coordinator requirements..."
    & $Pip install -r $Req --quiet
}

# -- 4. Write .env if absent (inherits primary's CHAIN_ID + key paths) ---------
$EnvFile = Join-Path $CoordDir ".env.secondary"
$EnvLink = Join-Path $CoordDir ".env"

$TreasuryAddr = "YETI1treasury"
$TreasuryFile = Join-Path $CoordDir "treasury_wallet.json"
if (Test-Path $TreasuryFile) {
    try { $TreasuryAddr = (Get-Content $TreasuryFile -Raw | ConvertFrom-Json).address } catch {}
}

if (-not (Test-Path $EnvFile)) {
    Write-Host "[setup] Writing .env.secondary..."
    @"
# Soft Yeti Coordinator - SECONDARY (3060 Ti failover)
# Uses the SAME coordinator.key + CHAIN_ID as the primary to produce valid signed blocks.
COORDINATOR_ED25519_KEY_PATH=$CoordDir\coordinator.key
COORDINATOR_ED25519_PUBLIC_KEY_PATH=$CoordDir\coordinator.pub
COORDINATOR_ED25519_KEY_PASS=

DIFFICULTY_TARGET=0000
CHAIN_ID=yeti-testnet
CHAIN_STORE_PATH=$CoordDir\yeti-chain.jsonl
DB_PATH=$CoordDir\coordinator.db

API_KEY_HEADER=X-Yeti-API-Key
GENERATE_TIMEOUT_S=900

TREASURY_WALLET=$TreasuryAddr
REWARD_RATE=0.001
BASE_RATE=0.0001
TREASURY_FEE=0.1
CANARY_RATE=0.05
"@ | Set-Content $EnvFile -Encoding UTF8
}

# Back up the primary .env (if any) and replace with secondary one for this run.
$PrimaryEnv = Join-Path $CoordDir ".env"
$PrimaryEnvBak = Join-Path $CoordDir ".env.primary.bak"
if ((Test-Path $PrimaryEnv) -and -not (Test-Path $PrimaryEnvBak)) {
    Copy-Item $PrimaryEnv $PrimaryEnvBak -Force
    Write-Host "[env]   Backed up primary .env to .env.primary.bak"
}
Copy-Item $EnvFile $PrimaryEnv -Force
Write-Host "[env]   Using secondary .env"

# -- 5. Start secondary coordinator --------------------------------------------
Write-Host ""
Write-Host "Starting SECONDARY coordinator on http://0.0.0.0:8900 ..."
Write-Host "  This machine's Tailscale IP: $(try { (Get-NetIPAddress -InterfaceAlias *tailscale* -AddressFamily IPv4 -ErrorAction Stop).IPAddress } catch { 'unknown' })"
Write-Host "  Set in J-Claw: YETI_COORDINATOR_FALLBACK_URL=http://<this-IP>:8900"
Write-Host "  Or update Cloudflare Tunnel to route api.soft-yeti.com here."
Write-Host "  Ctrl+C to stop.  Restore primary: Copy-Item '$PrimaryEnvBak' '$PrimaryEnv' -Force"
Write-Host ""

Push-Location $Root
try {
    & $Python -m uvicorn coordinator.main:app --host 0.0.0.0 --port 8900 --log-level info
} finally {
    # Restore primary .env on exit (in case this terminal is reused)
    if (Test-Path $PrimaryEnvBak) {
        Copy-Item $PrimaryEnvBak $PrimaryEnv -Force
        Write-Host "[restored] primary .env"
    }
    Pop-Location
}
