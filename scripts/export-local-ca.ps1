[CmdletBinding()]
param(
    [string]$OutputPath,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $projectRoot "edumeeting-local-root.crt"
} elseif (-not [IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path (Get-Location) $OutputPath
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)

if ((Test-Path -LiteralPath $OutputPath) -and -not $Force) {
    throw "El archivo ya existe: $OutputPath. Usa -Force para reemplazarlo."
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".env"))) {
    throw "No existe .env en la raiz. Configura el proyecto y vuelve a iniciar Docker Compose."
}

$composeArguments = @(
    "compose",
    "--project-directory", $projectRoot,
    "-f", (Join-Path $projectRoot "compose.yaml"),
    "-f", (Join-Path $projectRoot "compose.local-https.yaml")
)
$certificatePath = "/data/caddy/pki/authorities/local/root.crt"

& docker @composeArguments exec -T https sh -c "test -s $certificatePath"
if ($LASTEXITCODE -ne 0) {
    throw "No se encontro la CA local en Caddy. Inicia HTTPS con: docker compose -f compose.yaml -f compose.local-https.yaml up -d"
}

$outputDirectory = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}

$temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) "edumeeting-ca-$([Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null

try {
    & docker @composeArguments cp "https:$certificatePath" $temporaryDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Docker no pudo exportar la CA local de Caddy."
    }

    $temporaryCertificate = Join-Path $temporaryDirectory "root.crt"
    if (-not (Test-Path -LiteralPath $temporaryCertificate)) {
        throw "Docker termino la copia, pero no se encontro root.crt."
    }

    $pem = Get-Content -LiteralPath $temporaryCertificate -Raw
    if ($pem -notmatch '(?s)^-----BEGIN CERTIFICATE-----\s*(?<der>[A-Za-z0-9+/=\r\n]+)\s*-----END CERTIFICATE-----\s*$') {
        throw "El archivo exportado no es un certificado PEM valido."
    }

    $der = [Convert]::FromBase64String(($Matches.der -replace '\s', ''))
    $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($der)
    Move-Item -LiteralPath $temporaryCertificate -Destination $OutputPath -Force:$Force
    Write-Output "CA local exportada: $OutputPath"
    Write-Output "Huella SHA-1: $($certificate.Thumbprint)"
} finally {
    Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
