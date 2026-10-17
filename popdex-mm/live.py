"""Live executor + shared-account guards for mm.py. Active only when config mode == "live"
AND env POPDEX_LIVE=1. Implements live_prep/SHARED_ACCOUNT_SAFETY.md:
own ledger only (DDMM-tagged orders), never cancelAll/closeAll, never reduce-only,
BTC position reconcile every 30s (2 consecutive mismatches -> pause), margin floor guard."""
import json, sys, time, urllib.request, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_prep"))
from adapter import PopdexAdapter, is_ours, coid_str
API = "https://api.popdex.xyz/api/v1/account/"
TERMINAL = ("fullyfilled", "cancelled", "partiallyfilledcancelled", "filled", "canceled", "rejected")

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Content-Type": "application/json", "User-Agent": "degen-popdex-mm/1.0"}), timeout=10) as r:
        return json.load(r)

class Live:
    def __init__(s, cfg, keyfile):
        s.cfg = cfg; s.acct = cfg["account"]; s.sym = cfg["symbol"]
        s.ad = PopdexAdapter(s.acct, keyfile, cfg.get("net", "mainnet"))
        s.open = {}; s.last_reconcile = 0; s.mismatch = 0; s.lock = threading.Lock()
        s.sends = 0; s.send_errors = 0; s.last_acct_pos = None; s.recorded = {}
    def base(s): return API + s.acct
    def positions_snapshot(s):
        return {(p["symbol"], p["positionSide"]): p["holdQty"] for p in get(s.base() + "/positions")["data"]}
    def account_btc_pos(s):
        sg = {"Long": 1, "Short": -1}
        return sum(sg.get(p["positionSide"], 0) * float(p["holdQty"]) for p in get(s.base() + "/positions")["data"] if p["symbol"] == s.sym)
    def available_margin(s): return float(get(s.base() + "/overview")["data"]["availableMargin"])
    def pending(s):
        return [o for o in get(s.base() + f"/orders?symbol={s.sym}&category=Futures")["data"] if is_ours(o.get("clientOid"))]
    def order(s, coid):
        d = get(s.base() + "/orders/client-oid/" + coid_str(coid)).get("data")
        return (d[0] if d else {}) if isinstance(d, list) else (d or {})
    def cleanup_own(s):
        """cancel any resting DDMM orders (e.g. left by a crash). Own orders only."""
        n = 0
        for o in s.pending():
            c = o["clientOid"].encode().ljust(32, b"\0")
            try: s.ad.cancel_own(c); n += 1
            except Exception: pass
        return n
    def place(s, side, px, qty):
        lot, tick = s.cfg["lot"], s.cfg["tick"]
        if abs(qty / lot - round(qty / lot)) > 1e-9 or abs(px / tick - round(px / tick)) > 1e-9:
            raise ValueError(f"qty {qty} / price {px} not on lot/tick grid")
        if qty * px < s.cfg["min_notional"]: raise ValueError("below min notional")
        coid, tx = s.ad.place_post_only(s.cfg["symbol_id"], side, px, round(qty, 4), reduce_only=False)
        s.sends += 1
        with s.lock: s.open[coid] = {"side": side, "px": px, "qty": qty, "filled": 0.0, "tx": tx, "t": time.time(), "seen": False}
        return coid
    def cancel(s, coid):
        s.sends += 1; return s.ad.cancel_own(coid)
    def poll(s):
        """-> (fills, closed). Fills come from the exchange as truth: for every own DDMM order created
        since run start (open orders + order history), delta = filledQty - already recorded."""
        fills, closed = [], []
        orders = {}
        try:
            for o in get(s.base() + f"/history/orders?symbol={s.sym}&category=Futures&limit=100")["data"]: orders[o.get("clientOid")] = o
            for o in get(s.base() + f"/orders?symbol={s.sym}&category=Futures")["data"]: orders[o.get("clientOid")] = o
        except Exception: return fills, closed
        start_ms = s.cfg.get("live_run_start_ms", 0)
        for cid, o in orders.items():
            if not is_ours(cid): continue
            try: ts = int(cid[4:15], 16)
            except Exception: continue
            if ts < start_ms: continue
            f = float(o.get("filledQty") or 0); done = s.recorded.get(cid, 0.0)
            if f > done + 1e-12:
                side = "buy" if o["side"] == "Buy" else "sell"
                fills.append((side, float(o.get("avgDealPrice") or o.get("price")), round(f - done, 8))); s.recorded[cid] = f
            if str(o.get("status", "")).lower() in TERMINAL: closed.append(cid.encode().ljust(32, b"\0"))
        now_ = time.time()
        with s.lock:
            for coid, o in list(s.open.items()):
                cid = coid_str(coid)
                if cid in orders and str(orders[cid].get("status", "")).lower() in TERMINAL: s.open.pop(coid, None)
                elif cid not in orders and now_ - o["t"] > 30: s.open.pop(coid, None); closed.append(coid); s.send_errors += 1
        return fills, closed
    def guards(s, ledger_inv):
        if time.time() - s.last_reconcile < 30: return "keep"
        s.last_reconcile = time.time()
        acct = s.account_btc_pos(); s.last_acct_pos = acct
        if abs(acct - ledger_inv) > s.cfg["lot"] * 1.5:
            s.mismatch += 1
            if s.mismatch >= 2: return f"BTC position mismatch: account {acct} vs MM ledger {ledger_inv:.4f} (manual BTC trade?)"
        else: s.mismatch = 0
        if s.available_margin() < s.cfg.get("min_avail_margin_usd", 500): return "available margin below floor"
        return None
