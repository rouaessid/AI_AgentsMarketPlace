// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

// ════════════════════════════════════════════════════════════════════════════
//  EscrowManager
// ════════════════════════════════════════════════════════════════════════════
// Gère le blocage et la distribution en ETH natif du paiement des tâches.
// Les juges se partagent un pourcentage fixe (judgeFeePercentage).
// Le reste va au provider en cas de succès, ou le client est remboursé.
// Le prix par tâche est lu depuis IdentityRegistry — un sous-paiement est rejeté.

interface IIdentityRegistry {
    function getPricePerTask(string calldata agentId_) external view returns (uint256);
    function isActive(string calldata agentId_) external view returns (bool);
}

contract EscrowManager is Ownable, ReentrancyGuard {
    address public validationRegistry;
    address public identityRegistry;   // read price on-chain
    uint256 public judgeFeePercentage; // ex: 10 pour 10%

    // taskId => montant bloqué en ETH
    mapping(string => uint256) public taskFunds;
    // taskId => adresse du client ayant payé
    mapping(string => address) public taskClients;
    // taskId => agentId (to identify provider for release)
    mapping(string => string)  public taskAgent;

    error Unauthorized();
    error InvalidFeePercentage();
    error NoFundsLocked(string taskId);
    error TransferFailed();
    error ZeroAddress();
    error InsufficientPayment(uint256 sent, uint256 required);
    error AgentNotActive(string agentId);

    event PaymentDeposited(string indexed taskId, address indexed client, uint256 amount);
    event FundsReleased(string indexed taskId, address indexed provider, uint256 providerAmount, uint256 totalJudgeAmount);
    event ClientRefunded(string indexed taskId, address indexed client, uint256 amount);

    constructor(uint256 _judgeFeePercentage) Ownable(msg.sender) {
        if (_judgeFeePercentage > 100) revert InvalidFeePercentage();
        judgeFeePercentage = _judgeFeePercentage;
    }

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

    modifier onlyValidationRegistry() {
        if (msg.sender != validationRegistry) revert Unauthorized();
        _;
    }

    /**
     * @notice Le client dépose l'ETH pour une tâche.
     * @param taskId_  Identifiant unique de la tâche
     * @param agentId_ Agent à appeler — le prix est vérifié on-chain via IdentityRegistry
     *
     * Le montant exact requis = IdentityRegistry.getPricePerTask(agentId_).
     * Un sous-paiement est rejeté avec InsufficientPayment.
     */
    function depositPayment(
        string calldata taskId_,
        string calldata agentId_
    ) external payable nonReentrant {
        // Verify price if IdentityRegistry is set
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
     * @notice Appelé par ValidationRegistry.sol si le verdict est VALID.
     *         Libère les fonds et partage entre provider et juges.
     */
    function releaseFunds(
        string calldata taskId_, 
        address provider_, 
        address[] calldata consensusJudges_
    ) external nonReentrant onlyValidationRegistry {
        uint256 totalAmount = taskFunds[taskId_];
        if (totalAmount == 0) revert NoFundsLocked(taskId_);

        // Sécurité Reentrancy : mettre le solde à zéro avant les transferts
        taskFunds[taskId_] = 0;

        uint256 judgeTotalAmount = (totalAmount * judgeFeePercentage) / 100;
        uint256 providerAmount = totalAmount - judgeTotalAmount;

        // 1. Distribuer aux bons juges
        if (consensusJudges_.length > 0 && judgeTotalAmount > 0) {
            uint256 amountPerJudge = judgeTotalAmount / consensusJudges_.length;
            for (uint256 i = 0; i < consensusJudges_.length; i++) {
                (bool success, ) = consensusJudges_[i].call{value: amountPerJudge}("");
                if (!success) revert TransferFailed();
            }
        } else {
            // S'il n'y a pas de juges (anormal, mais cas limite) : tout va au provider
            providerAmount = totalAmount;
            judgeTotalAmount = 0;
        }

        // 2. Distribuer au provider
        if (providerAmount > 0) {
            (bool success, ) = provider_.call{value: providerAmount}("");
            if (!success) revert TransferFailed();
        }

        emit FundsReleased(taskId_, provider_, providerAmount, judgeTotalAmount);
    }

    /**
     * @notice Appelé par ValidationRegistry.sol si le verdict est INVALID ou la tâche expire.
     *         Rembourse le client.
     */
    function refundClient(string calldata taskId_) external nonReentrant onlyValidationRegistry {
        uint256 amount = taskFunds[taskId_];
        if (amount == 0) revert NoFundsLocked(taskId_);

        address client = taskClients[taskId_];
        
        // Sécurité Reentrancy
        taskFunds[taskId_] = 0;

        (bool success, ) = client.call{value: amount}("");
        if (!success) revert TransferFailed();

        emit ClientRefunded(taskId_, client, amount);
    }
}
