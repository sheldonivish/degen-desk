#!/usr/bin/env bash
# Degen Desk installer / updater. Safe to re-run.
#   curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/install.sh | bash
# Env:
#   TARGET   install folder (default /workspace/trenches)
#   DD_REPO  git URL to install from (default https://github.com/sheldonivish/degen-desk.git)
#   DD_REF   branch (default main)
#   DD_SRC   install from a local folder instead of GitHub (for testing)
# Never overwrites your data: calls.jsonl, dex_cache.json, runs/, lists.txt, telegram/config.json.
set -euo pipefail

TARGET="${TARGET:-/workspace/trenches}"
DD_REPO="${DD_REPO:-https://github.com/sheldonivish/degen-desk.git}"
DD_REF="${DD_REF:-main}"
DD_SRC="${DD_SRC:-}"

say() { printf '[degen-desk] %s\n' "$*"; }
die() { printf '[degen-desk] ERROR: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "Python 3.9+ is required"

is_protected() {   # user data that must never be overwritten
  case "$1" in
    calls.jsonl|dex_cache.json|lists.txt|telegram/config.json|runs|runs/*|.git|.git/*) return 0 ;;
    *) return 1 ;;
  esac
}

# Copy package files from $1 into $TARGET without touching user data.
# Code files that differ are backed up once as <file>.bak before being replaced.
copy_in() {
  local src="$1" rel
  mkdir -p "$TARGET"
  (cd "$src" && find . -type f ! -path './.git/*' ! -path '*/__pycache__/*' | sed 's|^\./||') | while IFS= read -r rel; do
    is_protected "$rel" && continue
    mkdir -p "$TARGET/$(dirname "$rel")"
    if [ -f "$TARGET/$rel" ] && ! cmp -s "$src/$rel" "$TARGET/$rel"; then
      cp -p "$TARGET/$rel" "$TARGET/$rel.bak"
      say "updated $rel (previous copy saved as $rel.bak)"
    fi
    cp -p "$src/$rel" "$TARGET/$rel"
  done
}

fetch_src() {   # prints a temp folder holding the package
  local tmp; tmp="$(mktemp -d)"
  if command -v git >/dev/null 2>&1; then
    git clone --quiet --depth 1 --branch "$DD_REF" "$DD_REPO" "$tmp/pkg" >&2 || die "git clone of $DD_REPO failed"
  else
    local tarball="${DD_REPO%.git}/archive/refs/heads/$DD_REF.tar.gz"
    mkdir -p "$tmp/pkg"
    curl -fsSL "$tarball" | tar -xz -C "$tmp/pkg" --strip-components 1 || die "download of $tarball failed"
  fi
  printf '%s\n' "$tmp/pkg"
}

if [ -n "$DD_SRC" ]; then
  [ -f "$DD_SRC/fetch.py" ] || die "DD_SRC=$DD_SRC does not contain fetch.py"
  say "installing from local folder $DD_SRC into $TARGET"
  copy_in "$DD_SRC"
elif [ -d "$TARGET/.git" ]; then
  say "updating existing checkout in $TARGET"
  git -C "$TARGET" pull --ff-only --quiet || die "git pull failed in $TARGET (local changes?)"
elif [ ! -e "$TARGET" ] || [ -z "$(ls -A "$TARGET" 2>/dev/null)" ]; then
  say "installing into $TARGET"
  if command -v git >/dev/null 2>&1; then
    mkdir -p "$(dirname "$TARGET")"
    rmdir "$TARGET" 2>/dev/null || true
    git clone --quiet --branch "$DD_REF" "$DD_REPO" "$TARGET" || die "git clone of $DD_REPO failed"
  else
    src="$(fetch_src)"; copy_in "$src"; rm -rf "$(dirname "$src")"
  fi
else
  say "$TARGET exists and is not a git checkout: copying scripts in, keeping your data"
  src="$(fetch_src)"; copy_in "$src"; rm -rf "$(dirname "$src")"
fi

cd "$TARGET"
mkdir -p runs
[ -f calls.jsonl ] || : > calls.jsonl
[ -f lists.txt ] || cp lists.example.txt lists.txt
[ -f telegram/config.json ] || cp telegram/config.example.json telegram/config.json

say "smoke test (offline)..."
python3 -m py_compile fetch.py telegram/tg.py || die "syntax check failed"
empty="$(mktemp)"; python3 fetch.py tally --calls "$empty" >/dev/null || die "fetch.py tally failed"; rm -f "$empty"
python3 fetch.py --help >/dev/null || die "fetch.py --help failed"
TELEGRAM_BOT_TOKEN= python3 telegram/tg.py --config telegram/config.example.json send --file README.md --dry-run >/dev/null \
  || die "telegram dry run failed"
python3 telegram/test_tg.py >/dev/null 2>&1 || die "telegram tests failed (run: python3 telegram/test_tg.py)"
rm -rf __pycache__ telegram/__pycache__

lists=$(grep -cvE '^\s*(#|$)' lists.txt || true)
say "installed in $TARGET"
[ "$lists" -gt 0 ] || say "next: add your X list IDs to $TARGET/lists.txt (one per line)"
echo "OK"
