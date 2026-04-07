from __future__ import annotations
import json
from pathlib import Path
from dotenv import dotenv_values
from web3 import Web3

env      = dotenv_values(Path(__file__).parent.parent / ".env")
RPC_URL  = env.get("RPC_URL", "http://127.0.0.1:8545")
CHAIN_ID = int(env.get("CHAIN_ID", 31337))
REGISTRY = env.get("IDENTITY_REGISTRY_ADDRESS", "")
STAKING  = env.get("STAKING_CONTRACT_ADDRESS", "")

# ABI IdentityRegistry
REGISTRY_ABI = [
    {
        "inputs": [
            {"name": "agentId_",   "type": "string"},
            {"name": "agentType_", "type": "uint8"},
            {"name": "agentURI_",  "type": "string"},
            {"name": "version_",   "type": "string"},
        ],
        "name": "register",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "agentId",  "type": "string"},
            {"indexed": True,  "name": "tokenId",  "type": "uint256"},
            {"indexed": True,  "name": "owner",    "type": "address"},
            {"indexed": False, "name": "agentType","type": "uint8"},
            {"indexed": False, "name": "agentURI", "type": "string"},
            {"indexed": False, "name": "version",  "type": "string"},
        ],
        "name": "AgentCreated",
        "type": "event",
    },
]

# ABI StakingContract — minimal
STAKING_ABI = [
    {
        "inputs": [],
        "name": "stake",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "withdraw",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "agent", "type": "address"}],
        "name": "getStake",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "agent", "type": "address"}],
        "name": "isEligibleProvider",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def get_w3() -> Web3:
    return Web3(Web3.HTTPProvider(RPC_URL))


def sign_and_send(
    private_key: str,
    agent_id:    str,
    agent_type:  int,
    agent_uri:   str,
    version:     str,
) -> tuple[str, int]:
    w3       = get_w3()
    account  = w3.eth.account.from_key(private_key)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(REGISTRY),
        abi=REGISTRY_ABI,
    )

    tx = contract.functions.register(
        agent_id, agent_type, agent_uri, version
    ).build_transaction({
        "from":    account.address,
        "nonce":   w3.eth.get_transaction_count(account.address),
        "gas":     300_000,
        "chainId": CHAIN_ID,
    })

    signed      = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash_raw = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt     = w3.eth.wait_for_transaction_receipt(tx_hash_raw)

    # Formater tx_hash correctement → 0x + 64 chars hex
    tx_hash_str = tx_hash_raw.hex()
    if not tx_hash_str.startswith("0x"):
        tx_hash_str = "0x" + tx_hash_str

    # Récupérer tokenId depuis event
    token_id = 1
    try:
        logs = contract.events.AgentCreated().process_receipt(receipt)
        if logs:
            token_id = logs[0]["args"]["tokenId"]
    except Exception:
        pass

    return tx_hash_str, int(token_id)


def stake_for_agent(
    private_key:  str,
    stake_amount_eth: float,
) -> str:
    """
    Stake ETH dans StakingContract pour le wallet du seller.
    Appelé après register + confirm.
    Retourne tx_hash.
    """
    if not STAKING:
        raise ValueError(
            "STAKING_CONTRACT_ADDRESS non configuré dans .env"
        )

    w3      = get_w3()
    account = w3.eth.account.from_key(private_key)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(STAKING),
        abi=STAKING_ABI,
    )

    amount_wei = w3.to_wei(stake_amount_eth, "ether")

    tx = contract.functions.stake().build_transaction({
        "from":    account.address,
        "value":   amount_wei,
        "nonce":   w3.eth.get_transaction_count(account.address),
        "gas":     100_000,
        "chainId": CHAIN_ID,
    })

    signed  = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash)

    return tx_hash.hex() if not isinstance(tx_hash, str) else tx_hash


def get_stake_amount(address: str) -> float:
    """Retourne le stake actuel d'un wallet en ETH."""
    if not STAKING:
        return 0.0
    try:
        w3       = get_w3()
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(STAKING),
            abi=STAKING_ABI,
        )
        amount_wei = contract.functions.getStake(
            Web3.to_checksum_address(address)
        ).call()
        return float(w3.from_wei(amount_wei, "ether"))
    except Exception:
        return 0.0


def is_eligible_provider(address: str) -> bool:
    """Vérifie si le wallet a le stake minimum pour être provider."""
    if not STAKING:
        return False
    try:
        w3       = get_w3()
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(STAKING),
            abi=STAKING_ABI,
        )
        return contract.functions.isEligibleProvider(
            Web3.to_checksum_address(address)
        ).call()
    except Exception:
        return False


def get_hardhat_accounts() -> list[dict]:
    w3 = get_w3()
    accounts = [
        {
            "address":     "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            "private_key": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
        },
        {
            "address":     "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            "private_key": "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
        },
        {
            "address":     "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            "private_key": "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
        },
    ]
    result = []
    for a in accounts:
        try:
            balance = w3.eth.get_balance(a["address"])
            eth     = round(float(w3.from_wei(balance, "ether")), 4)
        except Exception:
            eth = 0.0
        result.append({
            **a,
            "balance_eth": eth,
            "label":       f"{a['address'][:6]}...{a['address'][-4:]}",
        })
    return result