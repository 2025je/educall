[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    # Nombre del archivo dentro de la carpeta de respaldos; por omisión, el más reciente.
    [string]$File
)

# Restaura un respaldo de PostgreSQL: respalda la base actual, detiene la aplicación,
# restaura en una sola transacción y vuelve a iniciar los servicios.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $compose = @("compose", "-f", "compose.yaml")
    $services = @("web", "worker", "scheduler")
    if (Test-Path compose.local-https.yaml) {
        $compose += @("-f", "compose.local-https.yaml")
        $services += "https"
    }
    $backupDir = Join-Path $root "backups"
    if (Test-Path .env) {
        $line = Get-Content .env | Where-Object { $_ -match '^\s*BACKUP_DIR\s*=' } | Select-Object -Last 1
        if ($line) { $backupDir = [IO.Path]::GetFullPath((Join-Path $root (($line -split '=', 2)[1].Trim().Trim('"')))) }
    }
    if (-not $File) {
        $latest = Get-ChildItem $backupDir -Filter "edumeeting-*.dump" -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
        if (-not $latest) { throw "No hay respaldos en $backupDir." }
        $File = $latest.Name
    }
    $File = Split-Path -Leaf $File
    if (-not (Test-Path (Join-Path $backupDir $File))) { throw "No existe $File en $backupDir." }
    if (-not $PSCmdlet.ShouldProcess($File, "Reemplazar la base de datos actual")) { return }

    docker @compose run --rm --no-deps -e "BACKUP_LABEL=antes-de-restaurar" backup-before-migrate
    if ($LASTEXITCODE -ne 0) { throw "No se pudo respaldar la base actual; no se restauró nada." }

    docker @compose stop @services
    docker @compose run --rm --no-deps --entrypoint sh backup-before-migrate /backup.sh restore $File
    $restoreCode = $LASTEXITCODE
    docker @compose up -d --wait @services
    if ($restoreCode -ne 0) { throw "pg_restore falló (código $restoreCode). La base no cambió porque la restauración es una sola transacción." }
    Write-Host "Base restaurada desde $File."
}
finally {
    Pop-Location
}