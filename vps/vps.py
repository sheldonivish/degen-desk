#!/usr/bin/env python3
"""Tiny SSH/SFTP helper for boxes without an ssh client (paramiko only, key auth only).

  DD_VPS_HOST=<ip> python vps.py 'systemctl is-active degen-calls'      run a command, print tail + exit code
  DD_VPS_HOST=<ip> python vps.py put LOCAL REMOTE                         upload one file
  python vps.py keygen                                                    make ~/.ssh/degen_vps (+ .pub), ed25519

Env: DD_VPS_HOST (required), DD_VPS_USER (root), DD_VPS_KEY (~/.ssh/degen_vps).
First login with a password only if the provider gave you one: DD_VPS_PASSWORD from a secret store, never typed in chat;
install the key, then disable password login (bootstrap.sh) and drop the password.
"""
import os, sys
import paramiko

HOST = os.environ.get("DD_VPS_HOST", "")
USER = os.environ.get("DD_VPS_USER", "root")
KEY = os.path.expanduser(os.environ.get("DD_VPS_KEY", "~/.ssh/degen_vps"))


def keygen():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization as S
    if os.path.exists(KEY): sys.exit(f"{KEY} exists; not overwriting")
    os.makedirs(os.path.dirname(KEY), mode=0o700, exist_ok=True)
    k = Ed25519PrivateKey.generate()
    open(KEY, "wb").write(k.private_bytes(S.Encoding.PEM, S.PrivateFormat.OpenSSH, S.NoEncryption())); os.chmod(KEY, 0o600)
    pub = k.public_key().public_bytes(S.Encoding.OpenSSH, S.PublicFormat.OpenSSH).decode() + " degen-desk"
    open(KEY + ".pub", "w").write(pub + "\n"); print(pub)


def conn():
    if not HOST: sys.exit("set DD_VPS_HOST")
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pw = os.environ.get("DD_VPS_PASSWORD")
    if pw and not os.path.exists(KEY):
        c.connect(HOST, username=USER, password=pw, look_for_keys=False, allow_agent=False, timeout=20)
    else:
        c.connect(HOST, username=USER, key_filename=KEY, look_for_keys=False, allow_agent=False, timeout=20)
    return c


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    if a[0] == "keygen": keygen(); sys.exit()
    c = conn()
    if a[0] == "put":
        s = c.open_sftp(); s.put(a[1], a[2]); s.close(); print("put ok"); sys.exit()
    _, o, e = c.exec_command(a[0], timeout=900)
    out, err = o.read().decode(errors="replace"), e.read().decode(errors="replace")
    print(out[-6000:]); print("ERR:", err[-3000:]) if err.strip() else None
    print("rc", o.channel.recv_exit_status())
