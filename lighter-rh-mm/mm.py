#!/usr/bin/env python3
"""Lighter (Robinhood Chain) market maker. Shadow mode by default; never places orders unless --live."""
import argparse, asyncio, json, math, os, subprocess, sys, time, urllib.request, collections, signal

_D = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(_D, "config.json") if os.path.exists(os.path.join(_D, "config.json")) else os.path.join(_D, "config.example.json")))
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def get(path):
    with urllib.request.urlopen(urllib.request.Request(CFG["rest"] + path, headers={"User-Agent": "mm"}), timeout=5) as r:
        return json.load(r)

# ---------------- market feed (ws preferred, REST poll fallback) ----------------
class Book:
    def __init__(s): s.bids, s.asks, s.ts = [], [], 0.0
    @property
    def mid(s): return (s.bids[0][0] + s.asks[0][0]) / 2 if s.bids and s.asks else None

class Feed:
    def __init__(s, mids, mode, on_trade, log):
        s.mids, s.mode, s.on_trade, s.log = mids, mode, on_trade, log
        s.books = {m: Book() for m in mids}; s.seen = {m: set() for m in mids}
    async def run(s):
        if s.mode == "ws": await s.ws()
        else: await s.poll()
    async def poll(s):
        while True:
            for m in s.mids:
                try:
                    ob = await asyncio.to_thread(get, f"/api/v1/orderBookOrders?market_id={m}&limit=20")
                    b = s.books[m]
                    b.bids = [(float(o["price"]), float(o["remaining_base_amount"])) for o in ob["bids"]]
                    b.asks = [(float(o["price"]), float(o["remaining_base_amount"])) for o in ob["asks"]]
                    b.ts = time.time()
                    s.log("book", m, {"bids": b.bids[:5], "asks": b.asks[:5]})
                    tr = await asyncio.to_thread(get, f"/api/v1/recentTrades?market_id={m}&limit=50")
                    new = [t for t in tr["trades"] if t["trade_id"] not in s.seen[m]]
                    first = not s.seen[m]
                    for t in sorted(new, key=lambda t: t["trade_id"]):
                        s.seen[m].add(t["trade_id"])
                        if first: continue  # skip backlog
                        ev = {"id": t["trade_id"], "px": float(t["price"]), "sz": float(t["size"]),
                              "taker_buy": t["is_maker_ask"], "ts": t["timestamp"] / 1000}
                        # is_maker_ask True => maker sold => taker BUY
                        s.log("trade", m, ev); s.on_trade(m, ev)
                    if len(s.seen[m]) > 5000: s.seen[m] = set(sorted(s.seen[m])[-1000:])
                except Exception as e:
                    s.log("err", m, {"e": str(e)[:200]})
            await asyncio.sleep(CFG["poll_s"])
    async def ws(s):
        import websockets
        async with websockets.connect(CFG["ws"], ping_interval=20) as w:
            for m in s.mids:
                await w.send(json.dumps({"type": "subscribe", "channel": f"order_book/{m}"}))
                await w.send(json.dumps({"type": "subscribe", "channel": f"trade/{m}"}))
            levels = {m: ({}, {}) for m in s.mids}
            async for raw in w:
                msg = json.loads(raw); ch = msg.get("channel", "")
                if "order_book" in ch:
                    m = int(ch.split(":")[-1].split("/")[-1]); bd, ad = levels[m]
                    ob = msg.get("order_book", {})
                    for side, d in (("bids", bd), ("asks", ad)):
                        for o in ob.get(side, []):
                            p, z = float(o["price"]), float(o["size"])
                            if z == 0: d.pop(p, None)
                            else: d[p] = z
                    b = s.books[m]
                    b.bids = sorted(bd.items(), reverse=True)[:20]; b.asks = sorted(ad.items())[:20]; b.ts = time.time()
                    s.log("book", m, {"bids": b.bids[:5], "asks": b.asks[:5]})
                elif "trade" in ch:
                    m = int(ch.split(":")[-1].split("/")[-1])
                    for t in msg.get("trades", []):
                        ev = {"id": t["trade_id"], "px": float(t["price"]), "sz": float(t["size"]),
                              "taker_buy": t["is_maker_ask"], "ts": t["timestamp"] / 1000}
                        s.log("trade", m, ev); s.on_trade(m, ev)

# ---------------- quoting engine ----------------
class Quoter:
    def __init__(s, m, mc):
        s.m, s.mc = m, mc; s.mids = collections.deque()
    def update_vol(s, mid, now):
        s.mids.append((now, mid))
        while s.mids and now - s.mids[0][0] > CFG["vol_window_s"]: s.mids.popleft()
    def vol_bps(s):
        p = [x[1] for x in s.mids]
        if len(p) < 5: return 0.0
        r = [math.log(p[i] / p[i - 1]) for i in range(1, len(p))]
        mu = sum(r) / len(r)
        return 1e4 * math.sqrt(sum((x - mu) ** 2 for x in r) / len(r))  # per-tick stdev in bps
    def quotes(s, book, pos_usd, total_exposure):
        mid = book.mid
        if mid is None: return None
        min_half = CFG["fee_bps"] + CFG["buffer_bps"]
        half = max(min_half, CFG["vol_k"] * s.vol_bps(), (book.asks[0][0] - book.bids[0][0]) / mid * 1e4 / 2)
        maxp = s.mc["max_pos_usd"]
        skew = -CFG["skew_bps_at_max"] * max(-1, min(1, pos_usd / maxp))  # long -> shift quotes down
        bid = mid * (1 + (skew - half) / 1e4); ask = mid * (1 + (skew + half) / 1e4)
        # post-only: never cross touch
        bid = min(bid, book.asks[0][0] - 1e-9); ask = max(ask, book.bids[0][0] + 1e-9)
        size_usd = max(CFG["min_order_usd"], s.mc["order_usd"])
        room_long = min(maxp - pos_usd, CFG["total_exposure_usd"] - total_exposure)
        room_short = min(maxp + pos_usd, CFG["total_exposure_usd"] - total_exposure)
        lev_cap = CFG["max_leverage"] * CFG["equity_usd"]
        q = {}
        if room_long >= CFG["min_order_usd"] and total_exposure + size_usd <= lev_cap or pos_usd < 0:
            q["bid"] = (bid, min(size_usd, max(room_long, -pos_usd)) / mid)
        if room_short >= CFG["min_order_usd"] and total_exposure + size_usd <= lev_cap or pos_usd > 0:
            q["ask"] = (ask, min(size_usd, max(room_short, pos_usd)) / mid)
        return q

# ---------------- fill simulator (queue-conservative) ----------------
class Sim:
    """Our resting quote fills only when a public taker trade prints STRICTLY through our price
    (price better than ours), i.e. assumes we are last in queue at our level. Fill size capped by trade size."""
    def __init__(s, mids):
        s.pos = {m: 0.0 for m in mids}; s.cash = {m: 0.0 for m in mids}; s.quotes = {m: {} for m in mids}
        s.fills = []; s.pending_mo = []; s.fees = 0.0
    def on_trade(s, m, t, mid, log):
        q = s.quotes[m]
        if t["taker_buy"] and "ask" in q and t["px"] > q["ask"][0]:
            s._fill(m, "sell", q["ask"][0], min(q["ask"][1], t["sz"]), mid, log); q.pop("ask")
        elif not t["taker_buy"] and "bid" in q and t["px"] < q["bid"][0]:
            s._fill(m, "buy", q["bid"][0], min(q["bid"][1], t["sz"]), mid, log); q.pop("bid")
    def _fill(s, m, side, px, sz, mid, log):
        sgn = 1 if side == "buy" else -1
        fee = px * sz * CFG["fee_bps"] / 1e4
        s.pos[m] += sgn * sz; s.cash[m] -= sgn * px * sz + fee; s.fees += fee
        f = {"m": m, "side": side, "px": px, "sz": sz, "mid": mid, "ts": time.time(), "mo": {}}
        s.fills.append(f); log("fill", m, f)
    def pnl(s, m, mid): return s.cash[m] + s.pos[m] * mid
    def markouts(s, books):
        now = time.time()
        for f in s.fills:
            for h in CFG["markout_s"]:
                if str(h) not in f["mo"] and now - f["ts"] >= h and books[f["m"]].mid:
                    sgn = 1 if f["side"] == "buy" else -1
                    f["mo"][str(h)] = sgn * (books[f["m"]].mid - f["px"]) / f["px"] * 1e4  # bps, + = good

# ---------------- kill switches ----------------
class Risk:
    def __init__(s, stale_s=None):
        s.stale_s = stale_s or CFG["stale_s"]
        s.rejects = 0; s.day = time.strftime("%Y-%m-%d"); s.day_start_pnl = 0.0; s.reason = None
    def check(s, total_pnl, books, positions_usd):
        if time.strftime("%Y-%m-%d") != s.day: s.day, s.day_start_pnl = time.strftime("%Y-%m-%d"), total_pnl
        if os.path.exists(CFG["stop_file"]): return "stop file present"
        if total_pnl - s.day_start_pnl < -CFG["daily_loss_pct"] / 100 * CFG["equity_usd"]: return "daily loss limit"
        for m, b in books.items():
            if time.time() - b.ts > s.stale_s: return f"stale feed market {m}"
        for m, p in positions_usd.items():
            if abs(p) > CFG["markets"][str(m)]["max_pos_usd"] * 1.25: return f"position cap market {m}"
        if sum(abs(p) for p in positions_usd.values()) > CFG["total_exposure_usd"] * 1.25: return "total exposure cap"
        if s.rejects >= CFG["max_rejects"]: return "too many rejects/nonce errors"
        return None

# ---------------- live execution stub ----------------
class LiveExec:
    """Disabled unless --live. Reads key from macOS Keychain. Uses official lighter-python SignerClient."""
    def __init__(s):
        if CFG["account_index"] is None or CFG["api_key_index"] is None:
            sys.exit("live: set account_index and api_key_index in config.json")
        key = subprocess.run(["security", "find-generic-password", "-s", CFG["keychain_service"],
                              "-a", CFG["keychain_account"], "-w"], capture_output=True, text=True).stdout.strip()
        if not key: sys.exit("live: key not found in Keychain (service lighter-rh, account api)")
        import lighter  # pip install git+https://github.com/elliottech/lighter-python
        s.client = lighter.SignerClient(url=CFG["rest"], private_key=key,
                                        account_index=CFG["account_index"], api_key_index=CFG["api_key_index"])
        del key
        raise NotImplementedError("live order placement intentionally not enabled in phase 1 (shadow only)")
    async def replace_quotes(s, m, q): ...      # post-only (time_in_force=POST_ONLY) create/modify
    async def cancel_all(s): ...                # client.cancel_all_orders(...)
    async def reduce_only_close(s, m, pos): ... # IOC reduce_only market close

# ---------------- main loop ----------------
async def main(a):
    mids = [int(m) for m in CFG["markets"]]
    os.makedirs(DATA, exist_ok=True)
    rec = open(os.path.join(DATA, f"rec_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"), "a")
    def log(kind, m, d):
        rec.write(json.dumps({"t": round(time.time(), 3), "k": kind, "m": m, "d": d}) + "\n"); rec.flush()
    sim, risk = Sim(mids), Risk(None if a.feed == "ws" else 15.0)  # REST poll cycle is slower; live requires ws + 3s
    quoters = {m: Quoter(m, CFG["markets"][str(m)]) for m in mids}
    feed = Feed(mids, a.feed, lambda m, t: sim.on_trade(m, t, feed.books[m].mid, log), log)
    if a.live and a.feed != "ws": sys.exit("live requires --feed ws")
    live = LiveExec() if a.live else None
    stop = asyncio.Event()
    for sg in (signal.SIGINT, signal.SIGTERM): asyncio.get_running_loop().add_signal_handler(sg, stop.set)
    ft = asyncio.create_task(feed.run()); t0 = time.time(); last_status = 0
    try:
        await asyncio.sleep(3)
        while not stop.is_set() and not ft.done():
            now = time.time()
            pos_usd = {m: sim.pos[m] * (feed.books[m].mid or 0) for m in mids}
            tot = sum(sim.pnl(m, feed.books[m].mid or 0) for m in mids)
            r = risk.check(tot, feed.books, pos_usd)
            if r:
                log("kill", -1, {"reason": r}); print(time.strftime("%H:%M:%S"), "KILL:", r, flush=True)
                for m in mids: sim.quotes[m] = {}
                if live: await live.cancel_all(); [await live.reduce_only_close(m, sim.pos[m]) for m in mids]
                if "stale" in r: await asyncio.sleep(1); continue  # shadow: resume when feed recovers
                break
            expo = sum(abs(v) for v in pos_usd.values())
            for m in mids:
                b = feed.books[m]
                if b.mid is None: continue
                quoters[m].update_vol(b.mid, now)
                q = quoters[m].quotes(b, pos_usd[m], expo)
                if q is not None:
                    old = sim.quotes[m]
                    for side in ("bid", "ask"):
                        if side in q and (side not in old or abs(q[side][0] / old[side][0] - 1) * 1e4 > CFG["requote_bps"]):
                            old[side] = q[side]
                        elif side not in q: old.pop(side, None)
                    if live: await live.replace_quotes(m, old)
            sim.markouts(feed.books)
            if now - last_status > a.status_s:
                last_status = now; write_status(sim, feed, quoters, t0, mids)
            if a.duration and now - t0 > a.duration: break
            await asyncio.sleep(0.5)
    finally:
        if live: await live.cancel_all()
        write_status(sim, feed, quoters, t0, mids); ft.cancel(); rec.close()

def write_status(sim, feed, quoters, t0, mids):
    out = {"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "runtime_min": round((time.time() - t0) / 60, 1), "markets": {}}
    for m in mids:
        mid = feed.books[m].mid or 0; fs = [f for f in sim.fills if f["m"] == m]
        mo = {h: [f["mo"][h] for f in fs if h in f["mo"]] for h in map(str, CFG["markout_s"])}
        vol = sum(f["px"] * f["sz"] for f in fs)
        out["markets"][CFG["markets"][str(m)]["symbol"]] = {
            "mid": mid, "fills": len(fs), "volume_usd": round(vol, 2), "pos": round(sim.pos[m], 6),
            "pos_usd": round(sim.pos[m] * mid, 2), "pnl_usd": round(sim.pnl(m, mid), 4),
            "pnl_bps_of_volume": round(sim.pnl(m, mid) / vol * 1e4, 2) if vol else None,
            "markout_bps_avg": {h: round(sum(v) / len(v), 2) if v else None for h, v in mo.items()},
            "adverse_pct_5s": round(100 * sum(1 for x in mo["5"] if x < 0) / len(mo["5"]), 1) if mo["5"] else None,
            "vol_bps": round(quoters[m].vol_bps(), 3), "quotes": sim.quotes[m]}
    out["total_pnl_usd"] = round(sum(v["pnl_usd"] for v in out["markets"].values()), 4)
    json.dump(out, open(os.path.join(DATA, "status.json"), "w"), indent=1)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="REAL orders. Off by default.")
    p.add_argument("--feed", choices=["ws", "poll"], default="ws")
    p.add_argument("--duration", type=float, default=0)
    p.add_argument("--status-s", type=float, default=30)
    a = p.parse_args()
    if a.live: print("LIVE MODE requested", flush=True)
    else: print("SHADOW MODE: no orders will be placed", flush=True)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    asyncio.run(main(a))
