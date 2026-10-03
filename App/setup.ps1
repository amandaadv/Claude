# Baby Luz -- Automação de Produção
# Instalador para computador novo (recém-formatado). Roda uma vez: instala o
# Python, as bibliotecas, prepara as pastas locais, e baixa o modelo de IA
# usado pra identificar produtos por foto. As credenciais (API do site,
# OpenAI) já vêm prontas no código -- nada pra preencher aqui.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "=== Baby Luz - Automação de Produção - Instalador ===" -ForegroundColor Cyan
Write-Host ""

# 1. Python -----------------------------------------------------------------
# "python" isn't a reliable check on a fresh Windows install: Windows ships a
# fake "python.exe"/"python3.exe" on PATH (an App Execution Alias) that just
# prints a Microsoft Store nag and exits 0 with no real Python behind it --
# Get-Command finds it same as a real install, so it can't tell them apart.
# The Python 3.13+ official installer also switched to registering only the
# "py" launcher by default, not "python" -- so a genuinely fresh, correctly
# installed Python may not have a "python" command at all. Checking actual
# version output from each candidate, in order, catches both cases.
Write-Host "[1/3] Verificando Python..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($candidate in @("python", "py")) {
    try {
        $versionOutput = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $versionOutput -match "^Python \d") {
            $pythonCmd = $candidate
            Write-Host $versionOutput
            break
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "Python não encontrado nesse computador." -ForegroundColor Red
    Write-Host "Baixe e instale em https://www.python.org/downloads/"
    Write-Host "IMPORTANTE: na tela de instalação, marque a caixinha 'Add python.exe to PATH'."
    Write-Host "Depois de instalar, feche esta janela, abra uma nova, e rode este arquivo de novo."
    Read-Host "Pressione Enter para sair"
    exit 1
}
Write-Host "OK (usando '$pythonCmd')" -ForegroundColor Green
Write-Host ""

# 2. Bibliotecas Python -------------------------------------------------------
Write-Host "[2/3] Instalando bibliotecas Python (pode demorar alguns minutos)..." -ForegroundColor Yellow
& $pythonCmd -m pip install --upgrade pip
& $pythonCmd -m pip install -r (Join-Path $scriptDir "requirements.txt")
Write-Host "OK" -ForegroundColor Green
Write-Host ""

# 3. Pastas locais + modelo de IA --------------------------------------------
Write-Host "[3/3] Preparando pastas e baixando o modelo de IA (~90MB, só na primeira vez)..." -ForegroundColor Yellow
$root = Join-Path $env:LOCALAPPDATA "ProductionAutomation"
$modelsFolder = Join-Path $root "models"
foreach ($folder in @($root, $modelsFolder, (Join-Path $root "storage"), (Join-Path $root "logs"), (Join-Path $root "backups"))) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
}

$modelPath = Join-Path $modelsFolder "clip-vit-base-patch32-vision-quantized.onnx"
if (Test-Path $modelPath) {
    Write-Host "Modelo de IA já existe, pulando o download." -ForegroundColor Green
} else {
    $modelUrl = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx"
    Write-Host "Baixando de $modelUrl ..."
    Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath
    Write-Host "OK" -ForegroundColor Green
}
Write-Host ""

Write-Host "=== Instalação concluída! ===" -ForegroundColor Cyan
Write-Host "Para abrir o sistema, dê duplo clique em 'Baby Luz - Automação.bat'."
Read-Host "Pressione Enter para fechar"
