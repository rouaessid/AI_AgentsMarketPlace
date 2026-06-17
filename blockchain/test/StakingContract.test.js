const { ethers } = require("hardhat");
const { expect } = require("chai");

describe("StakingContract", function () {
  let staking, owner, provider, judge, platform, registry;

  beforeEach(async () => {
    [owner, provider, judge, platform, registry] = await ethers.getSigners();

    const Factory = await ethers.getContractFactory("StakingContract");
    staking = await Factory.deploy(platform.address);
    await staking.waitForDeployment();

    await staking.setValidationRegistry(registry.address);
  });

  describe("Stake", () => {
    it("provider peut staker", async () => {
      await staking.connect(provider).stake({ value: ethers.parseEther("0.5") });
      expect(await staking.getStake(provider.address))
        .to.equal(ethers.parseEther("0.5"));
    });

    it("judge peut staker", async () => {
      await staking.connect(judge).stake({ value: ethers.parseEther("0.1") });
      expect(await staking.getStake(judge.address))
        .to.equal(ethers.parseEther("0.1"));
    });

    it("isEligibleProvider true si stake >= 0.1 ETH", async () => {
      await staking.connect(provider).stake({ value: ethers.parseEther("0.1") });
      expect(await staking.isEligibleProvider(provider.address)).to.be.true;
    });

    it("isEligibleProvider false si stake < 0.001 ETH", async () => {
      await staking.connect(provider).stake({ value: ethers.parseEther("0.0005") });
      expect(await staking.isEligibleProvider(provider.address)).to.be.false;
    });

    it("isEligibleJudge true si stake >= 0.0005 ETH", async () => {
      await staking.connect(judge).stake({ value: ethers.parseEther("0.0005") });
      expect(await staking.isEligibleJudge(judge.address)).to.be.true;
    });
  });

  describe("Withdraw", () => {
    it("peut retirer si pas locké", async () => {
      await staking.connect(provider).stake({ value: ethers.parseEther("1") });
      const before = await ethers.provider.getBalance(provider.address);
      await staking.connect(provider).withdraw();
      const after = await ethers.provider.getBalance(provider.address);
      expect(after).to.be.gt(before);
    });

    it("ne peut pas retirer si locké", async () => {
      await staking.connect(provider).stake({ value: ethers.parseEther("1") });
      await staking.connect(registry).lockStake(provider.address, 3600);
      await expect(staking.connect(provider).withdraw())
        .to.be.revertedWith("StakingContract: stake locked - task in progress");
    });
  });

  describe("Slash", () => {
    it("slash provider 10%", async () => {
      await staking.connect(provider).stake({ value: ethers.parseEther("1") });
      const before = await ethers.provider.getBalance(platform.address);
      await staking.connect(registry).slashProvider(provider.address);
      const after = await ethers.provider.getBalance(platform.address);
      expect(after - before).to.equal(ethers.parseEther("0.1"));
      expect(await staking.getStake(provider.address))
        .to.equal(ethers.parseEther("0.9"));
    });

    it("slash judge 5%", async () => {
      await staking.connect(judge).stake({ value: ethers.parseEther("1") });
      await staking.connect(registry).slashJudge(judge.address);
      expect(await staking.getStake(judge.address))
        .to.equal(ethers.parseEther("0.95"));
    });

    it("seul ValidationRegistry peut slasher", async () => {
      await staking.connect(provider).stake({ value: ethers.parseEther("1") });
      await expect(staking.connect(owner).slashProvider(provider.address))
        .to.be.revertedWith("StakingContract: caller is not ValidationRegistry");
    });
  });

  describe("Lock / Unlock", () => {
    it("lock et unlock par registry", async () => {
      await staking.connect(provider).stake({ value: ethers.parseEther("1") });
      await staking.connect(registry).lockStake(provider.address, 3600);
      expect(await staking.isLocked(provider.address)).to.be.true;
      await staking.connect(registry).unlockStake(provider.address);
      expect(await staking.isLocked(provider.address)).to.be.false;
    });
  });
});