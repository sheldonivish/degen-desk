#!/usr/bin/env python3
"""Trenches report data pipeline (data side only; X reads go through the x MCP tools).

Usage:
  python3 fetch.py build --raw runs/raw_<stamp>.json [--calls calls.jsonl] [--no-append]
      -> writes runs/run_<stamp>.json (structured data) and runs/blocks_<stamp>.md (ready-to-paste
         Majors price line, Calls & CAs bullets, concentration flag, 24h most-mentioned, post digest)
  python3 fetch.py tally [--calls calls.jsonl] [--hours 24]
      -> prints the most-mentioned-by-distinct-accounts ranking from calls.jsonl
  python3 fetch.py enrich [--ca <CA> --chain solana] [--hours 24]
      -> v3 keyless on-chain enrichment (pump.fun curve, Musebook snapshot, RugCheck/GoPlus, risk heuristics)
         for given CAs or every CA in calls.jsonl; writes runs/enrich_<stamp>.{md,json}
  python3 fetch.py scan [--min-liq 10000 --min-mcap 25000 --min-buys 10 --chain all --sort h1]
      -> DexScreener boosts + Musebook pulse/live tokens, filtered, cross-referenced with calls.jsonl and the
         newest run; writes runs/scan_<stamp>.{md,json}
  python3 fetch.py launches [--limit 15]
      -> short pump.fun launch snapshot from Musebook's public feed (no socket); writes runs/launches_<stamp>.{md,json}
  build also enriches every CA (v3) unless --no-enrich is passed.
  v4 research modes (keyless, read-only; each writes runs/<mode>_<stamp>.{md,json}):
  python3 fetch.py quote --ca <SOL mint> [--amount-sol 1 --slippage-bps 100]   Jupiter price/token stats + buy & sell-back quote
  python3 fetch.py raydium --ca <SOL mint>                                      Raydium pools (TVL, 24h vol, fee, LP burn)
  python3 fetch.py backpack [--symbol SOL_USDC_PERP] [--type spot|perp]         Backpack tickers / book / funding / OI
  python3 fetch.py rwa [--limit 10]                                             Backpack stock perps, Solana xStock prices, Musebook RWA status
  python3 fetch.py kalshi [--query bitcoin] [--series KXBTCD] [--source both|kalshi|jupiter]   prediction markets
  python3 fetch.py ore                                                          ORE v3 mining board/treasury/last round (on-chain)
  python3 fetch.py metaplex [--query clawd | --address <agent mint>] [--launches]   Metaplex agent registry + Genesis launches
  None of these build, sign or send anything.

Raw input format (one file per run):
  {"window": {"start": ISO, "end": ISO},
   "lists": {"<list_id>": [<search_posts_all response>, ...]}}   # >1 response when a list was split
Each response is the x.search_posts_all JSON as returned ({"data": [...], "includes": {"users": [...]}, "meta": {...}}).
Stdlib only. Every number in the output comes from DexScreener / Hyperliquid / CoinGecko or the posts themselves.
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ_NAME = os.environ.get("DD_TZ", "Asia/Dubai")   # report timezone; set DD_TZ (e.g. Asia/Kolkata) to change
DUBAI = ZoneInfo(TZ_NAME)
TZL = os.environ.get("DD_TZ_LABEL") or TZ_NAME.split("/")[-1].replace("_", " ")   # label printed after times
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "trenches-report/2.0", "Accept": "application/json"}
CAP = 25

CHAIN_ALIASES = {"sol": "solana", "solana": "solana", "eth": "ethereum", "ethereum": "ethereum", "base": "base",
                 "bsc": "bsc", "bnb": "bsc", "robinhood": "robinhood", "arbitrum": "arbitrum", "arb": "arbitrum",
                 "polygon": "polygon", "avax": "avalanche", "avalanche": "avalanche", "sui": "sui",
                 "hyperevm": "hyperevm", "abstract": "abstract", "monad": "monad", "blast": "blast", "sonic": "sonic",
                 "tron": "tron", "ton": "ton", "unichain": "unichain", "linea": "linea", "megaeth": "megaeth"}
EVM_RE = r"0x[a-fA-F0-9]{40}"
SOL_RE = r"[1-9A-HJ-NP-Za-km-z]{32,44}"
PREFIXED_RE = re.compile(r"\b([a-z]{2,12}):(" + EVM_RE + "|" + SOL_RE + r")\b")
BARE_EVM_RE = re.compile(r"(?<![:\w])(" + EVM_RE + r")\b")
BARE_SOL_RE = re.compile(r"(?<![:\w/])(" + SOL_RE + r")(?![\w])")
CASHTAG_RE = re.compile(r"(?<![\w$])\$([A-Za-z][A-Za-z0-9_]{0,14})\b")
URL_RE = re.compile(r"https?://\S+")
KEYWORDS = re.compile(r"\b(" + "|".join([
    r"crypto\w*", r"memecoins?", r"memes?", r"coins?", r"tokens?", r"solana", r"sol", r"eth", r"btc", r"bitcoin",
    r"ethereum", r"pump\w*", r"dump\w*", r"bids?", r"bidding", r"longs?", r"shorts?", r"liquidat\w*", r"leverage\w*",
    r"positions?", r"positioned", r"markets?", r"mcap", r"mc", r"market ?cap", r"charts?", r"ath", r"dips?", r"bull\w*",
    r"bear\w*", r"binance", r"stablecoins?", r"trad(e|es|ing|er|ers)", r"portfolio", r"pnl", r"profits?", r"runners?",
    r"ape[ds]?", r"launch\w*", r"dex\w*", r"onchain", r"on-chain", r"wallets?", r"airdrops?", r"narratives?",
    r"accumulat\w*", r"sell\w*", r"sold", r"buy\w*", r"bought", r"hold(ing|ers?)?", r"trenches", r"degens?", r"rugs?",
    r"rugged", r"fomo", r"\d+x", r"spot", r"perps?", r"alts?", r"altcoins?", r"bags?", r"entry", r"exit(ed)?",
    r"cto", r"kol\w*", r"liquidity", r"inflows?", r"outflows?", r"fees", r"supply", r"conviction\w*"]) + r")\b", re.I)


def http_json(url, data=None, timeout=25, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                         headers={**UA, **({"Content-Type": "application/json"} if data is not None else {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise last


def to_dubai(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(DUBAI)


def hhmm(dt):
    return dt.strftime("%-I:%M %p")


def fmt_usd(v):
    if v is None:
        return "n/a"
    v = float(v)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"${v / div:.2f}{suf}"
    return f"${v:,.2f}" if abs(v) >= 1 else f"${v:.6g}"


def fmt_pct(v):
    return "n/a" if v is None else f"{float(v):+.1f}%"


def fmt_age(ms, now):
    if not ms:
        return "n/a"
    d = now - datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    h = int(d.total_seconds() // 3600)
    if h < 1:
        return f"{int(d.total_seconds() // 60)}m"
    if h < 48:
        return f"{h}h"
    return f"{h // 24}d"


def ca_link(chain, ca):
    if chain == "solana" and ca.endswith("pump"):
        return f"https://pump.fun/coin/{ca}"
    return f"https://dexscreener.com/{chain or 'search?q='}/{ca}" if chain else f"https://dexscreener.com/search?q={ca}"


# ---------------------------------------------------------------- posts
def load_posts(raw):
    users, per_list, capped, seen = {}, {}, [], {}
    for list_id, responses in raw["lists"].items():
        if isinstance(responses, dict):
            responses = [responses]
        per_list[list_id] = 0
        for resp in responses:
            for u in (resp.get("includes") or {}).get("users", []):
                users[u["id"]] = u["username"]
            n = len(resp.get("data") or [])
            per_list[list_id] += n
            if n >= CAP:
                capped.append(list_id)
            for p in resp.get("data") or []:
                edits = p.get("edit_history_tweet_ids") or p.get("edit_history_post_ids") or [p["id"]]
                canon = max(edits, key=int)
                cur = seen.get(canon)
                if cur is None or int(p["id"]) > int(cur["id"]):
                    lists = (cur or {}).get("_lists", set())
                    seen[canon] = {**p, "_lists": lists}
                seen[canon]["_lists"].add(list_id)
    raw_total = sum(per_list.values())
    posts, dropped_reply, dropped_offtopic = [], [], []
    for p in seen.values():
        p["handle"] = users.get(p.get("author_id"), p.get("url", "").split("/")[3] if p.get("url") else "unknown")
        p["lists"] = sorted(p.pop("_lists"))
        p.setdefault("url", f"https://x.com/{p['handle']}/status/{p['id']}")
        refs = {r.get("type") for r in p.get("referenced_tweets") or []}
        if p.get("text", "").startswith("RT @") or "retweeted" in refs or "replied_to" in refs or p.get("in_reply_to_user_id"):
            dropped_reply.append(p)
            continue
        body = URL_RE.sub(" ", p.get("text", ""))
        p["cas"] = extract_cas(body)
        p["cashtags"] = sorted({c.upper() for c in CASHTAG_RE.findall(body)})
        p["keywords"] = sorted({m.group(0).lower() for m in KEYWORDS.finditer(body)})
        if not (p["cas"] or p["cashtags"] or p["keywords"]):
            dropped_offtopic.append(p)
            continue
        dt = to_dubai(p["created_at"])
        p["time_dubai"] = hhmm(dt)
        posts.append(p)
    posts.sort(key=lambda x: x["created_at"], reverse=True)
    return posts, {"per_list": per_list, "capped_lists": capped, "raw_total": raw_total, "unique": len(seen),
                   "dropped_replies_rts": len(dropped_reply),
                   "dropped_offtopic": [{"handle": p["handle"], "url": p["url"], "text": p["text"][:80]} for p in dropped_offtopic],
                   "kept": len(posts)}


def extract_cas(text):
    found, spans = [], []
    for m in PREFIXED_RE.finditer(text):
        chain = CHAIN_ALIASES.get(m.group(1).lower())
        addr = m.group(2)
        if chain is None:
            chain = "evm?" if addr.startswith("0x") else "solana"
        found.append({"chain": chain, "ca": addr})
        spans.append(m.span(2))
    def free(span):
        return not any(s <= span[0] < e for s, e in spans)
    for m in BARE_EVM_RE.finditer(text):
        if free(m.span(1)):
            found.append({"chain": None, "ca": m.group(1)})
    for m in BARE_SOL_RE.finditer(text):
        a = m.group(1)
        if free(m.span(1)) and not a.startswith("0x") and re.search(r"\d", a) and re.search(r"[a-z]", a) and re.search(r"[A-Z]", a):
            found.append({"chain": "solana", "ca": a})
    out, keys = [], set()
    for f in found:
        k = f["ca"].lower()
        if k not in keys:
            keys.add(k)
            out.append(f)
    return out


# ---------------------------------------------------------------- DexScreener
def dex_lookup(chain, ca):
    try:
        if chain and chain not in ("evm?",):
            pairs = http_json(f"https://api.dexscreener.com/tokens/v1/{chain}/{ca}")
        else:
            pairs = (http_json(f"https://api.dexscreener.com/latest/dex/tokens/{ca}") or {}).get("pairs") or []
    except Exception as e:
        return {"chain": chain, "ca": ca, "ok": False, "error": str(e)}
    pairs = [p for p in pairs or [] if (p.get("baseToken") or {}).get("address", "").lower() == ca.lower()]
    if not pairs:
        return {"chain": chain, "ca": ca, "ok": False, "error": "no pairs on DexScreener"}
    best = max(pairs, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0))
    created = [p.get("pairCreatedAt") for p in pairs if p.get("pairCreatedAt")]
    pc = best.get("priceChange") or {}
    return {"ok": True, "chain": best.get("chainId") or chain, "ca": ca,
            "ticker": (best.get("baseToken") or {}).get("symbol"), "name": (best.get("baseToken") or {}).get("name"),
            "mcap": best.get("marketCap"), "fdv": best.get("fdv"), "liquidity": (best.get("liquidity") or {}).get("usd"),
            "h1": pc.get("h1"), "h24": pc.get("h24"), "price_usd": best.get("priceUsd"),
            "pair_created_ms": min(created) if created else None, "pair_url": best.get("url"), "dex": best.get("dexId")}


# ---------------------------------------------------------------- majors
def majors():
    try:
        meta, ctxs = http_json("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
        out = {}
        for u, c in zip(meta["universe"], ctxs):
            if u["name"] in ("BTC", "ETH", "SOL"):
                px, prev = float(c["markPx"]), float(c["prevDayPx"])
                out[u["name"]] = {"price": px, "chg24": (px / prev - 1) * 100}
        if len(out) == 3:
            return {"source": "Hyperliquid perp mark price", "source_url": "https://app.hyperliquid.xyz", "data": out}
    except Exception as e:
        err = str(e)
    try:
        j = http_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true")
        m = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
        return {"source": "CoinGecko spot", "source_url": "https://www.coingecko.com",
                "data": {k: {"price": j[v]["usd"], "chg24": j[v]["usd_24h_change"]} for k, v in m.items()}}
    except Exception:
        pass
    try:  # Coinbase Exchange 24h stats: open = price 24h ago, last = latest trade
        def cb(sym):
            j = http_json(f"https://api.exchange.coinbase.com/products/{sym}-USD/stats")
            last, opn = float(j["last"]), float(j["open"])
            return sym, {"price": last, "chg24": (last / opn - 1) * 100}
        with ThreadPoolExecutor(3) as ex:
            data = dict(ex.map(cb, ["BTC", "ETH", "SOL"]))
        return {"source": "Coinbase spot", "source_url": "https://www.coinbase.com/explore", "data": data}
    except Exception as e:
        return {"source": None, "error": f"Hyperliquid, CoinGecko and Coinbase all failed: {e}"}


# ---------------------------------------------------------------- tally
def read_calls(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def most_mentioned(calls, now, hours=24):
    cutoff = now - timedelta(hours=hours)
    groups = {}
    for c in calls:
        t = datetime.fromisoformat(c["time_utc"].replace("Z", "+00:00"))
        if t < cutoff:
            continue
        g = groups.setdefault((c.get("chain"), c["ca"].lower()), {"ticker": c.get("ticker"), "chain": c.get("chain"),
                                                                  "ca": c["ca"], "handles": set(), "mentions": 0})
        g["ticker"] = g["ticker"] or c.get("ticker")
        g["handles"].add(c["handle"])
        g["mentions"] += 1
    rows = sorted(groups.values(), key=lambda g: (-len(g["handles"]), -g["mentions"], g["ticker"] or ""))
    return [{**g, "handles": sorted(g["handles"]), "distinct": len(g["handles"])} for g in rows]


# ---------------------------------------------------------------- on-chain enrichment (v3, merged from clawd)
# Every figure carries {"source": ..., "as_of_utc": ...}. Anything a source does not return is left out, never guessed.
import base64, hashlib, struct

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_API = "https://frontend-api-v3.pump.fun/coins-v2/{}"
SOLANA_RPCS = ["https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"]
MUSEBOOK = "https://musebook.trade"
GOPLUS_CHAIN_IDS = {"ethereum": "1", "bsc": "56", "base": "8453", "arbitrum": "42161", "polygon": "137",
                    "avalanche": "43114", "robinhood": "4663", "blast": "81457", "sonic": "146", "abstract": "2741",
                    "monad": "143", "linea": "59144", "unichain": "130", "tron": "tron"}
# heuristic thresholds (printed with the flags so readers see the rule, not a verdict)
TH_LIQ_MC = 0.05        # liquidity under 5% of market cap = thin
TH_NEW_PAIR_H = 24      # oldest pair younger than 24h
TH_TOP10 = 30.0         # top-10 non-pool holders above 30% of supply
TH_TAX = 10.0           # EVM buy/sell tax above 10%


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or now_utc()).isoformat(timespec="seconds")


def dubai_hhmm(iso_str):
    try:
        return hhmm(to_dubai(iso_str))
    except Exception:
        return None


def b58decode(s):
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + b


def b58encode(b):
    n, s = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


_P = 2 ** 255 - 19
_D = -121665 * pow(121666, _P - 2, _P) % _P


def _on_curve(b):  # ed25519 point-decompression check, used to find program-derived addresses
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    u, v = (y * y - 1) % _P, (_D * y * y + 1) % _P
    x2 = u * pow(v, _P - 2, _P) % _P
    if x2 == 0:
        return True
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * pow(2, (_P - 1) // 4, _P) % _P
    return (x * x - x2) % _P == 0


def find_pda(seeds, program):
    pid = b58decode(program)
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"".join(seeds) + bytes([bump]) + pid + b"ProgramDerivedAddress").digest()
        if not _on_curve(h):
            return b58encode(h)
    return None


def http_get(url, timeout=20, tries=2, data=None, headers=None):
    """Like http_json but short retries; returns (json, error_string)."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                         headers={**UA, "User-Agent": "Mozilla/5.0 trenches-report/3.0",
                                                  **({"Content-Type": "application/json"} if data is not None else {}),
                                                  **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode()), None
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:  # noqa
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (i + 1))
    return None, last


def solana_accounts(addresses):
    """getMultipleAccounts (base64) across public RPCs. Returns ({addr: bytes|None}, rpc_url, error)."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
            "params": [addresses, {"encoding": "base64", "commitment": "confirmed"}]}
    err = None
    for rpc in SOLANA_RPCS:
        j, e = http_get(rpc, data=body, timeout=20, tries=2)
        if j and "result" in j:
            vals = j["result"]["value"]
            return {a: (base64.b64decode(v["data"][0]) if v else None) for a, v in zip(addresses, vals)}, rpc, None
        err = e or (j or {}).get("error")
    return None, None, f"Solana RPC unavailable ({err})"


def _u64(b, off):
    return struct.unpack_from("<Q", b, off)[0]


def parse_mint(b):
    """SPL / Token-2022 base mint layout (first 82 bytes)."""
    if not b or len(b) < 82:
        return None
    mint_auth = b58encode(b[4:36]) if struct.unpack_from("<I", b, 0)[0] else None
    freeze_auth = b58encode(b[50:82]) if struct.unpack_from("<I", b, 46)[0] else None
    return {"mint_authority": mint_auth, "freeze_authority": freeze_auth, "supply_raw": _u64(b, 36), "decimals": b[44]}


def parse_bonding_curve(b):
    if not b or len(b) < 49:
        return None
    out = {"virtual_token_reserves": _u64(b, 8), "virtual_sol_reserves": _u64(b, 16), "real_token_reserves": _u64(b, 24),
           "real_sol_reserves": _u64(b, 32), "token_total_supply": _u64(b, 40), "complete": bool(b[48])}
    if len(b) >= 81:
        out["creator"] = b58encode(b[49:81])
    if len(b) >= 82:
        out["mayhem_mode"] = bool(b[81])
    # newer curves can be quoted in a token other than SOL; quote mint sits at offset 83 (all zeros = SOL)
    if len(b) >= 115 and any(b[83:115]):
        out["quote_mint"] = b58encode(b[83:115])
    return out


def parse_pump_global(b):  # disc(8) initialized(1) authority(32) fee_recipient(32) init_vtok init_vsol init_rtok supply
    if not b or len(b) < 105:
        return None
    return {"initial_virtual_token_reserves": _u64(b, 73), "initial_virtual_sol_reserves": _u64(b, 81),
            "initial_real_token_reserves": _u64(b, 89), "token_total_supply": _u64(b, 97)}


def pump_info(ca, sol_usd=None):
    """pump.fun bonding-curve state: on-chain (Solana RPC) first, pump.fun frontend API as a second source."""
    out = {}
    curve_addr = find_pda([b"bonding-curve", b58decode(ca)], PUMP_PROGRAM)
    global_addr = find_pda([b"global"], PUMP_PROGRAM)
    accts, rpc, err = solana_accounts([curve_addr, global_addr, ca])
    t = iso()
    if accts is not None:
        mint = parse_mint(accts.get(ca))
        if mint:
            out["mint"] = {**mint, "source": f"Solana RPC ({rpc.split('//')[1]})", "as_of_utc": t}
        bc, gl = parse_bonding_curve(accts.get(curve_addr)), parse_pump_global(accts.get(global_addr))
        if bc is None:
            out["curve"] = {"exists": False, "note": "no pump.fun bonding-curve account for this mint",
                            "source": "Solana RPC", "as_of_utc": t}
        else:
            c = {"exists": True, "address": curve_addr, "complete": bc["complete"], "source": f"Solana RPC ({rpc.split('//')[1]}), pump.fun program account", "as_of_utc": t}
            if bc.get("mayhem_mode"):
                c["mayhem_mode"] = True  # different curve mechanics: progress / SOL-in-curve not comparable, omitted
            if bc.get("quote_mint"):
                c["quote_mint"] = bc["quote_mint"]  # reserves are in that token's units: SOL figures omitted
            elif not bc.get("mayhem_mode"):
                c["real_sol_in_curve"] = bc["real_sol_reserves"] / 1e9
            if bc.get("creator"):
                c["creator"] = bc["creator"]
            if bc["complete"]:
                c["progress_pct"] = 100.0
                c["status"] = "graduated (curve complete, trading on AMM)"
            else:
                c["status"] = "on bonding curve"
                if gl and gl["initial_real_token_reserves"] and not bc.get("mayhem_mode"):
                    init = gl["initial_real_token_reserves"]
                    c["progress_pct"] = round(max(0.0, (init - bc["real_token_reserves"]) / init * 100), 2)
                    c["progress_formula"] = "(initial_real_token_reserves - real_token_reserves) / initial_real_token_reserves, from the pump.fun Global account"
                if bc["virtual_token_reserves"] and not bc.get("quote_mint"):
                    # pump-bonding-curve skill: marketCap = virtualSolReserves * mintSupply / virtualTokenReserves (mintSupply 1e15 = 1B @ 6dp)
                    mc_sol = bc["virtual_sol_reserves"] * 1_000_000_000_000_000 / bc["virtual_token_reserves"] / 1e9
                    c["curve_mcap_sol"] = round(mc_sol, 2)
                    if sol_usd:
                        c["curve_mcap_usd"] = round(mc_sol * sol_usd["price"])
                        c["sol_usd_source"] = sol_usd["source"]
            out["curve"] = c
    else:
        out["curve_error"] = err
    j, e = http_get(PUMP_API.format(ca), timeout=15, tries=2)
    if j and j.get("mint") == ca:
        api = {"source": "pump.fun frontend API v3", "as_of_utc": iso(), "complete": j.get("complete")}
        for k in ("pump_swap_pool", "raydium_pool", "creator", "is_banned", "reply_count"):
            if j.get(k) not in (None, ""):
                api[k] = j[k]
        if j.get("created_timestamp"):
            api["created_utc"] = iso(datetime.fromtimestamp(j["created_timestamp"] / 1000, tz=timezone.utc))
        out["pump_api"] = api
    elif e and "404" not in e:
        out["pump_api_error"] = e
    return out


def musebook_snapshot(ca):
    j, e = http_get(f"{MUSEBOOK}/api/decide/snapshot?mint={ca}", timeout=45, tries=2)
    if not j or "sources" not in j:
        return {"error": e or (j or {}).get("error") or "no data"}
    keep = ("priceUsd", "change1h", "change24h", "liquidityUsd", "volume24hUsd", "buys24h", "sells24h",
            "mintAuthorityDisabled", "freezeAuthorityDisabled", "topHoldersPercent")
    srcs = []
    for s in j["sources"]:
        if s.get("available"):
            d = {k: s[k] for k in keep if s.get(k) is not None}
            if d:
                srcs.append({"provider": s["id"], "observed_utc": s.get("observedAt") or s.get("fetchedAt"), **d})
    if not srcs:
        return {"error": "snapshot returned no usable provider data", "warnings": j.get("warnings")}
    out = {"source": "Musebook decide snapshot", "url": f"{MUSEBOOK}/api/decide/snapshot?mint={ca}",
           "as_of_utc": j.get("fetchedAt"), "providers": srcs, "gates": j.get("gates") or []}
    if (j.get("launch") or {}).get("matched"):
        out["clawd_launch_match"] = j["launch"]["matched"]
    return out


def rugcheck(ca):
    rep, e1 = http_get(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report", timeout=30, tries=2)
    summ, e2 = http_get(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report/summary", timeout=20, tries=2)
    if not rep and not summ:
        return {"error": e1 or e2}
    out = {"source": "RugCheck API", "as_of_utc": iso(), "url": f"https://rugcheck.xyz/tokens/{ca}"}
    if summ:
        for k in ("score_normalised", "lpLockedPct"):
            if summ.get(k) is not None:
                out[k] = summ[k]
        out["risks"] = [{"name": r.get("name"), "level": r.get("level")} for r in summ.get("risks") or []]
    if rep:
        out["mint_authority"] = rep.get("mintAuthority")
        out["freeze_authority"] = rep.get("freezeAuthority")
        for k in ("rugged", "totalHolders", "graphInsidersDetected"):
            if rep.get(k) is not None:
                out[k] = rep[k]
        known = rep.get("knownAccounts") or {}
        holders = rep.get("topHolders") or []
        pools = {a for a, v in known.items() if (v or {}).get("type") in ("AMM", "LOCKER")}
        for m in rep.get("markets") or []:
            for k in ("liquidityA", "liquidityB", "pubkey"):
                if m.get(k):
                    pools.add(m[k])
        non_pool = [h for h in holders if h.get("owner") not in pools and h.get("address") not in pools]
        if holders:
            out["top10_pct_excl_pools"] = round(sum(h.get("pct") or 0 for h in non_pool[:10]), 2)
            out["top10_insider_flags"] = sum(1 for h in non_pool[:10] if h.get("insider"))
        if "risks" not in out:
            out["risks"] = [{"name": r.get("name"), "level": r.get("level")} for r in rep.get("risks") or []]
    return out


def goplus(chain, ca):
    cid = GOPLUS_CHAIN_IDS.get(chain)
    if chain == "solana":
        url = f"https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={ca}"
    elif cid:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{cid}?contract_addresses={ca}"
    else:
        return {"error": f"GoPlus has no chain mapping for {chain}"}
    j, e = http_get(url, timeout=25, tries=2)
    res = ((j or {}).get("result") or {})
    d = res.get(ca) or res.get(ca.lower())
    if not d:
        return {"error": e or (j or {}).get("message") or "no data"}
    out = {"source": "GoPlus Security API", "as_of_utc": iso()}
    def flag(k):
        v = d.get(k)
        return None if v in (None, "") else v == "1"
    for k in ("is_honeypot", "cannot_sell_all", "is_mintable", "hidden_owner", "transfer_pausable", "is_open_source",
              "is_proxy", "can_take_back_ownership", "owner_change_balance"):
        v = flag(k)
        if v is not None:
            out[k] = v
    for k in ("buy_tax", "sell_tax"):
        if d.get(k) not in (None, ""):
            out[k + "_pct"] = round(float(d[k]) * 100, 2)
    if d.get("holder_count"):
        out["holder_count"] = int(d["holder_count"])
    if d.get("owner_address"):
        out["owner_address"] = d["owner_address"]
    hs = d.get("holders") or []
    if hs:
        np_ = [h for h in hs if str(h.get("is_locked")) != "1" and str(h.get("is_contract")) != "1"]
        out["top10_pct_excl_contracts_locked"] = round(sum(float(h.get("percent") or 0) for h in np_[:10]) * 100, 2)
    lp = d.get("lp_holders") or []
    if lp:
        out["lp_locked_pct"] = round(sum(float(h.get("percent") or 0) for h in lp if str(h.get("is_locked")) == "1") * 100, 2)
    return out


def risk_flags(dex, e):
    """Plain heuristic flags from what was actually returned. Each flag states its rule."""
    flags, now = [], now_utc()
    if dex and dex.get("ok"):
        mc = dex.get("mcap") or dex.get("fdv")
        if mc and dex.get("liquidity") is not None and dex["liquidity"] / mc < TH_LIQ_MC:
            flags.append(f"thin liquidity: liq/MC {dex['liquidity'] / mc:.1%} (< {TH_LIQ_MC:.0%}) [DexScreener]")
        if dex.get("pair_created_ms"):
            age_h = (now - datetime.fromtimestamp(dex["pair_created_ms"] / 1000, tz=timezone.utc)).total_seconds() / 3600
            if age_h < TH_NEW_PAIR_H:
                flags.append(f"new pair: {int(age_h)}h {int(age_h % 1 * 60)}m old (< {TH_NEW_PAIR_H}h) [DexScreener]")
    mint = (e.get("pump") or {}).get("mint")
    rc = e.get("rugcheck") or {}
    if mint:
        if mint.get("mint_authority"):
            flags.append("mint authority still set [Solana RPC]")
        if mint.get("freeze_authority"):
            flags.append("freeze authority still set [Solana RPC]")
    elif rc and "error" not in rc:
        if rc.get("mint_authority"):
            flags.append("mint authority still set [RugCheck]")
        if rc.get("freeze_authority"):
            flags.append("freeze authority still set [RugCheck]")
    if rc.get("top10_pct_excl_pools", 0) > TH_TOP10:
        flags.append(f"top-10 holders {rc['top10_pct_excl_pools']}% excl. pools (> {TH_TOP10:.0f}%) [RugCheck]")
    if rc.get("rugged"):
        flags.append("RugCheck marks token as rugged [RugCheck]")
    for r in rc.get("risks") or []:
        if (r.get("level") or "").lower() == "danger":
            flags.append(f"RugCheck danger: {r['name']} [RugCheck]")
    gp = e.get("goplus") or {}
    if gp and "error" not in gp:
        for k, label in (("is_honeypot", "honeypot"), ("cannot_sell_all", "cannot sell all"), ("is_mintable", "mintable"),
                         ("hidden_owner", "hidden owner"), ("transfer_pausable", "transfers pausable"),
                         ("can_take_back_ownership", "ownership can be reclaimed"), ("owner_change_balance", "owner can change balances")):
            if gp.get(k):
                flags.append(f"{label} [GoPlus]")
        for k in ("buy_tax_pct", "sell_tax_pct"):
            if gp.get(k, 0) > TH_TAX:
                flags.append(f"{k.split('_')[0]} tax {gp[k]}% (> {TH_TAX:.0f}%) [GoPlus]")
        if gp.get("top10_pct_excl_contracts_locked", 0) > TH_TOP10:
            flags.append(f"top-10 holders {gp['top10_pct_excl_contracts_locked']}% excl. contracts/locked (> {TH_TOP10:.0f}%) [GoPlus]")
    return flags


def enrich_ca(chain, ca, dex=None, sol_usd=None):
    """All keyless enrichment for one CA. Solana: pump.fun curve, Musebook snapshot, RugCheck (GoPlus fallback).
    EVM: GoPlus. Always: DexScreener-derived heuristics."""
    e = {"chain": chain, "ca": ca, "started_utc": iso()}
    is_sol = chain == "solana" or (chain is None and not ca.startswith("0x"))
    if is_sol:
        with ThreadPoolExecutor(3) as ex:
            fp, fm, fr = ex.submit(pump_info, ca, sol_usd), ex.submit(musebook_snapshot, ca), ex.submit(rugcheck, ca)
            e["pump"], e["musebook"], e["rugcheck"] = fp.result(), fm.result(), fr.result()
        if "error" in e["rugcheck"]:
            e["goplus"] = goplus("solana", ca)
    elif chain:
        e["goplus"] = goplus(chain, ca)
    liq_mc = None
    if dex and dex.get("ok") and (dex.get("mcap") or dex.get("fdv")) and dex.get("liquidity") is not None:
        liq_mc = round(dex["liquidity"] / (dex.get("mcap") or dex.get("fdv")), 4)
    e["dex_derived"] = {"liq_to_mcap": liq_mc, "pair_created_ms": (dex or {}).get("pair_created_ms"),
                        "source": "DexScreener", "as_of_utc": (dex or {}).get("fetched_utc") or iso()} if dex and dex.get("ok") else None
    e["flags"] = risk_flags(dex, e)
    return e


def enrich_lines(e, dex=None):
    """Markdown sub-bullets for one enriched CA. Labels every figure with its source and local (DD_TZ) time."""
    L = []
    p = e.get("pump") or {}
    c = p.get("curve")
    if c and c.get("exists"):
        s = f"pump.fun curve: {c['status']}"
        if not c["complete"] and c.get("progress_pct") is not None:
            s += f", {c['progress_pct']:.1f}% to graduation"
        if c.get("curve_mcap_sol") is not None:
            s += f", curve MC {c['curve_mcap_sol']:,.1f} SOL" + (f" (~{fmt_usd(c['curve_mcap_usd'])}; SOL price: {c['sol_usd_source']})" if c.get("curve_mcap_usd") else "")
        s += f", {c['real_sol_in_curve']:,.2f} SOL in curve" if not c["complete"] and c.get("real_sol_in_curve") is not None else ""
        s += f", quoted in non-SOL token `{c['quote_mint'][:6]}…` (SOL figures omitted)" if c.get("quote_mint") else ""
        s += ", Mayhem-mode curve (progress not comparable, omitted)" if c.get("mayhem_mode") else ""
        api = p.get("pump_api") or {}
        if api.get("pump_swap_pool"):
            s += f"; PumpSwap pool `{api['pump_swap_pool'][:6]}…` per pump.fun API"
        elif api.get("raydium_pool"):
            s += f"; Raydium pool `{api['raydium_pool'][:6]}…` per pump.fun API"
        L.append(f"  - {s} [Solana RPC, {dubai_hhmm(c['as_of_utc'])} {TZL}]")
    elif c and not c.get("exists"):
        L.append(f"  - Not a pump.fun bonding-curve token (no curve account) [Solana RPC, {dubai_hhmm(c['as_of_utc'])} {TZL}]")
    m = p.get("mint")
    if m:
        L.append(f"  - Mint authority {'SET' if m['mint_authority'] else 'revoked'}, freeze authority {'SET' if m['freeze_authority'] else 'revoked'} [Solana RPC, {dubai_hhmm(m['as_of_utc'])} {TZL}]")
    mb = e.get("musebook") or {}
    if mb.get("providers"):
        for pr in mb["providers"]:
            bits = []
            if pr.get("liquidityUsd") is not None:
                bits.append(f"liq {fmt_usd(pr['liquidityUsd'])}")
            if pr.get("volume24hUsd") is not None:
                bits.append(f"24h vol {fmt_usd(pr['volume24hUsd'])}")
            if pr.get("buys24h") is not None and pr.get("sells24h") is not None:
                bits.append(f"24h buys/sells {pr['buys24h']:,}/{pr['sells24h']:,}")
            if pr.get("change1h") is not None:
                bits.append(f"1h {fmt_pct(pr['change1h'])}")
            if pr.get("topHoldersPercent") is not None:
                bits.append(f"top holders {pr['topHoldersPercent']:.1f}%")
            if pr.get("mintAuthorityDisabled") is not None:
                bits.append("mint " + ("disabled" if pr["mintAuthorityDisabled"] else "ENABLED"))
            if pr.get("freezeAuthorityDisabled") is not None:
                bits.append("freeze " + ("disabled" if pr["freezeAuthorityDisabled"] else "ENABLED"))
            L.append(f"  - Musebook snapshot via {pr['provider']}: {', '.join(bits)} [observed {dubai_hhmm(pr['observed_utc'])} {TZL}]")
    rc = e.get("rugcheck") or {}
    if rc and "error" not in rc:
        bits = []
        if rc.get("score_normalised") is not None:
            bits.append(f"risk score {rc['score_normalised']} (RugCheck normalised; lower = fewer risks)")
        if rc.get("lpLockedPct") is not None:
            bits.append(f"LP locked {rc['lpLockedPct']:.0f}%")
        if rc.get("top10_pct_excl_pools") is not None:
            bits.append(f"top-10 holders {rc['top10_pct_excl_pools']}% excl. pools")
        if rc.get("totalHolders") is not None:
            bits.append(f"{rc['totalHolders']:,} holders")
        if rc.get("graphInsidersDetected"):
            bits.append(f"{rc['graphInsidersDetected']} insider wallets detected")
        if rc.get("risks"):
            bits.append("risks: " + ", ".join(f"{r['name']} ({r['level']})" for r in rc["risks"]))
        L.append(f"  - {'; '.join(bits)} [RugCheck, {dubai_hhmm(rc['as_of_utc'])} {TZL}]")
    gp = e.get("goplus") or {}
    if gp and "error" not in gp:
        bits = []
        for k, lab in (("is_honeypot", "honeypot"), ("is_mintable", "mintable"), ("is_open_source", "verified source")):
            if k in gp:
                bits.append(f"{lab} {'yes' if gp[k] else 'no'}")
        for k in ("buy_tax_pct", "sell_tax_pct"):
            if k in gp:
                bits.append(f"{k.split('_')[0]} tax {gp[k]}%")
        if "holder_count" in gp:
            bits.append(f"{gp['holder_count']:,} holders")
        if "top10_pct_excl_contracts_locked" in gp:
            bits.append(f"top-10 holders {gp['top10_pct_excl_contracts_locked']}% excl. contracts/locked")
        if "lp_locked_pct" in gp:
            bits.append(f"LP locked {gp['lp_locked_pct']}%")
        L.append(f"  - {'; '.join(bits)} [GoPlus, {dubai_hhmm(gp['as_of_utc'])} {TZL}]")
    L.append("  - Risk flags (heuristics, not a verdict): " + ("; ".join(e["flags"]) if e["flags"] else "none triggered"))
    return L


def enrich_errors(e):
    errs = []
    p = e.get("pump") or {}
    for k in ("curve_error", "pump_api_error"):
        if p.get(k):
            errs.append(f"{k}: {p[k]}")
    for k in ("musebook", "rugcheck", "goplus"):
        if isinstance(e.get(k), dict) and e[k].get("error"):
            errs.append(f"{k}: {e[k]['error']}")
    return errs


def enrich_many(cas, dex_map=None, sol_usd=None, workers=4):
    dex_map = dex_map or {}
    with ThreadPoolExecutor(workers) as ex:
        return dict(zip([c["ca"].lower() for c in cas],
                        ex.map(lambda c: enrich_ca(c.get("chain"), c["ca"], dex_map.get(c["ca"].lower()), sol_usd), cas)))


# ---------------------------------------------------------------- scan / launches (cross-reference X chatter with on-chain movement)
def dex_batch(chain, addresses):
    """DexScreener /tokens/v1 batch (<=30 per call). Returns {addr_lower: summary}."""
    out = {}
    for i in range(0, len(addresses), 30):
        chunk = addresses[i:i + 30]
        j, e = http_get(f"https://api.dexscreener.com/tokens/v1/{chain}/{','.join(chunk)}", timeout=25, tries=3)
        for p in j or []:
            a = ((p.get("baseToken") or {}).get("address") or "").lower()
            if a not in [c.lower() for c in chunk]:
                continue
            cur = out.get(a)
            if cur is None or ((p.get("liquidity") or {}).get("usd") or 0) > (cur["liquidity"] or 0):
                pc, tx = p.get("priceChange") or {}, (p.get("txns") or {}).get("h24") or {}
                out[a] = {"chain": chain, "ca": (p.get("baseToken") or {}).get("address"),
                          "ticker": (p.get("baseToken") or {}).get("symbol"), "name": (p.get("baseToken") or {}).get("name"),
                          "mcap": p.get("marketCap") or p.get("fdv"), "mcap_is_fdv": not p.get("marketCap"),
                          "liquidity": (p.get("liquidity") or {}).get("usd"), "buys24": tx.get("buys"), "sells24": tx.get("sells"),
                          "vol24": (p.get("volume") or {}).get("h24"), "h1": pc.get("h1"), "h6": pc.get("h6"), "h24": pc.get("h24"),
                          "pair_created_ms": p.get("pairCreatedAt"), "url": p.get("url"), "dex": p.get("dexId")}
    return out


def passes_scan(d, min_liq, min_mc, min_buys):
    return bool(d and (d.get("liquidity") or 0) >= min_liq and (d.get("mcap") or 0) >= min_mc and (d.get("buys24") or 0) >= min_buys)


def mention_index(calls_path, run_path=None, hours=24):
    """CAs and tickers mentioned by the tracked accounts: calls.jsonl (last N hours) + the latest run's posts."""
    now = now_utc()
    by_ca, by_tag = {}, {}
    for c in read_calls(calls_path):
        t = datetime.fromisoformat(c["time_utc"].replace("Z", "+00:00"))
        if t < now - timedelta(hours=hours):
            continue
        r = by_ca.setdefault(c["ca"].lower(), {"ca": c["ca"], "chain": c.get("chain"), "ticker": c.get("ticker"), "handles": set(), "posts": set(), "src": set()})
        r["handles"].add(c["handle"]); r["posts"].add(c["post_url"]); r["src"].add("calls.jsonl")
        if c.get("ticker"):
            by_tag.setdefault(c["ticker"].upper(), {"handles": set(), "posts": set(), "src": set()})
            by_tag[c["ticker"].upper()]["handles"].add(c["handle"]); by_tag[c["ticker"].upper()]["posts"].add(c["post_url"]); by_tag[c["ticker"].upper()]["src"].add("calls.jsonl")
    if run_path is None:
        runs = sorted((os.path.join(HERE, "runs", f) for f in os.listdir(os.path.join(HERE, "runs")) if re.match(r"run_.*\.json$", f)),
                      key=os.path.getmtime)
        run_path = runs[-1] if runs else None
    if run_path and os.path.exists(run_path):
        run = json.load(open(run_path))
        for p in run.get("posts") or []:
            for c in p.get("cas") or []:
                r = by_ca.setdefault(c["ca"].lower(), {"ca": c["ca"], "chain": c.get("chain"), "ticker": None, "handles": set(), "posts": set(), "src": set()})
                r["handles"].add(p["handle"]); r["posts"].add(p["url"]); r["src"].add(os.path.basename(run_path))
            if len(p.get("cashtags") or []) <= 4:
                for t in p.get("cashtags") or []:
                    g = by_tag.setdefault(t.upper(), {"handles": set(), "posts": set(), "src": set()})
                    g["handles"].add(p["handle"]); g["posts"].add(p["url"]); g["src"].add(os.path.basename(run_path))
    return by_ca, by_tag, run_path


def _mv(d):
    """Only the fields DexScreener actually returned."""
    bits = []
    if d.get("mcap") is not None:
        bits.append(f"{'FDV' if d.get('mcap_is_fdv') else 'MC'} {fmt_usd(d['mcap'])}")
    if d.get("liquidity") is not None:
        bits.append(f"liq {fmt_usd(d['liquidity'])}")
    if d.get("buys24") is not None:
        bits.append(f"24h buys {d['buys24']:,}")
    for k in ("h1", "h6", "h24"):
        if d.get(k) is not None:
            bits.append(f"{k} {fmt_pct(d[k])}")
    return ", ".join(bits) or "no pair figures returned"


def pump_curves_batch(mints):
    """One getMultipleAccounts call for many pump.fun curves (launch snapshots). Returns ({mint: info}, error)."""
    mints = [m for m in mints if m and m.endswith("pump")][:99]
    if not mints:
        return {}, None
    curves = {m: find_pda([b"bonding-curve", b58decode(m)], PUMP_PROGRAM) for m in mints}
    g = find_pda([b"global"], PUMP_PROGRAM)
    accts, rpc, err = solana_accounts(list(curves.values()) + [g])
    if accts is None:
        return {}, err
    gl, t, out = parse_pump_global(accts.get(g)), iso(), {}
    for m, ca in curves.items():
        bc = parse_bonding_curve(accts.get(ca))
        if not bc:
            continue
        info = {"complete": bc["complete"], "source": f"Solana RPC ({rpc.split('//')[1]})", "as_of_utc": t}
        if bc.get("mayhem_mode"):
            info["mayhem_mode"] = True
        if bc.get("quote_mint"):
            info["quote_mint"] = bc["quote_mint"]
        elif not bc.get("mayhem_mode"):
            info["real_sol_in_curve"] = bc["real_sol_reserves"] / 1e9
        if not bc["complete"] and gl and gl["initial_real_token_reserves"] and not bc.get("mayhem_mode"):
            init = gl["initial_real_token_reserves"]
            info["progress_pct"] = round(max(0.0, (init - bc["real_token_reserves"]) / init * 100), 2)
        if bc["virtual_token_reserves"] and not bc.get("quote_mint"):
            info["curve_mcap_sol"] = round(bc["virtual_sol_reserves"] * 1_000_000_000_000_000 / bc["virtual_token_reserves"] / 1e9, 2)
        out[m] = info
    return out, None


def _who(m):
    return ", ".join(f"[@{h}](https://x.com/{h})" for h in sorted(m["handles"])) + f" ({len(m['posts'])} post(s), from {', '.join(sorted(m['src']))})"


def scan(args):
    t0 = now_utc()
    stamp = run_stamp("scan")
    sources, errors = {}, []
    latest, e1 = http_get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=25, tries=3)
    top, e2 = http_get("https://api.dexscreener.com/token-boosts/top/v1", timeout=25, tries=3)
    pulse, e3 = http_get(f"{MUSEBOOK}/api/pulse", timeout=25)
    tokens, e4 = http_get(f"{MUSEBOOK}/live/tokens.json", timeout=25)
    trending, e5 = http_get(f"{MUSEBOOK}/api/v1/trending", timeout=25)
    for name, val, err in (("dexscreener_boosts_latest", latest, e1), ("dexscreener_boosts_top", top, e2),
                           ("musebook_pulse_boosts", pulse, e3), ("musebook_live_tokens", tokens, e4), ("musebook_v1_trending", trending, e5)):
        if err:
            errors.append(f"{name}: {err}")
    cand = {}  # (chain, addr_lower) -> {"chain","ca","seen_in":set,"boost":...}
    def add(chain, ca, src, extra=None):
        if not chain or not ca:
            return
        k = (chain, ca.lower())
        c = cand.setdefault(k, {"chain": chain, "ca": ca, "seen_in": set()})
        c["seen_in"].add(src)
        if extra:
            c.update(extra)
    for b in latest or []:
        add(b.get("chainId"), b.get("tokenAddress"), "DexScreener boosts (latest)", {"boost_amount": b.get("totalAmount") or b.get("amount")})
    for b in top or []:
        add(b.get("chainId"), b.get("tokenAddress"), "DexScreener boosts (top)", {"boost_amount": b.get("totalAmount")})
    for b in (pulse or {}).get("boosts") or []:
        add("solana", b.get("address"), "Musebook pulse boosts")
    for t in (tokens or {}).get("tokens") or []:
        add("solana", t.get("mint"), "Musebook live tokens")
    sources = {"dexscreener_boosts_latest": len(latest or []), "dexscreener_boosts_top": len(top or []),
               "musebook_pulse_boosts": len((pulse or {}).get("boosts") or []),
               "musebook_pulse_generated_at": (pulse or {}).get("generated_at"), "musebook_pulse_stale": (pulse or {}).get("stale"),
               "musebook_live_tokens": len((tokens or {}).get("tokens") or []), "musebook_live_tokens_generated_at": (tokens or {}).get("generated_at"),
               "musebook_v1_trending_items": len((trending or {}).get("trending") or []),
               "musebook_v1_trending_note": "returns Musebook agent-directory profiles (no token mints), so it can't be matched to CAs" if trending else None}
    if args.chain != "all":
        cand = {k: v for k, v in cand.items() if k[0] == args.chain}
    by_ca, by_tag, run_path = mention_index(args.calls, args.run, args.hours)
    # also evaluate every called CA against the same filters
    for k, m in by_ca.items():
        if m.get("chain") and m["chain"] not in ("evm?",):
            add(m["chain"], m["ca"], "tracked-account call")
    by_chain = {}
    for (chain, _), c in cand.items():
        by_chain.setdefault(chain, []).append(c["ca"])
    dex = {}
    with ThreadPoolExecutor(4) as ex:
        for res in ex.map(lambda kv: dex_batch(kv[0], kv[1]), by_chain.items()):
            dex.update(res)
    as_of = iso()
    qualifying, called_movers, ticker_hits = [], [], []
    for (chain, k), c in cand.items():
        d = dex.get(k)
        if not passes_scan(d, args.min_liq, args.min_mcap, args.min_buys):
            continue
        row = {**d, "seen_in": sorted(c["seen_in"]), "boost_amount": c.get("boost_amount")}
        qualifying.append(row)
        if k in by_ca:
            called_movers.append({**row, "match": "CA", "mentions": by_ca[k]})
        elif (d.get("ticker") or "").upper() in by_tag and "tracked-account call" not in c["seen_in"]:
            ticker_hits.append({**row, "match": "ticker only (ambiguous)", "mentions": by_tag[(d.get("ticker") or "").upper()]})
    key = lambda r: -(r.get(args.sort) or -1e9)
    qualifying.sort(key=key); called_movers.sort(key=key); ticker_hits.sort(key=key)
    L = [f"# Scan {t0.astimezone(DUBAI).strftime('%Y-%m-%d %-I:%M %p')} {TZL}",
         f"Filters (clawd boost-scan rule): liquidity >= {fmt_usd(args.min_liq)}, MC >= {fmt_usd(args.min_mcap)}, 24h buys >= {args.min_buys}. "
         f"Pair figures: DexScreener, as of {dubai_hhmm(as_of)} {TZL}. Ranked by {args.sort} change.",
         f"Sources: DexScreener boosts latest {sources['dexscreener_boosts_latest']}, top {sources['dexscreener_boosts_top']}; "
         f"Musebook pulse boosts {sources['musebook_pulse_boosts']} (generated {dubai_hhmm(sources['musebook_pulse_generated_at']) if sources['musebook_pulse_generated_at'] else 'n/a'} {TZL}{', stale' if sources['musebook_pulse_stale'] else ''}); "
         f"Musebook live tokens {sources['musebook_live_tokens']}; tracked-account CAs {len(by_ca)} (calls.jsonl last {args.hours}h + {os.path.basename(run_path) if run_path else 'no run'}). "
         f"{len(cand)} candidates, {len(qualifying)} pass the filters.",
         "Boosts are paid placements: a signal, not an endorsement.", "",
         "## Movers that the tracked accounts are ALSO talking about (CA match)"]
    if not called_movers:
        L.append("None this scan.")
    for r in called_movers:
        L.append(f"- **${(r['ticker'] or '?').upper()}** [{r['ca']}]({ca_link(r['chain'], r['ca'])}) ({r['chain']}): {_mv(r)}. Seen in: {', '.join(r['seen_in'])}. Called by {_who(r['mentions'])}")
    L.append("\n## Ticker-only matches (same symbol as a cashtag the accounts used; may be a different coin)")
    if not ticker_hits:
        L.append("None this scan.")
    for r in ticker_hits[:10]:
        L.append(f"- ${(r['ticker'] or '?').upper()} [{r['ca']}]({ca_link(r['chain'], r['ca'])}) ({r['chain']}): {_mv(r)}. Mentioned by {_who(r['mentions'])}")
    L.append(f"\n## Top {args.top} boosted/trending movers passing the filters (context, not called)")
    others = [r for r in qualifying if "tracked-account call" not in r["seen_in"]]
    if not others:
        L.append("None this scan.")
    for r in others[:args.top]:
        L.append(f"- ${(r['ticker'] or '?').upper()} [{r['ca']}]({ca_link(r['chain'], r['ca'])}) ({r['chain']}): {_mv(r)}. Seen in: {', '.join(r['seen_in'])}")
    not_pass = [m for k, m in by_ca.items() if not passes_scan(dex.get(k), args.min_liq, args.min_mcap, args.min_buys)]
    if not_pass:
        L.append("\nCalled CAs that do NOT pass the filters: " + "; ".join(
            f"${(dex.get(m['ca'].lower()) or {}).get('ticker') or m.get('ticker') or '?'} ({_mv(dex[m['ca'].lower()]) if m['ca'].lower() in dex else 'no DexScreener pair'})" for m in not_pass))
    if sources.get("musebook_v1_trending_note"):
        L.append(f"\nNote: Musebook /api/v1/trending {sources['musebook_v1_trending_note']}.")
    if errors:
        L.append("\nSource errors: " + "; ".join(errors))
    L.append("\nNot financial advice.")
    md = "\n".join(L) + "\n"
    out = {"generated_utc": as_of, "filters": {"min_liq": args.min_liq, "min_mcap": args.min_mcap, "min_buys": args.min_buys},
           "sources": sources, "errors": errors, "run_used": run_path, "called_movers": called_movers, "ticker_hits": ticker_hits,
           "qualifying": qualifying}
    os.makedirs(os.path.join(HERE, "runs"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "runs", f"scan_{stamp}.json"), "w"), indent=1, default=sorted, ensure_ascii=False)
    open(os.path.join(HERE, "runs", f"scan_{stamp}.md"), "w").write(md)
    print(md)


def launches(args):
    t0 = now_utc()
    stamp = run_stamp("launches")
    src = "Musebook /live/tokens.json (clawd relay + Jupiter quotes)"
    j, err = http_get(f"{MUSEBOOK}/live/tokens.json", timeout=25)
    items = (j or {}).get("tokens") or []
    gen = (j or {}).get("generated_at")
    if not items:  # fallback: the same feed through Musebook's public MCP (stateless HTTP JSON-RPC, no socket)
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "live_launches", "arguments": {"limit": 25}}}
        try:
            req = urllib.request.Request(f"{MUSEBOOK}/mcp", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=25).read().decode()
            m = re.search(r"data: (\{.*\})", raw)
            res = json.loads(m.group(1) if m else raw)["result"]["content"][0]["text"]
            items = json.loads(res).get("launches") or []
            src, gen = "Musebook public MCP live_launches", iso()
        except Exception as e:
            err = f"{err}; MCP fallback: {e}"
    items = sorted(items, key=lambda t: t.get("created_at") or "", reverse=True)[:args.limit]
    dex = dex_batch("solana", [t["mint"] for t in items if t.get("mint")]) if items else {}
    curves, curve_err = pump_curves_batch([t.get("mint") for t in items])
    by_ca, by_tag, run_path = mention_index(args.calls, args.run, args.hours)
    L = [f"# pump.fun launch snapshot {t0.astimezone(DUBAI).strftime('%Y-%m-%d %-I:%M %p')} {TZL}",
         f"Source: {src}, generated {dubai_hhmm(gen) if gen else 'n/a'} {TZL}{' (stale)' if (j or {}).get('stale') else ''}. "
         f"Pair figures where a pair exists: DexScreener, as of {dubai_hhmm(iso())} {TZL}. Launch feeds sample launches; brand-new coins usually have no pair yet.", ""]
    if not items:
        L.append(f"No launches returned ({err}).")
    for t in items:
        d = dex.get((t.get("mint") or "").lower())
        bits = [f"created {dubai_hhmm(t['created_at'])} {TZL}" if t.get("created_at") else None]
        if t.get("price_usd") is not None:
            bits.append(f"price ${t['price_usd']:.3g} ({t.get('quote_source')})")
        cv = curves.get(t.get("mint"))
        if cv:
            if cv["complete"]:
                bits.append(f"curve complete/graduated [{cv['source']}]")
            else:
                cb = []
                if cv.get("progress_pct") is not None:
                    cb.append(f"{cv['progress_pct']:.1f}% to graduation")
                if cv.get("curve_mcap_sol") is not None:
                    cb.append(f"curve MC {cv['curve_mcap_sol']:,.1f} SOL")
                if cv.get("real_sol_in_curve") is not None:
                    cb.append(f"{cv['real_sol_in_curve']:.2f} SOL in curve")
                if cv.get("quote_mint"):
                    cb.append(f"quoted in non-SOL token `{cv['quote_mint'][:6]}…`")
                if cv.get("mayhem_mode"):
                    cb.append("Mayhem-mode curve (progress not comparable)")
                if cb:
                    bits.append(", ".join(cb) + f" [{cv['source']}]")
        if d and _mv(d) != "no pair figures returned":
            bits.append(f"{_mv(d)} [DexScreener]")
        hit = by_ca.get((t.get("mint") or "").lower())
        tag = by_tag.get((t.get("symbol") or "").upper())
        mention = f" **Mentioned (CA) by {_who(hit)}**" if hit else (f" Ticker matches a cashtag by {_who(tag)} (may be a different coin)." if tag else "")
        L.append(f"- {t.get('name')} (${t.get('symbol')}) [{t.get('mint')}]({ca_link('solana', t.get('mint') or '')}): {', '.join(b for b in bits if b)}.{mention}")
    if curve_err:
        L.append(f"\npump.fun curve data unavailable this run ({curve_err}).")
    L.append("\nNew launches are extremely high risk. Not financial advice.")
    md = "\n".join(L) + "\n"
    json.dump({"generated_utc": iso(), "source": src, "feed_generated_at": gen, "error": err, "launches": items, "dex": dex, "curves": curves},
              open(os.path.join(HERE, "runs", f"launches_{stamp}.json"), "w"), indent=1, ensure_ascii=False)
    open(os.path.join(HERE, "runs", f"launches_{stamp}.md"), "w").write(md)
    print(md)


def enrich_cmd(args):
    t0 = now_utc()
    stamp = run_stamp("enrich")
    cas = []
    if args.ca:
        cas = [{"chain": args.chain, "ca": a} for a in args.ca]
    else:
        seen = {}
        for c in read_calls(args.calls):
            if datetime.fromisoformat(c["time_utc"].replace("Z", "+00:00")) >= t0 - timedelta(hours=args.hours):
                seen.setdefault(c["ca"].lower(), {"chain": c.get("chain"), "ca": c["ca"]})
        cas = list(seen.values())
    for c in cas:
        if c["chain"] is None and not c["ca"].startswith("0x"):
            c["chain"] = "solana"
    with ThreadPoolExecutor(6) as ex:
        dex = dict(zip([c["ca"].lower() for c in cas], ex.map(lambda c: dex_lookup(c["chain"], c["ca"]), cas)))
        fm = ex.submit(majors)
    for d in dex.values():
        if d.get("ok"):
            d["fetched_utc"] = iso()
    maj = fm.result()
    sol = {"price": maj["data"]["SOL"]["price"], "source": maj["source"]} if maj.get("source") else None
    enr = enrich_many(cas, dex, sol)
    L = [f"# CA enrichment {t0.astimezone(DUBAI).strftime('%Y-%m-%d %-I:%M %p')} {TZL}", ""]
    for c in cas:
        k = c["ca"].lower()
        d, e = dex.get(k, {}), enr[k]
        chain = d.get("chain") or c["chain"]
        head = (f"- **${(d.get('ticker') or '?').upper()}** ({d.get('name')}), {chain}: [{c['ca']}]({ca_link(chain, c['ca'])}). "
                f"MC {fmt_usd(d.get('mcap') or d.get('fdv'))}, liq {fmt_usd(d.get('liquidity'))}, 1h {fmt_pct(d.get('h1'))}, 24h {fmt_pct(d.get('h24'))}, "
                f"pair age {fmt_age(d.get('pair_created_ms'), now_utc())} [DexScreener, {hhmm(now_utc().astimezone(DUBAI))} {TZL}]"
                if d.get("ok") else f"- **Unresolved CA** {chain}: [{c['ca']}]({ca_link(chain, c['ca'])}) ({d.get('error')})")
        L.append(head)
        L.extend(enrich_lines(e, d))
        errs = enrich_errors(e)
        if errs:
            L.append("  - Not returned: " + "; ".join(errs))
    L.append("\nNot financial advice.")
    md = "\n".join(L) + "\n"
    json.dump({"generated_utc": iso(), "majors": maj, "dex": dex, "enrich": enr},
              open(os.path.join(HERE, "runs", f"enrich_{stamp}.json"), "w"), indent=1, ensure_ascii=False, default=list)
    open(os.path.join(HERE, "runs", f"enrich_{stamp}.md"), "w").write(md)
    print(md)


# ---------------------------------------------------------------- build
def build(args):
    raw = json.load(open(args.raw))
    stamp = re.sub(r"^raw_|\.json$", "", os.path.basename(args.raw))
    outdir = os.path.dirname(os.path.abspath(args.raw))
    now = datetime.now(timezone.utc)
    posts, stats = load_posts(raw)

    uniq = {}
    for p in posts:
        for c in p["cas"]:
            uniq.setdefault(c["ca"].lower(), c)
    with ThreadPoolExecutor(max_workers=8) as ex:
        fut_major = ex.submit(majors)
        dex = dict(zip(uniq.keys(), ex.map(lambda c: dex_lookup(c["chain"], c["ca"]), uniq.values())))
        maj = fut_major.result()
    as_of = hhmm(now.astimezone(DUBAI))
    # last-good cache: if DexScreener rate-limits us (shared box IP), reuse the last successful lookup and label its time
    cache_path = os.path.join(HERE, "dex_cache.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    for k, d in dex.items():
        if d.get("ok"):
            d["as_of_dubai"] = as_of
            cache[k] = {**d, "fetched_utc": now.isoformat(timespec="seconds")}
        elif k in cache and "no pairs" not in (d.get("error") or ""):
            c = cache[k]
            dex[k] = {**c, "as_of_dubai": hhmm(to_dubai(c["fetched_utc"])), "cached": True}
    json.dump(cache, open(cache_path, "w"), indent=1)

    # v3: keyless on-chain enrichment per CA (pump.fun curve, Musebook snapshot, RugCheck/GoPlus, heuristics)
    enr = {}
    if not args.no_enrich and uniq:
        sol = {"price": maj["data"]["SOL"]["price"], "source": maj["source"]} if maj.get("source") else None
        for k, d in dex.items():
            if d.get("ok") and not d.get("cached"):
                d.setdefault("fetched_utc", now.isoformat(timespec="seconds"))
        enr = enrich_many([{"chain": (dex.get(k) or {}).get("chain") or c["chain"], "ca": c["ca"]} for k, c in uniq.items()], dex, sol)

    calls = []
    for p in sorted(posts, key=lambda x: x["created_at"]):
        for c in p["cas"]:
            d = dex.get(c["ca"].lower(), {})
            calls.append({"id": f"{p['id']}:{c['ca']}", "time_utc": p["created_at"],
                          "time_dubai": to_dubai(p["created_at"]).isoformat(), "handle": p["handle"],
                          "ticker": d.get("ticker"), "chain": d.get("chain") or c["chain"], "ca": c["ca"],
                          "post_url": p["url"], "mcap_at_call": d.get("mcap"),
                          "mcap_source": "DexScreener" if d.get("mcap") is not None else None,
                          "mcap_as_of_utc": now.isoformat(timespec="seconds") if d.get("mcap") is not None else None,
                          "logged_by": "trenches-v2"})
    # upsert into the tally: new calls are appended; existing rows only get missing fields filled
    # (the first mcap snapshot is never overwritten, so mcap_at_call stays the earliest one we captured)
    existing = read_calls(args.calls)
    idx = {c["id"]: i for i, c in enumerate(existing)}
    new = []
    for c in calls:
        if c["id"] in idx:
            e = existing[idx[c["id"]]]
            if e.get("ticker") is None and c.get("ticker"):
                e["ticker"] = c["ticker"]
            if e.get("mcap_at_call") is None and c.get("mcap_at_call") is not None:
                for k in ("mcap_at_call", "mcap_source", "mcap_as_of_utc"):
                    e[k] = c[k]
        else:
            new.append(c)
    all_calls = existing + new
    if not args.no_append:
        tmp = args.calls + ".tmp"
        with open(tmp, "w") as f:
            for c in all_calls:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        os.replace(tmp, args.calls)
    mm = most_mentioned(all_calls, now, args.hours)

    # concentration
    by_handle = {}
    for c in calls:
        by_handle[c["handle"]] = by_handle.get(c["handle"], 0) + 1
    conc = None
    if calls:
        top, n = max(by_handle.items(), key=lambda kv: kv[1])
        share = n / len(calls)
        conc = {"handle": top, "calls": n, "total": len(calls), "share": share, "flag": share > 0.4 and len(calls) >= 3}

    run = {"generated_utc": now.isoformat(timespec="seconds"), "as_of_dubai": as_of, "window": raw.get("window"),
           "stats": stats, "majors": maj, "posts": posts, "dex": dex, "calls": calls, "new_calls_logged": len(new),
           "concentration": conc, "most_mentioned": mm, "tally_total_rows": len(all_calls), "enrich": enr}
    json.dump(run, open(os.path.join(outdir, f"run_{stamp}.json"), "w"), indent=1, ensure_ascii=False, default=list)
    md = blocks(run)
    open(os.path.join(outdir, f"blocks_{stamp}.md"), "w").write(md)
    print(md)


def blocks(run):
    L = []
    s, w = run["stats"], run["window"] or {}
    ws, we = (hhmm(to_dubai(w["start"])), hhmm(to_dubai(w["end"]))) if w.get("start") else ("?", "?")
    L.append(f"<!-- window {ws}–{we} {TZL} · per-list results {s['per_list']} · raw {s['raw_total']} → unique {s['unique']}"
             f" → kept {s['kept']} (dropped {s['dropped_replies_rts']} replies/RTs, {len(s['dropped_offtopic'])} off-topic)"
             f" · capped lists: {s['capped_lists'] or 'none'} -->")
    L.append("\n## MAJORS PRICE LINE")
    m = run["majors"]
    if m.get("source"):
        parts = [f"{k} {fmt_usd(v['price']) if v['price'] < 1000 else '$' + format(round(v['price']), ',')} ({fmt_pct(v['chg24'])} 24h)"
                 for k, v in m["data"].items()]
        L.append(f"{', '.join(parts)}. Source: [{m['source']}]({m['source_url']}), as of {run['as_of_dubai']} {TZL}.")
    else:
        L.append(f"Prices unavailable this run ({m.get('error')}).")

    L.append("\n## CALLS & CAs")
    L.append(f"Figures: DexScreener, as of {run['as_of_dubai']} {TZL}.\n")
    order, groups = [], {}
    for c in run["calls"]:
        k = c["ca"].lower()
        if k not in groups:
            order.append(k)
            groups[k] = []
        groups[k].append(c)
    for k in sorted(order, key=lambda k: (-len({c['handle'] for c in groups[k]}), -len(groups[k]))):
        cs, d = groups[k], run["dex"].get(k, {})
        ca, chain = cs[0]["ca"], d.get("chain") or cs[0]["chain"]
        callers = {}
        for c in cs:
            callers.setdefault(c["handle"], []).append(c["post_url"])
        who = "; ".join(f"[@{h}](https://x.com/{h}) (" + ", ".join(f"[post]({u})" if len(us) == 1 else f"[{i + 1}]({u})" for i, u in enumerate(us)) + ")"
                        for h, us in callers.items())
        if d.get("ok"):
            mc = f"MC {fmt_usd(d['mcap'])}" if d.get("mcap") else f"FDV {fmt_usd(d['fdv'])}"
            stale = f" (cached DexScreener figures from {d['as_of_dubai']} {TZL})" if d.get("cached") else ""
            stats_ = f"{mc}, liq {fmt_usd(d['liquidity'])}, 1h {fmt_pct(d['h1'])}, 24h {fmt_pct(d['h24'])}, pair age {fmt_age(d['pair_created_ms'], datetime.now(timezone.utc))}{stale}"
            L.append(f"- **${(d['ticker'] or '?').upper()}** ({d['name']}), {chain.capitalize() if chain != 'bsc' else 'BSC'}: [{ca}]({ca_link(chain, ca)}). {stats_}. Called by {who}.")
        else:
            L.append(f"- **Unresolved CA**, {chain or 'unknown chain'}: [{ca}]({ca_link(chain, ca)}). Not found on DexScreener ({d.get('error')}). Called by {who}.")
        e = (run.get("enrich") or {}).get(k)
        if e:
            L.extend(enrich_lines(e, d))
    tags = {}
    for p in run["posts"]:
        if len(p["cashtags"]) <= 4:  # posts listing 5+ tickers (flow/screener dumps) are not calls
            for t in p["cashtags"]:
                if t not in ("BTC", "ETH", "SOL", "USDT", "USDC"):
                    tags.setdefault(t, []).append((p["handle"], p["url"]))
    if tags:
        L.append("\nCashtag-only mentions (no CA, not tallied): " + "; ".join(
            f"${t} by " + ", ".join(f"[@{h}]({u})" for h, u in v) for t, v in tags.items()))
    c = run["concentration"]
    if c:
        line = f"Concentration: @{c['handle']} made {c['calls']} of {c['total']} CA mentions ({c['share']:.0%})."
        L.append(("\n**FLAG** " if c["flag"] else "\n") + line)

    L.append("\n## MOST MENTIONED (24h, distinct accounts)")
    rows = run["most_mentioned"]
    if not rows:
        L.append("No calls logged in the last 24h.")
    for r in rows[:5]:
        L.append(f"- ${(r['ticker'] or '?').upper()} ({r['chain']}): {r['distinct']} account(s), {r['mentions']} mention(s): "
                 + ", ".join(f"[@{h}](https://x.com/{h})" for h in r["handles"]))
    L.append(f"(Tally file holds {run['tally_total_rows']} call rows in total; {run['new_calls_logged']} new this run.)")

    L.append("\n## POST DIGEST (kept, newest first)")
    for p in run["posts"]:
        flat = " ".join(p["text"].split())
        L.append(f"- {p['time_dubai']} [@{p['handle']}](https://x.com/{p['handle']}) {p['url']} :: {flat}")
    if s["dropped_offtopic"]:
        L.append("\nDropped as off-topic: " + "; ".join(f"@{d['handle']} \"{' '.join(d['text'].split())}\"" for d in s["dropped_offtopic"]))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- v4 research modes (keyless, read-only)
# Every mode here only READS public data. None of them builds, signs or sends a transaction or an order.
JUP_LITE = "https://lite-api.jup.ag"
SOL_MINT = "So11111111111111111111111111111111111111112"
RAYDIUM_API = "https://api-v3.raydium.io"
BACKPACK_API = "https://api.backpack.exchange/api/v1"
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
ORE_PROGRAM = "oreV3EG1i9BEgiAJ8b177Z2S2rMarzak4NMv1kULvWv"
ORE_MINT = "oreoU2P8bN6jkk3jbaiVxYnG1dCXcYxwhwyK9jSybcp"
ORE_SPLIT = "SpLiT11111111111111111111111111111111111112"


def run_stamp(mode):
    """runs/<mode>_<YYYYMMDD_HHMM>; adds seconds if that file already exists (no same-minute overwrite)."""
    t = now_utc().astimezone(DUBAI)
    s = t.strftime("%Y%m%d_%H%M")
    if os.path.exists(os.path.join(HERE, "runs", f"{mode}_{s}.md")):
        s = t.strftime("%Y%m%d_%H%M%S")
    return s


def write_out(mode, md, data):
    os.makedirs(os.path.join(HERE, "runs"), exist_ok=True)
    s = run_stamp(mode)
    json.dump({"generated_utc": iso(), **data}, open(os.path.join(HERE, "runs", f"{mode}_{s}.json"), "w"),
              indent=1, ensure_ascii=False)
    open(os.path.join(HERE, "runs", f"{mode}_{s}.md"), "w").write(md)
    print(md)
    print(f"(saved runs/{mode}_{s}.md and .json)")


def now_label():
    return dubai_hhmm(iso())


def musebook_mcp(tool, args=None, path="/mcp-research", timeout=45):
    """Musebook public MCP over stateless HTTP JSON-RPC (keyless, read-only tools). Returns (obj, error)."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args or {}}}
    try:
        req = urllib.request.Request(MUSEBOOK + path, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "User-Agent": "Mozilla/5.0 trenches-report/4.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode()
    except Exception as e:
        return None, f"Musebook MCP {tool}: {getattr(e, 'code', '') or e}"
    for line in txt.splitlines() if not txt.lstrip().startswith("{") else [txt]:
        line = line[5:] if line.startswith("data:") else line
        try:
            d = json.loads(line)
        except Exception:
            continue
        res = d.get("result") or {}
        if d.get("error") or res.get("isError"):
            return None, f"Musebook MCP {tool}: {d.get('error') or (res.get('content') or [{}])[0].get('text', 'error')[:200]}"
        try:
            return json.loads(res["content"][0]["text"]), None
        except Exception:
            return res, None
    return None, f"Musebook MCP {tool}: unreadable response"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(v, signed=True):
    v = _f(v)
    return None if v is None else (f"{v:+.1f}%" if signed else f"{v:.1f}%")


def jup_prices(mints):
    out, err = {}, None
    for i in range(0, len(mints), 50):
        for attempt in range(3):
            j, e = http_get(f"{JUP_LITE}/price/v3?ids={','.join(mints[i:i + 50])}", timeout=20)
            if j is not None or "429" not in str(e):
                break
            time.sleep(3 * (attempt + 1))  # keyless lite API is rate-limited; back off politely
        if j is None:
            err = e
            continue
        out.update({k: v for k, v in j.items() if v})
    return out, err


# ---- quote: Jupiter price + token stats + read-only swap quote (buy and sell-back)
def quote_cmd(args):
    ca, t = args.ca, iso()
    if ca.startswith("0x"):
        sys.exit("quote is Solana-only (Jupiter). For EVM tokens use `enrich --ca <CA> --chain <chain>`.")
    lam = int(round(args.amount_sol * 1e9))
    with ThreadPoolExecutor(3) as ex:
        fp = ex.submit(jup_prices, [ca, SOL_MINT])
        ft = ex.submit(http_get, f"{JUP_LITE}/tokens/v2/search?query={ca}", 20)
        fq = ex.submit(http_get, f"{JUP_LITE}/swap/v1/quote?inputMint={SOL_MINT}&outputMint={ca}&amount={lam}"
                                 f"&slippageBps={args.slippage_bps}", 20)
    (prices, perr), (tok, terr), (buy, berr) = fp.result(), ft.result(), fq.result()
    tok = next((x for x in (tok or []) if x.get("id") == ca), None)
    sell, serr = (None, None)
    if buy and buy.get("outAmount"):
        sell, serr = http_get(f"{JUP_LITE}/swap/v1/quote?inputMint={ca}&outputMint={SOL_MINT}&amount={buy['outAmount']}"
                              f"&slippageBps={args.slippage_bps}", 20)
    sym = (tok or {}).get("symbol") or ca[:6]
    dec = (tok or {}).get("decimals") or (prices.get(ca) or {}).get("decimals")
    L = [f"# Jupiter quote check: ${str(sym).upper()} {ca}", f"Read-only. Quotes only: nothing is built, signed or sent. "
         f"Sources: Jupiter lite API (keyless), as of {dubai_hhmm(t)} {TZL}.", ""]
    p = prices.get(ca)
    if p:
        bits = [f"price ${p['usdPrice']:.6g}" if p.get("usdPrice") is not None else None,
                f"liquidity {fmt_usd(p['liquidity'])}" if p.get("liquidity") is not None else None,
                f"24h {_pct(p.get('priceChange24h'))}" if p.get("priceChange24h") is not None else None,
                f"launchpad {p['launchpad']}" if p.get("launchpad") else None]
        L.append(f"- Price: {', '.join(b for b in bits if b)} [Jupiter Price API v3]")
    else:
        L.append(f"- Price: not returned ({perr or 'token not priced by Jupiter'}) [Jupiter Price API v3]")
    if tok:
        a = tok.get("audit") or {}
        bits = [f"MC {fmt_usd(tok['mcap'])}" if tok.get("mcap") is not None else None,
                f"{tok['holderCount']:,} holders" if tok.get("holderCount") is not None else None,
                f"organic score {tok['organicScore']:.0f} ({tok.get('organicScoreLabel')})" if tok.get("organicScore") is not None else None,
                f"top holders {a['topHoldersPercentage']:.1f}%" if a.get("topHoldersPercentage") is not None else None,
                f"dev holds {a['devBalancePercentage']:.2f}%" if a.get("devBalancePercentage") is not None else None,
                f"dev has launched {a['devMints']} tokens ({a.get('devMigrations', 'n/a')} migrated)" if a.get("devMints") is not None else None,
                ("mint authority disabled" if a["mintAuthorityDisabled"] else "MINT AUTHORITY ACTIVE") if a.get("mintAuthorityDisabled") is not None else None,
                ("freeze authority disabled" if a["freezeAuthorityDisabled"] else "FREEZE AUTHORITY ACTIVE") if a.get("freezeAuthorityDisabled") is not None else None,
                f"graduated {dubai_hhmm(tok['graduatedAt'])} {TZL} {tok['graduatedAt'][:10]}" if tok.get("graduatedAt") else None]
        s24 = tok.get("stats24h") or {}
        if s24.get("numBuys") is not None:
            bits.append(f"24h buys/sells {s24['numBuys']:,}/{s24.get('numSells', 0):,}, {s24.get('numTraders', 0):,} traders, "
                        f"{s24.get('numOrganicBuyers', 0):,} organic buyers")
        L.append(f"- Token: {', '.join(b for b in bits if b)} [Jupiter Tokens API v2]")
    else:
        L.append(f"- Token stats: not returned ({terr or 'no match'}) [Jupiter Tokens API v2]")

    def q_line(label, q, e, in_amt, in_dec, out_dec, in_sym, out_sym):
        if not q or not q.get("outAmount"):
            return f"- {label}: no route ({e or (q or {}).get('error') or 'not returned'})"
        route = " > ".join(dict.fromkeys(r["swapInfo"].get("label", "?") for r in q.get("routePlan", [])))
        out = int(q["outAmount"]) / 10 ** out_dec if out_dec is not None else None
        imp = _f(q.get("priceImpactPct"))
        return (f"- {label}: {in_amt:,.6g} {in_sym} -> {out:,.6g} {out_sym}" if out is not None else f"- {label}: raw out {q['outAmount']}") + \
               (f", price impact {imp * 100:.2f}%" if imp is not None else "") + f", slippage limit {q.get('slippageBps')} bps, route {route}"
    L.append(q_line(f"Buy quote", buy, berr, args.amount_sol, 9, dec, "SOL", str(sym).upper()) + " [Jupiter Swap API v1 /quote]")
    if buy and buy.get("outAmount") and dec is not None:
        L.append(q_line("Sell-back quote", sell, serr, int(buy["outAmount"]) / 10 ** dec, dec, 9, str(sym).upper(), "SOL") + " [Jupiter Swap API v1 /quote]")
        if sell and sell.get("outAmount"):
            back = int(sell["outAmount"]) / 1e9
            L.append(f"- Round trip: {args.amount_sol:g} SOL in, {back:.6g} SOL back = {(1 - back / args.amount_sol) * 100:.2f}% lost to "
                     f"impact and pool fees at quote time (excludes network/priority fees). Quotes move every block.")
    L.append("\nNot financial advice. To trade, the user does it themselves in their own wallet (see trading guardrails).")
    write_out("quote", "\n".join(L) + "\n", {"ca": ca, "amount_sol": args.amount_sol, "price": p, "token": tok,
                                              "buy_quote": buy, "sell_quote": sell,
                                              "errors": {k: v for k, v in (("price", perr), ("token", terr), ("buy", berr), ("sell", serr)) if v}})


# ---- raydium: pools for a mint
def raydium_cmd(args):
    t = iso()
    j, e = http_get(f"{RAYDIUM_API}/pools/info/mint?mint1={args.ca}&poolType=all&poolSortField=liquidity&sortType=desc"
                    f"&pageSize={args.limit}&page=1", timeout=20)
    pools = ((j or {}).get("data") or {}).get("data") or []
    L = [f"# Raydium pools for {args.ca}", f"Source: Raydium API v3 (keyless), as of {dubai_hhmm(t)} {TZL}.", ""]
    if j is None or not (j or {}).get("success", True):
        L.append(f"Raydium API unavailable ({e or (j or {}).get('msg')}).")
    elif not pools:
        L.append("No Raydium pools for this mint. (pump.fun graduates have migrated to PumpSwap since 2025; check `enrich` or DexScreener.)")
    for p in pools:
        a, b = p.get("mintA") or {}, p.get("mintB") or {}
        d = p.get("day") or {}
        bits = [f"TVL {fmt_usd(p['tvl'])}" if p.get("tvl") is not None else None,
                f"price {p['price']:.6g} {b.get('symbol')} per {a.get('symbol')}" if p.get("price") is not None else None,
                f"24h volume {fmt_usd(d['volume'])}" if d.get("volume") is not None else None,
                f"fee {p['feeRate'] * 100:.2f}%" if p.get("feeRate") is not None else None,
                f"LP burned {p['burnPercent']}%" if p.get("burnPercent") is not None and p.get("type") == "Standard" else None]
        L.append(f"- {p.get('type')} {a.get('symbol')}/{b.get('symbol')} pool `{p.get('id')}`: {', '.join(x for x in bits if x)}")
    if pools and all((p.get("tvl") or 0) < 1000 for p in pools):
        L.append("\nAll Raydium pools here hold under $1K TVL: the real liquidity is elsewhere (PumpSwap/Meteora/Orca); use `quote` or `enrich`.")
    write_out("raydium", "\n".join(L) + "\n", {"ca": args.ca, "count": ((j or {}).get("data") or {}).get("count"), "pools": pools, "error": e})


# ---- backpack: exchange market data (spot, perps, stock perps)
def backpack_cmd(args):
    t = iso()
    L = [f"# Backpack market data", f"Source: Backpack Exchange public API (keyless), as of {dubai_hhmm(t)} {TZL}. Read-only.", ""]
    data = {}
    if args.symbol:
        s = args.symbol.upper()
        with ThreadPoolExecutor(4) as ex:
            ft = ex.submit(http_get, f"{BACKPACK_API}/ticker?symbol={s}", 15)
            fd = ex.submit(http_get, f"{BACKPACK_API}/depth?symbol={s}", 15)
            fm = ex.submit(http_get, f"{BACKPACK_API}/markPrices?symbol={s}", 15) if "PERP" in s else None
            fo = ex.submit(http_get, f"{BACKPACK_API}/openInterest?symbol={s}", 15) if "PERP" in s else None
        (tk, e1), (dp, e2) = ft.result(), fd.result()
        mk = fm.result()[0] if fm else None
        oi = fo.result()[0] if fo else None
        data = {"ticker": tk, "depth_top": None, "mark": mk, "open_interest": oi}
        if not tk:
            L.append(f"{s}: no ticker ({e1 if str(e1).startswith('HTTP') else 'unknown symbol or empty response'}). "
                     f"Run `backpack` without --symbol to list symbols.")
        else:
            L.append(f"- {s}: last {tk['lastPrice']}, 24h {_pct(_f(tk.get('priceChangePercent')) * 100)}, high {tk['high']}, low {tk['low']}, "
                     f"24h quote volume {fmt_usd(_f(tk['quoteVolume']))}, {int(tk.get('trades') or 0):,} trades [Backpack ticker]")
        if dp and dp.get("bids") and dp.get("asks"):
            bids = sorted(dp["bids"], key=lambda x: -float(x[0]))[:5]
            asks = sorted(dp["asks"], key=lambda x: float(x[0]))[:5]
            bb, ba = float(bids[0][0]), float(asks[0][0])
            data["depth_top"] = {"bids": bids, "asks": asks}
            L.append(f"- Book: best bid {bids[0][0]} / best ask {asks[0][0]} (spread {(ba - bb) / ((ba + bb) / 2) * 100:.3f}%); "
                     f"top-5 depth {sum(float(q) for _, q in bids):,.4g} bid / {sum(float(q) for _, q in asks):,.4g} ask (base units) [Backpack depth]")
        if mk and mk[0:1]:
            m = mk[0]
            L.append(f"- Perp: mark {m.get('markPrice')}, index {m.get('indexPrice')}, funding {(_f(m.get('fundingRate')) or 0) * 100:.4f}% per interval, "
                     f"next funding {datetime.fromtimestamp(m['nextFundingTimestamp'] / 1000, DUBAI).strftime('%-I:%M %p')} {TZL} [Backpack markPrices]")
        if oi and oi[0:1]:
            L.append(f"- Open interest {float(oi[0]['openInterest']):,.2f} (base units) [Backpack openInterest]")
    else:
        tks, e = http_get(f"{BACKPACK_API}/tickers", 20)
        mk, e2 = http_get(f"{BACKPACK_API}/markets", 20)
        typ = {m["symbol"]: (m.get("marketType"), m.get("rwaMarketType")) for m in (mk or [])}
        rows = [x for x in (tks or []) if args.type == "all" or (typ.get(x["symbol"], ("",))[0] or "").lower() == args.type]
        rows.sort(key=lambda x: -(_f(x.get("quoteVolume")) or 0))
        data = {"tickers": rows[:args.limit], "markets_count": len(mk or [])}
        if not tks:
            L.append(f"Backpack tickers unavailable ({e}).")
        L.append(f"Top {min(args.limit, len(rows))} {args.type + ' ' if args.type != 'all' else ''}markets by 24h quote volume ({len(mk or [])} markets listed):")
        for x in rows[:args.limit]:
            mt, rwa = typ.get(x["symbol"], (None, None))
            L.append(f"- {x['symbol']}{' (' + rwa.lower() + ')' if rwa else ''}: last {x['lastPrice']}, 24h {_pct((_f(x.get('priceChangePercent')) or 0) * 100)}, "
                     f"vol {fmt_usd(_f(x.get('quoteVolume')))}")
    L.append("\nMarket data only. Trading on Backpack needs the user's own account and API keys, which Degen Desk does not hold.")
    write_out("backpack", "\n".join(L) + "\n", data)


# ---- rwa: tokenized stocks and RWA research (Backpack stock/index markets, Jupiter xStock prices, Musebook RWA status)
def rwa_cmd(args):
    t = iso()
    with ThreadPoolExecutor(4) as ex:
        fm = ex.submit(http_get, f"{BACKPACK_API}/markets", 20)
        ft = ex.submit(http_get, f"{BACKPACK_API}/tickers", 20)
        fq = ex.submit(http_get, f"{MUSEBOOK}/api/rwa/quotes", 30)
        fs = ex.submit(http_get, f"{MUSEBOOK}/api/rwa/status", 30)
    (mk, e1), (tks, e2), (cat, e3), (st, e4) = fm.result(), ft.result(), fq.result(), fs.result()
    L = [f"# Tokenized stocks and RWA snapshot", f"Read-only research, as of {dubai_hhmm(t)} {TZL}. Sources labelled per line.", ""]
    rwa = {m["symbol"]: m.get("rwaMarketType") for m in (mk or []) if m.get("rwaMarketType")}
    tk = {x["symbol"]: x for x in (tks or [])}
    L.append(f"## Backpack stock and index markets ({len(rwa)} listed) [Backpack public API]")
    if not mk:
        L.append(f"Backpack unavailable ({e1}).")
    rows = sorted(rwa, key=lambda s: -(_f((tk.get(s) or {}).get("quoteVolume")) or 0))
    for s in rows[:args.limit]:
        x = tk.get(s) or {}
        L.append(f"- {s} ({rwa[s].lower()}, {'perp' if 'PERP' in s else 'spot'}): last {x.get('lastPrice', 'n/a')}, "
                 f"24h {_pct((_f(x.get('priceChangePercent')) or 0) * 100) if x else 'n/a'}, vol {fmt_usd(_f(x.get('quoteVolume'))) if x else 'n/a'}")
    assets = (cat or {}).get("assets") or []
    L.append("")
    L.append(f"## Solana tokenized stocks (xStocks etc.): catalog {(cat or {}).get('source', 'Musebook /api/rwa/quotes')}, "
             f"{len(assets)} assets; prices [Jupiter Price API v3]")
    if not assets:
        L.append(f"Catalog unavailable ({e3}).")
    pick = assets[:max(args.limit * 2, 20)]
    prices, perr = jup_prices([a["mint"] for a in pick]) if pick else ({}, None)
    priced = sorted([a for a in pick if a["mint"] in prices], key=lambda a: -(prices[a["mint"]].get("liquidity") or 0))
    for a in priced[:args.limit]:
        p = prices[a["mint"]]
        L.append(f"- {a['symbol']} ({a.get('name')}, {a.get('category')}): ${p['usdPrice']:,.2f}, 24h {_pct(p.get('priceChange24h'))}, "
                 f"on-chain liquidity {fmt_usd(p.get('liquidity'))} `{a['mint']}`")
    if pick and not priced:
        L.append(f"No Jupiter prices returned ({perr}).")
    L.append("")
    if st:
        L.append(f"## Musebook RWA issuance readiness [Musebook /api/rwa/status]")
        L.append(f"- Protocol {st.get('protocol')} on {st.get('network')}: stage {st.get('stage')}, launch enabled {st.get('launchEnabled')}, "
                 f"transaction builder {st.get('transactionBuilderAvailable')}")
        for c in (st.get("checks") or [])[:6]:
            L.append(f"  - {c.get('title')}: {c.get('state')}")
    else:
        L.append(f"Musebook RWA status unavailable ({e4}).")
    L.append("\nTokenized stocks track but are not the shares themselves; check issuer terms and your jurisdiction. Not financial advice.")
    write_out("rwa", "\n".join(L) + "\n", {"backpack_rwa_markets": {s: tk.get(s) for s in rows}, "xstock_prices": {a["symbol"]: prices[a["mint"]] for a in priced},
                                            "musebook_rwa_status": st, "errors": {k: v for k, v in (("bp_markets", e1), ("bp_tickers", e2), ("catalog", e3), ("status", e4), ("jup", perr)) if v}})


# ---- kalshi: prediction-market data (Kalshi public API + Jupiter Prediction via Musebook MCP)
def kalshi_cmd(args):
    t = iso()
    q = (args.query or "").lower()
    L = [f"# Prediction markets{': ' + args.query if args.query else ''}",
         f"Read-only market data, as of {dubai_hhmm(t)} {TZL}. Prices are market prices, not calibrated probabilities. Not advice.", ""]
    data = {}
    if args.source in ("kalshi", "both"):
        evs, cur, err = [], None, None
        for _ in range(args.pages):
            u = f"{KALSHI_API}/events?limit=200&status=open&with_nested_markets=true" + (f"&series_ticker={args.series}" if args.series else "") + (f"&cursor={cur}" if cur else "")
            j, err = http_get(u, timeout=20)
            if not j:
                break
            evs += j.get("events") or []
            cur = j.get("cursor")
            if not cur:
                break
        mk = []
        for ev in evs:
            for m in ev.get("markets") or []:
                text = " ".join(str(x) for x in (ev.get("title"), ev.get("sub_title"), m.get("title"), m.get("yes_sub_title"), ev.get("category"))).lower()
                if q and q not in text:
                    continue
                mk.append((ev, m))
        mk.sort(key=lambda em: -(_f(em[1].get("volume_24h_fp")) or 0))
        L.append(f"## Kalshi ({len(evs)} open events scanned{', series ' + args.series if args.series else ''}; top {min(args.limit, len(mk))} of {len(mk)} matching markets by 24h volume) [Kalshi public API]")
        if not evs:
            L.append(f"Kalshi unavailable ({err}).")
        for ev, m in mk[:args.limit]:
            yb, ya, lp = _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars")), _f(m.get("last_price_dollars"))
            ct = m.get("close_time")
            L.append(f"- {ev.get('title')}: {m.get('yes_sub_title') or m.get('title')} `{m.get('ticker')}`: YES bid/ask "
                     f"{'n/a' if yb is None else f'{yb * 100:.0f}c'}/{'n/a' if ya is None else f'{ya * 100:.0f}c'}, last {'n/a' if lp is None else f'{lp * 100:.0f}c'}, "
                     f"24h vol {(_f(m.get('volume_24h_fp')) or 0):,.0f} contracts, OI {(_f(m.get('open_interest_fp')) or 0):,.0f}, closes {to_dubai(ct).strftime('%Y-%m-%d %-I:%M %p') + ' ' + TZL if ct else 'n/a'}")
        data["kalshi"] = [{"event": ev.get("event_ticker"), "title": ev.get("title"), "market": m} for ev, m in mk[:args.limit]]
        data["kalshi_events_scanned"] = len(evs)
    if args.source in ("jupiter", "both"):
        a = {"limit": min(args.limit, 10)}
        if args.query:
            a["query"] = args.query
        if args.provider:
            a["provider"] = args.provider
        j, err = musebook_mcp("prediction_events", a)
        L.append("")
        L.append(f"## Jupiter Prediction (Kalshi/Polymarket markets on Solana) [Musebook research MCP prediction_events, retrieved "
                 f"{dubai_hhmm((j or {}).get('retrieved_at') or t)} {TZL}]")
        if not j:
            L.append(f"Unavailable ({err}).")
        for ev in (j or {}).get("events") or []:
            vol = _f(ev.get("volumeUsd"))
            L.append(f"- {ev.get('metadata', {}).get('title')} `{ev.get('eventId')}` ({ev.get('category')}"
                     f"{', volume ' + fmt_usd(vol / 1e6) if vol is not None else ''})")
            for m in (ev.get("markets") or [])[:3]:
                pr = m.get("pricing") or {}
                by, bn = _f(pr.get("buyYesPriceUsd")), _f(pr.get("buyNoPriceUsd"))
                L.append(f"  - {m.get('title')} ({m.get('provider')}, {m.get('status')}): buy YES {'n/a' if by is None else f'{by / 1e4:.0f}c'}, "
                         f"buy NO {'n/a' if bn is None else f'{bn / 1e4:.0f}c'}")
        data["jupiter"] = j
        data["jupiter_units_note"] = "Jupiter USD fields are micro-USD (1e6 = $1), per Jupiter docs and the tool's units field."
    L.append("\nDFlow serves these same Kalshi markets on Solana, but DFlow's own API needs a DFlow API key; trading needs a wallet and KYC. Not wired.")
    write_out("kalshi", "\n".join(L) + "\n", data)


# ---- ore: ORE v3 mining board state, read straight from chain
def _parse_ore_round(b):
    if not b or len(b) < 952:
        return None
    u = lambda off: _u64(b, off)
    deployed = [u(16 + 8 * i) for i in range(25)]
    count = [u(416 + 8 * i) for i in range(25)]
    sh = b[616:648]
    r = None
    if sh not in (b"\0" * 32, b"\xff" * 32):
        r = 0
        for i in range(4):
            r ^= int.from_bytes(sh[8 * i:8 * i + 8], "little")
    return {"id": u(8), "total_deployed_sol": sum(deployed) / 1e9, "squares_with_sol": sum(1 for d in deployed if d),
            "unique_miners": u(912), "motherlode_ore": u(656) / 1e11, "protocol_fee_sol": u(896) / 1e9,
            "returned_sol": u(904) / 1e9, "top_miner": b58encode(b[920:952]), "rng": r,
            "winning_square": (r % 25) + 1 if r is not None else None,
            "motherlode_hit": (int(f"{r:064b}"[::-1], 2) % 500 == 0) if r is not None else None,
            "max_miners_on_square": max(count)}


def ore_cmd(args):
    t = iso()
    board, treas = find_pda([b"board"], ORE_PROGRAM), find_pda([b"treasury"], ORE_PROGRAM)
    acc, rpc, err = solana_accounts([board, treas])
    L = [f"# ORE mining snapshot", f"Read straight from the ORE v3 program `{ORE_PROGRAM}` via Solana RPC, as of {dubai_hhmm(t)} {TZL}. "
         f"Read-only: no mining, deploying or claiming.", ""]
    data = {}
    if not acc or not acc.get(board):
        L.append(f"ORE board account unavailable ({err or 'not found'}).")
        write_out("ore", "\n".join(L) + "\n", {"error": err})
        return
    b = acc[board]
    rid, start, end, cost = _u64(b, 8), _u64(b, 16), _u64(b, 24), _u64(b, 32)
    slot_j, _ = http_get(rpc, data={"jsonrpc": "2.0", "id": 1, "method": "getSlot", "params": [{"commitment": "confirmed"}]}, timeout=15)
    slot = (slot_j or {}).get("result")
    rp = [find_pda([b"round", rid.to_bytes(8, "little")], ORE_PROGRAM), find_pda([b"round", (rid - 1).to_bytes(8, "little")], ORE_PROGRAM)]
    racc, _, rerr = solana_accounts(rp)
    cur, prev = _parse_ore_round((racc or {}).get(rp[0])), _parse_ore_round((racc or {}).get(rp[1]))
    prices, _ = jup_prices([ORE_MINT, SOL_MINT])
    ore_usd, sol_usd = (prices.get(ORE_MINT) or {}).get("usdPrice"), (prices.get(SOL_MINT) or {}).get("usdPrice")
    src = f"[Solana RPC {rpc.split('//')[1]}]"
    left = f", ~{(end - slot) * 0.4:.0f}s left ({end - slot} slots)" if slot and end != 2 ** 64 - 1 and end > slot else ""
    L.append(f"- Board: round {rid:,}, slots {start:,} to {end:,}{left}; production cost EMA {cost / 1e9:.4f} SOL per ORE "
             f"{('(~' + fmt_usd(cost / 1e9 * sol_usd) + ')') if sol_usd else ''} {src}")
    if acc.get(treas) and len(acc[treas]) >= 48:
        tb = acc[treas]
        L.append(f"- Treasury: motherlode pool {_u64(tb, 8) / 1e11:,.2f} ORE{(' (~' + fmt_usd(_u64(tb, 8) / 1e11 * ore_usd) + ')') if ore_usd else ''}, "
                 f"unclaimed miner rewards {_u64(tb, 40) / 1e11:,.0f} ORE, refined {_u64(tb, 32) / 1e11:,.0f} ORE {src}")
    if cur:
        L.append(f"- Current round so far: {cur['total_deployed_sol']:.3f} SOL deployed across {cur['squares_with_sol']}/25 squares by "
                 f"{cur['unique_miners']} miners {src}")
    if prev:
        tm = "split among miners" if prev["top_miner"] == ORE_SPLIT else f"`{prev['top_miner'][:6]}…`"
        L.append(f"- Previous round {prev['id']:,}: {prev['total_deployed_sol']:.3f} SOL deployed by {prev['unique_miners']} miners; "
                 + (f"winning square #{prev['winning_square']} (derived from the round's slot hash per ORE source), " if prev["winning_square"] else "")
                 + f"protocol fee {prev['protocol_fee_sol']:.3f} SOL, {prev['returned_sol']:.3f} SOL returned to winners; solo reward {tm}"
                 + ("; MOTHERLODE HIT" if prev.get("motherlode_hit") else "") + f" {src}")
    if ore_usd:
        p = prices[ORE_MINT]
        L.append(f"- ORE price ${ore_usd:,.2f}, 24h {_pct(p.get('priceChange24h'))}, liquidity {fmt_usd(p.get('liquidity'))} [Jupiter Price API v3]")
    if rerr:
        L.append(f"- Round accounts unavailable ({rerr}).")
    L.append("\nMining is a game with a house edge: on-chain fees go to the protocol and admin each round. Execution is out of scope here.")
    write_out("ore", "\n".join(L) + "\n", {"board": {"round_id": rid, "start_slot": start, "end_slot": end, "production_cost_ema_lamports": cost},
                                            "slot": slot, "current_round": cur, "previous_round": prev, "ore_usd": ore_usd, "sol_usd": sol_usd})


# ---- metaplex: agent registry + live Genesis launches (via Musebook public API)
def metaplex_cmd(args):
    t = iso()
    L = [f"# Metaplex agents{(': ' + (args.address or args.query)) if (args.address or args.query) else ''}",
         f"Source: Musebook public Metaplex endpoints (keyless), as of {dubai_hhmm(t)} {TZL}. Read-only.", ""]
    data = {}
    if args.address:
        j, e = http_get(f"{MUSEBOOK}/api/metaplex/agents/{args.address}", 25)
        data["agent"] = j
        if not j or not j.get("success", True):
            L.append(f"No agent record ({e or (j or {}).get('error')}).")
        else:
            svc = ", ".join(f"{s.get('name')} {s.get('endpoint')}" for s in j.get("services") or [])
            L.append(f"- {j.get('name')}: {j.get('description') or '(no description)'}")
            L.append(f"  - active {j.get('active')}, x402 support {j.get('x402Support')}, services: {svc or 'none listed'}")
            for r in j.get("registrations") or []:
                L.append(f"  - registry {r.get('agentRegistry')} id `{r.get('agentId')}`")
    else:
        from urllib.parse import quote as _q
        j, e = http_get(f"{MUSEBOOK}/api/metaplex/agents?page=1&pageSize={args.limit}" + (f"&query={_q(args.query)}" if args.query else ""), 25)
        d = (j or {}).get("data") or {}
        data["agents"] = d
        L.append(f"## Registered agents ({d.get('total', 'n/a')} {'matching' if args.query else 'indexed'}; showing {len(d.get('agents') or [])}) [Musebook /api/metaplex/agents]")
        if not j:
            L.append(f"Unavailable ({e}).")
        for a in d.get("agents") or []:
            md = a.get("metadata") or {}
            L.append(f"- {a.get('name')} `{a.get('mintAddress')}`: {(a.get('description') or '')[:120]}"
                     f" (active {a.get('isActive')}, agent token {'yes `' + str(a['agentToken']) + '`' if a.get('agentToken') else 'none'}, "
                     f"x402 {md.get('x402Support')}, indexed {(a.get('indexedAt') or '')[:10]})")
        if args.launches:
            lj, le = http_get(f"{MUSEBOOK}/api/metaplex/launches?network=solana-mainnet&status=live", 25)
            ls = (lj or {}).get("data") or []
            data["launches"] = ls[:args.limit]
            L.append("")
            L.append(f"## Live Metaplex Genesis launches ({len(ls)} live; newest {min(args.limit, len(ls))}) [Musebook /api/metaplex/launches]")
            if not lj:
                L.append(f"Unavailable ({le}).")
            for x in sorted(ls, key=lambda x: (x.get("launch") or {}).get("startTime") or "", reverse=True)[:args.limit]:
                ln, bt = x.get("launch") or {}, x.get("baseToken") or {}
                L.append(f"- {bt.get('name')} (${bt.get('symbol')}) `{bt.get('address')}`: {ln.get('mechanic')}, started "
                         f"{(ln.get('startTime') or '')[:10]}, verified {ln.get('verified')} {ln.get('launchPage') or ''}")
    L.append("\nRegistry data is self-reported by agent owners. Minting, funding or launching agents needs a wallet: out of scope.")
    write_out("metaplex", "\n".join(L) + "\n", data)



def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--raw", required=True)
    b.add_argument("--calls", default=os.path.join(HERE, "calls.jsonl"))
    b.add_argument("--hours", type=int, default=24)
    b.add_argument("--no-append", action="store_true")
    b.add_argument("--no-enrich", action="store_true", help="skip v3 on-chain enrichment (v2 behaviour)")
    for name in ("scan", "launches", "enrich"):
        x = sub.add_parser(name)
        x.add_argument("--calls", default=os.path.join(HERE, "calls.jsonl"))
        x.add_argument("--hours", type=int, default=24)
        if name != "enrich":
            x.add_argument("--run", default=None, help="run_*.json to cross-reference (default: newest in runs/)")
    sc = sub.choices["scan"]
    sc.add_argument("--min-liq", type=float, default=10_000)
    sc.add_argument("--min-mcap", type=float, default=25_000)
    sc.add_argument("--min-buys", type=int, default=10)
    sc.add_argument("--chain", default="all", help="restrict boosted candidates to one chain, e.g. solana")
    sc.add_argument("--sort", default="h1", choices=["h1", "h6", "h24", "vol24"])
    sc.add_argument("--top", type=int, default=10)
    sub.choices["launches"].add_argument("--limit", type=int, default=15)
    en = sub.choices["enrich"]
    en.add_argument("--ca", action="append", help="CA to enrich (repeatable); default = all CAs in calls.jsonl within --hours")
    en.add_argument("--chain", default=None, help="chain for --ca (solana, ethereum, base, bsc, robinhood, ...)")
    q = sub.add_parser("quote", help="Jupiter price, token stats and a read-only buy + sell-back quote")
    q.add_argument("--ca", required=True)
    q.add_argument("--amount-sol", type=float, default=1.0)
    q.add_argument("--slippage-bps", type=int, default=100)
    r = sub.add_parser("raydium", help="Raydium pools for a mint")
    r.add_argument("--ca", required=True)
    r.add_argument("--limit", type=int, default=5)
    bp = sub.add_parser("backpack", help="Backpack exchange market data")
    bp.add_argument("--symbol", default=None, help="e.g. SOL_USDC, SOL_USDC_PERP, NVDA.US_USDC_PERP")
    bp.add_argument("--type", default="all", choices=["all", "spot", "perp"])
    bp.add_argument("--limit", type=int, default=15)
    rw = sub.add_parser("rwa", help="tokenized stocks / RWA snapshot")
    rw.add_argument("--limit", type=int, default=10)
    k = sub.add_parser("kalshi", help="prediction markets: Kalshi public API + Jupiter Prediction (Musebook MCP)")
    k.add_argument("--query", default=None)
    k.add_argument("--series", default=None, help="Kalshi series ticker, e.g. KXBTCD")
    k.add_argument("--source", default="both", choices=["both", "kalshi", "jupiter"])
    k.add_argument("--provider", default=None, choices=["kalshi", "polymarket", "bisonfi"], help="Jupiter provider filter")
    k.add_argument("--limit", type=int, default=10)
    k.add_argument("--pages", type=int, default=5, help="Kalshi event pages of 200 to scan")
    sub.add_parser("ore", help="ORE v3 mining board, treasury and last round (on-chain)")
    mp = sub.add_parser("metaplex", help="Metaplex agent registry and live Genesis launches")
    mp.add_argument("--query", default=None)
    mp.add_argument("--address", default=None, help="agent mint address for a single record")
    mp.add_argument("--launches", action="store_true", help="also list live Metaplex Genesis launches")
    mp.add_argument("--limit", type=int, default=10)
    t = sub.add_parser("tally")
    t.add_argument("--calls", default=os.path.join(HERE, "calls.jsonl"))
    t.add_argument("--hours", type=int, default=24)
    a = ap.parse_args()
    if a.cmd == "build":
        build(a)
    elif a.cmd == "scan":
        scan(a)
    elif a.cmd == "launches":
        launches(a)
    elif a.cmd == "enrich":
        enrich_cmd(a)
    elif a.cmd in ("quote", "raydium", "backpack", "rwa", "kalshi", "ore", "metaplex"):
        {"quote": quote_cmd, "raydium": raydium_cmd, "backpack": backpack_cmd, "rwa": rwa_cmd, "kalshi": kalshi_cmd,
         "ore": ore_cmd, "metaplex": metaplex_cmd}[a.cmd](a)
    else:
        for r in most_mentioned(read_calls(a.calls), datetime.now(timezone.utc), a.hours):
            print(f"${str(r['ticker']).upper()} {r['chain']} {r['ca']}: {r['distinct']} accounts / {r['mentions']} mentions: {', '.join(r['handles'])}")


if __name__ == "__main__":
    main()
