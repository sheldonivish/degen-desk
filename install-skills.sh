#!/usr/bin/env bash
# Degen Desk clawd pack installer. Safe to re-run.
#   curl -fsSL https://raw.githubusercontent.com/sheldonivish/degen-desk/main/install-skills.sh | bash
#
# Installs the Musebook "Clawd" skill pack (204 skills: 203 + the clawd master guide),
# grouped into 17 category skills `clawd-<category>/` (a router SKILL.md each, the original
# skills under `clawd-<category>/skills/<slug>/SKILL.reference.md`), plus the
# degen-desk-skill-map router, into your skills library. 18 skill folders in total instead of
# 205, so skill loaders that only read the first N skills still see everything.
# Nothing from Musebook is stored in this repo: the bundle is downloaded from its public
# sources and adapted on your box by clawd/build_pack.py (Degen Desk "Running here" notes,
# money-moving guardrails, clawd-<name> link rewrites, missing-upstream notes), then grouped by
# clawd/consolidate.py using clawd/categories.tsv (paths and cross-references rewritten).
# An existing skill folder is NEVER overwritten (delete it yourself to reinstall it), except
# with DD_REMOVE_FLAT=1 (see below).
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
#   DD_REMOVE_FLAT=1    an older install left 204 top-level clawd-<slug> folders: back them up
#                       (tarball in DD_BACKUP_DIR, default $HOME) and replace them, the old
#                       clawd-master and the old skill map with the consolidated layout
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
DD_REMOVE_FLAT="${DD_REMOVE_FLAT:-0}"
DD_BACKUP_DIR="${DD_BACKUP_DIR:-$HOME}"

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

# 1. Degen Desk build files (build_pack.py, pack.tsv, consolidate.py, categories.tsv, skill map)
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

# 3. Build (adapt) into a flat staging folder, then group into category skills
[ -f "$SRC/clawd/consolidate.py" ] && [ -f "$SRC/clawd/categories.tsv" ] || die "$SRC has no clawd/consolidate.py or clawd/categories.tsv"
python3 "$SRC/clawd/build_pack.py" --bundle "$BUNDLE" --master "$WORK/master.md" --plugin "$WORK/plugin" \
  --out "$WORK/flat" --final "$DD_NOTES_DIR" --manifest "$SRC/clawd/pack.tsv" || die "build failed"
python3 "$SRC/clawd/consolidate.py" --manifest "$SRC/clawd/categories.tsv" --final "$DD_NOTES_DIR" \
  --src "$WORK/flat" --out "$WORK/stage" || die "consolidation failed"
mkdir -p "$WORK/stage/degen-desk-skill-map"
python3 "$SRC/clawd/consolidate.py" --manifest "$SRC/clawd/categories.tsv" --final "$DD_NOTES_DIR" \
  --skill-map-base "$SRC/skills/degen-desk-skill-map/SKILL.md" --skill-map-out "$WORK/stage/degen-desk-skill-map/SKILL.md" \
  || die "skill map build failed"

# 4. Older installs: 204 flat clawd-<slug> folders at the top level
mkdir -p "$SKILLS_DIR"
flat="$(python3 - "$SKILLS_DIR" "$SRC/clawd/categories.tsv" <<'PY'
import csv, os, sys
W, man = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(man, encoding='utf-8'), delimiter='\t'))
cats = {r['category'] for r in rows}
old = [r['name'] for r in rows if r['name'] not in cats and os.path.isdir(os.path.join(W, r['name']))]
m = os.path.join(W, 'clawd-master')
if os.path.isdir(m) and not os.path.isdir(os.path.join(m, 'skills', 'clawd')): old.append('clawd-master')
print('\n'.join(old))
PY
)"
if [ -n "$flat" ]; then
  n_flat="$(printf '%s\n' "$flat" | wc -l | tr -d ' ')"
  if [ "$DD_REMOVE_FLAT" = "1" ]; then
    mkdir -p "$DD_BACKUP_DIR"
    bk="$DD_BACKUP_DIR/clawd-flat-backup-$(date +%Y%m%d_%H%M%S).tgz"
    old_map=""; [ -d "$SKILLS_DIR/degen-desk-skill-map" ] && old_map="degen-desk-skill-map"
    # shellcheck disable=SC2086
    (cd "$SKILLS_DIR" && tar -czf "$bk" $flat $old_map) || die "backup of the old flat clawd folders failed"
    say "backed up $n_flat old top-level clawd folders${old_map:+ and the old skill map} to $bk"
    printf '%s\n' "$flat" | while IFS= read -r d; do [ -n "$d" ] && rm -rf -- "${SKILLS_DIR:?}/$d"; done
    [ -n "$old_map" ] && rm -rf -- "${SKILLS_DIR:?}/degen-desk-skill-map"
  else
    warn "found $n_flat top-level clawd-<slug> folders from an older install. Many skill loaders only read the first ~100 skills, so these can hide other skills."
    warn "re-run with DD_REMOVE_FLAT=1 to back them up and replace them with the consolidated layout (17 clawd-<category> skills)."
  fi
fi

# 5. Install without overwriting
added=0; kept=0
for d in "$WORK/stage"/*/; do
  name="$(basename "$d")"
  if [ -e "$SKILLS_DIR/$name" ]; then kept=$((kept+1)); continue; fi
  cp -R "$d" "$SKILLS_DIR/.$name.partial" && mv "$SKILLS_DIR/.$name.partial" "$SKILLS_DIR/$name"
  added=$((added+1))
done

# 6. Validate: frontmatter name == folder for every category skill + skill map, all 204
#    sub-skills present, no nested SKILL.md that a loader could register as a separate skill
python3 - "$SKILLS_DIR" "$SRC/clawd/categories.tsv" <<'PY' || die "validation failed"
import csv, os, re, sys
W, man = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(man, encoding='utf-8'), delimiter='\t'))
cats = sorted({r['category'] for r in rows})
bad = []; n = 0
for d in cats + ['degen-desk-skill-map']:
    p = os.path.join(W, d, 'SKILL.md')
    t = open(p, encoding='utf-8').read() if os.path.isfile(p) else ''
    m = re.match(r'^---\n(.*?)\n---\n', t, re.S)
    name = re.search(r'^name:\s*(.+)$', m.group(1), re.M).group(1).strip() if m else None
    desc = re.search(r'^description:\s*(.+)$', m.group(1), re.M) if m else None
    if name != d or not desc: bad.append(d)
    n += 1
subs = [r for r in rows if os.path.isfile(os.path.join(W, r['category'], 'skills', r['slug'], 'SKILL.reference.md'))]
nested = [dp for c in cats for dp, ds, fs in os.walk(os.path.join(W, c)) if 'SKILL.md' in fs and dp != os.path.join(W, c)]
flat = [r['name'] for r in rows if r['name'] not in cats and os.path.isdir(os.path.join(W, r['name']))]
total = len([d for d in os.listdir(W) if os.path.isfile(os.path.join(W, d, 'SKILL.md'))])
print(f"[clawd-pack] {len(cats)} clawd category skills + skill map in {W}; frontmatter checked {n}, invalid {len(bad)}; "
      f"sub-skills {len(subs)}/{len(rows)}; nested SKILL.md {len(nested)}; skill folders in library {total}")
if flat: print(f"[clawd-pack] note: {len(flat)} old top-level clawd-<slug> folders still present (DD_REMOVE_FLAT=1 replaces them)")
if bad: print("[clawd-pack] invalid:", ", ".join(bad[:20]))
if bad or len(subs) != len(rows) or nested: sys.exit(1)
PY
say "installed $added new skill folders, kept $kept existing (never overwritten)"
say "money-moving clawd skills stay gated by memecoin-trading-guardrails (your wallet, your approval)"
echo "OK"
