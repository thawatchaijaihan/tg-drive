# GAPT-CINEMA: Build & Run Script for Rust Backend + TV WASM UI

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "🎬 GAPT-CINEMA — RUST STACK BUILDER" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# Step 1: Build TV WebAssembly UI
Write-Host "`n[1/2] Building TV UI (Rust WebAssembly)..." -ForegroundColor Yellow
cd tv-ui
npx -y wasm-pack build --target web --out-dir ../rust-server/static/pkg
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to compile TV WASM UI" -ForegroundColor Red
    exit 1
}
cd ..
Write-Host "✅ TV WASM UI build complete!" -ForegroundColor Green

# Step 2: Build & Run Rust Backend (Axum + Tokio)
Write-Host "`n[2/2] Launching Axum + Tokio Server on port 8086..." -ForegroundColor Yellow
cargo run -p rust-server
