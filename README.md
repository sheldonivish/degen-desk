# Degen Desk

Free, keyless memecoin trenches research tools. Degen Desk is the data side of an AI "trenches desk" bot:

- **Hourly X-list report**: reads the X lists you choose, dedupes and filters the posts, pulls out every contract address (CA), prices it, flags concentration (one account pushing a coin), and keeps a 24h "most mentioned by distinct accounts" tally.
- **On-chain CA research**: pump.fun bonding curve and graduation %, mint/freeze authority, RugCheck (Solana) and GoPlus (EVM) checks, holder concentration and labelled risk flags.
- **Boost and launch scans**: DexScreener boosts and Musebook feeds, filtered and cross-checked against what your tracked accounts called; newest pump.fun launches.
- **Read-only market modes**: Jupiter quote with buy + sell-back round-trip loss, Raydium pools, Backpack markets and funding, tokenized stocks / RWA, Kalshi and Jupiter prediction markets, ORE mining, Metaplex agents.
- **Telegram delivery**: posts the report to one approved Telegram group, channel, topic or DM through your own bot, with clean formatting and safe splitting.
- **Optional Lighter perps** (`lighter.py`) and a **BTC autopilot for Lighter** (`autopilot/`) that run only on your own computer, with your own key, dry-run by default.

**Research first.** The report and research tools never build, sign or send a transaction, order or payment. The only parts that can place orders are the optional Lighter tools (`lighter.py` and `autopilot/`), and only on your own computer with an API key you store yourself; both default to dry-run. There is no wallet, no private key and no API key anywhere in this repo. Not financial advice.

## Install

On the machine the bot runs on (Python 3.9+, `git` optional):

```bash
curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/install.sh | bash
```

This installs to `/workspace/trenches` (set `TARGET=/some/dir` before `bash` to change it). It is safe to re-run: it updates the scripts and never touches your own data (`calls.jsonl`, `dex_cache.json`, `runs/`, `lists.txt`, `telegram/config.json`). It finishes with an offline smoke test and prints `OK`.

Then add the X lists you want to track to `lists.txt`, one list ID per line (the number at the end of `https://x.com/i/lists/<id>`).

Optional: report times default to Asia/Dubai. Set `DD_TZ` (for example `export DD_TZ=Asia/Kolkata`) and optionally `DD_TZ_LABEL` (for example `IST`) to change the timezone and the label printed after every time.

## Optional: the clawd skill pack (all of clawd's skills)

Degen Desk can also carry the full Musebook "Clawd" Solana skill pack: 203 skills plus the Clawd master guide (perps, swaps, launches, prediction markets, wallets, x402, Solana dev, media and more), and `degen-desk-skill-map`, the router that tells the bot which skill fits a job and what it needs to run.

The pack installs as **17 category skills**, not 204 separate ones, so it doesn't crowd other skills out of libraries that only load the first ~100: `clawd-master` (top index + master guide), `clawd-memecoin-pump`, `clawd-pump-devkit`, `clawd-spot-bots`, `clawd-perps-imperial`, `clawd-perps-vulcan`, `clawd-prediction-markets`, `clawd-launchpads-agents`, `clawd-wallets-payments`, `clawd-chain-dev`, `clawd-research-productivity`, `clawd-design-ui`, `clawd-media-gen`, `clawd-home-devices`, `clawd-cloud-workers`, `clawd-dev-tools`, `clawd-messaging`. Each one's `SKILL.md` is a router: when to use it, then a table of its sub-skills (what each does, whether it moves money, needs an API key, a CLI or a Mac, or depends on an unreachable host) with the exact path of the full recipe, `clawd-<category>/skills/<slug>/SKILL.reference.md`. Every original skill is kept in full there (its `SKILL.md` renamed to `SKILL.reference.md` so loaders don't register it separately).

```bash
curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/install-skills.sh | bash
```

- **Nothing from Musebook is stored in this repo.** The installer downloads the public bundle from `https://musebook.trade/clawd-skills.tar.gz` (v3.14.0, sha256 pinned), the master guide from `https://musebook.trade/SKILL.md`, and the two plugin manifests from `github.com/Solizardking/clawd-plugin` (pinned commit). It then adapts them on your machine with `clawd/build_pack.py`.
- **What the adaptation adds:** `clawd-<slug>` names, a "Use when ..." description, a "Running here (Degen Desk)" note (paths, keyless `fetch.py` substitutes, the secure secret form for keys), the money-moving guardrails block on the 58 skills that can trade, swap, launch, pay or sign (flags in `clawd/pack.tsv`), old skill names and links rewritten, and "Missing upstream pieces" notes where the bundle points to files it doesn't ship. `clawd/consolidate.py` then groups the skills by `clawd/categories.tsv`, writes the routers and rewrites paths and cross-references to the category layout.
- Installs into `/home/box/agent-data/workflows/clawd-<category>/`. Set `SKILLS_DIR=/some/dir` to change this, for example to test into a temp folder. It **never overwrites** an existing skill folder, so it is safe to re-run. Delete a folder first if you want to reinstall it. It finishes by checking the frontmatter of every category skill (name matches folder), that all 204 sub-skills are present and that no nested `SKILL.md` remains, and prints the counts and `OK`.
- Upgrading from the older layout (204 top-level `clawd-<slug>` folders): re-run with `DD_REMOVE_FLAT=1`. The installer tars the old folders and the old skill map into `$HOME` (or `DD_BACKUP_DIR`) and replaces them with the category layout. Without it, it only warns.
- If Musebook publishes a new bundle, the pinned checksum stops the install. Re-run with `CLAWD_ALLOW_UPSTREAM_CHANGE=1` to accept it.
- **Research first.** The pack is guidance and tooling. Every money-moving clawd skill runs only through `memecoin-trading-guardrails`: your own wallet (Phantom or Coinbase), and explicit approval of each trade's exact terms. Many skills also need an API key, a CLI or a Mac. `degen-desk-skill-map` lists what each one needs.
- The clawd skills keep their upstream authors' licenses. Several ship their own MIT or Apache-2.0 `LICENSE` file, and the plugin repo is MIT.

## Files

- `fetch.py`: the whole data pipeline. Python 3 standard library only: no installs, no keys, no wallet.
- `telegram/tg.py`: Telegram delivery (Markdown to Telegram HTML, splitting, safe sending). `telegram/test_tg.py`: offline tests. `telegram/SKILL.md`: the bot's Telegram run book.
- `lists.example.txt`: template for `lists.txt` (your X list IDs).
- `install-skills.sh`, `clawd/build_pack.py`, `clawd/pack.tsv`: the clawd pack installer, adapter and money-moving flags. `clawd/consolidate.py`, `clawd/categories.tsv`: groups the pack into the 17 category router skills (category, purpose, needs and money flag per sub-skill). `skills/degen-desk-skill-map/SKILL.md`: the skill router it installs.
- `autopilot/`: the optional BTC autopilot for Lighter (macOS launchd agent, dry-run by default). See [BTC autopilot](#btc-autopilot-for-lighter-optional-runs-on-your-mac) and [`autopilot/README.md`](autopilot/README.md).
- `lighter.py`: Lighter perps (keyless reads, paper, gated orders). `lighter/install-local.sh` and `lighter/lt`: set it up for live trading on your own computer. `skills/lighter-perps/SKILL.md`: the bot's Lighter run book. See [Lighter perps](#lighter-perps-optional-gated).
- Created on your machine and never committed: `calls.jsonl` (running call log, one row per post + CA), `dex_cache.json` (last good DexScreener lookup per CA, used only when DexScreener rate-limits), `runs/` (inputs and outputs of every run), `lists.txt`, `telegram/config.json`.

## Each hourly run

1. **Read X.** For each list ID in `lists.txt`, make one `search_posts_all` call with the X tools:
   - `query`: `list:<id> -is:retweet -is:reply`
   - `max_results`: 25, `sort_order`: `recency`
   - `start_time`: now minus 70 minutes (UTC ISO)
   - `expansions`: `author_id`, `user.fields`: `username,name`
   - `post.fields`: `created_at,author_id,public_metrics,referenced_tweets,entities,edit_history_tweet_ids`

   If a list returns 25 results it hit the cap: re-query it with two halves of the window (`start_time`/`end_time`) and keep both responses.
2. **Save the responses** to `runs/raw_<YYYYMMDD_HHMM>.json`:
   ```json
   {"window": {"start": "<ISO>", "end": "<ISO>"},
    "lists": {"<list_id>": [<response>, <response if split>]}}
   ```
3. **Run** `python3 fetch.py build --raw runs/raw_<stamp>.json`. It:
   - dedupes across lists, including edited-post duplicates;
   - drops replies/RTs and off-topic posts (no cashtag, no CA, no crypto/market keyword) and prints what it dropped;
   - extracts CAs (`chain:CA` prefixes and bare EVM/Solana addresses) and resolves them on DexScreener (best-liquidity pair: ticker, chain, MC or FDV, liquidity, 1h/24h change, pair age);
   - fetches BTC/ETH/SOL from Hyperliquid marks, falling back to CoinGecko and then Coinbase;
   - upserts every CA mention into `calls.jsonl` (re-runs never duplicate rows; `mcap_at_call` keeps the first snapshot);
   - computes the concentration flag (one account > 40% of CA mentions, at least 3 mentions) and the 24h most-mentioned ranking by distinct accounts;
   - enriches every CA on-chain (see below; `--no-enrich` skips it);
   - writes `runs/run_<stamp>.json` and ready-to-paste `runs/blocks_<stamp>.md`.
4. **Write the report** from the blocks: TL;DR, trenches sentiment, majors, accumulating/bullish, fading, calls & CAs, most mentioned (24h), and "Not financial advice."
   Style: no tables; link every account to `https://x.com/<handle>`; cite posts by their x.com status URL; Solana CAs ending in `pump` link to pump.fun, all other CAs to DexScreener; label every figure with its source and time; never write a number that isn't in a post or the blocks.
5. **Quiet-hour rule:** fewer than 5 on-topic posts and no CAs means a short note (TL;DR, majors line, "quiet hour") instead of a full report.

## Command list

All commands run from the install folder, use only the Python 3 standard library, need no keys or wallet, and only read public data. Every figure carries its source and time; anything a source doesn't return is left out. Each mode prints Markdown and saves `runs/<mode>_<stamp>.{md,json}`.

Hourly report
- `python3 fetch.py build --raw runs/raw_<stamp>.json [--no-append] [--no-enrich] [--hours 24]`: the report data blocks. `--no-append` leaves `calls.jsonl` untouched (for tests).
- `python3 fetch.py tally [--hours 24]`: most-mentioned CAs by distinct accounts from `calls.jsonl`.

Memecoin research
- `python3 fetch.py enrich [--ca <CA> --chain solana] [--hours 24]`: on-chain enrichment for the given CAs (repeat `--ca`), or every CA in `calls.jsonl` from the last N hours. EVM chains: ethereum, base, bsc, robinhood, arbitrum, ...
- `python3 fetch.py scan [--min-liq 10000 --min-mcap 25000 --min-buys 10 --chain all|solana --sort h1|h6|h24|vol24 --top 10]`: DexScreener boosts (latest + top), Musebook pulse boosts and live tokens, plus every called CA; filtered (liq >= $10K, MC >= $25K, >= 10 buys in 24h) and split into movers your tracked accounts also called (CA match), ticker-only matches, context movers, and called CAs that fail the filters.
- `python3 fetch.py launches [--limit 15]`: newest pump.fun launches from Musebook's public feed, with curve progress and DexScreener figures where a pair exists; flags launches your tracked accounts mentioned.
- `python3 fetch.py quote --ca <Solana mint> [--amount-sol 1] [--slippage-bps 100]`: Jupiter lite API: price, liquidity, 24h change; holders, organic score, top-holder %, dev holdings, authorities, 24h buys/sells; a read-only buy quote for N SOL and a sell-back quote, with price impact, route and the round-trip loss at quote time.
- `python3 fetch.py raydium --ca <Solana mint> [--limit 5]`: Raydium pools for the mint: type, pool id, TVL, price, 24h volume, fee, LP burned %.

Markets beyond memecoins
- `python3 fetch.py backpack [--type all|spot|perp] [--limit 15]`: top Backpack markets by 24h volume.
- `python3 fetch.py backpack --symbol SOL_USDC_PERP`: one market's ticker, spread and depth, and for perps mark/index price, funding, next funding time and open interest.
- `python3 fetch.py rwa [--limit 10]`: tokenized stocks and RWA: Backpack stock/index markets, Solana xStocks priced via Jupiter, Musebook RWA status.
- `python3 fetch.py kalshi [--query <text>] [--series KXBTCD] [--source both|kalshi|jupiter] [--provider kalshi|polymarket|bisonfi] [--limit 10] [--pages 5]`: prediction markets from Kalshi's public API and Jupiter Prediction (via Musebook's keyless research MCP). Crypto ladders: `KXBTCD`, `KXETHD`, `KXSOLD` (daily above/below), `KXBTC`, `KXSOLE` (ranges).
- `python3 fetch.py ore`: ORE v3 mining read straight from chain: current round, slots left, motherlode, SOL deployed, miners, last round's winner, ORE price.
- `python3 fetch.py metaplex [--query <name> | --address <agent mint>] [--launches] [--limit 10]`: Metaplex agent registry; `--launches` adds live Genesis launches.

Not wired, on purpose: swaps or orders on any venue, token or agent launches, fee claims, ORE deploying or claiming, x402 payments, and anything else that needs a key or a wallet or moves money.

## Data sources (all public and keyless)

- X posts: the X tools of the bot platform (`search_posts_all` on your lists).
- DexScreener API: pairs, boosts.
- Hyperliquid perp marks for BTC/ETH/SOL, falling back to CoinGecko and Coinbase.
- Solana public RPC (`api.mainnet-beta.solana.com`, fallback `solana-rpc.publicnode.com`): pump.fun bonding curve (program `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`), mint/freeze authority, ORE v3 accounts.
- pump.fun frontend API v3.
- Musebook (`musebook.trade`): decide snapshot, pulse, live tokens, RWA and Metaplex endpoints, public research MCP.
- RugCheck (Solana) and GoPlus (EVM, including Robinhood Chain 4663).
- Jupiter lite API, Raydium API v3, Backpack Exchange public API, Kalshi public API.

## On-chain enrichment

- **pump.fun curve** (Solana): on curve or graduated, % to graduation, curve MC in SOL (USD only with a labelled SOL price); pool after graduation from the pump.fun API. A mint with no curve account is reported as "not a pump.fun curve token".
- **Mint/freeze authority** (Solana) from the mint account.
- **Musebook decide snapshot** (Solana): liquidity across pools, 24h volume, buys/sells, top-holder %.
- **RugCheck** (Solana): normalised risk score, risks, LP locked %, top-10 holders excluding pools, insider wallets. Falls back to GoPlus Solana.
- **GoPlus** (EVM): honeypot, taxes, mintable, verified source, holders, top-10, LP locked.
- **Heuristic risk flags**, each printed with its rule: liq/MC < 5%, pair < 24h old, mint or freeze authority set, top-10 > 30%, RugCheck danger or rugged, GoPlus honeypot / can't sell / mintable / hidden owner / pausable / tax > 10%.

## Telegram setup (summary)

Full run book: `telegram/SKILL.md`.

1. In Telegram, open @BotFather, send `/newbot`, pick a name and a username ending in `bot`. BotFather gives you a token.
2. Save the token as the `TELEGRAM_BOT_TOKEN` environment variable / secret on the bot platform. Never paste it into chat or a file. If it leaks, `/revoke` it in @BotFather.
3. Add the bot to your group (member is enough), channel (admin with "Post messages"), or open it and press Start for a DM.
4. Send `/start@<yourbot>` in the group (privacy mode hides plain messages), then run `python3 telegram/tg.py chats` to find the chat id.
5. Approve the destination and save it: `python3 telegram/tg.py config --chat <id> [--thread <topic id>] --enable`.
6. Preview with `python3 telegram/tg.py send --file <report.md> --dry-run`, then send with `python3 telegram/tg.py send --file <report.md> --require "Not financial advice"`.
7. Pause anytime: `python3 telegram/tg.py config --disable`.

`tg.py` only posts to the one chat saved in `telegram/config.json`, refuses to send while `enabled` is false, reads the token only from the environment and scrubs it from errors. Run `python3 telegram/test_tg.py` for the offline tests.

## Known limits

- These are free public APIs on a shared IP: DexScreener, Hyperliquid, CoinGecko, Jupiter and the Solana public RPC sometimes rate-limit. The script retries with backoff, falls back to cached DexScreener data (labelled with its time) and to other price sources, and otherwise says plainly that data is unavailable.
- The Musebook snapshot can take up to ~45s; a full `build` with enrichment usually takes 10 to 60s and can reach ~3 min when DexScreener throttles.
- GoPlus "LP locked" reads 0% on pools without an LP token (Uniswap v4 style): treat it as "not shown locked", not "unlocked".
- RugCheck's score and the risk flags are heuristics, not safety guarantees.
- `mcap_at_call` is the market cap when the run fetched it (within about 70 minutes of the post), not at the exact second of the post.
- Only CA mentions are tallied; cashtag-only shills appear in the report but not the tally.
- The off-topic keyword filter is a heuristic; check the printed dropped list if a big post is missing.
- X returns at most ~280 characters of long posts.

## Disclaimer

Degen Desk is a research tool. Memecoins are extremely risky and most go to zero. Nothing it outputs is a recommendation to buy or sell anything, and third-party data can be wrong, late or manipulated. Do your own research. **Not financial advice.**

License: MIT, (c) 2026 BeingInvested.

## Lighter perps (optional, gated)

`lighter.py` adds Lighter (lighter.xyz) perps: keyless reads, 1%-risk sizing, paper trading, and gated live orders (preview the exact terms, approve, send once). Risk is hard-capped at 1% of equity per trade, every entry carries a reduce-only stop, and withdraw, transfer, account mode, collateral and close-all are hard-blocked. Skill: [`skills/lighter-perps/SKILL.md`](skills/lighter-perps/SKILL.md).

**Where it runs.** Lighter rejects orders from restricted jurisdictions (`restricted jurisdiction`, code 20558), and that includes many cloud servers, so a bot's cloud box can read and paper-trade but can't place orders. Live trading runs on **your own computer**, and only if Lighter's terms allow your location (https://lighter.xyz/terms: the US, Canada, UK and others are restricted). Don't use a VPN or proxy to get around it.

**Set up your computer (macOS, Linux, or Windows via WSL):**

1. In Lighter, make a sub-account that holds only your trading money, switch to it, and create an API key in slot 4–254 at https://app.lighter.xyz/apikeys. Note the account index and slot (they aren't secret). Lighter has no trade-only key: an API key can also make secure withdrawals to your own wallet, so keep only trading money in that sub-account.
2. Install (no key involved):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/lighter/install-local.sh | bash -s -- --account <INDEX> --slot <SLOT>
   ```
   It installs Lighter's official agent kit (code only; its key prompt is skipped) to `~/.agents/skills/lighter-agent-kit`, puts the script at `~/.degen-desk/desk_lighter.py` (not `lighter.py`, which would shadow the SDK) with the `~/.degen-desk/lt` runner, and runs a keyless read. It never takes a key.
3. Store the API private key yourself:
   - macOS Keychain: `security add-generic-password -U -a lighter -s degen-desk-lighter -w` (paste the key twice; nothing shows).
   - Linux/WSL: add `export LIGHTER_API_PRIVATE_KEY=...` to your own `~/.bashrc` or `~/.zshrc` in an editor, then `chmod 600` it.
   `lt` loads the key only for commands with `--live`. Never paste it in chat, and never share a seed phrase or wallet private key.
4. Check it (sends nothing): `~/.degen-desk/lt keycheck --live`.

**Use it** (your bot can run these on your computer, with your approval of each command):

- Reads: `lt markets --search SOL | book SOL | funding SOL | stats SOL | positions | account --index N`
- Paper: `lt paper init --collateral 1000`, then `lt place --approve CODE --paper`
- Trade:
  1. `lt preview open SOL --side long --stop 107.2 [--tp 110]` shows the exact terms and a 5-minute code.
  2. You say yes to those exact terms.
  3. `lt place --approve CODE --live` sends once, never retries, and reads the account back.
  4. `preview close` and `preview cancel` work the same way.

On a cloud box, `python3 lighter.py ...` does the same reads, previews and paper trades without a key.

Referral link (the template author's; disclosed): https://app.lighter.xyz/?ref=SHELDON. Not financial advice.

## BTC autopilot for Lighter (optional, runs on your Mac)

`autopilot/` is an unattended BTC-perp bot for Lighter built from multi-timeframe smart-money-concepts (SMC) rules from a trading course (setups A, G and RIMC on a 4h / 15m / 3m stack). When a setup fires it sends one grouped order: entry + reduce-only stop + reduce-only take-profit. Full guide, backtest and risks: [`autopilot/README.md`](autopilot/README.md).

- **Honest numbers:** BTC only. Out-of-sample (19 Jun to 7 Oct 2026) at 1% risk: 38 trades, profit factor about 2.7, max drawdown -3.4%. The same rules failed on ETH, 2023 was negative, and 38 trades is a small sample. It is not scalping: expect about 1-2 trades a week, held hours up to a day.
- **Guardrails:** 1% risk per trade by default (2% hard ceiling), 3x leverage cap, one position, exchange-side stop + TP on every entry, -4% daily loss stop, -15% drawdown pause, kill switch, reconcile on restart. **Dry-run by default**; live needs `install.sh --live`.
- **Where:** your own Mac, after the Lighter setup above (sub-account, API key in your Keychain, `lighter/install-local.sh`). Lighter blocks cloud servers; never use a VPN or proxy.
- **Install (dry-run):** `curl -fsSL https://github.com/sheldonivish/degen-desk/archive/refs/heads/main.tar.gz | tar xz -C /tmp && bash /tmp/degen-desk-main/autopilot/install.sh`
- **Stop:** `~/.degen-desk/autopilot/venv/bin/python3 ~/.degen-desk/autopilot/autopilot.py stop` (cancels BTC orders, closes the BTC position, stays stopped), or `bash ~/.degen-desk/autopilot/uninstall.sh`.

Not financial advice. It can lose money.

## Changelog

- **2026-10-09:** Added `autopilot/`, a BTC autopilot for Lighter (multi-timeframe SMC setups A, G and RIMC, backtested Feb 2022 to Oct 2026) with 1% default risk, 3x leverage cap, exchange-side stop + TP on every entry, daily stop, drawdown pause, kill switch and a one-command macOS installer (dry-run by default). Fixes in the autopilot's Lighter client: the signer client is created inside an event loop, the active-orders read passes auth correctly, and the installer no longer runs a key check. `skills/lighter-perps` gained an autopilot section.
- **2026-10-08 to 09:** Lighter perps (`lighter.py`, `lighter/install-local.sh`, `lt` runner, `skills/lighter-perps`), template v3 support, clawd pack as 17 category skills.
