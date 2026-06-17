require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config({ path: "../.env" });

const DEPLOYER_KEY = process.env.DEPLOYER_PRIVATE_KEY
  ? [process.env.DEPLOYER_PRIVATE_KEY]
  : [];

module.exports = {
  solidity: {
    version: "0.8.25",
    settings: {
      optimizer: { enabled: true, runs: 200 },
      viaIR: true,
      evmVersion: "cancun",
    },
  },
  networks: {
    // ── Local (Anvil / Hardhat node) ─────────────────────────────────────────
    hardhat:   { chainId: 31337 },
    localhost: { url: "http://127.0.0.1:8545", chainId: 31337 },

    // ── Layer 2 : Polygon ─────────────────────────────────────────────────────
    polygonMumbai: {
      url:      process.env.POLYGON_MUMBAI_RPC_URL || "https://rpc-mumbai.maticvigil.com",
      accounts: DEPLOYER_KEY,
      chainId:  80001,
    },
    polygon: {
      url:      process.env.POLYGON_RPC_URL || "https://polygon-rpc.com",
      accounts: DEPLOYER_KEY,
      chainId:  137,
    },

    // ── Sepolia (gardé pour référence) ────────────────────────────────────────
    sepolia: {
      url:      process.env.SEPOLIA_RPC_URL || "",
      accounts: DEPLOYER_KEY,
      chainId:  11155111,
    },

    // ── Base Sepolia (L2 testnet) ─────────────────────────────────────────────
    baseSepolia: {
      url:      process.env.BASE_SEPOLIA_RPC_URL || "https://sepolia.base.org",
      accounts: DEPLOYER_KEY,
      chainId:  84532,
    },
  },
  mocha: {
    reporter: "mochawesome",
    reporterOptions: {
      reportDir:      "test-reports",
      reportFilename: "rapport-tests",
      quiet:          true,
      charts:         true,
      code:           false,
    },
  },
  etherscan: {
    apiKey: {
      mainnet:       process.env.ETHERSCAN_API_KEY   || "",
      sepolia:       process.env.ETHERSCAN_API_KEY   || "",
      polygon:       process.env.POLYGONSCAN_API_KEY || "",
      polygonMumbai: process.env.POLYGONSCAN_API_KEY || "",
      baseSepolia:   process.env.BASESCAN_API_KEY    || "",
    },
    customChains: [
      {
        network:  "baseSepolia",
        chainId:  84532,
        urls: {
          apiURL:      "https://api-sepolia.basescan.org/api",
          browserURL:  "https://sepolia.basescan.org",
        },
      },
    ],
  },
};