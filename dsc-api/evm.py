from fastapi import FastAPI, HTTPException
from web3 import Web3
from web3.logs import DISCARD
from dotenv import load_dotenv
from pathlib import Path
import os
import json
from pydantic import BaseModel
from typing import Optional

# Data type classes
class MintRequest(BaseModel):
    amount: float

class DepositRequest(MintRequest):
    token_address: str

class RedeemRequest(DepositRequest):
    pass

class BurnRequest(MintRequest):
    pass

class DepositAndMintRequest(DepositRequest):
    amount_dsc_to_mint: float

class RedeemForDscRequest(DepositRequest):
    amount_dsc_to_burn: float

class LiquidateRequest(BaseModel):
    collateral: str
    user: str
    debt_to_cover: float

class UserAddress(BaseModel):
    user: str

class UserTokenRequest(UserAddress):
    token: str

class UserTokenRequestWithAmount(UserTokenRequest):
    amount: Optional[float] = None

class ApproveTokenRequest(BaseModel):
    token_address: str
    spender_address: str
    amount: float

class TokenMint(BaseModel):
    amount: float

load_dotenv()

app = FastAPI()

# Helper function to validate Ethereum addresses
def is_valid_address(address: str) -> bool:
    if not isinstance(address, str) or not address.strip():
        return False
    try:
        return Web3.is_checksum_address(address) or Web3.to_address(address)
    except ValueError:
        return False

# Web3 setup
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
SEPOLIA_DSCEngine_ADDRESS = os.getenv("SEPOLIA_DSCEngine_ADDRESS")
SEPOLIA_WAVAX_ADDRESS = os.getenv("SEPOLIA_WAVAX_ADDRESS")
SEPOLIA_WETH_ADDRESS = os.getenv("SEPOLIA_WETH_ADDRESS")
SEPOLIA_DSC_ADDRESS = os.getenv("SEPOLIA_DSC_ADDRESS")

# Validate environment variables at startup
required_vars = {
    "SEPOLIA_RPC_URL": SEPOLIA_RPC_URL,
    "PRIVATE_KEY": PRIVATE_KEY,
    "SEPOLIA_DSCEngine_ADDRESS": SEPOLIA_DSCEngine_ADDRESS,
    "SEPOLIA_WAVAX_ADDRESS": SEPOLIA_WAVAX_ADDRESS,
    "SEPOLIA_WETH_ADDRESS": SEPOLIA_WETH_ADDRESS,
    "SEPOLIA_DSC_ADDRESS": SEPOLIA_DSC_ADDRESS
}
missing_vars = [key for key, value in required_vars.items() if not value]
if missing_vars:
    raise RuntimeError(f"Missing environment variables: {', '.join(missing_vars)}")

# Derive public address from private key
try:
    if not PRIVATE_KEY.startswith("0x"):
        PRIVATE_KEY = "0x" + PRIVATE_KEY
    account = Web3().eth.account.from_key(PRIVATE_KEY)
    public_address = account.address
except ValueError as e:
    raise RuntimeError(f"Invalid private key: {str(e)}")

# Validate addresses
for var_name, address in [
    ("PUBLIC_ADDRESS", public_address),
    ("SEPOLIA_DSCEngine_ADDRESS", SEPOLIA_DSCEngine_ADDRESS),
    ("SEPOLIA_WAVAX_ADDRESS", SEPOLIA_WAVAX_ADDRESS),
    ("SEPOLIA_WETH_ADDRESS", SEPOLIA_WETH_ADDRESS),
    ("SEPOLIA_DSC_ADDRESS", SEPOLIA_DSC_ADDRESS)
]:
    if not is_valid_address(address):
        raise RuntimeError(f"Invalid Ethereum address for {var_name}: {address}")

w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
private_key = PRIVATE_KEY
contract_address = Web3.to_checksum_address(SEPOLIA_DSCEngine_ADDRESS)
wavax_address = Web3.to_checksum_address(SEPOLIA_WAVAX_ADDRESS)
weth_address = Web3.to_checksum_address(SEPOLIA_WETH_ADDRESS)
dsc_address = Web3.to_checksum_address(SEPOLIA_DSC_ADDRESS)

# Verify chain ID (Sepolia = 11155111)
if w3.eth.chain_id != 11155111:
    raise RuntimeError(f"Connected to wrong network. Expected chain ID 11155111 (Sepolia), got {w3.eth.chain_id}")

if not w3.is_connected():
    raise HTTPException(status_code=500, detail="Failed to connect to the Ethereum node")

# Load ABI
abi_path = Path(__file__).resolve().parent.parent / "dsc-foundry-StableToken" / "out" / "DSCEngine.sol" / "DSCEngine.json"
if not abi_path.exists():
    raise RuntimeError(f"ABI file not found at {abi_path}")
with open(abi_path, "r") as abi_file:
    contract_json = json.load(abi_file)
    abi = contract_json["abi"]

# WETH ABI (includes receive(), withdrawEthAndBurnWETH, and events)
weth_abi = [
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"}
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [],
        "name": "depositEthAndMintWETH",
        "outputs": [],
        "payable": True,
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "amountToBurn", "type": "uint256"}
        ],
        "name": "withdrawEthAndBurnWETH",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "src", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "wad", "type": "uint256"}
        ],
        "name": "Deposit",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "to", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "value", "type": "uint256"}
        ],
        "name": "Transfer",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "string", "name": "status", "type": "string"}
        ],
        "name": "BurnedAndWithdrawn",
        "type": "event"
    }
]

# Minimal ERC20 ABI for WAVAX and DSC
erc20_abi = [
    {
        "constant": False,
        "inputs": [],
        "name": "depositEthAndMintWAVAX",
        "outputs": [],
        "payable": True,
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"}
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Initialize contracts
contract = w3.eth.contract(address=contract_address, abi=abi)
wavax_contract = w3.eth.contract(address=wavax_address, abi=erc20_abi)
weth_contract = w3.eth.contract(address=weth_address, abi=weth_abi)
dsc_contract = w3.eth.contract(address=dsc_address, abi=erc20_abi)

def build_tx(function=None, to_address=None, value=0, data=None):
    """Helper to build, sign, and send a transaction with receipt confirmation"""
    if not is_valid_address(public_address):
        raise ValueError(f"Invalid public address: {public_address}")
    nonce = w3.eth.get_transaction_count(public_address)
    chain_id = w3.eth.chain_id
    gas_price = w3.eth.gas_price  # Dynamic gas price
    txn = {
        "from": public_address,
        "nonce": nonce,
        "gas": 100000 if function is None else 3000000,
        "gasPrice": gas_price,
        "value": value,
        "chainId": chain_id
    }
    if function:
        txn.update(function().build_transaction({
            "from": public_address,
            "nonce": nonce,
            "gas": 3000000,
            "gasPrice": gas_price,
            "value": value,
            "chainId": chain_id
        }))
    else:
        txn["to"] = Web3.to_checksum_address(to_address)
        if data:
            txn["data"] = data
        else:
            txn["data"] = "0x"
    signed_txn = w3.eth.account.sign_transaction(txn, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status == 0:
        raise HTTPException(status_code=500, detail="Transaction reverted")
    return tx_hash, receipt

async def approve_token(token_contract, spender_address, amount):
    """Approve a spender to spend tokens for public_address"""
    try:
        if not is_valid_address(spender_address):
            raise ValueError(f"Invalid spender address: {spender_address}")
        spender_address = Web3.to_checksum_address(spender_address)
        amount_in_wei = w3.to_wei(amount, "ether")
        allowance = token_contract.functions.allowance(public_address, spender_address).call()
        if allowance < amount_in_wei:
            tx_hash, _ = build_tx(
                lambda: token_contract.functions.approve(spender_address, amount_in_wei)  # Fixed: Pass arguments
            )
            return tx_hash.hex()
        return None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approval failed: {str(e)}")
    
@app.post("/approve-tokens")
async def approve_tokens(data: ApproveTokenRequest):
    try:
        if not is_valid_address(data.token_address):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token_address}")
        if not is_valid_address(data.spender_address):
            raise HTTPException(status_code=400, detail=f"Invalid spender address: {data.spender_address}")
        token_address = Web3.to_checksum_address(data.token_address)
        spender_address = Web3.to_checksum_address(data.spender_address)
        amount = data.amount

        if amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")

        token_contract = None
        token_name = None
        if token_address.lower() == wavax_address.lower():
            token_contract = wavax_contract
            token_name = "WAVAX"
        elif token_address.lower() == weth_address.lower():
            token_contract = weth_contract
            token_name = "WETH"
        elif token_address.lower() == dsc_address.lower():
            token_contract = dsc_contract
            token_name = "DSC"
        else:
            raise HTTPException(status_code=400, detail="Invalid token address. Must be WAVAX, WETH, or DSC.")

        tx_hash = await approve_token(token_contract, spender_address, amount)
        if tx_hash:
            return {f"{token_name}_approval": tx_hash}
        return {"message": f"No approval needed for {token_name}; sufficient allowance already set"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/deposit-eth-to-weth")
async def deposit_eth_to_weth(data: TokenMint):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        if not is_valid_address(weth_address):
            raise HTTPException(status_code=500, detail=f"Invalid WETH address: {weth_address}")
        if not is_valid_address(public_address):
            raise HTTPException(status_code=500, detail="Invalid account address")
        
        # Check balances before transaction
        eth_balance_before = w3.eth.get_balance(public_address)
        weth_balance_before = weth_contract.functions.balanceOf(public_address).call()
        amount_in_wei = w3.to_wei(data.amount, "ether")
        gas_limit = 100000
        gas_price = w3.eth.gas_price
        required_balance = amount_in_wei + (gas_limit * gas_price)
        if eth_balance_before < required_balance:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient ETH balance: {w3.from_wei(eth_balance_before, 'ether')} ETH available, {w3.from_wei(required_balance, 'ether')} ETH required"
            )
        
        # Send ETH directly to WETH contract to trigger receive()
        tx_hash, receipt = build_tx(
            to_address=weth_address,
            value=amount_in_wei,
            data=None
        )
        
        # Parse logs for Deposit or Transfer events
        deposit_logs = weth_contract.events.Deposit().process_receipt(receipt, errors=DISCARD)
        transfer_logs = weth_contract.events.Transfer().process_receipt(receipt, errors=DISCARD)
        events = {
            "deposit_events": [
                {"address": log.args.src, "amount": w3.from_wei(log.args.wad, "ether")}
                for log in deposit_logs
                if hasattr(log.args, "src") and hasattr(log.args, "wad")
            ],
            "transfer_events": [
                {"from": log.args["from"], "to": log.args.to, "amount": w3.from_wei(log.args.value, "ether")}
                for log in transfer_logs
                if hasattr(log.args, "from") and hasattr(log.args, "to") and hasattr(log.args, "value")
            ]
        }
        
        # Check balances after transaction
        eth_balance_after = w3.eth.get_balance(public_address)
        weth_balance_after = weth_contract.functions.balanceOf(public_address).call()
        
        # Verify WETH increase
        weth_increase = weth_balance_after - weth_balance_before
        if weth_increase < amount_in_wei:
            raise HTTPException(
                status_code=500,
                detail=f"WETH not minted: expected increase of {w3.from_wei(amount_in_wei, 'ether')} WETH, got {w3.from_wei(weth_increase, 'ether')} WETH"
            )
        
        return {
            "tx_hash": tx_hash.hex(),
            "eth_balance_before": w3.from_wei(eth_balance_before, "ether"),
            "eth_balance_after": w3.from_wei(eth_balance_after, "ether"),
            "weth_balance_before": w3.from_wei(weth_balance_before, "ether"),
            "weth_balance_after": w3.from_wei(weth_balance_after, "ether"),
            "events": events,
            "tx_data": "0x"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WETH deposit failed: {str(e)}")

@app.post("/withdraw-eth-and-burn-weth")
async def withdraw_eth_and_burn_weth(data: TokenMint):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        if not is_valid_address(weth_address):
            raise HTTPException(status_code=500, detail=f"Invalid WETH address: {weth_address}")
        if not is_valid_address(public_address):
            raise HTTPException(status_code=500, detail="Invalid account address")
        
        # Check balances before transaction
        eth_balance_before = w3.eth.get_balance(public_address)
        weth_balance_before = weth_contract.functions.balanceOf(public_address).call()
        amount_in_wei = w3.to_wei(data.amount, "ether")
        gas_limit = 300000
        gas_price = w3.eth.gas_price
        required_gas = gas_limit * gas_price
        if weth_balance_before < amount_in_wei:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient WETH balance: {w3.from_wei(weth_balance_before, 'ether')} WETH available, {w3.from_wei(amount_in_wei, 'ether')} WETH required"
            )
        if eth_balance_before < required_gas:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient ETH balance for gas: {w3.from_wei(eth_balance_before, 'ether')} ETH available, {w3.from_wei(required_gas, 'ether')} ETH required"
            )
        
        # Check contract ETH balance
        contract_eth_balance = w3.eth.get_balance(weth_address)
        if contract_eth_balance < amount_in_wei:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient contract ETH balance: {w3.from_wei(contract_eth_balance, 'ether')} ETH available, {w3.from_wei(amount_in_wei, 'ether')} ETH required"
            )
        
        # Call withdrawEthAndBurnWETH with amount_in_wei
        tx_hash, receipt = build_tx(
            lambda: weth_contract.functions.withdrawEthAndBurnWETH(amount_in_wei),  # Fixed: Pass amount_in_wei directly
            value=0
        )
        
        # Parse logs for BurnedAndWithdrawn or Transfer events
        burn_logs = weth_contract.events.BurnedAndWithdrawn().process_receipt(receipt, errors=DISCARD)
        transfer_logs = weth_contract.events.Transfer().process_receipt(receipt, errors=DISCARD)
        events = {
            "burned_and_withdrawn_events": [
                {"user": log.args.user, "amount": w3.from_wei(log.args.amount, "ether"), "status": log.args.status}
                for log in burn_logs
                if hasattr(log.args, "user") and hasattr(log.args, "amount") and hasattr(log.args, "status")
            ],
            "transfer_events": [
                {"from": log.args["from"], "to": log.args.to, "amount": w3.from_wei(log.args.value, "ether")}
                for log in transfer_logs
                if hasattr(log.args, "from") and hasattr(log.args, "to") and hasattr(log.args, "value")
            ]
        }
        
        # Check balances after transaction
        eth_balance_after = w3.eth.get_balance(public_address)
        weth_balance_after = weth_contract.functions.balanceOf(public_address).call()
        
        # Verify ETH increase and WETH decrease
        eth_increase = eth_balance_after - eth_balance_before
        weth_decrease = weth_balance_before - weth_balance_after
        if eth_increase < amount_in_wei - required_gas:
            raise HTTPException(
                status_code=500,
                detail=f"ETH not received: expected increase of ~{w3.from_wei(amount_in_wei, 'ether')} ETH, got {w3.from_wei(eth_increase, 'ether')} ETH"
            )
        if weth_decrease < amount_in_wei:
            raise HTTPException(
                status_code=500,
                detail=f"WETH not burned: expected decrease of {w3.from_wei(amount_in_wei, 'ether')} WETH, got {w3.from_wei(weth_decrease, 'ether')} WETH"
            )
        
        return {
            "tx_hash": tx_hash.hex(),
            "eth_balance_before": w3.from_wei(eth_balance_before, "ether"),
            "eth_balance_after": w3.from_wei(eth_balance_after, "ether"),
            "weth_balance_before": w3.from_wei(weth_balance_before, "ether"),
            "weth_balance_after": w3.from_wei(weth_balance_after, "ether"),
            "events": events
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"WETH withdraw and burn failed: {str(e)}")
    
@app.post("/deposit-collateral")
async def deposit_collateral(data: DepositRequest):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        if not is_valid_address(data.token_address):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token_address}")
        token = Web3.to_checksum_address(data.token_address)
        amount_in_wei = w3.to_wei(data.amount, "ether")
        # Check allowance
        token_contract = w3.eth.contract(address=token, abi=erc20_abi)
        allowance = token_contract.functions.allowance(public_address, contract_address).call()
        if allowance < amount_in_wei:
            raise HTTPException(status_code=400, detail="Insufficient allowance. Approve tokens first")
        tx_hash, _ = build_tx(
            lambda: contract.functions.depositCollateral(token, amount_in_wei)  # Fixed: Pass token, amount_in_wei
        )
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mint-dsc")
async def mint_dsc(data: MintRequest):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        amount_in_wei = w3.to_wei(data.amount, "ether")
        tx_hash, _ = build_tx(
            lambda: contract.functions.mintDsc(amount_in_wei)  # Fixed: Pass amount_in_wei
        )
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/redeem-collateral")
async def redeem_collateral(data: RedeemRequest):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        if not is_valid_address(data.token_address):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token_address}")
        token = Web3.to_checksum_address(data.token_address)
        amount_in_wei = w3.to_wei(data.amount, "ether")
        tx_hash, _ = build_tx(
            lambda: contract.functions.redeemCollateral(token, amount_in_wei)  # Fixed: Pass token, amount_in_wei
        )
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/burn-dsc")
async def burn_dsc(data: BurnRequest):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        amount_in_wei = w3.to_wei(data.amount, "ether")
        # Check allowance
        allowance = dsc_contract.functions.allowance(public_address, contract_address).call()
        if allowance < amount_in_wei:
            raise HTTPException(status_code=400, detail="Insufficient DSC allowance. Approve tokens first")
        tx_hash, _ = build_tx(
            lambda: contract.functions.burnDsc(amount_in_wei)  # Fixed: Pass amount_in_wei
        )
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/deposit-collateral-and-mint-dsc")
async def deposit_collateral_and_mint_dsc(data: DepositAndMintRequest):
    try:
        if data.amount <= 0 or data.amount_dsc_to_mint <= 0:
            raise HTTPException(status_code=400, detail="Amounts must be positive")
        if not is_valid_address(data.token_address):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token_address}")
        token = Web3.to_checksum_address(data.token_address)
        amount_in_wei = w3.to_wei(data.amount, "ether")
        amount_dsc_to_mint_in_wei = w3.to_wei(data.amount_dsc_to_mint, "ether")
        # Check allowance
        token_contract = w3.eth.contract(address=token, abi=erc20_abi)
        allowance = token_contract.functions.allowance(public_address, contract_address).call()
        if allowance < amount_in_wei:
            raise HTTPException(status_code=400, detail="Insufficient collateral allowance. Approve tokens first")
        tx_hash, _ = build_tx(
            lambda: contract.functions.depositCollateralAndMintDsc(token, amount_in_wei, amount_dsc_to_mint_in_wei)  # Fixed: Pass arguments
        )
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/redeem-collateral-for-dsc")
async def redeem_collateral_for_dsc(data: RedeemForDscRequest):
    try:
        if data.amount <= 0 or data.amount_dsc_to_burn <= 0:
            raise HTTPException(status_code=400, detail="Amounts must be positive")
        if not is_valid_address(data.token_address):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token_address}")
        token = Web3.to_checksum_address(data.token_address)
        amount_in_wei = w3.to_wei(data.amount, "ether")
        amount_dsc_to_burn_in_wei = w3.to_wei(data.amount_dsc_to_burn, "ether")
        # Check allowance
        allowance = dsc_contract.functions.allowance(public_address, contract_address).call()
        if allowance < amount_dsc_to_burn_in_wei:
            raise HTTPException(status_code=400, detail="Insufficient DSC allowance. Approve tokens first")
        tx_hash, _ = build_tx(
            lambda: contract.functions.redeemCollateralForDsc(token, amount_in_wei, amount_dsc_to_burn_in_wei)
        )
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/liquidate")
async def liquidate(data: LiquidateRequest):
    try:
        if data.debt_to_cover <= 0:
            raise HTTPException(status_code=400, detail="Debt to cover must be positive")
        if not is_valid_address(data.collateral):
            raise HTTPException(status_code=400, detail=f"Invalid collateral address: {data.collateral}")
        if not is_valid_address(data.user):
            raise HTTPException(status_code=400, detail=f"Invalid user address: {data.user}")
        collateral = Web3.to_checksum_address(data.collateral)
        user = Web3.to_checksum_address(data.user)
        debt_to_cover_in_wei = w3.to_wei(data.debt_to_cover, "ether")
        # Check allowance
        allowance = dsc_contract.functions.allowance(public_address, contract_address).call()
        if allowance < debt_to_cover_in_wei:
            raise HTTPException(status_code=400, detail="Insufficient DSC allowance. Approve tokens first")
        tx_hash, _ = build_tx(contract.functions.liquidate, [collateral, user, debt_to_cover_in_wei])
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/account-information")
async def get_account_information(data: UserAddress):
    try:
        if not is_valid_address(data.user):
            raise HTTPException(status_code=400, detail=f"Invalid user address: {data.user}")
        user = Web3.to_checksum_address(data.user)
        total_dsc_minted, collateral_value_in_usd = contract.functions.getAccountInformation(user).call()
        return {
            "total_dsc_minted": w3.from_wei(total_dsc_minted, "ether"),
            "collateral_value_in_usd": w3.from_wei(collateral_value_in_usd, "ether")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/collateral-balance")
async def get_collateral_balance(data: UserTokenRequest):
    try:
        if not is_valid_address(data.user):
            raise HTTPException(status_code=400, detail=f"Invalid user address: {data.user}")
        if not is_valid_address(data.token):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token}")
        user = Web3.to_checksum_address(data.user)
        token = Web3.to_checksum_address(data.token)
        balance = contract.functions.getCollateralBalanceOfUser(user, token).call()
        return {"balance": w3.from_wei(balance, "ether")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/health-factor")
async def get_health_factor(data: UserAddress):
    try:
        if not is_valid_address(data.user):
            raise HTTPException(status_code=400, detail=f"Invalid user address: {data.user}")
        user = Web3.to_checksum_address(data.user)
        health_factor = contract.functions.getHealthFactor(user).call()
        return {"health_factor": w3.from_wei(health_factor, "ether")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/collateral-tokens")
async def get_collateral_tokens():
    try:
        tokens = contract.functions.getCollateralTokens().call()
        return {"collateral_tokens": tokens}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/usd-value")
async def get_usd_value(data: UserTokenRequestWithAmount):
    try:
        if not is_valid_address(data.token):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token}")
        if not is_valid_address(data.user):
            raise HTTPException(status_code=400, detail=f"Invalid user address: {data.user}")
        token = Web3.to_checksum_address(data.token)
        user = Web3.to_checksum_address(data.user)
        if data.amount is not None:
            if data.amount <= 0:
                raise HTTPException(status_code=400, detail="Amount must be positive")
            amount_in_wei = w3.to_wei(data.amount, "ether")
        else:
            amount_in_wei = contract.functions.getCollateralBalanceOfUser(user, token).call()
        usd_value = contract.functions.getUsdValue(token, amount_in_wei).call()
        return {"usd_value": w3.from_wei(usd_value, "ether")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))