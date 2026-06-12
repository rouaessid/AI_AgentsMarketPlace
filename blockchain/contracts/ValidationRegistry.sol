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
//  Identifiants : tous les agents sont référencés par tokenId (uint256 ERC-721).
//  Le backend résout agentId → tokenId via IdentityRegistry avant tout appel.
//
//  Contrats liés :
//    IdentityRegistry   → identité + type + wallet des agents (via tokenId)
//    StakingContract    → éligibilité + lock/unlock/slash des stakes
//    ReputationRegistry → écriture des scores après consensus
//    EscrowManager      → libération/remboursement des paiements
// ════════════════════════════════════════════════════════════════════════════

import "./interfaces/IIdentityRegistry.sol";
import "./interfaces/IStakingContract.sol";
import "./interfaces/IEscrowManager.sol";

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
        string     taskId;
        uint256    providerTokenId;  // tokenId ERC-721 du provider
        address    providerWallet;
        bytes32    requestHash;
        bytes32    traceHash;        // keccak256(trace JSON) — vérifiable par les juges
        TaskStatus status;
        uint256    createdAt;
        uint256    commitDeadline;
        uint256    revealDeadline;
        uint256[3] judgeTokenIds;    // tokenIds ERC-721 des 3 juges
        address[3] judgeWallets;
        uint8      finalResponse;    // 0=INVALID 50=DISPUTED 100=VALID
        string     finalTag;         // "VALID" | "INVALID" | "DISPUTED" | "EXPIRED"
        uint256    score;            // score agrégé 0-100
        uint8      mode;             // 0=solo 1=pipeline
    }

    struct ValidationRecord {
        address validatorAddress; // toujours address(this)
        uint256 tokenId;          // tokenId ERC-721 du provider
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

    IIdentityRegistry   public identityRegistry;
    IStakingContract    public stakingContract;
    IEscrowManager      public escrowManager;

    // Scores par tokenId — source pour EigenTrust
    mapping(uint256 => uint256) public _agentSoloTotal;
    mapping(uint256 => uint256) public _agentSoloCount;
    mapping(uint256 => uint256) public _agentPipelineTotal;
    mapping(uint256 => uint256) public _agentPipelineCount;

    // Taux d'accord des juges (on-chain)
    mapping(address => uint256) public judgeAgreements;
    mapping(address => uint256) public judgeTotalVotes;

    // Honeypot — autorisation des juges
    mapping(uint256 => bool) public judgeAuthorized;  // judgeTokenId → honeypot passé

    // Tâches de validation
    mapping(string  => ValidationTask)                  private _tasks;
    mapping(string  => bool)                            private _taskExists;
    mapping(string  => mapping(uint256 => JudgeCommit)) private _commits;
    mapping(uint256 => string)                          private _judgeActiveTask;

    mapping(bytes32 => ValidationRecord) private _validationRecords;

    // ── Events ────────────────────────────────────────────────────────────────

    event ValidationRequest(
        address indexed validatorAddress,
        uint256 indexed tokenId,
        string          requestURI,
        bytes32 indexed requestHash
    );

    event ValidationResponse(
        address indexed validatorAddress,
        uint256 indexed tokenId,
        bytes32 indexed requestHash,
        uint8           response,
        string          responseURI,
        bytes32         responseHash,
        string          tag
    );

    event JudgesAssigned(string indexed taskId, uint256 judge0, uint256 judge1, uint256 judge2, uint256 commitDeadline, uint256 revealDeadline);
    event VoteCommitted(string indexed taskId, uint256 indexed judgeTokenId);
    event VoteRevealed(string indexed taskId, uint256 indexed judgeTokenId, InternalVote vote, uint8 taskCompletion, uint8 outputQuality, uint8 noFabrication, uint8 toolUsage);
    event ScoreRecorded(uint256 indexed tokenId, string taskId, uint8 score, uint8 mode);
    event JudgeScoreUpdated(address indexed judgeWallet, uint256 agreementRate, uint256 totalVotes);
    event ProviderSlashed(uint256 indexed tokenId, address indexed wallet, uint256 amount);
    event JudgeSlashed(uint256 indexed tokenId, address indexed wallet, uint256 amount, string reason);
    event TaskExpired(string indexed taskId);
    event HoneypotPassed(uint256 judgeTokenId, string resultCID);
    event HoneypotFailed(uint256 judgeTokenId, string resultCID);

    // ── Errors ────────────────────────────────────────────────────────────────

    error TaskNotFound(string taskId);
    error TaskAlreadyExists(string taskId);
    error WrongStatus(string taskId, TaskStatus current);
    error NotAJudgeOfTask(uint256 judgeTokenId, string taskId);
    error AlreadyCommitted(uint256 judgeTokenId);
    error AlreadyRevealed(uint256 judgeTokenId);
    error CommitMismatch(uint256 judgeTokenId);
    error VoteIsNone();
    error CommitWindowClosed(string taskId);
    error CommitWindowStillOpen(string taskId);
    error RevealWindowClosed(string taskId);
    error RevealWindowStillOpen(string taskId);
    error CallerNotJudgeWallet(uint256 judgeTokenId, address caller, address expected);
    error ProviderIneligible(uint256 tokenId);
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

    function recordHoneypotResult(
        uint256         judgeTokenId_,
        bool            passed_,
        string calldata resultCID_
    ) external onlyOwner {
        judgeAuthorized[judgeTokenId_] = passed_;
        if (passed_) emit HoneypotPassed(judgeTokenId_, resultCID_);
        else         emit HoneypotFailed(judgeTokenId_, resultCID_);
    }

    function isJudgeAuthorized(uint256 judgeTokenId_) external view returns (bool) {
        return judgeAuthorized[judgeTokenId_];
    }

    // ── External — Validation Flow ────────────────────────────────────────────

    /**
     * @notice Étape 1 — Soumet un résultat pour validation.
     * @param providerTokenId_ tokenId ERC-721 du provider (capturé par le backend au début de l'exécution)
     */
    function validationRequest(
        string  calldata taskId_,
        uint256          providerTokenId_,
        string  calldata requestURI_,
        bytes32          requestHash_,
        bytes32          traceHash_,
        uint8            mode_
    ) external nonReentrant {
        if (_taskExists[taskId_]) revert TaskAlreadyExists(taskId_);

        if (!identityRegistry.isActiveByTokenId(providerTokenId_))                      revert ProviderIneligible(providerTokenId_);
        if (identityRegistry.getAgentTypeByTokenId(providerTokenId_) != AGENT_TYPE_PROVIDER) revert ProviderIneligible(providerTokenId_);

        address providerWallet = identityRegistry.getAgentWalletByTokenId(providerTokenId_);
        if (!stakingContract.isEligibleProvider(providerWallet)) revert ProviderIneligible(providerTokenId_);

        stakingContract.lockStake(providerWallet, STAKE_LOCK_DURATION);

        ValidationTask storage t = _tasks[taskId_];
        t.taskId          = taskId_;
        t.providerTokenId = providerTokenId_;
        t.providerWallet  = providerWallet;
        t.requestHash     = requestHash_;
        t.traceHash       = traceHash_;
        t.status          = TaskStatus.PENDING;
        t.createdAt       = block.timestamp;
        t.mode            = mode_;
        _taskExists[taskId_] = true;

        _validationRecords[requestHash_] = ValidationRecord({
            validatorAddress: address(this),
            tokenId:          providerTokenId_,
            response:         0,
            responseHash:     bytes32(0),
            tag:              "PENDING",
            responseURI:      "",
            lastUpdate:       block.timestamp
        });
        emit ValidationRequest(address(this), providerTokenId_, requestURI_, requestHash_);
    }

    /**
     * @notice Étape 2 — Assigne 3 juges parmi les candidats proposés.
     * @param candidates_ tokenIds des juges candidats (≥ JUDGE_COUNT, ≤ MAX_CANDIDATES)
     */
    function assignJudges(
        string    calldata taskId_,
        uint256[] calldata candidates_
    ) external onlyOwner nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        if (t.status != TaskStatus.PENDING) revert WrongStatus(taskId_, t.status);
        if (candidates_.length > MAX_CANDIDATES) revert TooManyCandidates(candidates_.length, MAX_CANDIDATES);

        uint256[20] memory eligible;
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
            uint256 tmp        = eligible[i];
            eligible[i]        = eligible[swapIdx];
            eligible[swapIdx]  = tmp;

            uint256 judgeTokenId = eligible[i];
            address judgeWallet  = identityRegistry.getAgentWalletByTokenId(judgeTokenId);
            t.judgeTokenIds[i]   = judgeTokenId;
            t.judgeWallets[i]    = judgeWallet;
            _judgeActiveTask[judgeTokenId] = taskId_;
            stakingContract.lockStake(judgeWallet, STAKE_LOCK_DURATION);
        }

        t.status         = TaskStatus.COMMITTING;
        t.commitDeadline = block.timestamp + COMMIT_WINDOW;
        t.revealDeadline = t.commitDeadline + REVEAL_WINDOW;

        emit JudgesAssigned(taskId_, t.judgeTokenIds[0], t.judgeTokenIds[1], t.judgeTokenIds[2], t.commitDeadline, t.revealDeadline);
    }

    /**
     * @notice Étape 3 — Juge soumet son vote hashé.
     */
    function commitVote(
        string  calldata taskId_,
        uint256          judgeTokenId_,
        bytes32          commitHash_
    ) external nonReentrant {
        ValidationTask storage t = _getTask(taskId_);

        if (t.status != TaskStatus.COMMITTING) revert WrongStatus(taskId_, t.status);
        if (block.timestamp > t.commitDeadline) revert CommitWindowClosed(taskId_);

        uint256 idx      = _judgeIndexOf(t, judgeTokenId_);
        address expected = t.judgeWallets[idx];
        if (msg.sender != expected) revert CallerNotJudgeWallet(judgeTokenId_, msg.sender, expected);

        JudgeCommit storage c = _commits[taskId_][judgeTokenId_];
        if (c.committed) revert AlreadyCommitted(judgeTokenId_);

        c.commitHash = commitHash_;
        c.committed  = true;

        emit VoteCommitted(taskId_, judgeTokenId_);
        if (_allCommitted(t)) t.status = TaskStatus.REVEALING;
    }

    /**
     * @notice Étape 4 — Juge révèle son vote et ses 4 scores (0-25 chacun).
     */
    function revealVote(
        string       calldata taskId_,
        uint256               judgeTokenId_,
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

        uint256 idx      = _judgeIndexOf(t, judgeTokenId_);
        address expected = t.judgeWallets[idx];
        if (msg.sender != expected) revert CallerNotJudgeWallet(judgeTokenId_, msg.sender, expected);

        JudgeCommit storage c = _commits[taskId_][judgeTokenId_];
        if (!c.committed) revert NotAJudgeOfTask(judgeTokenId_, taskId_);
        if (c.revealed)   revert AlreadyRevealed(judgeTokenId_);

        if (keccak256(abi.encode(vote_, taskCompletion_, outputQuality_, noFabrication_, toolUsage_, salt_)) != c.commitHash)
            revert CommitMismatch(judgeTokenId_);

        c.vote           = vote_;
        c.taskCompletion = taskCompletion_;
        c.outputQuality  = outputQuality_;
        c.noFabrication  = noFabrication_;
        c.toolUsage      = toolUsage_;
        c.revealed       = true;

        emit VoteRevealed(taskId_, judgeTokenId_, vote_, taskCompletion_, outputQuality_, noFabrication_, toolUsage_);
    }

    /**
     * @notice Étape 5 — Clôture la validation, calcule le consensus on-chain.
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
            JudgeCommit storage c = _commits[taskId_][t.judgeTokenIds[i]];
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

        emit ScoreRecorded(t.providerTokenId, taskId_, uint8(aggregatedScore), t.mode);

        if (t.mode == 0) {
            _agentSoloTotal[t.providerTokenId] += aggregatedScore;
            _agentSoloCount[t.providerTokenId] += 1;
        } else {
            _agentPipelineTotal[t.providerTokenId] += aggregatedScore;
            _agentPipelineCount[t.providerTokenId] += 1;
        }

        _recordValidationResponse(t.requestHash, t.providerTokenId, erc8004Response, justificationURI_, tag);

        if (erc8004Response != RESPONSE_DISPUTED) {
            bool providerValid = (erc8004Response == RESPONSE_VALID);
            _applyOutcomes(t, providerValid, votedValid, didReveal);

            if (address(escrowManager) != address(0)) {
                address[] memory validJudges = new address[](validCount);
                uint256 idx = 0;
                for (uint8 i = 0; i < JUDGE_COUNT; i++) {
                    if (votedValid[i]) validJudges[idx++] = t.judgeWallets[i];
                }
                if (t.mode == 1) { try escrowManager.releaseFundsPipeline(taskId_, validJudges) {} catch {} }
                else             { try escrowManager.releaseFunds(taskId_, t.providerWallet, validJudges) {} catch {} }
            }
        } else {
            if (address(escrowManager) != address(0)) { try escrowManager.refundClient(taskId_) {} catch {} }
        }

        stakingContract.unlockStake(t.providerWallet);
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            if (t.judgeWallets[i] != address(0)) stakingContract.unlockStake(t.judgeWallets[i]);
            if (t.judgeTokenIds[i] != 0) delete _judgeActiveTask[t.judgeTokenIds[i]];
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
        _recordValidationResponse(t.requestHash, t.providerTokenId, 0, "", "EXPIRED");
        stakingContract.unlockStake(t.providerWallet);
        if (address(escrowManager) != address(0)) { try escrowManager.refundClient(taskId_) {} catch {} }

        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            uint256 jTokenId = t.judgeTokenIds[i];
            address jwallet  = t.judgeWallets[i];
            if (jwallet == address(0)) continue;
            JudgeCommit storage c = _commits[taskId_][jTokenId];
            if (!c.committed || !c.revealed) {
                uint256 amt = stakingContract.slashJudge(jwallet);
                emit JudgeSlashed(jTokenId, jwallet, amt, "ABSENT");
            }
            stakingContract.unlockStake(jwallet);
            delete _judgeActiveTask[jTokenId];
        }
        emit TaskExpired(taskId_);
    }

    /**
     * @notice Admin-only: cancel a task stuck in PENDING (assignJudges never succeeded).
     * Unlocks the provider stake and refunds escrow. Safe because judges were never assigned.
     */
    function adminCancelPendingTask(string calldata taskId_) external onlyOwner nonReentrant {
        ValidationTask storage t = _getTask(taskId_);
        if (t.status != TaskStatus.PENDING) revert NotExpirable(taskId_);

        t.status = TaskStatus.EXPIRED; t.finalResponse = 0; t.finalTag = "EXPIRED";
        _recordValidationResponse(t.requestHash, t.providerTokenId, 0, "", "EXPIRED");
        stakingContract.unlockStake(t.providerWallet);
        if (address(escrowManager) != address(0)) { try escrowManager.refundClient(taskId_) {} catch {} }
        emit TaskExpired(taskId_);
    }

    // ── Views ─────────────────────────────────────────────────────────────────

    function getTask(string calldata taskId_) external view returns (ValidationTask memory) {
        return _getTask(taskId_);
    }

    function getResponseURI(string calldata taskId_) external view returns (string memory) {
        return _validationRecords[_getTask(taskId_).requestHash].responseURI;
    }

    function getTraceHash(string calldata taskId_) external view returns (bytes32) {
        return _getTask(taskId_).traceHash;
    }

    function getJudgeCommit(string calldata taskId_, uint256 judgeTokenId_) external view returns (JudgeCommit memory) {
        return _commits[taskId_][judgeTokenId_];
    }

    function isJudgeBusy(uint256 judgeTokenId_) external view returns (bool) {
        return bytes(_judgeActiveTask[judgeTokenId_]).length > 0;
    }

    function getJudgeActiveTask(uint256 judgeTokenId_) external view returns (string memory) {
        return _judgeActiveTask[judgeTokenId_];
    }

    function getAgentScore(uint256 tokenId_) external view returns (uint256 averageScore, uint256 totalTasks) {
        totalTasks    = _agentSoloCount[tokenId_] + _agentPipelineCount[tokenId_];
        uint256 total = _agentSoloTotal[tokenId_] + _agentPipelineTotal[tokenId_];
        averageScore  = totalTasks > 0 ? total / totalTasks : 0;
    }

    function getJudgeAgreementRate(address judgeWallet_) external view returns (uint256 rate, uint256 totalVotes) {
        totalVotes = judgeTotalVotes[judgeWallet_];
        rate       = totalVotes > 0 ? (judgeAgreements[judgeWallet_] * 100) / judgeTotalVotes[judgeWallet_] : 50;
    }

    function isEligibleJudgeCandidate(uint256 judgeTokenId_) external view returns (bool) {
        return _isEligibleJudge(judgeTokenId_);
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    function _getTask(string memory taskId_) internal view returns (ValidationTask storage) {
        if (!_taskExists[taskId_]) revert TaskNotFound(taskId_);
        return _tasks[taskId_];
    }

    function _judgeIndexOf(ValidationTask storage t, uint256 judgeTokenId_) internal view returns (uint256) {
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            if (t.judgeTokenIds[i] == judgeTokenId_) return i;
        }
        revert NotAJudgeOfTask(judgeTokenId_, t.taskId);
    }

    function _allCommitted(ValidationTask storage t) internal view returns (bool) {
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            if (!_commits[t.taskId][t.judgeTokenIds[i]].committed) return false;
        }
        return true;
    }

    function _allRevealed(ValidationTask storage t) internal view returns (bool) {
        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            if (!_commits[t.taskId][t.judgeTokenIds[i]].revealed) return false;
        }
        return true;
    }

    function _isEligibleJudge(uint256 tokenId_) internal view returns (bool) {
        if (!identityRegistry.agentTokenExists(tokenId_))                             return false;
        if (!identityRegistry.isActiveByTokenId(tokenId_))                            return false;
        if (identityRegistry.getAgentTypeByTokenId(tokenId_) != AGENT_TYPE_JUDGE)     return false;
        address wallet = identityRegistry.getAgentWalletByTokenId(tokenId_);
        if (!stakingContract.isEligibleJudge(wallet))                                 return false;
        if (stakingContract.isLocked(wallet))                                         return false;
        if (bytes(_judgeActiveTask[tokenId_]).length > 0)                             return false;
        return true;
    }

    function _recordValidationResponse(bytes32 requestHash_, uint256 tokenId_, uint8 response_, string memory responseURI_, string memory tag_) internal {
        bytes32 responseHash = keccak256(abi.encode(requestHash_, response_, tag_));
        ValidationRecord storage rec = _validationRecords[requestHash_];
        rec.response     = response_;
        rec.responseHash = responseHash;
        rec.tag          = tag_;
        rec.responseURI  = responseURI_;
        rec.lastUpdate   = block.timestamp;
        emit ValidationResponse(address(this), tokenId_, requestHash_, response_, responseURI_, responseHash, tag_);
    }

    function _applyOutcomes(ValidationTask storage t, bool providerValid, bool[3] memory votedValid, bool[3] memory didReveal) internal {
        if (!providerValid) {
            uint256 slashedAmt = stakingContract.slashProvider(t.providerWallet);
            emit ProviderSlashed(t.providerTokenId, t.providerWallet, slashedAmt);
        }

        for (uint8 i = 0; i < JUDGE_COUNT; i++) {
            uint256 jTokenId = t.judgeTokenIds[i];
            address jwallet  = t.judgeWallets[i];
            if (jwallet == address(0)) continue;

            if (!didReveal[i]) {
                uint256 amt = stakingContract.slashJudge(jwallet);
                emit JudgeSlashed(jTokenId, jwallet, amt, "ABSENT");
            } else {
                bool aligned = (providerValid && votedValid[i]) || (!providerValid && !votedValid[i]);
                if (aligned) {
                    judgeAgreements[jwallet]++;
                } else {
                    uint256 amt = stakingContract.slashJudge(jwallet);
                    emit JudgeSlashed(jTokenId, jwallet, amt, "DEVIATED");
                }
                judgeTotalVotes[jwallet]++;
                uint256 rate = (judgeAgreements[jwallet] * 100) / judgeTotalVotes[jwallet];
                emit JudgeScoreUpdated(jwallet, rate, judgeTotalVotes[jwallet]);
            }
        }
    }
}
