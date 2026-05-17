from web3 import Web3
from app.core.config import get_settings

def check():
    settings = get_settings()
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url))
    
    keys = [
        ("Platform", settings.platform_private_key),
        ("Judge 1", settings.judge_1_private_key),
        ("Judge 2", settings.judge_2_private_key),
        ("Judge 3", settings.judge_3_private_key),
    ]
    
    print(f"Connected to {settings.rpc_url}: {w3.is_connected()}")
    
    for name, key in keys:
        if not key:
            print(f"{name}: No key")
            continue
        try:
            acc = w3.eth.account.from_key(key)
            bal = w3.eth.get_balance(acc.address)
            print(f"{name}: {acc.address} | Balance: {w3.from_wei(bal, 'ether')} ETH")
        except Exception as e:
            print(f"{name}: Error - {e}")

if __name__ == "__main__":
    check()
