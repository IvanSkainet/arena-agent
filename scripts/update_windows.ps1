# Arena Local Agent — Windows Update wrapper
# Этот файл вызывает единый инсталлятор в режиме обновления.
$Installer = Join-Path $PSScriptRoot "install_windows_service.ps1"
if (-not (Test-Path $Installer)) {
    Write-Error "Не найден install_windows_service.ps1 в той же папке. Проверьте целостность архива."
    exit 1
}
& $Installer -Update
