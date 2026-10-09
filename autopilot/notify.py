"""Optional Telegram notifier for trade opens/closes (OFF by default).
Enable only for a chat the user approved for trade alerts: set config.json telegram.enabled=true and chat_id.
Token: macOS Keychain item (service degen-desk-telegram, account telegram) or TELEGRAM_BOT_TOKEN in the
environment. Never printed or logged."""
import json, os, re, subprocess, sys, urllib.request


def _token():
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if t:
        return t
    if sys.platform == "darwin":
        r = subprocess.run(["security", "find-generic-password", "-s", "degen-desk-telegram", "-a", "telegram", "-w"],
                           capture_output=True, text=True)
        return r.stdout.strip()
    return ""


class Telegram:
    def __init__(self, chat_id, thread_id=None):
        self.chat_id, self.thread_id = chat_id, thread_id
        self.tok = _token()

    def __call__(self, text):
        if not self.tok:
            raise RuntimeError("no Telegram token")
        body = {"chat_id": self.chat_id, "text": "[Degen Desk autopilot] " + text, "disable_web_page_preview": True}
        if self.thread_id:
            body["message_thread_id"] = self.thread_id
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.tok}/sendMessage", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("ok")
        except Exception as e:
            raise RuntimeError(re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot<TOKEN>", str(e))[:160])
