// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/EIP712.sol";

contract IdentityRegistry is ERC721URIStorage, Ownable, EIP712 {
    using ECDSA for bytes32;

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
    }

    bytes32 private constant _SET_WALLET_TYPEHASH = keccak256(
        "SetAgentWallet(uint256 tokenId,address newWallet,uint256 deadline)"
    );

    uint256 private _nextTokenId = 1;

    mapping(string  => AgentIdentity)                    private _agents;
    mapping(uint256 => string)                           private _tokenToAgentId;
    mapping(uint256 => AgentVersion)                     private _versions;
    mapping(string  => bool)                             private _agentIdExists;
    mapping(uint256 => mapping(string => bytes))         private _metadata;

    string public agentRegistry;

    event AgentCreated(
        string  indexed agentId,
        uint256 indexed tokenId,
        address indexed owner,
        AgentType agentType,
        string  agentURI,
        string  version
    );

    event AgentVersionMinted(
        string  indexed agentId,
        uint256 indexed newTokenId,
        uint256 indexed previousTokenId,
        string  agentURI,
        string  version
    );

    event MetadataSet(
        uint256 indexed tokenId,
        string  indexed indexedKey,
        string  metadataKey,
        bytes   metadataValue
    );

    event AgentStatusChanged(
        string  indexed agentId,
        AgentStatus oldStatus,
        AgentStatus newStatus
    );

    error AgentIdNotFound(string agentId);
    error AgentIdAlreadyExists(string agentId);
    error AgentIdInvalid();
    error TokenNotFound(uint256 tokenId);
    error NotAgentOwner(string agentId, address caller);
    error SoulboundTransferForbidden();
    error ReservedMetadataKey(string key);
    error InvalidSignature();
    error SignatureExpired(uint256 deadline, uint256 blockTimestamp);
    error InvalidWallet();
    error AgentNotActive(string agentId);

    modifier agentExists(string memory agentId) {
        if (!_agentIdExists[agentId]) revert AgentIdNotFound(agentId);
        _;
    }

    modifier onlyAgentOwner(string memory agentId) {
        if (_agents[agentId].owner != msg.sender)
            revert NotAgentOwner(agentId, msg.sender);
        _;
    }

    modifier notReservedKey(string memory key) {
        if (keccak256(bytes(key)) == keccak256(bytes("agentWallet")))
            revert ReservedMetadataKey(key);
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

    constructor()
        ERC721("AgentMarket Identity", "AMID")
        Ownable(msg.sender)
        EIP712("AgentMarket", "1")
    {
        agentRegistry = string(abi.encodePacked(
            "eip155:", _uint2str(block.chainid),
            ":", _addr2str(address(this))
        ));
    }

    // ─── Register ────────────────────────────────────────────────────────────

    function register(
        string    calldata agentId_,
        AgentType agentType_,
        string    calldata agentURI_,
        string    calldata version_
    )
        external
        validAgentId(agentId_)
        returns (uint256 tokenId)
    {
        if (_agentIdExists[agentId_]) revert AgentIdAlreadyExists(agentId_);

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
            tokenHistory:   history
        });

        _agentIdExists[agentId_] = true;
        _tokenToAgentId[tokenId] = agentId_;

        emit MetadataSet(tokenId, "agentWallet", "agentWallet", abi.encode(msg.sender));
        emit AgentCreated(agentId_, tokenId, msg.sender, agentType_, agentURI_, version_);
    }

    // ─── New version ──────────────────────────────────────────────────────────

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

    // ─── SOULBOUND ────────────────────────────────────────────────────────────
    // OZ 5.x : ERC721URIStorage ne surcharge pas _update
    // donc on n'utilise que override sans liste

    function _update(
        address to,
        uint256 tokenId,
        address auth
    ) internal override returns (address) {
        address from = _ownerOf(tokenId);
        if (from != address(0) && to != address(0)) {
            revert SoulboundTransferForbidden();
        }
        return super._update(to, tokenId, auth);
    }

    function approve(address, uint256)
        public pure
        override(ERC721, IERC721)
    {
        revert SoulboundTransferForbidden();
    }

    function setApprovalForAll(address, bool)
        public pure
        override(ERC721, IERC721)
    {
        revert SoulboundTransferForbidden();
    }

    // ─── Metadata ─────────────────────────────────────────────────────────────

    function getMetadata(uint256 tokenId, string memory key)
        external view returns (bytes memory)
    {
        if (!_exists(tokenId)) revert TokenNotFound(tokenId);
        return _metadata[tokenId][key];
    }

    function setMetadata(
        uint256 tokenId,
        string  calldata key,
        bytes   calldata value
    ) external notReservedKey(key) {
        if (!_exists(tokenId)) revert TokenNotFound(tokenId);
        string memory aid = _tokenToAgentId[tokenId];
        if (_agents[aid].owner != msg.sender) revert NotAgentOwner(aid, msg.sender);
        _metadata[tokenId][key] = value;
        emit MetadataSet(tokenId, key, key, value);
    }

    // ─── agentWallet ─────────────────────────────────────────────────────────

    function setAgentWallet(
        string  calldata agentId_,
        address newWallet,
        uint256 deadline,
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
        emit MetadataSet(tokenId, "agentWallet", "agentWallet", abi.encode(newWallet));
    }

    // ─── Status ──────────────────────────────────────────────────────────────

    function setAgentStatus(string calldata agentId_, AgentStatus newStatus)
        external onlyOwner agentExists(agentId_)
    {
        AgentStatus old = _agents[agentId_].status;
        _agents[agentId_].status = newStatus;
        emit AgentStatusChanged(agentId_, old, newStatus);
    }

    // ─── Views ───────────────────────────────────────────────────────────────

    function getAgent(string calldata agentId_)
        external view agentExists(agentId_)
        returns (AgentIdentity memory)
    {
        return _agents[agentId_];
    }

    function getVersion(uint256 tokenId)
        external view returns (AgentVersion memory)
    {
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

    function getAgentIdByToken(uint256 tokenId)
        external view returns (string memory)
    {
        if (!_exists(tokenId)) revert TokenNotFound(tokenId);
        return _tokenToAgentId[tokenId];
    }

    function getAgentWallet(string calldata agentId_)
        external view agentExists(agentId_)
        returns (address)
    {
        return _agents[agentId_].agentWallet;
    }

    function isActive(string calldata agentId_) external view returns (bool) {
        return _agentIdExists[agentId_] &&
               _agents[agentId_].status == AgentStatus.ACTIVE;
    }

    function agentIdExists(string calldata agentId_) external view returns (bool) {
        return _agentIdExists[agentId_];
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

    // ─── ERC-165 ─────────────────────────────────────────────────────────────
    // OZ 5.x : ERC721URIStorage surcharge supportsInterface
    // donc on liste uniquement ERC721URIStorage

    function supportsInterface(bytes4 interfaceId)
        public view override(ERC721URIStorage)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }

    // ─── Internals ───────────────────────────────────────────────────────────

    function _exists(uint256 tokenId) internal view returns (bool) {
        return _ownerOf(tokenId) != address(0);
    }

    function _uint2str(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        uint256 tmp = v; uint256 d;
        while (tmp != 0) { d++; tmp /= 10; }
        bytes memory buf = new bytes(d);
        while (v != 0) { d--; buf[d] = bytes1(uint8(48 + v % 10)); v /= 10; }
        return string(buf);
    }

    function _addr2str(address a) internal pure returns (string memory) {
        bytes memory b    = new bytes(42);
        bytes memory hex_ = "0123456789abcdef";
        b[0] = "0"; b[1] = "x";
        for (uint256 i = 0; i < 20; i++) {
            b[2 + i*2]     = hex_[uint8(bytes20(a)[i]) >> 4];
            b[2 + i*2 + 1] = hex_[uint8(bytes20(a)[i]) & 0xf];
        }
        return string(b);
    }
}