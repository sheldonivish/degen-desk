#!/usr/bin/env python3
"""Degen Desk: consolidate flat clawd-<slug> skills into category router skills.

Input:  a folder holding the flat clawd-* skills (as built by build_pack.py or an older install).
Output: ~17 category skills `clawd-<category>/` in --out, each with a router SKILL.md and the
        original skills moved unchanged to `clawd-<category>/skills/<slug>/` (their SKILL.md is
        renamed SKILL.reference.md so skill loaders don't register 204 skills again). Internal
        cross-references (absolute paths, relative links, `clawd-<slug>` names) are rewritten
        to the new paths. Optional: regenerate the degen-desk-skill-map and fix references in
        other (core) skills in place.
"""
import argparse, csv, os, re, shutil, sys

CATS = [
 ('clawd-master', 'top index + Clawd/Musebook stack guide',
  "Use first when unsure which clawd skill fits, or for the full Clawd/Musebook stack overview: connectors, live-bundle onboarding, pump.fun and Phoenix flows, x402, safety rules, the Vulcan CLI install script, not-shipped skill substitutes, and the index of every clawd category skill and sub-skill."),
 ('clawd-memecoin-pump', 'pump.fun & memecoin trading',
  "Use for pump.fun and Solana memecoin work beyond the hourly report: DexScreener screening, pump.fun bonding-curve/graduation analytics and price-impact quotes, read-only creator-vault and unclaimed-reward checks, pump.fun buy/sell, launching a pump.fun token, creator-fee claims and splits, PUMP incentive claims, token lifecycle and AMM migration, authority/admin ops, multi-bot pump swarms, $CLAWD token ops and the Cheshire $CLAWD trading terminal."),
 ('clawd-pump-devkit', 'pump.fun program & SDK developer kit',
  "Use when building on, auditing or explaining the pump.fun program and SDK: fee tiers and creator-vault math, SDK instruction builders, program PDAs and account layouts, Anchor/SPL patterns, SDK security practices, test infrastructure, build and release, secure Bash tooling, AGENTS/CLAUDE files for SDK repos, building a pump MCP server, Rust and TypeScript vanity-address tools, and wallet-generation guidance. Reference guides; nothing here trades."),
 ('clawd-spot-bots', 'spot swaps, LP & trading bots',
  "Use for spot swaps and trading bots: DFlow Solana swaps and DFlow builder/platform fees, Uniswap swap plans with deep links and Uniswap Trading API swap integration, Uniswap LP position plans and the LP API, copy-trading (mirroring) a wallet, DCA / recurring buys, weighted index-basket buys, and NOXA DEX quotes and launch feed."),
 ('clawd-perps-imperial', 'Imperial perpetuals',
  "Use for perpetual futures on Imperial: the Imperial entry point and skill index, observe/paper/live execution modes, keyless market intel (funding, marks, depth, routes), portfolio balances and positions, pre-trade risk checks, live market orders, reducing/closing positions, margin deposit/withdraw, TP/SL, TWAP execution and grid ladders."),
 ('clawd-perps-vulcan', 'Phoenix perpetuals via the Vulcan CLI',
  "Use for Phoenix perpetuals through the Vulcan CLI: install and first paper trade, onboarding (wallet, registration, collateral), execution-mode taxonomy, market intel (tickers, order book, funding), technical analysis (RSI, MACD and more), notional-to-lot-size calculation, portfolio margin/positions/PnL, risk and liquidation distance, error recovery, market/limit orders, position management with TP/SL, margin and leverage, TP/SL ladders, TWAP, grid orders and a TA strategy runner."),
 ('clawd-prediction-markets', 'prediction markets (DFlow / Kalshi)',
  "Use for prediction markets on DFlow/Kalshi: the DFlow docs, API and docs-MCP index, Kalshi market data (orderbook, trades, top of book, candlesticks), scanning markets for arbitrage, cheap long-shots, near-certain plays or big movers, a wallet's Kalshi positions and P&L, and buying, selling or redeeming YES/NO outcome tokens."),
 ('clawd-launchpads-agents', 'launchpads, agent identity & Robinhood Chain',
  "Use for token launchpads and on-chain agent identity: the Clawd/Cheshire Agent Launchpad, Cheshire ERC-8004 identity, reputation and validation registries on Robinhood Chain, the Cheshire API/MCP, omnichain agent mints and ZK omni messaging, Google A2A/MCP agent-registry artifacts, Robinhood Chain bonded-curve, Launchpad V3 and Pons launches, the RH crypto-agent pack, the solana-clawd engine, agent catalog deploy/mint and agentic commerce, on-chain skill hubs and skill stores, SolanaOS gateway nodes, and PostHog analytics for Cheshire."),
 ('clawd-wallets-payments', 'wallets, payments & x402',
  "Use for wallets and payments: Phantom wallet MCP ops, the Sponge wallet, paid HTTP APIs through the Pay CLI (x402 / HTTP 402), paying 402s with any token (Tempo/Uniswap) or via the OKX app, Stripe payments and MCP, DFlow Proof KYC, building Phantom Connect wallet apps, and compressed SPL token operations."),
 ('clawd-chain-dev', 'Solana & EVM smart-contract development',
  "Use for Solana and EVM smart-contract and dapp development: Solana/Anchor dapps, common Solana build errors, Lean 4 formal verification, an autonomous Solana coding loop, a TEE verifier stack, Light Protocol rent-free development, compressed PDAs, ZK nullifier PDAs and Light testing, DeepWiki repo Q&A, MagicBlock ephemeral rollups, EVM reads/writes with viem, CCA auction deployment, and Uniswap v4 hooks, SDK and hook security."),
 ('clawd-research-productivity', 'research, notes & productivity',
  "Use for research, notes and productivity tools: weather, OpenRouter model lists and pricing, GitHub via gh (issues, PRs, runs), searching past session logs, discovering skills, RSS/blog monitoring, summarizing URLs and videos, editing PDFs, the oracle prompt bundler, Gemini CLI Q&A, Notion, Trello, Obsidian vaults, Google Places lookups, and Mac-only Apple Notes, Apple Reminders, Bear and Things 3."),
 ('clawd-design-ui', 'UI & motion design for the web',
  "Use for web UI and motion design: finding the name of an animation effect, Apple-style fluid and gesture-driven motion, UI polish and design-engineering philosophy, auditing and code-reviewing animations, shadcn/ui components, and Core Web Vitals performance work."),
 ('clawd-media-gen', 'media generation & processing',
  "Use for media generation and processing: extracting video frames or clips with ffmpeg, clipping YouTube videos with bilingual subtitles, image generation and editing (OpenAI, Gemini Nano Banana Pro, OpenRouter), speech-to-text (Whisper API or local Whisper), text-to-speech (ElevenLabs via sag, offline sherpa-onnx), audio spectrograms, and GIF search."),
 ('clawd-home-devices', 'cameras, speakers, lights & devices',
  "Use for cameras, speakers, lights and other devices: RTSP/ONVIF camera snapshots and clips, Spotify playback, Sonos and BluOS speakers, Philips Hue lights, Eight Sleep pods, macOS UI capture with Peekaboo, and the Clawdbot node canvas. Most need a local CLI and LAN access to the device."),
 ('clawd-cloud-workers', 'Cloudflare platform & Workers',
  "Use for Cloudflare: the platform overview (Workers, Pages, KV, D1, R2, Workers AI, Vectorize, flags, network), the Agents SDK, Durable Objects, Sandbox SDK, Workers best-practice reviews, deploying with wrangler, Cloudflare Email Service sending and routing, Cloudflare One Zero Trust/SASE, and migrations to Cloudflare One."),
 ('clawd-dev-tools', 'coding agents & developer tools',
  "Use for coding-agent and developer tooling: driving tmux sessions, authoring, generating and installing agent skills, the ClawdHub skill registry, calling MCP servers from the CLI (mcporter), agent-browser smoke tests, running Codex/Claude Code/OpenCode in the background, the Clawdex dual-engine pattern, driving Clawd Code via MCP, scaffolding an agent TUI, the OpenRouter TypeScript SDK, agent migration and OAuth, the 1Password CLI, macOS desktop automation, and CodexBar model-usage stats."),
 ('clawd-messaging', 'messaging & communication connectors',
  "Use for messaging and communication: Discord and Slack actions, X/Twitter via the bird CLI (prefer the built-in x tools), WhatsApp via wacli, IMAP/SMTP email via himalaya, the Google Workspace CLI (gog), iMessage/SMS and the BlueBubbles plugin (Mac), Clawdbot voice calls, and Foodora reorders and order status."),
]
CAT_IDS = [c[0] for c in CATS]

def load_manifest(p):
    rows = list(csv.DictReader(open(p, encoding='utf-8'), delimiter='\t'))
    for r in rows:
        assert r['category'] in CAT_IDS, r
    return rows

def parse_tags(tags):
    out = {'ready': False, 'ref': False, 'wallet': False, 'mac': False, 'key': [], 'cli': [], 'unreachable': []}
    cur = None
    for tok in [t.strip() for t in tags.split(', ') if t.strip()]:
        m = re.match(r'^(key|cli|unreachable):\s*(.*)$', tok)
        if m: cur = m.group(1); out[cur].append(m.group(2)); continue
        if tok in ('ready', 'ref', 'wallet', 'mac'): out[tok] = True; cur = None; continue
        if cur: out[cur].append(tok)
        else: out.setdefault('other', []).append(tok)
    return out

def short_desc(r):
    d = r['description'].strip()
    d = re.sub(r'^Use when you need Clawd [\w-]+:\s*', '', d)
    d = re.sub(r'\s*\(Clawd [\w-]+\)\.?$', '.', d)
    d = d[0].upper() + d[1:] if d else r['purpose']
    if len(d) > 230: d = d[:229].rsplit(' ', 1)[0].rstrip(',;:—-') + '…'
    return d.replace('|', '/')

# ---------- path mapping ----------
class Mapper:
    def __init__(self, rows, final, src=None):
        self.final = final.rstrip('/')
        self.src = src.rstrip('/') if src else None
        self.by_name = {r['name']: r for r in rows}
        # longest names first so the regex alternation is unambiguous
        self.names = sorted(self.by_name, key=len, reverse=True)
        alt = '|'.join(re.escape(n) for n in self.names)
        F = re.escape(self.final)
        self.abs_re = re.compile(F + r'/(' + alt + r')(?![\w-])((?:/[^\s)`"\'<>\]|,;]*)?)')
        self.rel_re = re.compile(r'(?<![\w.])((?:\./)?(?:\.\./)+)(' + alt + r')(?![\w-])((?:/[^\s)`"\'<>\]|,;]*)?)')
        self.bare_re = re.compile(r'(?<![\w/.@-])(' + alt + r')(?![\w-])(/SKILL\.md(?![\w.]))?')
        self.link_re = re.compile(r'(\]\()([^)\s]+)((?:\s+"[^"]*")?\))')

    def newdir(self, name):
        r = self.by_name[name]
        return f"{r['category']}/skills/{r['slug']}"

    def map_abs(self, p):
        """old absolute path (under final) -> new absolute path"""
        f = self.final + '/'
        if not p.startswith(f): return p
        rest = p[len(f):]
        head, _, tail = rest.partition('/')
        if head not in self.by_name: return p
        if tail == 'SKILL.md': tail = 'SKILL.reference.md'
        return f + self.newdir(head) + ('/' + tail if tail else '')

    def map_rest(self, name, rest):
        if re.match(r'^/SKILL\.md(?=$|[#?])', rest):
            rest = '/SKILL.reference.md' + rest[len('/SKILL.md'):]
        return self.newdir(name) + rest

def rewrite_text(text, M, old_file, new_file, is_md, skip_name_line=False, keep_master_bare=True):
    """old_file/new_file: absolute paths in the *final* namespace."""
    olddir, newdir = os.path.dirname(old_file), os.path.dirname(new_file)
    n = [0]
    def link(m):
        tgt = m.group(2)
        if re.match(r'^([a-z][a-z0-9+.-]*:|#|\{|<)', tgt, re.I): return m.group(0)
        path, frag = re.match(r'^([^#?]*)(.*)$', tgt).groups()
        if not path: return m.group(0)
        if path.startswith('/'):
            if not path.startswith(M.final + '/'): return m.group(0)
            new = M.map_abs(path)
        else:
            res = os.path.normpath(os.path.join(olddir, path))
            sib = re.match(r'^(?:\.\./)+([a-z0-9-]+)/SKILL\.md$', path)
            if sib and M.src and ('clawd-' + sib.group(1)) in M.by_name and not os.path.exists(M.src + res[len(M.final):]):
                # un-prefixed sibling-skill link left over from the upstream bundle
                res = f"{M.final}/clawd-{sib.group(1)}/SKILL.md"
            new = os.path.relpath(M.map_abs(res), newdir)
            if path.endswith('/') and not new.endswith('/'): new += '/'
            if path.startswith('./') and not new.startswith('.'): new = './' + new
        if new == path: return m.group(0)
        n[0] += 1
        return m.group(1) + new + frag + m.group(3)
    def absr(m):
        n[0] += 1
        return M.final + '/' + M.map_rest(m.group(1), m.group(2))
    def relr(m):
        dots, name, rest = m.groups()
        res = os.path.normpath(os.path.join(olddir, dots + name + rest))
        new = os.path.relpath(M.map_abs(res), newdir)
        n[0] += 1
        return new + ('/' if rest.endswith('/') and not new.endswith('/') else '')
    def bare(m):
        name, sk = m.group(1), m.group(2)
        if name == 'clawd-master' and keep_master_bare:
            # still a valid skill (now the top index); only path-ish uses move
            after = m.string[m.end():m.end() + 1]
            if not sk and after != '/': return m.group(0)
        n[0] += 1
        return M.map_rest(name, sk or '')
    if is_md:
        text = M.link_re.sub(link, text)
    text = M.abs_re.sub(absr, text)
    if is_md:
        text = M.rel_re.sub(relr, text)
        if skip_name_line:
            fm = re.match(r'^(\ufeff?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$))', text, re.S)
            if fm:
                head = fm.group(1)
                head2 = '\n'.join(l if l.startswith('name:') else M.bare_re.sub(bare, l) for l in head.split('\n'))
                text = head2 + M.bare_re.sub(bare, text[len(head):])
            else:
                text = M.bare_re.sub(bare, text)
        else:
            text = M.bare_re.sub(bare, text)
        text = text.replace('(supporting files ship alongside this SKILL.md)', '(supporting files ship alongside this file)')
        text = text.replace('The individual capabilities are installed as separate `clawd-<slug>` skills (204 total incl. this one)', 'The individual capabilities are installed as sub-skills of the `clawd-<category>` router skills (`clawd-<category>/skills/<slug>/SKILL.reference.md`; 204 total incl. this guide, now at `clawd-master/skills/clawd/`; the category index is the `clawd-master` router)')
        text = text.replace('and the `clawd-dflow-*` skills', 'and the other `dflow-*` sub-skills (in `clawd-prediction-markets`, `clawd-spot-bots`, `clawd-wallets-payments`)')
    return text, n[0]

def is_text(p):
    if os.path.getsize(p) > 8_000_000: return False
    try:
        with open(p, 'rb') as fh: b = fh.read()
        if b'\0' in b[:8192]: return False
        b.decode('utf-8'); return True
    except Exception: return False

# ---------- router ----------
def yq(s): return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

def router(cat, title, use_when, subs, M, all_rows):
    final = M.final
    money_subs = [r for r in subs if r['money'] == 'yes']
    names = ', '.join(r['slug'] for r in subs)
    desc = f"{use_when} Router for {len(subs)} Clawd sub-skills: {names}." if cat != 'clawd-master' else f"{use_when} The full original master guide is the sub-skill skills/clawd."
    if len(desc) > 1000:
        desc = desc[:999].rsplit(',', 1)[0] + ', …'
    L = ['---', f'name: {cat}', f'description: {yq(desc)}', '---', '',
         f'# {cat}: {title}', '',
         f'**Use this when…** {use_when}', '',
         f'This is a router. Pick the sub-skill that fits from the table, then **Read its full recipe at the path in the last column** (supporting files sit in the same folder). Each recipe opens with a "Running here (Degen Desk)" note that maps its paths and tools to this box; follow it. Sub-skill folders live under `{final}/{cat}/skills/<slug>/`; their main file is `SKILL.reference.md` (renamed from `SKILL.md` so the library does not load them as separate skills).', '',
         'Order of preference: Degen Desk core skills and `/workspace/trenches/fetch.py` first for keyless research (see the "Try first" column), then the sub-skill. Never install a CLI, use a paid service, or contact anyone (post, message, email) without the owner\'s explicit approval. Keys, tokens and passwords come only through the secure secret form, never in chat or files; never ask for a seed phrase or private key.', '']
    if money_subs:
        L += [f'**Money-moving sub-skills ({len(money_subs)}, marked 💸 yes):** {", ".join(r["slug"] for r in money_subs)}. These run **only through `memecoin-trading-guardrails`**: research/quote first, the owner\'s own wallet only (Phantom plugin or Coinbase connector, or an EVM wallet the owner controls), the exact terms shown and approved by the owner for every single trade/payment/launch/claim, no local keypairs or private keys, confirm on-chain, never retry a write, never auto-trade. Where a sub-skill\'s own steps conflict (`--yes` flags, auto-execute, env private keys), the guardrails win.', '']
    else:
        L += ['**Money:** no sub-skill here moves money. If a task turns into a trade, payment, launch or claim, stop and go through `memecoin-trading-guardrails`.', '']
    if cat == 'clawd-master':
        L += ['## Category index', '', 'All Clawd skills (204 from the Musebook Clawd pack v3.14.0) are grouped into these category skills. Read the category\'s `SKILL.md` router, then the sub-skill\'s `SKILL.reference.md`. Full runnability map: `degen-desk-skill-map`.', '',
              '| Category skill | Covers | Sub-skills | Money-moving |', '|---|---|---|---|']
        for c, t, u in CATS:
            rs = [r for r in all_rows if r['category'] == c]
            L.append(f'| `{c}` | {t} | {len(rs)} | {sum(r["money"]=="yes" for r in rs)} |')
        L += ['']
    L += ['## Sub-skills', '',
          '| Sub-skill | What it does | 💸 Moves money | API key / account | CLI | Mac-only | Unreachable host | Status | Try first | Read (full recipe) |',
          '|---|---|---|---|---|---|---|---|---|---|']
    for r in subs:
        t = parse_tags(r['tags'])
        status = ', '.join(x for x in (['ready'] if t['ready'] else []) + (['reference guide'] if t['ref'] else []) + t.get('other', [])) or ('needs setup' if (t['key'] or t['cli'] or t['wallet'] or t['mac']) else '—')
        cell = lambda xs: ', '.join(xs).replace('|', '/') if xs else '—'
        money = '💸 yes (guardrails)' if r['money'] == 'yes' else 'no'
        path = f"`{final}/{cat}/skills/{r['slug']}/SKILL.reference.md`"
        L.append(f"| **{r['slug']}** | {short_desc(r)} | {money} | {cell(t['key'])} | {cell(t['cli'])} | {'yes' if t['mac'] else 'no'} | {cell(t['unreachable'])} | {status} | {r['first'].replace('|','/') or '—'} | {path} |")
    if cat == 'clawd-master':
        L += ['', 'Before the Oct 2026 consolidation this guide was the whole top-level `clawd-master` skill; it is kept in full at the path above (Musebook plugin manifests under `skills/clawd/plugins/`). Old `clawd-<slug>` skill names now mean the sub-skill of the same slug in the category listed above.', '']
    else:
        L += ['', f'Original skill names: each sub-skill was the top-level skill `clawd-<slug>` before the Oct 2026 consolidation; references to those names mean the sub-skill here.', '']
    if any(parse_tags(r['tags'])['unreachable'] for r in subs):
        L += ['Unreachable hosts: these remote hosts failed TLS from this box when audited (Oct 2026). Try once; if it still fails, say so instead of retrying. On-chain reads over public RPC still work.', '']
    if any(parse_tags(r['tags'])['mac'] for r in subs):
        L += ['Mac-only sub-skills cannot run on this Linux box; explain that and offer an alternative.', '']
    return '\n'.join(L)

# ---------- build ----------
def build(src, out, rows, final):
    M = Mapper(rows, final, src)
    os.makedirs(out, exist_ok=True)
    stats = {'files': 0, 'edits': 0, 'moved': 0}
    for r in rows:
        s = os.path.join(src, r['name'])
        if not os.path.isfile(os.path.join(s, 'SKILL.md')):
            sys.exit(f'missing source skill {s}')
        d = os.path.join(out, r['category'], 'skills', r['slug'])
        if os.path.exists(d): sys.exit(f'refusing to overwrite {d}')
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copytree(s, d, symlinks=True)
        os.rename(os.path.join(d, 'SKILL.md'), os.path.join(d, 'SKILL.reference.md'))
        stats['moved'] += 1
        for root, ds, fs in os.walk(d):
            for f in fs:
                p = os.path.join(root, f)
                if os.path.islink(p) or not is_text(p): continue
                newrel = os.path.relpath(p, d)
                oldrel = 'SKILL.md' if newrel == 'SKILL.reference.md' else newrel
                old_abs = f"{M.final}/{r['name']}/{oldrel}"
                new_abs = f"{M.final}/{r['category']}/skills/{r['slug']}/{newrel}"
                t = open(p, encoding='utf-8').read()
                t2, k = rewrite_text(t, M, old_abs, new_abs, f.lower().endswith('.md'), skip_name_line=(newrel == 'SKILL.reference.md'))
                if t2 != t:
                    open(p, 'w', encoding='utf-8').write(t2); stats['files'] += 1; stats['edits'] += k
    for cat, title, use_when in CATS:
        subs = [r for r in rows if r['category'] == cat]
        if not subs: continue
        open(os.path.join(out, cat, 'SKILL.md'), 'w', encoding='utf-8').write(router(cat, title, use_when, subs, M, rows))
    return stats

def fix_refs(paths, rows, final):
    M = Mapper(rows, final); tot = 0
    for p in paths:
        t = open(p, encoding='utf-8').read()
        ap_ = os.path.abspath(p)
        t2, k = rewrite_text(t, M, ap_, ap_, p.endswith('.md'))
        if t2 != t: open(p, 'w', encoding='utf-8').write(t2)
        tot += k; print(f'[consolidate] {p}: {k} refs rewritten')
    return tot

def skill_map(base, rows, final, out):
    M = Mapper(rows, final)
    t = open(base, encoding='utf-8').read()
    fm_intro = t.split('\n## ', 1)[0]
    fm_intro = re.sub(r'\n\*\*Layout \(Oct 2026 consolidation\)\.\*\*[^\n]*\n', '\n', fm_intro)  # idempotent re-runs
    owner = re.search(r'\n(## Owner setup unlocks\n.*)$', t, re.S)
    owner = owner.group(1) if owner else ''
    fm_intro, _ = rewrite_text(fm_intro, M, base, base, True)
    owner, _ = rewrite_text(owner, M, base, base, True)
    fm_intro = re.sub(r'(description: ")Use when deciding which Degen Desk or clawd-\* skill fits', r'\1Use when deciding which Degen Desk skill or clawd category skill (and which sub-skill inside it) fits', fm_intro)
    fm_intro = fm_intro.replace('(2) a clawd-* skill for anything else', '(2) a clawd category skill (the `clawd-<category>` router, then the sub-skill it points to) for anything else')
    L = [fm_intro.rstrip('\n'), '',
         f'**Layout (Oct 2026 consolidation).** The 204 Clawd skills are grouped into {len(CATS)} category skills `clawd-<category>` (below). Each category\'s `SKILL.md` is a router; the full recipe of a sub-skill is `{final}/<category>/skills/<slug>/SKILL.reference.md`. A line `- <slug>` under a category means that path. Old names `clawd-<slug>` (from before the consolidation) mean the sub-skill with that slug.', '']
    for cat, title, use_when in CATS:
        subs = [r for r in rows if r['category'] == cat]
        L.append(f'## {cat}: {title} ({len(subs)})')
        L.append(f'Router: `{final}/{cat}/SKILL.md` · sub-skills: `{final}/{cat}/skills/<slug>/SKILL.reference.md`')
        for r in subs:
            line = f"- {r['slug']}: {r['purpose']}; {r['tags']}"
            if r['first']: line += f" => {r['first']}"
            L.append(line)
        L.append('')
    L.append(owner.rstrip('\n'))
    open(out, 'w', encoding='utf-8').write('\n'.join(L) + '\n')

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--final', required=True, help='skills library path written into routers/notes')
    ap.add_argument('--src'); ap.add_argument('--out')
    ap.add_argument('--fix-refs', nargs='*', default=[])
    ap.add_argument('--skill-map-base'); ap.add_argument('--skill-map-out')
    A = ap.parse_args()
    rows = load_manifest(A.manifest)
    if A.src and A.out:
        print('[consolidate]', build(A.src, A.out, rows, A.final))
    if A.fix_refs:
        fix_refs(A.fix_refs, rows, A.final)
    if A.skill_map_base and A.skill_map_out:
        skill_map(A.skill_map_base, rows, A.final, A.skill_map_out)
        print('[consolidate] skill map ->', A.skill_map_out)
