from fastapi import FastAPI, HTTPException
from web3 import Web3
from web3.logs import DISCARD
from web3.exceptions import ContractLogicError
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from typing import Optional

# Data models
class ApproveTokenRequest(BaseModel):
    token_address: str
    amount: float

class TokenDepositRequest(BaseModel):
    token_address: str
    amount: float

class SendEthRequest(BaseModel):
    amount: float

class TransferTokensRequest(BaseModel):
    receiver: str
    token_address: str
    amount: float

class WithdrawDepositsRequest(BaseModel):
    token_address: Optional[str] = None

load_dotenv()

app = FastAPI()

# Helper function to validate Ethereum addresses
def is_valid_address(address: str) -> bool:
    if not isinstance(address, str) or not address.strip():
        return False
    try:
        return Web3.is_checksum_address(address) or Web3.to_checksum_address(address)
    except ValueError:
        return False

# Helper function to check if a contract exists
def is_contract_deployed(w3: Web3, address: str) -> bool:
    try:
        code = w3.eth.get_code(Web3.to_checksum_address(address))
        return len(code) > 0
    except Exception:
        return False

# Web3 setup
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
DSC_TRANSFER_HUB_ADDRESS = os.getenv("EVM_DSC_TRANSFER_HUB_ADDRESS")

# Validate environment variables
required_env_vars = {
    "SEPOLIA_RPC_URL": SEPOLIA_RPC_URL,
    "PRIVATE_KEY": PRIVATE_KEY,
    "EVM_DSC_TRANSFER_HUB_ADDRESS": DSC_TRANSFER_HUB_ADDRESS
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
if not is_valid_address(DSC_TRANSFER_HUB_ADDRESS):
    raise RuntimeError(f"Invalid Ethereum address for DSC_TRANSFER_HUB_ADDRESS: {DSC_TRANSFER_HUB_ADDRESS}")
if not is_valid_address(public_address):
    raise RuntimeError(f"Invalid derived public address: {public_address}")

w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
private_key = PRIVATE_KEY
dsc_transfer_hub_address = Web3.to_checksum_address(DSC_TRANSFER_HUB_ADDRESS)

# Verify chain ID (Sepolia = 11155111)
if w3.eth.chain_id != 11155111:
    raise RuntimeError(f"Connected to wrong network. Expected chain ID 11155111 (Sepolia), got {w3.eth.chain_id}")

if not w3.is_connected():
    raise HTTPException(status_code=500, detail="Failed to connect to Ethereum node")

# DSCTransferHub ABI
dsc_transfer_hub_abi = [
    {
        "inputs": [
            {"internalType": "address", "name": "_router", "type": "address"},
            {"internalType": "address", "name": "_link", "type": "address"},
            {"internalType": "address[]", "name": "_initialTokens", "type": "address[]"}
        ],
        "stateMutability": "nonpayable",
        "type": "constructor"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "token", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "TokensDeposited",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "internalType": "bytes32", "name": "messageId", "type": "bytes32"},
            {"indexed": False, "internalType": "uint64", "name": "destinationChainSelector", "type": "uint64"},
            {"indexed": False, "internalType": "address", "name": "receiver", "type": "address"},
            {"indexed": False, "internalType": "address", "name": "token", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "tokenAmount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "fees", "type": "uint256"}
        ],
        "name": "TokensTransferred",
        "type": "event"
    },
    {
        "inputs": [
            {"internalType": "uint64", "name": "_destinationChainSelector", "type": "uint64"},
            {"internalType": "bool", "name": "_allowed", "type": "bool"}
        ],
        "name": "allowlistDestinationChain",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "_token", "type": "address"},
            {"internalType": "uint256", "name": "_amount", "type": "uint256"}
        ],
        "name": "depositTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint64", "name": "", "type": "uint64"}
        ],
        "name": "allowlistedChains",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"}
        ],
        "name": "isSupportedToken",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint64", "name": "_destinationChainSelector", "type": "uint64"},
            {"internalType": "address", "name": "_receiver", "type": "address"},
            {"internalType": "address", "name": "_token", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "transferTokens",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "_token", "type": "address"}
        ],
        "name": "withdrawDeposits",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"}
        ],
        "name": "userEthDeposits",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "address", "name": "", "type": "address"}
        ],
        "name": "userTokenDeposits",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"}
        ],
        "name": "supportedTokens",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "stateMutability": "payable",
        "type": "receive"
    }
]

# Minimal ERC20 ABI for token approvals
erc20_abi = [
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
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Initialize contract
if not is_contract_deployed(w3, dsc_transfer_hub_address):
    raise RuntimeError(f"No contract deployed at {dsc_transfer_hub_address} on Sepolia")

dsc_transfer_hub = w3.eth.contract(address=dsc_transfer_hub_address, abi=dsc_transfer_hub_abi)

def build_tx(function=None, to_address=None, value=0, data=None):
    """Helper to build, sign, and send a transaction with receipt confirmation"""
    if not is_valid_address(public_address):
        raise ValueError(f"Invalid public address: {public_address}")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            nonce = w3.eth.get_transaction_count(public_address)
            chain_id = w3.eth.chain_id
            gas_price = w3.eth.gas_price * 2  # Doubled gas price for reliability
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
                if not is_valid_address(to_address):
                    raise ValueError(f"Invalid to address: {to_address}")
                txn["to"] = Web3.to_checksum_address(to_address)
                txn["data"] = data if data else "0x"
            signed_txn = w3.eth.account.sign_transaction(txn, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            if receipt.status == 0:
                # Attempt to decode revert reason
                try:
                    w3.eth.call(txn)
                except ContractLogicError as call_error:
                    raise HTTPException(status_code=500, detail=f"Transaction reverted: {str(call_error)}")
                raise HTTPException(status_code=500, detail="Transaction reverted: Unknown reason")
            return tx_hash, receipt
        except ValueError as e:
            if "nonce too low" in str(e) and attempt < max_retries - 1:
                continue
            raise HTTPException(status_code=500, detail=f"Transaction failed: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Transaction failed: {str(e)}")

async def approve_token(token_contract, spender_address, amount):
    """Approve a spender to spend tokens"""
    try:
        if not is_valid_address(spender_address):
            raise ValueError(f"Invalid spender address: {spender_address}")
        spender_address = Web3.to_checksum_address(spender_address)
        amount_in_wei = w3.to_wei(amount, "ether")
        allowance = token_contract.functions.allowance(public_address, spender_address).call()
        if allowance < amount_in_wei:
            tx_hash, _ = build_tx(
                lambda: token_contract.functions.approve(spender_address, amount_in_wei)
            )
            return tx_hash.hex()
        return None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approval failed: {str(e)}")

@app.post("/approve-tokens")
async def approve_tokens(data: ApproveTokenRequest):
    """Approve DSCTransferHub to spend tokens"""
    try:
        if not is_valid_address(data.token_address):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token_address}")
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        
        token_address = Web3.to_checksum_address(data.token_address)
        token_contract = w3.eth.contract(address=token_address, abi=erc20_abi)
        
        # Check if token is supported by DSCTransferHub
        is_supported = dsc_transfer_hub.functions.isSupportedToken(token_address).call()
        if not is_supported:
            raise HTTPException(status_code=400, detail="Token not supported by DSCTransferHub")

        tx_hash = await approve_token(token_contract, dsc_transfer_hub_address, data.amount)
        if tx_hash:
            return {"approval_tx_hash": tx_hash}
        return {"message": "No approval needed; sufficient allowance already set"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/deposit-tokens")
async def deposit_tokens(data: TokenDepositRequest):
    """Deposit tokens into DSCTransferHub"""
    try:
        if not is_valid_address(data.token_address):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token_address}")
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        
        token_address = Web3.to_checksum_address(data.token_address)
        amount_in_wei = w3.to_wei(data.amount, "ether")
        
        # Check if token is supported
        is_supported = dsc_transfer_hub.functions.isSupportedToken(token_address).call()
        if not is_supported:
            raise HTTPException(status_code=400, detail="Token not supported by DSCTransferHub")
        
        # Ensure approval is set
        token_contract = w3.eth.contract(address=token_address, abi=erc20_abi)
        allowance = token_contract.functions.allowance(public_address, dsc_transfer_hub_address).call()
        if allowance < amount_in_wei:
            raise HTTPException(status_code=400, detail="Insufficient allowance. Approve tokens first")

        tx_hash, _ = build_tx(
            lambda: dsc_transfer_hub.functions.depositTokens(token_address, amount_in_wei)
        )
        return {"tx_hash": tx_hash.hex()}
    except ContractLogicError as e:
        raise HTTPException(status_code=500, detail=f"Contract execution reverted: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send-eth")
async def send_eth(data: SendEthRequest):
    """Send ETH to DSCTransferHub to hit the receive function"""
    try:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        
        amount_in_wei = w3.to_wei(data.amount, "ether")
        gas_limit = 100000  # Match WETH deposit gas limit
        gas_price = w3.eth.gas_price * 2  # Dynamic gas price, doubled for reliability
        required_balance = amount_in_wei + (gas_limit * gas_price)
        eth_balance_before = w3.eth.get_balance(public_address)
        
        if eth_balance_before < required_balance:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient ETH balance: {w3.from_wei(eth_balance_before, 'ether')} ETH available, {w3.from_wei(required_balance, 'ether')} ETH required"
            )
        
        # Verify contract can receive ETH
        if not is_contract_deployed(w3, dsc_transfer_hub_address):
            raise HTTPException(status_code=500, detail=f"No contract deployed at {dsc_transfer_hub_address}")

        # Send ETH directly to DSCTransferHub contract to trigger receive()
        tx_hash, receipt = build_tx(
            to_address=dsc_transfer_hub_address,
            value=amount_in_wei,
            data="0x"  # Explicitly set empty data to hit receive function
        )
        
        # Parse logs for TokensDeposited or other events
        deposit_logs = dsc_transfer_hub.events.TokensDeposited().process_receipt(receipt, errors=DISCARD)
        events = {
            "deposit_events": [
                {
                    "from": log.args["from"],
                    "token": log.args.token,
                    "amount": w3.from_wei(log.args.amount, "ether")
                }
                for log in deposit_logs
                if hasattr(log.args, "from") and hasattr(log.args, "token") and hasattr(log.args, "amount")
            ]
        }
        
        # Check ETH deposits after transaction
        eth_deposits = dsc_transfer_hub.functions.userEthDeposits(public_address).call()
        eth_balance_after = w3.eth.get_balance(public_address)
        
        # Verify ETH deposit increase
        if eth_deposits < amount_in_wei:
            raise HTTPException(
                status_code=500,
                detail=f"ETH not deposited: expected increase of {w3.from_wei(amount_in_wei, 'ether')} ETH, got {w3.from_wei(eth_deposits, 'ether')} ETH in deposits"
            )
        
        return {
            "tx_hash": tx_hash.hex(),
            "eth_balance_before": w3.from_wei(eth_balance_before, "ether"),
            "eth_balance_after": w3.from_wei(eth_balance_after, "ether"),
            "eth_deposits": w3.from_wei(eth_deposits, "ether"),
            "events": events,
            "tx_data": "0x"
        }
    except ContractLogicError as e:
        raise HTTPException(status_code=500, detail=f"Contract execution reverted: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ETH transfer failed: {str(e)}")

@app.post("/transfer-tokens")
async def transfer_tokens(data: TransferTokensRequest):
    """Transfer tokens cross-chain to Avalanche Fuji"""
    try:
        if not is_valid_address(data.receiver):
            raise HTTPException(status_code=400, detail=f"Invalid receiver address: {data.receiver}")
        if not is_valid_address(data.token_address):
            raise HTTPException(status_code=400, detail=f"Invalid token address: {data.token_address}")
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        
        token_address = Web3.to_checksum_address(data.token_address)
        receiver_address = Web3.to_checksum_address(data.receiver)
        amount_in_wei = w3.to_wei(data.amount, "ether")
        destination_chain_selector = 14767482510784806043  # Avalanche Fuji

        # Check if token is supported
        is_supported = dsc_transfer_hub.functions.isSupportedToken(token_address).call()
        if not is_supported:
            raise HTTPException(status_code=400, detail="Token not supported by DSCTransferHub")
        
        # Check if destination chain is allowlisted
        is_allowlisted = dsc_transfer_hub.functions.allowlistedChains(destination_chain_selector).call()
        if not is_allowlisted:
            raise HTTPException(status_code=400, detail="Destination chain not allowlisted")

        # Check sufficient deposits
        token_deposit = dsc_transfer_hub.functions.userTokenDeposits(public_address, token_address).call()
        if token_deposit < amount_in_wei:
            raise HTTPException(status_code=400, detail="Insufficient token deposit")

        # Check sufficient ETH for fees
        eth_deposit = dsc_transfer_hub.functions.userEthDeposits(public_address).call()
        if eth_deposit == 0:
            raise HTTPException(status_code=400, detail="Insufficient ETH deposit for fees")

        tx_hash, _ = build_tx(
            lambda: dsc_transfer_hub.functions.transferTokens(destination_chain_selector, receiver_address, token_address, amount_in_wei)
        )
        return {"tx_hash": tx_hash.hex()}
    except ContractLogicError as e:
        raise HTTPException(status_code=500, detail=f"Contract execution reverted: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contract execution failed: {str(e)}")

@app.post("/withdraw-deposits")
async def withdraw_deposits(data: WithdrawDepositsRequest):
    """Withdraw remaining tokens and ETH from DSCTransferHub"""
    try:
        token_address = Web3.to_checksum_address(data.token_address) if data.token_address else None
        
        # Check deposits
        token_balance = 0
        if token_address:
            is_supported = dsc_transfer_hub.functions.isSupportedToken(token_address).call()
            if not is_supported:
                raise HTTPException(status_code=400, detail="Token not supported by DSCTransferHub")
            token_balance = dsc_transfer_hub.functions.userTokenDeposits(public_address, token_address).call()
        
        eth_balance = dsc_transfer_hub.functions.userEthDeposits(public_address).call()
        
        if token_balance == 0 and eth_balance == 0:
            raise HTTPException(status_code=400, detail="Nothing to withdraw")
        
        if token_address:
            tx_hash, _ = build_tx(
                lambda: dsc_transfer_hub.functions.withdrawDeposits(token_address)
            )
            return {"tx_hash": tx_hash.hex()}
        else:
            raise HTTPException(status_code=400, detail="Token address required for withdrawal")
    except ContractLogicError as e:
        raise HTTPException(status_code=500, detail=f"Contract execution reverted: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))