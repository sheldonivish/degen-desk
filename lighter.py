#!/usr/bin/env python3
"""Degen Desk x Lighter (lighter.xyz) perps helper.

Reads are keyless. Trading is gated: preview -> user approves the exact terms -> place.
DRY-RUN IS THE DEFAULT. Nothing is signed or sent unless `place --live --approve <code>`.

Reads (no key):
  lighter.py markets [--search SOL]
  lighter.py book SOL [--limit 5]
  lighter.py funding SOL | stats SOL
  lighter.py account --index N | --l1 0x...
  lighter.py positions [--index N]          # open positions only (defaults to $LIGHTER_ACCOUNT_INDEX)
  lighter.py size SOL --side long --equity 1000 --entry 108.3 --stop 107.2 [--risk-pct 1]

Paper (local simulation via the official kit, no key):
  lighter.py paper init|status|positions|trades|reset|order ...   (passed to kit paper.py)

Gated trading (risk hard-capped at 1% of equity per trade):
  lighter.py preview open SOL --side long --stop 107.2 [--tp 110] [--entry market|limit --price P]
                         [--slippage 0.3] [--stop-slippage 0.5] [--leverage 5] [--margin cross|isolated]
                         [--risk-pct 1] [--size N] [--equity USD]
  lighter.py preview close SOL [--size N] [--slippage 0.3]          # reduce-only, needs the account index
  lighter.py preview cancel SOL (--order-index N | --all)
  lighter.py place --approve CODE              # dry-run: shows exactly what would be sent
  lighter.py place --approve CODE --paper      # fill the entry on the local paper account
  lighter.py place --approve CODE --live       # sign + send ONCE, then confirm via account read

Hard-blocked (never implemented): withdraw, transfer, mode, collateral, fast-withdraw,
change-api-key, sub-account. Do those in the Lighter app.

Env: LIGHTER_API_PRIVATE_KEY (secret, only needed for --live), LIGHTER_ACCOUNT_INDEX,
LIGHTER_API_KEY_INDEX (4-254), optional LIGHTER_HOST. The kit's credentials file is never read.
The API private key is never printed or logged; the log holds order ids and tx hashes only.
"""
import argparse, asyncio, hashlib, json, math, os, secrets, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path

KIT = Path(os.path.expanduser(os.environ.get("LIGHTER_KIT_DIR", "~/.agents/skills/lighter-agent-kit")))
HOST = os.environ.get("LIGHTER_HOST", "https://mainnet.zklighter.elliot.ai").rstrip("/")
STATE = Path(os.path.expanduser(os.environ.get("LIGHTER_DESK_STATE", "~/.degen-desk/lighter")))
PENDING, USED, LOG = STATE / "pending.json", STATE / "used_codes.txt", STATE / "orders.log"
MAX_RISK_PCT = 1.0            # Degen Desk policy: never risk more than 1% of equity per trade
DEFAULT_TTL = 300             # approval codes expire after 5 minutes
BLOCKED = {"withdraw", "transfer", "mode", "collateral", "fast-withdraw", "fast_withdraw",
           "change-api-key", "change_api_key", "sub-account", "sub_account", "close-all", "close_all"}
SECRET_ENV = ("LIGHTER_API_PRIVATE_KEY", "LIGHTER_ETH_PRIVATE_KEY")
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# ---------------------------------------------------------------- helpers
def out(obj, code=0):
    print(json.dumps(obj, indent=2, default=str)); sys.exit(code)

def fail(msg, code=1, **extra):
    out({"error": msg, **extra}, code)

def redact(s):
    s = str(s)
    for name in SECRET_ENV:
        v = os.environ.get(name)
        if v and len(v) > 8:
            s = s.replace(v, "[REDACTED]").replace(v.removeprefix("0x"), "[REDACTED]")
    return s

def api(path, **params):
    url = f"{HOST}/api/v1/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "degen-desk"}), timeout=20) as r:
            return json.loads(r.read())
    except Exception as e:
        fail(f"read failed: {path}", detail=str(e)[:200])

def kit(script, *args):
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    r = subprocess.run([sys.executable, str(KIT / "scripts" / script), *args],
                       capture_output=True, text=True, timeout=90, env=env)
    try: return json.loads(r.stdout)
    except Exception: return {"error": (r.stdout or r.stderr).strip()[-400:]}

def market(sym):
    sym = sym.upper()
    ob = next((m for m in api("orderBooks").get("order_books", [])
               if m.get("symbol") == sym and m.get("market_type") == "perp"), None)
    if not ob: fail(f"unknown perp market {sym}")
    det = (api("orderBookDetails", market_id=ob["market_id"]).get("order_book_details") or [{}])[0]
    if ob.get("status") != "active" or det.get("is_frozen"): fail(f"{sym} is not active")
    imf = det.get("min_initial_margin_fraction") or 10000
    return {"symbol": sym, "id": int(ob["market_id"]), "sd": int(ob["supported_size_decimals"]),
            "pd": int(ob["supported_price_decimals"]), "min_base": float(ob["min_base_amount"]),
            "min_quote": float(ob["min_quote_amount"]), "taker_fee_pct": float(ob["taker_fee"]),
            "max_leverage": int(10000 // int(imf)), "last": det.get("last_trade_price")}

def top_of_book(mid):
    d = api("orderBookOrders", market_id=mid, limit=5)
    asks = [float(x["price"]) for x in d.get("asks", [])]; bids = [float(x["price"]) for x in d.get("bids", [])]
    if not asks or not bids: fail("empty order book")
    return max(bids), min(asks)

def account(index):
    a = (api("account", by="index", value=str(index)).get("accounts") or [None])[0]
    if not a: fail(f"account {index} not found")
    return a

def equity_of(a):
    for k in ("total_asset_value", "collateral"):
        try:
            v = float(a.get(k) or 0)
            if v > 0: return v
        except ValueError: pass
    return 0.0

def open_positions(a):
    return [p for p in a.get("positions", []) if float(p.get("position") or 0) != 0]

def env_account_index():
    v = os.environ.get("LIGHTER_ACCOUNT_INDEX")
    return int(v) if v and v.strip().isdigit() else None

def to_int(x, dec, mode):
    f = x * 10 ** dec
    return int(math.ceil(f - 1e-9) if mode == "up" else math.floor(f + 1e-9) if mode == "down" else round(f))

def from_int(i, dec): return round(i / 10 ** dec, dec)

def new_code(): return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
def hcode(c): return hashlib.sha256(c.strip().upper().encode()).hexdigest()
def coi(): return secrets.randbelow(2 ** 47 - 1) + 1          # client_order_index (uint48)

def state_dir():
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True); os.chmod(STATE, 0o700)

def log(entry):
    state_dir()
    safe = {k: entry[k] for k in ("ts", "mode", "action", "market", "client_order_ids", "order_index", "tx_hash", "status") if k in entry}
    with open(LOG, "a") as f: f.write(json.dumps(safe) + "\n")

def save_pending(rec, ttl):
    state_dir()
    code = new_code()
    rec.update({"code_sha256": hcode(code), "created": int(time.time()), "expires": int(time.time()) + ttl, "host": HOST})
    tmp = PENDING.with_suffix(".tmp"); tmp.write_text(json.dumps(rec, indent=2)); os.chmod(tmp, 0o600); tmp.replace(PENDING)
    return code

# ---------------------------------------------------------------- reads
def cmd_reads(a):
    if a.cmd == "markets":
        out(kit("query.py", "market", "list", "--market_type", "perp", *(["--search", a.search] if a.search else [])))
    if a.cmd == "book":
        d = api("orderBookOrders", market_id=market(a.symbol)["id"], limit=a.limit)
        out({"symbol": a.symbol.upper(),
             "asks": sorted([(float(x["price"]), x["remaining_base_amount"]) for x in d.get("asks", [])]),
             "bids": sorted([(float(x["price"]), x["remaining_base_amount"]) for x in d.get("bids", [])], reverse=True)})
    if a.cmd == "funding": out(kit("query.py", "market", "funding", "--symbol", a.symbol.upper()))
    if a.cmd == "stats": out(kit("query.py", "market", "stats", "--symbol", a.symbol.upper()))
    if a.cmd == "account":
        out(kit("query.py", "account", "info", "--account_index", a.index) if a.index
            else kit("query.py", "account", "info", "--by", "l1_address", "--value", a.l1))
    if a.cmd == "positions":
        idx = a.index if a.index is not None else env_account_index()
        if idx is None: fail("pass --index N or set LIGHTER_ACCOUNT_INDEX")
        acc = account(idx)
        out({"equity": equity_of(acc), "available_balance": acc.get("available_balance"),
             "positions": [{k: p.get(k) for k in ("symbol", "sign", "position", "avg_entry_price", "unrealized_pnl",
                            "liquidation_price", "margin_mode", "initial_margin_fraction")} for p in open_positions(acc)]})

def risk_size(equity, risk_pct, loss_per_unit, sd):
    raw = equity * risk_pct / 100 / loss_per_unit
    return math.floor(raw * 10 ** sd + 1e-9) / 10 ** sd

def cmd_size(a):
    if a.risk_pct > MAX_RISK_PCT or a.risk_pct <= 0: fail(f"risk-pct must be >0 and <= {MAX_RISK_PCT}")
    m = market(a.symbol)
    if (a.side == "long") != (a.stop < a.entry): fail("stop is on the wrong side of entry")
    fee = (a.entry + a.stop) * a.fee_bps / 1e4
    lpu = abs(a.entry - a.stop) + fee
    size = risk_size(a.equity, a.risk_pct, lpu, m["sd"])
    out({"symbol": m["symbol"], "side": a.side, "entry": a.entry, "stop": a.stop, "equity": a.equity,
         "risk_pct": a.risk_pct, "size": size, "max_loss_usd": round(size * lpu, 4), "notional_usd": round(size * a.entry, 2),
         "implied_leverage": round(size * a.entry / a.equity, 2), "max_leverage": m["max_leverage"],
         "meets_minimums": size >= m["min_base"] and size * a.entry >= m["min_quote"],
         "note": "Sizing only. Nothing was placed."})

# ---------------------------------------------------------------- preview
def preview_open(a):
    if a.risk_pct > MAX_RISK_PCT or a.risk_pct <= 0: fail(f"risk-pct must be >0 and <= {MAX_RISK_PCT} (Degen Desk policy)")
    if a.stop is None: fail("--stop is required: every entry carries a reduce-only stop")
    m = market(a.symbol); long_ = a.side in ("long", "buy"); pd, sd = m["pd"], m["sd"]
    bid, ask = top_of_book(m["id"])
    # equity: the smaller of the live account (if LIGHTER_ACCOUNT_INDEX is set) and --equity
    idx = env_account_index(); acc_eq = equity_of(account(idx)) if idx is not None else None
    cands = [x for x in (acc_eq, a.equity) if x]
    if not cands: fail("no equity: set LIGHTER_ACCOUNT_INDEX (public read) or pass --equity USD")
    equity = min(cands)
    # entry worst price
    if a.entry == "market":
        ref = ask if long_ else bid
        worst_i = to_int(ref * (1 + a.slippage / 100), pd, "up") if long_ else to_int(ref * (1 - a.slippage / 100), pd, "down")
        tif, expiry = "IOC", 0
    else:
        if a.price is None: fail("--price is required for --entry limit")
        ref = a.price; worst_i = to_int(a.price, pd, "near"); tif, expiry = "GTT", -1
    worst = from_int(worst_i, pd)
    # stop (reduce-only stop-loss market with a worst fill price)
    if long_ and not a.stop < min(worst, ref): fail("long stop must be below entry")
    if not long_ and not a.stop > max(worst, ref): fail("short stop must be above entry")
    trig_i = to_int(a.stop, pd, "near")
    stop_worst_i = to_int(a.stop * (1 - a.stop_slippage / 100), pd, "down") if long_ else to_int(a.stop * (1 + a.stop_slippage / 100), pd, "up")
    stop_worst = from_int(stop_worst_i, pd)
    tp_i = None
    if a.tp is not None:
        if long_ and not a.tp > worst: fail("long TP must be above entry")
        if not long_ and not a.tp < worst: fail("short TP must be below entry")
        tp_i = to_int(a.tp, pd, "near")
    fee_unit = (worst + stop_worst) * m["taker_fee_pct"] / 100
    lpu = abs(worst - stop_worst) + fee_unit
    max_size = risk_size(equity, a.risk_pct, lpu, sd)
    size = max_size if a.size is None else math.floor(a.size * 10 ** sd + 1e-9) / 10 ** sd
    if size > max_size: fail(f"size {size} risks more than {a.risk_pct}% of equity; max is {max_size}")
    if size < m["min_base"] or size * ref < m["min_quote"]:
        fail("size below market minimum", size=size, min_base=m["min_base"], min_quote_usd=m["min_quote"])
    notional = size * worst
    lev = a.leverage or max(1, math.ceil(notional / equity))
    if lev > m["max_leverage"]: fail(f"leverage {lev}x exceeds market max {m['max_leverage']}x")
    if notional / equity > lev: fail(f"notional {notional:.2f} needs more than {lev}x on equity {equity:.2f}; raise --leverage or cut size")
    max_loss = size * lpu
    if max_loss > equity * MAX_RISK_PCT / 100 + 1e-9: fail("max loss exceeds 1% hard cap")
    ids = {"entry": coi(), "stop": coi(), **({"tp": coi()} if tp_i else {})}
    terms = {"venue": "Lighter perps", "host": HOST, "market": m["symbol"], "market_id": m["id"],
             "side": "long" if long_ else "short", "size": size, "entry_type": a.entry, "time_in_force": tif,
             "reference_price": ref, "worst_entry_price": worst, "stop_trigger": from_int(trig_i, pd),
             "stop_worst_fill": stop_worst, "stop_reduce_only": True, "take_profit": from_int(tp_i, pd) if tp_i else None,
             "leverage": lev, "margin_mode": a.margin, "notional_usd": round(notional, 2), "equity_used": round(equity, 2),
             "equity_source": "account" if acc_eq and equity == acc_eq else "--equity",
             "risk_pct_cap": a.risk_pct, "max_loss_usd": round(max_loss, 4),
             "max_loss_pct": round(max_loss / equity * 100, 4), "taker_fee_pct": m["taker_fee_pct"]}
    ints = {"base": to_int(size, sd, "near"), "worst": worst_i, "trig": trig_i, "stop_worst": stop_worst_i,
            "tp": tp_i, "is_ask": 0 if long_ else 1, "expiry": expiry, "ids": ids}
    return {"action": "open", "terms": terms, "ints": ints, "account_index": idx}

def preview_close(a):
    idx = a.index if a.index is not None else env_account_index()
    if idx is None: fail("close needs the account: set LIGHTER_ACCOUNT_INDEX or pass --index")
    m = market(a.symbol); pd, sd = m["pd"], m["sd"]
    pos = next((p for p in open_positions(account(idx)) if int(p["market_id"]) == m["id"]), None)
    if not pos: fail(f"no open {m['symbol']} position on this account")
    held = abs(float(pos["position"])); long_pos = int(pos["sign"]) == 1
    size = held if a.size is None else min(held, math.floor(a.size * 10 ** sd + 1e-9) / 10 ** sd)
    bid, ask = top_of_book(m["id"])
    ref = bid if long_pos else ask
    worst_i = to_int(ref * (1 - a.slippage / 100), pd, "down") if long_pos else to_int(ref * (1 + a.slippage / 100), pd, "up")
    ids = {"close": coi()}
    terms = {"venue": "Lighter perps", "host": HOST, "market": m["symbol"], "market_id": m["id"],
             "position": f"{'long' if long_pos else 'short'} {held}", "avg_entry": pos.get("avg_entry_price"),
             "unrealized_pnl": pos.get("unrealized_pnl"), "close_side": "sell" if long_pos else "buy",
             "size": size, "order": "market IOC, reduce-only", "reference_price": ref, "worst_fill_price": from_int(worst_i, pd)}
    ints = {"base": to_int(size, sd, "near"), "worst": worst_i, "is_ask": 1 if long_pos else 0, "ids": ids}
    return {"action": "close", "terms": terms, "ints": ints, "account_index": idx}

def preview_cancel(a):
    m = market(a.symbol)
    if not a.all and a.order_index is None: fail("pass --order-index N or --all")
    terms = {"venue": "Lighter perps", "host": HOST, "market": m["symbol"], "market_id": m["id"],
             "cancel": f"ALL open orders on {m['symbol']} (including attached stops/TPs)" if a.all else f"order {a.order_index}"}
    return {"action": "cancel", "terms": terms, "ints": {"order_index": a.order_index, "all": bool(a.all)},
            "account_index": env_account_index()}

def cmd_preview(a):
    rec = {"open": preview_open, "close": preview_close, "cancel": preview_cancel}[a.action](a)
    ttl = max(30, min(a.ttl, 900))
    code = save_pending(rec, ttl)
    out({"status": "PREVIEW - nothing sent", "action": rec["action"], "terms": rec["terms"],
         "approval_code": code, "expires_in_s": ttl,
         "next": f"Show these exact terms to the user. Only after an explicit yes to them: "
                 f"lighter.py place --approve {code} --live   (omit --live for a dry-run)"})

# ---------------------------------------------------------------- place
def load_pending(code):
    if not PENDING.exists(): fail("no pending preview; run preview first")
    rec = json.loads(PENDING.read_text())
    if rec.get("action") not in ("open", "close", "cancel"): fail("pending action is not allowed", 2)
    if hcode(code) != rec.get("code_sha256"): fail("approval code does not match the pending preview")
    if USED.exists() and rec["code_sha256"] in USED.read_text().split(): fail("approval code already used; preview again")
    if time.time() > rec["expires"]: fail("approval code expired; preview again")
    if rec.get("host") != HOST: fail("LIGHTER_HOST changed since preview; preview again")
    return rec

def consume(rec):
    state_dir()
    with open(USED, "a") as f: f.write(rec["code_sha256"] + "\n")
    PENDING.unlink(missing_ok=True)

def tx_plan(rec):
    i, t = rec["ints"], rec["terms"]
    if rec["action"] == "open":
        plan = []
        if t.get("leverage"): plan.append({"tx": "update_leverage", "market_id": t["market_id"], "leverage": t["leverage"], "margin_mode": t["margin_mode"]})
        orders = [{"role": "entry", "type": "LIMIT", "tif": t["time_in_force"], "client_order_index": i["ids"]["entry"],
                   "base_amount": i["base"], "price": i["worst"], "is_ask": i["is_ask"], "reduce_only": 0}]
        if i.get("tp"): orders.append({"role": "take_profit", "type": "TAKE_PROFIT_LIMIT", "client_order_index": i["ids"]["tp"],
                                       "base_amount": 0, "trigger": i["tp"], "price": i["tp"], "is_ask": 1 - i["is_ask"], "reduce_only": 1})
        orders.append({"role": "stop", "type": "STOP_LOSS", "client_order_index": i["ids"]["stop"], "base_amount": 0,
                       "trigger": i["trig"], "price": i["stop_worst"], "is_ask": 1 - i["is_ask"], "reduce_only": 1})
        plan.append({"tx": "create_grouped_orders", "grouping": "OTOCO" if i.get("tp") else "OTO", "orders": orders})
        return plan
    if rec["action"] == "close":
        return [{"tx": "create_order", "type": "MARKET", "tif": "IOC", "reduce_only": 1, "client_order_index": i["ids"]["close"],
                 "base_amount": i["base"], "price": i["worst"], "is_ask": i["is_ask"]}]
    return [{"tx": "cancel_all_orders(market)" if i["all"] else "cancel_order", "market_id": rec["terms"]["market_id"],
             **({} if i["all"] else {"order_index": i["order_index"]})}]

def drift_check(rec):
    if rec["action"] != "open" or rec["terms"]["entry_type"] != "market": return
    bid, ask = top_of_book(rec["terms"]["market_id"]); w = rec["terms"]["worst_entry_price"]
    if (rec["terms"]["side"] == "long" and ask > w) or (rec["terms"]["side"] == "short" and bid < w):
        fail("price moved past the approved worst entry price; nothing sent, preview again",
             best_bid=bid, best_ask=ask, worst_entry=w)

def live_creds():
    key = os.environ.get("LIGHTER_API_PRIVATE_KEY", "").strip()
    acct, kidx = os.environ.get("LIGHTER_ACCOUNT_INDEX", "").strip(), os.environ.get("LIGHTER_API_KEY_INDEX", "").strip()
    missing = [n for n, v in (("LIGHTER_API_PRIVATE_KEY", key), ("LIGHTER_ACCOUNT_INDEX", acct), ("LIGHTER_API_KEY_INDEX", kidx)) if not v]
    if missing: fail("live trading not configured; nothing sent", missing=missing,
                     how="add them through a secure secret request (never in chat, files, or the kit's credentials file)")
    if not acct.isdigit() or not kidx.isdigit() or not 4 <= int(kidx) <= 254:
        fail("LIGHTER_ACCOUNT_INDEX must be an integer and LIGHTER_API_KEY_INDEX must be 4-254")
    return key, int(acct), int(kidx)

def load_sdk():
    sys.path.insert(0, str(KIT / "scripts"))
    from _sdk import ensure_lighter       # official kit: vendored, pinned SDK; stubs eth_account (no L1 key support)
    ensure_lighter()
    import lighter
    from lighter.signer_client import CreateOrderTxReq
    return lighter, CreateOrderTxReq

async def send_live(rec, key, acct, kidx):
    lighter, Req = load_sdk()
    client = None
    try:
        client = lighter.SignerClient(url=HOST, account_index=acct, api_private_keys={kidx: key})
        rc = getattr(getattr(client.api_client, "rest_client", None), "retry_client", "missing")
        if rc not in (None, "missing"): return {"error": "SDK HTTP retries are enabled; refusing to send"}
        err = client.check_client()
        if err: return {"error": "API key check failed (key not registered for this account/slot?)", "detail": redact(err)[:200]}
        i, t, res = rec["ints"], rec["terms"], {"tx_hashes": []}
        if rec["action"] == "open":
            mm = client.ISOLATED_MARGIN_MODE if t["margin_mode"] == "isolated" else client.CROSS_MARGIN_MODE
            _, r, e = await client.update_leverage(t["market_id"], mm, t["leverage"])
            if e or (r is not None and getattr(r, "code", 200) != 200):
                return {"error": "leverage update failed; order NOT sent", "detail": redact(e or r)[:200]}
            res["tx_hashes"].append(getattr(r, "tx_hash", None))
            entry_tif = client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL if t["time_in_force"] == "IOC" else client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME
            orders = [Req(MarketIndex=t["market_id"], ClientOrderIndex=i["ids"]["entry"], BaseAmount=i["base"], Price=i["worst"],
                          IsAsk=i["is_ask"], Type=client.ORDER_TYPE_LIMIT, TimeInForce=entry_tif, ReduceOnly=0, TriggerPrice=0,
                          OrderExpiry=i["expiry"])]
            if i.get("tp"):
                orders.append(Req(MarketIndex=t["market_id"], ClientOrderIndex=i["ids"]["tp"], BaseAmount=0, Price=i["tp"],
                                  IsAsk=1 - i["is_ask"], Type=client.ORDER_TYPE_TAKE_PROFIT_LIMIT,
                                  TimeInForce=client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME, ReduceOnly=1, TriggerPrice=i["tp"], OrderExpiry=-1))
            orders.append(Req(MarketIndex=t["market_id"], ClientOrderIndex=i["ids"]["stop"], BaseAmount=0, Price=i["stop_worst"],
                              IsAsk=1 - i["is_ask"], Type=client.ORDER_TYPE_STOP_LOSS,
                              TimeInForce=client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL, ReduceOnly=1, TriggerPrice=i["trig"], OrderExpiry=-1))
            g = client.GROUPING_TYPE_ONE_TRIGGERS_A_ONE_CANCELS_THE_OTHER if i.get("tp") else client.GROUPING_TYPE_ONE_TRIGGERS_THE_OTHER
            _, r, e = await client.create_grouped_orders(grouping_type=g, orders=orders)
        elif rec["action"] == "close":
            _, r, e = await client.create_order(t["market_id"], i["ids"]["close"], i["base"], i["worst"], i["is_ask"],
                                                client.ORDER_TYPE_MARKET, client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                                                reduce_only=True, order_expiry=client.DEFAULT_IOC_EXPIRY)
        else:
            if i["all"]:
                _, r, e = await client.cancel_all_orders(client.CANCEL_ALL_TIF_IMMEDIATE, 0, cancel_all_market_index=t["market_id"])
            else:
                _, r, e = await client.cancel_order(t["market_id"], i["order_index"])
        if e or r is None or getattr(r, "code", 200) != 200:
            return {"error": "send rejected (not retried)", "detail": redact(e or r)[:300]}
        res["tx_hashes"].append(getattr(r, "tx_hash", None)); res["status"] = "accepted"
        return res
    except Exception as ex:
        return {"error": "send failed (not retried)", "detail": redact(f"{type(ex).__name__}: {ex}")[:300]}
    finally:
        try:
            if client is not None: await client.close()
        except Exception: pass

def confirm(rec, acct):
    time.sleep(3)
    a = account(acct); mid = rec["terms"]["market_id"]
    p = next((x for x in open_positions(a) if int(x["market_id"]) == mid), None)
    return {"position_now": ({"side": "long" if int(p["sign"]) == 1 else "short", "size": p["position"],
                              "avg_entry": p["avg_entry_price"], "liq": p.get("liquidation_price")} if p else "flat"),
            "pending_order_count": a.get("pending_order_count"), "total_order_count": a.get("total_order_count"),
            "note": "accepted != filled; verify the position above. Never resend: preview again if needed."}

def cmd_place(a):
    rec = load_pending(a.approve)
    plan = tx_plan(rec)
    ids = list(rec["ints"].get("ids", {}).values())
    base = {"ts": int(time.time()), "action": rec["action"], "market": rec["terms"]["market"], "client_order_ids": ids}
    if a.live and a.paper: fail("choose --live or --paper, not both")
    if not a.live and not a.paper:
        drift_check(rec)
        out({"status": "DRY-RUN - nothing signed or sent", "terms": rec["terms"], "would_send": plan,
             "note": "code NOT consumed; add --live to send once, or --paper to simulate"})
    if a.paper:
        if rec["action"] != "open": fail("paper mode only simulates entries (kit paper engine: market/IOC, perps)")
        t = rec["terms"]; drift_check(rec)
        r = kit("paper.py", "order", "ioc", t["market"], "--side", t["side"], "--amount", str(t["size"]), "--price", str(t["worst_entry_price"]))
        consume(rec); log({**base, "mode": "paper", "status": r.get("status", "error")})
        out({"status": "PAPER", "fill": r, "note": "stop/TP are not simulated by the kit's paper engine; track them manually"})
    key, acct, kidx = live_creds()                         # fails cleanly before anything is consumed
    if rec.get("account_index") not in (None, acct): fail("LIGHTER_ACCOUNT_INDEX differs from the previewed account; preview again")
    drift_check(rec)
    consume(rec)                                           # single use: consumed BEFORE sending, so it can never fire twice
    res = asyncio.run(send_live(rec, key, acct, kidx)); del key
    log({**base, "mode": "live", "tx_hash": ",".join(h for h in res.get("tx_hashes", []) if h) or None,
         "status": res.get("status", "error")})
    if "error" in res: out({"status": "NOT PLACED", **res, "terms": rec["terms"]}, 1)
    out({"status": "SENT ONCE", "terms": rec["terms"], "client_order_ids": ids, "tx_hashes": res["tx_hashes"], **confirm(rec, acct)})

# ---------------------------------------------------------------- cli
def main():
    if len(sys.argv) > 1 and sys.argv[1].lower() in BLOCKED:
        fail(f"'{sys.argv[1]}' is hard-blocked in Degen Desk. Do it yourself in the Lighter app.", 2)
    if len(sys.argv) > 2 and sys.argv[1] == "preview" and sys.argv[2].lower() in BLOCKED:
        fail(f"'{sys.argv[2]}' is hard-blocked in Degen Desk. Do it yourself in the Lighter app.", 2)
    if len(sys.argv) > 1 and sys.argv[1] == "paper":
        if len(sys.argv) > 2 and sys.argv[2] not in {"init", "reset", "set_tier", "status", "positions", "trades", "health", "liquidation_price", "refresh", "order"}:
            fail("unknown paper command")
        out(kit("paper.py", *sys.argv[2:]))
    p = argparse.ArgumentParser(description="Degen Desk x Lighter (dry-run by default)")
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("markets").add_argument("--search")
    b = s.add_parser("book"); b.add_argument("symbol"); b.add_argument("--limit", type=int, default=5)
    s.add_parser("funding").add_argument("symbol"); s.add_parser("stats").add_argument("symbol")
    ac = s.add_parser("account"); g = ac.add_mutually_exclusive_group(required=True); g.add_argument("--index"); g.add_argument("--l1")
    s.add_parser("positions").add_argument("--index", type=int)
    z = s.add_parser("size"); z.add_argument("symbol"); z.add_argument("--side", choices=["long", "short"], required=True)
    for k in ("equity", "entry", "stop"): z.add_argument(f"--{k}", type=float, required=True)
    z.add_argument("--risk-pct", type=float, default=1.0); z.add_argument("--fee-bps", type=float, default=0.0)
    pv = s.add_parser("preview"); ps = pv.add_subparsers(dest="action", required=True)
    o = ps.add_parser("open"); o.add_argument("symbol"); o.add_argument("--side", choices=["long", "short", "buy", "sell"], required=True)
    o.add_argument("--stop", type=float); o.add_argument("--tp", type=float)
    o.add_argument("--entry", choices=["market", "limit"], default="market"); o.add_argument("--price", type=float)
    o.add_argument("--slippage", type=float, default=0.3); o.add_argument("--stop-slippage", type=float, default=0.5)
    o.add_argument("--leverage", type=int); o.add_argument("--margin", choices=["cross", "isolated"], default="cross")
    o.add_argument("--risk-pct", type=float, default=1.0); o.add_argument("--size", type=float); o.add_argument("--equity", type=float)
    c = ps.add_parser("close"); c.add_argument("symbol"); c.add_argument("--size", type=float)
    c.add_argument("--slippage", type=float, default=0.3); c.add_argument("--index", type=int)
    x = ps.add_parser("cancel"); x.add_argument("symbol"); x.add_argument("--order-index", type=int); x.add_argument("--all", action="store_true")
    for sp in (o, c, x): sp.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    pl = s.add_parser("place"); pl.add_argument("--approve", required=True)
    pl.add_argument("--live", action="store_true"); pl.add_argument("--paper", action="store_true")
    a = p.parse_args()
    if a.cmd == "size": return cmd_size(a)
    if a.cmd == "preview": return cmd_preview(a)
    if a.cmd == "place": return cmd_place(a)
    return cmd_reads(a)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as ex:   # never let a traceback (which could carry secrets) reach the chat
        print(json.dumps({"error": "unexpected failure", "detail": redact(f"{type(ex).__name__}: {ex}")[:300]}, indent=2))
        sys.exit(1)
