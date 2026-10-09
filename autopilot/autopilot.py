#!/usr/bin/env python3
"""Degen Desk BTC autopilot for Lighter perps (multi-timeframe SMC rules: setups A + G + RIMC, backtested on BTC).

  autopilot.py run [--live | --dry-run]      the loop (launchd runs this through run.sh); dry-run is the default
  autopilot.py status                         equity, position, today's PnL, guardrails, last signals
  autopilot.py stop                           kill switch: cancel orders, close the BTC position, exit (stays stopped)
  autopilot.py pause | resume                 no new entries (open trade keeps its stop/TP) | clear pause + drawdown pause
  autopilot.py start                          remove the STOP file and (re)start the launchd job

Every entry goes out as ONE grouped order: entry + reduce-only stop-loss + reduce-only take-profit (3R for A/RIMC,
5R for G, or the structural target if closer), so the stop exists on Lighter the moment the entry fills.
Guardrails (config.json): 1% risk of live equity per trade by default (hard ceiling 2%), 3x leverage cap (size shrinks), one position,
-4% UTC-day loss stop, -15% drawdown-from-peak pause (manual resume), 24h max hold, STOP file kill switch.
"""
from __future__ import annotations
import argparse, csv, fcntl, json, math, os, subprocess, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
HOME = Path(os.environ.get("AUTOPILOT_HOME", os.path.expanduser("~/.degen-desk/autopilot")))
M1 = 60_000
DEFAULTS = json.loads((HERE / "config.default.json").read_text())


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def load_config(home=HOME):
    cfg = dict(DEFAULTS)
    p = home / "config.json"
    if p.exists():
        cfg.update(json.loads(p.read_text()))
    # hard ceiling: config can lower risk, never raise it above the 2% hard ceiling
    cfg["risk_per_trade"] = min(float(cfg["risk_per_trade"]), float(DEFAULTS["max_risk_per_trade_hard_cap"]))
    cfg["max_open_positions"] = 1
    return cfg


class Autopilot:
    def __init__(self, cfg, exchange, mode, home=HOME, store=None, signal_fn=None, notifier=None, clock=time.time):
        self.cfg, self.ex, self.mode, self.home = cfg, exchange, mode, Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.store, self.signal_fn, self.notify, self.clock = store, signal_fn, notifier, clock
        self.paths = {k: self.home / v for k, v in dict(state="state.json", status="status.json", log="log.jsonl",
                                                          trades="trades.csv", stop="STOP", pause="PAUSE").items()}
        self.st = self._load_state()
        self.last_eval = None

    # ------------------------------------------------------------------ persistence
    def _load_state(self):
        p = self.paths["state"]
        base = dict(peak_equity=None, paused=False, pause_reason=None, day=None, day_start_equity=None, day_halted=False,
                    open_trade=None, armed_g=None, acted=[], last_signals=[], last_bar_ts=None, reset_peak=False)
        if p.exists():
            try:
                base.update(json.loads(p.read_text()))
            except Exception:
                pass
        return base

    def save(self):
        self.st["acted"] = self.st["acted"][-300:]
        self.st["last_signals"] = self.st["last_signals"][-25:]
        tmp = self.paths["state"].with_suffix(".tmp")
        tmp.write_text(json.dumps(self.st, indent=1, default=str)); tmp.replace(self.paths["state"])

    def log(self, event, **kw):
        rec = {"ts": utc(self.now_ms()), "mode": self.mode, "event": event, **kw}
        with open(self.paths["log"], "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    def trade_row(self, **kw):
        cols = ["time_utc", "mode", "event", "setup", "side", "size", "entry", "stop", "tp", "exit", "reason", "pnl_usd", "R",
                "equity", "risk_usd", "key"]
        new = not self.paths["trades"].exists()
        with open(self.paths["trades"], "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({"time_utc": utc(self.now_ms()), "mode": self.mode, **kw})

    def say(self, text):
        if self.notify:
            try:
                self.notify(text)
            except Exception as e:
                self.log("notify_failed", error=str(e)[:120])

    def now_ms(self):
        return int(self.clock() * 1000)

    # ------------------------------------------------------------------ kill switch
    def kill(self, why="STOP file"):
        """Close the BTC position first (reduce-only market), and only once flat cancel the remaining orders, so a
        failed close never leaves the position without its exchange stop. Not flat after 3 tries -> keep the stop/TP,
        exit non-zero (launchd restarts and the STOP file makes it retry)."""
        self.log("kill_switch", why=why)
        res = {"close": [], "cancel": None}
        flat = False
        for attempt in range(3):
            acc = self.ex.account()
            if not acc["position"]:
                flat = True; break
            res["close"].append(self.ex.close_position(acc["position"], immediate=True))
            time.sleep(3 if self.ex.live else 0)
        else:
            flat = not self.ex.account()["position"]
        if flat:
            res["cancel"] = self.ex.cancel_all()
            if self.st.get("open_trade"):
                self._record_close(self.ex.account()["equity"], "kill_switch")
            self.st["armed_g"] = None
        self.log("killed" if flat else "kill_incomplete", flat=flat, detail=res)
        self.say(f"Autopilot STOPPED ({why}). " + ("Position closed, orders cancelled." if flat else
                 "Position could NOT be closed - its stop/TP were left in place; retrying after restart. Check Lighter."))
        self.save(); self.write_status({"state": "stopped" if flat else "stopping", "flat": flat})
        return flat

    # ------------------------------------------------------------------ main step
    def tick(self):
        now = self.now_ms()
        if self.paths["stop"].exists():
            return "stopped" if self.kill("STOP file") else "kill_incomplete"
        acc = self._acc = self.ex.account()
        eq, pos = acc["equity"], acc["position"]
        self._guards(now, eq, pos)
        self._reconcile(now, acc)
        new_bar = False
        if self.store is not None:
            try:
                self.store.update(now)
            except Exception as e:
                self.log("feed_error", error=str(e)[:200])
            lt = self.store.last_ts()
            if lt is not None and lt != self.st["last_bar_ts"]:
                self.st["last_bar_ts"] = lt; new_bar = True
        if new_bar:
            self._acc = self.ex.account() if self.ex.live else self._acc
            self._on_bar(now, self._acc)
        self.save(); self.write_status()
        return "ok"

    def _guards(self, now, eq, pos):
        cfg, st = self.cfg, self.st
        day = utc(now)[:10]
        if st["day"] != day:
            st.update(day=day, day_start_equity=eq, day_halted=False)
            self.log("new_utc_day", equity=eq)
        if st["peak_equity"] is None or st.get("reset_peak"):
            st["peak_equity"] = eq; st["reset_peak"] = False
        st["peak_equity"] = max(st["peak_equity"], eq)
        if not st["day_halted"] and eq <= st["day_start_equity"] * (1 - cfg["daily_loss_stop"]):
            st["day_halted"] = True
            self.log("daily_loss_stop", equity=eq, day_start=st["day_start_equity"])
            self.say(f"Daily loss stop hit ({eq / st['day_start_equity'] - 1:.1%} today). No new trades until 00:00 UTC.")
        if not st["paused"] and eq <= st["peak_equity"] * (1 - cfg["drawdown_pause"]):
            st.update(paused=True, pause_reason=f"drawdown {eq / st['peak_equity'] - 1:.1%} from peak {st['peak_equity']:.2f}")
            self.log("drawdown_pause", equity=eq, peak=st["peak_equity"])
            self.say(f"Autopilot PAUSED: {st['pause_reason']}. Open trade keeps its stop/TP. Resume with: autopilot.py resume")
        if self.paths["pause"].exists() and not st["paused"]:
            st.update(paused=True, pause_reason="manual pause")
            self.log("manual_pause")

    def can_open(self, now):
        st = self.st
        why = []
        if st["paused"]: why.append("paused: " + str(st["pause_reason"]))
        if st["day_halted"]: why.append("daily loss stop")
        if st["open_trade"]: why.append("position open")
        lt = self.store.last_ts() if self.store else None
        if self.store is not None and (lt is None or now - (lt + M1) > self.cfg["max_data_lag_s"] * 1000):
            why.append("candle data stale")
        return why

    # ------------------------------------------------------------------ reconcile with the exchange
    def _reconcile(self, now, acc):
        st, pos = self.st, acc["position"]
        ot, ag = st["open_trade"], st["armed_g"]
        if ag and pos and not ot:                       # resting G limit filled
            st["open_trade"] = ot = dict(ag, ts_open=pos.get("ts", now), entry=pos["entry"], size=pos["size"], filled_from="G limit")
            st["armed_g"] = None
            self.log("entry_filled", setup="G", entry=pos["entry"], size=pos["size"], stop=ot["stop"], tp=ot["tp"])
            self.trade_row(event="open", setup="G", side=ot["side"], size=pos["size"], entry=pos["entry"], stop=ot["stop"],
                           tp=ot["tp"], equity=acc["equity"], risk_usd=round(ot["risk_usd"], 2), key=ot["key"])
            self.say(f"OPEN G {'long' if ot['side'] == 1 else 'short'} BTC {pos['size']} @ {pos['entry']} | SL {ot['stop']} TP {ot['tp']}")
        if ag and not pos and not ot:
            orders = self.ex.active_orders()
            if orders is not None and not any(o["kind"] == "entry" for o in orders) and now - ag["ts_armed"] > 20_000:
                if abs(acc["equity"] - ag["equity_at_open"]) > 1e-6 * max(1.0, acc["equity"]):
                    # the limit filled and the stop/TP closed it between two loops
                    st["open_trade"] = dict(ag, ts_open=now, entry=ag["lim"], filled_from="G limit (filled+closed between loops)")
                    st["armed_g"] = None
                    self.trade_row(event="open", setup="G", side=ag["side"], size=ag["size"], entry=ag["lim"], stop=ag["stop"],
                                   tp=ag["tp"], equity=ag["equity_at_open"], risk_usd=round(ag["risk_usd"], 2), key=ag["key"])
                    self._record_close(acc["equity"], None)
                else:
                    st["armed_g"] = None; st["acted"].append(ag["key"])
                    self.log("g_limit_vanished", key=ag["key"], note="entry order no longer resting and no fill (expired or cancelled outside the bot)")
                return
        if ot and not pos:
            if now - ot.get("ts_open", now) < 20_000 and self.ex.live:
                return                                   # give the fill a moment to show up
            self._record_close(acc["equity"], None)
            if self.ex.live:
                self.ex.cancel_all()                     # sweep any leftover reduce-only child
            return
        if pos and not ot:
            if ag:
                return
            self.log("orphan_position", position=pos, policy=self.cfg["orphan_policy"])
            if self.cfg["orphan_policy"] == "protect" and self.ex.live:
                orders = self.ex.active_orders()
                if orders is not None and not any(o["kind"] == "stop" for o in orders):
                    k = self.cfg["orphan_stop_pct"] / 100
                    trig = pos["entry"] * (1 - k) if pos["side"] == 1 else pos["entry"] * (1 + k)
                    worst = trig * (1 - 0.005) if pos["side"] == 1 else trig * (1 + 0.005)
                    r = self.ex.place_stop(pos, self.ex.meta.px(trig), self.ex.meta.px(worst))
                    self.log("orphan_stop_placed", trigger=trig, result=r)
            return
        if ot and pos:
            if pos["side"] != ot["side"]:
                self.log("position_side_mismatch", position=pos, trade=ot)
                return
            ot["size_now"] = pos["size"]
            if not ot.get("fill_confirmed"):
                ot.update(entry=pos["entry"], size=pos["size"], fill_confirmed=True)
            # exchange-side stop must exist (grace period after entry)
            if self.ex.live and now - ot.get("ts_open", now) > 30_000 and now - ot.get("stop_checked", 0) > 60_000:
                ot["stop_checked"] = now
                self._protect(ot, pos)
            # time exit (backtest: 24h max hold)
            if now >= ot["ts_open"] + (self.cfg["max_hold_minutes"] + 1) * M1 and not ot.get("time_exit_sent"):
                ot["time_exit_sent"] = now
                r = self.ex.close_position(pos)
                self.log("time_exit", result=r)
                self.ex.cancel_all() if self.ex.live else None

    def _protect(self, ot, pos):
        """Exchange-side stop (and TP) must exist for the open trade; re-place what is missing; if the stop
        cannot be placed, close the position (never leave it unprotected)."""
        orders = self.ex.active_orders()
        if orders is None:
            return
        if not any(o["kind"] == "stop" for o in orders):
            sw = self.cfg["stop_worst_fill_pct"] / 100
            worst = ot["stop"] * (1 - sw) if ot["side"] == 1 else ot["stop"] * (1 + sw)
            r = self.ex.place_stop(pos, ot["stop"], self.ex.meta.px(worst))
            self.log("stop_missing_replaced", result=r)
            if not r.get("ok"):
                self.log("stop_replace_failed_closing", result=r)
                self.ex.close_position(pos)
                return
        if ot.get("tp") and not any(o["kind"] == "tp" for o in orders):
            r = self.ex.place_tp(pos, ot["tp"])
            self.log("tp_missing_replaced", result=r)

    def _record_close(self, equity, reason):
        ot = self.st["open_trade"]
        pnl = equity - ot["equity_at_open"]
        R = pnl / ot["risk_usd"] if ot.get("risk_usd") else None
        if reason is None:
            reason = "time" if ot.get("time_exit_sent") else ("tp" if pnl > 0 else "sl")
        self.log("trade_closed", setup=ot["setup"], pnl_usd=round(pnl, 4), R=R and round(R, 3), reason=reason, equity=equity)
        self.trade_row(event="close", setup=ot["setup"], side=ot["side"], size=ot.get("size"), entry=ot.get("entry"),
                       stop=ot["stop"], tp=ot["tp"], reason=reason, pnl_usd=round(pnl, 4), R=R and round(R, 3), equity=equity,
                       key=ot["key"])
        self.say(f"CLOSED {ot['setup']} {'long' if ot['side'] == 1 else 'short'} BTC: {pnl:+.2f} USD ({R:+.2f}R, {reason}). Equity {equity:.2f}")
        self.st.setdefault("closed", []).append(dict(key=ot["key"], setup=ot["setup"], side=ot["side"], pnl=pnl, R=R, reason=reason,
                                                     ts_open=ot["ts_open"], ts_close=self.now_ms(), entry=ot.get("entry")))
        self.st["closed"] = self.st["closed"][-200:]
        self.st["open_trade"] = None

    # ------------------------------------------------------------------ signals
    def _on_bar(self, now, acc):
        try:
            ev = self.signal_fn(self.store)
        except Exception as e:
            self.log("engine_error", error=f"{type(e).__name__}: {e}"[:300], tb=traceback.format_exc()[-600:])
            return
        self.last_eval = ev
        enabled = set(self.cfg["setups_enabled"])
        mkts = [s for s in ev["market"] if s["setup"] in enabled and s["key"] not in self.st["acted"]]
        gs = [g for g in ev["g"] if "G" in enabled]
        for s in mkts:
            self.st["last_signals"].append(dict(ts=utc(s["ts_sig"]), setup=s["setup"], side=s["side"], stop=s["stop"], final=s["final"]))
        blocked = self.can_open(now)
        # an armed G limit that is no longer valid (or we cannot trade) gets cancelled
        ag = self.st["armed_g"]
        if ag:
            cur = next((g for g in gs if g["key"] == ag["key"]), None)
            if blocked or mkts or cur is None or cur["state"] != "armed":
                why = blocked or (["market signal takes priority"] if mkts else ["G setup no longer armed: " + (cur["state"] if cur else "gone")])
                r = self.ex.cancel_all()
                acc2 = self.ex.account()
                if acc2["position"]:          # filled in the meantime: cancel_all also removed its stop/TP -> re-protect now
                    p = acc2["position"]
                    self.st["open_trade"] = dict(ag, ts_open=now, entry=p["entry"], size=p["size"], filled_from="G limit (raced)")
                    self.st["armed_g"] = None
                    self.log("g_cancel_raced_fill", result=r)
                    self._protect(self.st["open_trade"], p)
                    return
                self.st["armed_g"] = None
                self.log("g_limit_cancelled", key=ag["key"], why=why, result=r)
        if blocked:
            for s in mkts:
                self.st["acted"].append(s["key"])
                self.log("signal_skipped", setup=s["setup"], key=s["key"], why=blocked)
            return
        if mkts:
            s = mkts[0]
            self.st["acted"].append(s["key"])
            for o in mkts[1:]:
                self.st["acted"].append(o["key"]); self.log("signal_skipped", key=o["key"], why=["one position at a time"])
            self._enter_market(now, s, acc)
            return
        if self.st["armed_g"] is None:
            armed = [g for g in gs if g["state"] == "armed" and g["key"] not in self.st["acted"]]
            if armed:
                last = ev["last_close"]
                g = min(armed, key=lambda x: abs(x["lim"] - last))
                self._arm_g(now, g, acc)

    def _basis(self):
        if not (self.ex.live and self.cfg["basis_adjust"]):
            return 0.0
        try:
            bid, ask = self.ex.book(); ref = self.store.feed.last_price()
            b = (bid + ask) / 2 - ref
            if abs(b) / ref > self.cfg["max_basis_pct"] / 100:
                raise RuntimeError(f"basis {b:.1f} too large")
            return b
        except Exception as e:
            self.log("basis_error", error=str(e)[:160])
            return None

    def _size(self, equity, entry, dist):
        cfg, M = self.cfg, self.ex.meta
        risk_usd = cfg["risk_per_trade"] * equity
        lpu = dist + entry * cfg["size_buffer_bps"] * 1e-4
        size_risk = risk_usd / lpu
        size_lev = cfg["leverage_cap"] * equity / entry
        size = M.floor_size(min(size_risk, size_lev))
        if size < M.min_base or size * entry < M.min_quote:
            return None, dict(reason="below Lighter minimum", size=size, min_base=M.min_base, min_quote=M.min_quote)
        return size, dict(risk_usd=size * lpu, risk_pct=size * lpu / equity, notional=size * entry, lev=size * entry / equity,
                          lev_capped=size_lev < size_risk)

    def _enter_market(self, now, s, acc):
        import strategy as ST
        M = self.ex.meta
        bid, ask = self.ex.book()
        ref = ask if s["side"] == 1 else bid
        basis = self._basis()
        if basis is None:
            self.log("signal_skipped", key=s["key"], why=["basis check failed"]); return
        sig = dict(s, stop=s["stop"] + basis, final=s["final"] + basis)
        plan = ST.plan_trade(sig, ref)
        if "reject" in plan:
            self.log("signal_rejected", key=s["key"], setup=s["setup"], why=plan["reject"], ref=ref); return
        size, info = self._size(acc["equity"], ref, plan["dist"])
        if size is None:
            self.log("signal_rejected", key=s["key"], why=info); return
        side = s["side"]; slip = self.cfg["entry_max_slippage_bps"] * 1e-4
        worst = M.px(ref * (1 + slip), "up") if side == 1 else M.px(ref * (1 - slip), "down")
        stop = M.px(plan["stop"]); tp = M.px(plan["tp"])
        sw = self.cfg["stop_worst_fill_pct"] / 100
        stop_worst = M.px(stop * (1 - sw), "down") if side == 1 else M.px(stop * (1 + sw), "up")
        order = dict(setup=s["setup"], side=side, size=size, entry_type="market (IOC limit)", worst=worst, ref=ref, stop=stop,
                     stop_worst=stop_worst, tp=tp, basis=round(basis, 2), stop_pct=round(plan["stop_pct"] * 100, 3),
                     rr_struct=round(plan["rr_struct"], 2), **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in info.items()})
        if self.ex.live:
            lr = self.ex.set_leverage(self.cfg["leverage_cap"], self.cfg["margin_mode"])
            if not lr.get("ok"):
                self.log("entry_aborted", key=s["key"], why="leverage update failed", result=lr); return
        r = self.ex.open_group(side, size, "ioc", worst, stop, stop_worst, tp)
        self.log("entry_sent", key=s["key"], order=order, result=r)
        if not r.get("ok"):
            self.say(f"Entry NOT placed ({s['setup']}): {str(r.get('error'))[:120]}")
            if "20558" in str(r.get("error")) or "restricted" in str(r.get("error")).lower():
                self.st.update(paused=True, pause_reason="Lighter geo-block (20558) - wrong location, never reroute")
            return
        self.st["open_trade"] = dict(key=s["key"], setup=s["setup"], side=side, stop=stop, tp=tp, entry=ref, size=size,
                                     ts_open=now, equity_at_open=acc["equity"], risk_usd=info["risk_usd"], ts_sig=s["ts_sig"])
        if self.ex.live:
            time.sleep(3)
            p = self.ex.account()["position"]
            if not p:
                self.log("entry_not_filled", key=s["key"]); self.ex.cancel_all(); self.st["open_trade"] = None; return
            self.st["open_trade"].update(entry=p["entry"], size=p["size"])
        self.trade_row(event="open", setup=s["setup"], side=side, size=size, entry=self.st["open_trade"]["entry"], stop=stop, tp=tp,
                       equity=acc["equity"], risk_usd=round(info["risk_usd"], 2), key=s["key"])
        self.say(f"OPEN {s['setup']} {'long' if side == 1 else 'short'} BTC {size} @ ~{ref} | SL {stop} TP {tp} | risk ${info['risk_usd']:.2f} ({info['risk_pct']:.2%})")

    def _arm_g(self, now, g, acc):
        import strategy as ST
        M = self.ex.meta
        basis = self._basis()
        if basis is None:
            return
        lim = g["lim"] + basis
        sig = dict(g, stop=g["stop"] + basis, final=g["final"] + basis)
        plan = ST.plan_trade(sig, lim)
        if "reject" in plan:
            self.st["acted"].append(g["key"])
            self.log("g_rejected", key=g["key"], why=plan["reject"]); return
        size, info = self._size(acc["equity"], lim, plan["dist"])
        if size is None:
            self.st["acted"].append(g["key"]); self.log("g_rejected", key=g["key"], why=info); return
        side = g["side"]
        lim_p = M.px(lim, "down") if side == 1 else M.px(lim, "up")
        stop = M.px(plan["stop"]); tp = M.px(plan["tp"])
        sw = self.cfg["stop_worst_fill_pct"] / 100
        stop_worst = M.px(stop * (1 - sw), "down") if side == 1 else M.px(stop * (1 + sw), "up")
        if self.ex.live:
            lr = self.ex.set_leverage(self.cfg["leverage_cap"], self.cfg["margin_mode"])
            if not lr.get("ok"):
                self.log("g_aborted", key=g["key"], result=lr); return
        r = self.ex.open_group(side, size, "gtt", lim_p, stop, stop_worst, tp)
        self.log("g_limit_placed", key=g["key"], lim=lim_p, stop=stop, tp=tp, size=size, exp=utc(g["exp_ts"]), info=info, result=r)
        if not r.get("ok"):
            self.st["acted"].append(g["key"]); return
        self.st["armed_g"] = dict(key=g["key"], setup="G", side=side, stop=stop, tp=tp, lim=lim_p, size=size, ts_sig=g["ts_sig"],
                                  exp_ts=g["exp_ts"], equity_at_open=acc["equity"], risk_usd=info["risk_usd"], ts_armed=now)
        self.say(f"G limit {'buy' if side == 1 else 'sell'} BTC {size} @ {lim_p} | SL {stop} TP {tp} (expires {utc(g['exp_ts'])} UTC)")

    # ------------------------------------------------------------------ status
    def write_status(self, extra=None):
        acc = getattr(self, "_acc", None)
        st = self.st
        d = dict(updated_utc=utc(self.now_ms()), mode=self.mode, pid=os.getpid(),
                 equity=acc and round(acc["equity"], 4), position=acc and acc["position"],
                 day=st["day"], day_start_equity=st["day_start_equity"],
                 day_pnl=(acc and st["day_start_equity"]) and round(acc["equity"] - st["day_start_equity"], 4),
                 day_halted=st["day_halted"], paused=st["paused"], pause_reason=st["pause_reason"], peak_equity=st["peak_equity"],
                 open_trade=st["open_trade"], armed_g=st["armed_g"], last_bar_utc=st["last_bar_ts"] and utc(st["last_bar_ts"]),
                 feed=getattr(getattr(self.store, "feed", None), "name", None), last_signals=st["last_signals"][-10:],
                 g_candidates=[{k: g[k] for k in ("key", "state", "lim", "stop")} for g in (self.last_eval or {}).get("g", [])][-5:],
                 config={k: self.cfg[k] for k in ("risk_per_trade", "leverage_cap", "daily_loss_stop", "drawdown_pause", "setups_enabled")})
        if extra:
            d.update(extra)
        tmp = self.paths["status"].with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, default=str)); tmp.replace(self.paths["status"])


# ====================================================================== wiring / CLI
def make_signal_fn():
    import strategy as ST
    def fn(store):
        w, pre = store.window()
        return ST.evaluate(w, pre)
    return fn


def make_notifier(cfg):
    t = cfg.get("telegram") or {}
    if not t.get("enabled") or not t.get("chat_id"):
        return None
    import notify
    return notify.Telegram(t["chat_id"], t.get("thread_id"))


def cmd_run(a):
    try:
        return _run(a)
    except Exception as e:
        import exchange as X
        HOME.mkdir(parents=True, exist_ok=True)
        with open(HOME / "log.jsonl", "a") as f:
            f.write(json.dumps({"ts": utc(time.time() * 1000), "event": "fatal", "error": X.redact(f"{type(e).__name__}: {e}")[:400]}) + "\n")
        print(json.dumps({"error": "autopilot failed to start", "detail": X.redact(f"{type(e).__name__}: {e}")[:300]}))
        return 2


def _run(a):
    cfg = load_config()
    if sys.platform == "darwin" and os.path.exists("/usr/bin/caffeinate"):
        # keep the Mac from idle/system sleep while (and only while) this process lives
        subprocess.Popen(["/usr/bin/caffeinate", "-i", "-s", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    HOME.mkdir(parents=True, exist_ok=True); os.chmod(HOME, 0o700)
    lock = open(HOME / "autopilot.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another autopilot is already running"); return 1
    import exchange as X, feed as F, strategy as ST
    live = bool(a.live)
    mode = "live" if live else "dry-run"
    acct = os.environ.get("LIGHTER_ACCOUNT_INDEX") or cfg.get("account_index")
    kidx = os.environ.get("LIGHTER_API_KEY_INDEX") or cfg.get("api_key_index")
    if acct in (None, "") or kidx in (None, ""):
        print(json.dumps({"error": "Lighter account index / API key slot not set: run lighter/install-local.sh "
                          "--account <INDEX> --slot <SLOT> first (or set them in config.json); not trading"}))
        return 0      # clean exit: launchd does not restart-loop
    acct, kidx = int(acct), int(kidx)
    lx = X.LighterExchange(acct, kidx, allow_send=live)
    if live:
        lx.keycheck()
        ex = lx
    else:
        os.environ.pop("LIGHTER_API_PRIVATE_KEY", None)
        eq0 = cfg["paper_equity"] or lx.account()["equity"] or 1000.0
        ex = X.PaperExchange(eq0, meta=lx.meta)
    feed, errs = F.pick_feed(cfg["data_source"])
    if feed is None:
        print(json.dumps({"error": "no candle source reachable", "detail": errs})); return 3
    store = F.CandleStore(feed, ST.HTF_ANCHOR_MS, keep_days=cfg["window_days"] + 10, window_days=cfg["window_days"],
                          cache_path=HOME / f"candles_{feed.name}.npz")
    now = int(time.time() * 1000)
    store.bootstrap(now)
    w0, pre0 = store.window()            # fail fast if the 4h history or the 1m window is incomplete
    if pre0 is None or len(w0["ts"]) < 3 * 1440:
        raise RuntimeError("candle bootstrap incomplete")
    store.save()
    if not live:
        # paper: feed it the closed bars from now on
        ex.last = store.m1[store.last_ts()][3]
    ap = Autopilot(cfg, ex, mode, store=store, signal_fn=make_signal_fn(), notifier=make_notifier(cfg))
    acc = ex.account()
    ap.log("start", account=acct, api_key_index=kidx, equity=acc["equity"], position=acc["position"], feed=feed.name,
           feed_errors=errs, open_trade=ap.st["open_trade"], armed_g=ap.st["armed_g"], config=cfg)
    if live and acc.get("other_positions"):
        ap.log("warning_other_positions", symbols=acc["other_positions"])
    if ap.paths["stop"].exists():
        return 0 if ap.kill("STOP file present at start") else 4
    # restart reconciliation: a stale armed G with no resting order is forgotten (re-evaluated next bar)
    if live and ap.st["armed_g"]:
        o = ex.active_orders()
        if o is not None and not any(x["kind"] == "entry" for x in o) and not acc["position"]:
            ap.log("armed_g_forgotten_on_restart", key=ap.st["armed_g"]["key"]); ap.st["armed_g"] = None
    ap.say(f"Autopilot started ({mode}). Equity {acc['equity']:.2f}. Risk {cfg['risk_per_trade']:.0%}/trade, lev cap {cfg['leverage_cap']}x.")
    last_save = 0; last_paper_bar = store.last_ts()
    while True:
        try:
            if not live:
                store.update(int(time.time() * 1000))
                for t in range(last_paper_bar + M1, store.last_ts() + M1, M1):
                    o, h, l, c, v = store.m1[t]; ex.on_bar(t, o, h, l, c)
                last_paper_bar = store.last_ts()
            r = ap.tick()
            if r == "stopped":
                return 0
            if r == "kill_incomplete":
                return 4          # non-zero: launchd restarts us and the STOP file retries the close
            if time.time() - last_save > 600:
                store.save(); last_save = time.time()
        except KeyboardInterrupt:
            ap.log("interrupted"); return 0
        except Exception as e:
            ap.log("loop_error", error=X.redact(f"{type(e).__name__}: {e}")[:300], tb=X.redact(traceback.format_exc()[-800:]))
            time.sleep(20)
        time.sleep(cfg["poll_seconds"])


def cmd_status(a):
    s = HOME / "status.json"
    if not s.exists():
        print(json.dumps({"status": "not running yet (no status.json)", "home": str(HOME)})); return 0
    d = json.loads(s.read_text())
    age = time.time() - datetime.strptime(d["updated_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    d["status_age_s"] = round(age)
    d["daemon_alive"] = age < 120 and d.get("state") != "stopped"
    d["stop_file"] = (HOME / "STOP").exists()
    tr = HOME / "trades.csv"
    if tr.exists():
        rows = list(csv.DictReader(open(tr)))
        d["recent_trades"] = rows[-6:]
        closed = [r for r in rows if r["event"] == "close"]
        d["closed_trades"] = len(closed)
        d["total_pnl_usd"] = round(sum(float(r["pnl_usd"] or 0) for r in closed), 2)
    print(json.dumps(d, indent=1, default=str)); return 0


def cmd_stop(a):
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "STOP").write_text(utc(time.time() * 1000) + " stop requested\n")
    print("STOP file written; the autopilot cancels orders, closes the BTC position and exits within ~15s.")
    for _ in range(18):
        time.sleep(5)
        s = HOME / "status.json"
        if s.exists() and json.loads(s.read_text()).get("state") == "stopped":
            print(json.dumps({"stopped": True, "flat": json.loads(s.read_text()).get("flat")})); return 0
    print(json.dumps({"stopped": "not confirmed yet - is the daemon running? check: autopilot.py status"})); return 1


def cmd_pause(a):
    (HOME / "PAUSE").write_text("manual pause\n"); print("paused: no new entries; any open trade keeps its stop and TP"); return 0


def cmd_resume(a):
    (HOME / "PAUSE").unlink(missing_ok=True)
    p = HOME / "state.json"
    if p.exists():
        st = json.loads(p.read_text()); st.update(paused=False, pause_reason=None, reset_peak=True)
        p.write_text(json.dumps(st, indent=1))
    print("resumed: pause cleared and drawdown peak reset to current equity (takes effect on the next loop)"); return 0


def cmd_start(a):
    (HOME / "STOP").unlink(missing_ok=True)
    uid = os.getuid()
    r = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.degendesk.autopilot"], capture_output=True, text=True)
    print(r.stdout or r.stderr or "kickstarted"); return r.returncode


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    r = s.add_parser("run"); g = r.add_mutually_exclusive_group(); g.add_argument("--live", action="store_true"); g.add_argument("--dry-run", action="store_true")
    for n in ("status", "stop", "pause", "resume", "start"):
        s.add_parser(n)
    a = p.parse_args()
    return {"run": cmd_run, "status": cmd_status, "stop": cmd_stop, "pause": cmd_pause, "resume": cmd_resume, "start": cmd_start}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main() or 0)
