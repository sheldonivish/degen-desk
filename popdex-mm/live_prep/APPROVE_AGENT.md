# Approve the Degen Desk MM agent on PopDEX (one time, signed by the owner)

What it does: authorizes a trade-only agent key that lives on the server. It can place, cancel and modify orders
for the owner's account. It CANNOT withdraw or transfer funds (PopDEX docs: product-docs/chain/agent-key).
Revoke any time: call revokeAgent(agent) from the main wallet.

| Field | Value |
|---|---|
| Network | Morph Tachyon mainnet, chainId 2184 (0x888) |
| RPC | https://app.popdex.xyz/api/v1/web3/rpc |
| Explorer | https://app.popdex.xyz/explorer |
| From | the owner's main PopDEX wallet |
| To (Account precompile) | 0x0000000000000000000000000000000000001008 |
| Value / gas | 0 / none: the chain is gasless (gas price 0) |
| Function | approveAgent(agent, delegator=main, name=0x0, expiresAt=0 (never), initialNonce=now ms, isGlobal=false), selector 0xd4c647da |

## Steps
1. On the server: `python live_prep/approve_agent.py --gen` (new agent key, chmod 600, address printed, key never printed).
   Never reuse or overwrite an agent key (nonce replay risk).
2. `python live_prep/approve_agent.py --html <MAIN_WALLET>` writes `sign_approve.html` with both public addresses.
3. Send the page to the owner. They open it in the browser with MetaMask or Rabby (serving it from `http://localhost`
   on their own computer helps if the extension won't inject into `file://`), click Connect, pick the main wallet,
   approve the network switch/add, confirm. The page prints a tx hash.
4. Verify: `GET https://api.popdex.xyz/api/v1/account/<MAIN_WALLET>/agents` lists the agent address. The web app's own
   session key (`UI_app.popdex.xyz`) is normal; the max is 10 agents.
5. The deposit must be credited before approveAgent. The main private key never leaves the owner's wallet.

A raw-calldata fallback is `--tx <MAIN_WALLET>`; it is valid only for about an hour because initialNonce must be > now - 1h.
