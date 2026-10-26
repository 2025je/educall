[CmdletBinding()]
param(
    [string]$Label = "manual"
)

# Crea un respaldo inmediato de PostgreSQL en .\backups (o en BACKUP_DIR de .env).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if ($Label -notmatch '^[A-Za-z0-9_-]+$') { throw "La etiqueta solo puede tener letras, números, guiones y guiones bajos." }
    $compose = @("compose", "-f", "compose.yaml")
    if (Test-Path compose.local-https.yaml) { $compose += @("-f", "compose.local-https.yaml") }
    docker @compose run --rm --no-deps -e "BACKUP_LABEL=$Label" backup-before-migrate
    if ($LASTEXITCODE -ne 0) { throw "El respaldo falló (código $LASTEXITCODE). ¿Está corriendo el servicio db?" }
}
finally {
    Pop-Location
}