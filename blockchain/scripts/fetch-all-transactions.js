/**
 * Génère une page HTML avec toutes les transactions de tous les contrats déployés.
 * Usage : node scripts/fetch-all-transactions.js [BASESCAN_API_KEY]
 */

const https = require("https");
const fs    = require("fs");
const path  = require("path");

const API_KEY    = process.argv[2] || "YourApiKeyToken";
const START_BLOCK = 42707662;
const CHAIN_ID   = 84532; // Base Sepolia
const BASE_API   = `https://api.etherscan.io/v2/api?chainid=${CHAIN_ID}`;
const BASE_SCAN  = "https://sepolia.basescan.org";

const CONTRACTS = {
  IdentityRegistry:   "0x23f60CD8B68ee1439BC3AF10BD462c2C4d28c119",
  StakingContract:    "0xBf96c8459ec229E155899294C4E697647E1F37E5",
  ReputationRegistry: "0x6F5178B17f20D94B6f106f6b6b8DCb7aD38CC11E",
  EscrowManager:      "0xe899039E3774d70D86d1d59021859773DFA301f1",
  ValidationRegistry: "0xE1aCDb0689CA4684ad7E400591239446b3E2f3dc",
};

const CONTRACT_COLORS = {
  IdentityRegistry:   "#3B82F6",
  StakingContract:    "#10B981",
  ReputationRegistry: "#F59E0B",
  EscrowManager:      "#EF4444",
  ValidationRegistry: "#8B5CF6",
};

function fetch(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(e); }
      });
    }).on("error", reject);
  });
}

function short(addr) {
  return addr ? addr.slice(0, 6) + "…" + addr.slice(-4) : "";
}

function timestamp(ts) {
  return new Date(parseInt(ts) * 1000).toLocaleString("fr-FR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function methodName(input) {
  if (!input || input === "0x") return "deploy / transfer ETH";
  const sig = input.slice(0, 10);
  const sigs = {
    "0x1249c58b": "mint / register",
    "0x40c10f19": "mint",
    "0x60fe47b1": "setActive",
    "0xb88d4fde": "safeTransferFrom",
    "0x095ea7b3": "approve",
    "0xa9059cbb": "transfer",
  };
  return sigs[sig] || sig;
}

async function fetchTxs(name, address) {
  const url = `${BASE_API}&module=account&action=txlist&address=${address}&startblock=${START_BLOCK}&sort=asc&apikey=${API_KEY}`;
  const res = await fetch(url);
  if (res.status !== "1" && res.status !== 1) {
    console.warn(`  [${name}] Aucune tx ou erreur API: ${res.message}`);
    return [];
  }
  return (res.result || []).map((tx) => ({ ...tx, contractName: name }));
}

async function main() {
  console.log("Récupération des transactions sur Base Sepolia…\n");

  const allTxs = [];
  for (const [name, addr] of Object.entries(CONTRACTS)) {
    process.stdout.write(`  ${name}… `);
    const txs = await fetchTxs(name, addr);
    console.log(`${txs.length} tx`);
    allTxs.push(...txs);
    await new Promise((r) => setTimeout(r, 300));
  }

  allTxs.sort((a, b) => parseInt(a.timeStamp) - parseInt(b.timeStamp));

  const totalCount = allTxs.length;

  // Sélectionne 4 tx par contrat (diversité) triées chronologiquement
  const PER_CONTRACT = 4;
  const selected = [];
  for (const name of Object.keys(CONTRACTS)) {
    const contractTxs = allTxs.filter((t) => t.contractName === name);
    selected.push(...contractTxs.slice(0, PER_CONTRACT));
  }
  selected.sort((a, b) => parseInt(a.timeStamp) - parseInt(b.timeStamp));

  const rows = selected.map((tx, i) => {
    const color = CONTRACT_COLORS[tx.contractName] || "#6B7280";
    const status = tx.isError === "0" ? "✓" : "✗";
    const statusColor = tx.isError === "0" ? "#10B981" : "#EF4444";
    return `
    <tr>
      <td>${i + 1}</td>
      <td>${timestamp(tx.timeStamp)}</td>
      <td><span class="badge" style="background:${color}">${tx.contractName}</span></td>
      <td><a href="${BASE_SCAN}/address/${tx.from}" target="_blank">${short(tx.from)}</a></td>
      <td class="method">${methodName(tx.input)}</td>
      <td>${tx.value !== "0" ? (parseInt(tx.value) / 1e18).toFixed(4) + " ETH" : "—"}</td>
      <td style="color:${statusColor};font-weight:bold">${status}</td>
      <td><a href="${BASE_SCAN}/tx/${tx.hash}" target="_blank">${short(tx.hash)}</a></td>
    </tr>`;
  }).join("");

  const counts = {};
  for (const name of Object.keys(CONTRACTS)) {
    counts[name] = allTxs.filter((t) => t.contractName === name).length;
  }
  const summaryCards = Object.entries(counts).map(([name, count]) => `
    <div class="card" style="border-left:4px solid ${CONTRACT_COLORS[name]}">
      <div class="card-name">${name}</div>
      <div class="card-count">${count}</div>
      <div class="card-label">transactions</div>
    </div>`).join("");

  const html = `<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <title>Transactions — AI Agents Marketplace — Base Sepolia</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; padding: 32px; }
    h1 { font-size: 1.6rem; margin-bottom: 4px; color: #f8fafc; }
    .subtitle { color: #94a3b8; font-size: 0.9rem; margin-bottom: 28px; }
    .cards { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px; }
    .card { background: #1e293b; border-radius: 10px; padding: 16px 20px; min-width: 160px; }
    .card-name { font-size: 0.78rem; color: #94a3b8; margin-bottom: 6px; }
    .card-count { font-size: 2rem; font-weight: 700; color: #f1f5f9; }
    .card-label { font-size: 0.75rem; color: #64748b; }
    .total-badge { background: #1e293b; border-radius: 10px; padding: 16px 20px; min-width: 160px; border-left: 4px solid #f1f5f9; }
    table { width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; font-size: 0.82rem; }
    thead { background: #0f172a; }
    th { padding: 12px 14px; text-align: left; color: #64748b; font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
    td { padding: 10px 14px; border-bottom: 1px solid #0f172a; vertical-align: middle; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #263347; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 0.72rem; font-weight: 600; color: #fff; white-space: nowrap; }
    .method { font-family: monospace; color: #a5b4fc; font-size: 0.78rem; }
    a { color: #60a5fa; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .footer { margin-top: 20px; color: #475569; font-size: 0.75rem; text-align: right; }
  </style>
</head>
<body>
  <h1>AI Agents Marketplace — Transactions on-chain</h1>
  <p class="subtitle">Réseau : Base Sepolia · Déployé le 11/06/2026 · ${totalCount} transactions au total · ${selected.length} représentatives affichées (4 par contrat)</p>
  <div class="cards">
    ${summaryCards}
    <div class="card total-badge">
      <div class="card-name">TOTAL</div>
      <div class="card-count">${allTxs.length}</div>
      <div class="card-label">transactions</div>
    </div>
  </div>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Date</th>
        <th>Contrat</th>
        <th>From</th>
        <th>Méthode</th>
        <th>Valeur</th>
        <th>Statut</th>
        <th>Hash</th>
      </tr>
    </thead>
    <tbody>
      ${rows || "<tr><td colspan='8' style='text-align:center;padding:40px;color:#64748b'>Aucune transaction trouvée — vérifiez votre clé API Basescan</td></tr>"}
    </tbody>
  </table>
  <p class="footer">Affichage : ${selected.length} / ${totalCount} transactions · historique complet sur sepolia.basescan.org · Généré le ${new Date().toLocaleString("fr-FR")}</p>
</body>
</html>`;

  const outPath = path.join(__dirname, "..", "test-reports", "transactions.html");
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, html, "utf8");
  console.log(`\n✓ Rapport généré : ${outPath}`);
  console.log(`  Ouvre dans Chrome : start chrome "${outPath}"`);
}

main().catch(console.error);
