"""Arcus (arcus.xyz) BTC-USD perp adapter with the Degen Desk autopilot exchange interface.

  account() -> {"equity", "free_collateral", "position": None | {"side","size","entry","upnl"}, "other_positions"}
  active_orders() -> [{"kind": entry|stop|tp|other, ...}] | None
  book() -> (bid, ask)      set_leverage(lev, margin)      open_group(...)      cancel_all()
  close_position(pos)       place_stop(pos, trigger, worst)  place_tp(pos, price)   dead_man(arm_seconds | None)

Auth: Ed25519 API key (public = ARCUS_API_KEY, private = ARCUS_SIGNING_KEY) registered to ARCUS_ADDRESS / subaccount
ARCUS_ACCOUNT_INDEX. Keys come only from the environment (systemd EnvironmentFile, chmod 600) and are never printed.
Orders: Scheme-1 typed canonical payload (op 1 plain, op 2 cancel, op 4 TPSL); cancelAllOrders / setLeverage /
scheduleCancel: Scheme-2 (timestamp + action + canonical JSON body).
Market entries: IOC limit at a worst price, then a position-level SL (+TP) pair (positionTpsl) the moment the fill
shows; if the stop cannot be placed the position is closed. Resting (G) entries: entryTpsl bundle (entry + bound SL/TP).
"""
from __future__ import annotations
import json, math, os, secrets, time, urllib.error, urllib.parse, urllib.request
from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP
from exchange import Meta

HOST = os.environ.get("ARCUS_HOST", "https://api.arcus.xyz").rstrip("/")
SECRET_ENV = ("ARCUS_SIGNING_KEY",)
GTT_US = 40 * 86400 * 1_000_000          # goodTilTime must be >= 1 month ahead
TIF = {"GTT": 0, "FOK": 1, "IOC": 2, "ALO": 3}


def redact(s):
    s = str(s)
    for n in SECRET_ENV:
        v = os.environ.get(n)
        if v and len(v) > 8:
            s = s.replace(v, "[REDACTED]")
    return s


class ArcusExchange:
    live = True

    def __init__(self, allow_send=False, market="BTC-USD"):
        self.allow_send = allow_send
        self.addr = os.environ["ARCUS_ADDRESS"].strip()
        self.addr_l = self.addr.lower()
        self.ai = int(os.environ.get("ARCUS_ACCOUNT_INDEX", "0"))
        self.pub = os.environ.get("ARCUS_API_KEY", "").strip().lower()
        self._sk = None
        self.market = market
        m = next(x for x in self._get("/v1/markets")["markets"] if x["marketDisplayName"] == market)
        if m["status"] != "ONLINE":
            raise RuntimeError(f"{market} not ONLINE")
        self.mid = int(m["marketId"])
        self.tick, self.step = Decimal(m["tickSize"]), Decimal(m["stepSize"])
        pd = max(0, -self.tick.normalize().as_tuple().exponent); sd = max(0, -self.step.normalize().as_tuple().exponent)
        self.meta = Meta(self.mid, sd, pd, float(m["minOrderSize"]), float(m["minOrderNotional"]),
                         int(round(1 / float(m["initialMarginFraction"]))))
        self.meta.tick = float(self.tick)
        self.dm_armed = False

    # ------------------------------------------------------------------ http
    def _req(self, method, path, body=None, headers=None, query=None):
        url = HOST + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        h = {"Content-Type": "application/json", "User-Agent": "degen-desk-arcus"}; h.update(headers or {})
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read(); return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"error": raw[:300].decode(errors="ignore")}

    def _get(self, path, **q):
        s, d = self._req("GET", path, query=q or None)
        if s != 200:
            raise RuntimeError(f"GET {path} -> {s} {str(d)[:200]}")
        return d

    # ------------------------------------------------------------------ signing
    def _key(self):
        if self._sk is None:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            k = os.environ.get("ARCUS_SIGNING_KEY", "").strip()
            if not k:
                raise RuntimeError("no ARCUS_SIGNING_KEY in the environment")
            k = k[2:] if k.lower().startswith("0x") else k
            self._sk = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(k))
            if self._sk.public_key().public_bytes_raw().hex() != self.pub:
                self._sk = None
                raise RuntimeError("ARCUS_SIGNING_KEY does not match ARCUS_API_KEY")
        return self._sk

    def _sign(self, msg: str) -> str:
        return self._key().sign(msg.encode()).hex()

    def _hdr(self, ts, sig):
        return {"X-API-Key": self.pub, "X-Timestamp": str(ts), "X-Signature": sig}

    def _ticks(self, price):
        n = Decimal(str(price)) / self.tick
        if n != n.to_integral_value():
            raise ValueError(f"price {price} not on tick {self.tick}")
        return int(n)

    def _steps(self, qty):
        n = Decimal(str(qty)) / self.step
        if n != n.to_integral_value():
            raise ValueError(f"qty {qty} not on step {self.step}")
        return int(n)

    def _pstr(self, x, mode="near"):
        r = {"up": ROUND_UP, "down": ROUND_DOWN}.get(mode, ROUND_HALF_UP)
        return str((Decimal(str(x)) / self.tick).to_integral_value(rounding=r) * self.tick)

    def _qstr(self, x):
        return str((Decimal(str(x)) / self.step).to_integral_value(rounding=ROUND_DOWN) * self.step)

    def _order(self, ts, side, otype, tif, qty, price, reduce=False, tpsl=None, stop_price=None, cid=None, pos_tpsl=False):
        """Build one order body + its Scheme-1 signature (op 1 plain, op 4 TPSL)."""
        g = int(time.time() * 1_000_000) + GTT_US
        q = "0" if pos_tpsl else self._qstr(qty)
        p = self._pstr(price)
        op = 4 if tpsl else 1
        payload = (f'{{"ad":"{self.addr_l}","ai":{self.ai},' + (f'"c":"{cid}",' if cid else "") +
                   f'"ct":{ts},"g":{g * 1000},"m":{self.mid},"op":{op},"p":{self._ticks(p)},"q":{self._steps(q)},'
                   f'"r":{1 if reduce else 0},"s":{0 if side == 1 else 1},"t":{TIF[tif]},"v":1}}')
        body = {"address": self.addr, "accountIndex": self.ai, "marketId": self.mid, "orderSide": "BUY" if side == 1 else "SELL",
                "orderType": otype, "quantity": q, "price": p, "timeInForce": tif, "goodTilTime": str(g), "timestamp": ts}
        if reduce: body["reduceOnly"] = True
        if cid: body["clientId"] = cid
        if tpsl:
            body["tpslType"] = tpsl; body["stopPrice"] = self._pstr(stop_price)
            if pos_tpsl: body["isPositionTPSL"] = True
        return body, self._sign(payload)

    def _guard(self):
        if not self.allow_send:
            return {"ok": False, "error": "dry-run: sending is disabled (nothing signed)"}
        return None

    def _post_order(self, body, sig, ts):
        s, d = self._req("POST", "/v1/placeOrder", body, self._hdr(ts, sig), {"address": self.addr})
        ok = s in (200, 202) and str(d.get("status", "")).upper() not in ("REJECTED", "ERROR")
        return {"ok": ok, "http": s, "resp": d, **({} if ok else {"error": redact(json.dumps(d))[:300]})}

    def _post_batch(self, orders, ts, grouping):
        bodies = []
        for b, sg in orders:
            b = dict(b); b["signature"] = sg; bodies.append(b)
        req = {"orders": bodies}
        if grouping: req["grouping"] = grouping
        s, d = self._req("POST", "/v1/batchPlaceOrders", req, self._hdr(ts, bodies[0]["signature"]), {"address": self.addr})
        rows = d.get("responses") or []
        bad = [r for r in rows if str(r.get("status", "")).upper() in ("ERROR", "REJECTED") or r.get("error")]
        ok = s in (200, 202) and rows and not bad
        if not ok and "POSITION_TPSL_ALREADY_EXISTS" in json.dumps(d) and grouping == "positionTpsl":
            return {"ok": True, "http": s, "resp": d, "note": "position TPSL already exists"}
        return {"ok": bool(ok), "http": s, "resp": d, **({} if ok else {"error": redact(json.dumps(d))[:400]})}

    def _legacy(self, action, body):
        ts = time.time_ns()
        msg = str(ts) + action + json.dumps(body, separators=(",", ":"), sort_keys=True)
        s, d = self._req("POST", f"/v1/{action}", body, self._hdr(ts, self._sign(msg)), {"address": self.addr})
        ok = s in (200, 202) and not (isinstance(d, dict) and d.get("error"))
        return {"ok": ok, "http": s, "resp": d, **({} if ok else {"error": redact(json.dumps(d))[:300]})}

    @staticmethod
    def cid(tag):
        return f"dd{tag}-{secrets.token_hex(6)}"

    # ------------------------------------------------------------------ reads
    def keycheck(self):
        self._key()
        ts = time.time_ns()
        s, d = self._req("GET", "/v1/affiliate/inviteCodes", headers=self._hdr(ts, self._sign(str(ts) + "inviteCodes")),
                         query={"address": self.addr})
        if s != 200:
            raise RuntimeError(f"Arcus key check failed: HTTP {s} {redact(d)[:120]}")
        keys = self._get("/v1/apiKeys", address=self.addr).get("apiKeys", [])
        k = next((x for x in keys if x.get("apiKey", "").lower() == self.pub and x.get("status") == "ACTIVE"), None)
        if not k:
            raise RuntimeError("API key not ACTIVE on this wallet")
        if k.get("accountIndex") not in (None, self.ai) and not k.get("allSubaccounts"):
            raise RuntimeError("API key is scoped to another subaccount")
        return {"ok": True, "valid_until_ms": k.get("validUntil")}

    def account(self):
        a = self._get("/v1/account", address=self.addr, accountIndex=self.ai)
        pos, other = None, []
        for mid, p in (a.get("positions") or {}).items():
            sz = float(p.get("size") or 0)
            if sz == 0:
                continue
            if int(mid) == self.mid:
                pos = {"side": 1 if sz > 0 else -1, "size": abs(sz), "entry": float(p.get("averageEntryPrice") or 0),
                       "upnl": float(p.get("unrealizedPnl") or 0)}
            else:
                other.append(p.get("marketDisplayName") or mid)
        return {"equity": float(a.get("equity") or 0), "free_collateral": float(a.get("freeCollateral") or 0),
                "position": pos, "other_positions": other}

    def book(self):
        d = self._get(f"/v1/bbo/{self.market}")
        b, a = d.get("bestBid") or {}, d.get("bestAsk") or {}
        if not b.get("price") or not a.get("price"):
            raise RuntimeError("empty BBO")
        return float(b["price"]), float(a["price"])

    def active_orders(self):
        try:
            d = self._get("/v1/openOrders", address=self.addr, accountIndex=self.ai, market=self.market)
        except Exception:
            return None
        out = []
        for o in d.get("orders", []):
            t = o.get("tpslType")
            kind = "stop" if t == "STOP_LOSS" else "tp" if t == "TAKE_PROFIT" else ("entry" if not o.get("reduceOnly") else "other")
            out.append({"kind": kind, "reduce_only": bool(o.get("reduceOnly")), "price": float(o.get("price") or 0),
                        "trigger": float(o.get("triggerPrice") or 0), "order_index": o.get("orderId"),
                        "client_order_index": o.get("clientId"), "status": o.get("status"), "pos_tpsl": bool(o.get("isPositionTPSL"))})
        return out

    # ------------------------------------------------------------------ writes
    def set_leverage(self, lev, margin="cross"):
        g = self._guard()
        if g: return g
        return self._legacy("setLeverage", {"accountIndex": self.ai, "address": self.addr, "isolated": margin == "isolated",
                                            "leverage": int(lev), "marketId": self.mid})

    def cancel_all(self):
        g = self._guard()
        if g: return g
        return self._legacy("cancelAllOrders", {"accountIndex": self.ai, "address": self.addr, "marketId": self.mid})

    def cancel_order(self, order_id):
        g = self._guard()
        if g: return g
        ts = time.time_ns()
        payload = f'{{"ad":"{self.addr_l}","ai":{self.ai},"ct":{ts},"id":"{order_id}","m":{self.mid},"op":2,"v":1}}'
        body = {"address": self.addr, "accountIndex": self.ai, "marketId": self.mid, "kind": "orderId", "orderId": str(order_id), "timestamp": ts}
        s, d = self._req("POST", "/v1/cancelOrder", body, self._hdr(ts, self._sign(payload)), {"address": self.addr})
        return {"ok": s in (200, 202), "http": s, "resp": d}

    def dead_man(self, seconds):
        """Arm/refresh (seconds ahead, 5..300) or disarm (None) the BTC-market dead man's switch (cancels resting orders)."""
        g = self._guard()
        if g: return g
        body = {"accountIndex": self.ai, "address": self.addr, "marketId": self.mid}
        if seconds:
            body["time"] = int(time.time() * 1_000_000) + int(seconds) * 1_000_000
        r = self._legacy("scheduleCancel", body)
        if r.get("ok"):
            self.dm_armed = bool(seconds)
        return r

    def _tpsl_pair(self, side, size, stop, stop_worst, tp, pos_level, ts=None):
        ts = ts or time.time_ns(); legs = []
        if tp is not None:
            legs.append(self._order(ts, -side, "LIMIT", "GTT", size, tp, reduce=True, tpsl="TAKE_PROFIT", stop_price=tp,
                                    cid=self.cid("tp"), pos_tpsl=pos_level))
        legs.append(self._order(ts, -side, "MARKET", "IOC", size, stop_worst, reduce=True, tpsl="STOP_LOSS", stop_price=stop,
                                cid=self.cid("sl"), pos_tpsl=pos_level))
        return legs, ts

    def open_group(self, side, size, tif, price, stop_trigger, stop_worst, tp, ids=None):
        g = self._guard()
        if g: return g
        if tif == "gtt":
            # entryTpsl: entry + bound SL (+TP). Arcus rejects a TP trigger that is already on the far side of the
            # oracle (e.g. a long TP below the current price) - then the TP is added right after the fill instead.
            bid, ask = self.book(); mid = (bid + ask) / 2
            tp_ok = tp is not None and ((tp > mid) if side == 1 else (tp < mid))
            ts = time.time_ns()
            entry = self._order(ts, side, "LIMIT", "GTT", size, price, cid=self.cid("en"))
            legs, _ = self._tpsl_pair(side, size, stop_trigger, stop_worst, tp if tp_ok else None, False, ts)
            r = self._post_batch([entry] + legs, ts, "entryTpsl")
            rows = (r.get("resp") or {}).get("responses") or []
            st = {str(x.get("clientId", ""))[:4]: str(x.get("status", "")).upper() for x in rows}
            ent_ok = st.get("dden") not in (None, "ERROR", "REJECTED"); sl_ok = st.get("ddsl") not in (None, "ERROR", "REJECTED")
            r["client_order_ids"] = {"entry": entry[0]["clientId"]}; r["tp_deferred"] = not tp_ok
            if ent_ok and sl_ok:
                r["ok"] = True; r.pop("error", None)
                if tp_ok and st.get("ddtp") in (None, "ERROR", "REJECTED"):
                    r["tp_deferred"] = True
            elif ent_ok:                      # entry rests without its stop: never allow that
                ent_id = next((x.get("orderId") for x in rows if str(x.get("clientId", "")).startswith("dden")), None)
                r["unwind"] = self.cancel_order(ent_id) if ent_id else self.cancel_all()
                r["ok"] = False; r["error"] = "stop leg rejected - entry cancelled: " + str(r.get("error"))[:200]
            return r
        # marketable IOC limit at the worst price, then position-level SL/TP
        acc0 = self.account()["position"]
        if acc0:
            return {"ok": False, "error": "position already open"}
        ts = time.time_ns()
        b, sg = self._order(ts, side, "LIMIT", "IOC", size, price, cid=self.cid("en"))
        r = self._post_order(b, sg, ts)
        if not r["ok"] and "racleDeviation" in str(r.get("error")):
            ts = time.time_ns(); b, sg = self._order(ts, side, "MARKET", "IOC", size, price, cid=self.cid("en"))
            r = self._post_order(b, sg, ts); r["fallback"] = "MARKET"
        if not r["ok"]:
            return r
        pos = None
        for _ in range(10):
            time.sleep(0.5)
            pos = self.account()["position"]
            if pos: break
        if not pos:
            r.update(ok=True, note="IOC entry accepted but no position (not filled)"); return r
        prot = self.protect_position(pos, stop_trigger, stop_worst, tp)
        r["protection"] = prot
        if not prot["stop_ok"]:
            r["emergency_close"] = self.close_position(pos)
            r.update(ok=False, error="stop could not be placed - position closed")
        return r

    def protect_position(self, pos, stop, stop_worst, tp):
        out = {"stop_ok": False}
        for attempt in range(3):
            legs, ts = self._tpsl_pair(pos["side"], pos["size"], stop, stop_worst, tp, True)
            rr = self._post_batch(legs, ts, "positionTpsl"); out[f"try{attempt}"] = rr
            if rr["ok"]:
                out["stop_ok"] = True; break
            time.sleep(1)
            o = self.active_orders() or []
            if any(x["kind"] == "stop" for x in o):
                out["stop_ok"] = True; out["note"] = "stop present after error"; break
        return out

    def close_position(self, pos, slippage_pct=0.5, immediate=True):
        g = self._guard()
        if g: return g
        bid, ask = self.book()
        long_ = pos["side"] == 1
        px = bid * (1 - slippage_pct / 100) if long_ else ask * (1 + slippage_pct / 100)
        ts = time.time_ns()
        b, sg = self._order(ts, -pos["side"], "MARKET", "IOC", pos["size"], self._pstr(px, "down" if long_ else "up"),
                            reduce=True, cid=self.cid("cl"))
        return self._post_order(b, sg, ts)

    def place_stop(self, pos, trigger, worst):
        g = self._guard()
        if g: return g
        ts = time.time_ns()
        leg = self._order(ts, -pos["side"], "MARKET", "IOC", pos["size"], worst, reduce=True, tpsl="STOP_LOSS",
                          stop_price=trigger, cid=self.cid("sl"), pos_tpsl=True)
        return self._post_batch([leg], ts, "positionTpsl")

    def place_tp(self, pos, price):
        g = self._guard()
        if g: return g
        ts = time.time_ns()
        leg = self._order(ts, -pos["side"], "LIMIT", "GTT", pos["size"], price, reduce=True, tpsl="TAKE_PROFIT",
                          stop_price=price, cid=self.cid("tp"), pos_tpsl=True)
        return self._post_batch([leg], ts, "positionTpsl")
