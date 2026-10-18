#!/usr/bin/env bash
# Is this server allowed to reach the venues? Prints location + HTTP codes. Run on the server BEFORE adding any key.
# A 403/451 or a "restricted jurisdiction" body means: do not trade from here (never route around it with a VPN/proxy).
set -u
echo "location: $(curl -s --max-time 8 https://ipinfo.io/json | jq -r '"\(.city), \(.country) (\(.org))"' 2>/dev/null)"
for u in https://mainnet.zklighter.elliot.ai/api/v1/orderBooks https://app.lighter.xyz \
         https://api.hyperliquid.xyz/info https://api.popdex.xyz/api/v1/public/market/tickers?category=Futures \
         https://www.okx.com/api/v5/public/time https://api.arcus.xyz/health https://api.arcus.xyz/v1/markets; do
  if [[ $u == *hyperliquid* ]]; then c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H 'Content-Type: application/json' -d '{"type":"meta"}' "$u")
  else c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$u"); fi
  echo "$c  $u"
done
