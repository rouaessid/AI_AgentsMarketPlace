// test/ValidationRegistry.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tests complets de ValidationRegistry
// Framework : Hardhat + ethers v6 + chai
//
// Couverture :
//   ✓ Deploy & configuration
//   ✓ validationRequest (étape 1)
//   ✓ assignJudges      (étape 2)
//   ✓ commitVote        (étape 3)
//   ✓ revealVote        (étape 4)
//   ✓ finaliseValidation (étape 5) → VALID / INVALID / DISPUTED
//   ✓ expireTask
//   ✓ ERC-8004 read functions
//   ✓ Slash provider et juges déviants
//   ✓ Réputation via ReputationRegistry stub
//   ✓ Cas d'erreur (wrong status, wrong wallet, bad reveal, etc.)
// ─────────────────────────────────────────────────────────────────────────────

const { ethers } = require("hardhat");
const { expect } = require("chai");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Calcule le commitHash d'un juge.
 * vote : 1 = VALID, 2 = INVALID  (InternalVote enum)
 */
function makeCommitHash(vote, salt) {
  // keccak256(abi.encode(vote, salt)) — ethers v6
  return ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(["uint8", "bytes32"], [vote, salt])
  );
}

const VOTE_VALID = 1;
const VOTE_INVALID = 2;

const COMMIT_WINDOW = 3600;  // 1 hour
const REVEAL_WINDOW = 3600;  // 1 hour
const STAKE_LOCK_DURATION = 10800; // 3 hours

// ── Fixtures ──────────────────────────────────────────────────────────────────

/**
 * Déploie des stubs minimalistes d'IdentityRegistry et StakingContract,
 * puis le vrai ValidationRegistry.
 *
 * Stub IdentityRegistry :
 *   - agents enregistrés en mémoire
 *   - getAgentType / isActive / agentIdExists / getAgentWallet / getCurrentTokenId
 *
 * Stub StakingContract :
 *   - enregistre les appels lock/unlock/slash
 *   - isEligibleProvider / isEligibleJudge retournent true par défaut
 *   - isLocked retourne false par défaut (configurable)
 *
 * Stub ReputationRegistry :
 *   - enregistre les appels recordReputation
 */
async function deployFixture() {
  const signers = await ethers.getSigners();
  const [owner, providerOwner, judge0, judge1, judge2, platformWallet, other] = signers;

  // ── Stub IdentityRegistry ─────────────────────────────────────────────────
  // On utilise un contrat inline déployé via ContractFactory depuis bytecode
  // → plus simple : on déploie les vrais contrats avec stubs via des mocks Solidity.
  // Pour les tests unitaires on utilise des fakes deployés.

  const IdentityStubFactory = await ethers.getContractFactory("IdentityRegistryStub");
  const identityStub = await IdentityStubFactory.deploy();
  await identityStub.waitForDeployment();

  const StakingStubFactory = await ethers.getContractFactory("StakingContractStub");
  const stakingStub = await StakingStubFactory.deploy();
  await stakingStub.waitForDeployment();

  const ReputationStubFactory = await ethers.getContractFactory("ReputationRegistryStub");
  const reputationStub = await ReputationStubFactory.deploy();
  await reputationStub.waitForDeployment();

  const EscrowStubFactory = await ethers.getContractFactory("EscrowManagerStub");
  const escrowStub = await EscrowStubFactory.deploy();
  await escrowStub.waitForDeployment();

  // ── ValidationRegistry ────────────────────────────────────────────────────
  const ValidationFactory = await ethers.getContractFactory("ValidationRegistry");
  const validation = await ValidationFactory.deploy(
    await identityStub.getAddress(),
    await stakingStub.getAddress(),
    await reputationStub.getAddress()
  );
  await validation.waitForDeployment();

  // Link components
  await validation.setEscrowManager(await escrowStub.getAddress());

  // Autoriser ValidationRegistry à appeler le stub staking
  await stakingStub.setValidationRegistry(await validation.getAddress());

  // ── Enregistrer agents dans le stub identity ──────────────────────────────
  // Provider : agentId = "provider-1", tokenId = 1, wallet = providerOwner
  await identityStub.registerAgent("provider-1", 0, providerOwner.address, 1); // type 0 = PROVIDER

  // Judges : type 1 = JUDGE, wallets = judge0 / judge1 / judge2
  await identityStub.registerAgent("judge-0", 1, judge0.address, 10);
  await identityStub.registerAgent("judge-1", 1, judge1.address, 11);
  await identityStub.registerAgent("judge-2", 1, judge2.address, 12);

  const CANDIDATES = ["judge-0", "judge-1", "judge-2"];

  return {
    validation,
    identityStub,
    stakingStub,
    reputationStub,
    escrowStub,
    owner,
    providerOwner,
    judge0,
    judge1,
    judge2,
    platformWallet,
    other,
    CANDIDATES,
  };
}

// ── Helpers de flow ──────────────────────────────────────────────────────────

async function doRequest(validation, providerOwner, taskId = "task-1") {
  const requestHash = ethers.keccak256(ethers.toUtf8Bytes("result-payload-" + taskId));
  await validation.connect(providerOwner).validationRequest(
    taskId,
    "provider-1",
    "ipfs://QmResult",
    requestHash
  );
  return requestHash;
}

async function doAssign(validation, owner, taskId, candidates) {
  await validation.connect(owner).assignJudges(taskId, candidates);
}

async function doCommit(validation, judge, judgeId, taskId, vote, salt) {
  const commitHash = makeCommitHash(vote, salt);
  await validation.connect(judge).commitVote(taskId, judgeId, commitHash);
  return commitHash;
}

async function doReveal(validation, judge, judgeId, taskId, vote, salt) {
  await validation.connect(judge).revealVote(taskId, judgeId, vote, salt);
}

async function fullFlow(ctx, votes = [VOTE_VALID, VOTE_VALID, VOTE_INVALID]) {
  const { validation, owner, providerOwner, judge0, judge1, judge2, CANDIDATES } = ctx;
  const taskId = "task-full";
  const salts = [
    ethers.randomBytes(32),
    ethers.randomBytes(32),
    ethers.randomBytes(32),
  ];

  const requestHash = await doRequest(validation, providerOwner, taskId);
  await doAssign(validation, owner, taskId, CANDIDATES);

  await doCommit(validation, judge0, "judge-0", taskId, votes[0], salts[0]);
  await doCommit(validation, judge1, "judge-1", taskId, votes[1], salts[1]);
  await doCommit(validation, judge2, "judge-2", taskId, votes[2], salts[2]);

  await doReveal(validation, judge0, "judge-0", taskId, votes[0], salts[0]);
  await doReveal(validation, judge1, "judge-1", taskId, votes[1], salts[1]);
  await doReveal(validation, judge2, "judge-2", taskId, votes[2], salts[2]);

  return { taskId, requestHash, salts };
}

// ═════════════════════════════════════════════════════════════════════════════
//  TESTS
// ═════════════════════════════════════════════════════════════════════════════

describe("ValidationRegistry", function () {

  // ── Deploy ─────────────────────────────────────────────────────────────────
  describe("Deployment", function () {
    it("stores sibling addresses", async function () {
      const ctx = await deployFixture();
      expect(await ctx.validation.identityRegistry())
        .to.equal(await ctx.identityStub.getAddress());
      expect(await ctx.validation.stakingContract())
        .to.equal(await ctx.stakingStub.getAddress());
      expect(await ctx.validation.reputationRegistry())
        .to.equal(await ctx.reputationStub.getAddress());
    });

    it("reverts if any sibling is address(0)", async function () {
      const F = await ethers.getContractFactory("ValidationRegistry");
      await expect(F.deploy(ethers.ZeroAddress, ethers.ZeroAddress, ethers.ZeroAddress))
        .to.be.revertedWithCustomError(await F.deploy(
          // dummy deploy just to get the error interface — we test via a real deploy
          ethers.Wallet.createRandom().address,
          ethers.Wallet.createRandom().address,
          ethers.Wallet.createRandom().address
        ).then(() => F.deploy(ethers.ZeroAddress, ethers.ZeroAddress, ethers.ZeroAddress))
          .catch(() => F.attach(ethers.ZeroAddress)), "ZeroAddress");
    });

    it("owner is deployer", async function () {
      const ctx = await deployFixture();
      expect(await ctx.validation.owner()).to.equal(ctx.owner.address);
    });
  });

  // ── Step 1 : validationRequest ────────────────────────────────────────────
  describe("validationRequest", function () {
    it("creates task and emits ValidationRequest (ERC-8004)", async function () {
      const ctx = await deployFixture();
      const requestHash = ethers.keccak256(ethers.toUtf8Bytes("payload"));

      await expect(
        ctx.validation.connect(ctx.providerOwner).validationRequest(
          "task-1", "provider-1", "ipfs://QmResult", requestHash
        )
      )
        .to.emit(ctx.validation, "ValidationRequest")
        .withArgs(await ctx.validation.getAddress(), 1, "ipfs://QmResult", requestHash);
    });

    it("task status is PENDING after request", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(0); // PENDING = 0
    });

    it("stores ERC-8004 record with tag PENDING", async function () {
      const ctx = await deployFixture();
      const requestHash = await doRequest(ctx.validation, ctx.providerOwner);
      const rec = await ctx.validation.getValidationStatus(requestHash);
      expect(rec.tag).to.equal("PENDING");
      expect(rec.validatorAddress).to.equal(await ctx.validation.getAddress());
      expect(rec.agentId).to.equal(1n); // tokenId du provider
    });

    it("reverts on duplicate taskId", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await expect(doRequest(ctx.validation, ctx.providerOwner))
        .to.be.revertedWithCustomError(ctx.validation, "TaskAlreadyExists");
    });

    it("reverts if provider not active", async function () {
      const ctx = await deployFixture();
      await ctx.identityStub.setActive("provider-1", false);
      const rh = ethers.keccak256(ethers.toUtf8Bytes("x"));
      await expect(
        ctx.validation.connect(ctx.providerOwner).validationRequest(
          "task-x", "provider-1", "ipfs://x", rh
        )
      ).to.be.revertedWithCustomError(ctx.validation, "ProviderIneligible");
    });

    it("reverts if provider type is JUDGE", async function () {
      const ctx = await deployFixture();
      const rh = ethers.keccak256(ethers.toUtf8Bytes("x"));
      await expect(
        ctx.validation.connect(ctx.judge0).validationRequest(
          "task-x", "judge-0", "ipfs://x", rh
        )
      ).to.be.revertedWithCustomError(ctx.validation, "ProviderIneligible");
    });

    it("reverts if provider stake insufficient", async function () {
      const ctx = await deployFixture();
      await ctx.stakingStub.setEligibleProvider(ctx.providerOwner.address, false);
      const rh = ethers.keccak256(ethers.toUtf8Bytes("x"));
      await expect(
        ctx.validation.connect(ctx.providerOwner).validationRequest(
          "task-x", "provider-1", "ipfs://x", rh
        )
      ).to.be.revertedWithCustomError(ctx.validation, "ProviderIneligible");
    });

    it("locks provider stake", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      expect(await ctx.stakingStub.lockCount(ctx.providerOwner.address)).to.equal(1n);
    });
  });

  // ── Step 2 : assignJudges ─────────────────────────────────────────────────
  describe("assignJudges", function () {
    it("assigns 3 judges and emits JudgesAssigned", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);

      await expect(ctx.validation.connect(ctx.owner).assignJudges("task-1", ctx.CANDIDATES))
        .to.emit(ctx.validation, "JudgesAssigned");
    });

    it("task status is COMMITTING after assign", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(1); // COMMITTING = 1
    });

    it("judges are marked busy", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      expect(await ctx.validation.isJudgeBusy("judge-0")).to.equal(true);
      expect(await ctx.validation.isJudgeBusy("judge-1")).to.equal(true);
      expect(await ctx.validation.isJudgeBusy("judge-2")).to.equal(true);
    });

    it("reverts if not owner", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await expect(
        ctx.validation.connect(ctx.other).assignJudges("task-1", ctx.CANDIDATES)
      ).to.be.revertedWithCustomError(ctx.validation, "OwnableUnauthorizedAccount");
    });

    it("reverts if not enough eligible judges", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      // Rendre les juges inéligibles
      await ctx.stakingStub.setEligibleJudge(ctx.judge0.address, false);
      await ctx.stakingStub.setEligibleJudge(ctx.judge1.address, false);
      await expect(
        ctx.validation.connect(ctx.owner).assignJudges("task-1", ctx.CANDIDATES)
      ).to.be.revertedWithCustomError(ctx.validation, "NotEnoughEligibleJudges");
    });

    it("reverts if wrong status", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await expect(
        ctx.validation.connect(ctx.owner).assignJudges("task-1", ctx.CANDIDATES)
      ).to.be.revertedWithCustomError(ctx.validation, "WrongStatus");
    });

    it("reverts if too many candidates", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      const tooMany = Array(21).fill("judge-0");
      await expect(
        ctx.validation.connect(ctx.owner).assignJudges("task-1", tooMany)
      ).to.be.revertedWithCustomError(ctx.validation, "TooManyCandidates");
    });
  });

  // ── Step 3 : commitVote ───────────────────────────────────────────────────
  describe("commitVote", function () {
    it("accepts commit and emits VoteCommitted", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      const salt = ethers.randomBytes(32);
      const commitHash = makeCommitHash(VOTE_VALID, salt);

      await expect(
        ctx.validation.connect(ctx.judge0).commitVote("task-1", "judge-0", commitHash)
      )
        .to.emit(ctx.validation, "VoteCommitted")
        .withArgs("task-1", "judge-0");
    });

    it("transitions to REVEALING when all 3 committed", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      const s0 = ethers.randomBytes(32);
      const s1 = ethers.randomBytes(32);
      const s2 = ethers.randomBytes(32);
      await doCommit(ctx.validation, ctx.judge0, "judge-0", "task-1", VOTE_VALID, s0);
      await doCommit(ctx.validation, ctx.judge1, "judge-1", "task-1", VOTE_VALID, s1);
      await doCommit(ctx.validation, ctx.judge2, "judge-2", "task-1", VOTE_VALID, s2);

      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(2); // REVEALING = 2
    });

    it("reverts if commit window closed", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await time.increase(COMMIT_WINDOW + 1);

      const salt = ethers.randomBytes(32);
      const commitHash = makeCommitHash(VOTE_VALID, salt);
      await expect(
        ctx.validation.connect(ctx.judge0).commitVote("task-1", "judge-0", commitHash)
      ).to.be.revertedWithCustomError(ctx.validation, "CommitWindowClosed");
    });

    it("reverts if wrong wallet", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      const commitHash = makeCommitHash(VOTE_VALID, ethers.randomBytes(32));
      await expect(
        ctx.validation.connect(ctx.other).commitVote("task-1", "judge-0", commitHash)
      ).to.be.revertedWithCustomError(ctx.validation, "CallerNotJudgeWallet");
    });

    it("reverts on double commit", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      const salt = ethers.randomBytes(32);
      const commitHash = makeCommitHash(VOTE_VALID, salt);
      await ctx.validation.connect(ctx.judge0).commitVote("task-1", "judge-0", commitHash);
      await expect(
        ctx.validation.connect(ctx.judge0).commitVote("task-1", "judge-0", commitHash)
      ).to.be.revertedWithCustomError(ctx.validation, "AlreadyCommitted");
    });
  });

  // ── Step 4 : revealVote ───────────────────────────────────────────────────
  describe("revealVote", function () {
    it("accepts reveal and emits VoteRevealed", async function () {
      const ctx = await deployFixture();
      const salt = ethers.randomBytes(32);
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await doCommit(ctx.validation, ctx.judge0, "judge-0", "task-1", VOTE_VALID, salt);
      await doCommit(ctx.validation, ctx.judge1, "judge-1", "task-1", VOTE_VALID, ethers.randomBytes(32));
      await doCommit(ctx.validation, ctx.judge2, "judge-2", "task-1", VOTE_VALID, ethers.randomBytes(32));

      await expect(
        ctx.validation.connect(ctx.judge0).revealVote("task-1", "judge-0", VOTE_VALID, salt)
      )
        .to.emit(ctx.validation, "VoteRevealed")
        .withArgs("task-1", "judge-0", VOTE_VALID);
    });

    it("reverts on wrong salt", async function () {
      const ctx = await deployFixture();
      const salt = ethers.randomBytes(32);
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await doCommit(ctx.validation, ctx.judge0, "judge-0", "task-1", VOTE_VALID, salt);
      await doCommit(ctx.validation, ctx.judge1, "judge-1", "task-1", VOTE_VALID, ethers.randomBytes(32));
      await doCommit(ctx.validation, ctx.judge2, "judge-2", "task-1", VOTE_VALID, ethers.randomBytes(32));

      await expect(
        ctx.validation.connect(ctx.judge0).revealVote(
          "task-1", "judge-0", VOTE_VALID, ethers.randomBytes(32) // mauvais salt
        )
      ).to.be.revertedWithCustomError(ctx.validation, "CommitMismatch");
    });

    it("reverts if reveal window closed", async function () {
      const ctx = await deployFixture();
      const salt = ethers.randomBytes(32);
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await doCommit(ctx.validation, ctx.judge0, "judge-0", "task-1", VOTE_VALID, salt);
      await doCommit(ctx.validation, ctx.judge1, "judge-1", "task-1", VOTE_VALID, ethers.randomBytes(32));
      await doCommit(ctx.validation, ctx.judge2, "judge-2", "task-1", VOTE_VALID, ethers.randomBytes(32));

      await time.increase(COMMIT_WINDOW + REVEAL_WINDOW + 1);

      await expect(
        ctx.validation.connect(ctx.judge0).revealVote("task-1", "judge-0", VOTE_VALID, salt)
      ).to.be.revertedWithCustomError(ctx.validation, "RevealWindowClosed");
    });

    it("transitions COMMITTING → REVEALING after commit deadline if not all committed", async function () {
      const ctx = await deployFixture();
      const salt = ethers.randomBytes(32);
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      // Seul judge-0 commit
      await doCommit(ctx.validation, ctx.judge0, "judge-0", "task-1", VOTE_VALID, salt);

      // On dépasse la deadline commit
      await time.increase(COMMIT_WINDOW + 1);

      // revealVote doit forcer la transition
      await expect(
        ctx.validation.connect(ctx.judge0).revealVote("task-1", "judge-0", VOTE_VALID, salt)
      ).to.emit(ctx.validation, "VoteRevealed");

      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(2); // REVEALING
    });
  });

  // ── Step 5 : finaliseValidation — VALID ───────────────────────────────────
  describe("finaliseValidation — verdict VALID (2 VALID, 1 INVALID)", function () {
    it("emits ValidationResponse with response=100 tag=VALID", async function () {
      const ctx = await deployFixture();
      const { taskId, requestHash } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);

      await expect(
        ctx.validation.connect(ctx.owner).finaliseValidation(taskId, 85, "ipfs://QmJustif")
      )
        .to.emit(ctx.validation, "ValidationResponse")
        .withArgs(
          await ctx.validation.getAddress(),
          1n,          // erc8004AgentId = tokenId provider
          requestHash,
          100,         // RESPONSE_VALID
          "ipfs://QmJustif",
          // responseHash (any) — on ne vérifie pas la valeur exacte ici
          (v) => typeof v === "string" || typeof v === "bigint",
          "VALID"
        );
    });

    it("task status is FINALISED", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");
      const task = await ctx.validation.getTask(taskId);
      expect(task.status).to.equal(3); // FINALISED = 3
    });

    it("provider reputation increased", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");

      const calls = await ctx.reputationStub.getCalls("provider-1");
      expect(calls.length).to.be.greaterThan(0);
      const lastCall = calls[calls.length - 1];
      expect(lastCall.isIncrease).to.equal(true);
      expect(lastCall.reason).to.equal("VALID");
    });

    it("deviant judge (voted INVALID) slashed", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await expect(
        ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif")
      ).to.emit(ctx.validation, "JudgeSlashed")
        .withArgs("judge-2", ctx.judge2.address, (v) => v >= 0n, "DEVIATED");
    });

    it("deviant judge reputation decreased", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");

      const calls = await ctx.reputationStub.getCalls("judge-2");
      const deviated = calls.find(c => c.reason === "DEVIATED");
      expect(deviated).to.not.be.undefined;
      expect(deviated.isIncrease).to.equal(false);
    });

    it("consensus judges reputation increased", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");

      for (const jid of ["judge-0", "judge-1"]) {
        const calls = await ctx.reputationStub.getCalls(jid);
        const consensus = calls.find(c => c.reason === "CONSENSUS");
        expect(consensus, `${jid} should have CONSENSUS`).to.not.be.undefined;
        expect(consensus.isIncrease).to.equal(true);
      }
    });

    it("provider stake unlocked after finalise", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");
      expect(await ctx.stakingStub.unlockCount(ctx.providerOwner.address)).to.equal(1n);
    });

    it("judges freed after finalise", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");
      expect(await ctx.validation.isJudgeBusy("judge-0")).to.equal(false);
      expect(await ctx.validation.isJudgeBusy("judge-1")).to.equal(false);
      expect(await ctx.validation.isJudgeBusy("judge-2")).to.equal(false);
    });

    it("calls escrow releaseFunds on VALID", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");
      expect(await ctx.escrowStub.releaseCount()).to.equal(1n);
      expect(await ctx.escrowStub.lastTaskId()).to.equal(taskId);
    });
  });

  // ── Step 5 : finaliseValidation — INVALID ────────────────────────────────
  describe("finaliseValidation — verdict INVALID (2 INVALID, 1 VALID)", function () {
    it("emits ValidationResponse with response=0 tag=INVALID", async function () {
      const ctx = await deployFixture();
      const { taskId, requestHash } = await fullFlow(ctx, [VOTE_INVALID, VOTE_INVALID, VOTE_VALID]);

      await expect(
        ctx.validation.finaliseValidation(taskId, 20, "ipfs://QmJustif")
      )
        .to.emit(ctx.validation, "ValidationResponse")
        .withArgs(
          await ctx.validation.getAddress(), 1n, requestHash,
          0, "ipfs://QmJustif", (v) => true, "INVALID"
        );
    });

    it("provider slashed and emits ProviderSlashed", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_INVALID, VOTE_INVALID, VOTE_VALID]);
      await expect(ctx.validation.finaliseValidation(taskId, 20, "ipfs://QmJustif"))
        .to.emit(ctx.validation, "ProviderSlashed");
    });

    it("provider reputation decreased", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_INVALID, VOTE_INVALID, VOTE_VALID]);
      await ctx.validation.finaliseValidation(taskId, 20, "ipfs://QmJustif");
      const calls = await ctx.reputationStub.getCalls("provider-1");
      const invalid = calls.find(c => c.reason === "INVALID");
      expect(invalid.isIncrease).to.equal(false);
    });

    it("deviant judge (voted VALID) slashed with reason DEVIATED", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_INVALID, VOTE_INVALID, VOTE_VALID]);
      await expect(ctx.validation.finaliseValidation(taskId, 20, "ipfs://QmJustif"))
        .to.emit(ctx.validation, "JudgeSlashed")
        .withArgs("judge-2", ctx.judge2.address, (v) => v >= 0n, "DEVIATED");
    });

    it("calls escrow refundClient on INVALID", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_INVALID, VOTE_INVALID, VOTE_VALID]);
      await ctx.validation.finaliseValidation(taskId, 20, "ipfs://QmJustif");
      expect(await ctx.escrowStub.refundCount()).to.equal(1n);
      expect(await ctx.escrowStub.lastTaskId()).to.equal(taskId);
    });
  });

  // ── Step 5 : finaliseValidation — DISPUTED ───────────────────────────────
  describe("finaliseValidation — verdict DISPUTED (1V/1I/1V = tie)", function () {
    it("tag=DISPUTED, response=50, no slash", async function () {
      const ctx = await deployFixture();
      // 1 VALID, 1 INVALID, 1 VALID → 2 VALID 1 INVALID → VALID en fait
      // Pour avoir DISPUTED : 1 VALID, 1 INVALID et 1 absent (not revealed)
      // On fait : judge2 ne reveal pas → 1V + 1I + absent → pas de majorité
      const taskId = "task-disp";
      const salts = [ethers.randomBytes(32), ethers.randomBytes(32), ethers.randomBytes(32)];

      await doRequest(ctx.validation, ctx.providerOwner, taskId);
      await doAssign(ctx.validation, ctx.owner, taskId, ctx.CANDIDATES);

      await doCommit(ctx.validation, ctx.judge0, "judge-0", taskId, VOTE_VALID, salts[0]);
      await doCommit(ctx.validation, ctx.judge1, "judge-1", taskId, VOTE_INVALID, salts[1]);
      // judge2 ne commit pas

      // Passer la deadline commit
      await time.increase(COMMIT_WINDOW + 1);

      // judge0 et judge1 reveal
      await doReveal(ctx.validation, ctx.judge0, "judge-0", taskId, VOTE_VALID, salts[0]);
      await doReveal(ctx.validation, ctx.judge1, "judge-1", taskId, VOTE_INVALID, salts[1]);

      // Passer reveal deadline
      await time.increase(REVEAL_WINDOW + 1);

      const requestHash = (await ctx.validation.getTask(taskId)).requestHash;

      await expect(ctx.validation.finaliseValidation(taskId, 50, "ipfs://QmJustif"))
        .to.emit(ctx.validation, "ValidationResponse")
        .withArgs(
          await ctx.validation.getAddress(), 1n, requestHash,
          50, "ipfs://QmJustif", (v) => true, "DISPUTED"
        );

      // Pas de ProviderSlashed
      const filter = ctx.validation.filters.ProviderSlashed();
      const events = await ctx.validation.queryFilter(filter);
      expect(events.length).to.equal(0);
    });
  });

  // ── Score validation ──────────────────────────────────────────────────────
  describe("finaliseValidation — score", function () {
    it("reverts if score > 100", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await expect(
        ctx.validation.finaliseValidation(taskId, 101, "ipfs://QmJustif")
      ).to.be.revertedWithCustomError(ctx.validation, "InvalidScore");
    });

    it("stores aggregated score in task", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 77, "ipfs://QmJustif");
      const task = await ctx.validation.getTask(taskId);
      expect(task.score).to.equal(77n);
    });

    it("reverts if reveal window still open", async function () {
      const ctx = await deployFixture();
      const taskId = "task-open";
      const salts = [ethers.randomBytes(32), ethers.randomBytes(32), ethers.randomBytes(32)];
      await doRequest(ctx.validation, ctx.providerOwner, taskId);
      await doAssign(ctx.validation, ctx.owner, taskId, ctx.CANDIDATES);
      await doCommit(ctx.validation, ctx.judge0, "judge-0", taskId, VOTE_VALID, salts[0]);
      await doCommit(ctx.validation, ctx.judge1, "judge-1", taskId, VOTE_VALID, salts[1]);
      await doCommit(ctx.validation, ctx.judge2, "judge-2", taskId, VOTE_VALID, salts[2]);
      await doReveal(ctx.validation, ctx.judge0, "judge-0", taskId, VOTE_VALID, salts[0]);
      // judge1 et judge2 n'ont pas encore révélé → fenêtre ouverte
      await expect(
        ctx.validation.finaliseValidation(taskId, 80, "ipfs://")
      ).to.be.revertedWithCustomError(ctx.validation, "RevealWindowStillOpen");
    });
  });

  // ── expireTask ────────────────────────────────────────────────────────────
  describe("expireTask", function () {
    it("expires COMMITTING task after commit deadline", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await time.increase(COMMIT_WINDOW + 1);

      await expect(ctx.validation.expireTask("task-1"))
        .to.emit(ctx.validation, "TaskExpired").withArgs("task-1");

      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(4); // EXPIRED = 4
    });

    it("slashes absent judges on expire", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await time.increase(COMMIT_WINDOW + 1);
      await ctx.validation.expireTask("task-1");
      // Tous les juges absents (aucun commit)
      expect(await ctx.stakingStub.slashCount(ctx.judge0.address)).to.equal(1n);
      expect(await ctx.stakingStub.slashCount(ctx.judge1.address)).to.equal(1n);
      expect(await ctx.stakingStub.slashCount(ctx.judge2.address)).to.equal(1n);
    });

    it("absent judges reputation decreased on expire", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await time.increase(COMMIT_WINDOW + 1);
      await ctx.validation.expireTask("task-1");

      for (const jid of ["judge-0", "judge-1", "judge-2"]) {
        const calls = await ctx.reputationStub.getCalls(jid);
        const absent = calls.find(c => c.reason === "ABSENT");
        expect(absent, `${jid} should have ABSENT reputation call`).to.not.be.undefined;
        expect(absent.isIncrease).to.equal(false);
      }
    });

    it("reverts if not yet expirable", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await expect(ctx.validation.expireTask("task-1"))
        .to.be.revertedWithCustomError(ctx.validation, "NotExpirable");
    });

    it("emits ValidationResponse with tag EXPIRED", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await time.increase(COMMIT_WINDOW + 1);

      await expect(ctx.validation.expireTask("task-1"))
        .to.emit(ctx.validation, "ValidationResponse");
    });
  });

  // ── ERC-8004 Read Functions ───────────────────────────────────────────────
  describe("ERC-8004 read functions", function () {
    it("getValidationStatus returns correct fields after finalise", async function () {
      const ctx = await deployFixture();
      const { taskId, requestHash } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");

      const rec = await ctx.validation.getValidationStatus(requestHash);
      expect(rec.validatorAddress).to.equal(await ctx.validation.getAddress());
      expect(rec.agentId).to.equal(1n);
      expect(rec.response).to.equal(100); // VALID
      expect(rec.tag).to.equal("VALID");
    });

    it("getAgentValidations returns requestHashes for agent", async function () {
      const ctx = await deployFixture();
      const rh1 = await doRequest(ctx.validation, ctx.providerOwner, "task-a");
      const rh2 = await doRequest(ctx.validation, ctx.providerOwner, "task-b");

      const hashes = await ctx.validation.getAgentValidations(1n); // tokenId=1
      expect(hashes).to.include(rh1);
      expect(hashes).to.include(rh2);
    });

    it("getValidatorRequests returns all requestHashes", async function () {
      const ctx = await deployFixture();
      const rh1 = await doRequest(ctx.validation, ctx.providerOwner, "task-x");
      const hashes = await ctx.validation.getValidatorRequests(await ctx.validation.getAddress());
      expect(hashes).to.include(rh1);
    });

    it("getSummary count=1 averageResponse=100 after VALID", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");

      const summary = await ctx.validation.getSummary(1n, [], "");
      expect(summary.count).to.equal(1n);
      expect(summary.averageResponse).to.equal(100);
    });

    it("getSummary filters by tag", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, 85, "ipfs://QmJustif");

      const validSummary = await ctx.validation.getSummary(1n, [], "VALID");
      const invalidSummary = await ctx.validation.getSummary(1n, [], "INVALID");
      expect(validSummary.count).to.equal(1n);
      expect(invalidSummary.count).to.equal(0n);
    });
  });

  // ── isEligibleJudgeCandidate view ─────────────────────────────────────────
  describe("isEligibleJudgeCandidate", function () {
    it("returns true for valid judge", async function () {
      const ctx = await deployFixture();
      expect(await ctx.validation.isEligibleJudgeCandidate("judge-0")).to.equal(true);
    });

    it("returns false for provider", async function () {
      const ctx = await deployFixture();
      expect(await ctx.validation.isEligibleJudgeCandidate("provider-1")).to.equal(false);
    });

    it("returns false for inactive judge", async function () {
      const ctx = await deployFixture();
      await ctx.identityStub.setActive("judge-0", false);
      expect(await ctx.validation.isEligibleJudgeCandidate("judge-0")).to.equal(false);
    });

    it("returns false for judge already busy", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      expect(await ctx.validation.isEligibleJudgeCandidate("judge-0")).to.equal(false);
    });
  });

  // ── Admin setters ─────────────────────────────────────────────────────────
  describe("Admin setters", function () {
    it("owner can update sibling addresses", async function () {
      const ctx = await deployFixture();
      const addr = ethers.Wallet.createRandom().address;
      await ctx.validation.connect(ctx.owner).setReputationRegistry(addr);
      expect(await ctx.validation.reputationRegistry()).to.equal(addr);
    });

    it("non-owner cannot update siblings", async function () {
      const ctx = await deployFixture();
      const addr = ethers.Wallet.createRandom().address;
      await expect(
        ctx.validation.connect(ctx.other).setReputationRegistry(addr)
      ).to.be.revertedWithCustomError(ctx.validation, "OwnableUnauthorizedAccount");
    });

    it("reverts setters with address(0)", async function () {
      const ctx = await deployFixture();
      await expect(
        ctx.validation.connect(ctx.owner).setIdentityRegistry(ethers.ZeroAddress)
      ).to.be.revertedWithCustomError(ctx.validation, "ZeroAddress");
    });
  });
});
