---
name: degen-desk-skill-map
description: "Use when deciding which Degen Desk skill or clawd category skill (and which sub-skill inside it) fits a request beyond the hourly report, and what it needs to run here: ready, a key, a CLI, a Mac, the owner's wallet, or reference only."
---
# Degen Desk skill map

The clawd category skills (`clawd-<category>` routers and their sub-skills) listed here come from the clawd pack. If they aren't installed yet, install them with `curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/install-skills.sh | bash` (installs into the skills library and never overwrites an existing skill). Until then, use the Degen Desk core skills and fetch.py.

Pick in this order: (1) free keyless sources first: Degen Desk core skills for reports, CA research and Telegram (`memecoin-trenches-report`, `memecoin-onchain-research`, `telegram-report-delivery`) and `/workspace/trenches/fetch.py` modes; (2) a clawd category skill (the `clawd-<category>` router, then the sub-skill it points to) for anything else, preferring `ready` ones; (3) anything that moves money (swap, order, launch, claim, payment, transfer, deposit) goes through `memecoin-trading-guardrails` first, every time, whatever the clawd skill says. Never route to a paid service (e.g. `clawd-wallets-payments/skills/pay`, `clawd-wallets-payments/skills/sponge-wallet`, paid APIs) unless the owner asks for it or free sources can't answer, and then only with approval. Skills whose remote hosts failed TLS when this map was made in Oct 2026 (Cheshire Terminal, funpump.ai, skills.x402.wtf, pons.family) are tagged `unreachable`: try once, and if it still fails say so instead of retrying; on-chain reads over public RPC still work. If a key, CLI or wallet is missing, say so and ask; never install, sign or spend without approval. Follow each clawd skill's "Running here" note for paths, tools and missing upstream pieces.

Tags: `ready` keyless, works now · `key: X` needs that key/account · `cli: Y` needs that CLI · `mac` macOS-only · `wallet` moves money (Phantom plugin or Coinbase connector + per-trade yes) · `ref` guide only · `unreachable: host` host failed when this map was made. `=>` = Degen Desk skill or fetch.py mode to use first.

**Layout (Oct 2026 consolidation).** The 204 Clawd skills are grouped into 17 category skills `clawd-<category>` (below). Each category's `SKILL.md` is a router; the full recipe of a sub-skill is `/home/box/agent-data/workflows/<category>/skills/<slug>/SKILL.reference.md`. A line `- <slug>` under a category means that path. Old names `clawd-<slug>` (from before the consolidation) mean the sub-skill with that slug.

## clawd-master: top index + Clawd/Musebook stack guide (1)
Router: `/home/box/agent-data/workflows/clawd-master/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-master/skills/<slug>/SKILL.reference.md`
- clawd: full Clawd stack guide + connectors; ref => all Degen Desk skills

## clawd-memecoin-pump: pump.fun & memecoin trading (16)
Router: `/home/box/agent-data/workflows/clawd-memecoin-pump/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-memecoin-pump/skills/<slug>/SKILL.reference.md`
- cheshire-terminal: Cheshire voice terminal dev; ref
- clawd-token-ops: $CLAWD token ops; wallet => fetch.py enrich
- clawd-trading-terminal: Cheshire $CLAWD trading surfaces; wallet
- dex-screener-scanner: DexScreener Solana screener; ready => fetch.py scan
- pump-admin-ops: authority/admin ops; wallet
- pump-bonding-curve: bonding-curve price/quote math; ready, ref => fetch.py enrich
- pump-claims-readonly: unclaimed rewards, creator vaults (read-only); cli: npm @nirholas/pump-sdk
- pump-fee-sharing: PumpFees BPS splits; wallet
- pump-token-incentives: PUMP reward claims; wallet
- pump-token-lifecycle: create to AMM migration flows; wallet
- pumpfun: router for the pump.fun suite; ref => memecoin-onchain-research
- pumpfun-analytics: curve state, graduation, price impact; ready => fetch.py enrich, quote
- pumpfun-fees: creator fee claims/splits; wallet
- pumpfun-launcher: launch a pump.fun token; wallet
- pumpfun-trading: pump.fun buy/sell; wallet => fetch.py quote first
- swarm-orchestrator: multi-bot pump trading swarms; wallet, key: HELIUS_RPC_URL, TELEGRAM_BOT_TOKEN, cli: SolanaOS core (unavailable)

## clawd-pump-devkit: pump.fun program & SDK developer kit (13)
Router: `/home/box/agent-data/workflows/clawd-pump-devkit/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-pump-devkit/skills/<slug>/SKILL.reference.md`
- pump-ai-agents: AGENTS/CLAUDE files for SDK repos; ref
- pump-build-release: SDK build and release; ref
- pump-fee-system: fee tiers, creator vault math; ref
- pump-mcp-server: build a pump MCP server; ref
- pump-rust-vanity: Rust vanity-address tooling; ref
- pump-sdk-core: pump SDK instruction builders; ref
- pump-security: SDK security practices; ref
- pump-shell-scripts: secure Bash tooling; ref
- pump-solana-architecture: program PDAs and account layouts; ref => fetch.py enrich (curve layout)
- pump-solana-dev: Anchor/SPL patterns used by pump; ref
- pump-solana-wallet: wallet generation guide (no local keys here); ref
- pump-testing: SDK test infrastructure; ref
- pump-ts-vanity: TS vanity-address tooling; ref

## clawd-spot-bots: spot swaps, LP & trading bots (10)
Router: `/home/box/agent-data/workflows/clawd-spot-bots/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-spot-bots/skills/<slug>/SKILL.reference.md`
- cheshire-noxa: NOXA DEX quotes/launch feed; wallet, cli: npm @x402solana/cheshire-noxa, unreachable: cheshireterminal.ai
- copy-trade: mirror a wallet (EVM); wallet
- dca-bot: recurring buys; wallet
- dflow-platform-fees: builder fees on DFlow routes; ref, key: DFLOW_API_KEY
- dflow-spot-trading: DFlow Solana swaps; wallet, key: DFLOW_API_KEY => fetch.py quote
- index-bot: weighted basket buys; wallet
- liquidity-planner: Uniswap LP plan + deep link; wallet
- lp-integration: Uniswap LP API; wallet, key: UNISWAP_API_KEY
- swap-integration: build Uniswap swaps into apps; ref, key: UNISWAP_API_KEY
- swap-planner: Uniswap swap plan + deep link; wallet

## clawd-perps-imperial: Imperial perpetuals (12)
Router: `/home/box/agent-data/workflows/clawd-perps-imperial/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-perps-imperial/skills/<slug>/SKILL.reference.md`
- imperial: Imperial entry point; wallet, key: IMPERIAL_API_KEY (wallet-signed JWT)
- imperial-execution-modes: observe/paper/live modes; ref
- imperial-grid-trading: grid ladders; wallet
- imperial-margin-operations: deposit/withdraw; wallet
- imperial-market-intel: funding, marks, depth, routes; ready => fetch.py backpack (funding)
- imperial-portfolio-intel: profile balances/positions; key: IMPERIAL_API_KEY
- imperial-position-management: reduce/close positions; wallet
- imperial-risk-management: pre-trade risk checks; ref
- imperial-skills-index: Imperial skill index; ref
- imperial-tpsl-management: TP/SL; wallet
- imperial-trade-execution: live market orders; wallet
- imperial-twap-execution: TWAP; wallet

## clawd-perps-vulcan: Phoenix perpetuals via the Vulcan CLI (18)
Router: `/home/box/agent-data/workflows/clawd-perps-vulcan/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-perps-vulcan/skills/<slug>/SKILL.reference.md`
- vulcan: Vulcan/Phoenix entry point; wallet, cli: vulcan
- vulcan-error-recovery: failure routing; ref
- vulcan-execution-modes: mode taxonomy; ref
- vulcan-grid-trading: grid orders; wallet, cli: vulcan
- vulcan-lot-size-calculator: notional to base lots; cli: vulcan, ref
- vulcan-margin-operations: collateral, leverage; wallet, cli: vulcan
- vulcan-market-intel: Phoenix tickers, book, funding; cli: vulcan => fetch.py backpack
- vulcan-onboarding: wallet, registration, collateral; wallet, cli: vulcan
- vulcan-portfolio-intel: margin, positions, PnL; cli: vulcan
- vulcan-position-management: close/reduce, TP/SL; wallet, cli: vulcan
- vulcan-quickstart: install + first paper trade; wallet, cli: vulcan
- vulcan-risk-management: liquidation distance, caps; ref
- vulcan-skills-index: Vulcan skill index; ref
- vulcan-ta-strategy: TA strategy runner; wallet, cli: vulcan
- vulcan-technical-analysis: RSI/MACD/etc on Phoenix; cli: vulcan
- vulcan-tpsl-management: TP/SL ladders; wallet, cli: vulcan
- vulcan-trade-execution: market/limit orders; wallet, cli: vulcan
- vulcan-twap-execution: TWAP runner; wallet, cli: vulcan

## lighter-perps: Lighter perp DEX (Degen Desk skill, 1)
Skill: `lighter-perps` · box script (reads, previews, paper): `/workspace/trenches/lighter.py` · owner's computer (live): `~/.degen-desk/lt` + `~/.degen-desk/desk_lighter.py`, set up with `lighter/install-local.sh` from the degen-desk repo · official kit: `~/.agents/skills/lighter-agent-kit`
- lighter-perps: reads (markets, book, funding, stats, positions), 1%-risk sizing and paper mode are `ready` anywhere; live trading runs only on the owner's own computer via machine-targeted Shell (Lighter blocks this box: restricted jurisdiction, code 20558; never a VPN or proxy): preview, exact-terms yes, then `lt place --approve CODE --live` once; key: owner's macOS Keychain item `degen-desk-lighter` (or `LIGHTER_API_PRIVATE_KEY` in their own shell profile on Linux/WSL), read by `lt` only for `--live`; gated by `memecoin-trading-guardrails` (Lighter section); withdraw/transfer hard-blocked => prefer this over Imperial/Vulcan when the owner says Lighter

## clawd-prediction-markets: prediction markets (DFlow / Kalshi) (5)
Router: `/home/box/agent-data/workflows/clawd-prediction-markets/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-prediction-markets/skills/<slug>/SKILL.reference.md`
- dflow-docs: DFlow docs/API index; ready
- dflow-kalshi-market-data: Kalshi book/trades via DFlow; key: DFLOW_API_KEY => fetch.py kalshi
- dflow-kalshi-market-scanner: Kalshi arb/movers scan; key: DFLOW_API_KEY => fetch.py kalshi
- dflow-kalshi-portfolio: wallet Kalshi positions; key: DFLOW_API_KEY
- dflow-kalshi-trading: buy/sell YES/NO; wallet, key: DFLOW_API_KEY => fetch.py kalshi first

## clawd-launchpads-agents: launchpads, agent identity & Robinhood Chain (22)
Router: `/home/box/agent-data/workflows/clawd-launchpads-agents/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-launchpads-agents/skills/<slug>/SKILL.reference.md`
- cheshire-agent-identity-registry: RH identity NFT reads; ready
- cheshire-agent-registries: RH agent registry pins; ready
- cheshire-agent-reputation-registry: RH reputation reads; ready
- cheshire-agent-validation-registry: RH validation reads; ready
- cheshire-api: Cheshire API/MCP; key: CHESHIRE_API_KEY, unreachable: cheshireterminal.ai
- cheshire-omni-mint: omnichain agent mint; wallet, cli: npm cheshire-terminal-agents, unreachable: cheshireterminal.ai, funpump.ai
- cheshire-zk-omni: ZK omni messenger; ref, unreachable: cheshireterminal.ai, funpump.ai
- clawd-agent-launchpad: build/launch/stake agents; wallet
- gateway-node-ops: SolanaOS gateway/nodes; ref, cli: npm solanaos
- google-agent-registry: A2A/MCP registry artifacts; ref
- pons-launch: RH fixed-supply launch; wallet, unreachable: pons.family
- posthog-cheshire: PostHog for Cheshire; ref, key: POSTHOG_API_KEY
- rh-bonded-launch: RH bonding-curve launch; wallet
- rh-crypto-agent: RH agent pack index; wallet, ref
- rh-launchpad-v3: RH Launchpad V3; wallet
- robinhood-agent-forge: register agent identities; wallet, key: CHESHIRE_API_KEY, unreachable: cheshireterminal.ai => fetch.py metaplex
- skillhub-onchain: publish skills on-chain; wallet, unreachable: skills.x402.wtf
- skills-store: Cheshire skills store index; wallet, ref, unreachable: cheshireterminal.ai, skills.x402.wtf
- solana-clawd: solana-clawd engine setup; ref, key: many (BIRDEYE, ANTHROPIC, X...)
- solana-clawd-agentic-commerce: Pay CLI agents, Genesis tokens; wallet => fetch.py metaplex
- solana-clawd-agents: agent catalog deploy/mint; wallet => fetch.py metaplex
- zk-omni-messaging: RH to Solana ZK messages; ref, unreachable: cheshireterminal.ai, funpump.ai

## clawd-wallets-payments: wallets, payments & x402 (9)
Router: `/home/box/agent-data/workflows/clawd-wallets-payments/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-wallets-payments/skills/<slug>/SKILL.reference.md`
- compressed-token: compressed SPL ops; wallet
- dflow-phantom-connect: Phantom Connect apps; ref
- dflow-proof-kyc: DFlow Proof KYC; ref
- pay: Pay CLI paid APIs (x402); wallet, cli: pay
- pay-with-any-token: pay HTTP 402 via Tempo/Uniswap; wallet, cli: tempo, cast
- pay-with-app: pay OKX APP 402s; wallet, key: UNISWAP_API_KEY
- phantom-wallet-mcp: Phantom wallet ops; wallet
- sponge-wallet: Sponge wallet + x402; wallet, key: SPONGE_API_KEY
- stripe: Stripe payments/MCP; wallet, key: STRIPE_SECRET_KEY

## clawd-chain-dev: Solana & EVM smart-contract development (16)
Router: `/home/box/agent-data/workflows/clawd-chain-dev/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-chain-dev/skills/<slug>/SKILL.reference.md`
- ask-mcp: DeepWiki repo Q&A; ready
- compressed-pda: compressed PDAs; ref
- deployer: deploy CCA auctions; wallet, cli: forge, cast (foundryup)
- magicblock: Ephemeral Rollups; ref, wallet
- solana-common-errors: common build errors; ref
- solana-dev: Solana dapps/Anchor; ref, cli: solana, anchor (curl installer)
- solana-formal-verification: Lean 4 proofs; ref, cli: lean4
- solana-ralphy-skill: autonomous Solana coding loop; ref
- solana-redpill-verifier: TEE verifier stack; ref
- solana-rent-free-dev: Light rent-free dev; ref
- testing: Light Protocol testing; ref, key: HELIUS_API_KEY
- v4-hook-generator: Uniswap v4 hooks; ref
- v4-sdk-integration: Uniswap v4 SDK; ref
- v4-security-foundations: v4 hook security; ref, cli: forge
- viem-integration: EVM reads/writes via viem; ref
- zk: ZK nullifier PDAs; ref

## clawd-research-productivity: research, notes & productivity (19)
Router: `/home/box/agent-data/workflows/clawd-research-productivity/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-research-productivity/skills/<slug>/SKILL.reference.md`
- apple-notes: Apple Notes; mac
- apple-reminders: Apple Reminders; mac
- bear-notes: Bear notes; mac
- blogwatcher: RSS/blog monitor; cli: blogwatcher (go install)
- find-skills: discover skills (skills.sh); cli: npx skills (npm)
- gemini: Gemini CLI Q&A; cli: gemini-cli (npm), key: Google login/key
- github: gh issues/PRs/runs; ready
- goplaces: Google Places CLI; cli: goplaces (brew/go), key: GOOGLE_PLACES_API_KEY
- local-places: Places proxy search; key: GOOGLE_PLACES_API_KEY
- nano-pdf: edit PDFs; cli: nano-pdf (uv/pip)
- notion: Notion pages/DBs; key: NOTION_KEY
- obsidian: Obsidian vaults; cli: obsidian-cli (brew/go)
- openrouter-models: model list, pricing; ready
- oracle: oracle prompt bundler; cli: oracle (npm), key: OPENAI_API_KEY
- session-logs: search past session logs; ref
- summarize: summarize URLs/videos; cli: summarize (npm/brew), key: an LLM key
- things-mac: Things 3; mac
- trello: Trello boards; key: TRELLO_API_KEY, TRELLO_TOKEN
- weather: weather (wttr.in, Open-Meteo); ready

## clawd-design-ui: UI & motion design for the web (7)
Router: `/home/box/agent-data/workflows/clawd-design-ui/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-design-ui/skills/<slug>/SKILL.reference.md`
- animation-vocabulary: name a motion effect; ref
- apple-design: Apple-style motion for web; ref
- emil-design-eng: UI polish philosophy; ref
- improve-animations: animation audit; ref
- review-animations: animation code review; ref
- shadcn: shadcn components; ref
- web-perf: Core Web Vitals; cli: Chrome DevTools MCP

## clawd-media-gen: media generation & processing (11)
Router: `/home/box/agent-data/workflows/clawd-media-gen/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-media-gen/skills/<slug>/SKILL.reference.md`
- gifgrep: GIF search; cli: gifgrep (go)
- nano-banana-pro: Gemini image gen/edit; key: GEMINI_API_KEY
- openai-image-gen: OpenAI image batches; key: OPENAI_API_KEY
- openai-whisper: local Whisper; cli: whisper (pip openai-whisper)
- openai-whisper-api: Whisper API transcription; key: OPENAI_API_KEY
- openrouter-images: OpenRouter image gen; key: OPENROUTER_API_KEY
- sag: ElevenLabs TTS; cli: sag (brew), key: ELEVENLABS_API_KEY
- sherpa-onnx-tts: offline TTS; cli: sherpa-onnx runtime + model
- songsee: audio spectrograms; cli: songsee (brew)
- video-frames: frames/clips via ffmpeg; ready
- youtube-clipper: clip YouTube videos; ready

## clawd-home-devices: cameras, speakers, lights & devices (8)
Router: `/home/box/agent-data/workflows/clawd-home-devices/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-home-devices/skills/<slug>/SKILL.reference.md`
- blucli: BluOS control (LAN); cli: blu (go)
- camsnap: RTSP camera snaps; cli: camsnap (brew)
- canvas: Clawdbot node canvas (not here); ref
- eightctl: Eight Sleep pods; cli: eightctl (go)
- openhue: Hue lights (LAN); cli: openhue (brew)
- peekaboo: macOS UI capture; mac
- sonoscli: Sonos control (LAN); cli: sonos (go)
- spotify-player: Spotify playback; cli: spogo/spotify_player

## clawd-cloud-workers: Cloudflare platform & Workers (9)
Router: `/home/box/agent-data/workflows/clawd-cloud-workers/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-cloud-workers/skills/<slug>/SKILL.reference.md`
- agents-sdk: Cloudflare Agents SDK; ref
- cloudflare: Cloudflare platform; ref
- cloudflare-email-service: CF email send/route; key: CLOUDFLARE_API_TOKEN
- cloudflare-one: Zero Trust/SASE; ref
- cloudflare-one-migrations: SASE migrations; ref
- durable-objects: Durable Objects; ref
- sandbox-sdk: Cloudflare sandboxes; ref
- workers-best-practices: Workers review; ref
- wrangler: deploy Workers; cli: wrangler (npm), key: CLOUDFLARE_API_TOKEN

## clawd-dev-tools: coding agents & developer tools (17)
Router: `/home/box/agent-data/workflows/clawd-dev-tools/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-dev-tools/skills/<slug>/SKILL.reference.md`
- 1password: 1Password CLI; cli: op (apt/brew)
- agent-browser: browser smoke tests; cli: agent-browser (npm)
- agent-desktop: macOS desktop automation; mac
- clawd-skills-installer: install skill packs; ref
- clawdex: dual-engine coding agent; cli: claude, codex (npm), key: BROWSER_USE_API_KEY etc.
- clawdhub: ClawdHub skill registry; cli: clawdhub (npm)
- coding-agent: run Codex/Claude Code; cli: claude/codex (npm), key: vendor keys
- create-agent-tui: scaffold agent TUI; ref, key: OPENROUTER_API_KEY
- forge: generate agent skills; ref
- mcporter: call MCP servers from CLI; cli: mcporter (npm)
- model-usage: CodexBar usage; mac
- openclawd-clawd-code-skill-main: drive Clawd Code via MCP; ref
- openrouter-agent-migration: sdk to agent migration; ref
- openrouter-oauth: Sign in with OpenRouter; ref
- openrouter-typescript-sdk: OpenRouter SDK reference; ref
- skill-creator: author skills; ref
- tmux: drive tmux sessions; ready

## clawd-messaging: messaging & communication connectors (11)
Router: `/home/box/agent-data/workflows/clawd-messaging/SKILL.md` · sub-skills: `/home/box/agent-data/workflows/clawd-messaging/skills/<slug>/SKILL.reference.md`
- bird: X CLI via cookies; cli: bird (npm) => built-in x tools
- bluebubbles: BlueBubbles channel plugin; mac, ref
- discord: Discord actions; key: Discord bot token
- food-order: reorder Foodora; wallet, cli: ordercli (go)
- gog: Google Workspace CLI; cli: gog (brew)
- himalaya: IMAP/SMTP email; cli: himalaya (apt/brew)
- imsg: iMessage/SMS; mac
- ordercli: Foodora order status; wallet, cli: ordercli (go)
- slack: Slack actions; key: Slack bot token
- voice-call: Clawdbot voice calls (not here); ref
- wacli: WhatsApp send/search; cli: wacli (go)

## Owner setup unlocks
- Phantom plugin (704) or Coinbase connector (68516158): the 58 `wallet` skills, always gated by `memecoin-trading-guardrails`. Solana flows sign in Phantom; EVM/Robinhood Chain/Uniswap flows need an EVM wallet the owner controls. Some also need a key or CLI.
- Keys: `DFLOW_API_KEY` 6 (DFlow spot, Kalshi data/scanner/portfolio/trading, platform fees); `IMPERIAL_API_KEY` 2 (Imperial entry + portfolio (wallet-signed JWT)); `UNISWAP_API_KEY` 3 (Uniswap swap/LP APIs, OKX 402 pay); `CHESHIRE_API_KEY` 2 (Cheshire API, agent forge); `OPENAI_API_KEY` 3 (image gen, Whisper API, oracle); `OPENROUTER_API_KEY` 2 (images, agent TUI); `GOOGLE_PLACES_API_KEY` 2 (places lookups); `CLOUDFLARE_API_TOKEN` 2 (wrangler, email service); one each: `HELIUS_API_KEY`, `HELIUS_RPC_URL` + `TELEGRAM_BOT_TOKEN` (swarm), `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `NOTION_KEY`, `TRELLO_API_KEY` + `TRELLO_TOKEN`, `STRIPE_SECRET_KEY`, `SPONGE_API_KEY`, `POSTHOG_API_KEY`, Discord and Slack bot tokens; LLM vendor keys for coding-agent, clawdex, summarize, gemini, solana-clawd.
- Lighter: the owner creates a sub-account + API key (slot 4–254) at app.lighter.xyz/apikeys, runs `lighter/install-local.sh` on their own computer, and stores the key themselves (macOS Keychain or their shell profile); never in chat or on this box. Reads and paper work without it. See `lighter-perps`.
- Vulcan CLI (Ellipsis-Labs GitHub install script, see `clawd-master`): 14 Phoenix perps skills; market data is keyless once installed, trading also needs a wallet.
- Other CLIs: 44 skills, each named on its line. Most install with npm, pip/uv or `go install` (node, uv and go are present); brew-only taps need a Linux build; SolanaOS core is unavailable. Ask before installing.
- Mac-only, cannot run here: 9 (apple-notes, apple-reminders, bear-notes, things-mac, peekaboo, agent-desktop, model-usage, imsg, bluebubbles).
- Keys, tokens and passwords go only through the secure secret form, never in chat, files or skills. Never ask for a seed phrase or private key.
