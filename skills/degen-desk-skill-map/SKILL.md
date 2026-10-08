---
name: degen-desk-skill-map
description: "Use when deciding which Degen Desk or clawd-* skill fits a request beyond the hourly report, and what it needs to run here: ready, a key, a CLI, a Mac, the owner's wallet, or reference only."
---
# Degen Desk skill map

The clawd-* skills listed here come from the clawd pack. If they aren't installed yet, install them with `curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/install-skills.sh | bash` (installs into the skills library and never overwrites an existing skill). Until then, use the Degen Desk core skills and fetch.py.

Pick in this order: (1) free keyless sources first: Degen Desk core skills for reports, CA research and Telegram (`memecoin-trenches-report`, `memecoin-onchain-research`, `telegram-report-delivery`) and `/workspace/trenches/fetch.py` modes; (2) a clawd-* skill for anything else, preferring `ready` ones; (3) anything that moves money (swap, order, launch, claim, payment, transfer, deposit) goes through `memecoin-trading-guardrails` first, every time, whatever the clawd skill says. Never route to a paid service (e.g. `clawd-pay`, `clawd-sponge-wallet`, paid APIs) unless the owner asks for it or free sources can't answer, and then only with approval. Skills whose remote hosts failed TLS when this map was made in Oct 2026 (Cheshire Terminal, funpump.ai, skills.x402.wtf, pons.family) are tagged `unreachable`: try once, and if it still fails say so instead of retrying; on-chain reads over public RPC still work. If a key, CLI or wallet is missing, say so and ask; never install, sign or spend without approval. Follow each clawd skill's "Running here" note for paths, tools and missing upstream pieces.

Tags: `ready` keyless, works now · `key: X` needs that key/account · `cli: Y` needs that CLI · `mac` macOS-only · `wallet` moves money (Phantom plugin or Coinbase connector + per-trade yes) · `ref` guide only · `unreachable: host` host failed when this map was made. `=>` = Degen Desk skill or fetch.py mode to use first.

## Pump.fun & memecoins (29)
- clawd-dex-screener-scanner: DexScreener Solana screener; ready => fetch.py scan
- clawd-pumpfun: router for the pump.fun suite; ref => memecoin-onchain-research
- clawd-pumpfun-analytics: curve state, graduation, price impact; ready => fetch.py enrich, quote
- clawd-pump-bonding-curve: bonding-curve price/quote math; ready, ref => fetch.py enrich
- clawd-pump-claims-readonly: unclaimed rewards, creator vaults (read-only); cli: npm @nirholas/pump-sdk
- clawd-pump-fee-system: fee tiers, creator vault math; ref
- clawd-pump-sdk-core: pump SDK instruction builders; ref
- clawd-pump-solana-architecture: program PDAs and account layouts; ref => fetch.py enrich (curve layout)
- clawd-pump-solana-dev: Anchor/SPL patterns used by pump; ref
- clawd-pump-security: SDK security practices; ref
- clawd-pump-testing: SDK test infrastructure; ref
- clawd-pump-build-release: SDK build and release; ref
- clawd-pump-shell-scripts: secure Bash tooling; ref
- clawd-pump-ai-agents: AGENTS/CLAUDE files for SDK repos; ref
- clawd-pump-mcp-server: build a pump MCP server; ref
- clawd-pump-rust-vanity: Rust vanity-address tooling; ref
- clawd-pump-ts-vanity: TS vanity-address tooling; ref
- clawd-pump-solana-wallet: wallet generation guide (no local keys here); ref
- clawd-pumpfun-trading: pump.fun buy/sell; wallet => fetch.py quote first
- clawd-pumpfun-launcher: launch a pump.fun token; wallet
- clawd-pumpfun-fees: creator fee claims/splits; wallet
- clawd-pump-fee-sharing: PumpFees BPS splits; wallet
- clawd-pump-token-incentives: PUMP reward claims; wallet
- clawd-pump-token-lifecycle: create to AMM migration flows; wallet
- clawd-pump-admin-ops: authority/admin ops; wallet
- clawd-swarm-orchestrator: multi-bot pump trading swarms; wallet, key: HELIUS_RPC_URL, TELEGRAM_BOT_TOKEN, cli: SolanaOS core (unavailable)
- clawd-clawd-token-ops: $CLAWD token ops; wallet => fetch.py enrich
- clawd-clawd-trading-terminal: Cheshire $CLAWD trading surfaces; wallet
- clawd-cheshire-terminal: Cheshire voice terminal dev; ref

## Spot swaps, DCA & LP (10)
- clawd-dflow-spot-trading: DFlow Solana swaps; wallet, key: DFLOW_API_KEY => fetch.py quote
- clawd-swap-planner: Uniswap swap plan + deep link; wallet
- clawd-swap-integration: build Uniswap swaps into apps; ref, key: UNISWAP_API_KEY
- clawd-copy-trade: mirror a wallet (EVM); wallet
- clawd-dca-bot: recurring buys; wallet
- clawd-index-bot: weighted basket buys; wallet
- clawd-liquidity-planner: Uniswap LP plan + deep link; wallet
- clawd-lp-integration: Uniswap LP API; wallet, key: UNISWAP_API_KEY
- clawd-dflow-platform-fees: builder fees on DFlow routes; ref, key: DFLOW_API_KEY
- clawd-cheshire-noxa: NOXA DEX quotes/launch feed; wallet, cli: npm @x402solana/cheshire-noxa, unreachable: cheshireterminal.ai

## Perps (Imperial, Vulcan/Phoenix) (30)
- clawd-imperial: Imperial entry point; wallet, key: IMPERIAL_API_KEY (wallet-signed JWT)
- clawd-imperial-skills-index: Imperial skill index; ref
- clawd-imperial-execution-modes: observe/paper/live modes; ref
- clawd-imperial-market-intel: funding, marks, depth, routes; ready => fetch.py backpack (funding)
- clawd-imperial-portfolio-intel: profile balances/positions; key: IMPERIAL_API_KEY
- clawd-imperial-risk-management: pre-trade risk checks; ref
- clawd-imperial-trade-execution: live market orders; wallet
- clawd-imperial-position-management: reduce/close positions; wallet
- clawd-imperial-margin-operations: deposit/withdraw; wallet
- clawd-imperial-tpsl-management: TP/SL; wallet
- clawd-imperial-twap-execution: TWAP; wallet
- clawd-imperial-grid-trading: grid ladders; wallet
- clawd-vulcan: Vulcan/Phoenix entry point; wallet, cli: vulcan
- clawd-vulcan-skills-index: Vulcan skill index; ref
- clawd-vulcan-quickstart: install + first paper trade; wallet, cli: vulcan
- clawd-vulcan-onboarding: wallet, registration, collateral; wallet, cli: vulcan
- clawd-vulcan-execution-modes: mode taxonomy; ref
- clawd-vulcan-market-intel: Phoenix tickers, book, funding; cli: vulcan => fetch.py backpack
- clawd-vulcan-technical-analysis: RSI/MACD/etc on Phoenix; cli: vulcan
- clawd-vulcan-lot-size-calculator: notional to base lots; cli: vulcan, ref
- clawd-vulcan-portfolio-intel: margin, positions, PnL; cli: vulcan
- clawd-vulcan-risk-management: liquidation distance, caps; ref
- clawd-vulcan-error-recovery: failure routing; ref
- clawd-vulcan-trade-execution: market/limit orders; wallet, cli: vulcan
- clawd-vulcan-position-management: close/reduce, TP/SL; wallet, cli: vulcan
- clawd-vulcan-margin-operations: collateral, leverage; wallet, cli: vulcan
- clawd-vulcan-tpsl-management: TP/SL ladders; wallet, cli: vulcan
- clawd-vulcan-twap-execution: TWAP runner; wallet, cli: vulcan
- clawd-vulcan-grid-trading: grid orders; wallet, cli: vulcan
- clawd-vulcan-ta-strategy: TA strategy runner; wallet, cli: vulcan

## Prediction markets (5)
- clawd-dflow-docs: DFlow docs/API index; ready
- clawd-dflow-kalshi-market-data: Kalshi book/trades via DFlow; key: DFLOW_API_KEY => fetch.py kalshi
- clawd-dflow-kalshi-market-scanner: Kalshi arb/movers scan; key: DFLOW_API_KEY => fetch.py kalshi
- clawd-dflow-kalshi-portfolio: wallet Kalshi positions; key: DFLOW_API_KEY
- clawd-dflow-kalshi-trading: buy/sell YES/NO; wallet, key: DFLOW_API_KEY => fetch.py kalshi first

## Launches, agent identity & Robinhood Chain (22)
- clawd-clawd-agent-launchpad: build/launch/stake agents; wallet
- clawd-cheshire-agent-registries: RH agent registry pins; ready
- clawd-cheshire-agent-identity-registry: RH identity NFT reads; ready
- clawd-cheshire-agent-reputation-registry: RH reputation reads; ready
- clawd-cheshire-agent-validation-registry: RH validation reads; ready
- clawd-cheshire-api: Cheshire API/MCP; key: CHESHIRE_API_KEY, unreachable: cheshireterminal.ai
- clawd-cheshire-omni-mint: omnichain agent mint; wallet, cli: npm cheshire-terminal-agents, unreachable: cheshireterminal.ai, funpump.ai
- clawd-cheshire-zk-omni: ZK omni messenger; ref, unreachable: cheshireterminal.ai, funpump.ai
- clawd-zk-omni-messaging: RH to Solana ZK messages; ref, unreachable: cheshireterminal.ai, funpump.ai
- clawd-google-agent-registry: A2A/MCP registry artifacts; ref
- clawd-robinhood-agent-forge: register agent identities; wallet, key: CHESHIRE_API_KEY, unreachable: cheshireterminal.ai => fetch.py metaplex
- clawd-rh-bonded-launch: RH bonding-curve launch; wallet
- clawd-rh-launchpad-v3: RH Launchpad V3; wallet
- clawd-pons-launch: RH fixed-supply launch; wallet, unreachable: pons.family
- clawd-rh-crypto-agent: RH agent pack index; wallet, ref
- clawd-solana-clawd-agents: agent catalog deploy/mint; wallet => fetch.py metaplex
- clawd-solana-clawd-agentic-commerce: Pay CLI agents, Genesis tokens; wallet => fetch.py metaplex
- clawd-solana-clawd: solana-clawd engine setup; ref, key: many (BIRDEYE, ANTHROPIC, X...)
- clawd-skillhub-onchain: publish skills on-chain; wallet, unreachable: skills.x402.wtf
- clawd-skills-store: Cheshire skills store index; wallet, ref, unreachable: cheshireterminal.ai, skills.x402.wtf
- clawd-gateway-node-ops: SolanaOS gateway/nodes; ref, cli: npm solanaos
- clawd-posthog-cheshire: PostHog for Cheshire; ref, key: POSTHOG_API_KEY

## Wallets, payments & x402 (9)
- clawd-phantom-wallet-mcp: Phantom wallet ops; wallet
- clawd-sponge-wallet: Sponge wallet + x402; wallet, key: SPONGE_API_KEY
- clawd-pay: Pay CLI paid APIs (x402); wallet, cli: pay
- clawd-pay-with-any-token: pay HTTP 402 via Tempo/Uniswap; wallet, cli: tempo, cast
- clawd-pay-with-app: pay OKX APP 402s; wallet, key: UNISWAP_API_KEY
- clawd-stripe: Stripe payments/MCP; wallet, key: STRIPE_SECRET_KEY
- clawd-dflow-proof-kyc: DFlow Proof KYC; ref
- clawd-dflow-phantom-connect: Phantom Connect apps; ref
- clawd-compressed-token: compressed SPL ops; wallet

## Solana & EVM dev (16)
- clawd-solana-dev: Solana dapps/Anchor; ref, cli: solana, anchor (curl installer)
- clawd-solana-common-errors: common build errors; ref
- clawd-solana-formal-verification: Lean 4 proofs; ref, cli: lean4
- clawd-solana-ralphy-skill: autonomous Solana coding loop; ref
- clawd-solana-redpill-verifier: TEE verifier stack; ref
- clawd-solana-rent-free-dev: Light rent-free dev; ref
- clawd-compressed-pda: compressed PDAs; ref
- clawd-zk: ZK nullifier PDAs; ref
- clawd-testing: Light Protocol testing; ref, key: HELIUS_API_KEY
- clawd-ask-mcp: DeepWiki repo Q&A; ready
- clawd-magicblock: Ephemeral Rollups; ref, wallet
- clawd-viem-integration: EVM reads/writes via viem; ref
- clawd-deployer: deploy CCA auctions; wallet, cli: forge, cast (foundryup)
- clawd-v4-hook-generator: Uniswap v4 hooks; ref
- clawd-v4-sdk-integration: Uniswap v4 SDK; ref
- clawd-v4-security-foundations: v4 hook security; ref, cli: forge

## Research & notes (19)
- clawd-weather: weather (wttr.in, Open-Meteo); ready
- clawd-openrouter-models: model list, pricing; ready
- clawd-github: gh issues/PRs/runs; ready
- clawd-session-logs: search past session logs; ref
- clawd-find-skills: discover skills (skills.sh); cli: npx skills (npm)
- clawd-blogwatcher: RSS/blog monitor; cli: blogwatcher (go install)
- clawd-summarize: summarize URLs/videos; cli: summarize (npm/brew), key: an LLM key
- clawd-nano-pdf: edit PDFs; cli: nano-pdf (uv/pip)
- clawd-oracle: oracle prompt bundler; cli: oracle (npm), key: OPENAI_API_KEY
- clawd-gemini: Gemini CLI Q&A; cli: gemini-cli (npm), key: Google login/key
- clawd-notion: Notion pages/DBs; key: NOTION_KEY
- clawd-trello: Trello boards; key: TRELLO_API_KEY, TRELLO_TOKEN
- clawd-obsidian: Obsidian vaults; cli: obsidian-cli (brew/go)
- clawd-local-places: Places proxy search; key: GOOGLE_PLACES_API_KEY
- clawd-goplaces: Google Places CLI; cli: goplaces (brew/go), key: GOOGLE_PLACES_API_KEY
- clawd-apple-notes: Apple Notes; mac
- clawd-apple-reminders: Apple Reminders; mac
- clawd-bear-notes: Bear notes; mac
- clawd-things-mac: Things 3; mac

## Media & design (26)
- clawd-video-frames: frames/clips via ffmpeg; ready
- clawd-youtube-clipper: clip YouTube videos; ready
- clawd-animation-vocabulary: name a motion effect; ref
- clawd-apple-design: Apple-style motion for web; ref
- clawd-emil-design-eng: UI polish philosophy; ref
- clawd-improve-animations: animation audit; ref
- clawd-review-animations: animation code review; ref
- clawd-shadcn: shadcn components; ref
- clawd-web-perf: Core Web Vitals; cli: Chrome DevTools MCP
- clawd-openai-image-gen: OpenAI image batches; key: OPENAI_API_KEY
- clawd-openai-whisper-api: Whisper API transcription; key: OPENAI_API_KEY
- clawd-openai-whisper: local Whisper; cli: whisper (pip openai-whisper)
- clawd-nano-banana-pro: Gemini image gen/edit; key: GEMINI_API_KEY
- clawd-openrouter-images: OpenRouter image gen; key: OPENROUTER_API_KEY
- clawd-sag: ElevenLabs TTS; cli: sag (brew), key: ELEVENLABS_API_KEY
- clawd-sherpa-onnx-tts: offline TTS; cli: sherpa-onnx runtime + model
- clawd-songsee: audio spectrograms; cli: songsee (brew)
- clawd-gifgrep: GIF search; cli: gifgrep (go)
- clawd-camsnap: RTSP camera snaps; cli: camsnap (brew)
- clawd-spotify-player: Spotify playback; cli: spogo/spotify_player
- clawd-sonoscli: Sonos control (LAN); cli: sonos (go)
- clawd-blucli: BluOS control (LAN); cli: blu (go)
- clawd-openhue: Hue lights (LAN); cli: openhue (brew)
- clawd-eightctl: Eight Sleep pods; cli: eightctl (go)
- clawd-peekaboo: macOS UI capture; mac
- clawd-canvas: Clawdbot node canvas (not here); ref

## Builder / dev tools (26)
- clawd-tmux: drive tmux sessions; ready
- clawd-skill-creator: author skills; ref
- clawd-forge: generate agent skills; ref
- clawd-clawd-skills-installer: install skill packs; ref
- clawd-clawdhub: ClawdHub skill registry; cli: clawdhub (npm)
- clawd-mcporter: call MCP servers from CLI; cli: mcporter (npm)
- clawd-agent-browser: browser smoke tests; cli: agent-browser (npm)
- clawd-coding-agent: run Codex/Claude Code; cli: claude/codex (npm), key: vendor keys
- clawd-clawdex: dual-engine coding agent; cli: claude, codex (npm), key: BROWSER_USE_API_KEY etc.
- clawd-openclawd-clawd-code-skill-main: drive Clawd Code via MCP; ref
- clawd-create-agent-tui: scaffold agent TUI; ref, key: OPENROUTER_API_KEY
- clawd-openrouter-typescript-sdk: OpenRouter SDK reference; ref
- clawd-openrouter-agent-migration: sdk to agent migration; ref
- clawd-openrouter-oauth: Sign in with OpenRouter; ref
- clawd-cloudflare: Cloudflare platform; ref
- clawd-agents-sdk: Cloudflare Agents SDK; ref
- clawd-durable-objects: Durable Objects; ref
- clawd-sandbox-sdk: Cloudflare sandboxes; ref
- clawd-workers-best-practices: Workers review; ref
- clawd-wrangler: deploy Workers; cli: wrangler (npm), key: CLOUDFLARE_API_TOKEN
- clawd-cloudflare-email-service: CF email send/route; key: CLOUDFLARE_API_TOKEN
- clawd-cloudflare-one: Zero Trust/SASE; ref
- clawd-cloudflare-one-migrations: SASE migrations; ref
- clawd-1password: 1Password CLI; cli: op (apt/brew)
- clawd-agent-desktop: macOS desktop automation; mac
- clawd-model-usage: CodexBar usage; mac

## Messaging & connectors (11)
- clawd-discord: Discord actions; key: Discord bot token
- clawd-slack: Slack actions; key: Slack bot token
- clawd-bird: X CLI via cookies; cli: bird (npm) => built-in x tools
- clawd-wacli: WhatsApp send/search; cli: wacli (go)
- clawd-himalaya: IMAP/SMTP email; cli: himalaya (apt/brew)
- clawd-gog: Google Workspace CLI; cli: gog (brew)
- clawd-imsg: iMessage/SMS; mac
- clawd-bluebubbles: BlueBubbles channel plugin; mac, ref
- clawd-voice-call: Clawdbot voice calls (not here); ref
- clawd-food-order: reorder Foodora; wallet, cli: ordercli (go)
- clawd-ordercli: Foodora order status; wallet, cli: ordercli (go)

## Master (1)
- clawd-master: full Clawd stack guide + connectors; ref => all Degen Desk skills

## Owner setup unlocks
- Phantom plugin (704) or Coinbase connector (68516158): the 58 `wallet` skills, always gated by `memecoin-trading-guardrails`. Solana flows sign in Phantom; EVM/Robinhood Chain/Uniswap flows need an EVM wallet the owner controls. Some also need a key or CLI.
- Keys: `DFLOW_API_KEY` 6 (DFlow spot, Kalshi data/scanner/portfolio/trading, platform fees); `IMPERIAL_API_KEY` 2 (Imperial entry + portfolio (wallet-signed JWT)); `UNISWAP_API_KEY` 3 (Uniswap swap/LP APIs, OKX 402 pay); `CHESHIRE_API_KEY` 2 (Cheshire API, agent forge); `OPENAI_API_KEY` 3 (image gen, Whisper API, oracle); `OPENROUTER_API_KEY` 2 (images, agent TUI); `GOOGLE_PLACES_API_KEY` 2 (places lookups); `CLOUDFLARE_API_TOKEN` 2 (wrangler, email service); one each: `HELIUS_API_KEY`, `HELIUS_RPC_URL` + `TELEGRAM_BOT_TOKEN` (swarm), `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `NOTION_KEY`, `TRELLO_API_KEY` + `TRELLO_TOKEN`, `STRIPE_SECRET_KEY`, `SPONGE_API_KEY`, `POSTHOG_API_KEY`, Discord and Slack bot tokens; LLM vendor keys for coding-agent, clawdex, summarize, gemini, solana-clawd.
- Vulcan CLI (Ellipsis-Labs GitHub install script, see `clawd-master`): 14 Phoenix perps skills; market data is keyless once installed, trading also needs a wallet.
- Other CLIs: 44 skills, each named on its line. Most install with npm, pip/uv or `go install` (node, uv and go are present); brew-only taps need a Linux build; SolanaOS core is unavailable. Ask before installing.
- Mac-only, cannot run here: 9 (apple-notes, apple-reminders, bear-notes, things-mac, peekaboo, agent-desktop, model-usage, imsg, bluebubbles).
- Keys, tokens and passwords go only through the secure secret form, never in chat, files or skills. Never ask for a seed phrase or private key.
