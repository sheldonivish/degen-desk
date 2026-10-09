#!/usr/bin/env bash
# Stop and remove the autopilot launchd job. By default it first runs the kill switch (cancel BTC orders, close
# the BTC position) and keeps logs/trades. --keep-position skips the kill switch; --purge also deletes the folder.
set -euo pipefail
DST="$HOME/.degen-desk/autopilot"; LABEL="com.degendesk.autopilot"; PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
KEEP=0; PURGE=0
for a in "$@"; do case "$a" in --keep-position) KEEP=1 ;; --purge) PURGE=1 ;; esac; done
if [ "$KEEP" = 0 ] && launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  "$DST/venv/bin/python3" "$DST/autopilot.py" stop || true
fi
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "[autopilot] launchd job removed. Logs kept in $DST (log.jsonl, trades.csv)."
if [ "$PURGE" = 1 ]; then rm -rf "$DST"; echo "[autopilot] removed $DST"; fi
