// test/IdentityRegistry.test.js
const { expect }     = require("chai");
const { ethers }     = require("hardhat");
const { time }       = require("@nomicfoundation/hardhat-network-helpers");

// ─── Constantes ──────────────────────────────────────────────────────────────

const AgentType   = { PROVIDER: 0, JUDGE: 1 };
const AgentStatus = { ACTIVE: 0, SUSPENDED: 1, REVOKED: 2 };

const URI_V1 = "ipfs://QmV1CID/agent.json";
const URI_V2 = "ipfs://QmV2CID/agent.json";
const URI_V3 = "ipfs://QmV3CID/agent.json";

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function deploy() {
  const [platform, alice, bob, carol] = await ethers.getSigners();
  const Factory  = await ethers.getContractFactory("IdentityRegistry");
  const registry = await Factory.deploy();
  await registry.waitForDeployment();
  return { registry, platform, alice, bob, carol };
}

async function registerAgent(registry, signer, agentId, type = AgentType.PROVIDER, uri = URI_V1, ver = "1.0.0") {
  return registry.connect(signer).register(agentId, type, uri, ver);
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("IdentityRegistry", function () {

  // ── Déploiement ─────────────────────────────────────────────────────────────
  describe("Deployment", function () {
    it("has correct name and symbol", async function () {
      const { registry } = await deploy();
      expect(await registry.name()).to.equal("AgentMarket Identity");
      expect(await registry.symbol()).to.equal("AMID");
    });

    it("builds agentRegistry = eip155:{chainId}:{address}", async function () {
      const { registry } = await deploy();
      const chainId = (await ethers.provider.getNetwork()).chainId;
      const ar      = await registry.agentRegistry();
      expect(ar).to.include(`eip155:${chainId}`);
      expect(ar.toLowerCase()).to.include((await registry.getAddress()).toLowerCase());
    });

    it("starts with 0 tokens minted", async function () {
      const { registry } = await deploy();
      expect(await registry.totalTokensMinted()).to.equal(0n);
    });
  });

  // ── Registration — premier mint ─────────────────────────────────────────────
  describe("register() — first mint", function () {
    it("mints token #1 for first agent", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X");
      expect(await registry.totalTokensMinted()).to.equal(1n);
      expect(await registry.ownerOf(1)).to.equal(alice.address);
    });

    it("agentId string is preserved and queryable", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X");
      const identity = await registry.getAgent("search-X");
      expect(identity.agentId).to.equal("search-X");
    });

    it("token_id ≠ agent_id — tokenId is uint, agentId is string", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "summarize-3");
      const tokenId = await registry.getCurrentTokenId("summarize-3");
      expect(tokenId).to.equal(1n);            // tokenId = 1
      expect("summarize-3").to.be.a("string"); // agentId = "summarize-3"
    });

    it("owner = msg.sender (wallet connecté, pas saisi manuellement)", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "agent-1");
      const identity = await registry.getAgent("agent-1");
      expect(identity.owner).to.equal(alice.address);
    });

    it("agentWallet = owner par défaut (wallet connecté)", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "agent-1");
      expect(await registry.getAgentWallet("agent-1")).to.equal(alice.address);
    });

    it("status = ACTIVE par défaut", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "agent-1");
      expect(await registry.isActive("agent-1")).to.be.true;
    });

    it("agentURI = URI IPFS du token courant", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X", AgentType.PROVIDER, URI_V1);
      expect(await registry.agentURI("search-X")).to.equal(URI_V1);
    });

    it("emits AgentCreated with correct args", async function () {
      const { registry, alice } = await deploy();
      await expect(registerAgent(registry, alice, "search-X", AgentType.PROVIDER, URI_V1, "1.0.0"))
        .to.emit(registry, "AgentCreated")
        .withArgs("search-X", 1n, alice.address, AgentType.PROVIDER, URI_V1, "1.0.0");
    });

    it("two different agents get different tokenIds", async function () {
      const { registry, alice, bob } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await registerAgent(registry, bob, "translate-Y");
      expect(await registry.getCurrentTokenId("search-X")).to.equal(1n);
      expect(await registry.getCurrentTokenId("translate-Y")).to.equal(2n);
    });

    it("reverts on duplicate agentId", async function () {
      const { registry, alice, bob } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await expect(registerAgent(registry, bob, "search-X"))
        .to.be.revertedWithCustomError(registry, "AgentIdAlreadyExists");
    });

    it("reverts on invalid agentId (special chars)", async function () {
      const { registry, alice } = await deploy();
      await expect(registerAgent(registry, alice, "search X!"))
        .to.be.revertedWithCustomError(registry, "AgentIdInvalid");
    });

    it("reverts on empty agentId", async function () {
      const { registry, alice } = await deploy();
      await expect(registerAgent(registry, alice, ""))
        .to.be.revertedWithCustomError(registry, "AgentIdInvalid");
    });

    it("reverse lookup tokenId → agentId works", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X");
      expect(await registry.getAgentIdByToken(1n)).to.equal("search-X");
    });
  });

  // ── Versioning — nouveau token par mise à jour ────────────────────────────
  describe("mintNewVersion() — new token per update", function () {
    it("mints a new tokenId, agentId remains the same", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X", AgentType.PROVIDER, URI_V1, "1.0.0");
      await registry.connect(alice).mintNewVersion("search-X", URI_V2, "1.1.0");

      // agentId inchangé
      expect(await registry.agentIdExists("search-X")).to.be.true;
      // nouveau tokenId = 2
      expect(await registry.getCurrentTokenId("search-X")).to.equal(2n);
      expect(await registry.totalTokensMinted()).to.equal(2n);
    });

    it("new agentURI points to new token's IPFS", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X", AgentType.PROVIDER, URI_V1);
      await registry.connect(alice).mintNewVersion("search-X", URI_V2, "1.1.0");
      expect(await registry.agentURI("search-X")).to.equal(URI_V2);
    });

    it("old token is still on-chain (history preserved)", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X", AgentType.PROVIDER, URI_V1, "1.0.0");
      await registry.connect(alice).mintNewVersion("search-X", URI_V2, "1.1.0");

      const history = await registry.getTokenHistory("search-X");
      expect(history.length).to.equal(2);
      expect(history[0]).to.equal(1n);
      expect(history[1]).to.equal(2n);

      // L'ancien token existe toujours
      const v1 = await registry.getVersion(1n);
      expect(v1.isCurrent).to.be.false;
      expect(v1.version).to.equal("1.0.0");
      expect(v1.agentURI).to.equal(URI_V1);
    });

    it("new token is current", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X", AgentType.PROVIDER, URI_V1, "1.0.0");
      await registry.connect(alice).mintNewVersion("search-X", URI_V2, "1.1.0");
      const v2 = await registry.getVersion(2n);
      expect(v2.isCurrent).to.be.true;
      expect(v2.version).to.equal("1.1.0");
    });

    it("three versions → tokenIds 1,2,3 for same agentId", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X", AgentType.PROVIDER, URI_V1, "1.0.0");
      await registry.connect(alice).mintNewVersion("search-X", URI_V2, "1.1.0");
      await registry.connect(alice).mintNewVersion("search-X", URI_V3, "2.0.0");

      expect(await registry.getCurrentTokenId("search-X")).to.equal(3n);
      const history = await registry.getTokenHistory("search-X");
      expect(history.length).to.equal(3);
    });

    it("emits AgentVersionMinted", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X", AgentType.PROVIDER, URI_V1);
      await expect(registry.connect(alice).mintNewVersion("search-X", URI_V2, "1.1.0"))
        .to.emit(registry, "AgentVersionMinted")
        .withArgs("search-X", 2n, 1n, URI_V2, "1.1.0");
    });

    it("non-owner cannot mint new version", async function () {
      const { registry, alice, bob } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await expect(registry.connect(bob).mintNewVersion("search-X", URI_V2, "1.1.0"))
        .to.be.revertedWithCustomError(registry, "NotAgentOwner");
    });

    it("cannot update non-existent agentId", async function () {
      const { registry, alice } = await deploy();
      await expect(registry.connect(alice).mintNewVersion("ghost-99", URI_V2, "1.0.0"))
        .to.be.revertedWithCustomError(registry, "AgentIdNotFound");
    });
  });

  // ── SOULBOUND — non transférable ─────────────────────────────────────────
  describe("Soulbound — transfer forbidden", function () {
    it("transferFrom reverts with SoulboundTransferForbidden", async function () {
      const { registry, alice, bob } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await expect(
        registry.connect(alice).transferFrom(alice.address, bob.address, 1n)
      ).to.be.revertedWithCustomError(registry, "SoulboundTransferForbidden");
    });

    it("safeTransferFrom reverts", async function () {
      const { registry, alice, bob } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await expect(
        registry.connect(alice)["safeTransferFrom(address,address,uint256)"](
          alice.address, bob.address, 1n
        )
      ).to.be.revertedWithCustomError(registry, "SoulboundTransferForbidden");
    });

    it("approve reverts", async function () {
      const { registry, alice, bob } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await expect(registry.connect(alice).approve(bob.address, 1n))
        .to.be.revertedWithCustomError(registry, "SoulboundTransferForbidden");
    });

    it("setApprovalForAll reverts", async function () {
      const { registry, alice, bob } = await deploy();
      await expect(registry.connect(alice).setApprovalForAll(bob.address, true))
        .to.be.revertedWithCustomError(registry, "SoulboundTransferForbidden");
    });
  });

  // ── agentWallet EIP-712 ───────────────────────────────────────────────────
  describe("setAgentWallet() — EIP-712", function () {
    async function signWallet(signer, registry, agentId, newWallet, deadline) {
      const chainId    = (await ethers.provider.getNetwork()).chainId;
      const regAddress = await registry.getAddress();
      const tokenId    = await registry.getCurrentTokenId(agentId);
      return signer.signTypedData(
        { name: "AgentMarket", version: "1", chainId, verifyingContract: regAddress },
        { SetAgentWallet: [
            { name: "tokenId",   type: "uint256" },
            { name: "newWallet", type: "address" },
            { name: "deadline",  type: "uint256" },
        ]},
        { tokenId, newWallet, deadline }
      );
    }

    it("owner sets agentWallet with valid EIP-712 sig", async function () {
      const { registry, alice, bob } = await deploy();
      await registerAgent(registry, alice, "search-X");
      const deadline = (await time.latest()) + 3600;
      const sig      = await signWallet(bob, registry, "search-X", bob.address, deadline);
      await registry.connect(alice).setAgentWallet("search-X", bob.address, deadline, sig);
      expect(await registry.getAgentWallet("search-X")).to.equal(bob.address);
    });

    it("reverts with expired deadline", async function () {
      const { registry, alice, bob } = await deploy();
      await registerAgent(registry, alice, "search-X");
      const deadline = (await time.latest()) - 1;
      const sig      = await signWallet(bob, registry, "search-X", bob.address, deadline);
      await expect(registry.connect(alice).setAgentWallet("search-X", bob.address, deadline, sig))
        .to.be.revertedWithCustomError(registry, "SignatureExpired");
    });

    it("reverts with wrong signer", async function () {
      const { registry, alice, bob, carol } = await deploy();
      await registerAgent(registry, alice, "search-X");
      const deadline = (await time.latest()) + 3600;
      // carol signe mais on déclare bob.address comme newWallet → mismatch
      const sig = await signWallet(carol, registry, "search-X", bob.address, deadline);
      await expect(registry.connect(alice).setAgentWallet("search-X", bob.address, deadline, sig))
        .to.be.revertedWithCustomError(registry, "InvalidSignature");
    });
  });

  // ── Status (plateforme) ───────────────────────────────────────────────────
  describe("setAgentStatus() — platform only", function () {
    it("platform suspends an agent", async function () {
      const { registry, platform, alice } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await expect(registry.connect(platform).setAgentStatus("search-X", AgentStatus.SUSPENDED))
        .to.emit(registry, "AgentStatusChanged")
        .withArgs("search-X", AgentStatus.ACTIVE, AgentStatus.SUSPENDED);
      expect(await registry.isActive("search-X")).to.be.false;
    });

    it("non-platform cannot change status", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await expect(registry.connect(alice).setAgentStatus("search-X", AgentStatus.SUSPENDED))
        .to.be.reverted;
    });
  });

  // ── Metadata on-chain ─────────────────────────────────────────────────────
  describe("Metadata on-chain", function () {
    it("owner can set and get arbitrary metadata on a token", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await registry.connect(alice).setMetadata(1n, "llmModel", ethers.toUtf8Bytes("gpt-4o"));
      expect(ethers.toUtf8String(await registry.getMetadata(1n, "llmModel"))).to.equal("gpt-4o");
    });

    it("reserved key agentWallet is rejected via setMetadata", async function () {
      const { registry, alice } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await expect(registry.connect(alice).setMetadata(1n, "agentWallet", ethers.toUtf8Bytes("x")))
        .to.be.revertedWithCustomError(registry, "ReservedMetadataKey");
    });

    it("non-owner cannot set metadata", async function () {
      const { registry, alice, bob } = await deploy();
      await registerAgent(registry, alice, "search-X");
      await expect(registry.connect(bob).setMetadata(1n, "key", ethers.toUtf8Bytes("val")))
        .to.be.revertedWithCustomError(registry, "NotAgentOwner");
    });
  });

  // ── ERC-165 / interfaces ──────────────────────────────────────────────────
  describe("ERC-165 / interfaces", function () {
    it("supports ERC-721", async function () {
      const { registry } = await deploy();
      expect(await registry.supportsInterface("0x80ac58cd")).to.be.true;
    });
    it("supports ERC-721Metadata", async function () {
      const { registry } = await deploy();
      expect(await registry.supportsInterface("0x5b5e139f")).to.be.true;
    });
  });
});
