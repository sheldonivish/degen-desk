#!/usr/bin/env python3
"""ONE-TIME live verification (run only after the owner says yes): one DDMM-tagged post-only BTC buy of the smallest
valid size (lot 0.0001 BTC, >= $10 min notional -> 0.0002 BTC) about 5% below the bid, then cancel it by its own clientOrderId.
Checks the whole path (agent key, signing, gasless send, order visible, cancel) with no fill and no fee.
Run on the server from the popdex-mm folder: .venv/bin/python test_order.py"""
import json, time, urllib.request
from live import Live
cfg = json.load(open("config.json")); L = Live(cfg, "secrets/agent_key.json")
from live import get
t = get("https://api.popdex.xyz/api/v1/public/market/tickers?category=Futures&symbol=BTCUSDT")["data"][0]
px = float(int(float(t["bid1Price"]) * 0.95)); qty = 0.0002  # lot 0.0001; 0.0001 BTC is below the $10 min notional
print("agent:", L.ad.agent.address)
before = L.positions_snapshot(); print("positions before:", before)
print("pending DDMM before:", L.pending())
try: coid = L.place("buy", px, qty)
except Exception as e: print("PLACE FAILED (no retry):", e); print("positions after:", L.positions_snapshot()); raise SystemExit(1)
print("place receipt status: 1"); print(f"PLACED buy {qty} @ {px} (~${px*qty:.2f}) coid={coid.rstrip(bytes(1)).decode()} tx=0x{L.open[coid]['tx'].removeprefix('0x')}")
o = {}
for _ in range(15):
    time.sleep(1)
    try:
        o = L.order(coid)
        if o: break
    except Exception as e: o = {"err": str(e)}
print("order after place:", json.dumps(o)[:700])
print("pending DDMM:", [(x.get("clientOid"), x.get("price"), x.get("qty"), x.get("orderStatus") or x.get("status")) for x in L.pending()])
tx2 = L.cancel(coid); print("CANCEL tx=0x" + tx2.removeprefix("0x"))
print("cancel receipt status:", L.ad.w3.eth.wait_for_transaction_receipt(tx2, timeout=15)["status"])
time.sleep(3)
o2 = {}
for _ in range(10):
    try: o2 = L.order(coid); break
    except Exception as e: o2 = {"err": str(e)}; time.sleep(1)
print("order after cancel:", json.dumps(o2)[:700])
print("pending DDMM now:", L.pending())
after = L.positions_snapshot(); print("positions after:", after, "UNCHANGED" if after == before else "CHANGED!")
