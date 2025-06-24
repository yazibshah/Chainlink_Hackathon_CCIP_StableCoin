from fastapi import FastAPI, HTTPException
from web3 import Web3
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
    if not isinstance(address, str) or not address:
        return False
    try:
        return Web3.is_checksum_address(address) or Web3.to_checksum_address(address)
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
required_env_vars = {
    "SEPOLIA_RPC_URL": SEPOLIA_RPC_URL,
    "PRIVATE_KEY": PRIVATE_KEY,
    "SEPOLIA_DSCEngine_ADDRESS": SEPOLIA_DSCEngine_ADDRESS,
    "SEPOLIA_WAVAX_ADDRESS": SEPOLIA_WAVAX_ADDRESS,
    "SEPOLIA_WETH_ADDRESS": SEPOLIA_WETH_ADDRESS,
    "SEPOLIA_DSC_ADDRESS": SEPOLIA_DSC_ADDRESS
}
missing_vars = [key for key, value in required_env_vars.items() if not value]
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

abi_path = Path(__file__).resolve().parent.parent / "Blockchain-Foundry-StableToken" / "out" / "DSCEngine.sol" / "DSCEngine.json"

if not w3.is_connected():
    raise HTTPException(status_code=500, detail="Failed to connect to the Ethereum node")

# Load ABI
with open(abi_path, "r") as abi_file:
    contract_json = json.load(abi_file)
    abi = contract_json["abi"]

# Minimal ERC20 ABI for depositEthAndMint functions
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
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
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
        "type": "function"
    }
]

# Initialize contracts
contract = w3.eth.contract(address=contract_address, abi=abi)
wavax_contract = w3.eth.contract(address=wavax_address, abi=erc20_abi)
weth_contract = w3.eth.contract(address=weth_address, abi=erc20_abi)
dsc_contract = w3.eth.contract(address=dsc_address, abi=erc20_abi)

def build_tx(function, args, value=0):
    """Helper to build and sign a transaction"""
    if not is_valid_address(public_address):
        raise ValueError(f"Invalid public address: {public_address}")
    nonce = w3.eth.get_transaction_count(public_address)
    txn = function(*args).build_transaction({
        "from": public_address,
        "nonce": nonce,
        "gas": 3000000,
        "gasPrice": w3.to_wei("20", "gwei"),
        "value": value
    })
    signed_txn = w3.eth.account.sign_transaction(txn, private_key)
    return w3.eth.send_raw_transaction(signed_txn.raw_transaction)

async def approve_token(token_contract, spender_address, amount):
    """Approve a spender to spend tokens for public_address"""
    try:
        if not is_valid_address(spender_address):
            raise ValueError(f"Invalid spender address: {spender_address}")
        spender_address = Web3.to_checksum_address(spender_address)
        amount_in_wei = w3.to_wei(amount, "ether")
        allowance = token_contract.functions.allowance(public_address, spender_address).call()
        if allowance < amount_in_wei:
            tx_hash = build_tx(
                token_contract.functions.approve,
                [spender_address, amount_in_wei]
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

@app.post("/mint-wavax")
async def mint_wavax(data: TokenMint):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        if not is_valid_address(wavax_address):
            raise HTTPException(status_code=500, detail=f"Invalid WAVAX contract address: {wavax_address}")
        if not is_valid_address(public_address):
            raise HTTPException(status_code=500, detail=f"Invalid public address: {public_address}")
        # Convert amount from ETH to Wei
        amount_in_wei = w3.to_wei(data.amount, "ether")
        # Deposit ETH and mint WAVAX
        tx_hash = build_tx(
            wavax_contract.functions.depositEthAndMintWAVAX,
            [],
            value=amount_in_wei
        )
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mint-weth")
async def mint_weth(data: TokenMint):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        if not is_valid_address(weth_address):
            raise HTTPException(status_code=500, detail=f"Invalid WETH contract address: {weth_address}")
        if not is_valid_address(public_address):
            raise HTTPException(status_code=500, detail=f"Invalid public address: {public_address}")
        # Convert amount from ETH to Wei
        amount_in_wei = w3.to_wei(data.amount, "ether")
        # Deposit ETH and mint WETH
        tx_hash = build_tx(
            weth_contract.functions.depositEthAndMintWETH,
            [],
            value=amount_in_wei
        )
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/deposit-collateral")
async def deposit_collateral(data: DepositRequest):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        if not is_valid_address(data.token_address):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token_address}")
        token = Web3.to_checksum_address(data.token_address)
        amount_in_wei = w3.to_wei(data.amount, "ether")
        tx_hash = build_tx(contract.functions.depositCollateral, [token, amount_in_wei])
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mint-dsc")
async def mint_dsc(data: MintRequest):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        amount_in_wei = w3.to_wei(data.amount, "ether")
        tx_hash = build_tx(contract.functions.mintDsc, [amount_in_wei])
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
        tx_hash = build_tx(contract.functions.redeemCollateral, [token, amount_in_wei])
        return {"tx_hash": tx_hash.hex()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/burn-dsc")
async def burn_dsc(data: BurnRequest):
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        amount_in_wei = w3.to_wei(data.amount, "ether")
        tx_hash = build_tx(contract.functions.burnDsc, [amount_in_wei])
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
        tx_hash = build_tx(contract.functions.depositCollateralAndMintDsc, [token, amount_in_wei, amount_dsc_to_mint_in_wei])
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
        tx_hash = build_tx(contract.functions.redeemCollateralForDsc, [token, amount_in_wei, amount_dsc_to_burn_in_wei])
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
        tx_hash = build_tx(contract.functions.liquidate, [collateral, user, debt_to_cover_in_wei])
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
            "total_dsc_minted": total_dsc_minted,
            "collateral_value_in_usd": collateral_value_in_usd
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/collateral-balance")
async def get_collateral_balance(data: UserTokenRequest):
    try:
        if not is_valid_address(data.user):
            raise HTTPException(status_code=400, detail=f"Invalid user address: {data.user}")
        if not is_valid_address(data.token):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token}")
        user = Web3.to_checksum_address(data.user)
        token = Web3.to_checksum_address(data.token)
        balance = contract.functions.getCollateralBalanceOfUser(user, token).call()
        return {"balance": w3.from_wei(balance, "ether")}  # Return in ETH
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health-factor")
async def get_health_factor(data: UserAddress):
    try:
        if not is_valid_address(data.user):
            raise HTTPException(status_code=400, detail=f"Invalid user address: {data.user}")
        user = Web3.to_checksum_address(data.user)
        health_factor = contract.functions.getHealthFactor(user).call()
        return {"health_factor": health_factor}
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
        # Use provided amount if given, otherwise fetch user's collateral balance
        if data.amount is not None:
            if data.amount <= 0:
                raise HTTPException(status_code=400, detail="Amount must be positive")
            amount_in_wei = w3.to_wei(data.amount, "ether")
        else:
            amount_in_wei = contract.functions.getCollateralBalanceOfUser(user, token).call()
        usd_value = contract.functions.getUsdValue(token, amount_in_wei).call()
        return {"usd_value": usd_value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))