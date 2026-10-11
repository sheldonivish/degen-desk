#!/usr/bin/env bash
# Install / update the Degen Desk BTC autopilot on macOS.
#   bash install.sh             -> installs and starts in DRY-RUN (paper fills on live candles, nothing sent)
#   bash install.sh --live      -> installs and starts LIVE (signs and sends orders on Lighter)
#   bash install.sh --no-start  -> installs files only
# Never takes, prints or stores the API key: run.sh reads it from the Keychain at start (service degen-desk-lighter).
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST="$HOME/.degen-desk/autopilot"
LABEL="com.degendesk.autopilot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
MODE="--dry-run"; START=1
for a in "$@"; do
  case "$a" in --live) MODE="--live" ;; --dry-run) MODE="--dry-run" ;; --no-start) START=0 ;;
    *) echo "unknown argument $a (use --live, --dry-run, --no-start)"; exit 1 ;; esac
done
say() { printf '[autopilot] %s\n' "$*"; }
[ "$(uname -s)" = "Darwin" ] || { say "macOS only"; exit 1; }
command -v python3 >/dev/null || { say "python3 is required"; exit 1; }
KIT="$HOME/.agents/skills/lighter-agent-kit"
[ -f "$KIT/scripts/_sdk.py" ] || { say "Lighter agent kit not found at $KIT (run the Degen Desk lighter/install-local.sh first)"; exit 1; }

mkdir -p "$DST/course_engine" "$HOME/Library/LaunchAgents"; chmod 700 "$HOME/.degen-desk" "$DST"
# stop a running instance before replacing files
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
for f in autopilot.py strategy.py feed.py exchange.py notify.py trade_signal.py run.sh uninstall.sh config.default.json; do
  install -m 600 "$SRC/$f" "$DST/$f"
done
chmod 700 "$DST/run.sh" "$DST/uninstall.sh" "$DST/autopilot.py"
for f in engine.py setups.py sim.py; do install -m 600 "$SRC/course_engine/$f" "$DST/course_engine/$f"; done
[ -f "$DST/config.json" ] || install -m 600 "$SRC/config.default.json" "$DST/config.json"

# venv on the SAME python3 the lt runner uses, so the kit's vendored SDK (.vendor/pyX.Y) matches
if [ ! -x "$DST/venv/bin/python3" ]; then
  say "creating venv"; python3 -m venv "$DST/venv"
fi
"$DST/venv/bin/python3" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
"$DST/venv/bin/python3" -m pip install --quiet "numpy>=1.24" || { say "numpy install failed"; exit 1; }
say "checking the Lighter SDK through the kit"
"$DST/venv/bin/python3" "$KIT/scripts/bootstrap.py" 2>/dev/null | grep -q '"status": *"ok"' && say "SDK ok" || say "warning: kit bootstrap did not report ok"
"$DST/venv/bin/python3" -c "import sys; sys.path.insert(0,'$DST'); import strategy, feed, exchange; print('[autopilot] modules import ok')"
# account index + key slot (not secret) from the ~/.degen-desk/lt runner made by lighter/install-local.sh
LT="$HOME/.degen-desk/lt"
if [ -f "$LT" ] && [ -z "${LIGHTER_ACCOUNT_INDEX:-}" ]; then
  a="$(grep -oE '^ACCOUNT_INDEX="?[0-9]+' "$LT" | grep -oE '[0-9]+$' | head -n1 || true)"
  k="$(grep -oE '^API_KEY_INDEX="?[0-9]+' "$LT" | grep -oE '[0-9]+$' | head -n1 || true)"
  [ -n "$a" ] && export LIGHTER_ACCOUNT_INDEX="$a"
  [ -n "$k" ] && export LIGHTER_API_KEY_INDEX="$k"
fi
# keyless reachability checks from this Mac
"$DST/venv/bin/python3" - <<'PY'
import sys, os; sys.path.insert(0, os.path.expanduser("~/.degen-desk/autopilot"))
import feed as F, exchange as X
f, errs = F.pick_feed("binance"); print("[autopilot] candle source:", f and f.name, errs or "")
acct, kidx = os.environ.get("LIGHTER_ACCOUNT_INDEX"), os.environ.get("LIGHTER_API_KEY_INDEX")
if not acct or not kidx:
    print("[autopilot] warning: no account index / key slot found (run lighter/install-local.sh --account <INDEX> --slot <SLOT> first); the bot will not trade until they are set")
else:
    x = X.LighterExchange(int(acct), int(kidx))
    a = x.account(); print("[autopilot] Lighter reachable; BTC market", x.meta.market_id, "min size", x.meta.min_base, "| equity", a["equity"], "| BTC position", a["position"])
PY

sed -e "s#__HOME__#$HOME#g" -e "s#__MODE__#$MODE#g" "$SRC/com.degendesk.autopilot.plist" > "$PLIST"
chmod 644 "$PLIST"
if [ "$MODE" = "--live" ]; then
  say "LIVE mode: run.sh reads the key from the Keychain at start and the bot checks it against your account + slot before any order"
fi
rm -f "$DST/STOP"
if [ "$START" = 1 ]; then
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  say "started $LABEL in $MODE mode. Status: $DST/venv/bin/python3 $DST/autopilot.py status"
else
  say "installed (not started). Start: launchctl bootstrap gui/\$(id -u) $PLIST"
fi
say "Kill switch: $DST/venv/bin/python3 $DST/autopilot.py stop   (or: touch $DST/STOP)"
