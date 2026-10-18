---
name: vps-bot-deploy
description: >-
  Use when the owner wants a trading bot (Lighter call executor, BTC autopilot on
  Lighter or Arcus, PopDEX market maker or similar) to run 24/7 on their own Ubuntu VPS (e.g. Vultr):
  pick the server, connect by key-only SSH (paramiko if the box has no ssh), check
  the venue is reachable and allowed there, harden it, install systemd services in
  practice mode, and switch to live only on the owner's explicit yes.
---
# Deploy a trading bot to a VPS

Code templates: degen-desk repo `vps/` (vps.py, bootstrap.sh, geo_check.sh, systemd/); Arcus autopilot: `arcus/` (see `arcus-autopilot`). Not financial advice.

## 1. Server
- Recommend a small plan: 1 vCPU, 2 GB RAM, NVMe (e.g. Vultr High Frequency, ~$12/month) running **Ubuntu 24.04 LTS**,
  in a region where the venue's terms allow trading. The owner buys it themselves; a payment needs their approval of the exact total.
- Ask them to add an SSH public key at creation. If the box has no `ssh`/`ssh-keygen`, make a venv with `paramiko` +
  `cryptography` and run `vps.py keygen` (ed25519, chmod 600). Give the owner only the `.pub` line.
- If the key wasn't added, collect the root password once through the secure secret form (never chat), log in with it
  only to install the key, then disable passwords. Never print, echo or log a password or key.

## 2. Reachability before any key
Run `geo_check.sh` on the server: ipinfo location, then HTTP codes for the venue APIs (Lighter mainnet API, app,
Hyperliquid, PopDEX, OKX, Arcus `https://api.arcus.xyz/health` and `/v1/markets`). Continue only on 200s and if the venue's terms allow that country. A geo-block
(403/451/"restricted jurisdiction") is final: never suggest a VPN, proxy or another region to dodge it without the owner
checking the terms.

## 3. Harden
`PUBKEY=... bash bootstrap.sh` as root after confirming a key login works: unprivileged user `degen`, ufw SSH-only (no open
ports), `PasswordAuthentication no`, `PermitRootLogin prohibit-password`, NTP on. Tell the owner the password no longer works
for SSH and the provider's web console is the fallback.

## 4. Install
- Code in `/opt/<bot>` owned by `degen`, its own venv, `chown -R degen:degen`.
- Secrets only in `EnvironmentFile`s (`/opt/<bot>/.env`, `telegram.env`) or a key JSON under `secrets/`, all chmod 600,
  owner `degen`. The owner pastes keys through the secure form; you write the file without printing it. Logs go through a
  redact helper. Never commit or copy secrets into skills, memory or the repo.
- One systemd unit per bot (`Restart=always`, `MemoryMax`), `systemctl enable --now`. Verify `is-active`, the
  `journalctl` tail and a read-only check (balance, open orders) with the key.
- Big recordings: add a cron cleanup (e.g. delete files older than 7 days) after the owner agrees.

## 5. Practice -> live
- Every bot starts in practice/shadow/dry-run. Live is a separate, explicit flag: a systemd drop-in (`CALLS_LIVE=1`,
  `POPDEX_LIVE=1`) or `--live` (Arcus: `autopilot.py run --dry-run` -> `run --live`), installed only after the owner says "go live" for that bot and account.
- **One live instance per account**: before switching, find and stop every other copy (owner's Mac launchd agent, an old
  service). Two copies double positions. Check the account has no unexpected positions/orders first, and ask about any
  position the bot didn't open.
- Two bots on the same signals (e.g. Lighter and Arcus autopilots): cap combined open risk across venues with a shared
  risk ledger file; if the other bot's state is unreadable or stale, assume it is at its full cap.
- Arcus: set exchange leverage to the cap with signed setLeverage before going live (accounts default to the exchange max),
  and place one tiny test trade to confirm SL/TP attach.
- After switching: confirm the service is active, the balance reads, nothing unexpected is resting. Report once.
- Kill switch: `touch /opt/<bot>/STOP` or `systemctl stop <unit>`; tell the owner "stop the bot" works anytime.

## 6. Operating it
Reach the server through `vps.py` (key auth) for status, logs and deploys. Back up a file before patching it, parse-check
Python before restarting, restart one service at a time and confirm open orders survived. Report only meaningful changes:
fills, exits, pauses, blockers.
