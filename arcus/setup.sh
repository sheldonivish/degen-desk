#!/usr/bin/env bash
# Assemble the Arcus BTC autopilot into a folder (default /opt/arcus-desk) from this repo checkout.
# Shared logic (strategy, course engine, candle feed, Telegram notify) comes from ../autopilot.
# Run from the repo root:  sudo DEST=/opt/arcus-desk bash arcus/setup.sh
# It never writes keys. Put ARCUS_API_KEY, ARCUS_SIGNING_KEY, ARCUS_ADDRESS, ARCUS_ACCOUNT_INDEX into
# $DEST/.env yourself (chmod 600, via the secure secret form) and TELEGRAM_BOT_TOKEN into $DEST/telegram.env.
set -euo pipefail
DEST="${DEST:-/opt/arcus-desk}"
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
mkdir -p "$DEST"
cp "$ROOT"/autopilot/{strategy.py,feed.py,notify.py} "$DEST"/
cp -r "$ROOT"/autopilot/course_engine "$DEST"/
cp "$HERE"/{autopilot.py,exchange.py,exchange_arcus.py,trade_signal.py} "$DEST"/
[ -f "$DEST/config.json" ] || cp "$HERE/config.default.json" "$DEST/config.json"
cp "$HERE/config.default.json" "$DEST/config.default.json"
if [ ! -d "$DEST/venv" ]; then
  python3 -m venv "$DEST/venv"
  "$DEST/venv/bin/pip" install -q numpy matplotlib cryptography websockets requests
fi
for f in .env telegram.env; do [ -f "$DEST/$f" ] && chmod 600 "$DEST/$f"; done
id degen >/dev/null 2>&1 && chown -R degen:degen "$DEST" && chmod 700 "$DEST"
"$DEST/venv/bin/python" -m py_compile "$DEST"/*.py && echo "OK: $DEST (practice mode until you switch the unit to --live)"
