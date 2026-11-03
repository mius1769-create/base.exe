<#
Локальный тестовый научный каталог NeSToR: воспроизводимая сборка на этом компьютере.
Только локальное тестирование: каталог не публикуется, не отправляется в облако и не кладётся в Git.
Запускается от обычной учётной записи (права администратора не нужны).

  powershell -NoProfile -ExecutionPolicy Bypass -File tools\Build-TestCatalog.ps1 `
      -Release "C:\путь\Genopoisk_expert_linux_2026-10-14.tar.gz" -Candidate "C:\путь\Nestor_scientific_YSTR.db"

Шаги: SHA-256 входов (Get-FileHash) → сборка с повторной проверкой SHA-256 и количеств
(60 011 записей, 51 985 индивидуальных, 8 026 агрегированных) → включение → проверка в
локальном интерфейсе (включён, перезапуск, выключение, снова включён). Код возврата 0 —
только если все проверки пройдены. При ошибке прежний каталог не меняется.
#>
param(
    [Parameter(Mandatory = $true)][string]$Release,
    [Parameter(Mandatory = $true)][string]$Candidate,
    [string]$VarDir = "",
    [string]$Python = "",
    [string]$ExpectedFile = "",      # только для проверки на синтетических данных (CI)
    [switch]$SkipUiCheck
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$AppRoot = Split-Path -Parent $PSScriptRoot
if (-not $VarDir) { $VarDir = Join-Path $AppRoot "var" }

$expected = @{
    release_sha256   = "745ca9cdc715c73ff351adee554a7e6259d92d952cfdd0580ac0356cd624d9b5"
    candidate_sha256 = "c6f713b1a0db0966fbabbfaae8fc926934ddd3131fccb591d7686719a7ba7d7d"
}
if ($ExpectedFile) {
    $j = Get-Content -Raw -Encoding UTF8 $ExpectedFile | ConvertFrom-Json
    $expected.release_sha256 = $j.release_sha256
    $expected.candidate_sha256 = $j.candidate_sha256
}

if (-not $Python) {
    if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py"; $PyArgs = @("-3") }
    else { $Python = (Get-Command python).Source; $PyArgs = @() }
} else { $PyArgs = @() }

function Test-Sha([string]$path, [string]$want, [string]$label) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "$label не найден: $path" }
    $got = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "$label SHA-256: $got"
    if ($got -ne $want) { throw "$label SHA-256 не совпал: ожидалось $want" }
    Write-Host "  совпадает с ожидаемым"
}

Test-Sha $Candidate $expected.candidate_sha256 "Nestor_scientific_YSTR.db"
if ($Release -match '\.zip$') {
    $zipHash = (Get-FileHash -LiteralPath $Release -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "ZIP SHA-256: $zipHash (SHA-256 вложенного .tar.gz проверяется при сборке)"
} elseif ($Release -match '\.rar$') {
    throw "RAR не читается: распакуйте части .rar (7-Zip / WinRAR) и укажите полученный .tar.gz"
} else {
    Test-Sha $Release $expected.release_sha256 "Архив"
}

$tool = Join-Path (Join-Path $AppRoot "tools") "build_test_catalog.py"
$common = @("--var-dir", $VarDir)
$buildArgs = $PyArgs + @($tool, "build-release", "--release", $Release, "--candidate", $Candidate, "--enable") + $common
if ($ExpectedFile) { $buildArgs += @("--expected-file", $ExpectedFile) }
$ErrorActionPreference = "Continue"   # вывод Python в stderr не должен прерывать сценарий; итог — по коду возврата
& $Python @buildArgs
if ($LASTEXITCODE -ne 0) { throw "сборка не прошла проверку (код $LASTEXITCODE); каталог не изменён" }

if (-not $SkipUiCheck) {
    $ui = & $Python @($PyArgs + @($tool, "verify-ui") + $common)
    $ui | Select-Object -Last 1 | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "проверка в локальном интерфейсе не пройдена (код $LASTEXITCODE)" }
}
& $Python @($PyArgs + @($tool, "status") + $common)
if ($LASTEXITCODE -ne 0) { throw "status: код $LASTEXITCODE" }
Write-Host "Готово: каталог включён. Выключить: $Python $($PyArgs -join ' ') tools\build_test_catalog.py disable"
