#!/usr/bin/env python3
"""Degen Desk call executor: turns every BTC / XAU call from the box into a live Lighter order group.

Inbox protocol (box -> VPS over SFTP): JSON files written atomically into calls/inbox/.
  {"msg": "<unique file name>", "action": "open|cancel|update", "id": call id, "symbol": "BTC|XAU", "side": "long|short",
   "entry", "stop", "tp1", "tp2", "expiry" (ISO), "test": bool, "close_if_filled": bool}
Each processed file is moved to calls/done/ and an ack calls/ack/<msg>.json is written ({"ok", "result"}).
The box keeps resending until the ack exists; duplicates are acked again without acting.

Execution per call: entry = GTT limit at the call entry (basis-adjusted from OKX to Lighter), split in two OTOCO groups
(half -> TP1, half -> TP2 runner), each with its own reduce-only exchange stop at the call stop. No break-even move.
Size: 2% of equity at risk, capped by per-market leverage, by total open risk (calls + autopilot) <= 4%, never rounded up.
Guards: STOP file (cancel + flatten our orders/positions), 4% UTC-day loss stop, 15% drawdown pause, one position per market.

PRACTICE by default: without env CALLS_LIVE=1 every call is sized and validated but nothing is sent (ack says "practice").
Set account_index / api_key_index / chat_id in calls/config.json (or LIGHTER_ACCOUNT_INDEX / LIGHTER_API_KEY_INDEX env).
The Lighter API key comes only from the environment (LIGHTER_API_PRIVATE_KEY, systemd EnvironmentFile chmod 600).
"""
import json, os, sys, time, math, traceback, urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("AUTOPILOT_HOME", "/opt/degen-desk"))
CD = HOME / "calls"
INBOX, DONE, ACK = CD / "inbox", CD / "done", CD / "ack"
STATE, LOG = CD / "state.json", CD / "log.jsonl"
sys.path.insert(0, str(HOME))
import exchange as X

CFG = dict(account_index=None, api_key_index=None, risk=0.02, max_total_risk=0.04, daily_loss=0.04, drawdown=0.15,
           lev_cap={"BTC": 10, "XAU": 15}, okx={"BTC": "BTC-USDT-SWAP", "XAU": "XAU-USDT-SWAP"}, max_basis_pct=0.3,
           stop_worst_pct=0.5, poll_s=10, chat_id=None)
p = CD / "config.json"
if p.exists():
    CFG.update(json.loads(p.read_text()))
CFG["account_index"] = int(os.environ.get("LIGHTER_ACCOUNT_INDEX") or CFG["account_index"] or 0) or None
CFG["api_key_index"] = int(os.environ.get("LIGHTER_API_KEY_INDEX") or CFG["api_key_index"] or 0) or None
if not CFG["account_index"] or not CFG["api_key_index"]:
    sys.exit("set account_index / api_key_index in calls/config.json or LIGHTER_ACCOUNT_INDEX / LIGHTER_API_KEY_INDEX")
LIVE = os.environ.get("CALLS_LIVE") == "1"
FOOT = "Auto-traded by Degen Desk · Not financial advice"
TERMINAL = {"closed", "cancelled", "expired", "skipped", "invalidated", "rejected", "vanished", "killed", "practice"}


def now(): return time.time()
def iso(t=None): return datetime.fromtimestamp(t or now(), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
def log(ev, **kw):
    line = json.dumps({"ts": iso(), "event": ev, **kw}, default=str)
    line = X.redact(line)
    with open(LOG, "a") as f: f.write(line + "\n")
    print(line, flush=True)


def tg(text):
    if not CFG.get("chat_id"):
        return
    if not LIVE:
        text = "<b>PRACTICE TRADE, no real money</b>\n" + text
    try:
        import notify
        notify.Telegram(CFG["chat_id"])._send_text(text + f"\n\n<i>{FOOT}</i>", parse_mode="HTML")
    except Exception as e:
        log("telegram_failed", error=str(e)[:200])


class Exec:
    def __init__(self):
        for d in (INBOX, DONE, ACK): d.mkdir(parents=True, exist_ok=True)
        self.ex = {s: X.LighterExchange(CFG["account_index"], CFG["api_key_index"], symbol=s, allow_send=LIVE) for s in ("BTC", "XAU")}
        if LIVE: self.ex["BTC"].keycheck()
        self.st = json.loads(STATE.read_text()) if STATE.exists() else {"calls": {}, "seen": [], "day": None,
                                                                             "day_start": None, "peak": None, "paused": False, "halted": False}

    def save(self):
        self.st["seen"] = self.st["seen"][-2000:]
        t = STATE.with_suffix(".tmp"); t.write_text(json.dumps(self.st, indent=1, default=str)); t.replace(STATE)
        for s in ("BTC", "XAU"):
            f = CD / f"busy_{s}"
            if any(c["symbol"] == s and c["status"] not in TERMINAL for c in self.st["calls"].values()):
                f.touch()
            elif f.exists():
                f.unlink()

    # ---------------------------------------------------------------- helpers
    def equity(self): return self.ex["BTC"].account()["equity"]

    def mid(self, s):
        b, a = self.ex[s].book(); return (b + a) / 2

    def basis(self, s, ref=None, ref_ts=None):
        if ref and (not ref_ts or now() - float(ref_ts) < 600):      # OKX price sampled on the box at send time
            lm = self.mid(s); b = lm - float(ref)
            return b if abs(b) / float(ref) * 100 <= CFG["max_basis_pct"] else None
        try:
            with urllib.request.urlopen(f"https://www.okx.com/api/v5/market/ticker?instId={CFG['okx'][s]}", timeout=8) as r:
                okx = float(json.load(r)["data"][0]["last"])
            lm = self.mid(s); b = lm - okx
            return b if abs(b) / okx * 100 <= CFG["max_basis_pct"] else None
        except Exception as e:
            log("basis_failed", symbol=s, error=str(e)[:150]); return 0.0

    def orders_detail(self, ex, which="inactive", limit=50):
        """Read-only: our orders on this market with sizes, keyed by client_order_index.
        which = "active" | "inactive" (filled / cancelled history). None if unavailable."""
        try:
            if ex._client is None and ex.active_orders() is None:
                return None
            lighter, _ = ex._sdk()
            auth, err = ex._client.create_auth_token_with_expiry(600)
            if err or not auth:
                return None
            api = lighter.OrderApi(ex._client.api_client)
            if which == "active":
                r = ex._run(api.account_active_orders(authorization=auth, account_index=CFG["account_index"], market_id=ex.meta.market_id))
            else:
                r = ex._run(api.account_inactive_orders(authorization=auth, account_index=CFG["account_index"], limit=limit,
                                                        market_id=ex.meta.market_id))
            return {o.client_order_index: dict(status=o.status, type=o.type, initial=float(o.initial_base_amount or 0),
                                               remaining=float(o.remaining_base_amount or 0), filled=float(o.filled_base_amount or 0))
                    for o in (r.orders or [])}
        except Exception as e:
            log("orders_detail_failed", which=which, error=X.redact(f"{type(e).__name__}: {e}")[:150]); return None

    def sync_fill(self, c, pos, ev):
        """Record the size that actually filled (partial entry fills included) and check the exchange stops/TPs cover
        exactly that. Never changes orders: a mismatch is logged as an ALERT for a human."""
        ex = self.ex[c["symbol"]]; dist = abs(c["entry"] - c["stop"])
        c.setdefault("size_planned", c["size"])
        hist = self.orders_detail(ex, "inactive") or {}; act = self.orders_detail(ex, "active") or {}
        for g in c["groups"]:
            e = hist.get(g["ids"]["entry"]) or act.get(g["ids"]["entry"])
            if e: g["filled"] = e["filled"]; g["entry_status"] = e["status"]
        eq = c.get("equity_at_open") or self.equity()
        c.update(size=pos["size"], risk_usd=round(pos["size"] * dist, 4), risk_pct=round(pos["size"] * dist / eq * 100, 3),
                 notional=round(pos["size"] * c["entry"], 2))
        stops = sum(act[g["ids"]["stop"]]["remaining"] for g in c["groups"] if g["ids"]["stop"] in act)
        tps = sum(act[g["ids"]["tp"]]["remaining"] for g in c["groups"] if g["ids"]["tp"] in act)
        log(ev, id=c["id"], pos=pos, planned=c["size_planned"], filled=pos["size"], stop_cover=stops, tp_cover=tps,
            groups=[{k: g.get(k) for k in ("size", "filled", "entry_status")} for g in c["groups"]])
        if act and (abs(stops - pos["size"]) > 1e-9 or tps - pos["size"] > 1e-9):
            log("ALERT_cover_mismatch", id=c["id"], pos=pos["size"], stop_cover=stops, tp_cover=tps)

    def autopilot_state(self):
        try: return json.loads((HOME / "state.json").read_text())
        except Exception: return {}

    def open_risk(self):
        r = sum(c.get("risk_usd", 0) for c in self.st["calls"].values() if c["status"] not in TERMINAL)
        ot = self.autopilot_state().get("open_trade") or self.autopilot_state().get("armed_g")
        return r + (float(ot.get("risk_usd", 0)) if ot else 0)

    def ours(self, c, orders):
        ids = {v for g in c["groups"] for v in g["ids"].values()}
        return [o for o in (orders or []) if o.get("client_order_index") in ids]

    def cancel_ours(self, c):
        ex = self.ex[c["symbol"]]; res = []
        for o in self.ours(c, ex.active_orders()):
            res.append(ex.cancel_order(o["order_index"]))
        return res

    # ---------------------------------------------------------------- inbox
    def inbox(self):
        for f in sorted(INBOX.glob("*.json")):
            try:
                m = json.loads(f.read_text()); name = m.get("msg") or f.stem
            except Exception as e:
                log("bad_message", file=f.name, error=str(e)[:100]); f.rename(DONE / f.name); continue
            if name in self.st["seen"]:
                res = {"ok": True, "result": "duplicate (already processed)"}
            else:
                try:
                    res = self.handle(m)
                except Exception as e:
                    res = {"ok": False, "result": X.redact(f"{type(e).__name__}: {e}")[:300]}
                    log("handle_error", msg=name, tb=X.redact(traceback.format_exc()[-600:]))
                self.st["seen"].append(name); self.save()
            (ACK / f"{name}.json").write_text(json.dumps(dict(res, msg=name, acked=iso()), default=str))
            f.rename(DONE / f.name)
            log("message", msg=name, action=m.get("action"), id=m.get("id"), **res)

    def handle(self, m):
        a, cid = m["action"], m["id"]; c = self.st["calls"].get(cid)
        if a == "open":
            if c and c["status"] not in TERMINAL:
                return {"ok": True, "result": f"already active ({c['status']})"}
            return self.open(m)
        if a == "cancel":
            if not c: return {"ok": True, "result": "nothing to cancel (never placed)"}
            if c["status"] == "placed":
                r = self.cancel_ours(c); c["status"] = "cancelled"; self.save()
                return {"ok": all(x.get("ok") for x in r), "result": f"cancelled {len(r)} orders", "detail": r}
            if c["status"] in ("filled", "tp1") and m.get("close_if_filled"):
                return self.flatten(c, "call closed by tracker")
            if c["status"] in TERMINAL:
                return {"ok": True, "result": f"nothing resting: already {c['status']}"}
            return {"ok": True, "result": f"not cancelled: status {c['status']} (exchange stop/TP manage it)"}
        if a == "update":
            if not c: return self.open(m)
            if c["status"] == "placed":
                self.cancel_ours(c); c["status"] = "cancelled"; time.sleep(2)
                return self.open(m)
            if c["status"] in ("filled", "tp1") and m.get("stop") and float(m["stop"]) != c["stop_call"]:
                return self.move_stop(c, float(m["stop"]))
            return {"ok": True, "result": f"no change applied (status {c['status']})"}
        return {"ok": False, "result": f"unknown action {a}"}

    def open(self, m):
        s, cid = m["symbol"], m["id"]; side = 1 if m["side"] == "long" else -1
        rec = dict(id=cid, symbol=s, side=side, test=bool(m.get("test")), status="rejected", groups=[], msg=m)
        def reject(why):
            rec["why"] = why; self.st["calls"][cid] = rec; self.save()
            if not rec["test"]:
                log("ALERT_call_not_placed", id=cid, why=why)
            return {"ok": False, "result": "not placed: " + why}
        if s not in self.ex: return reject(f"unsupported symbol {s}")
        if (HOME / "STOP").exists(): return reject("STOP kill switch present")
        if self.st["paused"]: return reject("15% drawdown pause active")
        if self.st["halted"]: return reject("4% daily loss stop active")
        exp = datetime.fromisoformat(m["expiry"]).timestamp() if m.get("expiry") else now() + 7200
        if exp <= now(): return reject("call already expired")
        if any(c["symbol"] == s and c["status"] not in TERMINAL for c in self.st["calls"].values()):
            return reject(f"another call already active on {s}")
        ex = self.ex[s]; acc = ex.account()
        if acc["position"]: return reject(f"{s} position already open on the account (not ours to stack on)")
        if s == "BTC":
            ap = self.autopilot_state()
            if ap.get("open_trade") or ap.get("armed_g"):
                return reject("BTC autopilot holds a trade / resting entry; calls do not fight an open position")
        b = self.basis(s, m.get("okx_ref"), m.get("okx_ref_ts"))
        if b is None: return reject("OKX-Lighter basis too wide")
        M = ex.meta
        entry = M.px(float(m["entry"]) + b); stop = M.px(float(m["stop"]) + b)
        tp1 = M.px(float(m["tp1"]) + b); tp2 = M.px(float(m.get("tp2") or m["tp1"]) + b)
        if not ((side == 1 and stop < entry < tp1 <= tp2) or (side == -1 and tp2 <= tp1 < entry < stop)):
            return reject("levels inconsistent")
        mid = self.mid(s)
        if not rec["test"] and ((side == 1 and (mid <= stop or mid >= tp1)) or (side == -1 and (mid >= stop or mid <= tp1))):
            return reject(f"price {mid} already beyond stop or TP1: call invalid")
        eq = acc["equity"]; dist = abs(entry - stop)
        budget = min(CFG["risk"] * eq, CFG["max_total_risk"] * eq - self.open_risk())
        if budget <= 0: return reject("total open risk already at 4%")
        lev = min(CFG["lev_cap"][s], M.max_leverage)
        size = M.floor_size(min(budget / dist, lev * eq / entry))
        minsz = max(M.min_base, M.min_quote / entry)
        if size < minsz:
            return reject(f"size {size} below Lighter minimum {minsz:.6f} within 2% risk / {lev}x cap")
        h1 = M.floor_size(size / 2); h2 = M.floor_size(size - h1)
        legs = [(h1, tp1), (h2, tp2)] if (h1 >= minsz and h2 >= minsz and tp2 != tp1) else [(size, tp1)]
        if not LIVE:
            rec.update(status="practice", entry=entry, stop=stop, tp1=tp1, tp2=tp2, size=size, legs=legs)
            self.st["calls"][cid] = rec; self.save()
            return {"ok": True, "result": f"practice: would place {m['side']} {s} {size} @ {entry} SL {stop} TP {tp1}/{tp2} "
                    f"risk {size * dist / eq * 100:.2f}% (set CALLS_LIVE=1 to trade)"}
        lr = ex.set_leverage(lev, "cross")
        if not lr.get("ok"): log("leverage_set_failed", symbol=s, result=lr)
        sw = CFG["stop_worst_pct"] / 100
        worst = M.px(stop * (1 - sw) if side == 1 else stop * (1 + sw))
        for sz, tp in legs:
            r = ex.open_group(side, sz, "gtt", entry, stop, worst, tp)
            if not r.get("ok"):
                if rec["groups"]:
                    break
                return reject("order rejected by Lighter: " + str(r.get("error"))[:200])
            rec["groups"].append(dict(size=sz, tp=tp, ids=r["client_order_ids"], tx=r.get("tx_hash")))
            time.sleep(1.5)
        placed = sum(g["size"] for g in rec["groups"])
        rec.update(status="placed", entry=entry, stop=stop, stop_call=float(m["stop"]), tp1=tp1, tp2=tp2, basis=b,
                   size=placed, risk_usd=round(placed * dist, 4), risk_pct=round(placed * dist / eq * 100, 3),
                   notional=round(placed * entry, 2), expiry=exp, placed_ts=now(), equity_at_open=eq)
        self.st["calls"][cid] = rec; self.save()
        time.sleep(3)
        live = self.ours(rec, ex.active_orders())
        return {"ok": True, "result": f"placed {len(rec['groups'])} group(s) {m['side']} {s} {placed} @ {entry} SL {stop} "
                f"TP {tp1}/{tp2} risk {rec['risk_pct']}% ({rec['risk_usd']:.2f} USD), resting orders seen: {len(live)}",
                "resting_orders": live}

    def move_stop(self, c, new_stop_call):
        ex = self.ex[c["symbol"]]; M = ex.meta; pos = ex.account()["position"]
        if not pos: return {"ok": False, "result": "no position to move the stop on"}
        ns = M.px(new_stop_call + c.get("basis", 0)); sw = CFG["stop_worst_pct"] / 100
        r = ex.place_stop(pos, ns, M.px(ns * (1 - sw) if pos["side"] == 1 else ns * (1 + sw)))
        if not r.get("ok"): return {"ok": False, "result": "new stop rejected, old stop kept", "detail": r}
        for o in self.ours(c, ex.active_orders()):
            if o["kind"] == "stop": ex.cancel_order(o["order_index"])
        c.update(stop=ns, stop_call=new_stop_call); self.save()
        return {"ok": True, "result": f"stop moved to {ns}"}

    def flatten(self, c, why):
        ex = self.ex[c["symbol"]]; self.cancel_ours(c); pos = ex.account()["position"]
        r = ex.close_position(pos) if pos else {"ok": True}
        c["status"] = "closed"; c["close_reason"] = why; self.save()
        return {"ok": r.get("ok", False), "result": f"flattened ({why})", "detail": r}

    # ---------------------------------------------------------------- monitor
    def guards(self):
        eq = self.equity(); day = iso()[:10]; st = self.st
        if st["day"] != day: st.update(day=day, day_start=eq, halted=False)
        st["peak"] = max(st["peak"] or eq, eq)
        if not st["halted"] and eq <= st["day_start"] * (1 - CFG["daily_loss"]):
            st["halted"] = True; log("ALERT_daily_loss_stop", equity=eq)
        if not st["paused"] and eq <= st["peak"] * (1 - CFG["drawdown"]):
            st["paused"] = True; log("ALERT_drawdown_pause", equity=eq, peak=st["peak"])
        return eq

    def monitor(self):
        kill = (HOME / "STOP").exists()
        for cid, c in list(self.st["calls"].items()):
            if c["status"] in TERMINAL: continue
            ex = self.ex[c["symbol"]]; pos = ex.account()["position"]; orders = ex.active_orders()
            mine = self.ours(c, orders); sname = "long" if c["side"] == 1 else "short"; s = c["symbol"]
            tag = f"{s} {sname}"
            if kill:
                r = self.flatten(c, "STOP kill switch"); c["status"] = "killed"; log("killed", id=cid, result=r); continue
            if c["status"] == "placed":
                if pos and pos["side"] == c["side"]:
                    c.update(status="filled", fill_px=pos["entry"], fill_ts=now()); self.sync_fill(c, pos, "filled")
                    part = (f" (partial: {pos['size']} of {c['size_planned']} planned)"
                            if pos["size"] < c["size_planned"] - 1e-9 else "")
                    if not c["test"]:
                        tg(f"<b>FILLED</b> {tag} on Lighter @ {pos['entry']:,}\nSize {pos['size']}{part} · Stop {c['stop']:,} · "
                           f"TP1 {c['tp1']:,} · TP2 {c['tp2']:,}\nRisk {c['risk_pct']}% of equity, stop is on the exchange")
                    continue
                entries = [o for o in mine if o["kind"] == "entry"]
                mid = self.mid(s)
                tagged = not c["test"] and ((c["side"] == 1 and mid >= c["tp1"]) or (c["side"] == -1 and mid <= c["tp1"]))
                if now() > c["expiry"] or self.st["halted"] or self.st["paused"] or tagged:
                    why = "expired" if now() > c["expiry"] else "invalidated"
                    r = self.cancel_ours(c); c["status"] = why if why == "expired" else "invalidated"
                    log("entry_cancelled", id=cid, why=why, mid=mid, result=r)
                elif orders is not None and not entries and now() - c["placed_ts"] > 60 and not pos:
                    c["status"] = "vanished"; log("ALERT_entry_vanished", id=cid)
                continue
            # filled / tp1
            if not pos or pos["side"] != c["side"]:
                mid = self.mid(s); stop_hit = abs(mid - c["stop"]) < abs(mid - c["tp2"])
                why = "STOPPED" if stop_hit else ("TP2 HIT" if c["status"] == "tp1" or len(c["groups"]) == 1 else "CLOSED")
                eq = self.equity(); pnl = eq - c["equity_at_open"]
                self.cancel_ours(c); c.update(status="closed", close_reason=why, pnl_usd=round(pnl, 2), close_ts=now())
                log("closed", id=cid, why=why, pnl=pnl)
                if not c["test"]:
                    tg(f"<b>{why}</b> {tag} on Lighter\nPosition closed. Account P&amp;L since entry {pnl:+.2f} USD "
                       f"({pnl / c['risk_usd']:+.2f}R)" if c["risk_usd"] else f"<b>{why}</b> {tag}")
                continue
            # entry still filling after the first fill: track the real size (never assume the planned size)
            if c["status"] == "filled" and pos["size"] > c["size"] + 1e-9:
                self.sync_fill(c, pos, "fill_grew")
            # TP1 only when the TP1 reduce-only order itself shows as filled in the order history.
            # A smaller-than-planned position (partial entry fill) is NOT a TP1 hit.
            if c["status"] == "filled" and len(c["groups"]) == 2 and pos["size"] < c["size"] - 1e-9:
                hist = self.orders_detail(ex, "inactive")
                t1 = (hist or {}).get(c["groups"][0]["ids"]["tp"])
                if t1 and t1["status"] == "filled" and t1["filled"] > 0:
                    c.update(status="tp1", tp1_filled=t1["filled"], tp1_ts=now()); log("tp1_hit", id=cid, pos=pos, tp1_order=t1)
                    c["size"] = pos["size"]
                    if not c["test"]:
                        tg(f"<b>TP1 HIT</b> {tag} on Lighter @ {c['tp1']:,}\nClosed {t1['filled']}, runner {pos['size']} held to "
                           f"TP2 {c['tp2']:,}, stop stays {c['stop']:,} (no break-even move)")
                elif hist is not None and c.get("reduced_seen") != pos["size"]:
                    c["reduced_seen"] = pos["size"]
                    log("ALERT_position_reduced_not_tp1", id=cid, pos=pos, recorded=c["size"], tp1_order=t1)
            # one position per market and it is ours: any reduce-only stop on the market protects it
            if orders is not None and not any(o["kind"] == "stop" for o in orders) and now() - c.get("fill_ts", 0) > 30:
                sw = CFG["stop_worst_pct"] / 100; M = ex.meta
                r = ex.place_stop(pos, c["stop"], M.px(c["stop"] * (1 - sw) if c["side"] == 1 else c["stop"] * (1 + sw)))
                log("ALERT_stop_missing_replaced", id=cid, result=r)
                if not r.get("ok"):
                    log("ALERT_stop_failed_flattening", id=cid, result=self.flatten(c, "stop could not be placed"))
        self.save()

    def run(self):
        log("start", mode="LIVE" if LIVE else "PRACTICE", equity=self.equity(), active=[k for k, c in self.st["calls"].items() if c["status"] not in TERMINAL])
        while True:
            try:
                self.guards(); self.inbox(); self.monitor()
                (CD / "heartbeat").write_text(iso())
            except Exception as e:
                log("loop_error", error=X.redact(f"{type(e).__name__}: {e}")[:300], tb=X.redact(traceback.format_exc()[-600:]))
                time.sleep(15)
            time.sleep(CFG["poll_s"])


if __name__ == "__main__":
    Exec().run()
