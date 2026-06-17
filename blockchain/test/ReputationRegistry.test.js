// test/ReputationRegistry.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tests de ReputationRegistry (ERC-8004)
//
// Couverture :
//   ✓ Déploiement & initialisation
//   ✓ giveFeedback — cas normaux (user, agent tiers)
//   ✓ giveFeedback — rejet si owner du token tente de noter
//   ✓ giveFeedback — rejet si valueDecimals > 18
//   ✓ giveFeedback — rejet si agentId inexistant
//   ✓ giveFeedback — rejet si registry pas initialisé
//   ✓ setEigenTrustScore — caller autorisé / non autorisé
//   ✓ revokeFeedback
//   ✓ appendResponse (event uniquement)
//   ✓ getSummary — filtrage par tag1/tag2
//   ✓ readFeedback
//   ✓ readAllFeedback
//   ✓ getClients / getLastIndex
//   ✓ NewFeedback event — tous les champs
// ─────────────────────────────────────────────────────────────────────────────

const { ethers } = require("hardhat");
const { expect } = require("chai");

// ── Stub IdentityRegistry minimal ─────────────────────────────────────────────

async function deployStubIdentity(deployer, agents) {
  const Stub = await ethers.getContractFactory("IdentityRegistryStub");
  const stub = await Stub.deploy();
  await stub.waitForDeployment();
  for (const a of agents) {
    await stub.registerAgent(a.agentId, 0, a.owner, a.tokenId);
  }
  return stub;
}

// ── Fixture ───────────────────────────────────────────────────────────────────

async function deploy(agents = []) {
  const [owner, user1, user2, authorizedCaller, agentOwner] =
    await ethers.getSigners();

  const identity = await deployStubIdentity(owner, agents.length
    ? agents
    : [
        { agentId: "researcher", tokenId: 1, owner: agentOwner.address },
        { agentId: "analyst",    tokenId: 2, owner: agentOwner.address },
      ]);

  const RR = await ethers.getContractFactory("ReputationRegistry");
  const rr = await RR.deploy();
  await rr.waitForDeployment();

  await rr.initialize(await identity.getAddress());
  await rr.setAuthorizedCaller(authorizedCaller.address, true);

  return { rr, identity, owner, user1, user2, authorizedCaller, agentOwner };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ReputationRegistry (ERC-8004)", function () {

  // ── Déploiement ──────────────────────────────────────────────────────────

  describe("Déploiement & initialisation", function () {
    it("getIdentityRegistry retourne l'adresse correcte", async function () {
      const { rr, identity } = await deploy();
      expect(await rr.getIdentityRegistry()).to.equal(await identity.getAddress());
    });

    it("giveFeedback échoue si registry non initialisé", async function () {
      const [user1] = await ethers.getSigners();
      const RR = await ethers.getContractFactory("ReputationRegistry");
      const rr = await RR.deploy();
      await rr.waitForDeployment();
      await expect(
        rr.connect(user1).giveFeedback(1, 85n, 0, "starred", "", "", "", ethers.ZeroHash)
      ).to.be.revertedWithCustomError(rr, "RegistryNotInitialized");
    });

    it("setAuthorizedCaller n'est accessible qu'au owner", async function () {
      const { rr, user1 } = await deploy();
      await expect(
        rr.connect(user1).setAuthorizedCaller(user1.address, true)
      ).to.be.reverted;
    });
  });

  // ── giveFeedback ─────────────────────────────────────────────────────────

  describe("giveFeedback", function () {
    it("un user peut noter un agent (starred)", async function () {
      const { rr, user1 } = await deploy();
      await expect(
        rr.connect(user1).giveFeedback(1, 85n, 0, "starred", "", "", "", ethers.ZeroHash)
      ).to.emit(rr, "NewFeedback").withArgs(
        1n, user1.address, 1n, 85n, 0, "starred", "starred", "", "", "", ethers.ZeroHash
      );
    });

    it("feedbackIndex s'incrémente correctement", async function () {
      const { rr, user1 } = await deploy();
      await rr.connect(user1).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user1).giveFeedback(1, 90n, 0, "starred", "", "", "", ethers.ZeroHash);
      expect(await rr.getLastIndex(1, user1.address)).to.equal(2n);
    });

    it("rejet si agentId inexistant", async function () {
      const { rr, user1 } = await deploy();
      await expect(
        rr.connect(user1).giveFeedback(999, 80n, 0, "starred", "", "", "", ethers.ZeroHash)
      ).to.be.revertedWithCustomError(rr, "AgentNotFound");
    });

    it("rejet si owner du token tente de noter son propre agent", async function () {
      const { rr, agentOwner } = await deploy();
      await expect(
        rr.connect(agentOwner).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash)
      ).to.be.revertedWithCustomError(rr, "AgentOwnerCannotRate");
    });

    it("rejet si valueDecimals > 18", async function () {
      const { rr, user1 } = await deploy();
      await expect(
        rr.connect(user1).giveFeedback(1, 100n, 19, "uptime", "", "", "", ethers.ZeroHash)
      ).to.be.revertedWithCustomError(rr, "InvalidValueDecimals");
    });

    it("accepte valueDecimals jusqu'à 18", async function () {
      const { rr, user1 } = await deploy();
      await expect(
        rr.connect(user1).giveFeedback(1, 9977n, 2, "uptime", "", "", "", ethers.ZeroHash)
      ).to.emit(rr, "NewFeedback");
    });

    it("accepte valeurs négatives (int128)", async function () {
      const { rr, user1 } = await deploy();
      await expect(
        rr.connect(user1).giveFeedback(1, -10n, 0, "successRate", "INVALID", "", "", ethers.ZeroHash)
      ).to.emit(rr, "NewFeedback");
    });
  });

  // ── setEigenTrustScore ───────────────────────────────────────────────────

  describe("setEigenTrustScore", function () {
    it("caller autorisé peut écrire un score EigenTrust", async function () {
      const { rr, authorizedCaller } = await deploy();
      await rr.connect(authorizedCaller).setEigenTrustScore(1, 87);
      expect(await rr.eigenTrustScore(1)).to.equal(87n);
    });

    it("owner peut aussi écrire un score EigenTrust", async function () {
      const { rr, owner } = await deploy();
      await rr.connect(owner).setEigenTrustScore(1, 92);
      expect(await rr.eigenTrustScore(1)).to.equal(92n);
    });

    it("caller non autorisé est rejeté", async function () {
      const { rr, user1 } = await deploy();
      await expect(
        rr.connect(user1).setEigenTrustScore(1, 50)
      ).to.be.revertedWithCustomError(rr, "UnauthorizedCaller");
    });

    it("setAuthorizedCaller false révoque l'accès", async function () {
      const { rr, owner, authorizedCaller } = await deploy();
      await rr.connect(owner).setAuthorizedCaller(authorizedCaller.address, false);
      await expect(
        rr.connect(authorizedCaller).setEigenTrustScore(1, 50)
      ).to.be.revertedWithCustomError(rr, "UnauthorizedCaller");
    });
  });

  // ── revokeFeedback ────────────────────────────────────────────────────────

  describe("revokeFeedback", function () {
    it("un user peut révoquer son propre feedback", async function () {
      const { rr, user1 } = await deploy();
      await rr.connect(user1).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash);
      await expect(rr.connect(user1).revokeFeedback(1, 1))
        .to.emit(rr, "FeedbackRevoked").withArgs(1n, user1.address, 1n);
      const [, , , , isRevoked] = await rr.readFeedback(1, user1.address, 1);
      expect(isRevoked).to.be.true;
    });

    it("rejet si feedbackIndex hors limites", async function () {
      const { rr, user1 } = await deploy();
      await expect(
        rr.connect(user1).revokeFeedback(1, 99)
      ).to.be.revertedWithCustomError(rr, "FeedbackIndexOutOfBounds");
    });

    it("getSummary exclut les feedbacks révoqués", async function () {
      const { rr, user1 } = await deploy();
      await rr.connect(user1).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user1).giveFeedback(1, 60n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user1).revokeFeedback(1, 1);
      const [count, avg] = await rr.getSummary(1, [user1.address], "starred", "");
      expect(count).to.equal(1n);
      expect(avg).to.equal(60n);
    });
  });

  // ── appendResponse ────────────────────────────────────────────────────────

  describe("appendResponse", function () {
    it("n'importe qui peut appendre une réponse (event)", async function () {
      const { rr, user1, user2 } = await deploy();
      await rr.connect(user1).giveFeedback(1, 50n, 0, "starred", "", "", "", ethers.ZeroHash);
      await expect(
        rr.connect(user2).appendResponse(1, user1.address, 1, "ipfs://QmResponse", ethers.ZeroHash)
      ).to.emit(rr, "ResponseAppended").withArgs(1n, user1.address, 1n, user2.address, "ipfs://QmResponse", ethers.ZeroHash);
    });

    it("rejet si feedbackIndex invalide", async function () {
      const { rr, user1, user2 } = await deploy();
      await expect(
        rr.connect(user2).appendResponse(1, user1.address, 99, "ipfs://Qm", ethers.ZeroHash)
      ).to.be.revertedWithCustomError(rr, "FeedbackIndexOutOfBounds");
    });
  });

  // ── getSummary ────────────────────────────────────────────────────────────

  describe("getSummary", function () {
    it("calcule la moyenne correctement", async function () {
      const { rr, user1, user2 } = await deploy();
      await rr.connect(user1).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user2).giveFeedback(1, 60n, 0, "starred", "", "", "", ethers.ZeroHash);
      const [count, avg] = await rr.getSummary(1, [user1.address, user2.address], "starred", "");
      expect(count).to.equal(2n);
      expect(avg).to.equal(70n);
    });

    it("filtre par tag1", async function () {
      const { rr, authorizedCaller, user1 } = await deploy();
      // authorizedCaller note en "uptime"
      await rr.connect(user1).giveFeedback(1, 95n, 2, "uptime", "", "", "", ethers.ZeroHash);
      await rr.connect(user1).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash);
      const [count] = await rr.getSummary(1, [user1.address], "uptime", "");
      expect(count).to.equal(1n);
    });

    it("filtre par tag1+tag2", async function () {
      const { rr, user1, user2 } = await deploy();
      await rr.connect(user1).giveFeedback(1, 80n, 0, "successRate", "VALID",   "", "", ethers.ZeroHash);
      await rr.connect(user2).giveFeedback(1, 20n, 0, "successRate", "INVALID", "", "", ethers.ZeroHash);
      const [countValid]   = await rr.getSummary(1, [user1.address, user2.address], "successRate", "VALID");
      const [countInvalid] = await rr.getSummary(1, [user1.address, user2.address], "successRate", "INVALID");
      expect(countValid).to.equal(1n);
      expect(countInvalid).to.equal(1n);
    });

    it("rejet si clientAddresses vide", async function () {
      const { rr } = await deploy();
      await expect(
        rr.getSummary(1, [], "starred", "")
      ).to.be.revertedWith("clientAddresses required");
    });
  });

  // ── readAllFeedback ───────────────────────────────────────────────────────

  describe("readAllFeedback", function () {
    it("retourne tous les feedbacks sans filtre", async function () {
      const { rr, user1, user2 } = await deploy();
      await rr.connect(user1).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user2).giveFeedback(1, 90n, 0, "starred", "", "", "", ethers.ZeroHash);
      const [clients, , values] = await rr.readAllFeedback(1, [], "", "", false);
      expect(clients.length).to.equal(2);
      expect(values[0]).to.equal(80n);
      expect(values[1]).to.equal(90n);
    });

    it("includeRevoked=false exclut les révoqués", async function () {
      const { rr, user1 } = await deploy();
      await rr.connect(user1).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user1).giveFeedback(1, 90n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user1).revokeFeedback(1, 1);
      const [, , values] = await rr.readAllFeedback(1, [user1.address], "", "", false);
      expect(values.length).to.equal(1);
      expect(values[0]).to.equal(90n);
    });
  });

  // ── getClients / getLastIndex ─────────────────────────────────────────────

  describe("getClients / getLastIndex", function () {
    it("getClients retourne les adresses uniques", async function () {
      const { rr, user1, user2 } = await deploy();
      await rr.connect(user1).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user1).giveFeedback(1, 85n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user2).giveFeedback(1, 70n, 0, "starred", "", "", "", ethers.ZeroHash);
      const clients = await rr.getClients(1);
      expect(clients.length).to.equal(2);
      expect(clients).to.include(user1.address);
      expect(clients).to.include(user2.address);
    });

    it("getLastIndex retourne le bon compteur", async function () {
      const { rr, user1 } = await deploy();
      expect(await rr.getLastIndex(1, user1.address)).to.equal(0n);
      await rr.connect(user1).giveFeedback(1, 80n, 0, "starred", "", "", "", ethers.ZeroHash);
      await rr.connect(user1).giveFeedback(1, 90n, 0, "starred", "", "", "", ethers.ZeroHash);
      expect(await rr.getLastIndex(1, user1.address)).to.equal(2n);
    });
  });

  // ── Scénario intégration : flux complet marketplace ──────────────────────

  describe("Scénario marketplace complet", function () {
    it("user donne 5 étoiles + EigenTrust mis à jour → getSummary + eigenTrustScore cohérents", async function () {
      const { rr, owner, authorizedCaller, user1 } = await deploy();

      // Plateforme écrit le score EigenTrust après calcul off-chain
      await rr.connect(authorizedCaller).setEigenTrustScore(1, 88);
      expect(await rr.eigenTrustScore(1)).to.equal(88n);

      // User → 5 étoiles (100 starred)
      await rr.connect(user1).giveFeedback(1, 100n, 0, "starred", "", "", "", ethers.ZeroHash);

      // Résumé starred
      const [cntStar, avgStar] = await rr.getSummary(1, [user1.address], "starred", "");
      expect(cntStar).to.equal(1n);
      expect(avgStar).to.equal(100n);

      // Score EigenTrust indépendant du feedback on-chain
      expect(await rr.eigenTrustScore(1)).to.equal(88n);

      // 1 client enregistré
      const clients = await rr.getClients(1);
      expect(clients.length).to.equal(1);
    });
  });

});
