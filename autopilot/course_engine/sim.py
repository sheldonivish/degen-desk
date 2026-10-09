"""Trade resolution on 1m bars + sequential portfolio + metrics.

Costs: Lighter Standard account = 0 maker / 0 taker fees (docs, Oct 2026).
`fee_taker`/`fee_maker` are parameters (bps). Slippage `slip` bps per side
applies to every market-type fill (market entries, stops, flip/time exits).
Limit entries fill at the limit only if price trades THROUGH it by 1 bp;
take-profits are resting limits filled only if price trades through by 1 bp.
Intrabar: stop is checked before targets (conservative); a limit fill bar
can stop out in the same bar but cannot take profit in it.
"""
from __future__ import annotations
import numpy as np

NAN = np.nan
MIN_STOP = 0.0010
MAX_STOP = 0.02
THRU = 0.0001


def resolve(sig, d1, flips_against, bos_against, mgmt, slip_bps=2.0, fee_taker=0.0, fee_maker=0.0,
            max_hold=1440, be_at_r=1.0, f5_against=None):
    o, h, l, c = d1["o"], d1["h"], d1["l"], d1["c"]
    N = len(c)
    side = sig["side"]; slip = slip_bps * 1e-4; ft = fee_taker * 1e-4; fm = fee_maker * 1e-4
    t = sig["t"]
    if t >= N:
        return None
    stop = sig["stop"]
    # ---------------- entry
    if sig["kind"] == "mkt":
        fill = o[t] * (1 + side * slip)
        fee_in = ft
        j0 = t
        same_bar_tp = True
    else:
        lim = sig["lim"]; e = min(sig["exp"], N)
        if side == 1:
            fl = np.nonzero(l[t:e] < lim * (1 - THRU))[0]
            cn = np.nonzero(c[t:e] < sig["cancel"])[0]
        else:
            fl = np.nonzero(h[t:e] > lim * (1 + THRU))[0]
            cn = np.nonzero(c[t:e] > sig["cancel"])[0]
        if not len(fl):
            return None
        jf = t + fl[0]
        if len(cn) and t + cn[0] < jf:
            return None
        if sig.get("need_ffb") and f5_against is not None:
            a = f5_against
            q = np.searchsorted(a, sig["t"] + 1)
            if not (q < len(a) and a[q] <= jf):
                return None
        # gap-through open fills at the open (better for us); otherwise at the limit
        fill = min(lim, o[jf]) if side == 1 else max(lim, o[jf])
        fee_in = fm
        j0 = jf
        same_bar_tp = False
        if not np.isfinite(sig["final"]):
            tf = sig["tp_from"]
            ext = h[tf:jf].max() if side == 1 else l[tf:jf].min()
            sig = dict(sig); sig["final"] = ext; sig["tp1"] = fill + 0.5 * (ext - fill)
    dist = side * (fill - stop)
    if dist <= 0:
        return None
    sp = dist / fill
    if sp < MIN_STOP or sp > MAX_STOP:
        return None
    final = sig["final"]; tp1 = sig["tp1"]; tp2 = sig.get("tp2", NAN)
    if not np.isfinite(final) or side * (final - fill) <= 0:
        return None
    rr = side * (final - fill) / dist
    if rr < sig["minrr"]:
        return None
    # ---------------- legs
    if mgmt == "fixed":
        legs = [(final, 1.0)]
    elif mgmt.startswith("cap"):
        k = float(mgmt[3:])
        legs = [((min(final, fill + k * dist) if side == 1 else max(final, fill - k * dist)), 1.0)]
    elif mgmt.startswith("pc"):  # 50% at first opposing level capped at k R, BE, runner to final w/ MTF flip exit
        k = float(mgmt[2:])
        t1 = fill + side * k * dist
        if np.isfinite(tp1) and side * (tp1 - fill) > 0:
            t1 = min(t1, tp1) if side == 1 else max(t1, tp1)
        legs = [(t1, 0.5), (final, 0.5)] if side * (final - t1) > 0 else [(final, 1.0)]
    elif mgmt == "tp1":
        if not np.isfinite(tp1) or side * (tp1 - fill) <= 0:
            return None
        legs = [(tp1, 1.0)]
    else:
        if not np.isfinite(tp1) or side * (tp1 - fill) <= 0 or side * (final - tp1) <= 0:
            legs = [(final, 1.0)]
        elif mgmt == "scale3" and np.isfinite(tp2) and side * (tp2 - tp1) > 0 and side * (final - tp2) > 0:
            legs = [(tp1, 1 / 3), (tp2, 1 / 3), (final, 1 / 3)]
        else:
            legs = [(tp1, 0.5), (final, 0.5)]
    managed = mgmt in ("partial", "scale3") or mgmt.startswith("pc")
    # next MTF flip against (runner exit / de-risk)
    fa = flips_against; qa = np.searchsorted(fa, j0 + 1); nxt_flip = fa[qa] if qa < len(fa) else N + 1
    ba = bos_against; qb = np.searchsorted(ba, j0 + 1); nxt_bos = ba[qb] if qb < len(ba) else N + 1
    rem = 1.0; pnl = 0.0; fees = fee_in; cur_stop = stop; li = 0; be = False
    reason = "time"; j_exit = min(j0 + max_hold, N - 1)
    jend = min(j0 + max_hold, N)
    j = j0
    mfe_r = 0.0
    while j < jend:
        if managed and j >= nxt_bos and j > j0 and not be:
            cur_stop = fill; be = True
        if managed and li > 0 and j >= nxt_flip and j > j0:
            px = o[j] * (1 - side * slip)
            pnl += rem * side * (px - fill); fees += rem * ft; rem = 0
            reason = "mtf_flip"; j_exit = j
            break
        # stop
        if (side == 1 and l[j] <= cur_stop) or (side == -1 and h[j] >= cur_stop):
            px = o[j] if ((side == 1 and o[j] < cur_stop) or (side == -1 and o[j] > cur_stop)) else cur_stop
            if j == j0 and sig["kind"] == "mkt":
                px = cur_stop if (side * (o[j] - cur_stop) > 0) else o[j]
            px *= (1 - side * slip)
            pnl += rem * side * (px - fill); fees += rem * ft; rem = 0
            reason = "be" if be and cur_stop == fill else "sl"; j_exit = j
            break
        if j > j0 or same_bar_tp:
            while li < len(legs):
                tp, fr = legs[li]
                if (side == 1 and h[j] > tp * (1 + THRU)) or (side == -1 and l[j] < tp * (1 - THRU)):
                    pnl += fr * side * (tp - fill); fees += fr * fm; rem -= fr; li += 1
                    if managed and not be:
                        cur_stop = fill; be = True
                else:
                    break
            if rem <= 1e-9:
                reason = "tp"; j_exit = j
                break
        # +1R breakeven (decided on bar close -> applies from next bar)
        if managed and not be and be_at_r > 0:
            fav = side * ((h[j] if side == 1 else l[j]) - fill) / dist
            if fav >= be_at_r:
                cur_stop = fill; be = True
        j += 1
    if rem > 1e-9:
        jx = min(j, N - 1)
        px = c[jx] * (1 - side * slip)
        pnl += rem * side * (px - fill); fees += rem * ft
        j_exit = jx
    R = (pnl - fees * fill) / dist
    return dict(setup=sig["setup"], side=side, t_sig=sig["t"], t_in=int(j0), t_out=int(j_exit), entry=fill,
                stop=stop, final=final, rr=rr, stop_pct=sp, R=float(R), reason=reason, counter=bool(sig.get("counter")))


def resolve_all(sigs, ctx, mgmt, slip_bps=2.0, fee_taker=0.0, fee_maker=0.0, be_at_r=1.0):
    out = []
    flips = {1: ctx.m_msf_dn_t, -1: ctx.m_msf_up_t}
    boss = {1: ctx.m_bos_dn_t, -1: ctx.m_bos_up_t}
    f5 = {1: ctx.f5_msf_dn_t, -1: ctx.f5_msf_up_t}
    for s in sigs:
        r = resolve(s, ctx.d1, flips[s["side"]], boss[s["side"]], mgmt, slip_bps, fee_taker, fee_maker,
                    be_at_r=be_at_r, f5_against=f5[s["side"]])
        if r is not None:
            out.append(r)
    return out


def portfolio(trades, ts, t_lo, t_hi, risk=0.01, lev_cap=10.0, day_cap_r=4.0, eq0=1.0):
    """One position at a time, chronological by fill. Daily stop after
    -day_cap_r R realised in the UTC day. Fixed-fractional compounding.
    Leverage cap scales risk down when stop is tight."""
    tr = sorted([x for x in trades if t_lo <= x["t_in"] < t_hi], key=lambda x: (x["t_in"], x["t_sig"]))
    busy = -1; eq = eq0; taken = []
    day_r = {}
    for x in tr:
        if x["t_in"] <= busy:
            continue
        day = ts[x["t_in"]] // 86_400_000
        if day_r.get(day, 0.0) <= -day_cap_r:
            continue
        scale = min(1.0, lev_cap * x["stop_pct"] / risk)
        ret = risk * scale * x["R"]
        eq *= (1 + ret)
        y = dict(x); y["ret"] = ret; y["eq"] = eq
        taken.append(y)
        busy = x["t_out"]
        dx = ts[x["t_out"]] // 86_400_000
        day_r[dx] = day_r.get(dx, 0.0) + x["R"] * scale
    return taken


def metrics(taken, ts, t_lo, t_hi, eq0=1.0):
    d0 = ts[t_lo] // 86_400_000; d1 = ts[min(t_hi, len(ts)) - 1] // 86_400_000
    nd = int(d1 - d0 + 1)
    daily = np.zeros(nd)
    for x in taken:
        k = int(ts[x["t_out"]] // 86_400_000 - d0)
        if 0 <= k < nd:
            daily[k] = (1 + daily[k]) * (1 + x["ret"]) - 1
    n = len(taken)
    eq = np.cumprod(1 + daily)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))
    dd = (np.concatenate([[1.0], eq]) / peak - 1).min()
    # trade-level DD too (intra-day sequences)
    te = np.cumprod([1 + x["ret"] for x in taken]) if n else np.array([1.0])
    tpk = np.maximum.accumulate(np.concatenate([[1.0], te]))
    tdd = (np.concatenate([[1.0], te]) / tpk - 1).min()
    sd = daily.std(ddof=1) if nd > 2 else 0
    sh = daily.mean() / sd * np.sqrt(365) if sd > 0 else 0.0
    R = np.array([x["R"] for x in taken]) if n else np.array([])
    rets = np.array([x["ret"] for x in taken]) if n else np.array([])
    gw = rets[rets > 0].sum(); gl = -rets[rets < 0].sum()
    streak = ws = 0
    for r in R:
        streak = streak + 1 if r < 0 else 0; ws = max(ws, streak)
    tot = float(eq[-1] - 1) if nd else 0.0
    yrs = nd / 365.0
    return dict(trades=n, win=float((R > 0).mean()) if n else 0.0, avgR=float(R.mean()) if n else 0.0,
                pf=float(gw / gl) if gl > 0 else (np.inf if gw > 0 else 0.0), sharpe=float(sh),
                maxdd=float(min(dd, tdd)), ret=tot, cagr=float((1 + tot) ** (1 / yrs) - 1) if yrs > 0 and tot > -1 else -1.0,
                streak=int(ws), tpd=n / max(nd, 1),
                tstat=float(R.mean() / (R.std(ddof=1) / np.sqrt(n))) if n > 2 and R.std() > 0 else 0.0)
