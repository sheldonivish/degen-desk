#!/usr/bin/env bash
# Degen Desk x Lighter: set up live Lighter trading on YOUR OWN computer (macOS, Linux or Windows via WSL).
#
#   curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/lighter/install-local.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/lighter/install-local.sh | bash -s -- --account <INDEX> --slot <SLOT>
#
# What it does (safe to re-run):
#   1. Installs Lighter's official agent kit (code + pinned SDK only) to ~/.agents/skills/lighter-agent-kit,
#      unless it's already there. It does NOT run the kit's credential prompt.
#   2. Downloads Degen Desk's gated Lighter script to ~/.degen-desk/desk_lighter.py
#      (deliberately not "lighter.py", which would shadow the SDK) and the ~/.degen-desk/lt runner.
#   3. Fills in your account index and key slot (not secrets) if you pass them, and runs a keyless read.
#   4. Prints how to store your API private key yourself (macOS Keychain, or your shell profile on Linux).
#
# It never asks for, accepts or stores your API private key, wallet key or seed phrase.
# Lighter blocks some countries (https://lighter.xyz/terms). Only use it where you're allowed; never via VPN or proxy.
# Env (optional): DD_RAW (base URL for the files), LIGHTER_KIT_DIR, DD_HOME (default ~/.degen-desk), DD_SKIP_TEST=1.
set -euo pipefail

DD_RAW="${DD_RAW:-https://raw.githubusercontent.com/sheldonivish/degen-desk/main}"
DD_HOME="${DD_HOME:-$HOME/.degen-desk}"
KIT_DIR="${LIGHTER_KIT_DIR:-$HOME/.agents/skills/lighter-agent-kit}"
KIT_REPO="https://github.com/elliottech/lighter-agent-kit.git"

say()  { printf '[degen-desk/lighter] %s\n' "$*"; }
die()  { printf '[degen-desk/lighter] ERROR: %s\n' "$*" >&2; exit 1; }

ACCOUNT=""; SLOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --account) [ $# -ge 2 ] || die "--account needs a number"; ACCOUNT="$2"; shift 2 ;;
    --slot)    [ $# -ge 2 ] || die "--slot needs a number"; SLOT="$2"; shift 2 ;;
    -h|--help) sed -n '2,19p' "$0" 2>/dev/null || true; exit 0 ;;
    *) die "unknown argument. This installer only takes --account <index> and --slot <4-254>. Never pass your API key, wallet key or seed phrase to any command." ;;
  esac
done
case "$ACCOUNT" in ""|*[!0-9]*) [ -z "$ACCOUNT" ] || die "--account must be a whole number (your Lighter account index)" ;; esac
case "$SLOT" in
  "") ;;
  *[!0-9]*) die "--slot must be a whole number from 4 to 254" ;;
  *) { [ "$SLOT" -ge 4 ] && [ "$SLOT" -le 254 ]; } || die "--slot must be 4-254 (0-3 are Lighter's own apps)" ;;
esac

OS="$(uname -s)"
case "$OS" in
  Darwin|Linux) ;;
  MINGW*|MSYS*|CYGWIN*) die "on Windows, run this inside WSL (Ubuntu) instead of Git Bash" ;;
  *) die "unsupported OS: $OS" ;;
esac
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required (macOS: xcode-select --install, or python.org)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "Python 3.9+ is required"

# 1. Official kit (code only)
if [ -f "$KIT_DIR/SKILL.md" ] && [ -f "$KIT_DIR/scripts/_sdk.py" ]; then
  say "Lighter agent kit already installed at $KIT_DIR (kept as is)"
else
  command -v git >/dev/null 2>&1 || die "git is required to fetch the Lighter agent kit (macOS: xcode-select --install)"
  [ ! -e "$KIT_DIR" ] || die "$KIT_DIR exists but looks incomplete; move it aside and re-run"
  say "installing Lighter's official agent kit to $KIT_DIR"
  mkdir -p "$(dirname "$KIT_DIR")"
  git clone --quiet --depth 1 --single-branch "$KIT_REPO" "$KIT_DIR" || die "git clone of $KIT_REPO failed"
  [ -f "$KIT_DIR/SKILL.md" ] || { rm -rf "$KIT_DIR"; die "kit clone looks incomplete"; }
fi
say "checking the Lighter SDK (first run downloads pinned dependencies)"
if python3 "$KIT_DIR/scripts/bootstrap.py" 2>/dev/null | grep -q '"status": *"ok"'; then
  say "SDK ready"
else
  say "warning: SDK bootstrap didn't report ok; retry later with: python3 $KIT_DIR/scripts/bootstrap.py"
fi

# 2. Degen Desk script + runner
mkdir -p "$DD_HOME"; chmod 700 "$DD_HOME"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
curl -fsSL --retry 3 "$DD_RAW/lighter.py" -o "$tmp/desk_lighter.py" || die "download of lighter.py failed"
curl -fsSL --retry 3 "$DD_RAW/lighter/lt" -o "$tmp/lt" || die "download of lighter/lt failed"
grep -q 'Degen Desk x Lighter' "$tmp/desk_lighter.py" || die "downloaded lighter.py doesn't look right"
grep -q '__ACCOUNT_INDEX__' "$tmp/lt" || die "downloaded lt doesn't look right"
python3 -m py_compile "$tmp/desk_lighter.py" 2>/dev/null || die "downloaded lighter.py doesn't compile"
rm -rf "$tmp/__pycache__"

# keep values from an existing runner unless new ones were passed
if [ -f "$DD_HOME/lt" ]; then
  old_acct="$(grep -oE '(^ACCOUNT_INDEX|LIGHTER_ACCOUNT_INDEX)=["'"'"']?[0-9]+' "$DD_HOME/lt" | grep -oE '[0-9]+$' | head -n 1 || true)"
  old_slot="$(grep -oE '(^API_KEY_INDEX|LIGHTER_API_KEY_INDEX)=["'"'"']?[0-9]+' "$DD_HOME/lt" | grep -oE '[0-9]+$' | head -n 1 || true)"
  [ -n "$ACCOUNT" ] || ACCOUNT="$old_acct"
  [ -n "$SLOT" ] || SLOT="$old_slot"
  cp -p "$DD_HOME/lt" "$DD_HOME/lt.bak"
  say "kept a copy of your previous runner as $DD_HOME/lt.bak"
fi
[ -z "$ACCOUNT" ] || sed -i.bak "s/__ACCOUNT_INDEX__/$ACCOUNT/" "$tmp/lt"
[ -z "$SLOT" ] || sed -i.bak "s/__API_KEY_INDEX__/$SLOT/" "$tmp/lt"
rm -f "$tmp/lt.bak"

if [ -f "$DD_HOME/lighter.py" ]; then
  mv "$DD_HOME/lighter.py" "$DD_HOME/lighter.py.old"
  say "renamed an old $DD_HOME/lighter.py to lighter.py.old (that name shadows the SDK)"
fi
install -m 700 "$tmp/desk_lighter.py" "$DD_HOME/desk_lighter.py"
install -m 700 "$tmp/lt" "$DD_HOME/lt"
say "installed $DD_HOME/desk_lighter.py and $DD_HOME/lt"

# 3. Keyless smoke test
if [ "${DD_SKIP_TEST:-0}" != "1" ]; then
  if out="$("$DD_HOME/lt" markets --search BTC 2>&1)" && printf '%s' "$out" | grep -q '"symbol"'; then
    say "read test OK (Lighter markets reachable from this computer)"
  else
    say "warning: the keyless read test failed:"; printf '%s\n' "$out" | head -n 8
  fi
fi

# 4. Next steps
echo
say "Next steps (you do these; never paste keys into chat):"
echo "  1. In the Lighter app, use a sub-account holding only your trading money, then create an API key"
echo "     in slot 4-254 at https://app.lighter.xyz/apikeys (switch to that sub-account first)."
if [ -z "$ACCOUNT" ] || [ -z "$SLOT" ]; then
  echo "  2. Re-run this installer with: bash -s -- --account <INDEX> --slot <SLOT>   (both are not secret)"
else
  echo "  2. Runner set to account $ACCOUNT, key slot $SLOT."
fi
if [ "$OS" = "Darwin" ]; then
  echo "  3. Store the API private key in your macOS Keychain. In Terminal, run:"
  echo "       security add-generic-password -U -a lighter -s degen-desk-lighter -w"
  echo "     and paste the key twice when asked (nothing shows while you paste). If a Keychain prompt"
  echo "     appears the first time it's used, click Always Allow."
else
  echo "  3. Add this line to your own shell profile (~/.bashrc or ~/.zshrc) in a text editor, then chmod 600 it:"
  echo "       export LIGHTER_API_PRIVATE_KEY=<your API private key>"
  echo "     (type it in the editor yourself, not on the command line, so it stays out of shell history)."
fi
echo "  4. Check it (sends nothing):  $DD_HOME/lt keycheck --live"
echo "  Reads: $DD_HOME/lt markets | book BTC | funding BTC | positions"
echo "  Trades: $DD_HOME/lt preview open BTC --side long --stop <price>, approve the exact terms, then"
echo "          $DD_HOME/lt place --approve <CODE> --live  (sends once; withdrawals and transfers are blocked)."
say "OK"
