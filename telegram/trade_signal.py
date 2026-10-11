#!/usr/bin/env python3
"""Trade-signal cards for Telegram: a dark BTC candlestick chart (PNG) + a short HTML caption.

Named trade_signal.py (not signal.py) on purpose: a file called signal.py shadows Python's
stdlib `signal` module for every script in this folder (subprocess, asyncio, ... import it).

Usage
  python3 trade_signal.py --side long --entry 82590 --stop 82340 --tp 83115 \
      --size 0.00586 --notional 484 --leverage 3 --risk-pct 1 --risk-usd 3.88 \
      --setup "Discount long" --reason "..." --status NEW --order "buy limit" \
      --zone demand:82423:82599 --zone supply:83125:83289 \
      --note "Expires ~11:55 PM if unfilled" [--send | --dry-run]

  Status is one of NEW, FILLED, TP HIT, STOPPED, CANCELLED. For closes pass --exit and
  optionally --pnl-usd / --r-multiple. Without --send it only renders the PNG + caption.

Library use (same functions the Mac autopilot's notify.py mirrors):
  fetch_candles(), render_chart(...), build_caption(...)

Candles: OKX public API, BTC-USDT-SWAP (no key needed). Times on the
chart are in DD_TZ (default Asia/Dubai). Sending goes through tg.py, so the approved chat in config.json and
its guard rails apply; nothing else is ever targeted.
"""
import argparse
import os
import html
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "signals"
from zoneinfo import ZoneInfo
DUBAI = ZoneInfo(os.environ.get("DD_TZ", "Asia/Dubai"))   # chart timezone; set DD_TZ to change
TZL = os.environ.get("DD_TZ_LABEL") or os.environ.get("DD_TZ", "Asia/Dubai").split("/")[-1].replace("_", " ")
OKX = "https://www.okx.com/api/v5/market/candles?instId={inst}&bar={bar}&limit={limit}"
STATUSES = ("NEW", "FILLED", "TP HIT", "STOPPED", "CANCELLED")
DISCLAIMER = os.environ.get("SIGNAL_FOOTER", "Auto-traded by Degen Desk · Not financial advice")

BG, PANEL, GRID, TXT, MUTED = "#0e1117", "#131722", "#232838", "#d1d4dc", "#787b86"
UP, DOWN = "#26a69a", "#ef5350"
COL = {"entry": "#4c9aff", "stop": "#ef5350", "tp": "#26a69a", "exit": "#f5c542",
       "demand": "#26a69a", "supply": "#ef5350"}


# ------------------------------------------------------------------ data
def fetch_candles(inst="BTC-USDT-SWAP", bar="15m", limit=192, timeout=15):
    """Return [(datetime_utc, o, h, l, c), ...] oldest first (includes the forming candle)."""
    url = OKX.format(inst=inst, bar=bar, limit=min(int(limit), 300))
    req = urllib.request.Request(url, headers={"User-Agent": "degen-desk/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    if body.get("code") != "0" or not body.get("data"):
        raise RuntimeError(f"OKX candles error: {body.get('msg') or body.get('code')}")
    rows = [(datetime.fromtimestamp(int(d[0]) / 1000, timezone.utc),
             float(d[1]), float(d[2]), float(d[3]), float(d[4])) for d in body["data"]]
    return sorted(rows, key=lambda x: x[0])


# ------------------------------------------------------------------ formatting
def fmt_px(x):
    return f"{x:,.0f}" if abs(x) >= 1000 else f"{x:,.2f}"


def pct(a, b):
    return (b / a - 1) * 100


def rr(entry, stop, tp):
    risk = abs(entry - stop)
    return abs(tp - entry) / risk if risk else 0.0


def headline(side, status):
    long = side.lower() == "long"
    dot = "🟢" if long else "🔴"
    tag = {"NEW": "", "FILLED": " · ✅ FILLED", "TP HIT": " · 🎯 TP HIT", "STOPPED": " · 🛑 STOPPED",
           "CANCELLED": " · ⚪ CANCELLED"}[status]
    return f"{dot} BTC {'LONG' if long else 'SHORT'} — Lighter{tag}"


def build_caption(side, entry, stop, tp, status="NEW", size=None, notional=None, leverage=None,
                  risk_pct=None, risk_usd=None, setup=None, reason=None, order=None, note=None,
                  exit_px=None, pnl_usd=None, r_multiple=None):
    """Telegram-HTML caption (kept well under the 1024-char photo caption limit)."""
    e = html.escape
    status = status.upper()
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    lines = [f"<b>{e(headline(side, status))}</b>"]
    if status == "NEW" and order:
        lines.append(f"<i>{e(order)} · pending</i>")
    lines.append("")
    lines.append(f"Entry: <b>{fmt_px(entry)}</b>")
    lines.append(f"Stop: <b>{fmt_px(stop)}</b> ({pct(entry, stop):+.2f}%)".replace("(-", "(−"))
    lines.append(f"Target: <b>{fmt_px(tp)}</b> ({pct(entry, tp):+.2f}%)".replace("(-", "(−"))
    risk_bits = [f"R:R {rr(entry, stop, tp):.1f}"]
    if risk_pct is not None:
        risk_bits.append(f"risk ~{risk_pct:g}%" + (f" (${risk_usd:,.2f})" if risk_usd is not None else ""))
    lines.append(" · ".join(risk_bits))
    if size is not None:
        sz = f"Size: {size:g} BTC"
        extra = [x for x in ((f"~${notional:,.0f}" if notional else None),
                             (f"{leverage:g}x" if leverage else None)) if x]
        lines.append(sz + (f" ({', '.join(extra)})" if extra else ""))
    if status in ("TP HIT", "STOPPED", "CANCELLED") and (exit_px is not None or pnl_usd is not None):
        res = []
        if exit_px is not None:
            res.append(f"exit {fmt_px(exit_px)}")
        if pnl_usd is not None:
            res.append(f"{pnl_usd:+,.2f} USD")
        if r_multiple is not None:
            res.append(f"{r_multiple:+.2f}R")
        lines.append("Result: <b>" + e(" · ".join(res)) + "</b>")
    if setup or reason:
        lines.append("")
        if setup:
            lines.append(f"<b>Setup:</b> {e(setup)}")
        if reason:
            lines.append(e(reason))
    if note:
        lines.append(f"⏳ {e(note)}")
    lines.append("")
    lines.append(f"<i>{e(DISCLAIMER)}</i>")
    return "\n".join(lines)


# ------------------------------------------------------------------ chart
def render_chart(candles, side, entry, stop, tp, out_path, zones=(), status="NEW", exit_px=None,
                 title_bar="15m", inst_label="BTC-USDT perp (OKX feed)"):
    """Dark candlestick chart with entry/stop/TP lines, risk/reward box and optional zones.
    zones: iterable of (kind, low, high) with kind 'demand' or 'supply'."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    n = len(candles)
    fig, ax = plt.subplots(figsize=(12, 6.75), dpi=110)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(color=GRID, linewidth=0.6, alpha=0.8)

    w = 0.62
    for i, (_, o, h, l, c) in enumerate(candles):
        col = UP if c >= o else DOWN
        ax.vlines(i, l, h, color=col, linewidth=0.9, zorder=2)
        ax.add_patch(Rectangle((i - w / 2, min(o, c)), w, max(abs(c - o), 1e-9), facecolor=col,
                               edgecolor=col, linewidth=0.5, zorder=3))

    right = n + max(14, n // 7)          # empty space on the right for the position box + labels
    ax.set_xlim(-1, right + 6)

    lows = [x[3] for x in candles] + [stop, entry, tp]
    highs = [x[2] for x in candles] + [stop, entry, tp]
    for _, lo, hi in zones:
        lows.append(lo); highs.append(hi)
    pad = (max(highs) - min(lows)) * 0.06
    ax.set_ylim(min(lows) - pad, max(highs) + pad)

    for kind, lo, hi in zones:
        c = COL.get(kind, MUTED)
        ax.axhspan(lo, hi, color=c, alpha=0.13, zorder=1)
        ax.text(1, (lo + hi) / 2, f"{kind} {fmt_px(lo)}–{fmt_px(hi)}", color=c, fontsize=8.5, va="center",
                ha="left", zorder=8, bbox=dict(boxstyle="round,pad=0.2", facecolor=BG, edgecolor=c, alpha=0.9))

    # risk / reward box to the right of the last candle
    x0, x1 = n + 1, right
    ax.add_patch(Rectangle((x0, min(entry, tp)), x1 - x0, abs(tp - entry), facecolor=COL["tp"], alpha=0.22, zorder=1))
    ax.add_patch(Rectangle((x0, min(entry, stop)), x1 - x0, abs(entry - stop), facecolor=COL["stop"], alpha=0.22, zorder=1))

    levels = [("TP", tp, COL["tp"]), ("Entry", entry, COL["entry"]), ("Stop", stop, COL["stop"])]
    if exit_px is not None:
        tol = abs(tp - stop) * 0.03
        if abs(exit_px - tp) <= tol:
            levels[0] = ("TP hit", tp, COL["tp"])
        elif abs(exit_px - stop) <= tol:
            levels[2] = ("Stopped", stop, COL["stop"])
        else:
            levels.append(("Exit", exit_px, COL["exit"]))
    for name, y, c in levels:
        ax.axhline(y, color=c, linewidth=1.3, linestyle="-" if name == "Entry" else "--", zorder=4)
        ax.text(right + 5.5, y, f"{name} {fmt_px(y)}", color="white", fontsize=9, fontweight="bold",
                va="center", ha="right", zorder=7,
                bbox=dict(boxstyle="round,pad=0.25", facecolor=c, edgecolor="none"))

    last = candles[-1][4]
    ax.axhline(last, color=MUTED, linewidth=0.7, linestyle=":", zorder=4)
    ax.text(n + 0.5, last, f" last {fmt_px(last)}", color=TXT, fontsize=8.5, va="bottom", ha="left", zorder=7)

    # x ticks every 6h, Dubai time
    ticks, labels = [], []
    for i, (t, *_rest) in enumerate(candles):
        td = t.astimezone(DUBAI)
        if td.minute == 0 and td.hour % 6 == 0:
            ticks.append(i); labels.append(td.strftime("%a %H:%M"))
    ax.set_xticks(ticks); ax.set_xticklabels(labels)
    ax.yaxis.tick_right()
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    long = side.lower() == "long"
    ttl = f"BTC {'LONG' if long else 'SHORT'} · Lighter · {status.upper()}"
    fig.text(0.012, 0.955, ttl, color=UP if long else DOWN, fontsize=15, fontweight="bold", ha="left")
    stamp = datetime.now(DUBAI).strftime("%b %d %H:%M")
    fig.text(0.012, 0.915, f"{inst_label} · {title_bar} · R:R {rr(entry, stop, tp):.1f} · as of {stamp} {TZL}",
             color=MUTED, fontsize=9.5, ha="left")
    fig.text(0.988, 0.955, "Degen Desk", color=TXT, fontsize=12, fontweight="bold", ha="right", alpha=0.85)
    fig.text(0.988, 0.915, "Not financial advice", color=MUTED, fontsize=8.5, ha="right")
    fig.subplots_adjust(left=0.02, right=0.93, top=0.89, bottom=0.07)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=BG)
    plt.close(fig)
    return str(out_path)


# ------------------------------------------------------------------ CLI
def parse_zone(s):
    kind, lo, hi = s.split(":")
    lo, hi = float(lo), float(hi)
    return kind.lower(), min(lo, hi), max(lo, hi)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--side", required=True, choices=["long", "short"])
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--tp", type=float, required=True)
    p.add_argument("--status", default="NEW", type=str.upper, choices=STATUSES)
    p.add_argument("--size", type=float)
    p.add_argument("--notional", type=float)
    p.add_argument("--leverage", type=float)
    p.add_argument("--risk-pct", type=float)
    p.add_argument("--risk-usd", type=float)
    p.add_argument("--setup")
    p.add_argument("--reason")
    p.add_argument("--order", help='e.g. "buy limit" (shown on NEW)')
    p.add_argument("--note")
    p.add_argument("--exit", dest="exit_px", type=float)
    p.add_argument("--pnl-usd", type=float)
    p.add_argument("--r-multiple", type=float)
    p.add_argument("--zone", action="append", default=[], type=parse_zone, help="demand:LOW:HIGH or supply:LOW:HIGH")
    p.add_argument("--bars", type=int, default=192, help="15m candles to show (192 = 2 days)")
    p.add_argument("--out", help="PNG path (default signals/<time>_<side>_<status>.png)")
    p.add_argument("--send", action="store_true", help="post to the approved chat via tg.py")
    p.add_argument("--dry-run", action="store_true", help="render + show what would be sent")
    a = p.parse_args(argv)

    if a.side == "long" and not (a.stop < a.entry < a.tp):
        sys.exit("error: a long needs stop < entry < tp")
    if a.side == "short" and not (a.tp < a.entry < a.stop):
        sys.exit("error: a short needs tp < entry < stop")

    candles = fetch_candles(limit=a.bars)
    stamp = datetime.now(DUBAI).strftime("%Y%m%d_%H%M%S")
    out = a.out or OUT_DIR / f"{stamp}_btc_{a.side}_{a.status.replace(' ', '').lower()}.png"
    render_chart(candles, a.side, a.entry, a.stop, a.tp, out, zones=a.zone, status=a.status, exit_px=a.exit_px)
    cap = build_caption(a.side, a.entry, a.stop, a.tp, a.status, a.size, a.notional, a.leverage, a.risk_pct,
                        a.risk_usd, a.setup, a.reason, a.order, a.note, a.exit_px, a.pnl_usd, a.r_multiple)
    cap_path = Path(str(out)).with_suffix(".caption.html")
    cap_path.write_text(cap, encoding="utf-8")

    sys.path.insert(0, str(HERE))
    import tg
    print(f"chart: {out}\ncaption: {cap_path} ({tg.vlen(cap)}/{tg.CAPTION_LIMIT} visible chars, "
          f"well-formed={tg.well_formed(cap)})", file=sys.stderr)
    if not a.send:
        print(cap)
        return
    if a.dry_run:
        tg.main(["photo", "--file", str(out), "--caption-file", str(cap_path), "--require", "Not financial advice",
                 "--dry-run"])
        return
    tg.main(["photo", "--file", str(out), "--caption-file", str(cap_path), "--require", "Not financial advice"])


if __name__ == "__main__":
    main()
