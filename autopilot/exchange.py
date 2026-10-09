"""Exchange adapters with one interface:
  account() -> {"equity": float, "position": None | {"side": +1/-1, "size": float, "entry": float}}
  active_orders() -> list of {"kind": entry|stop|tp|close|other, "reduce_only", "price", "trigger", "order_index"} | None
  book() -> (bid, ask)
  set_leverage(lev) ; open_group(...) ; cancel_all() ; close_position(pos) ; place_stop(pos, trigger, worst)
PaperExchange: candle-driven simulator with the backtest's fill rules (sim.py). Used for --dry-run and tests.
LighterExchange: live. Reads are public REST; sends reuse desk_lighter.py's SDK path (official agent kit,
vendored SDK, OTOCO entry + reduce-only stop + take-profit in ONE grouped tx). The API key comes only from the
environment the run.sh wrapper fills from the macOS Keychain; it is never printed or logged.
"""
from __future__ import annotations
import asyncio, json, math, os, secrets, sys, time, urllib.parse, urllib.request
from pathlib import Path

THRU = 0.0001
SECRET_ENV = ("LIGHTER_API_PRIVATE_KEY", "LIGHTER_ETH_PRIVATE_KEY")


def redact(s):
    s = str(s)
    for n in SECRET_ENV:
        v = os.environ.get(n)
        if v and len(v) > 8:
            s = s.replace(v, "[REDACTED]").replace(v.removeprefix("0x"), "[REDACTED]")
    return s


def coi():
    return secrets.randbelow(2 ** 47 - 1) + 1


class Meta:
    """BTC perp on Lighter (read live in LighterExchange; these are the Oct 2026 values)."""
    def __init__(self, market_id=1, sd=5, pd=1, min_base=0.00007, min_quote=10.0, max_leverage=50):
        self.market_id, self.sd, self.pd, self.min_base, self.min_quote, self.max_leverage = market_id, sd, pd, min_base, min_quote, max_leverage

    def floor_size(self, x):
        return math.floor(x * 10 ** self.sd + 1e-9) / 10 ** self.sd

    def px(self, x, mode="near"):
        f = x * 10 ** self.pd
        i = math.ceil(f - 1e-9) if mode == "up" else math.floor(f + 1e-9) if mode == "down" else round(f)
        return i / 10 ** self.pd


# ============================================================================ paper
class PaperExchange:
    """Fills on CLOSED 1m bars exactly like course_engine/sim.py:
    market (IOC) entry at the next bar open +/- slip; resting limit fills only when traded THROUGH by 1 bp
    (at min(limit, open)); stop checked before TP; stop fills at trigger (or the open if gapped) - slip;
    TP limit fills when traded through by 1 bp; no TP on the limit-fill bar; close-at-market at next open - slip."""
    live = False

    def __init__(self, equity=1000.0, slip_bps=2.0, meta=None):
        self.cash = float(equity); self.slip = slip_bps * 1e-4
        self.meta = meta or Meta()
        self.pos = None            # dict(side,size,entry)
        self.orders = []           # pending dicts
        self.last = None           # last bar close
        self.fills = []
        self.lev = None

    # --- interface
    def account(self):
        upnl = 0.0
        if self.pos and self.last:
            upnl = self.pos["side"] * self.pos["size"] * (self.last - self.pos["entry"])
        return {"equity": self.cash + upnl, "position": dict(self.pos) if self.pos else None}

    def active_orders(self):
        out = []
        for o in self.orders:
            if o["kind"] in ("stop", "tp") and not o.get("active"):
                continue
            out.append({"kind": o["kind"], "reduce_only": o["kind"] in ("stop", "tp", "close"), "price": o.get("price"),
                        "trigger": o.get("trigger"), "order_index": id(o)})
        return out

    def book(self):
        return (self.last, self.last)

    def set_leverage(self, lev):
        self.lev = lev
        return {"ok": True}

    def open_group(self, side, size, tif, price, stop_trigger, stop_worst, tp, ids=None):
        if self.pos or any(o["kind"] == "entry" for o in self.orders):
            return {"ok": False, "error": "paper: position or entry already open"}
        g = coi()
        self.orders.append(dict(kind="entry", side=side, size=size, tif=tif, price=price, group=g))
        self.orders.append(dict(kind="stop", side=-side, trigger=stop_trigger, worst=stop_worst, group=g, active=False))
        if tp is not None:
            self.orders.append(dict(kind="tp", side=-side, trigger=tp, price=tp, group=g, active=False))
        return {"ok": True, "status": "accepted", "tx_hashes": ["paper"]}

    def cancel_all(self):
        self.orders = [o for o in self.orders if o["kind"] == "close"]
        return {"ok": True}

    def close_position(self, pos=None, immediate=False):
        if self.pos:
            if immediate and self.last:      # kill switch in dry-run: flatten at the last price - slip
                self._exit(self.last * (1 - self.pos["side"] * self.slip), "close", None)
            else:
                self.orders.append(dict(kind="close", side=-self.pos["side"]))
        return {"ok": True}

    def place_stop(self, pos, trigger, worst):
        self.orders.append(dict(kind="stop", side=-pos["side"], trigger=trigger, worst=worst, group=None, active=True))
        return {"ok": True}

    def place_tp(self, pos, price):
        self.orders.append(dict(kind="tp", side=-pos["side"], trigger=price, price=price, group=None, active=True))
        return {"ok": True}

    # --- simulation
    def _exit(self, px, reason, ts):
        p = self.pos
        pnl = p["side"] * p["size"] * (px - p["entry"])
        self.cash += pnl
        self.fills.append(dict(ts=ts, kind="exit", reason=reason, px=px, pnl=pnl, side=p["side"], size=p["size"]))
        self.pos = None
        self.orders = [o for o in self.orders if o["kind"] not in ("stop", "tp", "close")]

    def on_bar(self, ts, o, h, l, c):
        s = self.slip
        fill_bar_limit = False; mkt_bar = False
        # 1) pending market-close / entry orders execute at this bar's open
        for od in [x for x in self.orders if x["kind"] == "close"]:
            self.orders.remove(od)
            if self.pos:
                self._exit(o * (1 - self.pos["side"] * s), "close", ts)
        for od in [x for x in self.orders if x["kind"] == "entry"]:
            side = od["side"]
            if od["tif"] == "ioc":
                px = o * (1 + side * s)
                if (side == 1 and px <= od["price"]) or (side == -1 and px >= od["price"]):
                    self._fill_entry(od, px, ts); mkt_bar = True
                else:
                    self._drop_group(od["group"])
            else:
                lim = od["price"]
                if (side == 1 and l < lim * (1 - THRU)) or (side == -1 and h > lim * (1 + THRU)):
                    px = min(lim, o) if side == 1 else max(lim, o)
                    self._fill_entry(od, px, ts); fill_bar_limit = True
        # 2) protective orders: stop first, then TP (not on a limit-fill bar)
        if self.pos:
            side = self.pos["side"]
            for od in [x for x in self.orders if x["kind"] == "stop" and x.get("active")]:
                st = od["trigger"]
                if (side == 1 and l <= st) or (side == -1 and h >= st):
                    gap = (side == 1 and o < st) or (side == -1 and o > st)
                    px = (o if gap else st) * (1 - side * s)
                    self._exit(px, "sl", ts)
                    break
        if self.pos and not fill_bar_limit:
            side = self.pos["side"]
            for od in [x for x in self.orders if x["kind"] == "tp" and x.get("active")]:
                tp = od["trigger"]
                if (side == 1 and h > tp * (1 + THRU)) or (side == -1 and l < tp * (1 - THRU)):
                    self._exit(tp, "tp", ts)
                    break
        self.last = c

    def _fill_entry(self, od, px, ts):
        self.orders.remove(od)
        self.pos = dict(side=od["side"], size=od["size"], entry=px, ts=ts)
        for x in self.orders:
            if x.get("group") == od["group"]:
                x["active"] = True
        self.fills.append(dict(ts=ts, kind="entry", px=px, side=od["side"], size=od["size"]))

    def _drop_group(self, g):
        self.orders = [x for x in self.orders if x.get("group") != g]


# ============================================================================ live
class LighterExchange:
    live = True
    HOST = os.environ.get("LIGHTER_HOST", "https://mainnet.zklighter.elliot.ai").rstrip("/")

    def __init__(self, account_index, api_key_index, kit_dir="~/.agents/skills/lighter-agent-kit", symbol="BTC", allow_send=False):
        self.acct, self.kidx = int(account_index), int(api_key_index)
        self.kit = Path(os.path.expanduser(kit_dir))
        self.allow_send = allow_send          # False in --dry-run: every send raises before signing
        self.loop = asyncio.new_event_loop()
        self._lighter = None; self._client = None; self._client_t = 0
        self.meta = self._load_meta(symbol)

    # --- public reads (keyless)
    def _api(self, path, **params):
        url = f"{self.HOST}/api/v1/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "degen-desk-autopilot"}), timeout=20) as r:
            return json.loads(r.read())

    def _load_meta(self, sym):
        ob = next(m for m in self._api("orderBooks")["order_books"] if m.get("symbol") == sym and m.get("market_type") == "perp")
        det = (self._api("orderBookDetails", market_id=ob["market_id"]).get("order_book_details") or [{}])[0]
        if ob.get("status") != "active" or det.get("is_frozen"):
            raise RuntimeError(f"{sym} market not active")
        imf = det.get("min_initial_margin_fraction") or 10000
        return Meta(int(ob["market_id"]), int(ob["supported_size_decimals"]), int(ob["supported_price_decimals"]),
                    float(ob["min_base_amount"]), float(ob["min_quote_amount"]), int(10000 // int(imf)))

    def account(self):
        a = (self._api("account", by="index", value=str(self.acct)).get("accounts") or [None])[0]
        if not a:
            raise RuntimeError("account not found")
        eq = 0.0
        for k in ("total_asset_value", "collateral"):
            try:
                v = float(a.get(k) or 0)
                if v > 0:
                    eq = v; break
            except ValueError:
                pass
        pos = None
        for p in a.get("positions", []):
            if int(p.get("market_id", -1)) == self.meta.market_id and float(p.get("position") or 0) != 0:
                pos = {"side": 1 if int(p["sign"]) == 1 else -1, "size": abs(float(p["position"])),
                       "entry": float(p.get("avg_entry_price") or 0), "upnl": float(p.get("unrealized_pnl") or 0),
                       "liq": p.get("liquidation_price")}
        other = [p.get("symbol") for p in a.get("positions", []) if float(p.get("position") or 0) != 0
                 and int(p.get("market_id", -1)) != self.meta.market_id]
        return {"equity": eq, "position": pos, "other_positions": other,
                "pending_order_count": a.get("pending_order_count")}

    def book(self):
        d = self._api("orderBookOrders", market_id=self.meta.market_id, limit=5)
        asks = [float(x["price"]) for x in d.get("asks", [])]; bids = [float(x["price"]) for x in d.get("bids", [])]
        if not asks or not bids:
            raise RuntimeError("empty order book")
        return max(bids), min(asks)

    # --- SDK (same loader as desk_lighter.py)
    def _sdk(self):
        if self._lighter is None:
            sys.path.insert(0, str(self.kit / "scripts"))
            from _sdk import ensure_lighter
            ensure_lighter()
            import lighter
            from lighter.signer_client import CreateOrderTxReq
            self._lighter = (lighter, CreateOrderTxReq)
        return self._lighter

    def _key(self):
        k = os.environ.get("LIGHTER_API_PRIVATE_KEY", "").strip()
        if not k:
            raise RuntimeError("no API key in the environment (run through run.sh --live)")
        return k

    def _new_client(self):
        lighter, _ = self._sdk()
        c = lighter.SignerClient(url=self.HOST, account_index=self.acct, api_private_keys={self.kidx: self._key()})
        rc = getattr(getattr(c.api_client, "rest_client", None), "retry_client", "missing")
        if rc not in (None, "missing"):
            raise RuntimeError("SDK HTTP retries are enabled; refusing to send")
        err = c.check_client()
        if err:
            raise RuntimeError("API key check failed: " + redact(err)[:160])
        return c

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def _new_client_sync(self):
        # the SDK's SignerClient needs a running event loop when constructed
        async def mk():
            return self._new_client()
        return self._run(mk())

    def keycheck(self):
        c = self._new_client_sync(); self._run(c.close()); return {"ok": True}

    def active_orders(self):
        """Needs an auth token signed with the key (live only). None if unavailable."""
        if not os.environ.get("LIGHTER_API_PRIVATE_KEY"):
            return None
        lighter, _ = self._sdk()
        if self._client is None or time.time() - self._client_t > 1800:
            if self._client is not None:
                try: self._run(self._client.close())
                except Exception: pass
            self._client = self._new_client_sync(); self._client_t = time.time()
        auth, err = self._client.create_auth_token_with_expiry(600)
        if err:
            raise RuntimeError("auth token: " + redact(err)[:120])
        api = lighter.OrderApi(self._client.api_client)
        if not auth:
            raise RuntimeError("auth token: empty")
        r = self._run(api.account_active_orders(authorization=auth, auth=auth, account_index=self.acct, market_id=self.meta.market_id))
        out = []
        for o in (r.orders or []):
            t = o.type
            kind = ("stop" if t.startswith("stop-loss") else "tp" if t.startswith("take-profit")
                    else "entry" if (t == "limit" and not o.reduce_only) else "other")
            out.append({"kind": kind, "reduce_only": bool(o.reduce_only), "price": float(o.price or 0),
                        "trigger": float(o.trigger_price or 0), "order_index": o.order_index, "status": o.status,
                        "client_order_index": o.client_order_index})
        return out

    def _send(self, fn):
        if not self.allow_send:
            return {"ok": False, "error": "dry-run: sending is disabled (nothing signed)"}
        async def go():
            c = self._new_client()
            try:
                return await fn(c)
            finally:
                try: await c.close()
                except Exception: pass
        try:
            _, r, e = self._run(go())
        except Exception as ex:
            return {"ok": False, "error": redact(f"{type(ex).__name__}: {ex}")[:300]}
        if e or r is None or getattr(r, "code", 200) != 200:
            return {"ok": False, "error": redact(e or r)[:300]}
        return {"ok": True, "tx_hash": getattr(r, "tx_hash", None)}

    def set_leverage(self, lev, margin="cross"):
        m = self.meta.market_id
        async def f(c):
            mm = c.ISOLATED_MARGIN_MODE if margin == "isolated" else c.CROSS_MARGIN_MODE
            return await c.update_leverage(m, mm, int(lev))
        return self._send(f)

    def open_group(self, side, size, tif, price, stop_trigger, stop_worst, tp, ids=None):
        """Entry (IOC limit at a worst price = marketable, or GTT resting limit) + reduce-only TAKE_PROFIT_LIMIT +
        reduce-only STOP_LOSS, as one OTOCO grouped tx: the stop and TP go live the moment the entry fills."""
        M = self.meta
        ids = ids or {"entry": coi(), "stop": coi(), "tp": coi()}
        base = round(size * 10 ** M.sd); is_ask = 0 if side == 1 else 1
        p_i = round(price * 10 ** M.pd); st_i = round(stop_trigger * 10 ** M.pd); sw_i = round(stop_worst * 10 ** M.pd)
        tp_i = round(tp * 10 ** M.pd) if tp is not None else None
        async def f(c):
            _, Req = self._sdk()
            tif_c = c.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL if tif == "ioc" else c.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME
            orders = [Req(MarketIndex=M.market_id, ClientOrderIndex=ids["entry"], BaseAmount=base, Price=p_i, IsAsk=is_ask,
                          Type=c.ORDER_TYPE_LIMIT, TimeInForce=tif_c, ReduceOnly=0, TriggerPrice=0,
                          OrderExpiry=(0 if tif == "ioc" else -1))]
            if tp_i:
                orders.append(Req(MarketIndex=M.market_id, ClientOrderIndex=ids["tp"], BaseAmount=0, Price=tp_i, IsAsk=1 - is_ask,
                                  Type=c.ORDER_TYPE_TAKE_PROFIT_LIMIT, TimeInForce=c.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                                  ReduceOnly=1, TriggerPrice=tp_i, OrderExpiry=-1))
            orders.append(Req(MarketIndex=M.market_id, ClientOrderIndex=ids["stop"], BaseAmount=0, Price=sw_i, IsAsk=1 - is_ask,
                              Type=c.ORDER_TYPE_STOP_LOSS, TimeInForce=c.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                              ReduceOnly=1, TriggerPrice=st_i, OrderExpiry=-1))
            g = c.GROUPING_TYPE_ONE_TRIGGERS_A_ONE_CANCELS_THE_OTHER if tp_i else c.GROUPING_TYPE_ONE_TRIGGERS_THE_OTHER
            return await c.create_grouped_orders(grouping_type=g, orders=orders)
        r = self._send(f); r["client_order_ids"] = ids
        return r

    def cancel_all(self):
        m = self.meta.market_id
        async def f(c):
            return await c.cancel_all_orders(c.CANCEL_ALL_TIF_IMMEDIATE, 0, cancel_all_market_index=m)
        return self._send(f)

    def close_position(self, pos, slippage_pct=0.5, immediate=True):
        if not self.allow_send:
            return {"ok": False, "error": "dry-run: sending is disabled (nothing signed)"}
        M = self.meta; bid, ask = self.book()
        long_ = pos["side"] == 1
        worst = M.px(bid * (1 - slippage_pct / 100), "down") if long_ else M.px(ask * (1 + slippage_pct / 100), "up")
        base = round(pos["size"] * 10 ** M.sd); w_i = round(worst * 10 ** M.pd); cid = coi()
        async def f(c):
            return await c.create_order(M.market_id, cid, base, w_i, 1 if long_ else 0, c.ORDER_TYPE_MARKET,
                                        c.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL, reduce_only=True, order_expiry=c.DEFAULT_IOC_EXPIRY)
        return self._send(f)

    def place_stop(self, pos, trigger, worst):
        M = self.meta; base = round(pos["size"] * 10 ** M.sd); cid = coi()
        t_i = round(trigger * 10 ** M.pd); w_i = round(worst * 10 ** M.pd); is_ask = 1 if pos["side"] == 1 else 0
        async def f(c):
            return await c.create_order(M.market_id, cid, base, w_i, is_ask, c.ORDER_TYPE_STOP_LOSS,
                                        c.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL, reduce_only=True, trigger_price=t_i, order_expiry=-1)
        return self._send(f)

    def place_tp(self, pos, price):
        M = self.meta; base = round(pos["size"] * 10 ** M.sd); cid = coi()
        p_i = round(price * 10 ** M.pd); is_ask = 1 if pos["side"] == 1 else 0
        async def f(c):
            return await c.create_order(M.market_id, cid, base, p_i, is_ask, c.ORDER_TYPE_TAKE_PROFIT_LIMIT,
                                        c.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME, reduce_only=True, trigger_price=p_i, order_expiry=-1)
        return self._send(f)
