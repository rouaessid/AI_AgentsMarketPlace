// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

// ════════════════════════════════════════════════════════════════════════════
//  ValidationRegistry  —  AgentMarket · ERC-8004 strict
// ════════════════════════════════════════════════════════════════════════════
//
//  Alignement ERC-8004 §Validation
//  ─────────────────────────────────────────────────────────────────────────
//  Le protocole ERC-8004 définit :
//
//    validationRequest(validatorAddress, agentId, requestURI, requestHash)
//      → dans notre cas : validatorAddress = address(this) (ce contrat EST
//        le validateur on-chain qui orchestre le pool de juges)
//        agentId = currentTokenId ERC-721 du provider dans IdentityRegistry
//
//    validationResponse(requestHash, response 0-100, responseURI, responseHash, tag)
//      → appelé en interne par finaliseValidation() après consensus
//        response = aggregatedScore (0-100)
//        tag      = "VALID" | "INVALID" | "DISPUTED"
//
//  Fonctions de lecture ERC-8004 :
//    getValidationStatus(requestHash)
//    getSummary(agentId, validatorAddresses[], tag)
//    getAgentValidations(agentId)
//    getValidatorRequests(validatorAddress)
//
//  Adaptation consensus :
//    validatorAddress = address(this) — ce contrat agrège 3 juges en commit-reveal
//    La réponse finale (0-100 + tag) est enregistrée après majorité
//    validationResponse() peut être appelé plusieurs fois pour le même requestHash
//    → on l'utilise : une fois au consensus, tag = verdict final
//
//  Contrats siblings (continuité exacte) :
//  ┌──────────────────────────────────────────────────────────────────────┐
//  │ IdentityRegistry   → isActive · agentIdExists · getAgentWallet      │
//  │                      getAgentType (uint8 : 0=PROVIDER 1=JUDGE)      │
//  │                      getCurrentTokenId → tokenId ERC-721 (agentId)  │
//  ├──────────────────────────────────────────────────────────────────────┤
//  │ StakingContract    → isEligibleProvider · isEligibleJudge · isLocked│
//  │                      lockStake · unlockStake                         │
//  │                      slashProvider · slashJudge                      │
//  ├──────────────────────────────────────────────────────────────────────┤
//  │ ReputationRegistry → recordReputation(agentId, delta, bool, reason)  │
//  │                      seul responsable de TOUS les scores             │
//  └──────────────────────────────────────────────────────────────────────┘

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

// ── Interfaces siblings ──────────────────────────────────────────────────────

interface IIdentityRegistry {
    function isActive(string calldata agentId)      external view returns (bool);
    function agentIdExists(string calldata agentId) external view returns (bool);
    function getAgentWallet(string calldata agentId) external view returns (address);
    /// Ajout minimal : 0 = PROVIDER, 1 = JUDGE
    function getAgentType(string calldata agentId)  external view returns (uint8);
    /// Retourne le tokenId ERC-721 courant = agentId au sens ERC-8004
    function getCurrentTokenId(string calldata agentId) external view returns (uint256);
}

interface IStakingContract {
    function isEligibleProvider(address agent) external view returns (bool);
    function isEligibleJudge   (address agent) external view returns (bool);
    function isLocked          (address agent) external view returns (bool);
    function lockStake  (address agent, uint256 duration) external;
    function unlockStake(address agent) external;
    function slashProvider(address agent) external returns (uint256);
    function slashJudge   (address agent) external returns (uint256);
}

interface IReputationRegistry {
    function recordReputation(
        string calldata agentId,
        uint256 delta,
        bool    isIncrease,
        string calldata reason
    ) external;
    function getScore(string calldata agentId) external view returns (uint256);
}

interface IEscrowManager {
    function releaseFunds(string calldata taskId, address provider, address[] calldata consensusJudges) external;
    function refundClient(string calldata taskId) external;
}

// ════════════════════════════════════════════════════════════════════════════

contract ValidationRegistry is Ownable, ReentrancyGuard {

    // ── Siblings ─────────────────────────────────────────────────────────────

    IIdentityRegistry   public identityRegistry;
    IStakingContract    public stakingContract;
    IReputationRegistry public reputationRegistry;
    IEscrowManager      public escrowManager;

    // ── Constantes ───────────────────────────────────────────────────────────

    uint8   public constant JUDGE_COUNT         = 3;
    uint256 public constant COMMIT_WINDOW       = 1 hours;
    uint256 public constant REVEAL_WINDOW       = 1 hours;
    uint256 public constant STAKE_LOCK_DURATION = 3 hours;
    uint256 public constant MAX_CANDIDATES      = 20;

    // ERC-8004 : response est 0-100
    uint8  public constant RESPONSE_VALID    = 100;
    uint8  public constant RESPONSE_INVALID  = 0;
    uint8  public constant RESPONSE_DISPUTED = 50;

    // Deltas réputation → tous via ReputationRegistry
    uint256 public constant REP_PROVIDER_VALID   = 10;
    uint256 public constant REP_PROVIDER_INVALID = 15;
    uint256 public constant REP_JUDGE_CONSENSUS  = 5;
    uint256 public constant REP_JUDGE_DEVIATED   = 8;
    uint256 public constant REP_JUDGE_ABSENT     = 10;

    uint8 private constant AGENT_TYPE_PROVIDER = 0;
    uint8 private constant AGENT_TYPE_JUDGE    = 1;

    // ── Enums internes ───────────────────────────────────────────────────────

    enum TaskStatus {
        PENDING,    // requestValidation() effectué, juges non encore assignés
        COMMITTING, // fenêtre commit ouverte
        REVEALING,  // fenêtre reveal ouverte
        FINALISED,  // consensus atteint (VALID / INVALID / DISPUTED)
        EXPIRED     // deadline dépassée sans participation
    }

    enum InternalVote { NONE, VALID, INVALID }

    // ── Structs internes (commit-reveal) ─────────────────────────────────────

    struct JudgeCommit {
        bytes32      commitHash; // keccak256(abi.encode(vote, salt))
        InternalVote vote;
        bool         committed;
        bool         revealed;
    }

    struct ValidationTask {
        // Identité interne
        string  taskId;           // ID opaque A2A
        string  providerAgentId;  // agentId string IdentityRegistry
        address providerWallet;

        // ERC-8004 fields
        bytes32 requestHash;      // == evidenceHash soumis par le provider
        uint256 erc8004AgentId;   // tokenId ERC-721 du provider (agentId ERC-8004)

        // Cycle de vie
        TaskStatus status;
        uint256    createdAt;
        uint256    commitDeadline;
        uint256    revealDeadline;

        // Pool juges
        string[3]  judgeIds;
        address[3] judgeWallets;

        // Résultat (rempli après finalise)
        uint8   finalResponse;    // ERC-8004 : 0-100
        string  finalTag;         // "VALID" | "INVALID" | "DISPUTED"
        uint256 score;            // Score numérique agrégé (0-100)
    }

    // ── ERC-8004 : stockage des validations (§Read Functions) ────────────────

    struct ValidationRecord {
        address validatorAddress; // toujours address(this)
        uint256 agentId;          // tokenId ERC-721 du provider
        uint8   response;         // 0-100
        bytes32 responseHash;     // keccak256(requestHash + response + tag)
        string  tag;              // "VALID" | "INVALID" | "DISPUTED"
        uint256 lastUpdate;
    }

    // ── State ────────────────────────────────────────────────────────────────

    // Tâches internes
    mapping(string  => ValidationTask)                    private _tasks;
    mapping(string  => bool)                              private _taskExists;
    mapping(string  => mapping(string => JudgeCommit))    private _commits;
    mapping(string  => string)                            private _judgeActiveTask;

    // ERC-8004 stockage
    mapping(bytes32 => ValidationRecord)   private _validationRecords;
    // agentId (tokenId) → requestHashes[]
    mapping(uint256 => bytes32[])          private _agentValidations;
    // validatorAddress → requestHashes[] (ici address(this) → tout)
    mapping(address => bytes32[])          private _validatorRequests;

    // ── Events ERC-8004 ──────────────────────────────────────────────────────

    /**
     * @dev ERC-8004 §ValidationRequest
     *      validatorAddress = address(this)
     *      agentId          = tokenId ERC-721 du provider
     */
    event ValidationRequest(
        address indexed validatorAddress,
        uint256 indexed agentId,
        string          requestURI,
        bytes32 indexed requestHash
    );

    /**
     * @dev ERC-8004 §ValidationResponse
     *      Émis par finaliseValidation() après consensus.
     *      response : 100=VALID · 0=INVALID · 50=DISPUTED
     */
    event ValidationResponse(
        address indexed validatorAddress,
        uint256 indexed agentId,
        bytes32 indexed requestHash,
        uint8           response,
        string          responseURI,
        bytes32         responseHash,
        string          tag
    );

    // ── Events internes ──────────────────────────────────────────────────────

    event JudgesAssigned(
        string  indexed taskId,
        string          judge0,
        string          judge1,
        string          judge2,
        uint256         commitDeadline,
        uint256         revealDeadline
    );

    event VoteCommitted(string indexed taskId, string indexed judgeId);
    event VoteRevealed (string indexed taskId, string indexed judgeId, InternalVote vote);
    event ProviderSlashed(string indexed agentId, address indexed wallet, uint256 amount);
    event JudgeSlashed   (string indexed agentId, address indexed wallet, uint256 amount, string reason);
    event TaskExpired    (string indexed taskId);

    // ── Errors ───────────────────────────────────────────────────────────────

    error TaskNotFound(string taskId);
    error TaskAlreadyExists(string taskId);
    error WrongStatus(string taskId, TaskStatus current);
    error NotAJudgeOfTask(string judgeId, string taskId);
    error AlreadyCommitted(string judgeId);
    error AlreadyRevealed(string judgeId);
    error CommitMismatch(string judgeId);
    error VoteIsNone();
    error CommitWindowClosed(string taskId);
    error CommitWindowStillOpen(string taskId);
    error RevealWindowClosed(string taskId);
    error RevealWindowStillOpen(string taskId);
    error CallerNotJudgeWallet(string judgeId, address caller, address expected);
    error ProviderIneligible(string agentId);
    error NotEnoughEligibleJudges(uint256 found, uint256 required);
    error TooManyCandidates(uint256 given, uint256 max);
    error InvalidScore(uint256 score);
    error NotExpirable(string taskId);
    error ZeroAddress();

    // ── Constructor ──────────────────────────────────────────────────────────

    constructor(
        address identityRegistry_,
        address stakingContract_,
        address reputationRegistry_
    ) Ownable(msg.sender) {
        if (identityRegistry_   == address(0) ||
            stakingContract_    == address(0) ||
            reputationRegistry_ == address(0)) revert ZeroAddress();

        identityRegistry   = IIdentityRegistry(identityRegistry_);
        stakingContract    = IStakingContract(stakingContract_);
        reputationRegistry = IReputationRegistry(reputationRegistry_);
    }

    // ── Admin ────────────────────────────────────────────────────────────────

    function setIdentityRegistry  (address a) external onlyOwner {
        if (a == address(0)) revert ZeroAddress();
        identityRegistry   = IIdentityRegistry(a);
    }
    function setStakingContract   (address a) external onlyOwner {
        if (a == address(0)) revert ZeroAddress();
        stakingContract    = IStakingContract(a);
    }
    function setReputationRegistry(address a) external onlyOwner {
        if (a == address(0)) revert ZeroAddress();
        reputationRegistry = IReputationRegistry(a);
    }

    function setEscrowManager(address a) external onlyOwner {
        if (a == address(0)) revert ZeroAddress();
        escrowManager = IEscrowManager(a);
    }

    // ════════════════════════════════════════════════════════════════════════
    //  ERC-8004 §1 — validationRequest
    // ════════════════════════════════════════════════════════════════════════

    /**
     * @notice Soumet un résultat pour validation indépendante.
     *         Conforme à ERC-8004 : validationRequest(validatorAddress, agentId,
     *         requestURI, requestHash) avec validatorAddress = address(this).
     *
     * @param taskId_          ID opaque A2A (unique, 1-64 chars)
     * @param providerAgentId_ agentId string dans IdentityRegistry
     * @param requestURI_      IPFS URI → JSON résultat complet (= requestURI ERC-8004)
     * @param requestHash_     keccak256(payload résultat) = evidenceHash proxy
     *
     * Vérifie :
     *   ① IdentityRegistry : ACTIVE + type == PROVIDER
     *   ② StakingContract  : stake >= MIN_PROVIDER_STAKE
     * Locke le stake provider pour STAKE_LOCK_DURATION.
     * Émet ValidationRequest (ERC-8004).
     */
    function validationRequest(
        string  calldata taskId_,
        string  calldata providerAgentId_,
        string  calldata requestURI_,
        bytes32          requestHash_
    ) external nonReentrant {
        if (_taskExists[taskId_]) revert TaskAlreadyExists(taskId_);

        // ① Identité
        if (!identityRegistry.isActive(providerAgentId_))
            revert ProviderIneligible(providerAgentId_);
        if (identityRegistry.getAgentType(providerAgentId_) != AGENT_TYPE_PROVIDER)
            revert ProviderIneligible(providerAgentId_);

        // ② Stake
        address providerWallet = identityRegistry.getAgentWallet(providerAgentId_);
        if (!stakingContract.isEligibleProvider(providerWallet))
            revert ProviderIneligible(providerAgentId_);

        // tokenId ERC-721 = agentId au sens ERC-8004
        uint256 erc8004AgentId = identityRegistry.getCurrentTokenId(providerAgentId_);

        // Lock stake
        stakingContract.lockStake(providerWallet, STAKE_LOCK_DURATION);

        // Créer la tâche
        ValidationTask storage t = _tasks[taskId_];
        t.taskId          = taskId_;
        t.providerAgentId = providerAgentId_;
        t.providerWallet  = providerWallet;
        t.requestHash     = requestHash_;
        t.erc8004AgentId  = erc8004AgentId;
        t.status          = TaskStatus.PENDING;
        t.createdAt       = block.timestamp;

        _taskExists[taskId_] = true;

        // ERC-8004 : initialiser le record (response = 0 = INVALID par défaut,
        // sera écrasé par validationResponse() à la finalisation)
        _validationRecords[requestHash_] = ValidationRecord({
            validatorAddress: address(this),
            agentId:          erc8004AgentId,
            response:         0,
            responseHash:     bytes32(0),
            tag:              "PENDING",
            lastUpdate:       block.timestamp
        });
        _agentValidations[erc8004AgentId].push(requestHash_);
        _validatorRequests[address(this)].push(requestHash_);

        // ERC-8004 event
        emit ValidationRequest(address(this), erc8004AgentId, requestURI_, requestHash_);
    }

    // ════════════════════════════════════════════════════════════════════════
    //  ÉTAPE 2 — assignJudges
    // ════════════════════════════════════════════════════════════════════════

    /**
     * @notice Backend (Agent Judge Selector) propose des candidats.
     *         Le contrat :
     *           ① Filtre par éligibilité (6 critères)
     *           ② Fisher-Yates on-chain → JUDGE_COUNT juges
     *           ③ Lock stakes + ouvre fenêtre commit
     *
     * @param taskId_     Tâche à assigner
     * @param candidates_ agentIds proposés (≥ JUDGE_COUNT, ≤ MAX_CANDIDATES)
     *
     * Critères éligibilité vérifiés on-chain :
     *   ① agentIdExists   ② isActive   ③ getAgentType == JUDGE
     *   ④ isEligibleJudge ⑤ !isLocked  ⑥ pas déjà assigné ici
     */
    function assignJudges(
        string calldata   taskId_,
        string[] calldata candidates_
    ) external onlyOwner nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        if (t.status != TaskStatus.PENDING)
            revert WrongStatus(taskId_, t.status);
        if (candidates_.length > MAX_CANDIDATES)
            revert TooManyCandidates(candidates_.length, MAX_CANDIDATES);

        // Filtrage
        string[20] memory eligible;
        uint256 eligibleCount = 0;
        for (uint256 i = 0; i < candidates_.length; i++) {
            if (eligibleCount == MAX_CANDIDATES) break;
            if (_isEligibleJudge(candidates_[i])) {
                eligible[eligibleCount++] = candidates_[i];
            }
        }
        if (eligibleCount < JUDGE_COUNT)
            revert NotEnoughEligibleJudges(eligibleCount, JUDGE_COUNT);

        // Fisher-Yates partiel
        uint256 seed = uint256(keccak256(abi.encodePacked(
            block.prevrandao, block.timestamp, taskId_, msg.sender
        )));

        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            uint256 swapIdx = i + (seed % (eligibleCount - i));
            seed = uint256(keccak256(abi.encodePacked(seed)));

            string memory tmp  = eligible[i];
            eligible[i]        = eligible[swapIdx];
            eligible[swapIdx]  = tmp;

            string memory judgeId    = eligible[i];
            address       judgeWallet = identityRegistry.getAgentWallet(judgeId);

            t.judgeIds[i]     = judgeId;
            t.judgeWallets[i] = judgeWallet;
            _judgeActiveTask[judgeId] = taskId_;
            stakingContract.lockStake(judgeWallet, STAKE_LOCK_DURATION);
        }

        t.status         = TaskStatus.COMMITTING;
        t.commitDeadline = block.timestamp + COMMIT_WINDOW;
        t.revealDeadline = t.commitDeadline + REVEAL_WINDOW;

        emit JudgesAssigned(
            taskId_,
            t.judgeIds[0], t.judgeIds[1], t.judgeIds[2],
            t.commitDeadline, t.revealDeadline
        );
    }

    // ════════════════════════════════════════════════════════════════════════
    //  ÉTAPE 3 — commitVote
    // ════════════════════════════════════════════════════════════════════════

    /**
     * @notice Juge soumet son vote hashé.
     * @param taskId_     Tâche
     * @param judgeId_    agentId du juge (IdentityRegistry)
     * @param commitHash_ keccak256(abi.encode(vote, salt))
     *                    InternalVote.VALID=1, InternalVote.INVALID=2
     *
     * msg.sender doit être l'agentWallet du juge.
     */
    function commitVote(
        string  calldata taskId_,
        string  calldata judgeId_,
        bytes32          commitHash_
    ) external nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        if (t.status != TaskStatus.COMMITTING)
            revert WrongStatus(taskId_, t.status);
        if (block.timestamp > t.commitDeadline)
            revert CommitWindowClosed(taskId_);

        uint256 idx      = _judgeIndexOf(t, judgeId_);
        address expected = t.judgeWallets[idx];
        if (msg.sender != expected)
            revert CallerNotJudgeWallet(judgeId_, msg.sender, expected);

        JudgeCommit storage c = _commits[taskId_][judgeId_];
        if (c.committed) revert AlreadyCommitted(judgeId_);

        c.commitHash = commitHash_;
        c.committed  = true;

        emit VoteCommitted(taskId_, judgeId_);

        if (_allCommitted(t)) t.status = TaskStatus.REVEALING;
    }

    // ════════════════════════════════════════════════════════════════════════
    //  ÉTAPE 4 — revealVote
    // ════════════════════════════════════════════════════════════════════════

    /**
     * @notice Juge révèle son vote.
     * @param taskId_  Tâche
     * @param judgeId_ agentId du juge
     * @param vote_    Vote original (VALID=1 ou INVALID=2)
     * @param salt_    Sel original du commit
     */
    function revealVote(
        string       calldata taskId_,
        string       calldata judgeId_,
        InternalVote          vote_,
        bytes32               salt_
    ) external nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        // Transition forcée si deadline commit passée
        if (t.status == TaskStatus.COMMITTING) {
            if (block.timestamp <= t.commitDeadline)
                revert CommitWindowStillOpen(taskId_);
            t.status = TaskStatus.REVEALING;
        }
        if (t.status != TaskStatus.REVEALING)
            revert WrongStatus(taskId_, t.status);
        if (block.timestamp > t.revealDeadline)
            revert RevealWindowClosed(taskId_);
        if (vote_ == InternalVote.NONE) revert VoteIsNone();

        uint256 idx      = _judgeIndexOf(t, judgeId_);
        address expected = t.judgeWallets[idx];
        if (msg.sender != expected)
            revert CallerNotJudgeWallet(judgeId_, msg.sender, expected);

        JudgeCommit storage c = _commits[taskId_][judgeId_];
        if (!c.committed) revert NotAJudgeOfTask(judgeId_, taskId_);
        if (c.revealed)   revert AlreadyRevealed(judgeId_);

        if (keccak256(abi.encode(vote_, salt_)) != c.commitHash)
            revert CommitMismatch(judgeId_);

        c.vote     = vote_;
        c.revealed = true;

        emit VoteRevealed(taskId_, judgeId_, vote_);
    }

    // ════════════════════════════════════════════════════════════════════════
    //  ERC-8004 §2 — validationResponse  (interne, appelé par finaliseValidation)
    // ════════════════════════════════════════════════════════════════════════

    /**
     * @dev Enregistre la réponse ERC-8004 on-chain et émet ValidationResponse.
     *      Appelé uniquement par finaliseValidation().
     *      Peut être appelé plusieurs fois pour le même requestHash (ERC-8004 permet).
     */
    function _recordValidationResponse(
        bytes32        requestHash_,
        uint256        erc8004AgentId_,
        uint8          response_,
        string memory  responseURI_,
        string memory  tag_
    ) internal {
        bytes32 responseHash = keccak256(abi.encode(requestHash_, response_, tag_));

        ValidationRecord storage rec = _validationRecords[requestHash_];
        rec.response     = response_;
        rec.responseHash = responseHash;
        rec.tag          = tag_;
        rec.lastUpdate   = block.timestamp;

        emit ValidationResponse(
            address(this),
            erc8004AgentId_,
            requestHash_,
            response_,
            responseURI_,
            responseHash,
            tag_
        );
    }

    // ════════════════════════════════════════════════════════════════════════
    //  ÉTAPE 5 — finaliseValidation
    // ════════════════════════════════════════════════════════════════════════

    /**
     * @notice Clôture la validation après reveal.
     *         Appelable par n'importe qui :
     *           • dès que tous ont révélé (finalisation anticipée)
     *           • après la deadline reveal
     *
     * @param taskId_           Tâche
     * @param aggregatedScore_  Score 0-100 calculé off-chain (average juges)
     * @param justificationURI_ IPFS URI → JSON justification agrégée
     *                          (= responseURI ERC-8004)
     *
     * Effets :
     *   → consensus → verdict → tag ERC-8004 ("VALID"/"INVALID"/"DISPUTED")
     *   → _recordValidationResponse() → émet ValidationResponse (ERC-8004)
     *   → StakingContract.slash* si nécessaire
     *   → ReputationRegistry.recordReputation (providers ET juges)
     *   → StakingContract.unlockStake (provider + juges)
     */
    function finaliseValidation(
        string  calldata taskId_,
        uint256          aggregatedScore_,
        string  calldata justificationURI_
    ) external nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        if (t.status != TaskStatus.REVEALING)
            revert WrongStatus(taskId_, t.status);

        bool allDone = _allRevealed(t);
        if (!allDone && block.timestamp <= t.revealDeadline)
            revert RevealWindowStillOpen(taskId_);

        if (aggregatedScore_ > 100)
            revert InvalidScore(aggregatedScore_);

        // ── Comptage votes ────────────────────────────────────────────────────
        uint256 validCount   = 0;
        uint256 invalidCount = 0;
        bool[3] memory votedValid;
        bool[3] memory didReveal;

        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            JudgeCommit storage c = _commits[taskId_][t.judgeIds[i]];
            if (!c.revealed) continue;
            didReveal[i] = true;
            if (c.vote == InternalVote.VALID)   { validCount++;   votedValid[i] = true; }
            if (c.vote == InternalVote.INVALID) { invalidCount++; }
        }

        // ── Verdict ───────────────────────────────────────────────────────────
        uint8  erc8004Response;
        string memory tag;

        if (validCount >= 2) {
            erc8004Response = RESPONSE_VALID;
            tag             = "VALID";
        } else if (invalidCount >= 2) {
            erc8004Response = RESPONSE_INVALID;
            tag             = "INVALID";
        } else {
            erc8004Response = RESPONSE_DISPUTED;
            tag             = "DISPUTED";
        }

        t.finalResponse = erc8004Response;
        t.finalTag      = tag;
        t.score         = aggregatedScore_;
        t.status        = TaskStatus.FINALISED;

        // ── ERC-8004 : enregistrer la réponse ────────────────────────────────
        _recordValidationResponse(
            t.requestHash,
            t.erc8004AgentId,
            erc8004Response,
            justificationURI_,
            tag
        );

        // ── Slash + réputation (seulement si verdict tranché) ─────────────────
        if (erc8004Response != RESPONSE_DISPUTED) {
            bool providerValid = (erc8004Response == RESPONSE_VALID);
            _applyOutcomes(t, providerValid, votedValid, didReveal);

            // ── Escrow paiement ────────────────────────────────────────────────
            if (address(escrowManager) != address(0)) {
                if (providerValid) {
                    address[] memory validJudges = new address[](validCount);
                    uint256 idx = 0;
                    for (uint8 i = 0; i < JUDGE_COUNT; i++) {
                        if (votedValid[i]) {
                            validJudges[idx++] = t.judgeWallets[i];
                        }
                    }
                    try escrowManager.releaseFunds(taskId_, t.providerWallet, validJudges) {} catch {}
                } else {
                    try escrowManager.refundClient(taskId_) {} catch {}
                }
            }
        } else {
             // Si DISPUTED, on rembourse le client pour ne pas bloquer les fonds
             if (address(escrowManager) != address(0)) {
                 try escrowManager.refundClient(taskId_) {} catch {}
             }
        }

        // ── Unlock stakes ─────────────────────────────────────────────────────
        stakingContract.unlockStake(t.providerWallet);
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            if (t.judgeWallets[i] != address(0))
                stakingContract.unlockStake(t.judgeWallets[i]);
            if (bytes(t.judgeIds[i]).length > 0)
                delete _judgeActiveTask[t.judgeIds[i]];
        }
    }

    // ── expireTask ───────────────────────────────────────────────────────────

    /**
     * @notice Force l'expiration si les deadlines sont passées sans vote.
     *         Slash les juges absents. Unlock le provider.
     *         Enregistre une réponse ERC-8004 avec tag "EXPIRED".
     */
    function expireTask(string calldata taskId_) external nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        bool expirable =
            (t.status == TaskStatus.COMMITTING && block.timestamp > t.commitDeadline) ||
            (t.status == TaskStatus.REVEALING  && block.timestamp > t.revealDeadline);
        if (!expirable) revert NotExpirable(taskId_);

        t.status        = TaskStatus.EXPIRED;
        t.finalResponse = 0;
        t.finalTag      = "EXPIRED";

        // ERC-8004 : enregistrer expiration
        _recordValidationResponse(
            t.requestHash, t.erc8004AgentId, 0, "", "EXPIRED"
        );

        // Unlock provider
        stakingContract.unlockStake(t.providerWallet);

        // Remboursement client de l'escrow car tâche expirée sans succès
        if (address(escrowManager) != address(0)) {
             try escrowManager.refundClient(taskId_) {} catch {}
        }

        // Juges absents → slash + réputation
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            string  storage jid     = t.judgeIds[i];
            address         jwallet = t.judgeWallets[i];
            if (jwallet == address(0)) continue;

            JudgeCommit storage c = _commits[taskId_][jid];
            if (!c.committed || !c.revealed) {
                uint256 amt = stakingContract.slashJudge(jwallet);
                emit JudgeSlashed(jid, jwallet, amt, "ABSENT");
                reputationRegistry.recordReputation(jid, REP_JUDGE_ABSENT, false, "ABSENT");
            }
            stakingContract.unlockStake(jwallet);
            delete _judgeActiveTask[jid];
        }

        emit TaskExpired(taskId_);
    }

    // ════════════════════════════════════════════════════════════════════════
    //  ERC-8004 §Read Functions
    // ════════════════════════════════════════════════════════════════════════

    /**
     * @notice ERC-8004 : getValidationStatus(requestHash)
     *         Retourne l'état courant d'une validation.
     */
    function getValidationStatus(bytes32 requestHash)
        external view
        returns (
            address validatorAddress,
            uint256 agentId,
            uint8   response,
            bytes32 responseHash,
            string memory tag,
            uint256 lastUpdate
        )
    {
        ValidationRecord storage rec = _validationRecords[requestHash];
        return (
            rec.validatorAddress,
            rec.agentId,
            rec.response,
            rec.responseHash,
            rec.tag,
            rec.lastUpdate
        );
    }

    /**
     * @notice ERC-8004 : getSummary(agentId, validatorAddresses[], tag)
     *         Retourne les statistiques agrégées de validation pour un agent.
     *         agentId = tokenId ERC-721 du provider.
     *         validatorAddresses et tag sont des filtres optionnels.
     *
     * @param agentId_           tokenId ERC-721 du provider
     * @param validatorAddresses Filtrer par validateurs (vide = tous)
     * @param tag_               Filtrer par tag ("VALID","INVALID","" = tous)
     */
    function getSummary(
        uint256          agentId_,
        address[] calldata validatorAddresses,
        string    calldata tag_
    )
        external view
        returns (uint64 count, uint8 averageResponse)
    {
        bytes32[] storage hashes = _agentValidations[agentId_];
        bool filterValidator = validatorAddresses.length > 0;
        bool filterTag       = bytes(tag_).length > 0;

        uint256 total    = 0;
        uint256 matched  = 0;

        for (uint256 i = 0; i < hashes.length; i++) {
            ValidationRecord storage rec = _validationRecords[hashes[i]];

            // Filtre validateur
            if (filterValidator) {
                bool found = false;
                for (uint256 j = 0; j < validatorAddresses.length; j++) {
                    if (rec.validatorAddress == validatorAddresses[j]) { found = true; break; }
                }
                if (!found) continue;
            }

            // Filtre tag
            if (filterTag && keccak256(bytes(rec.tag)) != keccak256(bytes(tag_))) continue;

            // N'agréger que les validations finalisées (pas PENDING/EXPIRED)
            bytes32 tagHash = keccak256(bytes(rec.tag));
            if (tagHash == keccak256(bytes("PENDING")) ||
                tagHash == keccak256(bytes("EXPIRED")))  continue;

            total   += rec.response;
            matched++;
        }

        count           = uint64(matched);
        averageResponse = matched > 0 ? uint8(total / matched) : 0;
    }

    /**
     * @notice ERC-8004 : getAgentValidations(agentId)
     *         Retourne tous les requestHashes liés à un agent (tokenId).
     */
    function getAgentValidations(uint256 agentId_)
        external view
        returns (bytes32[] memory)
    {
        return _agentValidations[agentId_];
    }

    /**
     * @notice ERC-8004 : getValidatorRequests(validatorAddress)
     *         Retourne tous les requestHashes traités par un validateur.
     *         (Pour ce contrat : address(this) = tous)
     */
    function getValidatorRequests(address validatorAddress)
        external view
        returns (bytes32[] memory)
    {
        return _validatorRequests[validatorAddress];
    }

    // ── Views internes supplémentaires ───────────────────────────────────────

    function getTask(string calldata taskId_)
        external view returns (ValidationTask memory)
    { return _getTask(taskId_); }

    function getJudgeCommit(string calldata taskId_, string calldata judgeId_)
        external view returns (JudgeCommit memory)
    { return _commits[taskId_][judgeId_]; }

    function isJudgeBusy(string calldata judgeId_)
        external view returns (bool)
    { return bytes(_judgeActiveTask[judgeId_]).length > 0; }

    function getJudgeActiveTask(string calldata judgeId_)
        external view returns (string memory)
    { return _judgeActiveTask[judgeId_]; }

    function isEligibleJudgeCandidate(string calldata judgeId_)
        external view returns (bool)
    { return _isEligibleJudge(judgeId_); }

    // ── Internals ────────────────────────────────────────────────────────────

    function _getTask(string memory taskId_)
        internal view returns (ValidationTask storage)
    {
        if (!_taskExists[taskId_]) revert TaskNotFound(taskId_);
        return _tasks[taskId_];
    }

    function _judgeIndexOf(ValidationTask storage t, string memory judgeId_)
        internal view returns (uint256)
    {
        bytes32 h = keccak256(bytes(judgeId_));
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            if (keccak256(bytes(t.judgeIds[i])) == h) return i;
        }
        revert NotAJudgeOfTask(judgeId_, t.taskId);
    }

    function _allCommitted(ValidationTask storage t) internal view returns (bool) {
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            if (!_commits[t.taskId][t.judgeIds[i]].committed) return false;
        }
        return true;
    }

    function _allRevealed(ValidationTask storage t) internal view returns (bool) {
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            if (!_commits[t.taskId][t.judgeIds[i]].revealed) return false;
        }
        return true;
    }

    /**
     * @dev 6 critères d'éligibilité juge :
     *   ① agentIdExists   ② isActive   ③ getAgentType == JUDGE
     *   ④ isEligibleJudge ⑤ !isLocked  ⑥ pas déjà assigné ici
     */
    function _isEligibleJudge(string memory judgeId_) internal view returns (bool) {
        if (!identityRegistry.agentIdExists(judgeId_)) return false;
        if (!identityRegistry.isActive(judgeId_))      return false;
        if (identityRegistry.getAgentType(judgeId_) != AGENT_TYPE_JUDGE) return false;

        address wallet = identityRegistry.getAgentWallet(judgeId_);
        if (!stakingContract.isEligibleJudge(wallet)) return false;
        if (stakingContract.isLocked(wallet))          return false;
        if (bytes(_judgeActiveTask[judgeId_]).length > 0) return false;

        return true;
    }

    /**
     * @dev Applique slash + réputation après consensus.
     *      TOUTE réputation → ReputationRegistry (providers ET juges).
     *
     *  Provider VALID   → +REP_PROVIDER_VALID  (ReputationRegistry)
     *  Provider INVALID → slashProvider()       (StakingContract)
     *                     -REP_PROVIDER_INVALID (ReputationRegistry)
     *
     *  Judge CONSENSUS  → +REP_JUDGE_CONSENSUS  (ReputationRegistry)
     *  Judge DEVIATED   → slashJudge()           (StakingContract)
     *                     -REP_JUDGE_DEVIATED    (ReputationRegistry)
     *  Judge ABSENT     → slashJudge()           (StakingContract)
     *                     -REP_JUDGE_ABSENT      (ReputationRegistry)
     */
    function _applyOutcomes(
        ValidationTask storage t,
        bool            providerValid,
        bool[3] memory  votedValid,
        bool[3] memory  didReveal
    ) internal {

        // ── Provider ──────────────────────────────────────────────────────────
        if (providerValid) {
            reputationRegistry.recordReputation(
                t.providerAgentId, REP_PROVIDER_VALID, true, "VALID"
            );
        } else {
            uint256 slashedAmt = stakingContract.slashProvider(t.providerWallet);
            emit ProviderSlashed(t.providerAgentId, t.providerWallet, slashedAmt);
            reputationRegistry.recordReputation(
                t.providerAgentId, REP_PROVIDER_INVALID, false, "INVALID"
            );
        }

        // ── Juges ─────────────────────────────────────────────────────────────
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            string  storage jid     = t.judgeIds[i];
            address         jwallet = t.judgeWallets[i];
            if (jwallet == address(0)) continue;

            if (!didReveal[i]) {
                // Absent
                uint256 amt = stakingContract.slashJudge(jwallet);
                emit JudgeSlashed(jid, jwallet, amt, "ABSENT");
                reputationRegistry.recordReputation(jid, REP_JUDGE_ABSENT, false, "ABSENT");

            } else {
                bool aligned =
                    ( providerValid &&  votedValid[i]) ||
                    (!providerValid && !votedValid[i]);

                if (aligned) {
                    reputationRegistry.recordReputation(
                        jid, REP_JUDGE_CONSENSUS, true, "CONSENSUS"
                    );
                } else {
                    uint256 amt = stakingContract.slashJudge(jwallet);
                    emit JudgeSlashed(jid, jwallet, amt, "DEVIATED");
                    reputationRegistry.recordReputation(
                        jid, REP_JUDGE_DEVIATED, false, "DEVIATED"
                    );
                }
            }
        }
    }
}
