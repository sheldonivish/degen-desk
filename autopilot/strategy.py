"""Live wrapper around the UNCHANGED backtest engine (course_engine/engine.py, setups.py, sim.py).

evaluate(d1) takes contiguous CLOSED 1m bars (ts[0] aligned to a 4h boundary, UTC) and answers, for
"now" = the open of the next 1m bar (ts[-1] + 60s):
  * market signals (Models A and RIMC) whose decision time is exactly now (entry at this bar's open,
    exactly as the backtest fills at o[t]);
  * Model G (golden zone / false first break) limit candidates still alive, with their state:
    waiting (no FFB yet), armed (FFB happened, limit should rest), dead/expired/done.
Nothing here looks at an unclosed bar. Parameters are the BTC configs selected in the backtest.
"""
from __future__ import annotations
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "course_engine"))
import engine as E          # noqa: E402
import setups as S          # noqa: E402
import sim as Z             # noqa: E402

NAN = np.nan
THRU = Z.THRU
MIN_STOP, MAX_STOP = Z.MIN_STOP, Z.MAX_STOP
MAX_HOLD_MIN = 1440

# exactly the chosen BTC configs (selected in the backtest); FILTERS copied from the backtest grid
FILTERS = {"cap": {"cap_counter": True}, "ret_ovh": {"ret": True, "overhead": True}}
SETUPS = {
    "A":    dict(stack=(240, 15, 5, 3), params={"mode": "aligned", "msf_only": True, "need_htf_pull": True, "minrr1": 2.0},
                 filt="ret_ovh", cap_r=3.0),
    "G":    dict(stack=(240, 15, 5, 1), params={"need_reason": False, "need_ffb": True, "ctx": "htf_or_disc"},
                 filt="cap", cap_r=5.0),
    "RIMC": dict(stack=(240, 15, 5, 1), params={"msf_only": False, "win": 96}, filt="ret_ovh", cap_r=3.0),
}
ORDER = ("A", "G", "RIMC")   # backtest tie order (trades list A + G + RIMC, stable sort)


HTF_ANCHOR_MS = 1640995200000   # 2022-01-01 00:00 UTC: where the backtest's 4h structure starts


def _htf_structure(d1: dict, prefix: dict | None):
    """4h structure is path dependent for months (tested: a 120-day warm-up still disagrees with the
    backtest on every OOS 4h bar; 365 days agrees). So the 4h state machine runs over the full 4h history
    from 2022-01-01 (prefix = closed 4h bars before the 1m window) + the window's own 4h bars, then is
    sliced back to the window's index space. Lower timeframes converge within days (tested)."""
    tfw = E.resample(d1, 240)
    if prefix is None or len(prefix["c"]) == 0:
        return tfw, E.structure(tfw)
    off = len(prefix["c"])
    assert int(prefix["ts"][-1]) + 240 * 60_000 == int(d1["ts"][0]), "4h prefix must end right before the 1m window"
    big = dict(o=np.concatenate([prefix["o"], tfw["o"]]), h=np.concatenate([prefix["h"], tfw["h"]]),
               l=np.concatenate([prefix["l"], tfw["l"]]), c=np.concatenate([prefix["c"], tfw["c"]]), m=240)
    st = E.structure(big)
    sl = {k: st[k][off:] for k in ("trend", "strong", "weak", "fixed", "pext", "legext")}
    sl["strong_i"] = st["strong_i"][off:] - off
    keep = st["ev_i"] >= off
    for k in ("ev_k", "ev_l", "ev_a", "ev_b"):
        sl[k] = st[k][keep]
    sl["ev_i"] = st["ev_i"][keep] - off
    sl["m"] = 240
    return tfw, sl


def build_cache(d1: dict, htf_prefix: dict | None = None) -> dict:
    """Same derived series as the backtest's data prep, only the timeframes these three setups read."""
    cache = {}
    for m in (1, 3, 5, 15):
        tf = E.resample(d1, m)
        cache[m] = dict(tf=tf, st=E.structure(tf), atr=E.atr(tf))
    tf4, st4 = _htf_structure(d1, htf_prefix)
    cache[240] = dict(tf=tf4, st=st4, atr=E.atr(tf4))
    for m in (5, 15):
        cache[m]["ob"] = E.order_blocks(cache[m]["tf"])
        cache[m]["fvg"] = E.fvgs(cache[m]["tf"])
        cache[m]["piv"] = E.pivots(cache[m]["tf"], 2)
    cache[15]["rng"] = E.ranges(cache[15]["tf"], cache[15]["st"])
    return cache


def _padded(d1):
    """setups.py drops a signal whose decision bar t == len(data) (it needs o[t] to fill). Live, t == N
    is 'now', so the model functions get one placeholder bar (flat at the last close, zero volume) that
    the cache never sees. It cannot create or move any signal: every structure input comes from the cache."""
    p = {k: np.append(v, v[-1]) for k, v in d1.items() if k in ("o", "h", "l", "c", "v")}
    for k in ("o", "h", "l"):
        p[k][-1] = d1["c"][-1]
    p["v"][-1] = 0.0
    p["ts"] = np.append(d1["ts"], d1["ts"][-1] + 60_000)
    return p


def _g_state(sig, d1, f5_against, N):
    """Backtest semantics of a G limit (sim.resolve) evaluated with bars < N only."""
    t, side, lim, cancel = sig["t"], sig["side"], sig["lim"], sig["cancel"]
    e = min(sig["exp"], N)
    l, h, c = d1["l"], d1["h"], d1["c"]
    if side == 1:
        fl = np.nonzero(l[t:e] < lim * (1 - THRU))[0]; cn = np.nonzero(c[t:e] < cancel)[0]
    else:
        fl = np.nonzero(h[t:e] > lim * (1 + THRU))[0]; cn = np.nonzero(c[t:e] > cancel)[0]
    q = np.searchsorted(f5_against, t + 1)
    ffb = int(f5_against[q]) if q < len(f5_against) else None
    if len(fl):
        jf = t + int(fl[0])
        if len(cn) and t + cn[0] < jf:
            return "dead", ffb, None
        return ("done" if (ffb is not None and ffb <= jf) else "dead"), ffb, jf
    if len(cn):
        return "dead", ffb, None
    if N >= sig["exp"]:
        return "expired", ffb, None
    if ffb is not None and ffb <= N:
        return "armed", ffb, None
    return "waiting", ffb, None


def evaluate(d1: dict, htf_prefix: dict | None = None, cache: dict | None = None) -> dict:
    ts = d1["ts"]; N = len(ts)
    assert N > 3 * 1440 and ts[0] % (240 * 60_000) == 0, "need >=3 days of 1m bars starting on a 4h boundary"
    assert np.all(np.diff(ts) == 60_000), "1m bars must be contiguous"
    now_ts = int(ts[-1]) + 60_000
    cache = cache or build_cache(d1, htf_prefix)
    dp = _padded(d1)
    out = {"now_ts": now_ts, "market": [], "g": [], "last_close": float(d1["c"][-1])}
    for name in ORDER:
        cfg = SETUPS[name]
        ctx = S.Ctx(cache, dp, *cfg["stack"])
        raw = S.MODELS[name](ctx, cfg["params"])
        sigs = S.apply_filters(ctx, raw, FILTERS[cfg["filt"]])
        if name == "G":
            f5 = {1: ctx.f5_msf_dn_t, -1: ctx.f5_msf_up_t}
            for s in sigs:
                if s["t"] > N or s["exp"] <= N:
                    continue
                st, ffb, jf = _g_state(s, d1, f5[s["side"]], N)
                rec = dict(setup="G", side=int(s["side"]), lim=float(s["lim"]), stop=float(s["stop"]),
                           cancel=float(s["cancel"]), ts_sig=int(dp["ts"][s["t"]]), exp_ts=int(ts[0] + s["exp"] * 60_000),
                           ffb_ts=(int(ts[0] + ffb * 60_000) if ffb is not None else None), state=st,
                           counter=bool(s.get("counter")), minrr=float(s["minrr"]), cap_r=cfg["cap_r"],
                           tp_from_ts=int(ts[0] + s["tp_from"] * 60_000))
                if st == "armed":
                    seg = d1["h"][s["tp_from"]:N] if s["side"] == 1 else d1["l"][s["tp_from"]:N]
                    rec["final"] = float(seg.max() if s["side"] == 1 else seg.min())
                rec["key"] = f"G:{rec['ts_sig']}:{rec['side']}:{rec['lim']}"
                out["g"].append(rec)
        else:
            for s in sigs:
                if s["t"] != N:
                    continue
                rec = dict(setup=name, side=int(s["side"]), stop=float(s["stop"]), final=float(s["final"]),
                           tp1=float(s["tp1"]), minrr=float(s["minrr"]), cap_r=cfg["cap_r"], ts_sig=now_ts,
                           entry_ref=float(s["entry_ref"]), counter=bool(s.get("counter")))
                rec["key"] = f"{name}:{now_ts}:{rec['side']}"
                out["market"].append(rec)
    return out


def plan_trade(sig: dict, fill_est: float) -> dict | None:
    """sim.resolve's entry checks for a single take-profit 'capK' trade, given the expected fill price.
    Returns stop/tp/R distance, or None with the backtest's rejection reason."""
    side, stop = sig["side"], sig["stop"]
    dist = side * (fill_est - stop)
    if dist <= 0:
        return {"reject": "stop on wrong side of entry"}
    sp = dist / fill_est
    if sp < MIN_STOP or sp > MAX_STOP:
        return {"reject": f"stop distance {sp:.3%} outside [{MIN_STOP:.1%}, {MAX_STOP:.0%}]"}
    final = sig["final"]
    if not np.isfinite(final) or side * (final - fill_est) <= 0:
        return {"reject": "target not beyond entry"}
    rr = side * (final - fill_est) / dist
    if rr < sig["minrr"]:
        return {"reject": f"structural R:R {rr:.2f} < {sig['minrr']}"}
    k = sig["cap_r"]
    tp = min(final, fill_est + k * dist) if side == 1 else max(final, fill_est - k * dist)
    return {"entry": fill_est, "stop": stop, "tp": tp, "dist": dist, "stop_pct": sp, "rr_struct": rr}
