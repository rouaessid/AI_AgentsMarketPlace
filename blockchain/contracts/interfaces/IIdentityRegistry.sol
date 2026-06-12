// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

interface IIdentityRegistry {
    // ── Par tokenId (utilisé par ValidationRegistry) ──────────────────────────
    function isActiveByTokenId(uint256 tokenId)        external view returns (bool);
    function agentTokenExists(uint256 tokenId)         external view returns (bool);
    function getAgentWalletByTokenId(uint256 tokenId)  external view returns (address);
    function getAgentTypeByTokenId(uint256 tokenId)    external view returns (uint8);

    // ── Par agentId string (utilisé par ReputationRegistry + EscrowManager) ───
    function agentIdExists(string calldata agentId_)       external view returns (bool);
    function getCurrentTokenId(string calldata agentId_)   external view returns (uint256);
    function isActive(string calldata agentId_)            external view returns (bool);
    function getPricePerTask(string calldata agentId_)     external view returns (uint256);

    // ── ERC-721 (utilisé par ReputationRegistry) ──────────────────────────────
    function ownerOf(uint256 tokenId) external view returns (address);
}
