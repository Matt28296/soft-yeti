# Soft Yeti coordinator startup script - Phase 0 testbed
# Run from: soft-yeti/   (this directory)
# Coordinator package lives in: soft-yeti/coordinator/ (run uvicorn from soft-yeti/ so Python finds it)

$ErrorActionPreference = "Stop"
$Root    = $PSScriptRoot                          # soft-yeti/
$CoordDir = Join-Path $Root "coordinator"         # soft-yeti/coordinator/
$Venv    = Join-Path $Root ".venv"
$Python  = Join-Path $Venv "Scripts\python.exe"
$Pip     = Join-Path $Venv "Scripts\pip.exe"

# -- 1. Venv ------------------------------------------------------------------
if (-not (Test-Path $Python)) {
    Write-Host "[setup] Creating .venv..."
    python -m venv $Venv
}

# -- 2. Install coordinator requirements --------------------------------------
$Req = Join-Path $CoordDir "requirements.txt"
if (Test-Path $Req) {
    Write-Host "[setup] Installing coordinator requirements..."
    & $Pip install -r $Req --quiet
} else {
    Write-Warning "requirements.txt not found at $Req - skipping pip install"
}

# -- 3. Generate Ed25519 keypair (PEM, no passphrase - Phase 0 testbed) -------
$KeyPath = Join-Path $CoordDir "coordinator.key"
$PubPath = Join-Path $CoordDir "coordinator.pub"

if (-not (Test-Path $KeyPath)) {
    Write-Host "[setup] Generating Ed25519 coordinator keypair..."
    # Write keygen script to temp file (stdin here-string hangs in background shells)
    $keygenScript = Join-Path $env:TEMP "yeti_keygen.py"
    @"
import sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, PublicFormat, NoEncryption
)

coord_dir = Path(sys.argv[1])
priv = Ed25519PrivateKey.generate()
pub  = priv.public_key()

key_path = coord_dir / "coordinator.key"
pub_path = coord_dir / "coordinator.pub"

key_path.write_bytes(priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
pub_path.write_bytes(pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
print(f"  coordinator.key -> {key_path}")
print(f"  coordinator.pub -> {pub_path}")
"@ | Set-Content $keygenScript -Encoding utf8
    & $Python $keygenScript $CoordDir
    Remove-Item $keygenScript -Force -ErrorAction SilentlyContinue
    Write-Host "[setup] Keypair written."
} else {
    Write-Host "[setup] Keypair already exists - skipping."
}

# -- 4. Generate treasury wallet (YETI1... address) ---------------------------
$TreasuryFile = Join-Path $CoordDir "treasury_wallet.json"

if (-not (Test-Path $TreasuryFile)) {
    Write-Host "[setup] Generating treasury wallet..."
    # Write treasury script to temp file (stdin here-string hangs in background shells)
    $treasuryScript = Join-Path $env:TEMP "yeti_treasury.py"
    @"
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])   # add soft-yeti/ to path
from chain.wallet import generate_wallet
import json
w = generate_wallet()
out = Path(sys.argv[1]) / "coordinator" / "treasury_wallet.json"
json.dump({"address": w["address"], "pubkey": w["pubkey"]}, open(out, "w"), indent=2)
print(w["address"])
"@ | Set-Content $treasuryScript -Encoding utf8
    $TreasuryAddr = & $Python $treasuryScript $Root
    Remove-Item $treasuryScript -Force -ErrorAction SilentlyContinue
    Write-Host "[setup] Treasury wallet: $TreasuryAddr"
} else {
    $TreasuryAddr = (Get-Content $TreasuryFile -Raw | ConvertFrom-Json).address
    Write-Host "[setup] Treasury wallet already exists: $TreasuryAddr"
}

# -- 5. Write .env (Phase 0 defaults - edit to tune) --------------------------
$EnvFile = Join-Path $CoordDir ".env"

if (-not (Test-Path $EnvFile)) {
    Write-Host "[setup] Writing .env with Phase 0 defaults..."
    # Use absolute paths - pydantic-settings resolves relative paths against CWD, not the package dir
    $envContent = @"
# Soft Yeti Coordinator - Phase 0 testbed
COORDINATOR_ED25519_KEY_PATH=$CoordDir\coordinator.key
COORDINATOR_ED25519_PUBLIC_KEY_PATH=$CoordDir\coordinator.pub
COORDINATOR_ED25519_KEY_PASS=

# Phase 0: empty = always passes on first attempt. Restore "0" after mechanics confirmed.
DIFFICULTY_TARGET=

CHAIN_ID=yeti-testnet
CHAIN_STORE_PATH=$CoordDir\yeti-chain.jsonl
DB_PATH=$CoordDir\coordinator.db
API_KEY_HEADER=X-Yeti-API-Key
GENERATE_TIMEOUT_S=900

TREASURY_WALLET=$TreasuryAddr
REWARD_RATE=0.001
TREASURY_FEE=0.1
CANARY_RATE=0.05
"@
    $envContent | Set-Content $EnvFile -Encoding UTF8

    Write-Host "[setup] .env written."
} else {
    Write-Host "[setup] .env already exists - skipping."
}

# -- 6. Start coordinator ------------------------------------------------------
Write-Host ""
Write-Host "Starting Soft Yeti coordinator on http://0.0.0.0:8900 ..."
Write-Host "  Chain ID   : yeti-testnet"
Write-Host "  Difficulty : 0 (single leading hex zero)"
Write-Host "  Treasury   : $TreasuryAddr"
Write-Host "  Logs       : uvicorn stdout (Ctrl+C to stop)"
Write-Host ""

Push-Location $Root
try {
    & $Python -m uvicorn coordinator.main:app --host 0.0.0.0 --port 8900 --log-level info
} finally {
    Pop-Location
}
