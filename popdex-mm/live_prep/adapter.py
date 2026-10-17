"""PopDEX live order adapter (NOT wired into mm.py; mm.py still refuses non-shadow mode).
Signs with the AGENT key, timestamp nonce (ms), gasless (gasPrice 0).
Touches only orders whose clientOrderId carries the MM tag. Never cancelAllOrders / closeAllPositions.
Refs: /docs/smart-contract/Order, /docs/product-docs/chain/nonces, /docs/api/web3-rpc/Send-Transaction"""
import json, time, secrets
from web3 import Web3
from eth_account import Account
from order_params import pack

ORDER = "0x0000000000000000000000000000000000001000"
NETS = {"mainnet": ("https://api.popdex.xyz/api/v1/web3/rpc", 2184),
        "testnet": ("https://testnet-api.popdex.xyz/api/v1/web3/rpc", 34952)}
TAG = b"DDMM"
ABI = [
 {"name": "placeOrder", "type": "function", "stateMutability": "nonpayable", "outputs": [{"name": "success", "type": "bool"}],
  "inputs": [{"name": "account", "type": "address"}, {"name": "clientOrderId", "type": "bytes32"}, {"name": "symbolId", "type": "uint16"},
             {"name": "orderParams", "type": "bytes32"}, {"name": "price", "type": "uint256"}, {"name": "qty", "type": "uint256"},
             {"name": "slippage", "type": "uint256"}, {"name": "builder", "type": "address"}, {"name": "builderFeeRate", "type": "uint256"}]},
 {"name": "cancelOrder", "type": "function", "stateMutability": "nonpayable", "outputs": [{"name": "success", "type": "bool"}],
  "inputs": [{"name": "account", "type": "address"}, {"name": "orderId", "type": "uint128"}, {"name": "clientOrderId", "type": "bytes32"}]},
]
def to18(x): return int(round(float(x) * 1e6)) * 10**12
def new_coid():  # ASCII only (raw bytes rejected on-chain: "Client order ID format invalid"), right-padded with zeros
    return (TAG + (format(int(time.time() * 1000), "x") + secrets.token_hex(6)).encode()).ljust(32, b"\0")
def coid_str(coid): return coid.rstrip(b"\0").decode()
def is_ours(c):
    c = c or ""
    return c.startswith(TAG.decode()) or c.lower().removeprefix("0x").startswith(TAG.hex())

class PopdexAdapter:
    def __init__(s, account, agent_key_file, net="mainnet"):
        rpc, s.chain_id = NETS[net]
        s.w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
        s.account = Web3.to_checksum_address(account)
        s.agent = Account.from_key(json.load(open(agent_key_file))["key"])
        s.c = s.w3.eth.contract(address=ORDER, abi=ABI); s._last = 0
    def _nonce(s):
        n = max(int(time.time() * 1000), s._last + 1); s._last = n; return n
    def _send(s, fn, gas=2_000_000):
        tx = fn.build_transaction({"from": s.agent.address, "nonce": s._nonce(), "gas": gas, "gasPrice": 0, "chainId": s.chain_id})
        return s.w3.eth.send_raw_transaction(s.agent.sign_transaction(tx).raw_transaction).hex()
    def _place_fn(s, symbol_id, side, price, qty, reduce_only, coid):
        return s.c.functions.placeOrder(s.account, coid, symbol_id, pack(side=0 if side == "buy" else 1, tif=4, reduce_only=reduce_only),
                                        to18(price), to18(qty), 0, "0x" + "00" * 20, 0)
    def place_post_only(s, symbol_id, side, price, qty, reduce_only=False):
        coid = new_coid(); return coid, s._send(s._place_fn(symbol_id, side, price, qty, reduce_only, coid))
    def simulate_place(s, symbol_id, side, price, qty):  # eth_call only, no state change
        return s._place_fn(symbol_id, side, price, qty, False, new_coid()).call({"from": s.agent.address})
    def cancel_own(s, coid):
        if not coid.startswith(TAG): raise ValueError("refusing to cancel a non-MM order")
        return s._send(s.c.functions.cancelOrder(s.account, 0, coid))
