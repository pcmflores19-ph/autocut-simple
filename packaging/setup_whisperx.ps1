# Sets up WhisperX for Wavefield.
#
# Wavefield cuts and mixes on its own; WhisperX is what turns the audio into a
# transcript. It cannot be bundled into the installer: with PyTorch it is
# several gigabytes, and the right build depends on whether the machine has an
# NVIDIA GPU. So it is installed here instead, into its own virtual
# environment, and the path is written into Wavefield's settings so the app
# finds it without anyone typing a path.
#
# Run by the installer, and again from Wavefield's Settings window if it is
# ever needed a second time. Safe to re-run.

$ErrorActionPreference = "Stop"
$envDir      = Join-Path $env:LOCALAPPDATA "Wavefield\whisperx-env"
$settingsDir = Join-Path $env:APPDATA "AutoCut"
$settings    = Join-Path $settingsDir "settings.json"

function Say($text)  { Write-Host $text }
function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }

Say ""
Say "  Setting up speech recognition for Wavefield"
Say "  ==========================================="
Say ""
Say "  This downloads about 2-3 GB and usually takes 5-15 minutes."
Say "  You only ever have to do this once."
Say ""

# ---------------------------------------------------------------- find Python
Step "Looking for Python"

# WhisperX needs 3.9-3.12; 3.13 has no PyTorch wheels yet, so a machine with
# only 3.13 would fail deep inside pip with nothing useful to read.
function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("3.12", "3.11", "3.10", "3.9")) {
            $candidates += ,@("py", @("-$v"))
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += ,@("python", @())
    }
    foreach ($c in $candidates) {
        try {
            $out = & $c[0] @($c[1] + @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")) 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $parts = $out.Trim().Split(".")
                $major = [int]$parts[0]; $minor = [int]$parts[1]
                if ($major -eq 3 -and $minor -ge 9 -and $minor -le 12) {
                    return @{ Exe = $c[0]; Args = $c[1]; Version = $out.Trim() }
                }
            }
        } catch { }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Say ""
    Say "  Python 3.9-3.12 was not found on this computer." -ForegroundColor Yellow
    Say ""
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Say "  It can be installed now, automatically."
        $answer = Read-Host "  Install Python 3.12? [Y/n]"
        if ($answer -eq "" -or $answer -match "^[Yy]") {
            Step "Installing Python 3.12"
            winget install --id Python.Python.3.12 --scope user `
                   --accept-package-agreements --accept-source-agreements
            # winget puts it on the PATH only for new processes, so look again
            # in this one before giving up.
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                        [Environment]::GetEnvironmentVariable("Path", "Machine")
            $python = Find-Python
        }
    }
    if (-not $python) {
        Say ""
        Say "  Install Python 3.12 from https://www.python.org/downloads/" -ForegroundColor Yellow
        Say "  Tick 'Add python.exe to PATH' during setup, then run this again"
        Say "  from Wavefield: File > Settings > Install WhisperX."
        Say ""
        Read-Host "  Press Enter to close"
        exit 1
    }
}
Say "  Found Python $($python.Version)"

# ------------------------------------------------------------- NVIDIA or not
Step "Checking for an NVIDIA graphics card"
$hasNvidia = $false
try {
    $null = & nvidia-smi 2>$null
    if ($LASTEXITCODE -eq 0) { $hasNvidia = $true }
} catch { }
if ($hasNvidia) {
    Say "  NVIDIA GPU found - installing the GPU build (transcribes much faster)"
} else {
    Say "  No NVIDIA GPU - installing the CPU build (slower, but works everywhere)"
}

# ------------------------------------------------------------ the environment
Step "Creating the WhisperX environment"
Say "  $envDir"
if (Test-Path $envDir) {
    Say "  (already there - reusing it)"
} else {
    & $python.Exe @($python.Args + @("-m", "venv", $envDir))
    if ($LASTEXITCODE -ne 0) { throw "could not create the environment" }
}
$venvPy = Join-Path $envDir "Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "the environment is missing $venvPy" }

& $venvPy -m pip install --upgrade pip --quiet

# PyTorch first and explicitly: installed as a dependency of whisperx it comes
# from PyPI, which on Windows is the CPU build - so a machine with a perfectly
# good NVIDIA card would silently transcribe on the CPU, several times slower.
Step "Installing PyTorch (the big one)"
if ($hasNvidia) {
    & $venvPy -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
} else {
    & $venvPy -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
}
if ($LASTEXITCODE -ne 0) { throw "PyTorch failed to install" }

Step "Installing WhisperX"
& $venvPy -m pip install whisperx
if ($LASTEXITCODE -ne 0) { throw "WhisperX failed to install" }

# ------------------------------------------------------------------- register
Step "Telling Wavefield where it is"
$whisperx = Join-Path $envDir "Scripts\whisperx.exe"
if (-not (Test-Path $whisperx)) { throw "whisperx.exe was not created" }

if (-not (Test-Path $settingsDir)) { New-Item -ItemType Directory -Path $settingsDir | Out-Null }
$data = @{}
if (Test-Path $settings) {
    try {
        $existing = Get-Content $settings -Raw | ConvertFrom-Json
        foreach ($p in $existing.PSObject.Properties) { $data[$p.Name] = $p.Value }
    } catch { }      # a corrupt settings file is not worth failing over
}
$data["whisperx_path"] = $whisperx
$data | ConvertTo-Json | Set-Content $settings -Encoding utf8
Say "  $settings"

# --------------------------------------------------------------------- verify
Step "Checking it works"
$cuda = & $venvPy -c "import torch; print(torch.cuda.is_available())" 2>$null
Say "  whisperx : $whisperx"
Say "  GPU ready: $cuda"

Say ""
Say "  Done. Wavefield will transcribe automatically after you press Analyze." -ForegroundColor Green
Say ""
Read-Host "  Press Enter to close"
