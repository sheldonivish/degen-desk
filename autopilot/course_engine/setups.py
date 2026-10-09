"""Setups -> candidate signals. Every signal is built only from data
available at its decision time (1m index t). Signals are dicts:
  setup, t, side, kind ('mkt'|'lmt'), lim, stop, tp1, tp2, final, exp, cancel,
  tp_from (lmt: compute final at fill = extreme since this idx), minrr, counter
"""
from __future__ import annotations
import numpy as np
import engine as E
from engine import BOS_UP, BOS_DN, MSF_UP, MSF_DN, SFP_HI, SFP_LO

NAN = np.nan
HM, MM, GM = 240, 15, 5


class Ctx:
    def __init__(self, cache, d1, hm=240, mm=15, gm=5, ltf=3):
        self.c = cache
        self.d1 = d1
        global HM, MM, GM
        HM, MM, GM = hm, mm, gm
        self.hm, self.mm, self.gm = hm, mm, gm
        self.H = cache[hm]; self.M = cache[mm]; self.L = cache[ltf]; self.ltf = ltf
        self.F5 = cache[gm]
        st = self.M["st"]
        self.m_msf_up_t = (st["ev_i"][st["ev_k"] == MSF_UP] + 1) * MM
        self.m_msf_dn_t = (st["ev_i"][st["ev_k"] == MSF_DN] + 1) * MM
        self.m_bos_up_t = (st["ev_i"][np.isin(st["ev_k"], (BOS_UP, MSF_UP))] + 1) * MM
        self.m_bos_dn_t = (st["ev_i"][np.isin(st["ev_k"], (BOS_DN, MSF_DN))] + 1) * MM
        s5 = self.F5["st"]
        self.f5_msf_dn_t = (s5["ev_i"][s5["ev_k"] == MSF_DN] + 1) * GM
        self.f5_msf_up_t = (s5["ev_i"][s5["ev_k"] == MSF_UP] + 1) * GM
        ob = self.M["ob"]
        self.sup = {k: ob[k][ob["side"] == -1] for k in ("top", "bot", "conf_t", "touch_t", "inval_t")}
        self.dem = {k: ob[k][ob["side"] == 1] for k in ("top", "bot", "conf_t", "touch_t", "inval_t")}

    # --- states at 1m index t
    def htf(self, t):
        k = t // HM - 1
        H = self.H["st"]
        return int(H["trend"][k]), H["strong"][k], H["weak"][k], bool(H["fixed"][k])

    def mtf(self, t):
        k = t // MM - 1
        M = self.M["st"]
        return int(M["trend"][k]), M["strong"][k], M["weak"][k], bool(M["fixed"][k]), M["pext"][k]

    def htf_eq(self, t):
        tr, s, w, _ = self.htf(t)
        lo, hi = (s, w) if tr == 1 else (w, s)
        return 0.5 * (lo + hi), lo, hi

    def atr15(self, t):
        return self.M["atr"][t // MM - 1]

    def aggressive_return(self, t, side, k_atr=3.0, nbars=4):
        """6.7: last leg into the entry was one big impulse against the trade."""
        k = t // MM - 1
        tf = self.M["tf"]
        a = self.M["atr"][k]
        if side == 1:
            drop = tf["h"][k - nbars + 1:k + 1].max() - tf["l"][k - nbars + 1:k + 1].min()
            dirn = tf["c"][k] < tf["o"][k - nbars + 1]
        else:
            drop = tf["h"][k - nbars + 1:k + 1].max() - tf["l"][k - nbars + 1:k + 1].min()
            dirn = tf["c"][k] > tf["o"][k - nbars + 1]
        return bool(dirn and drop >= k_atr * a)

    def overhead(self, t, side, entry, stop, r_mult=1.0):
        """6.7/4.8: unmitigated opposing 15m OB within r_mult*R of entry."""
        R = abs(entry - stop)
        z = self.sup if side == 1 else self.dem
        live = (z["conf_t"] <= t) & (z["touch_t"] >= t) & (z["inval_t"] > t)
        if side == 1:
            hit = live & (z["bot"] > entry) & (z["bot"] < entry + r_mult * R)
        else:
            hit = live & (z["top"] < entry) & (z["top"] > entry - r_mult * R)
        return bool(hit.any())

    def next_opposing(self, t, side, entry):
        z = self.sup if side == 1 else self.dem
        live = (z["conf_t"] <= t) & (z["touch_t"] >= t) & (z["inval_t"] > t)
        if side == 1:
            c = z["bot"][live & (z["bot"] > entry)]
            return c.min() if len(c) else NAN
        c = z["top"][live & (z["top"] < entry)]
        return c.max() if len(c) else NAN


def _ltf_events(ctx, kinds):
    st = ctx.L["st"]
    msk = np.isin(st["ev_k"], kinds)
    return st["ev_i"][msk], st["ev_k"][msk]


def _first_ltf_after(ctx, t0, t1, kinds_cache, side):
    """First LTF flip in direction `side` with avail in [t0, t1)."""
    arr = kinds_cache[side]
    j = np.searchsorted(arr, t0)
    if j < len(arr) and arr[j] < t1:
        return int(arr[j])
    return -1


def ltf_flip_times(ctx, msf_only=True):
    st = ctx.L["st"]
    up = (MSF_UP,) if msf_only else (MSF_UP, BOS_UP)
    dn = (MSF_DN,) if msf_only else (MSF_DN, BOS_DN)
    ups = st["ev_i"][np.isin(st["ev_k"], up)]
    dns = st["ev_i"][np.isin(st["ev_k"], dn)]
    m = ctx.ltf
    # map avail time -> ltf bar index for stop lookup
    return {1: (ups + 1) * m, -1: (dns + 1) * m, "i1": ups, "i-1": dns}


def _sig(**kw):
    base = dict(kind="mkt", lim=NAN, tp2=NAN, exp=-1, cancel=NAN, tp_from=-1, counter=False, minrr=2.0)
    base.update(kw)
    return base


# =============================================================== Model A
def model_a(ctx, p):
    """3.6/3.7: HTF trend, MTF aligned & pulling back, LTF flip -> enter.
    TP1 = MTF weak point, final = HTF weak point."""
    out = []
    st = ctx.L["st"]; m = ctx.ltf
    kinds = (MSF_UP, MSF_DN) if p.get("msf_only", True) else (MSF_UP, MSF_DN, BOS_UP, BOS_DN)
    msk = np.isin(st["ev_k"], kinds)
    c1 = ctx.d1["c"]
    for i, k in zip(st["ev_i"][msk], st["ev_k"][msk]):
        side = 1 if k > 0 else -1
        t = int((i + 1) * m)
        if t // HM < 2 or t >= len(c1):
            continue
        htr, hs, hw, hfix = ctx.htf(t)
        mtr, ms, mw, mfix, mpe = ctx.mtf(t)
        if htr != side:
            continue
        if p.get("need_htf_pull", False) and not hfix:
            continue
        if p.get("mode", "aligned") == "aligned":
            if mtr != side or not mfix:
                continue
            tp1 = mw
        else:  # aggressive: MTF still against, target only MTF internal point
            if mtr != -side:
                continue
            tp1 = ms
        entry = c1[t - 1]
        stop = st["strong"][i]
        final = hw
        if not np.isfinite(stop) or side * (entry - stop) <= 0:
            continue
        if side * (tp1 - entry) <= 0:
            continue
        if side * (final - tp1) < 0 or p.get("mode") == "aggressive":
            final = tp1
        rr1 = side * (tp1 - entry) / (side * (entry - stop))
        if rr1 < p.get("minrr1", 1.0):
            continue
        out.append(_sig(setup="A", t=t, side=side, stop=stop, tp1=tp1, final=final,
                        minrr=p.get("minrr", 2.0), entry_ref=entry))
    return out


# =============================================================== RIMC (6.2)
def model_rimc(ctx, p):
    """Range -> Initiation (conviction break) -> Mitigation (touch of the
    broken range's outer edge) -> Continuation. Entry on LTF flip after the
    touch (variant b in notes); stop = LTF protected point; TP1 = break
    extreme, final = HTF weak point or measured move."""
    out = []
    rng = ctx.M["rng"]; tf = ctx.M["tf"]; d1 = ctx.d1
    flips = ltf_flip_times(ctx, p.get("msf_only", True))
    st = ctx.L["st"]
    win = p.get("win", 96)
    for (i, kind, s, lo, hi, start, ext, bars, taps) in rng["ev"]:
        if kind != "brk":
            continue
        H = hi - lo
        t0 = (i + 1) * MM
        edge = hi if s == 1 else lo
        far = lo if s == 1 else hi
        # walk 15m bars after break: find first touch of edge, invalidate on close beyond far edge
        e1 = min((i + 1 + win) * MM, len(d1["c"]))
        tt = np.nonzero((d1["l"][t0:e1] <= edge) if s == 1 else (d1["h"][t0:e1] >= edge))[0]
        if not len(tt):
            continue
        touched_t = t0 + int(tt[0])  # 1m bar of the touch; flips must be available after it closes
        kt = touched_t // MM
        tend = min((i + 1 + win) * MM, len(d1["c"]))
        # invalidation: 15m close beyond far edge
        cl = tf["c"][kt:i + 1 + win]
        bad = np.nonzero((cl < far) if s == 1 else (cl > far))[0]
        if len(bad):
            tend = min(tend, (kt + bad[0] + 1) * MM)
        arr = flips[s]
        j = np.searchsorted(arr, touched_t + 1)
        if j >= len(arr) or arr[j] >= tend:
            continue
        t = int(arr[j]); li = flips[f"i{s}"][j]
        entry = d1["c"][t - 1]
        stop = st["strong"][li]
        if not np.isfinite(stop) or s * (entry - stop) <= 0:
            continue
        seg = d1["h"][t0:t] if s == 1 else d1["l"][t0:t]
        tp1 = seg.max() if s == 1 else seg.min()
        tp1 = max(tp1, ext) if s == 1 else min(tp1, ext)
        htr, hs, hw, _ = ctx.htf(t)
        mm = edge + s * H
        final = (max(hw, mm) if s == 1 else min(hw, mm)) if htr == s else mm
        if s * (tp1 - entry) <= 0:
            continue
        out.append(_sig(setup="RIMC", t=t, side=s, stop=stop, tp1=tp1, final=final,
                        minrr=p.get("minrr", 2.0), entry_ref=entry))
    return out


# =============================================================== Model B (+5.7)
def model_b(ctx, p):
    """3.9: MTF SFP of the weak point, confirmed by an LTF MSF the other way.
    Stop above SFP wick extreme; target = the pullback point that failed.
    range_only: SFP must sweep the active 15m range edge (5.7 range SFP)."""
    out = []
    M = ctx.M; st = M["st"]; tf = M["tf"]; d1 = ctx.d1; rng = M["rng"]
    flips = ltf_flip_times(ctx, True)
    stL = ctx.L["st"]
    N = p.get("win", 8)
    for i, k, lev, wick, tgt in zip(st["ev_i"], st["ev_k"], st["ev_l"], st["ev_a"], st["ev_b"]):
        if k not in (SFP_HI, SFP_LO):
            continue
        side = -1 if k == SFP_HI else 1
        if not np.isfinite(tgt):
            continue
        if p.get("range_only", False):
            if not rng["valid"][i - 1]:
                continue
            edge = rng["hi"][i - 1] if side == -1 else rng["lo"][i - 1]
            if not ((side == -1 and wick >= edge) or (side == 1 and wick <= edge)):
                continue
        t0 = (i + 1) * MM
        t1 = min((i + 1 + N) * MM, len(d1["c"]))
        # cancel if a 15m body closes beyond the wick (real BOS) before the flip
        cl = tf["c"][i + 1:i + 1 + N]
        bad = np.nonzero((cl > wick) if side == -1 else (cl < wick))[0]
        if len(bad):
            t1 = min(t1, (i + 1 + bad[0] + 1) * MM)
        arr = flips[side]
        j = np.searchsorted(arr, t0)
        if j >= len(arr) or arr[j] >= t1:
            continue
        t = int(arr[j])
        entry = d1["c"][t - 1]
        ext = d1["h"][i * MM:t].max() if side == -1 else d1["l"][i * MM:t].min()
        stop = ext * (1 + p.get("buf", 0.0002)) if side == -1 else ext * (1 - p.get("buf", 0.0002))
        if side * (tgt - entry) <= 0:
            continue
        htr, hs, hw, _ = ctx.htf(t)
        final = tgt
        counter = htr != side
        if not counter and p.get("extend_pro", True) and side * (hw - tgt) > 0:
            final = hw
        tp1 = entry + 0.5 * (tgt - entry) if final == tgt else tgt
        out.append(_sig(setup="B" + ("r" if p.get("range_only") else ""), t=t, side=side, stop=stop,
                        tp1=tp1, final=final, counter=counter, minrr=p.get("minrr", 1.8), entry_ref=entry))
    return out


# =============================================================== Model G (FFB / Golden Zone)
def model_g(ctx, p):
    """6.4: after an MTF flip, Golden Zone = latest unmitigated 5m OB at the
    origin of the leg that broke structure. Limit at its proximal edge, stop
    below distal edge, TP = the swing extreme before the trap (computed at
    fill). Requires a reason to return (5m FVG or equal lows above the zone),
    optional 'FFB' (5m MSF against before fill)."""
    out = []
    M = ctx.M; st = M["st"]; d1 = ctx.d1
    ob = ctx.F5["ob"]; fv = ctx.F5["fvg"]; pv = ctx.F5["piv"]
    exp_bars = p.get("exp", 96)
    for i, k, lev, legx, legx_i in zip(st["ev_i"], st["ev_k"], st["ev_l"], st["ev_a"], st["ev_b"]):
        if k not in (MSF_UP, MSF_DN) and not (p.get("use_bos", False) and k in (BOS_UP, BOS_DN)):
            continue
        side = 1 if k > 0 else -1
        tA = int((i + 1) * MM)
        if tA // HM < 2:
            continue
        legx_t = int(legx_i) * MM
        cand = (ob["side"] == side) & (ob["conf_t"] <= tA) & (ob["touch_t"] >= tA) & (ob["org"] * GM >= legx_t)
        if side == 1:
            cand &= (ob["bot"] >= legx) & (ob["top"] < lev)
        else:
            cand &= (ob["top"] <= legx) & (ob["bot"] > lev)
        idx = np.nonzero(cand)[0]
        if not len(idx):
            continue
        z = idx[-1]
        top, bot = ob["top"][z], ob["bot"][z]
        zc = ob["conf_t"][z]
        # reason to return: FVG beyond the zone formed after zone conf, or equal lows/highs
        reason = False
        if side == 1:
            fm = ((fv["up_i"] + 1) * GM >= zc) & ((fv["up_i"] + 1) * GM <= tA) & (fv["up_bot"] > top)
            reason = bool(fm.any())
            if not reason:
                pm = (pv["lo_conf"] + 1) * GM
                sel = (pm >= zc) & (pm <= tA) & (pv["lo_px"] > top)
                px = np.sort(pv["lo_px"][sel])
                reason = len(px) >= 2 and bool((np.diff(px) / px[1:] < p.get("eq_tol", 0.0008)).any())
        else:
            fm = ((fv["dn_i"] + 1) * GM >= zc) & ((fv["dn_i"] + 1) * GM <= tA) & (fv["dn_top"] < bot)
            reason = bool(fm.any())
            if not reason:
                pm = (pv["hi_conf"] + 1) * GM
                sel = (pm >= zc) & (pm <= tA) & (pv["hi_px"] < bot)
                px = np.sort(pv["hi_px"][sel])
                reason = len(px) >= 2 and bool((np.diff(px) / px[1:] < p.get("eq_tol", 0.0008)).any())
        if p.get("need_reason", True) and not reason:
            continue
        htr, hs, hw, _ = ctx.htf(tA)
        if p.get("ctx", "htf_or_disc") == "htf":
            if htr != side:
                continue
        elif p.get("ctx") == "htf_or_disc":
            eq, lo, hi = ctx.htf_eq(tA)
            if htr != side and not ((side == 1 and legx < eq) or (side == -1 and legx > eq)):
                continue
        buf = p.get("buf", 0.0002)
        lim = top if side == 1 else bot
        stop = bot * (1 - buf) if side == 1 else top * (1 + buf)
        out.append(_sig(setup="G", t=tA, side=side, kind="lmt", lim=lim, stop=stop, tp1=NAN, final=NAN,
                        exp=tA + exp_bars * MM, cancel=stop, tp_from=int(legx_t),
                        need_ffb=p.get("need_ffb", False), counter=(htr != side),
                        minrr=p.get("minrr", 2.0), entry_ref=lim))
    return out


# =============================================================== Model C (S2D / D2S)
def model_c(ctx, p):
    out = []
    M = ctx.M; tf = M["tf"]; ob = M["ob"]; d1 = ctx.d1
    ob5 = ctx.F5["ob"]
    n = len(tf["c"])
    R, W = p.get("react", 8), p.get("win", 32)
    for z in range(len(ob["side"])):
        s_z = ob["side"][z]
        side = -s_z  # tapped supply (-1) -> long flip (S2D)
        top, bot, j = ob["top"][z], ob["bot"][z], ob["touch"][z]
        if j >= n - 2 or ob["inval"][z] < j:
            continue
        prior = tf["l"][max(0, j - 20):j].min() if side == 1 else tf["h"][max(0, j - 20):j].max()
        # reaction: close back below supply bottom (long case) within R bars
        seg_c = tf["c"][j:j + R]
        react = np.nonzero((seg_c < bot) if side == 1 else (seg_c > top))[0]
        if not len(react):
            continue
        # break of the zone (close beyond far edge) within W bars after touch
        seg_c2 = tf["c"][j:j + W]
        brk = np.nonzero((seg_c2 > top) if side == 1 else (seg_c2 < bot))[0]
        brk = brk[brk > react[0]]
        if not len(brk):
            continue
        b = j + brk[0]
        lows = tf["l"][j:b + 1] if side == 1 else tf["h"][j:b + 1]
        rl_k = j + (int(np.argmin(lows)) if side == 1 else int(np.argmax(lows)))
        rl = tf["l"][rl_k] if side == 1 else tf["h"][rl_k]
        if (side == 1 and rl < prior) or (side == -1 and rl > prior):
            continue  # made a new LL/HH -> not a failure to continue
        tA = int((b + 1) * MM)
        # flip zone: earliest 5m OB (this side) formed in the push after the reaction extreme
        cand = (ob5["side"] == side) & (ob5["org"] * GM >= rl_k * MM) & (ob5["conf_t"] <= tA) & (ob5["touch_t"] >= tA)
        idx = np.nonzero(cand)[0]
        if not len(idx):
            continue
        f = idx[0]
        ftop, fbot = ob5["top"][f], ob5["bot"][f]
        buf = p.get("buf", 0.0002)
        lim = ftop if side == 1 else fbot
        stop = fbot * (1 - buf) if side == 1 else ftop * (1 + buf)
        tgt = ctx.next_opposing(tA, side, max(top, lim) if side == 1 else min(bot, lim))
        if not np.isfinite(tgt):
            continue
        rr = side * (tgt - lim) / (side * (lim - stop))
        if rr < p.get("minrr", 2.0):
            continue
        htr = ctx.htf(tA)[0]
        out.append(_sig(setup="C", t=tA, side=side, kind="lmt", lim=lim, stop=stop, tp1=lim + 0.5 * (tgt - lim),
                        final=tgt, exp=tA + p.get("exp", 48) * MM, cancel=stop, counter=(htr != side),
                        minrr=p.get("minrr", 2.0), entry_ref=lim))
    return out


# =============================================================== Range models D / F / PO3
def _range_dev_signals(ctx, p, name, accept):
    out = []
    M = ctx.M; rng = M["rng"]; tf = M["tf"]; d1 = ctx.d1
    flips = ltf_flip_times(ctx, True)
    pv = M["piv"]
    N = p.get("win", 8)
    for ev in rng["ev"]:
        i, kind, s, lo, hi, start, ext, bars, taps = ev
        if kind != "dev" or not accept(ev, ctx, p):
            continue
        side = -s
        H = hi - lo; eq = 0.5 * (lo + hi)
        t0 = (i + 1) * MM
        poc, vah, val = E.volume_profile(d1, start * MM, t0)
        if not np.isfinite(poc):
            continue
        if p.get("va_only", False):
            if (side == 1 and ext > val) or (side == -1 and ext < vah):
                continue
        t1 = min((i + 1 + N) * MM, len(d1["c"]))
        arr = flips[side]
        j = np.searchsorted(arr, (i - bars) * MM + 1)  # flip after the sweep began; entry no earlier than t0
        if j >= len(arr) or arr[j] >= t1:
            continue
        t = int(max(arr[j], t0))
        entry = d1["c"][t - 1]
        if (side == 1 and entry >= eq) or (side == -1 and entry <= eq):
            continue  # no longs in premium / shorts in discount
        seg = d1["l"][(i - max(bars, 0)) * MM - MM:t] if side == 1 else d1["h"][(i - max(bars, 0)) * MM - MM:t]
        x = seg.min() if side == 1 else seg.max()
        x = min(x, ext) if side == 1 else max(x, ext)
        buf = p.get("buf", 0.0002)
        stop = x * (1 - buf) if side == 1 else x * (1 + buf)
        final = hi if side == 1 else lo
        tp1 = poc if side * (poc - entry) > 0 else eq
        tp2 = vah if side == 1 else val
        if side * (tp2 - tp1) <= 0 or side * (final - tp2) <= 0:
            tp2 = NAN
        # 5.6 gate: opposite edge only if MTF structure agrees, else EQ
        mtr = ctx.mtf(t)[0]
        if p.get("gate", True) and mtr != side:
            final = eq if side * (eq - entry) > 0 else tp1
            tp1 = min(tp1, final) if side == 1 else max(tp1, final)
            tp2 = NAN
        if side * (tp1 - entry) <= 0:
            continue
        htr = ctx.htf(t)[0]
        out.append(_sig(setup=name, t=t, side=side, stop=stop, tp1=tp1, tp2=tp2, final=final,
                        counter=False, minrr=p.get("minrr", 2.0), entry_ref=entry))
    return out


def model_d(ctx, p):
    acc = lambda ev, ctx, p: ev[7] <= p.get("max_out", 3) and ev[8] >= p.get("min_taps", 1)
    return _range_dev_signals(ctx, p, "D" if p.get("min_taps", 1) < 2 else "F", acc)


def model_f(ctx, p):
    q = dict(p); q["min_taps"] = max(2, p.get("min_taps", 2))
    acc = lambda ev, ctx, p: ev[7] <= p.get("max_out", 3) and ev[8] >= q["min_taps"]
    return _range_dev_signals(ctx, q, "F", acc)


def model_po3(ctx, p):
    M = ctx.M; pv = M["piv"]

    def acc(ev, ctx, p):
        i, kind, s, lo, hi, start, ext, bars, taps = ev
        if bars < p.get("min_out", 2):
            return False
        # liquidity left inside the range: >=2 untaken lower highs (long) / higher lows (short)
        H = hi - lo
        if s == -1:  # broke below -> long, look for lower highs inside
            sel = (pv["hi_conf"] <= i) & (pv["hi_i"] >= start) & (pv["hi_px"] < hi - 0.15 * H)
            px = pv["hi_px"][sel][-4:]
        else:
            sel = (pv["lo_conf"] <= i) & (pv["lo_i"] >= start) & (pv["lo_px"] > lo + 0.15 * H)
            px = -pv["lo_px"][sel][-4:]
        return len(px) >= 2 and bool((np.diff(px) < 0).sum() >= 1)
    q = dict(p); q.setdefault("win", 16); q["gate"] = p.get("gate", False)
    return _range_dev_signals(ctx, q, "PO3", acc)


# =============================================================== Model E (range-break pullback)
def model_e(ctx, p):
    out = []
    M = ctx.M; rng = M["rng"]; tf = M["tf"]; d1 = ctx.d1
    flips = ltf_flip_times(ctx, True)
    stL = ctx.L["st"]
    win = p.get("win", 96)
    for (i, kind, s, lo, hi, start, ext, bars, taps) in rng["ev"]:
        if kind != "brk":
            continue
        H = hi - lo
        poc, vah, val = E.volume_profile(d1, start * MM, (i - bars) * MM)
        if not np.isfinite(poc):
            continue
        near = vah if s == 1 else val
        n15 = len(tf["c"])
        kend = min(i + 1 + win, n15)
        lows = tf["l"][i + 1:kend] if s == 1 else tf["h"][i + 1:kend]
        into = np.nonzero((lows <= near) if s == 1 else (lows >= near))[0]
        if not len(into):
            continue
        kt = i + 1 + into[0]
        seg1 = d1["l"][kt * MM:(kt + 1) * MM] if s == 1 else d1["h"][kt * MM:(kt + 1) * MM]
        j1 = kt * MM + int(np.nonzero((seg1 <= near) if s == 1 else (seg1 >= near))[0][0])
        cl = tf["c"][kt:kend]
        bad = np.nonzero((cl < poc) if s == 1 else (cl > poc))[0]
        tend = (kt + bad[0] + 1) * MM if len(bad) else kend * MM
        arr = flips[s]
        j = np.searchsorted(arr, j1 + 1)
        if j >= len(arr) or arr[j] >= tend:
            continue
        t = int(arr[j])
        entry = d1["c"][t - 1]
        seg = d1["l"][kt * MM:t] if s == 1 else d1["h"][kt * MM:t]
        x = seg.min() if s == 1 else seg.max()
        x = min(x, poc) if s == 1 else max(x, poc)
        buf = p.get("buf", 0.0002)
        stop = x * (1 - buf) if s == 1 else x * (1 + buf)
        seg2 = d1["h"][(i + 1) * MM:t] if s == 1 else d1["l"][(i + 1) * MM:t]
        tp1 = seg2.max() if s == 1 else seg2.min()
        final = (hi + H) if s == 1 else (lo - H)
        if s * (tp1 - entry) <= 0 or s * (entry - stop) <= 0:
            continue
        if s * (final - tp1) < 0:
            final = tp1
        out.append(_sig(setup="E", t=t, side=s, stop=stop, tp1=tp1, final=final,
                        minrr=p.get("minrr", 2.0), entry_ref=entry))
    return out


MODELS = dict(A=model_a, RIMC=model_rimc, B=model_b, G=model_g, C=model_c, D=model_d, F=model_f, PO3=model_po3, E=model_e)


def apply_filters(ctx, sigs, f):
    """Filters. f: dict(pd, ret, overhead, cap_counter)."""
    keep = []
    for s in sigs:
        t, side = s["t"], s["side"]
        e = s["lim"] if s["kind"] == "lmt" else s["entry_ref"]
        if f.get("pd") and s["setup"] in ("A", "B", "Br", "G", "C", "RIMC", "E"):
            eq, lo, hi = ctx.htf_eq(t)
            if np.isfinite(eq) and ((side == 1 and e > eq) or (side == -1 and e < eq)):
                continue
        if f.get("ret") and s["kind"] == "mkt" and ctx.aggressive_return(t, side):
            continue
        if f.get("overhead") and ctx.overhead(t, side, e, s["stop"], f.get("ovr_r", 1.0)):
            continue
        if f.get("cap_counter", True) and s.get("counter") and np.isfinite(s["final"]) and np.isfinite(s["tp1"]):
            s = dict(s); s["final"] = s["tp1"]; s["tp2"] = NAN
        keep.append(s)
    return keep
