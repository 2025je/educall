[CmdletBinding()]
param(
    # Direccion de depuracion inalambrica (IP:PUERTO) que muestra el telefono.
    [string]$Device,
    # Direccion de vinculacion (IP:PUERTO) de "Vincular con codigo"; solo la primera vez.
    [string]$PairAddress,
    [string]$PairCode,
    [ValidateSet("all", "llamadas", "asistencia")]
    [string]$App = "all",
    [switch]$Build,
    [switch]$Launch,
    [string]$AdbPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$apps = @{
    llamadas   = @{ Apk = "edumeeting-llamadas-debug.apk"; Package = "org.edumeeting.llamadas"; Service = "llamadas" }
    asistencia = @{ Apk = "edumeeting-asistencia-debug.apk"; Package = "org.edumeeting.asistencia"; Service = "asistencia" }
}
$selected = if ($App -eq "all") { @("llamadas", "asistencia") } else { @($App) }

function Find-Adb {
    if ($AdbPath) {
        if (-not (Test-Path -LiteralPath $AdbPath)) { throw "No existe adb en: $AdbPath" }
        return (Resolve-Path -LiteralPath $AdbPath).Path
    }
    $candidates = @()
    foreach ($root in @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, "C:\Android", "$env:LOCALAPPDATA\Android\Sdk")) {
        if ($root) { $candidates += Join-Path $root "platform-tools\adb.exe" }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    $command = Get-Command adb -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "No se encontro adb. Instala Android platform-tools o usa -AdbPath."
}

function Invoke-Adb {
    param([string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $script:adb @Arguments 2>&1 | ForEach-Object { "$_" }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = ($output -join "`n").Trim() }
}

function Get-ReadyDevices {
    $result = Invoke-Adb @("devices")
    return @($result.Output -split "`n" | Select-Object -Skip 1 |
        Where-Object { $_ -match '^(\S+)\s+device$' } | ForEach-Object { ($_ -split '\s+')[0] })
}

function Test-Address([string]$Value, [string]$Name) {
    if ($Value -notmatch '^[A-Za-z0-9.\-]+:\d{1,5}$') {
        throw "$Name debe tener el formato IP:PUERTO, por ejemplo 192.168.1.35:40259."
    }
}

$adb = Find-Adb
Write-Output "Usando adb: $adb"

if ($Build) {
    foreach ($name in $selected) {
        Write-Output "Compilando $name..."
        $previous = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & docker compose --project-directory $projectRoot -f (Join-Path $projectRoot "compose.android.yaml") run --rm $apps[$name].Service
            $buildExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previous
        }
        if ($buildExit -ne 0) { throw "Fallo la compilacion de $name." }
    }
}

foreach ($name in $selected) {
    $apkPath = Join-Path $projectRoot "artifacts\android\$($apps[$name].Apk)"
    if (-not (Test-Path -LiteralPath $apkPath)) {
        throw "No existe $apkPath. Ejecuta el script con -Build."
    }
}

if ($PairAddress) {
    Test-Address $PairAddress "PairAddress"
    if (-not $PairCode) { $PairCode = Read-Host "Codigo de vinculacion de 6 digitos" }
    if ($PairCode -notmatch '^\d{6}$') { throw "El codigo de vinculacion debe tener 6 digitos." }
    $pair = Invoke-Adb @("pair", $PairAddress, $PairCode)
    Write-Output $pair.Output
    if ($pair.Output -notmatch 'Successfully paired') {
        throw "No se pudo vincular. Revisa el codigo, el puerto y que el telefono este en la misma red."
    }
}

if (-not $Device) {
    $ready = @(Get-ReadyDevices)
    if ($ready.Count -eq 1) {
        $Device = $ready[0]
    } else {
        if ($ready.Count -gt 1) { Write-Output "Dispositivos conectados: $($ready -join ', ')" }
        $Device = Read-Host "Direccion de depuracion inalambrica (IP:PUERTO) o serie del dispositivo"
    }
}

if ($Device -match ':\d+$') {
    Test-Address $Device "Device"
    if ((Get-ReadyDevices) -notcontains $Device) {
        Invoke-Adb @("disconnect", $Device) | Out-Null
        $connect = Invoke-Adb @("connect", $Device)
        Write-Output $connect.Output
        Start-Sleep -Seconds 2
    }
}
if ((Get-ReadyDevices) -notcontains $Device) {
    throw ("El dispositivo $Device no esta disponible. Desbloquea el telefono, confirma que la depuracion " +
        "inalambrica siga activa y revisa el puerto actual. Si nunca lo vinculaste con esta PC, usa -PairAddress.")
}

$model = (Invoke-Adb @("-s", $Device, "shell", "getprop", "ro.product.model")).Output
Write-Output "Dispositivo listo: $Device ($model)"

$failed = @()
foreach ($name in $selected) {
    $info = $apps[$name]
    $apkPath = Join-Path $projectRoot "artifacts\android\$($info.Apk)"
    Write-Output "Instalando $($info.Apk) ($([math]::Round((Get-Item -LiteralPath $apkPath).Length / 1MB, 1)) MB)..."
    # --user 0: solo el perfil principal. Sin esto, Samsung "Dual App"/Carpeta segura reciben otra copia.
    $install = Invoke-Adb @("-s", $Device, "install", "-r", "--user", "0", $apkPath)
    Write-Output $install.Output
    $packages = (Invoke-Adb @("-s", $Device, "shell", "pm", "list", "packages", "--user", "0", $info.Package)).Output
    if ($install.Output -notmatch '(?m)^Success' -or $packages -notmatch [regex]::Escape("package:$($info.Package)")) {
        $failed += $name
        continue
    }
    Write-Output "OK: $($info.Package) instalado."
    if ($Launch) {
        Invoke-Adb @("-s", $Device, "shell", "monkey", "-p", $info.Package, "-c", "android.intent.category.LAUNCHER", "1") | Out-Null
    }
}

if ($failed.Count -gt 0) { throw "No se pudo instalar: $($failed -join ', ')." }
Write-Output "Instalacion completa. Puedes desactivar la depuracion inalambrica cuando termines."
