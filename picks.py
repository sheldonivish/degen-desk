#!/usr/bin/env python3
"""Short "picks" report (v4 format, owner request Oct 9 2026): market line, 0-5 picks with a
conviction score, then "Not financial advice." Every score input comes from run_<stamp>.json
(DexScreener, RugCheck/GoPlus, Solana RPC, Musebook, the call log). Nothing is estimated.

  python3 picks.py --run runs/run_<stamp>.json            # writes runs/report_<stamp>.md and prints it
  python3 picks.py --run ... --live-24h                   # also fetch fresh data for 24h multi-caller CAs not in this run
  python3 picks.py --run ... --explain                    # print the score breakdown per candidate (not part of the report)

Conviction (0-10):
  callers   distinct accounts calling the CA in the last 24h (warning posts don't count): 1->1, 2->3, 3+->4
  liquidity DexScreener best pair: >=$100K 2, $25K-100K 1, else 0; minus 1 if liq/MC < 5%
  safety    +1 mint+freeze revoked, not rugged, no RugCheck "danger" / GoPlus honeypot-type flag
            +1 top-10 holders (excl. pools) <= 20%
  age       +1 oldest pair >= 24h
  momentum  +1 24h > 0%, 1h between -15% and +100%, and (if Musebook has it) 24h buys >= sells
Caps: one caller -> max 5; a tracked account warned about it this run -> max 3;
hard fail (rugged, honeypot/can't sell, mint or freeze authority live, RugCheck danger, top-10 > 30%,
liquidity < $10K, no DexScreener data) -> max 2. A pick needs >= 6.
"""
import argparse, json, os, re, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch  # noqa: E402  (helpers: fmt_usd, ca_link, dex_lookup, enrich_ca)

MIN_PICK = 6
MAX_PICKS = 5
SINGLE_CALLER_CAP = 5
WARNING_CAP = 3
HARD_FAIL_CAP = 2
WARN_RE = re.compile(r"\b(rug\w*|scam\w*|avoid|careful|beware|cluster\w*|bundl\w*|honeypot|cannot be analy[sz]ed|"
                     r"dev sold|insiders?|jeet\w*|dump(ed|ing)?|stay away|exit liquidity)\b", re.I)


def pct(v):
    return f"{float(v):+.1f}%"


def market_line(maj):
    d = (maj or {}).get("data") or {}
    parts = [f"{s} {usd_price(d[s]['price'])} ({pct(d[s]['chg24'])})"
             for s in ("BTC", "ETH", "SOL") if d.get(s) and d[s].get("price") is not None]
    return " · ".join(parts) if parts else "Majors unavailable this hour"


def usd_price(v):
    return f"${v:,.0f}" if v >= 1000 else f"${v:,.2f}"


TZL = os.environ.get("DD_TZ_LABEL") or os.environ.get("DD_TZ", "Asia/Dubai").split("/")[-1].replace("_", " ")


def candidates(run, live=False):
    """CAs called this run, plus 24h CAs with 2+ distinct callers (fresh data fetched only with live=True)."""
    out = {}
    for c in run.get("calls") or []:
        out.setdefault(c["ca"].lower(), {"ca": c["ca"], "chain": c.get("chain")})
    for m in run.get("most_mentioned") or []:
        if m.get("distinct", 0) >= 2:
            out.setdefault(m["ca"].lower(), {"ca": m["ca"], "chain": m.get("chain")})
    dex, enr = dict(run.get("dex") or {}), dict(run.get("enrich") or {})
    for k, c in out.items():
        if live and k not in dex:
            dex[k] = fetch.dex_lookup(c["chain"], c["ca"])
        if live and k not in enr and dex.get(k, {}).get("ok"):
            enr[k] = fetch.enrich_ca(dex[k].get("chain") or c["chain"], c["ca"], dex[k])
    return out, dex, enr


def score(k, c, run, dex, enr):
    d, e = dex.get(k) or {}, enr.get(k) or {}
    rc = e.get("rugcheck") if "error" not in (e.get("rugcheck") or {"error": 1}) else {}
    gp = e.get("goplus") if "error" not in (e.get("goplus") or {"error": 1}) else {}
    mint = (e.get("pump") or {}).get("mint") or {}
    mb = next(iter(((e.get("musebook") or {}).get("providers") or [])), {})
    posts = {p["url"]: p for p in run.get("posts") or []}
    mm = next((m for m in run.get("most_mentioned") or [] if m["ca"].lower() == k), {})
    # callers: 24h distinct handles, minus anyone whose post this run reads as a warning
    warned = []
    for call in run.get("calls") or []:
        if call["ca"].lower() == k:
            txt = (posts.get(call["post_url"]) or {}).get("text", "")
            if WARN_RE.search(txt):
                warned.append((call["handle"], call["post_url"], txt))
    handles = set(mm.get("handles") or []) | {x["handle"] for x in run.get("calls") or [] if x["ca"].lower() == k}
    callers = sorted(handles - {w[0] for w in warned})
    s, why, risks, hard, bd = 0, [], [], [], {}
    n = len(callers)
    bd["callers"] = {0: 0, 1: 1, 2: 3}.get(n, 4)
    if n:
        why.append(f"{n} caller{'s' if n > 1 else ''} in 24h ({', '.join('@' + h for h in callers[:3])})")
    if not d.get("ok"):
        hard.append("no DexScreener data")
        bd.update(liquidity=0, safety=0, age=0, momentum=0)
    else:
        mc = d.get("mcap") or d.get("fdv")
        liq = d.get("liquidity") or 0
        bd["liquidity"] = 2 if liq >= 100_000 else 1 if liq >= 25_000 else 0
        if mc and liq / mc < fetch.TH_LIQ_MC:
            bd["liquidity"] = max(0, bd["liquidity"] - 1)
            risks.append((3, f"thin liquidity ({liq / mc:.1%} of MC)"))
        if liq < 10_000:
            hard.append(f"liquidity only {fetch.fmt_usd(liq)}")
        if bd["liquidity"] == 2:
            why.append(f"{fetch.fmt_usd(liq)} liquidity")
        age_h = None
        if d.get("pair_created_ms"):
            age_h = (datetime.now(timezone.utc).timestamp() * 1000 - d["pair_created_ms"]) / 3.6e6
            if run.get("generated_utc"):  # age as of the run, not as of rendering
                gen = datetime.fromisoformat(run["generated_utc"]).timestamp() * 1000
                age_h = (gen - d["pair_created_ms"]) / 3.6e6
        bd["age"] = 1 if age_h is not None and age_h >= 24 else 0
        if age_h is not None and age_h < 24:
            risks.append((4, f"brand-new pair ({fetch.fmt_age(d['pair_created_ms'], datetime.fromisoformat(run['generated_utc']))} old)"))
        elif age_h is not None:
            why.append(f"{int(age_h // 24)}d old")
        h1, h24 = d.get("h1"), d.get("h24")
        bs_ok = True
        if mb.get("buys24h") and mb.get("sells24h"):
            bs_ok = mb["buys24h"] >= mb["sells24h"]
        mom = h1 is not None and h24 is not None and h24 > 0 and -15 < h1 <= 100 and bs_ok
        bd["momentum"] = 1 if mom else 0
        if mom:
            why.append(f"holding {pct(h24)} on 24h")
        elif h1 is not None and h1 > 100:
            risks.append((5, f"already {pct(h1)} in 1h, chasing a vertical move"))
        elif h24 is not None and h24 <= 0:
            risks.append((2, f"down {pct(h24)} on 24h"))
        elif not bs_ok:
            risks.append((2, "more sells than buys in 24h"))
    # safety
    auth_live = bool(mint.get("mint_authority") or mint.get("freeze_authority")) if mint else \
        bool(rc.get("mint_authority") or rc.get("freeze_authority"))
    if auth_live:
        hard.append("mint or freeze authority still live")
    if rc.get("rugged"):
        hard.append("RugCheck marks it rugged")
    dangers = [r.get("name") for r in rc.get("risks") or [] if (r.get("level") or "").lower() == "danger"]
    if dangers:
        hard.append(f"RugCheck danger: {dangers[0]}")
    for key, lab in (("is_honeypot", "honeypot"), ("cannot_sell_all", "can't sell all"), ("is_mintable", "mintable"),
                     ("hidden_owner", "hidden owner"), ("owner_change_balance", "owner can change balances")):
        if gp.get(key):
            hard.append(f"GoPlus: {lab}")
    top10 = rc.get("top10_pct_excl_pools", gp.get("top10_pct_excl_contracts_locked"))
    if top10 is not None and top10 > fetch.TH_TOP10:
        hard.append(f"top-10 holders own {top10:.0f}%")
    have_safety_data = bool(rc or gp)
    bd["safety"] = (1 if have_safety_data and not auth_live and not hard else 0) + \
                   (1 if top10 is not None and top10 <= 20 else 0)
    if bd["safety"] == 2:
        why.append(f"top-10 hold {top10:.0f}%, mint/freeze revoked")
    if not have_safety_data:
        risks.append((3, "no RugCheck/GoPlus data"))
    if rc.get("lpLockedPct") is not None and rc["lpLockedPct"] < 50:
        risks.append((1, f"only {rc['lpLockedPct']:.0f}% of LP locked"))
    s = sum(bd.values())
    cap = 10
    if hard:
        cap = HARD_FAIL_CAP
        risks.append((9, hard[0]))
    if warned:
        cap = min(cap, WARNING_CAP)
        h, url, txt = warned[0]
        sents = [fetch.URL_RE.sub("", x).strip() for x in re.split(r"(?<=[.!?])\s+|\n+", txt)]
        sents = [x for x in sents if WARN_RE.search(x)] or [txt[:80]]
        best = max(sents, key=lambda x: (bool(re.search(r"\d+(\.\d+)?%", x)), len(WARN_RE.findall(x))))
        best = re.sub(r"\s*\(?CA\s+[1-9A-HJ-NP-Za-km-z]{32,44}\)?|\b0x[a-fA-F0-9]{40}\b", "", best).strip(" ,")
        snippet = best if len(best) <= 80 else best[:77].rsplit(" ", 1)[0] + "..."
        risks.append((8, f"[@{h}]({url}) warned: \"{snippet}\""))
    if n == 1:
        cap = min(cap, SINGLE_CALLER_CAP)
        risks.append((6, "only one account calling it"))
    if n == 0 and not warned:
        risks.append((6, "no tracked account is calling it"))
    final = min(s, cap)
    risks.sort(key=lambda r: -r[0])
    return {"k": k, "ca": c["ca"], "chain": d.get("chain") or c.get("chain"), "ticker": (d.get("ticker") or "?").upper(),
            "mc": d.get("mcap") or d.get("fdv"), "liq": d.get("liquidity"), "score": final, "raw": s, "cap": cap,
            "breakdown": bd, "why": why, "risk": risks[0][1] if risks else "memecoins can go to zero fast",
            "hard": hard, "warned": bool(warned), "callers": n}


def render(run, scored):
    stamp_t = run.get("as_of_dubai") or "?"
    L = [f"**Trenches picks · {stamp_t} {TZL}**", market_line(run.get("majors")), ""]
    picks = sorted([x for x in scored if x["score"] >= MIN_PICK], key=lambda x: (-x["score"], -(x["liq"] or 0)))[:MAX_PICKS]
    if not (run.get("stats") or {}).get("raw_total") and not run.get("posts"):
        L += ["X read failed this hour, so there are no picks.", ""]
    elif not picks:
        L.append("**No buys this hour.**")
        near = sorted([x for x in scored if not x["hard"]], key=lambda x: (-x["score"], -(x["liq"] or 0)))[:1]
        for x in near:
            L.append(f"Closest: ${x['ticker']} {x['score']}/10 ({x['risk']}).")
        L.append("")
    for i, x in enumerate(picks, 1):
        chain = (x["chain"] or "?").capitalize() if x["chain"] != "bsc" else "BSC"
        L += [f"**{i}. ${x['ticker']}** ({chain}) · **{x['score']}/10**",
              f"CA: [{x['ca']}]({fetch.ca_link(x['chain'], x['ca'])})",
              f"MC {fetch.fmt_usd(x['mc'])} · Liq {fetch.fmt_usd(x['liq'])}",
              f"Why: {', '.join(x['why'][:3]) or 'see data'}.",
              f"Risk: {x['risk'][0].upper() + x['risk'][1:]}.", ""]
    srcs = "Hyperliquid, DexScreener, RugCheck" if scored else "Hyperliquid"
    if any((run.get("dex") or {}).get(x["k"], {}).get("cached") for x in scored):
        srcs += " (some DexScreener figures cached)"
    L += [f"Data: {srcs}, {stamp_t} {TZL}.", "", "Not financial advice."]
    return "\n".join(L) + "\n", picks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", help="default: runs/report_<stamp>.md next to the run file")
    ap.add_argument("--live-24h", action="store_true", help="fetch data for 24h multi-caller CAs missing from the run")
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("--single-caller-cap", type=int, default=None, help=argparse.SUPPRESS)  # demo/tuning only
    ap.add_argument("--stdout", action="store_true", help="print only, don't write the report file")
    a = ap.parse_args()
    run = json.load(open(a.run))
    if a.single_caller_cap is not None:
        global SINGLE_CALLER_CAP
        SINGLE_CALLER_CAP = a.single_caller_cap
    cands, dex, enr = candidates(run, a.live_24h)
    scored = [score(k, c, run, dex, enr) for k, c in cands.items()]
    md, picks = render(run, scored)
    if a.explain:
        for x in sorted(scored, key=lambda x: -x["score"]):
            print(f"# ${x['ticker']} raw {x['raw']} cap {x['cap']} -> {x['score']}/10 {x['breakdown']} hard={x['hard']}",
                  file=sys.stderr)
    if not a.stdout:
        stamp = re.sub(r"^run_|\.json$", "", os.path.basename(a.run))
        out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.run)), f"report_{stamp}.md")
        open(out, "w").write(md)
        print(f"wrote {out}", file=sys.stderr)
    print(md, end="")


if __name__ == "__main__":
    main()
