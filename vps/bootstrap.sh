#!/usr/bin/env bash
# Run ONCE on a fresh Ubuntu 22.04/24.04 server as root, AFTER your public key is in /root/.ssh/authorized_keys
# and you have confirmed a key login works. Usage: PUBKEY="ssh-ed25519 AAAA... degen-desk" bash bootstrap.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
if [ -n "${PUBKEY:-}" ]; then
  install -d -m 700 /root/.ssh; touch /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys
  grep -qF "$PUBKEY" /root/.ssh/authorized_keys || echo "$PUBKEY" >> /root/.ssh/authorized_keys
fi
[ -s /root/.ssh/authorized_keys ] || { echo "no authorized key: refusing to disable passwords"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq python3-venv python3-pip ufw curl jq >/dev/null
id degen >/dev/null 2>&1 || useradd -m -s /bin/bash degen          # bots run as this unprivileged user
install -d -o degen -g degen -m 700 /opt/degen-desk /opt/popdex-mm
# firewall: SSH only, nothing listens publicly
ufw allow OpenSSH >/dev/null; ufw --force enable >/dev/null
# key-only SSH
cat > /etc/ssh/sshd_config.d/10-degen-hardening.conf <<'C'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
C
sshd -t && (systemctl reload ssh 2>/dev/null || systemctl reload sshd)
timedatectl set-ntp true || true
echo "OK: user degen, ufw on (SSH only), password login off. The provider's web console still works if you get locked out."
