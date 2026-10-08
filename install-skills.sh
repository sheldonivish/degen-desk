#!/usr/bin/env bash
# Degen Desk clawd pack installer. Safe to re-run.
#   curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/install-skills.sh | bash
#
# Installs the Musebook "Clawd" skill pack (204 skills: 203 + clawd-master) as
# clawd-<slug> skills, plus the degen-desk-skill-map router, into your skills library.
# Nothing from Musebook is stored in this repo: the bundle is downloaded from its public
# sources and adapted on your box by clawd/build_pack.py (Degen Desk "Running here" notes,
# money-moving guardrails, clawd-<name> link rewrites, missing-upstream notes).
# An existing skill folder is NEVER overwritten (delete it yourself to reinstall it).
#
# Env:
#   SKILLS_DIR          where skills go (default /home/box/agent-data/workflows)
#   DD_NOTES_DIR        skills path written into the "Running here" notes (default SKILLS_DIR)
#   DD_REPO / DD_REF    repo + branch for build_pack.py and the skill map (default this repo, main)
#   DD_SRC              use a local checkout instead of GitHub (testing)
#   CLAWD_BUNDLE_URL    default https://musebook.trade/clawd-skills.tar.gz (v3.14.0)
#   CLAWD_BUNDLE_FILE   use an already-downloaded bundle tarball instead
#   CLAWD_MASTER_URL    default https://musebook.trade/SKILL.md
#   CLAWD_PLUGIN_URL    default github.com/Solizardking/clawd-plugin, pinned commit
#   CLAWD_ALLOW_UPSTREAM_CHANGE=1   accept a bundle whose sha256 differs from the pinned v3.14.0
set -euo pipefail

SKILLS_DIR="${SKILLS_DIR:-/home/box/agent-data/workflows}"
DD_NOTES_DIR="${DD_NOTES_DIR:-$SKILLS_DIR}"
DD_REPO="${DD_REPO:-https://github.com/sheldonivish/degen-desk.git}"
DD_REF="${DD_REF:-main}"
DD_SRC="${DD_SRC:-}"
CLAWD_BUNDLE_URL="${CLAWD_BUNDLE_URL:-https://musebook.trade/clawd-skills.tar.gz}"
CLAWD_BUNDLE_SHA256="e40c3c96f24f84feaeec00c897477e73a7cba00b12a2f5d45bffa5703fa56493"
CLAWD_BUNDLE_FILE="${CLAWD_BUNDLE_FILE:-}"
CLAWD_MASTER_URL="${CLAWD_MASTER_URL:-https://musebook.trade/SKILL.md}"
CLAWD_MASTER_SHA256="67f1200ee980bae835c0bd56ccc6f10d545c619a501c37d77598fad38697b78d"
CLAWD_PLUGIN_URL="${CLAWD_PLUGIN_URL:-https://codeload.github.com/Solizardking/clawd-plugin/tar.gz/1ced93e1e3fca232be2001f11b8a9bcdaca3d80a}"
CLAWD_ALLOW_UPSTREAM_CHANGE="${CLAWD_ALLOW_UPSTREAM_CHANGE:-0}"

say()  { printf '[clawd-pack] %s\n' "$*"; }
warn() { printf '[clawd-pack] warning: %s\n' "$*" >&2; }
die()  { printf '[clawd-pack] ERROR: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "Python 3.9+ is required"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v tar  >/dev/null 2>&1 || die "tar is required"
python3 -c 'import yaml' 2>/dev/null || { warn "PyYAML missing; trying pip install --user pyyaml"; python3 -m pip install --quiet --user pyyaml >/dev/null 2>&1 || warn "could not install PyYAML; descriptions use the fallback parser"; }

sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# 1. Degen Desk build files (build_pack.py, pack.tsv, skill map)
here=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/clawd/build_pack.py" ]; then here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; fi
if [ -n "$DD_SRC" ]; then
  [ -f "$DD_SRC/clawd/build_pack.py" ] || die "DD_SRC=$DD_SRC has no clawd/build_pack.py"; SRC="$DD_SRC"
elif [ -n "$here" ]; then
  SRC="$here"
else
  if command -v git >/dev/null 2>&1; then
    git clone --quiet --depth 1 --branch "$DD_REF" "$DD_REPO" "$WORK/repo" || die "git clone of $DD_REPO failed"
  else
    mkdir -p "$WORK/repo"
    curl -fsSL "${DD_REPO%.git}/archive/refs/heads/$DD_REF.tar.gz" | tar -xz -C "$WORK/repo" --strip-components 1 || die "repo download failed"
  fi
  SRC="$WORK/repo"
fi
say "build files: $SRC"

# 2. Musebook Clawd bundle (public download, verified)
if [ -n "$CLAWD_BUNDLE_FILE" ]; then
  cp "$CLAWD_BUNDLE_FILE" "$WORK/bundle.tgz"
else
  say "downloading $CLAWD_BUNDLE_URL (~22 MB)"
  curl -fsSL --retry 3 "$CLAWD_BUNDLE_URL" -o "$WORK/bundle.tgz" || die "bundle download failed"
fi
got="$(sha256 "$WORK/bundle.tgz")"
if [ "$got" != "$CLAWD_BUNDLE_SHA256" ]; then
  [ "$CLAWD_ALLOW_UPSTREAM_CHANGE" = "1" ] || die "bundle sha256 $got != pinned v3.14.0 ($CLAWD_BUNDLE_SHA256). Musebook may have published a new version; re-run with CLAWD_ALLOW_UPSTREAM_CHANGE=1 to accept it."
  warn "bundle changed upstream (sha256 $got); continuing because CLAWD_ALLOW_UPSTREAM_CHANGE=1"
fi
mkdir -p "$WORK/bundle" && tar -xzf "$WORK/bundle.tgz" -C "$WORK/bundle" || die "bundle extract failed"
BUNDLE="$WORK/bundle/skills"; [ -d "$BUNDLE" ] || BUNDLE="$(find "$WORK/bundle" -mindepth 1 -maxdepth 1 -type d | head -1)"

curl -fsSL --retry 3 "$CLAWD_MASTER_URL" -o "$WORK/master.md" || die "master SKILL.md download failed"
[ "$(sha256 "$WORK/master.md")" = "$CLAWD_MASTER_SHA256" ] || warn "Clawd master SKILL.md changed upstream since v3.14.0; using the current copy"
mkdir -p "$WORK/plugin"
curl -fsSL --retry 3 "$CLAWD_PLUGIN_URL" | tar -xz -C "$WORK/plugin" --strip-components 1 || die "clawd-plugin download failed"

# 3. Build (adapt) into a staging folder
python3 "$SRC/clawd/build_pack.py" --bundle "$BUNDLE" --master "$WORK/master.md" --plugin "$WORK/plugin" \
  --out "$WORK/stage" --final "$DD_NOTES_DIR" --manifest "$SRC/clawd/pack.tsv" || die "build failed"
mkdir -p "$WORK/stage/degen-desk-skill-map"
cp "$SRC/skills/degen-desk-skill-map/SKILL.md" "$WORK/stage/degen-desk-skill-map/SKILL.md"

# 4. Install without overwriting
mkdir -p "$SKILLS_DIR"
added=0; kept=0
for d in "$WORK/stage"/*/; do
  name="$(basename "$d")"
  if [ -e "$SKILLS_DIR/$name" ]; then kept=$((kept+1)); continue; fi
  cp -R "$d" "$SKILLS_DIR/.$name.partial" && mv "$SKILLS_DIR/.$name.partial" "$SKILLS_DIR/$name"
  added=$((added+1))
done

# 5. Validate: frontmatter name == folder for every pack skill
python3 - "$SKILLS_DIR" <<'PY' || die "validation failed"
import os, re, sys
W = sys.argv[1]; bad = []; n = 0
for d in sorted(os.listdir(W)):
    if not (d.startswith('clawd-') or d == 'degen-desk-skill-map'): continue
    p = os.path.join(W, d, 'SKILL.md')
    t = open(p, encoding='utf-8').read() if os.path.isfile(p) else ''
    m = re.match(r'^---\n(.*?)\n---\n', t, re.S)
    name = re.search(r'^name:\s*(.+)$', m.group(1), re.M).group(1).strip() if m else None
    desc = re.search(r'^description:\s*(.+)$', m.group(1), re.M) if m else None
    if name != d or not desc: bad.append(d)
    n += 1
clawd = len([d for d in os.listdir(W) if d.startswith('clawd-')])
print(f"[clawd-pack] {clawd} clawd-* skills + skill map present in {W}; frontmatter checked {n}, invalid {len(bad)}")
if bad: print("[clawd-pack] invalid:", ", ".join(bad[:20])); sys.exit(1)
PY
say "installed $added new skill folders, kept $kept existing (never overwritten)"
say "money-moving clawd skills stay gated by memecoin-trading-guardrails (your wallet, your approval)"
echo "OK"
