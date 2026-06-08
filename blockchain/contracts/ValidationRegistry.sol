// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

// ════════════════════════════════════════════════════════════════════════════
//  ValidationRegistry — AgentMarket · ERC-8004
//
//  Orchestre la validation des agents par un pool de 3 juges en commit-reveal.
//  Le contrat est lui-même le validateur (validatorAddress = address(this)).
//
//  Flux : validationRequest → assignJudges → commitVote → revealVote → finaliseValidation
//
//  Contrats liés :
//    IdentityRegistry   → identité + type + wallet des agents
//    StakingContract    → éligibilité + lock/unlock/slash des stakes
//    ReputationRegistry → écriture des scores après consensus
//    EscrowManager      → libération/remboursement des paiements
// ════════════════════════════════════════════════════════════════════════════

// ── Interfaces ────────────────────────────────────────────────────────────────

interface IIdentityRegistry {
    function isActive(string calldata agentId)       external view returns (bool);
    function agentIdExists(string calldata agentId)  external view returns (bool);
    function getAgentWallet(string calldata agentId) external view returns (address);
    function getAgentType(string calldata agentId)   external view returns (uint8);
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

interface IEscrowManager {
    function releaseFunds(string calldata taskId, address provider, address[] calldata consensusJudges) external;
    function releaseFundsPipeline(string calldata taskId, address[] calldata consensusJudges) external;
    function refundClient(string calldata taskId) external;
}

// ════════════════════════════════════════════════════════════════════════════

contract ValidationRegistry is Ownable, ReentrancyGuard {

    // ── Type Declarations ─────────────────────────────────────────────────────

    enum TaskStatus {
        PENDING,    // validationRequest() soumis, juges non assignés
        COMMITTING, // fenêtre commit ouverte
        REVEALING,  // fenêtre reveal ouverte
        FINALISED,  // consensus atteint (VALID / INVALID / DISPUTED)
        EXPIRED     // deadline dépassée sans participation
    }

    enum InternalVote { NONE, VALID, INVALID }

    struct JudgeCommit {
        bytes32      commitHash;     // keccak256(vote, scores×4, salt)
        InternalVote vote;
        uint8        taskCompletion; // 0-25
        uint8        outputQuality;  // 0-25
        uint8        noFabrication;  // 0-25
        uint8        toolUsage;      // 0-25
        bool         committed;
        bool         revealed;
    }

    struct ValidationTask {
        string  taskId;
        string  providerAgentId;
        address providerWallet;
        bytes32 requestHash;
        bytes32 traceHash;      // keccak256(trace JSON) — vérifiable par les juges
        uint256 erc8004AgentId; // tokenId ERC-721 du provider
        TaskStatus status;
        uint256    createdAt;
        uint256    commitDeadline;
        uint256    revealDeadline;
        string[3]  judgeIds;
        address[3] judgeWallets;
        uint8   finalResponse;  // 0=INVALID 50=DISPUTED 100=VALID
        string  finalTag;       // "VALID" | "INVALID" | "DISPUTED" | "EXPIRED"
        uint256 score;          // score agrégé 0-100
        uint8   mode;           // 0=solo 1=pipeline
    }

    struct ValidationRecord {
        address validatorAddress; // toujours address(this)
        uint256 agentId;          // tokenId ERC-721
        uint8   response;         // 0-100
        bytes32 responseHash;
        string  tag;
        string  responseURI;      // IPFS URI des justifications juges agrégées
        uint256 lastUpdate;
    }

    // ── Constants ─────────────────────────────────────────────────────────────

    uint8   public constant JUDGE_COUNT         = 3;
    uint256 public constant COMMIT_WINDOW       = 5 minutes;
    uint256 public constant REVEAL_WINDOW       = 5 minutes;
    uint256 public constant STAKE_LOCK_DURATION = 30 minutes;
    uint256 public constant MAX_CANDIDATES      = 20;

    uint8 public constant RESPONSE_VALID    = 100;
    uint8 public constant RESPONSE_INVALID  = 0;
    uint8 public constant RESPONSE_DISPUTED = 50;

    uint8 private constant AGENT_TYPE_PROVIDER = 0;
    uint8 private constant AGENT_TYPE_JUDGE    = 1;

    // ── State Variables ───────────────────────────────────────────────────────

    // Contrats liés
    IIdentityRegistry   public identityRegistry;
    IStakingContract    public stakingContract;
    IEscrowManager      public escrowManager;

    // Scores séparés par mode — source unique pour scores et matrice C EigenTrust
    mapping(string  => uint256) public _agentSoloTotal;
    mapping(string  => uint256) public _agentSoloCount;
    mapping(string  => uint256) public _agentPipelineTotal;
    mapping(string  => uint256) public _agentPipelineCount;

    // Taux d'accord des juges (on-chain)
    mapping(address => uint256) public judgeAgreements;
    mapping(address => uint256) public judgeTotalVotes;

    // ── Honeypot — autorisation des juges ─────────────────────────────────────
    mapping(string => bool) public judgeAuthorized;  // judgeId → test technique passé

    // Tâches de validation
    mapping(string  => ValidationTask)                 private _tasks;
    mapping(string  => bool)                           private _taskExists;
    mapping(string  => mapping(string => JudgeCommit)) private _commits;
    mapping(string  => string)                         private _judgeActiveTask;

    // ERC-8004 stockage
    mapping(bytes32 => ValidationRecord) private _validationRecords;
    mapping(uint256 => bytes32[])        private _agentValidations;  // tokenId → requestHashes
    mapping(address => bytes32[])        private _validatorRequests; // validatorAddress → requestHashes

    // ── Events ────────────────────────────────────────────────────────────────

    // ERC-8004
    event ValidationRequest(
        address indexed validatorAddress,
        uint256 indexed agentId,
        string          requestURI,
        bytes32 indexed requestHash
    );

    event ValidationResponse(
        address indexed validatorAddress,
        uint256 indexed agentId,
        bytes32 indexed requestHash,
        uint8           response,
        string          responseURI,
        bytes32         responseHash,
        string          tag
    );

    // Internes
    event JudgesAssigned(string indexed taskId, string judge0, string judge1, string judge2, uint256 commitDeadline, uint256 revealDeadline);
    event VoteCommitted(string indexed taskId, string indexed judgeId);
    event VoteRevealed(string indexed taskId, string indexed judgeId, InternalVote vote, uint8 taskCompletion, uint8 outputQuality, uint8 noFabrication, uint8 toolUsage);
    event ScoreRecorded(string agentId, string taskId, uint8 score, uint8 mode);
    event JudgeScoreUpdated(address indexed judgeWallet, uint256 agreementRate, uint256 totalVotes);
    event ProviderSlashed(string indexed agentId, address indexed wallet, uint256 amount);
    event JudgeSlashed(string indexed agentId, address indexed wallet, uint256 amount, string reason);
    event TaskExpired(string indexed taskId);

    // Honeypot events
    event HoneypotPassed(string judgeId, string resultCID);
    event HoneypotFailed(string judgeId, string resultCID);

    // ── Errors ────────────────────────────────────────────────────────────────

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
    error NotExpirable(string taskId);
    error ZeroAddress();

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor(
        address identityRegistry_,
        address stakingContract_
    ) Ownable(msg.sender) {
        if (identityRegistry_ == address(0) ||
            stakingContract_  == address(0)) revert ZeroAddress();

        identityRegistry = IIdentityRegistry(identityRegistry_);
        stakingContract  = IStakingContract(stakingContract_);
    }

    // ── Admin ─────────────────────────────────────────────────────────────────

    function setIdentityRegistry(address a) external onlyOwner { if (a == address(0)) revert ZeroAddress(); identityRegistry = IIdentityRegistry(a); }
    function setStakingContract (address a) external onlyOwner { if (a == address(0)) revert ZeroAddress(); stakingContract  = IStakingContract(a);  }
    function setEscrowManager   (address a) external onlyOwner { if (a == address(0)) revert ZeroAddress(); escrowManager    = IEscrowManager(a);    }

    // ── Honeypot ──────────────────────────────────────────────────────────────

    /**
     * @notice Enregistre le résultat d'un honeypot pour un juge.
     *         Appelé par le backend (onlyOwner) après chaque vérification.
     * @param judgeId_   agentId du juge
     * @param passed_    true = honeypot réussi
     * @param resultCID_ IPFS CID du document de résultat
     */
    function recordHoneypotResult(
        string calldata judgeId_,
        bool            passed_,
        string calldata resultCID_
    ) external onlyOwner {
        judgeAuthorized[judgeId_] = passed_;
        if (passed_) emit HoneypotPassed(judgeId_, resultCID_);
        else         emit HoneypotFailed(judgeId_, resultCID_);
    }

    /**
     * @notice Retourne true si le juge est autorisé à valider.
     */
    function isJudgeAuthorized(string calldata judgeId_) external view returns (bool) {
        return judgeAuthorized[judgeId_];
    }

    // ── External — Validation Flow ────────────────────────────────────────────

    /**
     * @notice Étape 1 — Soumet un résultat pour validation.
     * @param taskId_          ID unique de la tâche
     * @param providerAgentId_ agentId du provider (IdentityRegistry)
     * @param requestURI_      IPFS URI du résultat complet
     * @param requestHash_     keccak256(résultat) = evidenceHash
     * @param traceHash_       keccak256(trace JSON) — vérifiable par les juges
     * @param mode_            0=solo 1=pipeline
     */
    function validationRequest(
        string  calldata taskId_,
        string  calldata providerAgentId_,
        string  calldata requestURI_,
        bytes32          requestHash_,
        bytes32          traceHash_,
        uint8            mode_
    ) external nonReentrant {
        if (_taskExists[taskId_]) revert TaskAlreadyExists(taskId_);

        if (!identityRegistry.isActive(providerAgentId_)) revert ProviderIneligible(providerAgentId_);
        if (identityRegistry.getAgentType(providerAgentId_) != AGENT_TYPE_PROVIDER) revert ProviderIneligible(providerAgentId_);

        address providerWallet = identityRegistry.getAgentWallet(providerAgentId_);
        if (!stakingContract.isEligibleProvider(providerWallet)) revert ProviderIneligible(providerAgentId_);

        uint256 erc8004AgentId = identityRegistry.getCurrentTokenId(providerAgentId_);
        stakingContract.lockStake(providerWallet, STAKE_LOCK_DURATION);

        ValidationTask storage t = _tasks[taskId_];
        t.taskId          = taskId_;
        t.providerAgentId = providerAgentId_;
        t.providerWallet  = providerWallet;
        t.requestHash     = requestHash_;
        t.traceHash       = traceHash_;
        t.erc8004AgentId  = erc8004AgentId;
        t.status          = TaskStatus.PENDING;
        t.createdAt       = block.timestamp;
        t.mode            = mode_;
        _taskExists[taskId_] = true;

        _validationRecords[requestHash_] = ValidationRecord({
            validatorAddress: address(this),
            agentId:          erc8004AgentId,
            response:         0,
            responseHash:     bytes32(0),
            tag:              "PENDING",
            responseURI:      "",
            lastUpdate:       block.timestamp
        });
        _agentValidations[erc8004AgentId].push(requestHash_);
        _validatorRequests[address(this)].push(requestHash_);

        emit ValidationRequest(address(this), erc8004AgentId, requestURI_, requestHash_);
    }

    /**
     * @notice Étape 2 — Assigne 3 juges parmi les candidats proposés.
     *         Fisher-Yates on-chain. Vérifie 6 critères d'éligibilité par candidat.
     * @param candidates_ agentIds proposés (≥ JUDGE_COUNT, ≤ MAX_CANDIDATES)
     */
    function assignJudges(
        string calldata   taskId_,
        string[] calldata candidates_
    ) external onlyOwner nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        if (t.status != TaskStatus.PENDING) revert WrongStatus(taskId_, t.status);
        if (candidates_.length > MAX_CANDIDATES) revert TooManyCandidates(candidates_.length, MAX_CANDIDATES);

        string[20] memory eligible;
        uint256 eligibleCount = 0;
        for (uint256 i = 0; i < candidates_.length; i++) {
            if (eligibleCount == MAX_CANDIDATES) break;
            if (_isEligibleJudge(candidates_[i]) && judgeAuthorized[candidates_[i]])
                eligible[eligibleCount++] = candidates_[i];
        }
        if (eligibleCount < JUDGE_COUNT) revert NotEnoughEligibleJudges(eligibleCount, JUDGE_COUNT);

        uint256 seed = uint256(keccak256(abi.encodePacked(block.prevrandao, block.timestamp, taskId_, msg.sender)));

        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            uint256 swapIdx    = i + (seed % (eligibleCount - i));
            seed               = uint256(keccak256(abi.encodePacked(seed)));
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

        emit JudgesAssigned(taskId_, t.judgeIds[0], t.judgeIds[1], t.judgeIds[2], t.commitDeadline, t.revealDeadline);
    }

    /**
     * @notice Étape 3 — Juge soumet son vote hashé.
     * @param commitHash_ keccak256(abi.encode(vote, scores×4, salt))
     */
    function commitVote(
        string  calldata taskId_,
        string  calldata judgeId_,
        bytes32          commitHash_
    ) external nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        if (t.status != TaskStatus.COMMITTING) revert WrongStatus(taskId_, t.status);
        if (block.timestamp > t.commitDeadline) revert CommitWindowClosed(taskId_);

        uint256 idx      = _judgeIndexOf(t, judgeId_);
        address expected = t.judgeWallets[idx];
        if (msg.sender != expected) revert CallerNotJudgeWallet(judgeId_, msg.sender, expected);

        JudgeCommit storage c = _commits[taskId_][judgeId_];
        if (c.committed) revert AlreadyCommitted(judgeId_);

        c.commitHash = commitHash_;
        c.committed  = true;

        emit VoteCommitted(taskId_, judgeId_);
        if (_allCommitted(t)) t.status = TaskStatus.REVEALING;
    }

    /**
     * @notice Étape 4 — Juge révèle son vote et ses 4 scores (0-25 chacun).
     */
    function revealVote(
        string       calldata taskId_,
        string       calldata judgeId_,
        InternalVote          vote_,
        bytes32               salt_,
        uint8                 taskCompletion_,
        uint8                 outputQuality_,
        uint8                 noFabrication_,
        uint8                 toolUsage_
    ) external nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        if (t.status == TaskStatus.COMMITTING) {
            if (block.timestamp <= t.commitDeadline) revert CommitWindowStillOpen(taskId_);
            t.status = TaskStatus.REVEALING;
        }
        if (t.status != TaskStatus.REVEALING) revert WrongStatus(taskId_, t.status);
        if (block.timestamp > t.revealDeadline) revert RevealWindowClosed(taskId_);
        if (vote_ == InternalVote.NONE) revert VoteIsNone();
        require(taskCompletion_ <= 25 && outputQuality_ <= 25 && noFabrication_ <= 25 && toolUsage_ <= 25, "Score out of range");

        uint256 idx      = _judgeIndexOf(t, judgeId_);
        address expected = t.judgeWallets[idx];
        if (msg.sender != expected) revert CallerNotJudgeWallet(judgeId_, msg.sender, expected);

        JudgeCommit storage c = _commits[taskId_][judgeId_];
        if (!c.committed) revert NotAJudgeOfTask(judgeId_, taskId_);
        if (c.revealed)   revert AlreadyRevealed(judgeId_);

        if (keccak256(abi.encode(vote_, taskCompletion_, outputQuality_, noFabrication_, toolUsage_, salt_)) != c.commitHash)
            revert CommitMismatch(judgeId_);

        c.vote           = vote_;
        c.taskCompletion = taskCompletion_;
        c.outputQuality  = outputQuality_;
        c.noFabrication  = noFabrication_;
        c.toolUsage      = toolUsage_;
        c.revealed       = true;

        emit VoteRevealed(taskId_, judgeId_, vote_, taskCompletion_, outputQuality_, noFabrication_, toolUsage_);
    }

    /**
     * @notice Étape 5 — Clôture la validation, calcule le consensus on-chain.
     *         Appelable par n'importe qui après la deadline ou quand tous ont révélé.
     * @param justificationURI_ IPFS URI du document JSON agrégé des justifications juges
     */
    function finaliseValidation(
        string calldata taskId_,
        string calldata justificationURI_
    ) external nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        if (t.status != TaskStatus.REVEALING) revert WrongStatus(taskId_, t.status);
        if (!_allRevealed(t) && block.timestamp <= t.revealDeadline) revert RevealWindowStillOpen(taskId_);

        uint256 validCount = 0; uint256 invalidCount = 0;
        uint256 totalScore = 0; uint256 revealCount  = 0;
        bool[3] memory votedValid; bool[3] memory didReveal;

        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            JudgeCommit storage c = _commits[taskId_][t.judgeIds[i]];
            if (!c.revealed) continue;
            didReveal[i] = true; revealCount++;
            totalScore  += uint256(c.taskCompletion) + uint256(c.outputQuality) + uint256(c.noFabrication) + uint256(c.toolUsage);
            if (c.vote == InternalVote.VALID)   { validCount++;   votedValid[i] = true; }
            if (c.vote == InternalVote.INVALID) { invalidCount++; }
        }

        uint256 aggregatedScore = revealCount > 0 ? totalScore / revealCount : 0;

        uint8 erc8004Response; string memory tag;
        if      (validCount   >= 2) { erc8004Response = RESPONSE_VALID;    tag = "VALID";    }
        else if (invalidCount >= 2) { erc8004Response = RESPONSE_INVALID;  tag = "INVALID";  }
        else                        { erc8004Response = RESPONSE_DISPUTED; tag = "DISPUTED"; }

        t.finalResponse = erc8004Response; t.finalTag = tag;
        t.score         = aggregatedScore; t.status   = TaskStatus.FINALISED;

        emit ScoreRecorded(t.providerAgentId, taskId_, uint8(aggregatedScore), t.mode);

        if (t.mode == 0) {
            _agentSoloTotal[t.providerAgentId] += aggregatedScore;
            _agentSoloCount[t.providerAgentId] += 1;
        } else {
            _agentPipelineTotal[t.providerAgentId] += aggregatedScore;
            _agentPipelineCount[t.providerAgentId] += 1;
        }

        _recordValidationResponse(t.requestHash, t.erc8004AgentId, erc8004Response, justificationURI_, tag);

        if (erc8004Response != RESPONSE_DISPUTED) {
            bool providerValid = (erc8004Response == RESPONSE_VALID);
            _applyOutcomes(t, providerValid, votedValid, didReveal);

            if (address(escrowManager) != address(0)) {
                address[] memory validJudges = new address[](validCount);
                uint256 idx = 0;
                for (uint8 i = 0; i < JUDGE_COUNT; i++) {
                    if (votedValid[i]) validJudges[idx++] = t.judgeWallets[i];
                }
                // Provider toujours payé — slash géré par StakingContract si INVALID
                if (t.mode == 1) { try escrowManager.releaseFundsPipeline(taskId_, validJudges) {} catch {} }
                else             { try escrowManager.releaseFunds(taskId_, t.providerWallet, validJudges) {} catch {} }
            }
        } else {
            // DISPUTED uniquement → remboursement client (pas de consensus)
            if (address(escrowManager) != address(0)) { try escrowManager.refundClient(taskId_) {} catch {} }
        }

        stakingContract.unlockStake(t.providerWallet);
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            if (t.judgeWallets[i] != address(0)) stakingContract.unlockStake(t.judgeWallets[i]);
            if (bytes(t.judgeIds[i]).length > 0) delete _judgeActiveTask[t.judgeIds[i]];
        }
    }

    /**
     * @notice Force l'expiration si les deadlines sont passées sans vote.
     */
    function expireTask(string calldata taskId_) external nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        bool expirable =
            (t.status == TaskStatus.COMMITTING && block.timestamp > t.commitDeadline) ||
            (t.status == TaskStatus.REVEALING  && block.timestamp > t.revealDeadline);
        if (!expirable) revert NotExpirable(taskId_);

        t.status = TaskStatus.EXPIRED; t.finalResponse = 0; t.finalTag = "EXPIRED";
        _recordValidationResponse(t.requestHash, t.erc8004AgentId, 0, "", "EXPIRED");
        stakingContract.unlockStake(t.providerWallet);
        if (address(escrowManager) != address(0)) { try escrowManager.refundClient(taskId_) {} catch {} }

        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            string  storage jid    = t.judgeIds[i];
            address         jwallet = t.judgeWallets[i];
            if (jwallet == address(0)) continue;
            JudgeCommit storage c = _commits[taskId_][jid];
            if (!c.committed || !c.revealed) {
                uint256 amt = stakingContract.slashJudge(jwallet);
                emit JudgeSlashed(jid, jwallet, amt, "ABSENT");
            }
            stakingContract.unlockStake(jwallet);
            delete _judgeActiveTask[jid];
        }
        emit TaskExpired(taskId_);
    }

    /**
     * @notice Émet ScoreRecorded(mode=1) pour les agents non-lead d'un pipeline.
     */
    function recordPipelineScores(
        string[] calldata agentIds_,
        string   calldata taskId_,
        uint8[]  calldata scores_
    ) external onlyOwner {
        require(agentIds_.length == scores_.length, "length mismatch");
        for (uint256 i = 0; i < agentIds_.length; i++) {
            emit ScoreRecorded(agentIds_[i], taskId_, scores_[i], 1);
        }
    }

    // ── Views — ERC-8004 ──────────────────────────────────────────────────────

    function getValidationStatus(bytes32 requestHash)
        external view returns (address validatorAddress, uint256 agentId, uint8 response, bytes32 responseHash, string memory tag, uint256 lastUpdate)
    {
        ValidationRecord storage rec = _validationRecords[requestHash];
        return (rec.validatorAddress, rec.agentId, rec.response, rec.responseHash, rec.tag, rec.lastUpdate);
    }

    function getSummary(uint256 agentId_, address[] calldata validatorAddresses, string calldata tag_)
        external view returns (uint64 count, uint8 averageResponse)
    {
        bytes32[] storage hashes    = _agentValidations[agentId_];
        bool      filterValidator   = validatorAddresses.length > 0;
        bool      filterTag         = bytes(tag_).length > 0;
        uint256   total = 0; uint256 matched = 0;

        for (uint256 i = 0; i < hashes.length; i++) {
            ValidationRecord storage rec = _validationRecords[hashes[i]];
            if (filterValidator) {
                bool found = false;
                for (uint256 j = 0; j < validatorAddresses.length; j++) {
                    if (rec.validatorAddress == validatorAddresses[j]) { found = true; break; }
                }
                if (!found) continue;
            }
            if (filterTag && keccak256(bytes(rec.tag)) != keccak256(bytes(tag_))) continue;
            bytes32 tagHash = keccak256(bytes(rec.tag));
            if (tagHash == keccak256(bytes("PENDING")) || tagHash == keccak256(bytes("EXPIRED"))) continue;
            total += rec.response; matched++;
        }
        count = uint64(matched); averageResponse = matched > 0 ? uint8(total / matched) : 0;
    }

    function getAgentValidations(uint256 agentId_) external view returns (bytes32[] memory) {
        return _agentValidations[agentId_];
    }

    function getValidatorRequests(address validatorAddress) external view returns (bytes32[] memory) {
        return _validatorRequests[validatorAddress];
    }

    // ── Views — Internes ──────────────────────────────────────────────────────

    function getTask(string calldata taskId_) external view returns (ValidationTask memory) {
        return _getTask(taskId_);
    }

    /**
     * @notice Retourne le responseURI (CID IPFS des justifications juges) d'une tâche.
     * @dev _validationRecords est private — ce getter permet la lecture via RPC direct
     *      sans passer par The Graph, avec zéro délai d'indexation.
     */
    function getResponseURI(string calldata taskId_) external view returns (string memory) {
        return _validationRecords[_getTask(taskId_).requestHash].responseURI;
    }

    function getTraceHash(string calldata taskId_) external view returns (bytes32) {
        return _getTask(taskId_).traceHash;
    }

    function getJudgeCommit(string calldata taskId_, string calldata judgeId_) external view returns (JudgeCommit memory) {
        return _commits[taskId_][judgeId_];
    }

    function isJudgeBusy(string calldata judgeId_) external view returns (bool) {
        return bytes(_judgeActiveTask[judgeId_]).length > 0;
    }

    function getJudgeActiveTask(string calldata judgeId_) external view returns (string memory) {
        return _judgeActiveTask[judgeId_];
    }

    function getAgentScore(string calldata agentId_) external view returns (uint256 averageScore, uint256 totalTasks) {
        totalTasks        = _agentSoloCount[agentId_] + _agentPipelineCount[agentId_];
        uint256 total     = _agentSoloTotal[agentId_] + _agentPipelineTotal[agentId_];
        averageScore      = totalTasks > 0 ? total / totalTasks : 0;
    }

    function getAgentModeScores(string calldata agentId_) external view returns (
        uint256 soloTotal, uint256 soloCount,
        uint256 pipelineTotal, uint256 pipelineCount
    ) {
        soloTotal     = _agentSoloTotal[agentId_];
        soloCount     = _agentSoloCount[agentId_];
        pipelineTotal = _agentPipelineTotal[agentId_];
        pipelineCount = _agentPipelineCount[agentId_];
    }

    function getJudgeAgreementRate(address judgeWallet_) external view returns (uint256 rate, uint256 totalVotes) {
        totalVotes = judgeTotalVotes[judgeWallet_];
        rate       = totalVotes > 0 ? (judgeAgreements[judgeWallet_] * 100) / totalVotes : 50;
    }

    function isEligibleJudgeCandidate(string calldata judgeId_) external view returns (bool) {
        return _isEligibleJudge(judgeId_);
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    function _getTask(string memory taskId_) internal view returns (ValidationTask storage) {
        if (!_taskExists[taskId_]) revert TaskNotFound(taskId_);
        return _tasks[taskId_];
    }

    function _judgeIndexOf(ValidationTask storage t, string memory judgeId_) internal view returns (uint256) {
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

    function _recordValidationResponse(bytes32 requestHash_, uint256 erc8004AgentId_, uint8 response_, string memory responseURI_, string memory tag_) internal {
        bytes32 responseHash = keccak256(abi.encode(requestHash_, response_, tag_));
        ValidationRecord storage rec = _validationRecords[requestHash_];
        rec.response     = response_;
        rec.responseHash = responseHash;
        rec.tag          = tag_;
        rec.responseURI  = responseURI_;
        rec.lastUpdate   = block.timestamp;
        emit ValidationResponse(address(this), erc8004AgentId_, requestHash_, response_, responseURI_, responseHash, tag_);
    }

    function _applyOutcomes(ValidationTask storage t, bool providerValid, bool[3] memory votedValid, bool[3] memory didReveal) internal {
        if (!providerValid) {
            uint256 slashedAmt = stakingContract.slashProvider(t.providerWallet);
            emit ProviderSlashed(t.providerAgentId, t.providerWallet, slashedAmt);
        }

        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            string  storage jid    = t.judgeIds[i];
            address         jwallet = t.judgeWallets[i];
            if (jwallet == address(0)) continue;

            if (!didReveal[i]) {
                uint256 amt = stakingContract.slashJudge(jwallet);
                emit JudgeSlashed(jid, jwallet, amt, "ABSENT");
            } else {
                bool aligned = (providerValid && votedValid[i]) || (!providerValid && !votedValid[i]);
                if (aligned) {
                    judgeAgreements[jwallet]++;
                } else {
                    uint256 amt = stakingContract.slashJudge(jwallet);
                    emit JudgeSlashed(jid, jwallet, amt, "DEVIATED");
                }
                judgeTotalVotes[jwallet]++;
                uint256 rate = (judgeAgreements[jwallet] * 100) / judgeTotalVotes[jwallet];
                emit JudgeScoreUpdated(jwallet, rate, judgeTotalVotes[jwallet]);
            }
        }
    }
}
