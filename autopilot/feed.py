"""Public BTC candle feeds reachable from the user's Mac (no keys). Binance USD-M BTCUSDT is the default:
it is the exact series the backtest ran on. OKX BTC-USDT-SWAP is the fallback (prices differ by a few dollars,
so signals can differ slightly from the backtest). Lighter's own candles are not used."""
from __future__ import annotations
import json, time, urllib.parse, urllib.request
import numpy as np

UA = {"User-Agent": "degen-desk-autopilot/1.0"}
H4 = 240 * 60_000
M1 = 60_000


def _get(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read())


class BinanceFeed:
    name = "binance"
    BASE = "https://fapi.binance.com/fapi/v1/"

    def klines(self, interval, start_ms, end_ms, now_ms):
        """Closed klines with open time in [start_ms, end_ms)."""
        rows, cur = [], start_ms
        step = M1 if interval == "1m" else H4
        while cur < end_ms:
            q = urllib.parse.urlencode(dict(symbol="BTCUSDT", interval=interval, startTime=cur, endTime=end_ms - 1, limit=1500))
            d = _get(self.BASE + "klines?" + q)
            if not d:
                break
            for k in d:
                if int(k[6]) < now_ms:      # close time passed -> closed bar
                    rows.append((int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
            nxt = int(d[-1][0]) + step
            if nxt <= cur or len(d) < 1500:
                break
            cur = nxt
            time.sleep(0.15)
        return rows

    def last_price(self):
        return float(_get(self.BASE + "ticker/price?symbol=BTCUSDT")["price"])


class OKXFeed:
    name = "okx"
    BASE = "https://www.okx.com/api/v5/market/"

    def klines(self, interval, start_ms, end_ms, now_ms):
        bar = "1m" if interval == "1m" else "4H"   # OKX 4H candles are UTC+8 aligned = also 4h-aligned in UTC
        rows, after = {}, end_ms
        while after > start_ms:
            q = urllib.parse.urlencode(dict(instId="BTC-USDT-SWAP", bar=bar, after=after, limit=100))
            d = _get(self.BASE + "history-candles?" + q).get("data", [])
            if not d:
                break
            for k in d:
                t = int(k[0])
                if start_ms <= t < end_ms and k[8] == "1":
                    rows[t] = (t, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[6]))
            oldest = min(int(k[0]) for k in d)
            if oldest >= after:
                break
            after = oldest
            time.sleep(0.11)
        return [rows[t] for t in sorted(rows)]

    def last_price(self):
        return float(_get(self.BASE + "ticker?instId=BTC-USDT-SWAP")["data"][0]["last"])


def pick_feed(pref="binance"):
    order = [BinanceFeed(), OKXFeed()] if pref == "binance" else [OKXFeed(), BinanceFeed()]
    errs = {}
    for f in order:
        try:
            f.last_price()
            return f, errs
        except Exception as e:
            errs[f.name] = str(e)[:160]
    return None, errs


class CandleStore:
    """Closed 1m bars for the last `keep_days` + the 4h history since 2022-01-01 (4h kline bootstrap, then
    every 4h period covered by 1m bars is re-derived from the 1m bars, the way the backtest built it)."""

    def __init__(self, feed, anchor_ms, keep_days=40, window_days=30, cache_path=None):
        self.feed, self.anchor, self.keep, self.wdays = feed, anchor_ms, keep_days, window_days
        self.m1 = {}      # ts -> (o,h,l,c,v)
        self.h4 = {}      # ts -> (o,h,l,c)
        self.cache_path = cache_path
        self.gaps_filled = 0

    def _load_cache(self):
        if not self.cache_path:
            return
        try:
            z = np.load(self.cache_path)
            if str(z["src"]) != self.feed.name:
                return
            for r in z["m1"]:
                self.m1[int(r[0])] = tuple(r[1:6])
            for r in z["h4"]:
                self.h4[int(r[0])] = tuple(r[1:5])
        except Exception:
            pass

    def save(self):
        if not self.cache_path:
            return
        m1 = np.array([(t, *self.m1[t]) for t in sorted(self.m1)]) if self.m1 else np.zeros((0, 6))
        h4 = np.array([(t, *self.h4[t]) for t in sorted(self.h4)]) if self.h4 else np.zeros((0, 5))
        tmp = str(self.cache_path) + ".tmp.npz"
        np.savez(tmp, m1=m1, h4=h4, src=self.feed.name)
        import os; os.replace(tmp, self.cache_path)

    def bootstrap(self, now_ms):
        self._load_cache()
        start1 = (now_ms - self.keep * 86_400_000) // H4 * H4
        need = range(self.anchor, now_ms // H4 * H4 - H4, H4)
        first_missing = next((t for t in need if t not in self.h4), None)
        if first_missing is not None:
            for r in self.feed.klines("4h", first_missing, now_ms, now_ms):
                self.h4[r[0]] = r[1:5]
        last1 = max(self.m1) if self.m1 else start1 - M1
        self.update(now_ms, since=max(start1, last1 + M1))

    def update(self, now_ms, since=None):
        last = max(self.m1) if self.m1 else None
        since = since if since is not None else (last + M1 if last else now_ms - 3 * M1)
        cur_open = now_ms // M1 * M1
        if since < cur_open:
            for r in self.feed.klines("1m", since, cur_open, now_ms):
                self.m1[r[0]] = r[1:6]
        # prune + forward-fill gaps (flat bars, zero volume) so the series stays contiguous like the backtest data
        lo = (now_ms - self.keep * 86_400_000) // H4 * H4
        for t in [t for t in self.m1 if t < lo]:
            del self.m1[t]
        if self.m1:
            ts = sorted(self.m1)
            t = ts[0]
            while t < ts[-1]:
                if t not in self.m1:
                    pc = self.m1[t - M1][3]
                    self.m1[t] = (pc, pc, pc, pc, 0.0); self.gaps_filled += 1
                t += M1
        # 4h bars fully covered by 1m bars are rebuilt from the 1m bars
        if self.m1:
            ts = sorted(self.m1); first = -(-ts[0] // H4) * H4
            t4 = first
            while t4 + H4 - M1 <= ts[-1]:
                b = [self.m1[t4 + k * M1] for k in range(240)]
                self.h4[t4] = (b[0][0], max(x[1] for x in b), min(x[2] for x in b), b[-1][3])
                t4 += H4

    def last_ts(self):
        return max(self.m1) if self.m1 else None

    def window(self):
        """(1m window dict starting on a 4h boundary ~window_days back, 4h prefix dict before it)."""
        last = max(self.m1)
        start = -(-(last + M1 - self.wdays * 86_400_000) // H4) * H4
        start = max(start, -(-min(self.m1) // H4) * H4)
        ts = np.arange(start, last + M1, M1, dtype=np.int64)
        arr = np.array([self.m1[int(t)] for t in ts])
        w = dict(ts=ts, o=arr[:, 0], h=arr[:, 1], l=arr[:, 2], c=arr[:, 3], v=arr[:, 4])
        pts = np.arange(self.anchor, start, H4, dtype=np.int64)
        missing = [int(t) for t in pts if int(t) not in self.h4]
        if missing:
            raise RuntimeError(f"4h history has {len(missing)} missing bars (first {missing[0]}); refetch")
        p = np.array([self.h4[int(t)] for t in pts]) if len(pts) else np.zeros((0, 4))
        pre = dict(ts=pts, o=p[:, 0], h=p[:, 1], l=p[:, 2], c=p[:, 3]) if len(pts) else None
        return w, pre
