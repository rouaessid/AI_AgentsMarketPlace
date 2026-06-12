// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/EIP712.sol";

// ════════════════════════════════════════════════════════════════════════════
//  IdentityRegistry — AgentMarket
//  Registre ERC-721 soulbound des agents (providers et judges).
//  Chaque agent est identifié par un agentId string et un tokenId NFT.
//  Transferts désactivés (soulbound). Versions gérées via mintNewVersion().
// ════════════════════════════════════════════════════════════════════════════

contract IdentityRegistry is ERC721URIStorage, Ownable, EIP712 {
    using ECDSA for bytes32;

    // ── Type Declarations ─────────────────────────────────────────────────────

    enum AgentType   { PROVIDER, JUDGE }
    enum AgentStatus { ACTIVE, SUSPENDED, REVOKED }

    struct AgentVersion {
        uint256 tokenId;
        string  agentURI;
        string  version;
        uint256 mintedAt;
        bool    isCurrent;
    }

    struct AgentIdentity {
        string      agentId;
        AgentType   agentType;
        AgentStatus status;
        address     owner;
        address     agentWallet;
        uint256     createdAt;
        uint256     currentTokenId;
        uint256[]   tokenHistory;
        uint256     pricePerTask;  // en wei — vérifié par EscrowManager
    }

    // ── Constants ─────────────────────────────────────────────────────────────

    bytes32 private constant _SET_WALLET_TYPEHASH = keccak256(
        "SetAgentWallet(uint256 tokenId,address newWallet,uint256 deadline)"
    );

    // ── State Variables ───────────────────────────────────────────────────────

    uint256 private _nextTokenId = 1;

    // agentId string → identité complète
    mapping(string  => AgentIdentity)                    private _agents;
    // tokenId → agentId string
    mapping(uint256 => string)                           private _tokenToAgentId;
    // tokenId → version metadata
    mapping(uint256 => AgentVersion)                     private _versions;

    // ── Events ────────────────────────────────────────────────────────────────

    event AgentCreated(
        string  agentId,
        uint256 indexed tokenId,
        address indexed owner,
        AgentType agentType,
        string  agentURI,
        string  version
    );

    event AgentVersionMinted(
        string  agentId,
        uint256 indexed newTokenId,
        uint256 indexed previousTokenId,
        string  agentURI,
        string  version
    );

    event AgentStatusChanged(
        string  indexed agentId,
        AgentStatus oldStatus,
        AgentStatus newStatus
    );

    // ── Errors ────────────────────────────────────────────────────────────────

    error AgentIdNotFound(string agentId);
    error AgentIdAlreadyExists(string agentId);
    error AgentIdInvalid();
    error TokenNotFound(uint256 tokenId);
    error NotAgentOwner(string agentId, address caller);
    error SoulboundTransferForbidden();
    error InvalidSignature();
    error SignatureExpired(uint256 deadline, uint256 blockTimestamp);
    error InvalidWallet();
    error AgentNotActive(string agentId);

    // ── Modifiers ─────────────────────────────────────────────────────────────

    modifier agentExists(string memory agentId) {
        if (bytes(_agents[agentId].agentId).length == 0) revert AgentIdNotFound(agentId);
        _;
    }

    modifier onlyAgentOwner(string memory agentId) {
        if (_agents[agentId].owner != msg.sender)
            revert NotAgentOwner(agentId, msg.sender);
        _;
    }

    modifier validAgentId(string memory agentId) {
        bytes memory b = bytes(agentId);
        if (b.length == 0 || b.length > 64) revert AgentIdInvalid();
        for (uint256 i = 0; i < b.length; i++) {
            bytes1 c = b[i];
            bool ok = (c >= 0x61 && c <= 0x7A) ||
                      (c >= 0x41 && c <= 0x5A) ||
                      (c >= 0x30 && c <= 0x39) ||
                      c == 0x2D || c == 0x5F;
            if (!ok) revert AgentIdInvalid();
        }
        _;
    }

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor()
        ERC721("AgentMarket Identity", "AMID")
        Ownable(msg.sender)
        EIP712("AgentMarket", "1")
    {}

    // ── External — Registration ───────────────────────────────────────────────

    /**
     * @notice Enregistre un nouvel agent et mint son NFT soulbound.
     * @param agentId_      Identifiant unique (alphanumérique, max 64 chars)
     * @param agentType_    PROVIDER ou JUDGE
     * @param agentURI_     URI IPFS du manifest (ipfs://Qm...)
     * @param version_      Version sémantique (ex: "1.0.0")
     * @param pricePerTask_ Prix par tâche en wei
     */
    function register(
        string    calldata agentId_,
        AgentType agentType_,
        string    calldata agentURI_,
        string    calldata version_,
        uint256   pricePerTask_
    )
        external
        validAgentId(agentId_)
        returns (uint256 tokenId)
    {
        if (bytes(_agents[agentId_].agentId).length > 0) revert AgentIdAlreadyExists(agentId_);

        tokenId = _nextTokenId++;
        _safeMint(msg.sender, tokenId);
        _setTokenURI(tokenId, agentURI_);

        _versions[tokenId] = AgentVersion({
            tokenId:   tokenId,
            agentURI:  agentURI_,
            version:   version_,
            mintedAt:  block.timestamp,
            isCurrent: true
        });

        uint256[] memory history = new uint256[](1);
        history[0] = tokenId;

        _agents[agentId_] = AgentIdentity({
            agentId:        agentId_,
            agentType:      agentType_,
            status:         AgentStatus.ACTIVE,
            owner:          msg.sender,
            agentWallet:    msg.sender,
            createdAt:      block.timestamp,
            currentTokenId: tokenId,
            tokenHistory:   history,
            pricePerTask:   pricePerTask_
        });

        _tokenToAgentId[tokenId]  = agentId_;

        emit AgentCreated(agentId_, tokenId, msg.sender, agentType_, agentURI_, version_);
    }

    // ── External — Versioning ─────────────────────────────────────────────────

    /**
     * @notice Mint une nouvelle version du token (nouvelle URI IPFS).
     * @dev L'ancien token reste mais isCurrent passe à false.
     */
    function mintNewVersion(
        string calldata agentId_,
        string calldata newURI_,
        string calldata newVersion_
    )
        external
        agentExists(agentId_)
        onlyAgentOwner(agentId_)
        returns (uint256 newTokenId)
    {
        if (_agents[agentId_].status != AgentStatus.ACTIVE)
            revert AgentNotActive(agentId_);

        uint256 prevTokenId = _agents[agentId_].currentTokenId;
        _versions[prevTokenId].isCurrent = false;

        newTokenId = _nextTokenId++;
        _safeMint(msg.sender, newTokenId);
        _setTokenURI(newTokenId, newURI_);

        _versions[newTokenId] = AgentVersion({
            tokenId:   newTokenId,
            agentURI:  newURI_,
            version:   newVersion_,
            mintedAt:  block.timestamp,
            isCurrent: true
        });

        _agents[agentId_].currentTokenId = newTokenId;
        _agents[agentId_].tokenHistory.push(newTokenId);
        _tokenToAgentId[newTokenId] = agentId_;

        emit AgentVersionMinted(agentId_, newTokenId, prevTokenId, newURI_, newVersion_);
    }

    // ── External — Admin ──────────────────────────────────────────────────────

    function setAgentStatus(string calldata agentId_, AgentStatus newStatus)
        external onlyOwner agentExists(agentId_)
    {
        AgentStatus old = _agents[agentId_].status;
        _agents[agentId_].status = newStatus;
        emit AgentStatusChanged(agentId_, old, newStatus);
    }

    /**
     * @notice Change le wallet opérationnel d'un agent (signature EIP-712 requise).
     */
    function setAgentWallet(
        string  calldata agentId_,
        address          newWallet,
        uint256          deadline,
        bytes   calldata signature
    ) external agentExists(agentId_) onlyAgentOwner(agentId_) {
        if (newWallet == address(0)) revert InvalidWallet();
        if (block.timestamp > deadline) revert SignatureExpired(deadline, block.timestamp);

        uint256 tokenId = _agents[agentId_].currentTokenId;
        bytes32 digest  = _hashTypedDataV4(keccak256(abi.encode(
            _SET_WALLET_TYPEHASH, tokenId, newWallet, deadline
        )));
        if (ECDSA.recover(digest, signature) != newWallet) revert InvalidSignature();

        _agents[agentId_].agentWallet = newWallet;
    }

    function setPricePerTask(string calldata agentId_, uint256 newPrice_)
        external agentExists(agentId_) onlyAgentOwner(agentId_)
    {
        _agents[agentId_].pricePerTask = newPrice_;
    }

    // ── Views ─────────────────────────────────────────────────────────────────

    function getAgent(string calldata agentId_)
        external view agentExists(agentId_)
        returns (AgentIdentity memory)
    {
        return _agents[agentId_];
    }

    function getAgentType(string calldata agentId_)
        external view agentExists(agentId_)
        returns (uint8)
    {
        return uint8(_agents[agentId_].agentType);
    }

    function getVersion(uint256 tokenId) external view returns (AgentVersion memory) {
        if (!_exists(tokenId)) revert TokenNotFound(tokenId);
        return _versions[tokenId];
    }

    function getCurrentTokenId(string calldata agentId_)
        external view agentExists(agentId_)
        returns (uint256)
    {
        return _agents[agentId_].currentTokenId;
    }

    function getTokenHistory(string calldata agentId_)
        external view agentExists(agentId_)
        returns (uint256[] memory)
    {
        return _agents[agentId_].tokenHistory;
    }

    function getAgentIdByToken(uint256 tokenId) external view returns (string memory) {
        if (!_exists(tokenId)) revert TokenNotFound(tokenId);
        return _tokenToAgentId[tokenId];
    }

    function agentTokenExists(uint256 tokenId_) external view returns (bool) {
        return _exists(tokenId_);
    }

    function isActiveByTokenId(uint256 tokenId_) external view returns (bool) {
        if (!_exists(tokenId_)) return false;
        return _agents[_tokenToAgentId[tokenId_]].status == AgentStatus.ACTIVE;
    }

    function getAgentWalletByTokenId(uint256 tokenId_) external view returns (address) {
        if (!_exists(tokenId_)) revert TokenNotFound(tokenId_);
        return _agents[_tokenToAgentId[tokenId_]].agentWallet;
    }

    function getAgentTypeByTokenId(uint256 tokenId_) external view returns (uint8) {
        if (!_exists(tokenId_)) revert TokenNotFound(tokenId_);
        return uint8(_agents[_tokenToAgentId[tokenId_]].agentType);
    }

    function getAgentWallet(string calldata agentId_)
        external view agentExists(agentId_)
        returns (address)
    {
        return _agents[agentId_].agentWallet;
    }

    function getPricePerTask(string calldata agentId_)
        external view agentExists(agentId_)
        returns (uint256)
    {
        return _agents[agentId_].pricePerTask;
    }

    function isActive(string calldata agentId_) external view returns (bool) {
        return bytes(_agents[agentId_].agentId).length > 0 &&
               _agents[agentId_].status == AgentStatus.ACTIVE;
    }

    function agentIdExists(string calldata agentId_) external view returns (bool) {
        return bytes(_agents[agentId_].agentId).length > 0;
    }

    function totalTokensMinted() external view returns (uint256) {
        return _nextTokenId - 1;
    }

    function agentURI(string calldata agentId_)
        external view agentExists(agentId_)
        returns (string memory)
    {
        return tokenURI(_agents[agentId_].currentTokenId);
    }

    // ── Soulbound — ERC-721 overrides ─────────────────────────────────────────

    function _update(address to, uint256 tokenId, address auth)
        internal override returns (address)
    {
        address from = _ownerOf(tokenId);
        if (from != address(0) && to != address(0))
            revert SoulboundTransferForbidden();
        return super._update(to, tokenId, auth);
    }

    function approve(address, uint256) public pure override(ERC721, IERC721) {
        revert SoulboundTransferForbidden();
    }

    function setApprovalForAll(address, bool) public pure override(ERC721, IERC721) {
        revert SoulboundTransferForbidden();
    }

    function supportsInterface(bytes4 interfaceId)
        public view override(ERC721URIStorage)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }

    // ── Internal Helpers ──────────────────────────────────────────────────────

    function _exists(uint256 tokenId) internal view returns (bool) {
        return _ownerOf(tokenId) != address(0);
    }

    function _uint2str(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        uint256 j = v;
        uint256 len;
        while (j != 0) { len++; j /= 10; }
        bytes memory bstr = new bytes(len);
        uint256 k = len;
        while (v != 0) { k--; bstr[k] = bytes1(uint8(48 + v % 10)); v /= 10; }
        return string(bstr);
    }

    function _addr2str(address a) internal pure returns (string memory) {
        bytes memory b = abi.encodePacked(a);
        bytes memory hex_ = "0123456789abcdef";
        bytes memory str = new bytes(42);
        str[0] = "0"; str[1] = "x";
        for (uint256 i = 0; i < 20; i++) {
            str[2 + i * 2]     = hex_[uint8(b[i]) >> 4];
            str[3 + i * 2]     = hex_[uint8(b[i]) & 0x0f];
        }
        return string(str);
    }
}
