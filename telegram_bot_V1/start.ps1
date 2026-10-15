# ============================================================
#  start.ps1 — Jalanin semua: API server + ngrok + Telegram bot
#  Cara pakai (dari folder telegram_bot_V1):
#      powershell -ExecutionPolicy Bypass -File .\start.ps1
# ============================================================
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$PORT = 8001

# Pilih python: venv kalau ada, kalau nggak pakai global
$PY = if (Test-Path ".\venv\Scripts\python.exe") { (Resolve-Path ".\venv\Scripts\python.exe").Path } else { "python" }
Write-Host "[0] Python: $PY" -ForegroundColor DarkGray

# 1. Cek MySQL
if (-not (Get-Process mysqld -ErrorAction SilentlyContinue)) {
    Write-Host "[!] MySQL belum jalan. Nyalain dulu MySQL di XAMPP/Laragon, terus jalanin script ini lagi." -ForegroundColor Red
    exit 1
}
Write-Host "[1] MySQL OK" -ForegroundColor Green

# 2. Matikan sisa proses lama (ngrok, api server, bot) biar nggak bentrok
Get-Process ngrok -ErrorAction SilentlyContinue | Stop-Process -Force
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match "main\.py|api_server" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

# 3. API server (FastAPI) — serve /miniapp & /website
Start-Process -FilePath $PY -ArgumentList "-m uvicorn api_server:app --host 0.0.0.0 --port $PORT --reload" `
    -WorkingDirectory $PSScriptRoot -WindowStyle Minimized
Write-Host "[2] API server jalan di http://localhost:$PORT" -ForegroundColor Green

# 4. ngrok (domain tetap -> URL nggak berubah tiap restart)
$DOMAIN = "finally-matching-upstage.ngrok-free.dev"
Start-Process -FilePath "ngrok" -ArgumentList "http --url=$DOMAIN $PORT" -WindowStyle Minimized
Write-Host "[3] Nunggu ngrok..." -ForegroundColor Yellow
$ok = $false
for ($i = 0; $i -lt 20 -and -not $ok; $i++) {
    Start-Sleep -Seconds 1
    try {
        $t = Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2
        $ok = [bool]($t.tunnels | Where-Object { $_.public_url -like "https://$DOMAIN*" })
    } catch {}
}
if (-not $ok) {
    Write-Host "[!] ngrok gagal pakai domain $DOMAIN. Cek authtoken akun yang punya domain: ngrok config add-authtoken <token>" -ForegroundColor Red
    exit 1
}
$url = "https://$DOMAIN"
Write-Host "[3] ngrok URL: $url" -ForegroundColor Green

# 5. Tulis .env (dibaca config.py)
Set-Content -Path ".env" -Value "API_BASE_URL=$url" -Encoding ascii
Write-Host "[4] .env di-update" -ForegroundColor Green

# 6. Bot (jalan di jendela ini, Ctrl+C buat stop)
Write-Host "[5] Start bot... (Ctrl+C buat berhenti)" -ForegroundColor Cyan
Write-Host "    Mini App: $url/miniapp/index.html" -ForegroundColor DarkGray
& $PY main.py
