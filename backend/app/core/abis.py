"""
abis.py — ABIs minimaux des contrats AgentMarket.

Un seul endroit pour toutes les définitions d'interface on-chain.
Chaque contrat expose uniquement les fonctions utilisées par le backend.
"""

# ── IdentityRegistry ──────────────────────────────────────────────────────────

IDENTITY_REGISTRY_ABI = [
    {
        "inputs": [{"type": "string", "name": "agentId_"}],
        "name": "isActive",
        "outputs": [{"type": "bool"}],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": "agentId_"}],
        "name": "getPricePerTask",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": "agentId_"}],
        "name": "getAgentWallet",
        "outputs": [{"type": "address"}],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [
            {"type": "string",  "name": "agentId_"},
            {"type": "uint8",   "name": "agentType_"},
            {"type": "string",  "name": "agentURI_"},
            {"type": "string",  "name": "version_"},
            {"type": "uint256", "name": "pricePerTask_"},
        ],
        "name": "register",
        "outputs": [{"type": "uint256", "name": "tokenId"}],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [
            {"type": "string", "name": "agentId_"},
            {"type": "string", "name": "newURI_"},
            {"type": "string", "name": "newVersion_"},
        ],
        "name": "mintNewVersion",
        "outputs": [{"type": "uint256", "name": "newTokenId"}],
        "stateMutability": "nonpayable", "type": "function",
    },
]


# ── EscrowManager ─────────────────────────────────────────────────────────────

ESCROW_MANAGER_ABI = [
    {
        "inputs": [
            {"type": "string", "name": "taskId_"},
            {"type": "string", "name": "agentId_"},
        ],
        "name": "depositPayment",
        "outputs": [],
        "stateMutability": "payable", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": ""}],
        "name": "taskFunds",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": ""}],
        "name": "taskClients",
        "outputs": [{"type": "address"}],
        "stateMutability": "view", "type": "function",
    },
]


# ── StakingContract ───────────────────────────────────────────────────────────

STAKING_CONTRACT_ABI = [
    {
        "inputs": [{"type": "address", "name": ""}],
        "name": "stakes",
        "outputs": [
            {"type": "uint256", "name": "amount"},
            {"type": "bool",    "name": "isActive"},
        ],
        "stateMutability": "view", "type": "function",
    },
]


# ── ValidationRegistry ────────────────────────────────────────────────────────

VALIDATION_REGISTRY_ABI = [
    {
        "inputs": [
            {"type": "string",  "name": "taskId_"},
            {"type": "string",  "name": "providerAgentId_"},
            {"type": "string",  "name": "requestURI_"},
            {"type": "bytes32", "name": "requestHash_"},
            {"type": "bytes32", "name": "traceHash_"},
            {"type": "uint8",   "name": "mode_"},
        ],
        "name": "validationRequest", "outputs": [],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [
            {"type": "string",   "name": "taskId_"},
            {"type": "string[]", "name": "candidates_"},
        ],
        "name": "assignJudges", "outputs": [],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [
            {"type": "string",  "name": "taskId_"},
            {"type": "string",  "name": "judgeId_"},
            {"type": "bytes32", "name": "commitHash_"},
        ],
        "name": "commitVote", "outputs": [],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [
            {"type": "string",  "name": "taskId_"},
            {"type": "string",  "name": "judgeId_"},
            {"type": "uint8",   "name": "vote_"},
            {"type": "bytes32", "name": "salt_"},
            {"type": "uint8",   "name": "taskCompletion_"},
            {"type": "uint8",   "name": "outputQuality_"},
            {"type": "uint8",   "name": "noFabrication_"},
            {"type": "uint8",   "name": "toolUsage_"},
        ],
        "name": "revealVote", "outputs": [],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [
            {"type": "string", "name": "taskId_"},
            {"type": "string", "name": "justificationURI_"},
        ],
        "name": "finaliseValidation", "outputs": [],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": "taskId_"}],
        "name": "getTraceHash",
        "outputs": [{"type": "bytes32"}],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": "agentId_"}],
        "name": "getAgentScore",
        "outputs": [
            {"type": "uint256", "name": "averageScore"},
            {"type": "uint256", "name": "totalTasks"},
        ],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": "agentId_"}],
        "name": "getAgentModeScores",
        "outputs": [
            {"type": "uint256", "name": "soloTotal"},
            {"type": "uint256", "name": "soloCount"},
            {"type": "uint256", "name": "pipelineTotal"},
            {"type": "uint256", "name": "pipelineCount"},
        ],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [{"type": "address", "name": "judgeWallet_"}],
        "name": "getJudgeAgreementRate",
        "outputs": [
            {"type": "uint256", "name": "rate"},
            {"type": "uint256", "name": "totalVotes"},
        ],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": "taskId_"}],
        "name": "getResponseURI",
        "outputs": [{"type": "string"}],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": "taskId_"}],
        "name": "expireTask", "outputs": [],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": "judgeId_"}],
        "name": "isJudgeAuthorized",
        "outputs": [{"type": "bool"}],
        "stateMutability": "view", "type": "function",
    },
    {
        "inputs": [
            {"type": "string", "name": "judgeId_"},
            {"type": "bool",   "name": "passed_"},
            {"type": "string", "name": "resultCID_"},
        ],
        "name": "recordHoneypotResult", "outputs": [],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [{"type": "string", "name": "taskId_"}],
        "name": "getTask",
        "outputs": [{"type": "tuple", "components": [
            {"type": "string",    "name": "taskId"},
            {"type": "string",    "name": "providerAgentId"},
            {"type": "address",   "name": "providerWallet"},
            {"type": "bytes32",   "name": "requestHash"},
            {"type": "bytes32",   "name": "traceHash"},
            {"type": "uint256",   "name": "erc8004AgentId"},
            {"type": "uint8",     "name": "status"},
            {"type": "uint256",   "name": "createdAt"},
            {"type": "uint256",   "name": "commitDeadline"},
            {"type": "uint256",   "name": "revealDeadline"},
            {"type": "string[3]", "name": "judgeIds"},
            {"type": "address[3]","name": "judgeWallets"},
            {"type": "uint8",     "name": "finalResponse"},
            {"type": "string",    "name": "finalTag"},
            {"type": "uint256",   "name": "score"},
            {"type": "uint8",     "name": "mode"},
        ]}],
        "stateMutability": "view", "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "taskId",        "type": "string"},
            {"indexed": False, "name": "judge0",         "type": "string"},
            {"indexed": False, "name": "judge1",         "type": "string"},
            {"indexed": False, "name": "judge2",         "type": "string"},
            {"indexed": False, "name": "commitDeadline", "type": "uint256"},
            {"indexed": False, "name": "revealDeadline", "type": "uint256"},
        ],
        "name": "JudgesAssigned", "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "name": "agentId", "type": "string"},
            {"indexed": False, "name": "taskId",  "type": "string"},
            {"indexed": False, "name": "score",   "type": "uint8"},
            {"indexed": False, "name": "mode",    "type": "uint8"},
        ],
        "name": "ScoreRecorded", "type": "event",
    },
]


# ── ReputationRegistry ────────────────────────────────────────────────────────

REPUTATION_REGISTRY_ABI = [
    {
        "inputs": [
            {"type": "uint256", "name": "agentId"},
            {"type": "int128",  "name": "value"},
            {"type": "uint8",   "name": "valueDecimals"},
            {"type": "string",  "name": "tag1"},
            {"type": "string",  "name": "tag2"},
            {"type": "string",  "name": "endpoint"},
            {"type": "string",  "name": "feedbackURI"},
            {"type": "bytes32", "name": "feedbackHash"},
        ],
        "name": "giveFeedback", "outputs": [],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [
            {"type": "uint256", "name": "tokenId"},
            {"type": "uint256", "name": "score"},
        ],
        "name": "setEigenTrustScore", "outputs": [],
        "stateMutability": "nonpayable", "type": "function",
    },
    {
        "inputs": [{"type": "uint256", "name": ""}],
        "name": "eigenTrustScore",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view", "type": "function",
    },
]
