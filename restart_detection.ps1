param(
    [string]$PhoneIp = "192.168.178.22",
    [string]$LmStudioBaseUrl = "http://localhost:1234/v1",
    [string]$Model = "qwen3.6-35b-a3b@q4_k_xl",
    [string]$RtspUrl = "rtsp://Daniel:Webdev20!@192.168.178.34/stream1",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$LogFile = Join-Path $ScriptDir "benchmark\live_detect.log"
$ErrorLogFile = Join-Path $ScriptDir "benchmark\live_detect.err.log"

if ([string]::IsNullOrWhiteSpace($Python)) {
    $VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $Python = $VenvPython
    } else {
        $Python = "python"
    }
}

if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python executable not found: $Python"
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "ffmpeg is not on PATH. Install ffmpeg before using deterrence AV recording."
}

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'benchmark[\\/]+live_detect\.py' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

$Arguments = @(
    "-u",
    "benchmark\live_detect.py",
    "--backend", "windows",
    "--base-url", $LmStudioBaseUrl,
    "--model", $Model,
    "--rtsp-url", $RtspUrl,
    "--no-think",
    "--preset-cycle", "1,2",
    "--preset-dwell", "55",
    "--vlm-max-size", "1440x810",
    "--alert-url", "http://$PhoneIp`:8765/bird",
    "--alert-cooldown", "60",
    "--deterrence-record-video", "on",
    "--deterrence-frame-size", "1440x810",
    "--deterrence-frame-fps", "1",
    "--post-detect-mode", "off",
    "--save-detections", "benchmark\detections",
    "--log-file", "benchmark\detections\log.jsonl"
)

$Process = Start-Process `
    -FilePath $Python `
    -ArgumentList $Arguments `
    -WorkingDirectory $ScriptDir `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError $ErrorLogFile `
    -WindowStyle Minimized `
    -PassThru

Write-Host "Started live detector process: $($Process.Id)"
Write-Host "Log file:   $LogFile"
Write-Host "Error file: $ErrorLogFile"
Write-Host "Check status:"
Write-Host "  Get-CimInstance Win32_Process | Where-Object { `$_.CommandLine -match 'benchmark[\\/]+live_detect\.py' }"
Write-Host "Watch logs:"
Write-Host "  Get-Content -Wait '$LogFile'"
