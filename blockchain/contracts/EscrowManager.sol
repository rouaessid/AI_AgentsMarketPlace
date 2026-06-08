// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

// ════════════════════════════════════════════════════════════════════════════
//  EscrowManager — AgentMarket
//  Gère le blocage et la distribution ETH des paiements de tâches.
//  Prix lu depuis IdentityRegistry. Juges payés via judgeFeePercentage.
//  Solo et pipeline supportés.
// ════════════════════════════════════════════════════════════════════════════

// ── Interface ────────────────────────────────────────────────────────────────

interface IIdentityRegistry {
    function getPricePerTask(string calldata agentId_) external view returns (uint256);
    function isActive(string calldata agentId_) external view returns (bool);
}

// ════════════════════════════════════════════════════════════════════════════

contract EscrowManager is Ownable, ReentrancyGuard {

    // ── State Variables ───────────────────────────────────────────────────────

    address public validationRegistry;
    address public identityRegistry;
    uint256 public judgeFeePercentage;

    // taskId → montant bloqué en ETH
    mapping(string => uint256) public taskFunds;
    // taskId → adresse du client ayant payé
    mapping(string => address) public taskClients;
    // taskId → agentId concerné
    mapping(string => string)  public taskAgent;
    // taskId → true si tâche pipeline
    mapping(string => bool)    public isPipelineTask;

    // Participants et parts pipeline (internes — gérés par ce contrat)
    mapping(string => address[]) private _pipelineWallets;
    mapping(string => uint256[]) private _pipelineShares; // bps, somme = 10000

    // ── Events ────────────────────────────────────────────────────────────────

    event PaymentDeposited(string indexed taskId, address indexed client, uint256 amount);
    event FundsReleased(string indexed taskId, address indexed provider, uint256 providerAmount, uint256 totalJudgeAmount);
    event ClientRefunded(string indexed taskId, address indexed client, uint256 amount);
    event PipelinePaymentDeposited(string indexed taskId, address indexed client, uint256 amount, uint256 participantCount);
    event PipelineFundsReleased(string indexed taskId, uint256 totalAmount, uint256 participantCount);

    // ── Errors ────────────────────────────────────────────────────────────────

    error Unauthorized();
    error InvalidFeePercentage();
    error NoFundsLocked(string taskId);
    error TransferFailed();
    error ZeroAddress();
    error InsufficientPayment(uint256 sent, uint256 required);
    error AgentNotActive(string agentId);
    error InvalidSharesLength();
    error InvalidSharesSum(uint256 got, uint256 expected);

    // ── Modifiers ─────────────────────────────────────────────────────────────

    modifier onlyValidationRegistry() {
        if (msg.sender != validationRegistry) revert Unauthorized();
        _;
    }

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor(uint256 _judgeFeePercentage) Ownable(msg.sender) {
        if (_judgeFeePercentage > 100) revert InvalidFeePercentage();
        judgeFeePercentage = _judgeFeePercentage;
    }

    // ── Admin ─────────────────────────────────────────────────────────────────

    function setValidationRegistry(address _registry) external onlyOwner {
        if (_registry == address(0)) revert ZeroAddress();
        validationRegistry = _registry;
    }

    function setIdentityRegistry(address _registry) external onlyOwner {
        if (_registry == address(0)) revert ZeroAddress();
        identityRegistry = _registry;
    }

    function setJudgeFeePercentage(uint256 _percentage) external onlyOwner {
        if (_percentage > 100) revert InvalidFeePercentage();
        judgeFeePercentage = _percentage;
    }

    // ── External — Solo ───────────────────────────────────────────────────────

    /**
     * @notice Dépôt ETH pour une tâche solo.
     * @param taskId_  Identifiant unique de la tâche
     * @param agentId_ Agent cible — prix vérifié via IdentityRegistry
     */
    function depositPayment(
        string calldata taskId_,
        string calldata agentId_
    ) external payable nonReentrant {
        if (identityRegistry != address(0)) {
            IIdentityRegistry ir = IIdentityRegistry(identityRegistry);
            if (!ir.isActive(agentId_)) revert AgentNotActive(agentId_);
            uint256 required = ir.getPricePerTask(agentId_);
            if (required > 0 && msg.value < required)
                revert InsufficientPayment(msg.value, required);
        } else {
            if (msg.value == 0) revert NoFundsLocked(taskId_);
        }

        taskFunds[taskId_]   += msg.value;
        taskClients[taskId_]  = msg.sender;
        taskAgent[taskId_]    = agentId_;

        emit PaymentDeposited(taskId_, msg.sender, msg.value);
    }

    /**
     * @notice Libère les fonds vers provider et juges (verdict VALID).
     * @dev Appelé uniquement par ValidationRegistry.
     */
    function releaseFunds(
        string calldata   taskId_,
        address           provider_,
        address[] calldata consensusJudges_
    ) external nonReentrant onlyValidationRegistry {
        uint256 totalAmount = taskFunds[taskId_];
        if (totalAmount == 0) revert NoFundsLocked(taskId_);

        taskFunds[taskId_] = 0;

        uint256 judgeTotalAmount = (totalAmount * judgeFeePercentage) / 100;
        uint256 providerAmount   = totalAmount - judgeTotalAmount;

        if (consensusJudges_.length > 0 && judgeTotalAmount > 0) {
            uint256 amountPerJudge = judgeTotalAmount / consensusJudges_.length;
            for (uint256 i = 0; i < consensusJudges_.length; i++) {
                (bool ok, ) = consensusJudges_[i].call{value: amountPerJudge}("");
                if (!ok) revert TransferFailed();
            }
        } else {
            providerAmount   = totalAmount;
            judgeTotalAmount = 0;
        }

        if (providerAmount > 0) {
            (bool ok, ) = provider_.call{value: providerAmount}("");
            if (!ok) revert TransferFailed();
        }

        emit FundsReleased(taskId_, provider_, providerAmount, judgeTotalAmount);
    }

    /**
     * @notice Rembourse le client (verdict INVALID ou tâche expirée).
     * @dev Fonctionne pour solo et pipeline (même stockage taskFunds/taskClients).
     */
    function refundClient(string calldata taskId_) external nonReentrant onlyValidationRegistry {
        uint256 amount = taskFunds[taskId_];
        if (amount == 0) revert NoFundsLocked(taskId_);

        address client = taskClients[taskId_];
        taskFunds[taskId_] = 0;

        (bool ok, ) = client.call{value: amount}("");
        if (!ok) revert TransferFailed();

        emit ClientRefunded(taskId_, client, amount);
    }

    // ── External — Pipeline ───────────────────────────────────────────────────

    /**
     * @notice Dépôt ETH pour une tâche pipeline multi-agents.
     * @param taskId_      ID unique de la tâche
     * @param agentIds_    Agents participants (lead en premier)
     * @param wallets_     Wallets des agents (même ordre)
     * @param shares_bps_  Part de chaque agent en basis points — somme = 10000
     */
    function depositPaymentPipeline(
        string   calldata  taskId_,
        string[] calldata  agentIds_,
        address[] calldata wallets_,
        uint256[] calldata shares_bps_
    ) external payable nonReentrant {
        if (wallets_.length != shares_bps_.length || wallets_.length == 0)
            revert InvalidSharesLength();

        uint256 totalShares = 0;
        for (uint256 i = 0; i < shares_bps_.length; i++) totalShares += shares_bps_[i];
        if (totalShares != 10_000) revert InvalidSharesSum(totalShares, 10_000);

        if (identityRegistry != address(0)) {
            IIdentityRegistry ir = IIdentityRegistry(identityRegistry);
            uint256 requiredTotal = 0;
            for (uint256 i = 0; i < agentIds_.length; i++) {
                if (!ir.isActive(agentIds_[i])) revert AgentNotActive(agentIds_[i]);
                requiredTotal += ir.getPricePerTask(agentIds_[i]);
            }
            if (requiredTotal > 0 && msg.value < requiredTotal)
                revert InsufficientPayment(msg.value, requiredTotal);
        } else {
            if (msg.value == 0) revert NoFundsLocked(taskId_);
        }

        taskFunds[taskId_]      += msg.value;
        taskClients[taskId_]     = msg.sender;
        taskAgent[taskId_]       = agentIds_[0];
        isPipelineTask[taskId_]  = true;
        _pipelineWallets[taskId_] = wallets_;
        _pipelineShares[taskId_]  = shares_bps_;

        emit PipelinePaymentDeposited(taskId_, msg.sender, msg.value, wallets_.length);
    }

    /**
     * @notice Libère les fonds d'une tâche pipeline (verdict VALID).
     *         Distribution : judgeFeePercentage% aux juges, reste aux providers selon shares_bps_.
     */
    function releaseFundsPipeline(
        string    calldata  taskId_,
        address[] calldata  consensusJudges_
    ) external nonReentrant onlyValidationRegistry {
        uint256 totalAmount = taskFunds[taskId_];
        if (totalAmount == 0) revert NoFundsLocked(taskId_);

        address[] storage wallets = _pipelineWallets[taskId_];
        uint256[] storage shares  = _pipelineShares[taskId_];
        if (wallets.length == 0) revert NoFundsLocked(taskId_);

        taskFunds[taskId_] = 0;

        uint256 judgeFees    = (totalAmount * judgeFeePercentage) / 100;
        uint256 providerPool = totalAmount - judgeFees;

        if (consensusJudges_.length > 0 && judgeFees > 0) {
            uint256 perJudge = judgeFees / consensusJudges_.length;
            for (uint256 i = 0; i < consensusJudges_.length; i++) {
                (bool ok, ) = consensusJudges_[i].call{value: perJudge}("");
                if (!ok) revert TransferFailed();
            }
        } else {
            providerPool = totalAmount;
        }

        for (uint256 i = 0; i < wallets.length; i++) {
            uint256 amount = (providerPool * shares[i]) / 10_000;
            if (amount > 0) {
                (bool ok, ) = wallets[i].call{value: amount}("");
                if (!ok) revert TransferFailed();
            }
        }

        emit PipelineFundsReleased(taskId_, totalAmount, wallets.length);
    }
}
