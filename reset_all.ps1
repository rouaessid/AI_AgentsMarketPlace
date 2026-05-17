# reset_all.ps1
# Réinitialise TOUT : blockchain + DB + IPFS local
# Puis redéploie les contrats et réenregistre les 8 agents.
#
# Usage :
#   1. Arrêter Anvil et le backend (Ctrl+C dans leurs terminaux)
#   2. Dans un terminal PowerShell à la racine du projet :
#      .\reset_all.ps1

Set-StrictMode -Off
$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "══════════════════════════════════════════"
Write-Host "  RESET COMPLET — AgentMarketplace"
Write-Host "══════════════════════════════════════════"
Write-Host ""

# ── 0. Vérifier que le backend et Anvil sont arrêtés ──────────────────────────
$uvicorn = Get-Process -Name "python" -ErrorAction SilentlyContinue |
           Where-Object { $_.CommandLine -match "uvicorn" }
if ($uvicorn) {
    Write-Host "[WARN] Le backend (uvicorn) semble tourner — arrête-le avant de continuer."
    Write-Host "       Ctrl+C dans son terminal, puis relance reset_all.ps1"
    exit 1
}

# ── 1. Supprimer la DB SQLite ─────────────────────────────────────────────────
$dbPath = "C:\tmp\agentmarket\agentmarket.db"
if (Test-Path $dbPath) {
    Remove-Item $dbPath -Force
    Write-Host "[OK] DB supprimée : $dbPath"
} else {
    Write-Host "[OK] DB absente (déjà propre)"
}

# ── 2. Supprimer les fichiers IPFS locaux ────────────────────────────────────
$ipfsPath = "C:\tmp\agentmarket\ipfs_local"
if (Test-Path $ipfsPath) {
    Remove-Item $ipfsPath -Recurse -Force
    Write-Host "[OK] IPFS local supprimé : $ipfsPath"
} else {
    Write-Host "[OK] IPFS local absent (déjà propre)"
}

# ── 3. Instruction Anvil ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "══ ÉTAPE SUIVANTE : Lance Anvil dans un terminal séparé ══"
Write-Host ""
Write-Host "  Si tu utilises --state, Anvil recharge l'ancien état."
Write-Host "  Pour repartir propre, lance Anvil SANS --state :"
Write-Host ""
Write-Host "    anvil"
Write-Host ""
Write-Host "  OU charge seulement l'état genesis initial (sans auto-save) :"
Write-Host ""
Write-Host "    anvil --load-state hardhat-state.json"
Write-Host ""
Write-Host "  Appuie sur ENTRÉE ici une fois Anvil lancé..."
Read-Host | Out-Null

# ── 4. Redéployer les contrats ────────────────────────────────────────────────
Write-Host ""
Write-Host "[...] Déploiement des contrats..."
Set-Location blockchain
$deployResult = npx hardhat run scripts/setup_complete.js --network localhost 2>&1
Write-Host $deployResult
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] setup_complete.js a échoué. Vérifie qu'Anvil tourne sur :8545"
    Set-Location ..
    exit 1
}
Set-Location ..
Write-Host "[OK] Contrats redéployés."

# ── 5. Instruction backend ────────────────────────────────────────────────────
Write-Host ""
Write-Host "══ ÉTAPE SUIVANTE : Lance le backend dans un terminal séparé ══"
Write-Host ""
Write-Host "    cd backend"
Write-Host "    ..\venv\Scripts\uvicorn app.main:app --reload --port 8000"
Write-Host ""
Write-Host "  Appuie sur ENTRÉE ici une fois le backend lancé..."
Read-Host | Out-Null

# ── 6. Enregistrer les agents ─────────────────────────────────────────────────
Write-Host ""
Write-Host "[...] Enregistrement de researcher-01..."
Set-Location blockchain
node scripts/register_researcher.js
if ($LASTEXITCODE -ne 0) { Write-Host "[ERREUR] register_researcher.js a échoué"; Set-Location ..; exit 1 }

Write-Host ""
Write-Host "[...] Enregistrement de analyst-01 et writer-01..."
node scripts/register_agents_robust.js
if ($LASTEXITCODE -ne 0) { Write-Host "[ERREUR] register_agents_robust.js a échoué"; Set-Location ..; exit 1 }

Write-Host ""
Write-Host "[...] Enregistrement des 5 juges..."
node scripts/register_judges_robust.js
if ($LASTEXITCODE -ne 0) { Write-Host "[ERREUR] register_judges_robust.js a échoué"; Set-Location ..; exit 1 }
Set-Location ..

# ── 7. Résumé ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "══════════════════════════════════════════"
Write-Host "  RESET TERMINÉ"
Write-Host "  8 agents enregistrés :"
Write-Host "    Providers : researcher-01, analyst-01, writer-01"
Write-Host "    Juges     : judge-alpha, judge-beta, judge-gamma,"
Write-Host "                judge-delta, judge-epsilon"
Write-Host "══════════════════════════════════════════"
Write-Host ""
