param(
    [string]$AndroidSerial = $env:ANDROID_ALERT_ADB_SERIAL,
    [string]$AlertDir = "/sdcard/Download/pigeon-setup/sounds"
)

$ErrorActionPreference = "Stop"

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
    throw "No connected ADB device found. Connect USB ADB or run: adb connect PHONE_IP:5555"
}

$files = (& adb -s $AndroidSerial shell "ls -1 '$AlertDir'/startle_combo_*.mp3 2>/dev/null || ls -1 '$AlertDir'/*.mp3 2>/dev/null") |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ }

if (-not $files) {
    throw "No alert MP3 files found in $AlertDir"
}

$selectedFile = $files | Get-Random

& adb -s $AndroidSerial shell am start -S `
    -a android.intent.action.VIEW `
    -n org.videolan.vlc/.StartActivity `
    -d "file://$selectedFile" `
    -t audio/mpeg

Write-Host "Triggered $selectedFile on $AndroidSerial"
