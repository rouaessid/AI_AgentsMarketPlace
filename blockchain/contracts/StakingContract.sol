// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title StakingContract
 * @notice Gère le stake des providers et judges.
 *         Slash déclenché uniquement par ValidationRegistry.
 */
contract StakingContract is Ownable, ReentrancyGuard {

    // ── Structs ──────────────────────────────────────────────────────────────

    struct StakeInfo {
        uint256 amount;          // montant staké en wei
        uint256 lockedUntil;     // timestamp — locked si tâche en cours
        bool    exists;
    }

    // ── State ─────────────────────────────────────────────────────────────────

    mapping(address => StakeInfo) public stakes;

    uint256 public constant MIN_PROVIDER_STAKE = 0.001 ether;
    uint256 public constant MIN_JUDGE_STAKE    = 0.0005 ether;
    uint256 public constant SLASH_PROVIDER_BPS = 1000; // 10%
    uint256 public constant SLASH_JUDGE_BPS    = 500;  // 5%

    address public validationRegistry;
    address public platformWallet;

    // ── Events ────────────────────────────────────────────────────────────────

    event Staked(address indexed agent, uint256 amount);
    event Unstaked(address indexed agent, uint256 amount);
    event Slashed(address indexed agent, uint256 amount, string reason);
    event ValidationRegistrySet(address indexed registry);

    // ── Modifiers ─────────────────────────────────────────────────────────────

    modifier onlyValidationRegistry() {
        require(
            msg.sender == validationRegistry,
            "StakingContract: caller is not ValidationRegistry"
        );
        _;
    }

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor(address _platformWallet) Ownable(msg.sender) {
        platformWallet = _platformWallet;
    }

    // ── Admin ─────────────────────────────────────────────────────────────────

    function setValidationRegistry(address _registry) external onlyOwner {
        validationRegistry = _registry;
        emit ValidationRegistrySet(_registry);
    }

    function setPlatformWallet(address _wallet) external onlyOwner {
        platformWallet = _wallet;
    }

    // ── Stake ─────────────────────────────────────────────────────────────────

    /**
     * @notice Déposer un stake.
     * @dev Appelé par provider ou judge.
     */
    function stake() external payable nonReentrant {
        require(msg.value > 0, "StakingContract: amount must be > 0");

        StakeInfo storage s = stakes[msg.sender];
        s.amount += msg.value;
        s.exists  = true;

        emit Staked(msg.sender, msg.value);
    }

    /**
     * @notice Retirer son stake.
     * @dev Impossible si stake locké (tâche en cours).
     */
    function withdraw() external nonReentrant {
        StakeInfo storage s = stakes[msg.sender];
        require(s.exists && s.amount > 0, "StakingContract: no stake");
        require(
            block.timestamp >= s.lockedUntil,
            "StakingContract: stake locked - task in progress"
        );

        uint256 amount = s.amount;
        s.amount = 0;
        s.exists = false;

        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "StakingContract: transfer failed");

        emit Unstaked(msg.sender, amount);
    }

    // ── Lock / Unlock ─────────────────────────────────────────────────────────

    /**
     * @notice Lock le stake d'un agent pendant une tâche.
     * @dev Appelé par ValidationRegistry au début d'une validation.
     */
    function lockStake(address agent, uint256 duration)
        external
        onlyValidationRegistry
    {
        stakes[agent].lockedUntil = block.timestamp + duration;
    }

    /**
     * @notice Unlock le stake d'un agent après une tâche.
     */
    function unlockStake(address agent)
        external
        onlyValidationRegistry
    {
        stakes[agent].lockedUntil = 0;
    }

    // ── Slash ─────────────────────────────────────────────────────────────────

    /**
     * @notice Slash un provider (résultat INVALID).
     * @dev 10% du stake → plateforme.
     */
    function slashProvider(address agent)
        external
        onlyValidationRegistry
        returns (uint256 slashedAmount)
    {
        return _slash(agent, SLASH_PROVIDER_BPS, "INVALID_RESULT");
    }

    /**
     * @notice Slash un judge contre consensus.
     * @dev 5% du stake → plateforme.
     */
    function slashJudge(address agent)
        external
        onlyValidationRegistry
        returns (uint256 slashedAmount)
    {
        return _slash(agent, SLASH_JUDGE_BPS, "AGAINST_CONSENSUS");
    }

    function _slash(
        address agent,
        uint256 bps,
        string memory reason
    ) internal returns (uint256 slashedAmount) {
        StakeInfo storage s = stakes[agent];
        require(s.exists && s.amount > 0, "StakingContract: no stake to slash");

        slashedAmount = (s.amount * bps) / 10_000;
        s.amount     -= slashedAmount;

        (bool ok, ) = platformWallet.call{value: slashedAmount}("");
        require(ok, "StakingContract: slash transfer failed");

        emit Slashed(agent, slashedAmount, reason);
    }

    // ── Views ─────────────────────────────────────────────────────────────────

    function getStake(address agent) external view returns (uint256) {
        return stakes[agent].amount;
    }

    function isEligibleProvider(address agent) external view returns (bool) {
        return stakes[agent].amount >= MIN_PROVIDER_STAKE;
    }

    function isEligibleJudge(address agent) external view returns (bool) {
        return stakes[agent].amount >= MIN_JUDGE_STAKE;
    }

    function isLocked(address agent) external view returns (bool) {
        return block.timestamp < stakes[agent].lockedUntil;
    }

    // ── Receive ───────────────────────────────────────────────────────────────

    receive() external payable {}
}