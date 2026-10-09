#!/usr/bin/env bash
# launchd entry point for the Degen Desk BTC autopilot. Usage: run.sh --live | --dry-run
# The Lighter API key is read from the macOS login Keychain (service degen-desk-lighter, account lighter) ONLY with
# --live, exported to the python process environment, never printed, logged, or written to a file.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:---dry-run}"
PY="$DIR/venv/bin/python3"; [ -x "$PY" ] || PY="$(command -v python3)"
# account index + key slot (not secret) from the existing ~/.degen-desk/lt runner when present
LT="$HOME/.degen-desk/lt"
if [ -f "$LT" ]; then
  a="$(grep -oE '^ACCOUNT_INDEX="?[0-9]+' "$LT" | grep -oE '[0-9]+$' | head -n1 || true)"
  k="$(grep -oE '^API_KEY_INDEX="?[0-9]+' "$LT" | grep -oE '[0-9]+$' | head -n1 || true)"
  [ -n "$a" ] && export LIGHTER_ACCOUNT_INDEX="$a"
  [ -n "$k" ] && export LIGHTER_API_KEY_INDEX="$k"
fi
unset LIGHTER_API_PRIVATE_KEY LIGHTER_ETH_PRIVATE_KEY
if [ "$MODE" = "--live" ]; then
  if ! k="$(security find-generic-password -s degen-desk-lighter -a lighter -w 2>/dev/null)" || [ -z "$k" ]; then
    echo '{"error": "no Lighter key in the macOS Keychain (service degen-desk-lighter); not trading"}'
    exit 0      # clean exit: launchd does not restart-loop
  fi
  export LIGHTER_API_PRIVATE_KEY="$k"; unset k
fi
cd "$DIR"
# autopilot.py itself starts `caffeinate -i -s -w <its pid>` so the Mac stays awake exactly while it runs
exec "$PY" "$DIR/autopilot.py" run "$MODE"
