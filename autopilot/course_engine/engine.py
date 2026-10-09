"""Market-structure / zone / range engine for the multi-timeframe SMC rules.

All outputs are causal: anything derived from a timeframe bar k (size m minutes)
is only usable from 1m index (k+1)*m onward (the open of the next 1m bar after
that TF bar closes). 1m data is contiguous (verified), so TF bar k covers
1m rows [k*m, (k+1)*m).
"""
from __future__ import annotations
import numpy as np
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
NAN = np.nan


def load_1m(symbol: str) -> dict:
    a = np.load(DATA / f"{symbol}_1m.npy")
    ts = a[:, 0].astype(np.int64)
    assert np.all(np.diff(ts) == 60_000), "1m data must be contiguous"
    return dict(ts=ts, o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4], v=a[:, 5])


def resample(d: dict, m: int) -> dict:
    n = len(d["c"]) // m
    sl = slice(0, n * m)
    o = d["o"][sl].reshape(n, m)[:, 0]
    h = d["h"][sl].reshape(n, m).max(1)
    l = d["l"][sl].reshape(n, m).min(1)
    c = d["c"][sl].reshape(n, m)[:, -1]
    v = d["v"][sl].reshape(n, m).sum(1)
    return dict(o=o, h=h, l=l, c=c, v=v, m=m, n=n, avail=(np.arange(n) + 1) * m)


def atr(tf: dict, n: int = 14) -> np.ndarray:
    h, l, c = tf["h"], tf["l"], tf["c"]
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    out = np.empty_like(tr)
    a = tr[0]
    k = 1.0 / n
    for i in range(len(tr)):
        a = a + k * (tr[i] - a)
        out[i] = a
    return out


# ---------------------------------------------------------------- structure
# event kinds
BOS_UP, BOS_DN, MSF_UP, MSF_DN, SFP_HI, SFP_LO, FIX_HI, FIX_LO = 1, -1, 2, -2, 3, -3, 4, -4


def structure(tf: dict) -> dict:
    """Structure state machine (3.2-3.4, 3.9).

    Uptrend: weak high trails candle by candle until a valid 2-candle pullback
    (2 consecutive red candles, the 2nd making a lower low than the 1st = inside
    bars ignored). Then the weak high is fixed (BOS line). Strong low = lowest
    low between the fixed high and the break of it. BOS = body close above the
    weak high. Wick above + close back below = SFP (BOS line staircases to the
    wick). MSF = body close below the strong low. Downtrend mirrored.

    Per-bar state after bar i closes:
      trend[i] (+1/-1), strong[i], weak[i] (fixed or trailing), fixed[i] (in pullback),
      pext[i] (pullback extreme so far), legext[i] (impulse extreme of current leg)
    events: list of (i, kind, level, aux1, aux2)
    """
    o, h, l, c = tf["o"], tf["h"], tf["l"], tf["c"]
    n = len(c)
    trend = np.zeros(n, np.int8)
    strong = np.full(n, NAN)
    weak = np.full(n, NAN)
    fixed_a = np.zeros(n, bool)
    pext_a = np.full(n, NAN)
    legext_a = np.full(n, NAN)
    strong_i = np.zeros(n, np.int64)
    ev = []
    tr = 1
    st, st_i = l[0], 0          # strong point
    run, run_i = h[0], 0        # trailing weak extreme (impulse leg extreme)
    fixed = False
    wk = NAN                    # fixed weak level (BOS line)
    pe, pe_i = NAN, 0           # pullback extreme since fix
    since_run, since_run_i = l[0], 0  # opposite extreme since run was set
    red = c < o
    grn = c > o
    for i in range(1, n):
        if tr == 1:
            if c[i] < st:  # bearish MSF
                ev.append((i, MSF_DN, st, run, run_i))
                tr = -1
                st, st_i = (max(run, wk) if fixed else run), run_i
                run, run_i = l[i], i
                since_run, since_run_i = h[i], i
                fixed = False; wk = NAN; pe = NAN
            elif fixed and c[i] > wk:  # bullish BOS
                ev.append((i, BOS_UP, wk, pe, pe_i))
                st, st_i = pe, pe_i
                run, run_i = h[i], i
                since_run, since_run_i = l[i], i
                fixed = False; wk = NAN; pe = NAN
            elif fixed:
                if h[i] > wk:  # SFP of weak high, staircase BOS line
                    ev.append((i, SFP_HI, wk, h[i], pe))
                    wk = h[i]
                    if h[i] > run:
                        run, run_i = h[i], i
                if l[i] < pe:
                    pe, pe_i = l[i], i
            else:
                if h[i] >= run:
                    run, run_i = h[i], i
                    since_run, since_run_i = l[i], i
                elif l[i] < since_run:
                    since_run, since_run_i = l[i], i
                if red[i] and red[i - 1] and l[i] < l[i - 1] and i - 1 >= run_i:
                    fixed = True; wk = run
                    pe, pe_i = since_run, since_run_i
                    ev.append((i, FIX_HI, wk, st, st_i))
        else:
            if c[i] > st:  # bullish MSF
                ev.append((i, MSF_UP, st, run, run_i))
                tr = 1
                st, st_i = (min(run, wk) if fixed else run), run_i
                run, run_i = h[i], i
                since_run, since_run_i = l[i], i
                fixed = False; wk = NAN; pe = NAN
            elif fixed and c[i] < wk:
                ev.append((i, BOS_DN, wk, pe, pe_i))
                st, st_i = pe, pe_i
                run, run_i = l[i], i
                since_run, since_run_i = h[i], i
                fixed = False; wk = NAN; pe = NAN
            elif fixed:
                if l[i] < wk:
                    ev.append((i, SFP_LO, wk, l[i], pe))
                    wk = l[i]
                    if l[i] < run:
                        run, run_i = l[i], i
                if h[i] > pe:
                    pe, pe_i = h[i], i
            else:
                if l[i] <= run:
                    run, run_i = l[i], i
                    since_run, since_run_i = h[i], i
                elif h[i] > since_run:
                    since_run, since_run_i = h[i], i
                if grn[i] and grn[i - 1] and h[i] > h[i - 1] and i - 1 >= run_i:
                    fixed = True; wk = run
                    pe, pe_i = since_run, since_run_i
                    ev.append((i, FIX_LO, wk, st, st_i))
        trend[i] = tr
        strong[i] = st
        strong_i[i] = st_i
        weak[i] = wk if fixed else run
        fixed_a[i] = fixed
        pext_a[i] = pe
        legext_a[i] = run
    evk = np.array([e[1] for e in ev], np.int8)
    evi = np.array([e[0] for e in ev], np.int64)
    evl = np.array([e[2] for e in ev], float)
    eva = np.array([e[3] for e in ev], float)
    evb = np.array([e[4] for e in ev], float)
    return dict(trend=trend, strong=strong, strong_i=strong_i, weak=weak, fixed=fixed_a,
                pext=pext_a, legext=legext_a, ev_i=evi, ev_k=evk, ev_l=evl, ev_a=eva, ev_b=evb,
                m=tf["m"])


def state_at(st: dict, t1m: np.ndarray | int):
    """Index of last closed TF bar usable at 1m index t (or -1)."""
    return np.asarray(t1m) // st["m"] - 1


# ------------------------------------------------------------ fractal pivots
def pivots(tf: dict, k: int = 2):
    """Fractal pivots with k bars each side. Confirmed (usable) at bar i+k close."""
    h, l = tf["h"], tf["l"]
    n = len(h)
    ph, pl = [], []
    for i in range(k, n - k):
        hw = h[i - k:i + k + 1]
        if h[i] == hw.max() and (hw[:k] < h[i]).all():
            ph.append(i)
        lw = l[i - k:i + k + 1]
        if l[i] == lw.min() and (lw[:k] > l[i]).all():
            pl.append(i)
    ph = np.array(ph, np.int64); pl = np.array(pl, np.int64)
    return dict(hi_i=ph, hi_px=h[ph], hi_conf=ph + k, lo_i=pl, lo_px=l[pl], lo_conf=pl + k)


# --------------------------------------------------------------- OBs / FVGs
def order_blocks(tf: dict, max_group: int = 3, age: int = 2000):
    """Order block (4.5): last 1..max_group opposite candles, push candle, and an
    imbalance (c3 does not overlap the zone). Demand: zone top = max high of
    group, bottom = min(group lows, push low). Confirmed at c3 close.
    Also tracks first touch (proximal edge traded into) and invalidation
    (close beyond distal edge) bar indices (on this TF), causally after conf.
    """
    o, h, l, c = tf["o"], tf["h"], tf["l"], tf["c"]
    n = len(c)
    red = c < o; grn = c > o
    zs = []
    for j in range(max_group, n - 2):
        p = j + 1; c3 = j + 2
        # demand
        if red[j] and grn[p]:
            g0 = j
            while g0 - 1 >= 0 and red[g0 - 1] and j - (g0 - 1) < max_group:
                g0 -= 1
            top = h[g0:j + 1].max(); bot = min(l[g0:j + 1].min(), l[p])
            if l[c3] > top:
                zs.append((1, top, bot, g0, c3))
        if grn[j] and red[p]:
            g0 = j
            while g0 - 1 >= 0 and grn[g0 - 1] and j - (g0 - 1) < max_group:
                g0 -= 1
            bot = l[g0:j + 1].min(); top = max(h[g0:j + 1].max(), h[p])
            if h[c3] < bot:
                zs.append((-1, top, bot, g0, c3))
    side = np.array([z[0] for z in zs], np.int8)
    top = np.array([z[1] for z in zs]); bot = np.array([z[2] for z in zs])
    org = np.array([z[3] for z in zs], np.int64); conf = np.array([z[4] for z in zs], np.int64)
    touch = np.full(len(zs), n, np.int64); inval = np.full(len(zs), n, np.int64)
    for k in range(len(zs)):
        s = conf[k] + 1
        e = min(n, s + age)
        if s >= n:
            continue
        if side[k] == 1:
            tt = np.nonzero(l[s:e] <= top[k])[0]
            ii = np.nonzero(c[s:e] < bot[k])[0]
        else:
            tt = np.nonzero(h[s:e] >= bot[k])[0]
            ii = np.nonzero(c[s:e] > top[k])[0]
        if len(tt): touch[k] = s + tt[0]
        if len(ii): inval[k] = s + ii[0]
        else: inval[k] = min(inval[k], e)
    m = tf["m"]
    return dict(side=side, top=top, bot=bot, org=org, conf=conf, touch=touch, inval=inval,
                conf_t=(conf + 1) * m, touch_t=touch * m, inval_t=(inval + 1) * m, m=m)


def fvgs(tf: dict):
    h, l = tf["h"], tf["l"]
    up = np.nonzero(l[2:] > h[:-2])[0]
    dn = np.nonzero(h[2:] < l[:-2])[0]
    return dict(up_i=up + 2, up_top=l[up + 2], up_bot=h[up], dn_i=dn + 2, dn_top=l[dn], dn_bot=h[dn + 2], m=tf["m"])


# ------------------------------------------------------------ volume profile
def volume_profile(d1: dict, i0: int, i1: int, rows: int = 200, va: float = 0.70):
    """FRVP over 1m bars [i0, i1). Volume spread across each bar's high-low."""
    i0 = max(0, i0)
    if i1 - i0 < 5:
        return NAN, NAN, NAN
    h = d1["h"][i0:i1]; l = d1["l"][i0:i1]; v = d1["v"][i0:i1]
    lo, hi = l.min(), h.max()
    if hi <= lo:
        return NAN, NAN, NAN
    edges = np.linspace(lo, hi, rows + 1)
    mid = (h + l) * 0.5
    # split each bar's volume across low/mid/high (cheap approximation of spreading)
    w = np.zeros(rows)
    for px, f in ((l, 0.25), (mid, 0.5), (h, 0.25)):
        idx = np.clip(((px - lo) / (hi - lo) * rows).astype(int), 0, rows - 1)
        w += np.bincount(idx, weights=v * f, minlength=rows)
    poc = int(np.argmax(w))
    tot = w.sum(); acc = w[poc]; a = b = poc
    while acc < va * tot and (a > 0 or b < rows - 1):
        up = w[b + 1] if b < rows - 1 else -1
        dn = w[a - 1] if a > 0 else -1
        if up >= dn:
            b += 1; acc += up
        else:
            a -= 1; acc += dn
    cen = (edges[:-1] + edges[1:]) * 0.5
    return cen[poc], edges[b + 1], edges[a]  # poc, vah, val


# --------------------------------------------------------------------- ranges
def ranges(tf: dict, st: dict, eq_tol: float = 0.0, k_break: float = 0.3,
           max_out: int = 12, max_age: int = 960):
    """Range engine (5.2/5.3/5.9). Candidate range drawn from structure when a
    weak point gets fixed (pullback starts): uptrend [strong low, weak high],
    downtrend [weak low, strong high]. Valid once price touches EQ (tolerance
    eq_tol * height short of EQ allowed). Wick deviations expand the boundary.
    A close outside starts an 'outside' episode: conviction break once the
    excursion beyond the edge exceeds k_break * height (range retired), or a
    reclaim (close back inside) = deviation / poor break; boundary moves to the
    extreme.
    Events: (i, kind, side, lo, hi, start_i, extreme, bars_out, taps)
      kind 'dev' = wick-only or reclaim deviation; 'brk' = conviction break;
      'valid' = range validated.
    Also per-bar active range lo/hi/valid/start arrays (state after bar i).
    """
    h, l, c = tf["h"], tf["l"], tf["c"]
    n = len(c)
    fixes = {}
    for i, k, lev, a, b in zip(st["ev_i"], st["ev_k"], st["ev_l"], st["ev_a"], st["ev_b"]):
        if k == FIX_HI:
            fixes[int(i)] = (a, lev, int(b), 1)   # lo=strong low, hi=weak high, start=strong low idx
        elif k == FIX_LO:
            fixes[int(i)] = (lev, a, int(b), -1)
    rlo = np.full(n, NAN); rhi = np.full(n, NAN); rval = np.zeros(n, bool); rstart = np.full(n, -1, np.int64)
    ev = []
    act = None
    for i in range(n):
        if i in fixes and (act is None or not act["valid"]):
            lo, hi, s0, dirn = fixes[i]
            if hi > lo:
                act = dict(lo=lo, hi=hi, start=s0, valid=False, dirn=dirn, out=0, ext=NAN, out_i=0,
                           taps_lo=0, taps_hi=0, born=i)
        if act is not None:
            lo, hi = act["lo"], act["hi"]; H = hi - lo; eq = 0.5 * (lo + hi)
            if not act["valid"]:
                if c[i] > hi or c[i] < lo:
                    act = None
                elif (act["dirn"] == 1 and l[i] <= eq + eq_tol * H) or (act["dirn"] == -1 and h[i] >= eq - eq_tol * H):
                    act["valid"] = True
                    ev.append((i, "valid", 0, lo, hi, act["start"], NAN, 0, 0))
            else:
                if i - act["born"] > max_age:
                    act = None
                elif act["out"] == 0:
                    if c[i] > hi:
                        act["out"] = 1; act["ext"] = h[i]; act["out_i"] = i
                    elif c[i] < lo:
                        act["out"] = -1; act["ext"] = l[i]; act["out_i"] = i
                    else:
                        if h[i] > hi:
                            act["taps_hi"] += 1
                            ev.append((i, "dev", 1, lo, hi, act["start"], h[i], 0, act["taps_hi"]))
                            act["hi"] = h[i]
                        if l[i] < lo:
                            act["taps_lo"] += 1
                            ev.append((i, "dev", -1, lo, hi, act["start"], l[i], 0, act["taps_lo"]))
                            act["lo"] = l[i]
                else:
                    s = act["out"]
                    act["ext"] = max(act["ext"], h[i]) if s == 1 else min(act["ext"], l[i])
                    exc = (act["ext"] - hi) if s == 1 else (lo - act["ext"])
                    if exc > k_break * H or i - act["out_i"] > max_out:
                        ev.append((i, "brk", s, lo, hi, act["start"], act["ext"], i - act["out_i"], 0))
                        act = None
                    elif (s == 1 and c[i] <= hi) or (s == -1 and c[i] >= lo):
                        bars = i - act["out_i"]
                        if s == 1:
                            act["taps_hi"] += 1
                            ev.append((i, "dev", 1, lo, hi, act["start"], act["ext"], bars, act["taps_hi"]))
                            act["hi"] = act["ext"]
                        else:
                            act["taps_lo"] += 1
                            ev.append((i, "dev", -1, lo, hi, act["start"], act["ext"], bars, act["taps_lo"]))
                            act["lo"] = act["ext"]
                        act["out"] = 0
        if act is not None:
            rlo[i] = act["lo"]; rhi[i] = act["hi"]; rval[i] = act["valid"]; rstart[i] = act["start"]
    return dict(lo=rlo, hi=rhi, valid=rval, start=rstart, ev=ev, m=tf["m"])
