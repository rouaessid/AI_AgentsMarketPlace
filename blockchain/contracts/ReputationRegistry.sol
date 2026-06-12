// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import "@openzeppelin/contracts/access/Ownable.sol";

// ════════════════════════════════════════════════════════════════════════════
//  ReputationRegistry — AgentMarket · ERC-8004 Reputation Registry
//
//  Tags utilisés :
//    successRate  ← ValidationRegistry.recordFromValidation() (score 0-100, audit trail)
//    starred      ← user via giveFeedback() (note 1-5 → 20-100)
//
//  Scores calculés (state variables directes) :
//    eigenTrustScore[tokenId]  ← platform via setEigenTrustScore() (résultat off-chain)
//
//  Lecture :
//    getClients(tokenId)                           → liste des wallets ayant donné feedback
//    getLastIndex(tokenId, clientAddress)           → dernier index de feedback
//    readFeedback(tokenId, clientAddress, index)    → détail d'un feedback
//    getSummary(tokenId, clientAddresses[], tag1, tag2) → moyenne agrégée
// ════════════════════════════════════════════════════════════════════════════

import "./interfaces/IIdentityRegistry.sol";

// ════════════════════════════════════════════════════════════════════════════

contract ReputationRegistry is Ownable {

    // ── Type Declarations ─────────────────────────────────────────────────────

    struct FeedbackData {
        int128 value;
        uint8  valueDecimals;
        string tag1;
        string tag2;
        bool   isRevoked;
    }

    // ── State Variables ───────────────────────────────────────────────────────

    IIdentityRegistry public identityRegistry;

    // Callers autorisés à écrire via setEigenTrustScore()
    mapping(address => bool) public authorizedCallers;

    // tokenId → clientAddress → feedbackIndex (1-based) → données
    mapping(uint256 => mapping(address => mapping(uint64 => FeedbackData))) private _feedback;
    // tokenId → clientAddress → dernier index écrit
    mapping(uint256 => mapping(address => uint64)) private _lastIndex;
    // tokenId → liste des clientAddresses ayant donné un feedback
    mapping(uint256 => address[]) private _clients;
    // tokenId → clientAddress → a déjà donné un feedback (évite les doublons dans _clients)
    mapping(uint256 => mapping(address => bool)) private _isClient;

    // EigenTrust score courant par agent — écrit par la plateforme après calcul off-chain
    mapping(uint256 => uint256) public eigenTrustScore;

    // ── Events ────────────────────────────────────────────────────────────────

    event NewFeedback(
        uint256 indexed agentId,
        address indexed clientAddress,
        uint64          feedbackIndex,
        int128          value,
        uint8           valueDecimals,
        string indexed  indexedTag1,
        string          tag1,
        string          tag2,
        string          endpoint,
        string          feedbackURI,
        bytes32         feedbackHash
    );

    event FeedbackRevoked(
        uint256 indexed agentId,
        address indexed clientAddress,
        uint64  indexed feedbackIndex
    );

    event ResponseAppended(
        uint256 indexed agentId,
        address indexed clientAddress,
        uint64          feedbackIndex,
        address indexed responder,
        string          responseURI,
        bytes32         responseHash
    );

    // ── Errors ────────────────────────────────────────────────────────────────

    error RegistryNotInitialized();
    error AgentNotFound(uint256 agentId);
    error AgentIdNotFound(string agentId);
    error InvalidValueDecimals(uint8 valueDecimals);
    error AgentOwnerCannotRate(uint256 agentId);
    error FeedbackIndexOutOfBounds(uint64 feedbackIndex);
    error UnauthorizedCaller(address caller);

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor() Ownable(msg.sender) {}

    // ── Admin ─────────────────────────────────────────────────────────────────

    function initialize(address identityRegistry_) external onlyOwner {
        identityRegistry = IIdentityRegistry(identityRegistry_);
    }

    function setAuthorizedCaller(address caller, bool authorized) external onlyOwner {
        authorizedCallers[caller] = authorized;
    }

    function setEigenTrustScore(uint256 tokenId, uint256 score) external {
        if (!authorizedCallers[msg.sender] && msg.sender != owner()) revert UnauthorizedCaller(msg.sender);
        eigenTrustScore[tokenId] = score;
    }

    // ── External — ERC-8004 Write ─────────────────────────────────────────────

    /**
     * @notice Feedback public d'un utilisateur sur un agent.
     * @dev Le propriétaire du token ne peut pas noter son propre agent (ERC-8004).
     */
    function giveFeedback(
        uint256         agentId,
        int128          value,
        uint8           valueDecimals,
        string calldata tag1,
        string calldata tag2,
        string calldata endpoint,
        string calldata feedbackURI,
        bytes32         feedbackHash
    ) external {
        _requireRegistry();
        if (valueDecimals > 18) revert InvalidValueDecimals(valueDecimals);

        try identityRegistry.ownerOf(agentId) returns (address tokenOwner) {
            if (tokenOwner == msg.sender) revert AgentOwnerCannotRate(agentId);
        } catch {
            revert AgentNotFound(agentId);
        }

        _store(agentId, msg.sender, value, valueDecimals, tag1, tag2, endpoint, feedbackURI, feedbackHash);
    }

    function revokeFeedback(uint256 agentId, uint64 feedbackIndex) external {
        uint64 last = _lastIndex[agentId][msg.sender];
        if (feedbackIndex == 0 || feedbackIndex > last)
            revert FeedbackIndexOutOfBounds(feedbackIndex);

        _feedback[agentId][msg.sender][feedbackIndex].isRevoked = true;
        emit FeedbackRevoked(agentId, msg.sender, feedbackIndex);
    }

    function appendResponse(
        uint256         agentId,
        address         clientAddress,
        uint64          feedbackIndex,
        string calldata responseURI,
        bytes32         responseHash
    ) external {
        if (feedbackIndex == 0 || feedbackIndex > _lastIndex[agentId][clientAddress])
            revert FeedbackIndexOutOfBounds(feedbackIndex);

        emit ResponseAppended(agentId, clientAddress, feedbackIndex, msg.sender, responseURI, responseHash);
    }

    // ── Views — ERC-8004 Read ─────────────────────────────────────────────────

    function getIdentityRegistry() external view returns (address) {
        return address(identityRegistry);
    }

    /**
     * @notice Retourne la moyenne des feedbacks non révoqués filtrés par tag.
     */
    function getSummary(
        uint256           agentId,
        address[] calldata clientAddresses,
        string    calldata tag1Filter,
        string    calldata tag2Filter
    ) external view returns (uint64 count, int128 summaryValue, uint8 summaryValueDecimals) {
        require(clientAddresses.length > 0, "clientAddresses required");

        bool   filterTag1 = bytes(tag1Filter).length > 0;
        bool   filterTag2 = bytes(tag2Filter).length > 0;
        int256 total      = 0;
        uint64 cnt        = 0;

        for (uint256 i = 0; i < clientAddresses.length; i++) {
            address client = clientAddresses[i];
            uint64  last   = _lastIndex[agentId][client];
            for (uint64 idx = 1; idx <= last; idx++) {
                FeedbackData storage fb = _feedback[agentId][client][idx];
                if (fb.isRevoked) continue;
                if (filterTag1 && keccak256(bytes(fb.tag1)) != keccak256(bytes(tag1Filter))) continue;
                if (filterTag2 && keccak256(bytes(fb.tag2)) != keccak256(bytes(tag2Filter))) continue;
                total += int256(fb.value);
                cnt++;
            }
        }

        count                = cnt;
        summaryValue         = cnt > 0 ? int128(total / int256(uint256(cnt))) : int128(0);
        summaryValueDecimals = 0;
    }

    function readFeedback(
        uint256 agentId,
        address clientAddress,
        uint64  feedbackIndex
    ) external view returns (
        int128 value,
        uint8  valueDecimals,
        string memory tag1,
        string memory tag2,
        bool   isRevoked
    ) {
        FeedbackData storage fb = _feedback[agentId][clientAddress][feedbackIndex];
        return (fb.value, fb.valueDecimals, fb.tag1, fb.tag2, fb.isRevoked);
    }

    function readAllFeedback(
        uint256           agentId,
        address[] calldata clientAddresses,
        string    calldata tag1Filter,
        string    calldata tag2Filter,
        bool               includeRevoked
    ) external view returns (
        address[] memory clients,
        uint64[]  memory feedbackIndexes,
        int128[]  memory values,
        uint8[]   memory valueDecimalsList,
        string[]  memory tag1s,
        string[]  memory tag2s,
        bool[]    memory revokedStatuses
    ) {
        address[] memory searchClients;
        if (clientAddresses.length > 0) {
            searchClients = new address[](clientAddresses.length);
            for (uint256 k = 0; k < clientAddresses.length; k++)
                searchClients[k] = clientAddresses[k];
        } else {
            address[] storage stored = _clients[agentId];
            searchClients = new address[](stored.length);
            for (uint256 k = 0; k < stored.length; k++)
                searchClients[k] = stored[k];
        }

        bool filterTag1 = bytes(tag1Filter).length > 0;
        bool filterTag2 = bytes(tag2Filter).length > 0;

        uint256 total = 0;
        for (uint256 i = 0; i < searchClients.length; i++) {
            address client = searchClients[i];
            uint64  last   = _lastIndex[agentId][client];
            for (uint64 idx = 1; idx <= last; idx++) {
                FeedbackData storage fb = _feedback[agentId][client][idx];
                if (!includeRevoked && fb.isRevoked) continue;
                if (filterTag1 && keccak256(bytes(fb.tag1)) != keccak256(bytes(tag1Filter))) continue;
                if (filterTag2 && keccak256(bytes(fb.tag2)) != keccak256(bytes(tag2Filter))) continue;
                total++;
            }
        }

        clients           = new address[](total);
        feedbackIndexes   = new uint64[](total);
        values            = new int128[](total);
        valueDecimalsList = new uint8[](total);
        tag1s             = new string[](total);
        tag2s             = new string[](total);
        revokedStatuses   = new bool[](total);

        uint256 pos = 0;
        for (uint256 i = 0; i < searchClients.length; i++) {
            address client = searchClients[i];
            uint64  last   = _lastIndex[agentId][client];
            for (uint64 idx = 1; idx <= last; idx++) {
                FeedbackData storage fb = _feedback[agentId][client][idx];
                if (!includeRevoked && fb.isRevoked) continue;
                if (filterTag1 && keccak256(bytes(fb.tag1)) != keccak256(bytes(tag1Filter))) continue;
                if (filterTag2 && keccak256(bytes(fb.tag2)) != keccak256(bytes(tag2Filter))) continue;
                clients[pos]           = client;
                feedbackIndexes[pos]   = idx;
                values[pos]            = fb.value;
                valueDecimalsList[pos] = fb.valueDecimals;
                tag1s[pos]             = fb.tag1;
                tag2s[pos]             = fb.tag2;
                revokedStatuses[pos]   = fb.isRevoked;
                pos++;
            }
        }
    }

    function getClients(uint256 agentId) external view returns (address[] memory) {
        return _clients[agentId];
    }

    function getLastIndex(uint256 agentId, address clientAddress) external view returns (uint64) {
        return _lastIndex[agentId][clientAddress];
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    function _requireRegistry() internal view {
        if (address(identityRegistry) == address(0)) revert RegistryNotInitialized();
    }

    function _store(
        uint256       agentId,
        address       clientAddress,
        int128        value,
        uint8         valueDecimals,
        string memory tag1,
        string memory tag2,
        string memory endpoint,
        string memory feedbackURI,
        bytes32       feedbackHash
    ) internal {
        uint64 newIndex = _lastIndex[agentId][clientAddress] + 1;
        _lastIndex[agentId][clientAddress] = newIndex;

        _feedback[agentId][clientAddress][newIndex] = FeedbackData({
            value:         value,
            valueDecimals: valueDecimals,
            tag1:          tag1,
            tag2:          tag2,
            isRevoked:     false
        });

        if (!_isClient[agentId][clientAddress]) {
            _isClient[agentId][clientAddress] = true;
            _clients[agentId].push(clientAddress);
        }

        emit NewFeedback(
            agentId, clientAddress, newIndex,
            value, valueDecimals,
            tag1, tag1, tag2,
            endpoint, feedbackURI, feedbackHash
        );
    }
}
