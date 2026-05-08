param(
    [string]$AndroidSerial = $env:ANDROID_SERIAL,
    [string]$RemoteDir = "/sdcard/Download/pigeon-setup"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    throw "adb is not installed or not on PATH"
}

if ([string]::IsNullOrWhiteSpace($AndroidSerial)) {
    $AndroidSerial = (& adb devices) |
        Select-String "^\S+\s+device$" |
        ForEach-Object { ($_ -split "\s+")[0] } |
        Select-Object -First 1
}

if ([string]::IsNullOrWhiteSpace($AndroidSerial)) {
    & adb devices
    throw "No authorized Android device found. Connect the phone, enable USB debugging, and approve the prompt."
}

$state = (& adb -s $AndroidSerial get-state 2>$null)
if ($LASTEXITCODE -ne 0 -or $state.Trim() -ne "device") {
    & adb devices
    throw "Android device is not authorized or not reachable: $AndroidSerial"
}

& adb -s $AndroidSerial shell "mkdir -p '$RemoteDir'"
& adb -s $AndroidSerial push (Join-Path $ScriptDir "server.py") "$RemoteDir/server.py"
& adb -s $AndroidSerial push (Join-Path $ScriptDir "start.sh") "$RemoteDir/start.sh"
& adb -s $AndroidSerial push (Join-Path $ScriptDir "termux_setup.sh") "$RemoteDir/termux_setup.sh"
& adb -s $AndroidSerial push (Join-Path $ScriptDir "restart_receiver.sh") "$RemoteDir/restart_receiver.sh"
& adb -s $AndroidSerial push (Join-Path $ScriptDir "alert.mp3") "$RemoteDir/alert.mp3"

$SoundsDir = Join-Path $ScriptDir "sounds"
if (Test-Path $SoundsDir) {
    & adb -s $AndroidSerial shell "rm -rf '$RemoteDir/sounds'"
    & adb -s $AndroidSerial push $SoundsDir "$RemoteDir/sounds"
}

Write-Host ""
Write-Host "Files copied to $RemoteDir"
Write-Host "Next, open Termux on the phone and run:"
Write-Host "  termux-setup-storage"
Write-Host "  sh ~/storage/downloads/pigeon-setup/termux_setup.sh"
Write-Host ""
Write-Host "For later receiver restarts after redeploying:"
Write-Host "  sh /sdcard/Download/pigeon-setup/restart_receiver.sh"
