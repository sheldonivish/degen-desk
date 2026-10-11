"""Optional Telegram notifier for the Degen Desk BTC autopilot (OFF by default).

Enable only for a chat the user approved for trade signals: config.json
  "telegram": {"enabled": true, "chat_id": <id>, "thread_id": null, "ops": false}
Token: macOS Keychain item (service degen-desk-telegram, account telegram) or TELEGRAM_BOT_TOKEN in the
environment. Never printed or logged.

Drop-in for the old notifier: autopilot.py still calls Telegram(chat_id, thread_id)(text). This version
recognises the autopilot's trade messages and posts them as signal cards (chart PNG + caption, via
trade_signal.py and matplotlib). If matplotlib/candles/sendPhoto fail it falls back to a text message.
  "G limit buy BTC ..."  -> NEW (pending limit)       "OPEN G long BTC ..." -> FILLED
  "OPEN <setup> long BTC ... @ ~ref ..." -> FILLED     "CLOSED ... (+1.9R, tp)" -> TP HIT / STOPPED / CLOSED
  "G limit cancelled ..." / "G limit expired ..."  -> CANCELLED (needs the 2-line autopilot.py patch)
Operational messages (started/paused/stopped/daily loss/entry not placed) are NOT posted to the group
unless telegram.ops is true; they include account equity, which stays private. "Equity ..." is always
stripped. Sends run on a background thread so the trading loop never waits on Telegram.
"""
import html, json, os, re, subprocess, sys, threading, time, urllib.error, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "notify_state.json"         # last signal per side, so CLOSED can redraw entry/stop/tp
LOG = HERE / "notify.log"
DISCLAIMER = "Auto-traded by Degen Desk · Not financial advice"
SETUP_NAMES = {"G": "Limit entry at a fresh demand/supply zone"}   # other setup codes are shown as-is
TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
NUM = r"([0-9][0-9.,]*)"


def _token():
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if t:
        return t
    if sys.platform == "darwin":
        r = subprocess.run(["security", "find-generic-password", "-s", "degen-desk-telegram", "-a", "telegram", "-w"],
                           capture_output=True, text=True)
        return r.stdout.strip()
    return ""


def _scrub(s):
    return TOKEN_RE.sub("bot<TOKEN>", str(s))[:200]


def _log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + _scrub(msg) + "\n")
    except Exception:
        pass


def _f(x):
    return float(str(x).replace(",", ""))


# ------------------------------------------------------------------ parse autopilot messages
def parse(text):
    """Return a signal dict for trade messages, or None for operational ones."""
    m = re.match(rf"G limit (buy|sell) BTC {NUM} @ {NUM} \| SL {NUM} TP {NUM}(?: \(expires (.+?) UTC\))?", text)
    if m:
        return dict(kind="NEW", side="long" if m[1] == "buy" else "short", size=_f(m[2]), entry=_f(m[3]),
                    stop=_f(m[4]), tp=_f(m[5]), setup="G", order=f"{m[1].capitalize()} limit",
                    note=f"Order expires {m[6]} UTC if unfilled" if m[6] else None)
    m = re.match(rf"OPEN (\S+) (long|short) BTC {NUM} @ ~?{NUM} \| SL {NUM} TP {NUM}"
                 rf"(?: \| risk \${NUM} \(([0-9.]+)%\))?", text)
    if m:
        return dict(kind="FILLED", setup=m[1], side=m[2], size=_f(m[3]), entry=_f(m[4]), stop=_f(m[5]), tp=_f(m[6]),
                    risk_usd=_f(m[7]) if m[7] else None, risk_pct=float(m[8]) if m[8] else None)
    m = re.match(r"CLOSED (\S+) (long|short) BTC: ([+-][0-9.,]+) USD \(([+-][0-9.]+)R, (\w+)\)", text)
    if m:
        reason = m[5]
        kind = "TP HIT" if reason == "tp" else "STOPPED" if reason == "sl" else "CLOSED"
        return dict(kind=kind, setup=m[1], side=m[2], pnl_usd=_f(m[3]), r_multiple=float(m[4]), reason=reason)
    m = re.match(r"G limit (cancelled|expired)\b(.*)", text)
    if m:
        return dict(kind="CANCELLED", setup="G", why=m[2].strip(" :()") or m[1])
    return None


def _load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save_state(st):
    try:
        STATE.write_text(json.dumps(st))
    except Exception:
        pass


# ------------------------------------------------------------------ Telegram
class Telegram:
    def __init__(self, chat_id, thread_id=None, ops=False, charts=True):
        self.chat_id, self.thread_id, self.ops, self.charts = chat_id, thread_id, ops, charts
        self.tok = _token()

    def __call__(self, text):
        if not self.tok:
            raise RuntimeError("no Telegram token")
        sig = parse(text)
        if sig is None and not self.ops:
            return None                                  # operational message: not for the group
        threading.Thread(target=self._deliver, args=(text, sig), daemon=True).start()
        return True

    # --- delivery (background thread) ---
    def _deliver(self, text, sig):
        try:
            if sig is None:
                self._send_text("[Degen Desk autopilot] " + re.sub(r"\s*Equity [0-9.,]+\.?", "", text))
                return
            full = self._complete(sig)
            if full is None:                                 # nothing to draw (e.g. close without a known open)
                self._send_text(html.escape(re.sub(r"\s*Equity [0-9.,]+\.?", "", text)) + f"\n\n<i>{DISCLAIMER}</i>",
                                parse_mode="HTML")
                return
            caption = self._caption(full)
            png = self._chart(full) if self.charts else None
            if png:
                try:
                    self._send_photo(png, caption)
                    return
                except Exception as e:
                    _log(f"sendPhoto failed, falling back to text: {e}")
            self._send_text(caption, parse_mode="HTML")
        except Exception as e:
            _log(f"notify failed: {e}")

    def _complete(self, sig):
        """Merge with the remembered open signal so closes/cancels can show entry/stop/tp."""
        st = _load_state()
        if sig["kind"] in ("NEW", "FILLED"):
            prev = st.get("last") or {}
            if sig["kind"] == "FILLED" and prev.get("kind") == "NEW" and prev.get("side") == sig["side"]:
                sig = {**{k: v for k, v in prev.items() if k in ("risk_usd", "risk_pct", "order")}, **{k: v for k, v in sig.items() if v is not None}}
            st["last"] = sig; _save_state(st)
            return sig
        prev = st.get("last")
        if not prev:
            return None
        merged = {**prev, **{k: v for k, v in sig.items() if v is not None}}
        st["last"] = None; _save_state(st)
        return merged

    def _caption(self, s):
        import trade_signal as TS
        kind = s["kind"]
        status = kind if kind in TS.STATUSES else "STOPPED" if (s.get("pnl_usd") or 0) < 0 else "TP HIT"
        if kind == "CLOSED":                          # time exit etc.: label it honestly
            status = "TP HIT" if (s.get("pnl_usd") or 0) >= 0 else "STOPPED"
        exit_px = None
        if s.get("r_multiple") is not None and s.get("entry") and s.get("stop"):
            risk = abs(s["entry"] - s["stop"])
            exit_px = s["entry"] + (1 if s["side"] == "long" else -1) * s["r_multiple"] * risk
        notional = s["size"] * s["entry"] if s.get("size") and s.get("entry") else None
        reason = None
        if kind == "CANCELLED":
            why = (s.get("why") or "").strip()
            reason = "Limit order removed before it filled; no position was opened." + \
                (f" ({why})" if why and "not filled" not in why and why not in ("expired", "cancelled") else "")
        elif kind == "CLOSED":
            reason = f"Closed by {s.get('reason')} exit."
        cap = TS.build_caption(s["side"], s["entry"], s["stop"], s["tp"], status=status, size=s.get("size"),
                               notional=notional, risk_pct=s.get("risk_pct"), risk_usd=s.get("risk_usd"),
                               setup=SETUP_NAMES.get(s.get("setup"), s.get("setup")), reason=reason,
                               order=s.get("order"), note=s.get("note") if kind == "NEW" else None,
                               exit_px=exit_px, pnl_usd=s.get("pnl_usd"), r_multiple=s.get("r_multiple"))
        s["_status"], s["_exit"] = status, exit_px
        return cap

    def _chart(self, s):
        try:
            import trade_signal as TS
            candles = TS.fetch_candles(limit=192)
            out = HERE / "signals" / f"{time.strftime('%Y%m%d_%H%M%S')}_{s['side']}_{s['_status'].replace(' ', '').lower()}.png"
            return TS.render_chart(candles, s["side"], s["entry"], s["stop"], s["tp"], out,
                                   status=s["_status"], exit_px=s.get("_exit"))
        except Exception as e:                          # no matplotlib, no network, ... -> text fallback
            _log(f"chart failed: {e}")
            return None

    # --- raw Bot API ---
    def _post(self, method, data, ctype, timeout=20):
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.tok}/{method}", data=data,
                                     headers={"Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read())
            except Exception:
                raise RuntimeError(_scrub(f"HTTP {e.code}")) from None
        except Exception as e:
            raise RuntimeError(_scrub(e)) from None
        if not body.get("ok"):
            raise RuntimeError(_scrub(f"{body.get('error_code')}: {body.get('description')}"))
        _log(f"{method} ok message_id={body['result'].get('message_id')}")
        return body["result"]

    def _send_text(self, text, parse_mode=None):
        body = {"chat_id": self.chat_id, "text": text[:4000], "link_preview_options": {"is_disabled": True}}
        if parse_mode:
            body["parse_mode"] = parse_mode
        if self.thread_id:
            body["message_thread_id"] = self.thread_id
        return self._post("sendMessage", json.dumps(body).encode(), "application/json", timeout=10)

    def _send_photo(self, path, caption):
        b = "----degendesk" + os.urandom(8).hex()
        fields = {"chat_id": str(self.chat_id), "caption": caption, "parse_mode": "HTML"}
        if self.thread_id:
            fields["message_thread_id"] = str(self.thread_id)
        out = bytearray()
        for k, v in fields.items():
            out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        out += (f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="{Path(path).name}"\r\n'
                f"Content-Type: image/png\r\n\r\n").encode() + Path(path).read_bytes() + b"\r\n"
        out += f"--{b}--\r\n".encode()
        return self._post("sendPhoto", bytes(out), f"multipart/form-data; boundary={b}", timeout=30)
