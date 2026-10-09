---
name: lighter-perps
description: >-
  Use when trading, scalping or checking perps on Lighter (lighter.xyz /
  zkLighter): prices, order books, funding, positions, practice (paper)
  trades, 1%-risk position sizing, setting up Lighter on the owner's own
  computer, or placing, closing or cancelling a Lighter order through the gated
  preview, approve, place flow.
---
# Lighter perps (Degen Desk)

Lighter is a zero-fee (Standard tier) perp DEX. Degen Desk trades it only through its gated script (`lighter.py` from github.com/sheldonivish/degen-desk), which wraps the SDK vendored by Lighter's official agent kit (`~/.agents/skills/lighter-agent-kit`, github.com/elliottech/lighter-agent-kit). The owner never risks more than **1% of the account per trade**; the script hard-caps that.

Anything that moves money follows `memecoin-trading-guardrails` first (Lighter section). A stored key is capability, not authority.

## 0. Where it runs (read first)
Lighter rejects sends from restricted jurisdictions, and that includes this bot's cloud computer: a live send from here fails with `restricted jurisdiction` (code 20558). So:
- **This computer (the box):** keyless reads, sizing, previews, dry-runs and paper trades only, with `python3 /workspace/trenches/lighter.py ...` (install it with the Degen Desk `install.sh` if missing). Never store a Lighter key here and never run `--live` here.
- **The owner's own computer:** live trading. It runs `~/.degen-desk/lt ...` (a runner around `~/.degen-desk/desk_lighter.py`) through machine-targeted Shell: call ListMachines, use the owner's connected desktop (default to the one their latest message came from), and the owner approves each command there.
- Only where Lighter's terms allow the owner's location (https://lighter.xyz/terms; the US, Canada, UK and others are barred). **Never suggest or use a VPN, proxy or remote host to get around the block.** If the owner is restricted, stay read-only and paper, or prepare the exact order for them to place in the Lighter app themselves.
- Preview and place on the **same** computer: the approval code lives in that computer's `~/.degen-desk/lighter/pending.json`.

## 1. Owner's computer setup (one time)
1. Lighter account: the template author's referral link is https://app.lighter.xyz/?ref=SHELDON (say it's a referral link). Connect the wallet, make a **sub-account** holding only trading money, fund it with USDC.
2. Switch to that sub-account, open https://app.lighter.xyz/apikeys and create an API key in **slot 4–254** (0–3 are Lighter's own apps). The wallet signs once; the private key is shown once.
3. Install (no key involved; the bot may run it on their computer, or they paste it in Terminal):
   `curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/lighter/install-local.sh | bash -s -- --account <INDEX> --slot <SLOT>`
   It installs the official kit (code only, skips the kit's key prompt), downloads the script as `~/.degen-desk/desk_lighter.py` and the `~/.degen-desk/lt` runner with the account index and slot filled in, and runs a keyless read. The account index and slot aren't secret; ask in chat (or look the index up from their wallet address: `lt account --l1 0x...`). A kit already installed with Lighter's own one-liner is kept (its key prompt should have been skipped).
   - Never name the script `lighter.py` on that computer: it shadows the SDK's `lighter` package. The runner refuses if it sees one.
4. Key, entered **by the owner, never through chat or the bot's shell**:
   - macOS: in their own Terminal, `security add-generic-password -U -a lighter -s degen-desk-lighter -w`, pasting the key twice (hidden). `lt` reads it with `security find-generic-password -s degen-desk-lighter -a lighter -w` **only when `--live` is passed**; the first time macOS may ask, so tell them to click Always Allow.
   - Linux or Windows (WSL): they add `export LIGHTER_API_PRIVATE_KEY=...` to their own shell profile (`~/.bashrc` or `~/.zshrc`, chmod 600) in an editor. `lt` reads only that line, only for `--live`.
   - Never take the key in chat, files, skills, memory or the kit's `credentials`/`lighter-config`. Never echo it. Never ask for a seed phrase or wallet private key.
5. Check (sends nothing): `~/.degen-desk/lt keycheck --live` confirms the key matches the account and slot; then `lt account --index <INDEX>` for balance and positions.
6. Paper first, then one tiny live test the owner approves, then normal size.
7. Rotate or revoke: the owner registers a new key over the slot (API-keys page), re-runs the Keychain command (or edits the profile line), re-runs the installer if the slot changed, then `lt keycheck --live`.

## 2. Reads (keyless; box or owner's computer)
`lighter.py markets [--search SOL]` · `book SOL --limit 5` · `funding SOL` (vs Binance/Bybit/Hyperliquid) · `stats SOL` · `positions [--index N]` · `account --index N | --l1 0x...`. On the owner's computer use `~/.degen-desk/lt <same args>` (the index is preset). More: the kit's `scripts/query.py`. Research only, no buy/sell advice.

## 3. Paper and sizing (no key)
`paper init --collateral 1000 --tier standard`, then `paper status|positions|trades|reset`. A previewed entry fills on paper with `place --approve CODE --paper` (taker-only, no stop/TP/funding/impact, so results are optimistic). `size SOL --side long --equity 1000 --entry 108.3 --stop 107.2` gives size = 1% of equity ÷ stop distance, notional, leverage and minimum checks.

## 4. Gated trading (owner's computer, via `~/.degen-desk/lt`)
1. **Preview** (nothing sent): `lt preview open SOL --side long --stop 107.2 [--tp 110] [--entry market|limit --price P] [--leverage 3] [--margin cross|isolated] [--risk-pct 1]`. It shows size, worst entry, the **required reduce-only stop** (trigger and worst fill), TP, leverage, notional and **max loss**, refuses anything over 1% of equity, and returns a code valid 5 minutes. `preview close SOL [--size N]` (reduce-only IOC) and `preview cancel SOL --order-index N | --all` work the same way.
2. **Show every term and the expiry time.** Wait for an explicit yes to those exact terms. A past yes, report, alert or schedule is not approval. If anything changes, preview again.
3. Optional dry-run: `lt place --approve CODE` prints what it would sign.
4. **Live, once:** `lt place --approve CODE --live`. It refuses if the account differs or price moved past the worst entry, burns the code, sends once (leverage update, then entry + stop [+ TP] as one group), reads the account back and **never retries**. Accepted is not filled: report the position it read back. On failure, say what failed and preview again; never resend. A `20558` / restricted-jurisdiction failure means wrong computer or location (section 0), never a reason to reroute.
- **Hard-blocked:** withdraw, transfer, account mode, collateral, fast-withdraw, change-api-key, sub-accounts and close-all. Don't use the kit's `trade.py` (it signs with no preview); point the owner to the Lighter app.
- Logs (`~/.degen-desk/lighter/orders.log`) hold only order ids and tx hashes.

## 6. BTC autopilot (optional, owner's Mac only)
An unattended BTC bot, `autopilot/` in the Degen Desk repo (guide: `autopilot/README.md`). It runs multi-timeframe SMC setups (A, G, RIMC on 4h/15m/3m) as a launchd agent on the owner's Mac and sends one grouped order per signal: entry + reduce-only stop + TP. Backtest: BTC only, OOS 38 trades, PF ~2.7; ETH failed; about 1–2 trades a week, not scalping. Say this plainly; never promise returns.
- Needs sections 1.1–1.4 done first (it reads the account index and slot from `~/.degen-desk/lt`, the key from the Keychain only in live mode).
- Install (dry-run, sends nothing): `curl -fsSL https://github.com/sheldonivish/degen-desk/archive/refs/heads/main.tar.gz | tar xz -C /tmp && bash /tmp/degen-desk-main/autopilot/install.sh`. Live only when the owner explicitly asks for live autopilot after seeing the risks: `bash /tmp/degen-desk-main/autopilot/install.sh --live`.
- Guardrails: 1% risk/trade by default (hard ceiling 2%), 3x leverage cap, one position, -4% daily stop, -15% drawdown pause, 24h max hold.
- Check: `~/.degen-desk/autopilot/venv/bin/python3 ~/.degen-desk/autopilot/autopilot.py status`. Stop (kill switch, closes the BTC position): `... autopilot.py stop`; `pause` / `resume`; remove: `bash ~/.degen-desk/autopilot/uninstall.sh`.
- Turning the autopilot on is the owner's standing approval for its own trades within these limits; it never replaces the preview → approve flow for manual orders. Never raise risk above the ceiling or disable a guardrail on request without restating the risk and getting an explicit yes.

## 5. Risks (say them plainly)
- **No trade-only key exists.** A Lighter API key can trade, cancel, change leverage and margin, move funds between the owner's own accounts and make secure withdrawals (to the owner's own wallet only). Anyone with the key could trade the account to zero, so keep only trading money in that sub-account.
- Orders are final, leverage can liquidate, and stops can slip or gap in fast markets.
- Standard tier: 300ms taker/cancel delay, 60 requests a minute.
- Shared or community use is research-only: "Not financial advice".

Docs: https://apidocs.lighter.xyz/docs/get-started · /docs/api-keys · /docs/trading.md · https://lighter.xyz/terms
