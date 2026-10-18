# Running Degen Desk bots on a VPS

For venues that block the bot's cloud computer but are allowed where the server sits (check first; never use a VPN or
proxy to get around a block). Tested on Vultr High Frequency 1 vCPU / 2 GB / Ubuntu 24.04; three bots use < 300 MB.

1. **Server**: Ubuntu 24.04 LTS, a region where the venue's terms allow trading. Add your SSH public key at creation
   (`python vps.py keygen` makes one if the box has no ssh-keygen). If the key wasn't added, use the root password once,
   from a secret store, to install the key.
2. **Harden**: `PUBKEY="$(cat ~/.ssh/degen_vps.pub)" bash bootstrap.sh` on the server: user `degen`, ufw SSH-only,
   password login off. The provider's web console stays as the fallback.
3. **Geo check**: `bash geo_check.sh`. Only continue if the venue answers 200 and its terms allow the location.
4. **Code**: copy `autopilot/*` (+ `calls/calls_exec.py`) to `/opt/degen-desk`, `popdex-mm/` to `/opt/popdex-mm`, the Arcus autopilot to
   `/opt/arcus-desk` (`arcus/setup.sh`, see `arcus/README.md`), make the venvs, `chown -R degen:degen`.
5. **Secrets**: only in `/opt/degen-desk/.env` and `telegram.env` (chmod 600, owner degen), or
   `/opt/popdex-mm/secrets/agent_key.json` (chmod 600). The owner pastes keys through a secure secret form, never chat.
   Never print, log or commit them (`exchange.redact` scrubs logs).
6. **Services**: copy `systemd/*.service` to `/etc/systemd/system/`, `systemctl daemon-reload && systemctl enable --now ...`.
   Everything starts in practice/shadow mode. Live = the drop-in `.conf` (or `--live`) only after the owner says so.
7. **One live instance per account**: before going live, stop any other copy (e.g. a launchd agent on the owner's Mac)
   so orders can't double up. Check `systemctl is-active`, the account's open orders and positions.
8. Cleanup cron for recordings: `systemd/popdex-mm-cleanup.cron` -> `/etc/cron.d/`.
