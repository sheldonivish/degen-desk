#!/usr/bin/env python3
"""PREPARED FOR LATER - DO NOT RUN without the user's explicit go-ahead.
Step 1 (--gen): create a brand-new agent key on the VPS (saved chmod 600, never printed).
Step 2 (--tx MAIN_WALLET): print the UNSIGNED approveAgent call for the user to sign
        in their own wallet (main private key never touches this server).
Step 2b (--html MAIN_WALLET): write sign_approve.html (from sign_approve.template.html) with the main wallet and the
        agent address filled in; the owner opens it in the browser that has MetaMask/Rabby and confirms (gas price 0).
Docs: /docs/product-docs/onboarding/how-to-trade-via-api, /docs/smart-contract/Account
Requires: pip install eth-account web3. Deposit must be credited BEFORE approveAgent."""
import argparse, json, os, time, stat
ACCOUNT = "0x0000000000000000000000000000000000001008"
RPC = "https://app.popdex.xyz/api/v1/web3/rpc"; CHAIN_ID = 2184
KEYF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "secrets", "agent_key.json")
ABI = [{"name": "approveAgent", "type": "function", "stateMutability": "nonpayable", "outputs": [],
        "inputs": [{"name": "agent", "type": "address"}, {"name": "delegator", "type": "address"},
                   {"name": "name", "type": "bytes32"}, {"name": "expiresAt", "type": "uint64"},
                   {"name": "initialNonce", "type": "uint64"}, {"name": "isGlobal", "type": "bool"}]}]
ap = argparse.ArgumentParser(); ap.add_argument("--gen", action="store_true"); ap.add_argument("--tx"); ap.add_argument("--html")
a = ap.parse_args()
if a.gen:
    from eth_account import Account
    if os.path.exists(KEYF): raise SystemExit("agent key already exists; never reuse/overwrite (replay risk)")
    os.makedirs(os.path.dirname(KEYF), mode=0o700, exist_ok=True)
    acct = Account.create()
    with open(KEYF, "w") as f: json.dump({"address": acct.address, "key": acct.key.hex()}, f)
    os.chmod(KEYF, stat.S_IRUSR | stat.S_IWUSR); print("agent address:", acct.address)
if a.tx:
    from web3 import Web3
    agent = json.load(open(KEYF))["address"]
    c = Web3().eth.contract(address=ACCOUNT, abi=ABI)
    data = c.encode_abi("approveAgent", args=[Web3.to_checksum_address(agent), Web3.to_checksum_address(a.tx),
                        b"\x00" * 32, 0, int(time.time() * 1000), False])
    print(json.dumps({"chainId": CHAIN_ID, "rpc": RPC, "from": a.tx, "to": ACCOUNT, "value": 0, "data": data}, indent=1))
    print("Sign+send this from the MAIN wallet (e.g. MetaMask with custom network chainId 2184, RPC above).")
if a.html:
    here = os.path.dirname(os.path.abspath(__file__))
    agent = json.load(open(KEYF))["address"]
    t = open(os.path.join(here, "sign_approve.template.html")).read()
    out = os.path.join(here, "sign_approve.html")
    open(out, "w").write(t.replace("__MAIN_WALLET__", a.html).replace("__AGENT_ADDRESS__", agent))
    print("wrote", out, "- send it to the owner; it holds only public addresses, no key")
