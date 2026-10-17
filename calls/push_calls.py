#!/usr/bin/env python3
"""Deliver BTC/XAU calls from open_calls.json to the VPS call executor (live Lighter orders), with acks + retries.

  push_calls.py sync              one pass: send new/changed/cancelled calls, collect acks, resend unacked
  push_calls.py watch --minutes 10  repeat sync every 20 s (spawned automatically by trade_signal.py --send)
  push_calls.py send FILE.json    push one hand-written message (tests)
  push_calls.py status            show unacked / failed messages
Exit code 2 + "ALERT" lines (also in calls/vps_sync.log) when a message is unacked > 5 min or the executor did not place it.

Config (env): DD_VPS_HOST (server IP/hostname, required), DD_VPS_USER (default root), DD_VPS_KEY (default ~/.ssh/degen_vps),
DD_CALLS_DIR (default /workspace/calls, holds open_calls.json), DD_VPS_CALLS (default /opt/degen-desk/calls).
Needs paramiko (pip install paramiko). Key-only SSH; never put a password here.
"""
import fcntl, hashlib, json, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import paramiko

CALLS = Path(os.environ.get("DD_CALLS_DIR", "/workspace/calls")); OPEN = CALLS / "open_calls.json"
STATE = CALLS / "vps_sync.json"; LOG = CALLS / "vps_sync.log"
HOST = os.environ.get("DD_VPS_HOST", "")
USER, KEY = os.environ.get("DD_VPS_USER", "root"), os.path.expanduser(os.environ.get("DD_VPS_KEY", "~/.ssh/degen_vps"))
R = os.environ.get("DD_VPS_CALLS", "/opt/degen-desk/calls")
SYM = {"BTC-USDT-SWAP": "BTC", "BTC": "BTC", "XAU-USDT-SWAP": "XAU", "XAU": "XAU", "XAUUSD": "XAU", "XAUT-USDT-SWAP": "XAU"}
DEAD = {"CANCELLED", "EXPIRED", "INVALIDATED", "INVALID"}


def say(msg, alert=False):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {'ALERT ' if alert else ''}{msg}"
    print(line, file=sys.stderr if alert else sys.stdout, flush=True)
    with open(LOG, "a") as f: f.write(line + "\n")


def load():
    if STATE.exists(): return json.loads(STATE.read_text())
    return {"cutover": datetime.now(timezone.utc).isoformat(), "sent": {}, "calls": {}}


def save(st):
    t = STATE.with_suffix(".tmp"); t.write_text(json.dumps(st, indent=1)); t.replace(STATE)


def conn():
    if not HOST: raise RuntimeError("DD_VPS_HOST not set")
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, look_for_keys=False, allow_agent=False, timeout=20)
    return c, c.open_sftp()


def okx(sym):
    import urllib.request
    i = {"BTC": "BTC-USDT-SWAP", "XAU": "XAU-USDT-SWAP"}[sym]
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://www.okx.com/api/v5/market/ticker?instId={i}", headers={"User-Agent": "Mozilla/5.0"}), timeout=8) as r:
            return float(json.load(r)["data"][0]["last"])
    except Exception as e:
        say(f"OKX price for basis failed ({e}); executor will use basis 0", alert=True); return None


def put(sftp, msg):
    if msg["action"] in ("open", "update") and "okx_ref" not in msg:
        msg["okx_ref"], msg["okx_ref_ts"] = okx(msg["symbol"]), time.time()
    name = msg["msg"]; tmp = f"{R}/inbox/.{name}.tmp"
    with sftp.open(tmp, "w") as f: f.write(json.dumps(msg))
    sftp.chmod(tmp, 0o644)
    sftp.posix_rename(tmp, f"{R}/inbox/{name}.json")


def wanted(st):
    """Messages the current open_calls.json implies."""
    d = json.loads(OPEN.read_text()); out = []
    cut = datetime.fromisoformat(st["cutover"])
    for c in d.get("calls", []):
        sym = SYM.get(c.get("instrument", "").upper())
        if not sym: continue
        try:
            posted = datetime.fromisoformat(c["posted"])
        except Exception:
            continue
        force = c["id"] in st.get("force", [])
        if posted < cut and not force: continue
        ver = hashlib.sha1(json.dumps([c.get(k) for k in ("entry", "stop", "tp1", "tp2", "expiry")]).encode()).hexdigest()[:8]
        base = dict(id=c["id"], symbol=sym, side=c["side"], entry=c["entry"], stop=c["stop"], tp1=c.get("tp1") or c.get("tp"),
                    tp2=c.get("tp2"), expiry=c.get("expiry"), test=bool(c.get("test")))
        known = st["calls"].get(c["id"]); status = str(c.get("status", "")).upper()
        if status in DEAD:
            if known and not known.get("cancelled"):
                out.append(dict(base, action="cancel", msg=f"{c['id']}__cancel"))
            continue
        exp_ok = not c.get("expiry") or datetime.fromisoformat(c["expiry"]) > datetime.now(timezone.utc)
        if not known:
            if status in ("NEW", "FILLED", "TRIGGERED") and exp_ok:
                out.append(dict(base, action="open", msg=f"{c['id']}__open__{ver}", late=status != "NEW"))
        elif known.get("ver") != ver and status == "NEW" or (known.get("ver") != ver and status in ("FILLED", "TP HIT")
                                                              and c.get("stop") != known.get("stop")):
            out.append(dict(base, action="update", msg=f"{c['id']}__update__{ver}"))
    return out


def sync(extra=None):
    # explicit release: an implicit close via refcount can be delayed (exception tracebacks
    # holding the frame), which self-deadlocked the 10-min watcher on Oct 16, 2026
    with open(CALLS / ".vps_sync.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return _sync(extra)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _sync(extra=None):
    st = load(); bad = False
    msgs = (extra or []) + wanted(st)
    try:
        c, sftp = conn()
    except Exception as e:
        say(f"cannot reach VPS {HOST}: {type(e).__name__}: {e}", alert=True); save(st); return 2
    try:
        for m in msgs:
            if m["msg"] in st["sent"]: continue
            put(sftp, m); st["sent"][m["msg"]] = {"t": time.time(), "n": 1, "acked": False, "id": m["id"], "action": m["action"], "test": m.get("test"), "m": m}
            if m["action"] in ("open", "update"):
                st["calls"].setdefault(m["id"], {}).update(ver=m["msg"].split("__")[-1], stop=m.get("stop"))
            if m["action"] == "cancel":
                st["calls"].setdefault(m["id"], {})["cancelled"] = True
            say(f"sent {m['msg']}")
        save(st)
        deadline = time.time() + 25
        while time.time() < deadline and any(not v["acked"] for v in st["sent"].values()):
            for name, v in st["sent"].items():
                if v["acked"]: continue
                try:
                    with sftp.open(f"{R}/ack/{name}.json") as f: a = json.loads(f.read())
                except IOError:
                    continue
                v.update(acked=True, ok=a.get("ok"), result=a.get("result"))
                say(f"ack {name}: ok={a.get('ok')} {a.get('result')}", alert=not a.get("ok") and not v.get("test"))
            time.sleep(3)
        for name, v in st["sent"].items():
            if v["acked"]: continue
            age = time.time() - v["t"]
            if age > 90 and time.time() - v.get("last", v["t"]) > 90:
                m = v.get("m")
                if m:
                    put(sftp, m); v["n"] += 1; v["last"] = time.time(); say(f"resent {name} (try {v['n']})")
            if age > 300:
                say(f"{name} NOT acknowledged by the VPS executor after {age / 60:.0f} min", alert=True); bad = True
        save(st)
    finally:
        sftp.close(); c.close()
    return 2 if bad else 0


def main():
    a = sys.argv[1:] or ["sync"]
    if a[0] == "sync": sys.exit(sync())
    if a[0] == "watch":
        mins = float(a[2]) if len(a) > 2 else 10; end = time.time() + mins * 60; rc = 0
        while time.time() < end:
            rc = sync() or rc; time.sleep(20)
        sys.exit(rc)
    if a[0] == "send":
        m = json.loads(Path(a[1]).read_text()); sys.exit(sync([m]))
    if a[0] == "force":                 # include a call posted before the cutover (a still-valid older call)
        st = load(); st.setdefault("force", []).append(a[1]); save(st); sys.exit(sync())
    if a[0] == "status":
        st = load()
        for k, v in st["sent"].items():
            if not v["acked"] or not v.get("ok"): print(k, v)
        return
    print(__doc__)


if __name__ == "__main__":
    main()
