// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

// ════════════════════════════════════════════════════════════════════════════
//  ReputationRegistry  —  AgentMarket · ERC-8004 Reputation Registry
// ════════════════════════════════════════════════════════════════════════════
//
//  Alignement ERC-8004 §Reputation Registry
//  ─────────────────────────────────────────────────────────────────────────
//  Interface publique conforme au spec :
//    giveFeedback(agentId, value, valueDecimals, tag1, tag2, endpoint, feedbackURI, feedbackHash)
//    revokeFeedback(agentId, feedbackIndex)
//    appendResponse(agentId, clientAddress, feedbackIndex, responseURI, responseHash)
//    getSummary(agentId, clientAddresses[], tag1, tag2) → (count, summaryValue, summaryValueDecimals)
//    readFeedback(agentId, clientAddress, feedbackIndex) → (value, valueDecimals, tag1, tag2, isRevoked)
//    readAllFeedback(agentId, clientAddresses[], tag1, tag2, includeRevoked)
//    getClients(agentId) → address[]
//    getLastIndex(agentId, clientAddress) → uint64
//    initialize(identityRegistry_)
//    getIdentityRegistry() → address
//
//  Adapter interne (compatibilité ValidationRegistry) :
//    recordReputation(agentId string, delta, isIncrease, reason)
//      → mappe vers giveFeedback() avec tag1="successRate", tag2=reason
//      → seuls les callers autorisés peuvent appeler (setAuthorizedCaller)
//
//  agentId ERC-8004 = tokenId uint256 de l'IdentityRegistry (ERC-721)
//  String agentId → tokenId via IIdentityRegistry.getCurrentTokenId()
//
//  Tags utilisés dans notre marketplace :
//  ┌─────────────────┬──────────────────────────────────────────────────────┐
//  │ tag1            │ Source / Sens                                        │
//  ├─────────────────┼──────────────────────────────────────────────────────┤
//  │ successRate     │ ValidationRegistry → provider/judge (score 0-100)   │
//  │ starred         │ User → agent (note 1-5, converti en 20-100)         │
//  │ reachable       │ Platform monitor → endpoint health (0 ou 1)         │
//  │ uptime          │ Platform monitor → uptime % (valueDecimals=2)       │
//  │ eigenTrust      │ Platform → score EigenTrust calculé off-chain       │
//  └─────────────────┴──────────────────────────────────────────────────────┘
//
//  Contrats siblings :
//  ┌──────────────────────────────────────────────────────────────────────┐
//  │ IdentityRegistry   → isActive · agentIdExists · getCurrentTokenId   │
//  │                      getAgentWallet · ownerOf (ERC-721)             │
//  ├──────────────────────────────────────────────────────────────────────┤
//  │ ValidationRegistry → appelle recordReputation() après finalisation  │
//  └──────────────────────────────────────────────────────────────────────┘

import "@openzeppelin/contracts/access/Ownable.sol";

// ── Interfaces ────────────────────────────────────────────────────────────────

interface IIdentityRegistry {
    function agentIdExists(string calldata agentId_) external view returns (bool);
    function getCurrentTokenId(string calldata agentId_) external view returns (uint256);
    function ownerOf(uint256 tokenId) external view returns (address);
}

// ── Contract ──────────────────────────────────────────────────────────────────

contract ReputationRegistry is Ownable {

    // ── State ─────────────────────────────────────────────────────────────────

    IIdentityRegistry public identityRegistry;

    // Callers autorisés à appeler recordReputation() (ex: ValidationRegistry)
    mapping(address => bool) public authorizedCallers;

    struct FeedbackData {
        int128 value;
        uint8  valueDecimals;
        string tag1;
        string tag2;
        bool   isRevoked;
    }

    // agentId (tokenId) → clientAddress → feedbackIndex (1-based) → data
    mapping(uint256 => mapping(address => mapping(uint64 => FeedbackData))) private _feedback;

    // agentId → clientAddress → dernier index (= nombre total de feedbacks donnés)
    mapping(uint256 => mapping(address => uint64)) private _lastIndex;

    // agentId → liste des clientAddresses uniques
    mapping(uint256 => address[])          private _clients;
    mapping(uint256 => mapping(address => bool)) private _isClient;

    // ── Events ERC-8004 ───────────────────────────────────────────────────────

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

    // ── Initialization ────────────────────────────────────────────────────────

    /// @notice Appelé par setup_complete.js après déploiement.
    function initialize(address identityRegistry_) external onlyOwner {
        identityRegistry = IIdentityRegistry(identityRegistry_);
    }

    /// @notice ERC-8004: retourne l'adresse de l'IdentityRegistry lié.
    function getIdentityRegistry() external view returns (address) {
        return address(identityRegistry);
    }

    // ── Gestion des callers autorisés ─────────────────────────────────────────

    /// @notice Autorise ou révoque un contrat à appeler recordReputation().
    function setAuthorizedCaller(address caller, bool authorized) external onlyOwner {
        authorizedCallers[caller] = authorized;
    }

    // ── ERC-8004: giveFeedback ────────────────────────────────────────────────

    /// @notice Donne un feedback public sur un agent.
    /// @dev Le propriétaire du token NE PEUT PAS noter son propre agent (spec ERC-8004).
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

        // Vérifie que le token existe et que le caller n'est pas le owner
        try identityRegistry.ownerOf(agentId) returns (address tokenOwner) {
            if (tokenOwner == msg.sender) revert AgentOwnerCannotRate(agentId);
        } catch {
            revert AgentNotFound(agentId);
        }

        _store(agentId, msg.sender, value, valueDecimals, tag1, tag2, endpoint, feedbackURI, feedbackHash);
    }

    // ── Adapter interne: appelé par ValidationRegistry ────────────────────────

    /// @notice Adapter pour ValidationRegistry.
    ///         Mappe (agentId string, delta, isIncrease, reason) → giveFeedback interne.
    ///         tag1 = "successRate", tag2 = reason ("VALID","INVALID","CONSENSUS","DEVIATED","ABSENT")
    ///         clientAddress = msg.sender (= adresse de ValidationRegistry)
    function recordReputation(
        string calldata agentId,
        uint256         delta,
        bool            isIncrease,
        string calldata reason
    ) external {
        if (!authorizedCallers[msg.sender]) revert UnauthorizedCaller(msg.sender);
        _requireRegistry();
        if (!identityRegistry.agentIdExists(agentId)) revert AgentIdNotFound(agentId);

        uint256 tokenId = identityRegistry.getCurrentTokenId(agentId);
        int128  value   = isIncrease
            ? int128(int256(delta))
            : -int128(int256(delta));

        _store(tokenId, msg.sender, value, 0, "successRate", reason, "", "", bytes32(0));
    }

    // ── ERC-8004: revokeFeedback ──────────────────────────────────────────────

    function revokeFeedback(uint256 agentId, uint64 feedbackIndex) external {
        uint64 last = _lastIndex[agentId][msg.sender];
        if (feedbackIndex == 0 || feedbackIndex > last)
            revert FeedbackIndexOutOfBounds(feedbackIndex);

        _feedback[agentId][msg.sender][feedbackIndex].isRevoked = true;
        emit FeedbackRevoked(agentId, msg.sender, feedbackIndex);
    }

    // ── ERC-8004: appendResponse ──────────────────────────────────────────────

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

    // ── ERC-8004: getSummary ──────────────────────────────────────────────────

    /// @notice Retourne la moyenne des feedbacks non révoqués filtrés par tag.
    /// @dev clientAddresses DOIT être non vide (spec ERC-8004 — anti-Sybil).
    function getSummary(
        uint256           agentId,
        address[] calldata clientAddresses,
        string    calldata tag1Filter,
        string    calldata tag2Filter
    ) external view returns (uint64 count, int128 summaryValue, uint8 summaryValueDecimals) {
        require(clientAddresses.length > 0, "clientAddresses required");

        bool filterTag1 = bytes(tag1Filter).length > 0;
        bool filterTag2 = bytes(tag2Filter).length > 0;

        int256 total = 0;
        uint64 cnt   = 0;

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

    // ── ERC-8004: readFeedback ────────────────────────────────────────────────

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

    // ── ERC-8004: readAllFeedback ─────────────────────────────────────────────

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
        // Solidity ne permet pas de mélanger calldata et storage dans un ternaire.
        // On copie _clients[agentId] en mémoire si aucun filtre de clients fourni.
        address[] memory searchClients;
        if (clientAddresses.length > 0) {
            searchClients = new address[](clientAddresses.length);
            for (uint256 k = 0; k < clientAddresses.length; k++) {
                searchClients[k] = clientAddresses[k];
            }
        } else {
            address[] storage stored = _clients[agentId];
            searchClients = new address[](stored.length);
            for (uint256 k = 0; k < stored.length; k++) {
                searchClients[k] = stored[k];
            }
        }

        bool filterTag1 = bytes(tag1Filter).length > 0;
        bool filterTag2 = bytes(tag2Filter).length > 0;

        // Premier passage : compter
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

        // Allouer
        clients           = new address[](total);
        feedbackIndexes   = new uint64[](total);
        values            = new int128[](total);
        valueDecimalsList = new uint8[](total);
        tag1s             = new string[](total);
        tag2s             = new string[](total);
        revokedStatuses   = new bool[](total);

        // Deuxième passage : remplir
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

    // ── ERC-8004: getClients ──────────────────────────────────────────────────

    function getClients(uint256 agentId) external view returns (address[] memory) {
        return _clients[agentId];
    }

    // ── ERC-8004: getLastIndex ────────────────────────────────────────────────

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
            agentId,
            clientAddress,
            newIndex,
            value,
            valueDecimals,
            tag1,       // indexed
            tag1,
            tag2,
            endpoint,
            feedbackURI,
            feedbackHash
        );
    }
}
