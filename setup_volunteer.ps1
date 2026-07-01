# Soft Yeti - volunteer setup script (Windows)
# Fully automatic: scans your GPU, installs Ollama + the right model, generates
# an encrypted wallet, and registers with the coordinator. No prompts. Once
# this finishes, the dashboard on/off toggle is the only thing you touch.
#
# Prerequisites (must be installed before running this):
#   - Python 3.11+    https://python.org/downloads
# Ollama is installed automatically below if not already present.

param(
    [string]$CoordinatorUrl = "https://api.soft-yeti.com"
)

$ErrorActionPreference = "Stop"
$Root      = $PSScriptRoot
$ClientDir = Join-Path $Root "client"
$Venv      = Join-Path $Root "client\.venv"
$Python    = Join-Path $Venv "Scripts\python.exe"
$Pip       = Join-Path $Venv "Scripts\pip.exe"

Write-Host ""
Write-Host "=== Soft Yeti Volunteer Setup ===" -ForegroundColor Cyan
Write-Host ""

# -- 1. Python check ----------------------------------------------------------
try {
    $pyVer = (python --version 2>&1).ToString()
    Write-Host "[ok] Python found: $pyVer"
} catch {
    Write-Host "[error] Python not found. Install from https://python.org/downloads" -ForegroundColor Red
    exit 1
}

# -- 2. Ollama check + auto-install -------------------------------------------
function Test-OllamaReachable {
    try {
        $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
        return $true
    } catch {
        return $false
    }
}

if (Test-OllamaReachable) {
    Write-Host "[ok] Ollama is running."
} else {
    Write-Host "[setup] Ollama not detected. Downloading and installing automatically..." -ForegroundColor Yellow
    $OllamaInstaller = Join-Path $env:TEMP "OllamaSetup.exe"
    try {
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $OllamaInstaller -UseBasicParsing
        Write-Host "[setup] Running Ollama installer (silent - this can take a few minutes on first install)..." -NoNewline

        # Don't use -Wait: it gives zero feedback for however long the silent
        # install takes, which reads as "frozen". Poll the process instead so
        # something prints, with a generous timeout rather than blocking forever.
        $proc = Start-Process -FilePath $OllamaInstaller -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -PassThru
        $installTimeoutSec = 300
        $elapsed = 0
        while (-not $proc.HasExited -and $elapsed -lt $installTimeoutSec) {
            Start-Sleep -Seconds 5
            $elapsed += 5
            Write-Host "." -NoNewline
        }
        Write-Host ""
        if (-not $proc.HasExited) {
            Write-Host "[warning] Installer still running after ${installTimeoutSec}s - continuing; it will finish in the background." -ForegroundColor Yellow
        }
        Remove-Item $OllamaInstaller -ErrorAction SilentlyContinue

        $ready = $false
        Write-Host "[setup] Waiting for Ollama to start..." -NoNewline
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 2
            if (Test-OllamaReachable) { $ready = $true; break }
            if ($i % 5 -eq 4) { Write-Host "." -NoNewline }
        }
        Write-Host ""
        if ($ready) {
            Write-Host "[ok] Ollama installed and running."
        } else {
            Write-Host "[warning] Ollama installed but not reachable yet - it may still be starting. Continuing; if mining fails, start Ollama manually and re-run this script." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[warning] Automatic Ollama install failed: $_" -ForegroundColor Yellow
        Write-Host "[warning] Please install manually from https://ollama.com/download and re-run this script." -ForegroundColor Yellow
    }
}

# -- 3. Detect GPU VRAM ---------------------------------------------------------
$DetectedVRAM = 0.0
$DetectedGPU  = "Unknown"

# Try nvidia-smi first
try {
    $nvOut = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null
    if ($nvOut) {
        $parts = $nvOut.Trim().Split(",")
        $DetectedGPU  = $parts[0].Trim()
        $DetectedVRAM = [math]::Round([double]$parts[1].Trim() / 1024, 1)
        Write-Host "[ok] NVIDIA GPU detected: $DetectedGPU ($DetectedVRAM GB VRAM)"
    }
} catch {}

# Try rocm-smi for AMD
if ($DetectedVRAM -eq 0) {
    try {
        $rocOut = & rocm-smi --showmeminfo vram --csv 2>$null | Select-Object -Skip 1 | Select-Object -First 1
        if ($rocOut) {
            # rocm-smi CSV: GPU_ID,VRAM_TOTAL(bytes),VRAM_USED(bytes)
            $parts = $rocOut.Split(",")
            $totalBytes = [double]$parts[1].Trim()
            $DetectedVRAM = [math]::Round($totalBytes / 1GB, 1)
            $DetectedGPU  = "AMD GPU"
            Write-Host "[ok] AMD GPU detected: $DetectedVRAM GB VRAM"
        }
    } catch {}
}

# Registry fallback (works for AMD/Intel/anything without a vendor CLI tool).
# HardwareInformation.qwMemorySize is a 64-bit value written by the driver --
# unlike WMI's Win32_VideoController.AdapterRAM (see below), it doesn't wrap
# around on cards with more than 4GB VRAM.
if ($DetectedVRAM -eq 0) {
    try {
        $classKey = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        $best = 0
        $bestName = $null
        Get-ChildItem -Path $classKey -ErrorAction SilentlyContinue |
            Where-Object { $_.PSChildName -match '^\d{4}$' } |
            ForEach-Object {
                $props = Get-ItemProperty -Path $_.PSPath -ErrorAction SilentlyContinue
                $mem = $props.'HardwareInformation.qwMemorySize'
                if ($mem -and [double]$mem -gt $best) {
                    $best = [double]$mem
                    $bestName = $props.DriverDesc
                }
            }
        if ($best -gt 0) {
            $DetectedVRAM = [math]::Round($best / 1GB, 1)
            $DetectedGPU  = $bestName
            Write-Host "[ok] GPU detected via registry: $DetectedGPU ($DetectedVRAM GB VRAM)"
        }
    } catch {}
}

# Last-resort fallback: WMI AdapterRAM. KNOWN BUG (Windows, not this script):
# AdapterRAM is a 32-bit field and wraps around on GPUs with >4GB VRAM (e.g.
# reports ~4GB on a 16GB card), so this only runs if every method above found
# nothing -- it's better than no number, but the registry method above should
# fire first on any modern driver.
if ($DetectedVRAM -eq 0) {
    try {
        $wmicOut = Get-WmiObject Win32_VideoController | Where-Object { $_.AdapterRAM -gt 0 } | Select-Object -First 1
        if ($wmicOut) {
            $DetectedVRAM = [math]::Round($wmicOut.AdapterRAM / 1GB, 1)
            $DetectedGPU  = $wmicOut.Name
            Write-Host "[warning] GPU VRAM detected via legacy WMI field, which under-reports on GPUs >4GB: $DetectedGPU ($DetectedVRAM GB VRAM reported)" -ForegroundColor Yellow
        }
    } catch {}
}

if ($DetectedVRAM -eq 0) {
    Write-Host "[warning] Could not detect GPU VRAM automatically. Defaulting to the safest small model." -ForegroundColor Yellow
}

# -- 4. Pick model from ladder --------------------------------------------------
# Model ladder (VRAM -> recommended Ollama model):
#   < 4 GB  : qwen2.5:1.5b-instruct    (1.0 GB) - minimal; limited task quality
#   4-6 GB  : phi4-mini                (2.5 GB) - good balance for small VRAM
#   6-10 GB : qwen2.5-coder:7b-instruct(4.7 GB) - default; best coding quality/size
#  10-20 GB : deepseek-coder-v2:16b    (8.9 GB) - MoE: 16B params, 2.4B active per pass
#  20+ GB   : qwen2.5-coder:32b        (19 GB)  - near-frontier quality

if     ($DetectedVRAM -ge 20) { $RecommendedModel = "qwen2.5-coder:32b";         $ModelSize = "19.0 GB" }
elseif ($DetectedVRAM -ge 10) { $RecommendedModel = "deepseek-coder-v2:16b";     $ModelSize = "8.9 GB"  }
elseif ($DetectedVRAM -ge 6)  { $RecommendedModel = "qwen2.5-coder:7b-instruct"; $ModelSize = "4.7 GB"  }
elseif ($DetectedVRAM -ge 4)  { $RecommendedModel = "phi4-mini";                 $ModelSize = "2.5 GB"  }
elseif ($DetectedVRAM -gt 0)  { $RecommendedModel = "qwen2.5:1.5b-instruct";     $ModelSize = "1.0 GB"  }
else                           { $RecommendedModel = "qwen2.5-coder:7b-instruct"; $ModelSize = "4.7 GB"  }

Write-Host ""
Write-Host "Recommended model for your GPU: $RecommendedModel ($ModelSize)" -ForegroundColor Green
Write-Host "  (based on $DetectedVRAM GB detected VRAM)"
Write-Host ""

# -- 5. Pull the inference model (if missing) ----------------------------------
$ModelName = $RecommendedModel
Write-Host "[setup] Ensuring model $ModelName is available..."
try {
    $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
    $modelExists = $tags.models | Where-Object { $_.name -like "$($ModelName.Split(':')[0])*" }
    if ($modelExists) {
        Write-Host "[ok] Model already pulled."
    } else {
        Write-Host "[setup] Pulling $ModelName ($ModelSize - first-time only)..."
        & ollama pull $ModelName
    }
} catch {
    Write-Host "[warning] Could not check/pull model - Ollama may be offline. Pull manually:  ollama pull $ModelName" -ForegroundColor Yellow
}

# -- 6. Create client venv -----------------------------------------------------
if (-not (Test-Path $Python)) {
    Write-Host "[setup] Creating Python venv in client\.venv ..."
    python -m venv $Venv
    Write-Host "[ok] Venv created."
} else {
    Write-Host "[ok] Venv already exists."
}

# -- 7. Install client requirements --------------------------------------------
$Req = Join-Path $ClientDir "requirements.txt"
Write-Host "[setup] Installing client requirements..."
& $Pip install -r $Req --quiet
Write-Host "[ok] Requirements installed."

# -- 8. Run setup wizard --------------------------------------------------------
Write-Host ""
Write-Host "=== Wallet + registration setup (automatic) ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Coordinator: $CoordinatorUrl"
Write-Host "Model:       $ModelName ($ModelSize)"
Write-Host "GPU:         $DetectedGPU ($DetectedVRAM GB VRAM)"
Write-Host ""
Write-Host "A wallet is generated and encrypted automatically - Windows protects the"
Write-Host "key for your account, so there's nothing for you to remember or type."
Write-Host ""

# Pass detected values as env vars so setup is fully non-interactive
$env:YETI_COORDINATOR_URL = $CoordinatorUrl
$env:YETI_DETECTED_VRAM   = "$DetectedVRAM"
$env:YETI_DETECTED_MODEL  = $ModelName
$env:YETI_DETECTED_GPU    = $DetectedGPU

Push-Location $ClientDir
try {
    & $Python yeti_client.py --setup
} finally {
    Pop-Location
    $env:YETI_COORDINATOR_URL = $null
    $env:YETI_DETECTED_VRAM   = $null
    $env:YETI_DETECTED_MODEL  = $null
    $env:YETI_DETECTED_GPU    = $null
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "GPU:   $DetectedGPU ($DetectedVRAM GB VRAM)"
Write-Host "Model: $ModelName ($ModelSize)"
Write-Host ""

# -- 9. Start dashboard ---------------------------------------------------------
Write-Host "[setup] Starting Soft Yeti dashboard at http://localhost:8901 ..."
$DashScript = Join-Path $ClientDir "dashboard.py"
Start-Process -FilePath $Python -ArgumentList $DashScript -WindowStyle Minimized

# -- 10. Create desktop shortcut -------------------------------------------------
try {
    $DesktopUrl = Join-Path ([Environment]::GetFolderPath("Desktop")) "Soft Yeti.url"
    $ShortcutContent = "[InternetShortcut]`r`nURL=http://localhost:8901`r`nIconIndex=0"
    Set-Content -Path $DesktopUrl -Value $ShortcutContent -Encoding UTF8
    Write-Host "[ok] Desktop shortcut created: Soft Yeti.url"
} catch {
    Write-Host "[warning] Could not create desktop shortcut: $_" -ForegroundColor Yellow
}

# -- 11. Open dashboard in browser -----------------------------------------------
Write-Host "[setup] Opening dashboard in browser..."
Start-Sleep -Seconds 3
Start-Process "http://localhost:8901"

Write-Host ""
Write-Host "Your dashboard is running at http://localhost:8901" -ForegroundColor Cyan
Write-Host "Use the toggle on the card to start and stop mining." -ForegroundColor Cyan
Write-Host ""
Write-Host "Note: if the coordinator restarts, re-run setup to get a new API key"
Write-Host "      (your wallet and volunteer ID are preserved)."
Write-Host ""
