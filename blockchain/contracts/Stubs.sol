// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

// ════════════════════════════════════════════════════════════════════════════
//  Stubs.sol — TEST ONLY
//  Ces stubs sont exclusivement utilisés dans les tests unitaires Hardhat.
//  En production, utiliser les vrais contrats :
//    ReputationRegistry → ReputationRegistry.sol (ERC-8004)
//    IdentityRegistry   → IdentityRegistry.sol
// ════════════════════════════════════════════════════════════════════════════

contract IdentityRegistryStub {
    struct Agent {
        bool exists;
        bool isActive;
        uint8 agentType;
        address wallet;
        uint256 tokenId;
    }

    mapping(string  => Agent)   public agents;
    mapping(uint256 => address) private _tokenOwner;   // tokenId → owner (pour ownerOf)
    mapping(uint256 => string)  private _tokenToAgentId; // tokenId → agentId

    function registerAgent(
        string calldata agentId,
        uint8 agentType_,
        address wallet_,
        uint256 tokenId_
    ) external {
        agents[agentId] = Agent({
            exists: true,
            isActive: true,
            agentType: agentType_,
            wallet: wallet_,
            tokenId: tokenId_
        });
        _tokenOwner[tokenId_]    = wallet_;
        _tokenToAgentId[tokenId_] = agentId;
    }

    /// @notice ERC-721 ownerOf — nécessaire pour ReputationRegistry.giveFeedback
    function ownerOf(uint256 tokenId) external view returns (address) {
        address owner = _tokenOwner[tokenId];
        require(owner != address(0), "IdentityRegistryStub: token does not exist");
        return owner;
    }

    function setActive(string calldata agentId, bool status) external {
        agents[agentId].isActive = status;
    }

    // ── Par agentId string ────────────────────────────────────────────────────

    function isActive(string calldata agentId) external view returns (bool) {
        return agents[agentId].isActive;
    }

    function agentIdExists(string calldata agentId) external view returns (bool) {
        return agents[agentId].exists;
    }

    function getAgentWallet(string calldata agentId) external view returns (address) {
        return agents[agentId].wallet;
    }

    function getAgentType(string calldata agentId) external view returns (uint8) {
        return agents[agentId].agentType;
    }

    function getCurrentTokenId(string calldata agentId) external view returns (uint256) {
        return agents[agentId].tokenId;
    }

    function getPricePerTask(string calldata /*agentId*/) external pure returns (uint256) {
        return 0;
    }

    // ── Par tokenId (interface utilisée par ValidationRegistry) ──────────────

    function isActiveByTokenId(uint256 tokenId) external view returns (bool) {
        return agents[_tokenToAgentId[tokenId]].isActive;
    }

    function agentTokenExists(uint256 tokenId) external view returns (bool) {
        return agents[_tokenToAgentId[tokenId]].exists;
    }

    function getAgentWalletByTokenId(uint256 tokenId) external view returns (address) {
        return agents[_tokenToAgentId[tokenId]].wallet;
    }

    function getAgentTypeByTokenId(uint256 tokenId) external view returns (uint8) {
        return agents[_tokenToAgentId[tokenId]].agentType;
    }
}

contract StakingContractStub {
    address public validationRegistry;
    mapping(address => bool) private _notEligibleProvider;
    mapping(address => bool) private _notEligibleJudge;
    
    mapping(address => uint256) public lockCount;
    mapping(address => uint256) public unlockCount;
    mapping(address => uint256) public slashCount;

    function setValidationRegistry(address registry) external {
        validationRegistry = registry;
    }

    function setEligibleProvider(address wallet, bool status) external {
        _notEligibleProvider[wallet] = !status;
    }

    function setEligibleJudge(address wallet, bool status) external {
        _notEligibleJudge[wallet] = !status;
    }

    function isEligibleProvider(address agent) external view returns (bool) {
        return !_notEligibleProvider[agent];
    }

    function isEligibleJudge(address agent) external view returns (bool) {
        return !_notEligibleJudge[agent];
    }

    function isLocked(address /*agent*/) external pure returns (bool) {
        return false;
    }

    function lockStake(address agent, uint256 /*duration*/) external {
        lockCount[agent]++;
    }

    function unlockStake(address agent) external {
        unlockCount[agent]++;
    }

    function slashProvider(address agent) external returns (uint256) {
        slashCount[agent]++;
        return 100; // returning some positive amount
    }

    function slashJudge(address agent) external returns (uint256) {
        slashCount[agent]++;
        return 50; // returning some positive amount
    }
}

contract ReputationRegistryStub {
    struct RepCall {
        uint256 delta;
        bool isIncrease;
        string reason;
    }

    mapping(string => RepCall[]) private _calls;

    function recordReputation(
        string calldata agentId,
        uint256 delta,
        bool isIncrease,
        string calldata reason
    ) external {
        _calls[agentId].push(RepCall(delta, isIncrease, reason));
    }

    function getScore(string calldata /*agentId*/) external pure returns (uint256) {
        return 100;
    }

    function getCalls(string calldata agentId) external view returns (RepCall[] memory) {
        return _calls[agentId];
    }
}

contract EscrowManagerStub {
    uint256 public releaseCount;
    uint256 public refundCount;
    string public lastTaskId;

    function releaseFunds(string calldata taskId, address /*provider*/, address[] calldata /*judges*/) external {
        releaseCount++;
        lastTaskId = taskId;
    }

    function releaseFundsPipeline(string calldata taskId, address[] calldata /*judges*/) external {
        releaseCount++;
        lastTaskId = taskId;
    }

    function refundClient(string calldata taskId) external {
        refundCount++;
        lastTaskId = taskId;
    }
}
