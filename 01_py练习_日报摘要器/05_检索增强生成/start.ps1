param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3001,
    [string]$Python = "python",
    [switch]$SkipDocker,
    [switch]$VisibleWindows
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$LogDir = Join-Path $Root "output\logs"
$PidDir = Join-Path $Root "output\pids"

New-Item -ItemType Directory -Force -Path $LogDir, $PidDir | Out-Null

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        Write-Host "Config file not found: $Path"
        return
    }

    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        if ($line.StartsWith("export ")) {
            $line = $line.Substring(7).Trim()
        }
        $index = $line.IndexOf("=")
        if ($index -lt 1) {
            return
        }

        $name = $line.Substring(0, $index).Trim()
        $value = $line.Substring($index + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

function Test-PortOpen {
    param([int]$Port)

    $client = New-Object Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    $stdout = Join-Path $LogDir "$Name.log"
    $stderr = Join-Path $LogDir "$Name.err.log"
    $windowStyle = if ($VisibleWindows) { "Normal" } else { "Hidden" }

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle $windowStyle `
        -PassThru

    Set-Content -LiteralPath (Join-Path $PidDir "$Name.pid") -Value $process.Id -Encoding ASCII
    Write-Host "$Name started. PID=$($process.Id)"
    Write-Host "  stdout: $stdout"
    Write-Host "  stderr: $stderr"
}

function Clear-FrontendCache {
    $target = Resolve-Path -LiteralPath (Join-Path $Root "frontend\.next") -ErrorAction SilentlyContinue
    if (-not $target) {
        return
    }

    $frontendRoot = (Resolve-Path -LiteralPath (Join-Path $Root "frontend")).Path
    if (-not $target.Path.StartsWith($frontendRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refuse to remove path outside frontend: $($target.Path)"
    }

    Remove-Item -LiteralPath $target.Path -Recurse -Force
    Write-Host "Removed frontend dev cache: $($target.Path)"
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$Seconds = 20
    )

    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

Set-Location $Root
Import-DotEnv (Join-Path $Root "backend\.env")

if (-not $SkipDocker) {
    Write-Host "Starting Docker services..."
    docker compose up -d
}

if (-not (Test-Path $Python)) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        throw "Python not found. Pass -Python <python.exe path>."
    }
    $Python = $pythonCmd.Source
}

if (Test-PortOpen $BackendPort) {
    Write-Host "Backend port $BackendPort is already in use. Skip backend startup."
} else {
    Start-LoggedProcess `
        -Name "backend" `
        -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
        -WorkingDirectory $Root
}

$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
}
if (-not $npmCmd) {
    throw "npm not found. Install Node.js or add npm to PATH."
}

if (Test-PortOpen $FrontendPort) {
    Write-Host "Frontend port $FrontendPort is already in use. Skip frontend startup."
} else {
    Clear-FrontendCache
    Start-LoggedProcess `
        -Name "frontend" `
        -FilePath $npmCmd.Source `
        -ArgumentList @("run", "dev", "--", "-p", "$FrontendPort") `
        -WorkingDirectory (Join-Path $Root "frontend")
}

$backendUrl = "http://127.0.0.1:$BackendPort/api/health"
$frontendUrl = "http://127.0.0.1:$FrontendPort"

Write-Host ""
Write-Host "Checking services..."
if (Wait-HttpOk $backendUrl 20) {
    Write-Host "Backend OK:  $backendUrl"
} else {
    Write-Host "Backend not ready yet. Check output\logs\backend.err.log"
}

if (Test-PortOpen $FrontendPort) {
    Write-Host "Frontend OK: $frontendUrl"
} else {
    Write-Host "Frontend not ready yet. Check output\logs\frontend.err.log"
}

Write-Host ""
Write-Host "Done."
Write-Host "Run with visible server windows:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\start.ps1 -VisibleWindows"
