#!/usr/bin/env python3
"""PopDEX BTCUSDT market maker for volume (Degen Desk).
SHADOW (default): live public feed (books5 + publicTrade), simulated post-only quotes and queue-aware fills,
no keys, no signing, no orders.
LIVE: only when config mode == "live" AND env POPDEX_LIVE=1 (systemd drop-in). Uses live.py + live_prep/adapter.py:
post-only quotes signed by a trade-only AGENT key the owner approved (secrets/agent_key.json, chmod 600),
own DDMM-tagged orders only, fills read from the exchange's order history, volume target -> unwind -> DONE,
run cost cap -> halt. See README.md and live_prep/SHARED_ACCOUNT_SAFETY.md."""
import asyncio, json, math, os, sys, time, datetime as dt
import warnings; warnings.filterwarnings("ignore", category=DeprecationWarning)
import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)
CFG = json.load(open(os.path.join(HERE, "config.json")))
LIVE = CFG.get("mode") == "live" and os.environ.get("POPDEX_LIVE") == "1"
if CFG.get("mode") not in ("shadow", "live") or (CFG.get("mode") == "live" and not LIVE):
    sys.exit("Live needs config mode=live AND env POPDEX_LIVE=1. Refusing.")
STOP = os.path.join(HERE, "STOP")
STATE_F = os.path.join(DATA, "state_live.json" if (CFG.get("mode") == "live" and os.environ.get("POPDEX_LIVE") == "1") else "state.json"); STATUS_F = os.path.join(DATA, "status.json")
T = CFG["tick"]; LOT = CFG["lot"]

def utcday(): return dt.datetime.utcnow().strftime("%Y-%m-%d")
def now(): return time.time()
def rnd_lot(q): return math.floor(q / LOT + 1e-9) * LOT

class MM:
    def __init__(s):
        s.bids = []; s.asks = []; s.book_ts = 0; s.last_trade_ts = 0
        s.quotes = {"buy": None, "sell": None}
        st = json.load(open(STATE_F)) if os.path.exists(STATE_F) else {}
        s.inv = st.get("inv", 0.0); s.cash = st.get("cash", 0.0)
        s.fees = st.get("fees", 0.0); s.vol = st.get("vol", 0.0)
        s.maker_vol = st.get("maker_vol", 0.0); s.taker_vol = st.get("taker_vol", 0.0)
        s.nfills = st.get("nfills", 0); s.writes = st.get("writes", 0)
        s.day = st.get("day", utcday()); s.day_start_pnl = st.get("day_start_pnl", None)
        s.halted = st.get("halted", None)
        s.mk = st.get("mk", {str(h): [0.0, 0] for h in CFG["markouts_s"]})
        s.pending_mk = []; s.started = now(); s.events = []; s.paused = None
        s.rec = None; s.rec_day = None; s.msgs = 0
        s.live = None; s.live_fills = []; s.live_guard_reason = None
        if LIVE:
            from live import Live
            s.live = Live(CFG, os.path.join(HERE, "secrets", "agent_key.json"))
            s.live.recorded = st.get("recorded", {})
            n = s.live.cleanup_own()
            if n: print(f"startup: cancelled {n} leftover own DDMM orders", flush=True)
        s.live_closed = []; s.unwinding = st.get("unwinding", False); s.run_started = st.get("run_started", now())

    # ---------- helpers ----------
    def mid(s):
        if not s.bids or not s.asks: return None
        return (s.bids[0][0] + s.asks[0][0]) / 2
    def pnl(s, m=None):
        m = m or s.mid()
        return None if m is None else s.cash + s.inv * m
    def record(s, kind, **kw):
        d = utcday()
        if d != s.rec_day:
            if s.rec: s.rec.close()
            s.rec = open(os.path.join(DATA, f"rec_{d}.jsonl"), "a"); s.rec_day = d
        s.rec.write(json.dumps({"t": round(now(), 3), "k": kind, **kw}) + "\n"); s.rec.flush()
    def event(s, msg):
        s.events = (s.events + [f"{dt.datetime.utcnow():%H:%M:%S}Z {msg}"])[-20:]
        s.record("event", msg=msg); print(msg, flush=True)
    def save(s):
        json.dump({k: getattr(s, k) for k in ["inv","cash","fees","vol","maker_vol","taker_vol",
                   "nfills","writes","day","day_start_pnl","halted","mk","unwinding","run_started"]} | ({"recorded": s.live.recorded} if s.live else {}), open(STATE_F + ".tmp", "w"))
        os.replace(STATE_F + ".tmp", STATE_F)

    # ---------- simulated order actions ----------
    def cancel(s, side):
        q = s.quotes[side]
        if q:
            s.writes += 1; s.quotes[side] = None
            if s.live and q.get("coid"):
                try: s.live.cancel(q["coid"])
                except Exception as e: s.event(f"LIVE cancel error {e}")
    def cancel_all(s):
        for sd in ("buy", "sell"): s.cancel(sd)
    def place(s, side, px, qty, reduce_only=False):
        book = s.bids if side == "buy" else s.asks
        # post-only: reject if crossing
        if side == "buy" and s.asks and px >= s.asks[0][0]: return
        if side == "sell" and s.bids and px <= s.bids[0][0]: return
        ahead = None
        for p, q in book:
            if abs(p - px) < T / 2: ahead = q; break
        if ahead is None:
            better = (px > book[0][0]) if (book and side == "buy") else (px < book[0][0]) if book else True
            # new price level inside the spread -> front of queue; behind visible depth -> assume huge queue
            ahead = 0.0 if better else (1e9 if len(book) >= 5 and ((side == "buy" and px < book[-1][0]) or (side == "sell" and px > book[-1][0])) else 0.0)
        if s.live: reduce_only = False  # shared one-way account: never reduce-only
        s.writes += 1
        coid = None
        if s.live:
            try: coid = s.live.place(side, px, round(qty, 4))
            except Exception as e: s.event(f"LIVE place error {e}"); return
        s.quotes[side] = {"coid": coid, "px": px, "qty": round(qty, 4), "ahead": ahead, "ro": reduce_only, "t": now()}

    def fill(s, side, px, qty, maker=True):
        sgn = 1 if side == "buy" else -1
        fee = px * qty * (CFG["maker_fee"] if maker else CFG["taker_fee"])
        s.inv += sgn * qty; s.cash -= sgn * px * qty + fee
        s.fees += fee; s.vol += px * qty; s.nfills += 1
        if maker: s.maker_vol += px * qty
        else: s.taker_vol += px * qty
        t = now()
        for h in CFG["markouts_s"]: s.pending_mk.append((t + h, h, sgn, px))
        s.record("fill", side=side, px=px, qty=qty, maker=maker, fee=round(fee, 6), inv=round(s.inv, 6))
        s.event(f"FILL {'maker' if maker else 'TAKER'} {side} {qty:.4f} @ {px:.1f} inv={s.inv:+.4f}")

    def on_trade(s, px, qty, side):
        if s.live: return  # live fills come from the exchange (own DDMM orders only)
        # aggressor side Sell hits bids (our buy); Buy lifts asks (our sell)
        q = s.quotes["buy"] if side == "Sell" else s.quotes["sell"]
        mine = "buy" if side == "Sell" else "sell"
        if not q: return
        through = px < q["px"] - T/2 if mine == "buy" else px > q["px"] + T/2
        at = abs(px - q["px"]) < T/2
        if through:
            s.fill(mine, q["px"], q["qty"]); s.quotes[mine] = None
        elif at:
            q["ahead"] -= qty
            if q["ahead"] < 0:
                f = rnd_lot(min(q["qty"], -q["ahead"])); q["ahead"] = 0
                if f >= LOT:
                    s.fill(mine, q["px"], f); q["qty"] = rnd_lot(q["qty"] - f)
                    if q["qty"] < LOT or q["qty"] * q["px"] < CFG["min_notional"]: s.quotes[mine] = None

    def on_book(s):
        # a level we were queued at that shrank -> those ahead of us cancelled/filled; keep ahead <= displayed size
        for side, book in (("buy", s.bids), ("sell", s.asks)):
            q = s.quotes[side]
            if not q: continue
            for p, sz in book:
                if abs(p - q["px"]) < T/2:
                    q["ahead"] = min(q["ahead"], sz); break

    # ---------- strategy ----------
    def desired(s, m):
        cap = CFG["inv_cap_usd"]; inv_usd = s.inv * m; ratio = max(-1, min(1, inv_usd / cap))
        skew = -ratio * CFG["skew_ticks_at_cap"] * T
        off = CFG["offset_ticks"] * T
        bb, ba = s.bids[0][0], s.asks[0][0]
        bid = math.floor((m + skew - off) / T) * T; ask = math.ceil((m + skew + off) / T) * T
        bid = min(bid, ba - T); ask = max(ask, bb + T)
        bid = max(bid, bb - CFG["max_offset_ticks"] * T); ask = min(ask, ba + CFG["max_offset_ticks"] * T)
        qty = rnd_lot(max(CFG["min_order_usd"], min(CFG["max_order_usd"], CFG["order_usd"])) / m)
        out = {"buy": (bid, qty, False), "sell": (ask, qty, False)}
        if inv_usd >= cap:   # long at cap: only reduce
            out["buy"] = None; out["sell"] = (max(bb + T, ba - 0*T), rnd_lot(min(qty * 2, s.inv)) or qty, True)
        if inv_usd <= -cap:
            out["sell"] = None; out["buy"] = (min(ba - T, bb), rnd_lot(min(qty * 2, -s.inv)) or qty, True)
        return out

    def flatten_taker(s, reason):
        if s.live:  # never take/flatten on the shared account: pull own quotes, alert
            s.cancel_all(); s.event(f"LIVE: flatten needed ({reason}); own quotes pulled, MM inv {s.inv:+.4f} left for manual review"); return
        m = s.mid()
        if abs(s.inv) < LOT / 2 or m is None: return
        side = "sell" if s.inv > 0 else "buy"
        px = s.bids[0][0] if side == "sell" else s.asks[0][0]
        s.writes += 1; s.event(f"TAKER FLATTEN ({reason})"); s.fill(side, px, abs(s.inv), maker=False)

    def step(s):
        t = now(); m = s.mid()
        if m is None: return
        # markouts
        keep = []
        for due, h, sgn, px in s.pending_mk:
            if t >= due:
                a = s.mk[str(h)]; a[0] += sgn * (m - px) / px * 1e4; a[1] += 1
            else: keep.append((due, h, sgn, px))
        s.pending_mk = keep
        # day roll
        d = utcday()
        if d != s.day: s.day = d; s.day_start_pnl = s.pnl(); s.halted = None if s.halted == "daily_loss" else s.halted; s.event("UTC day roll")
        if s.day_start_pnl is None: s.day_start_pnl = s.pnl()
        if os.path.exists(STOP):
            if s.halted != "STOP": s.cancel_all(); s.flatten_taker("STOP file"); s.halted = "STOP"; s.event("STOP file -> halted")
            return
        elif s.halted == "STOP": s.halted = None; s.event("STOP removed -> resume")
        if s.halted: return
        if s.live:
            for sd, px, q in s.live_fills: s.fill(sd, px, q)
            s.live_fills = []
            for c in s.live_closed:
                for sd in ("buy", "sell"):
                    if s.quotes[sd] and s.quotes[sd].get("coid") == c: s.quotes[sd] = None
            s.live_closed = []
            p = s.pnl()
            if p is not None and p <= -CFG.get("run_cost_cap_usd", 40):
                s.cancel_all(); s.halted = "cost_cap"; s.event(f"RUN COST CAP hit pnl {p:.2f} -> halted (own inv {s.inv:+.4f} left)"); return
            if not s.unwinding and s.vol >= CFG.get("volume_target_usd", 1e18):
                s.unwinding = True; s.cancel_all(); s.event(f"VOLUME TARGET reached ${s.vol:,.0f} -> unwinding own inventory")
            r = s.live_guard_reason
            if r:
                if s.paused != r: s.cancel_all(); s.paused = r; s.event(f"LIVE GUARD pause: {r}")
                return
            elif s.paused and s.paused != "stale": s.paused = None; s.event("live guard ok -> resume")
        day_pnl = s.pnl() - s.day_start_pnl
        if day_pnl <= -CFG["daily_loss_pct"] * CFG["equity_usd"]:
            s.cancel_all(); s.flatten_taker("daily loss cap"); s.halted = "daily_loss"
            s.event(f"DAILY LOSS CAP hit {day_pnl:.2f} -> halted until UTC day roll"); return
        stale = t - s.book_ts > CFG["stale_sec"]
        if stale:
            if s.paused != "stale": s.cancel_all(); s.paused = "stale"; s.event("feed stale -> quotes pulled")
            return
        elif s.paused == "stale": s.paused = None; s.event("feed ok -> resume")
        if not s.live and abs(s.inv * m) >= CFG["inv_cap_usd"] * CFG["hard_flatten_mult"]:
            s.cancel_all(); s.flatten_taker("hard inventory cap")
        want = s.desired(m)
        if s.unwinding:
            q_abs = rnd_lot(abs(s.inv))
            if q_abs * m < CFG["min_notional"]:
                s.cancel_all(); s.halted = "DONE"
                s.event(f"DONE: volume ${s.vol:,.0f}, pnl {s.pnl():.2f}, residual inv {s.inv:+.4f} (below min order)"); return
            want = {"buy": None, "sell": None}
            if s.inv > 0: want["sell"] = (s.asks[0][0], q_abs, False)
            else: want["buy"] = (s.bids[0][0], q_abs, False)
        for side in ("buy", "sell"):
            w = want[side]; q = s.quotes[side]
            if w is None:
                if q: s.cancel(side)
                continue
            px, qty, ro = w
            thr = 1 if s.unwinding else CFG["requote_ticks"]
            if q is None or abs(q["px"] - px) >= thr * T or q["ro"] != ro or (s.unwinding and abs(q["qty"] - qty) > LOT / 2):
                if q: s.cancel(side)
                s.place(side, px, qty, ro)

    def status(s):
        m = s.mid(); p = s.pnl(m); up = now() - s.started
        quota = CFG["write_quota_base"] + int(s.vol)
        st = {
            "mode": "LIVE" if LIVE else "SHADOW (simulated fills, no orders)", "symbol": CFG["symbol"], "updated_utc": dt.datetime.utcnow().isoformat(timespec="seconds"),
            "uptime_s": int(up), "feed_msgs": s.msgs, "book_age_s": round(now() - s.book_ts, 1),
            "mid": m, "best_bid": s.bids[0] if s.bids else None, "best_ask": s.asks[0] if s.asks else None,
            "quotes": s.quotes, "inventory_btc": round(s.inv, 6), "inventory_usd": round(s.inv * m, 2) if m else None,
            "pnl_usd": round(p, 4) if p is not None else None, "pnl_ex_fees_usd": round(p + s.fees, 4) if p is not None else None,
            "day_pnl_usd": round(p - s.day_start_pnl, 4) if p is not None and s.day_start_pnl is not None else None,
            "fees_usd": round(s.fees, 4), "volume_usd": round(s.vol, 2), "maker_volume_usd": round(s.maker_vol, 2),
            "taker_volume_usd": round(s.taker_vol, 2), "fills": s.nfills,
            "cost_per_100k_usd": round(-p / s.vol * 1e5, 2) if s.vol > 0 and p is not None else None,
            "fee_per_100k_usd": round(s.fees / s.vol * 1e5, 2) if s.vol > 0 else None,
            "markout_bps_avg": {h: (round(a[0] / a[1], 3) if a[1] else None, a[1]) for h, a in s.mk.items()},
            "writes_used_est": s.writes, "write_quota_est": min(quota, 500000),
            "writes_per_hour": round(s.writes / max(up, 1) * 3600, 1),
            "halted": s.halted, "paused": s.paused, "events": s.events[-10:],
            "live": {"order_usd": CFG["order_usd"], "volume_target_usd": CFG.get("volume_target_usd"),
                     "progress_pct": round(100 * s.vol / CFG["volume_target_usd"], 2) if CFG.get("volume_target_usd") else None,
                     "run_hours": round((now() - s.run_started) / 3600, 3),
                     "vol_per_hour": round(s.vol / max((now() - s.run_started) / 3600, 1e-6), 0),
                     "eta_hours": round((CFG["volume_target_usd"] - s.vol) / max(s.vol / max((now() - s.run_started) / 3600, 1e-6), 1e-6), 1) if CFG.get("volume_target_usd") and s.vol > 0 else None,
                     "unwinding": s.unwinding, "run_cost_cap_usd": CFG.get("run_cost_cap_usd"),
                     "account_btc_pos": s.live.last_acct_pos, "open_own_orders": len(s.live.open),
                     "sends": s.live.sends, "rejected_or_lost": s.live.send_errors} if s.live else None,
        }
        json.dump(st, open(STATUS_F + ".tmp", "w"), indent=1, default=str); os.replace(STATUS_F + ".tmp", STATUS_F)
        s.save()

    # ---------- feed ----------
    async def run(s):
        sub = {"op": "subscribe", "args": [
            {"category": "Futures", "topic": "books5", "symbol": CFG["symbol"]},
            {"category": "Futures", "topic": "publicTrade", "symbol": CFG["symbol"]}]}
        backoff = 1
        while True:
            try:
                async with websockets.connect(CFG["ws_url"], ping_interval=None, max_size=2**22, open_timeout=15) as ws:
                    await ws.send(json.dumps(sub)); s.event("ws connected + subscribed"); backoff = 1
                    async def pinger():
                        while True: await asyncio.sleep(20); await ws.send("ping")
                    pt = asyncio.create_task(pinger())
                    try:
                        async for raw in ws:
                            if raw == "pong": continue
                            s.msgs += 1
                            try: msg = json.loads(raw)
                            except Exception: continue
                            arg = msg.get("arg", {}); topic = arg.get("topic"); data = msg.get("data")
                            if msg.get("event"):
                                if msg.get("event") == "error": s.event(f"ws error {msg}")
                                continue
                            if topic == "books5" and isinstance(data, dict):
                                s.bids = [(float(p), float(q)) for p, q in data.get("b", [])]
                                s.asks = [(float(p), float(q)) for p, q in data.get("a", [])]
                                s.book_ts = now(); s.on_book()
                                if s.snap_due(): s.record("top", b=s.bids[:1], a=s.asks[:1])
                            elif topic == "publicTrade" and isinstance(data, list):
                                for tr in data:
                                    s.on_trade(float(tr["price"]), float(tr["size"]), tr.get("side"))
                                    s.last_trade_ts = now()
                    finally: pt.cancel()
            except Exception as e:
                s.event(f"ws disconnected: {type(e).__name__} {str(e)[:120]}")
            await asyncio.sleep(backoff); backoff = min(backoff * 2, 30)

    _ls = 0
    def snap_due(s):
        if now() - s._ls >= CFG["snap_every"]: s._ls = now(); return True
        return False

    async def loop(s):
        last = 0
        while True:
            await asyncio.sleep(0.2)
            try:
                s.step()
                if now() - last >= CFG["status_every"]: s.status(); last = now()
            except Exception as e: s.event(f"step error {type(e).__name__}: {e}")

async def live_poll(m):
    while True:
        await asyncio.sleep(2)
        try:
            f, c = await asyncio.to_thread(m.live.poll)
            m.live_fills += f; m.live_closed += c
            g = await asyncio.to_thread(m.live.guards, m.inv)
            if g != "keep": m.live_guard_reason = g
        except Exception as e: m.live_guard_reason = f"live poll error {type(e).__name__}"

async def main():
    m = MM(); m.event("start " + ("LIVE" if LIVE else "SHADOW"))
    if LIVE:
        import signal
        def _term(*a):
            try: m.cancel_all(); m.status(); print("SIGTERM: own quotes cancelled", flush=True)
            finally: os._exit(0)
        signal.signal(signal.SIGTERM, _term)
    await asyncio.gather(m.run(), m.loop(), *([live_poll(m)] if LIVE else []))

if __name__ == "__main__":
    asyncio.run(main())
