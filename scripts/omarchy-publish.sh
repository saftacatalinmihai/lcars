#!/usr/bin/env bash
# omarchy-publish.sh - the omarchy plugin (omarchy/) published to its own
# repo, the one `omarchy plugin add` clones and plugins.omarchy.org lists
# (docs/design/omarchy-plugin.md, section 3).
#
#   scripts/omarchy-publish.sh --src DIR [--remote URL] [--dry-run | --push]
#
# DIR is a checkout of the PUBLIC repo (the export's, scripts/export-public.py),
# never the private one: the split's history is DIR's, and what is pushed
# must be the public history. A tree holding any `*.local.*` file is a
# private one (the export leaves every such file out), and is refused.
#
# What it does, in order:
#   1. DIR clean, omarchy/manifest.json there;
#   2. the plugin's checks: scripts/test_omarchy_plugin.py on DIR/omarchy,
#      the installer and the theme hook required in its bin/;
#   3. `git subtree split --prefix=omarchy` in DIR: a commit whose tree is
#      omarchy/ at the root. The split is deterministic, so each publish
#      fast-forwards the last and `omarchy plugin update` (a fast-forward
#      pull) works for the users;
#   4. the remote's main read: the same tree is "nothing to publish"; a
#      change whose manifest version is not above the published one is
#      refused (bump "version" in omarchy/manifest.json);
#   5. with --push only: the split pushed to the remote's main, and the tag
#      v<version>. Without it (or with --dry-run, the default) it says what
#      it would push and pushes nothing.
#
# Run on the captain's word only. Making the repo on GitHub and filing the
# marketplace listing are his.

set -euo pipefail

REMOTE_DEFAULT="git@github.com:saftacatalinmihai/omarchy-lcars.git"
src=""
remote=$REMOTE_DEFAULT
push=0

die() { echo "omarchy-publish: $*" >&2; exit 1; }

while (($#)); do
  case "$1" in
  --src) src=${2:-}; shift 2 ;;
  --remote) remote=${2:-}; shift 2 ;;
  --push) push=1; shift ;;
  --dry-run) push=0; shift ;;
  -h | --help) sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) die "unknown argument: $1 (see --help)" ;;
  esac
done

[[ -n $src ]] || die "--src DIR is required: a checkout of the public repo"
src=$(cd "$src" && pwd) || die "no such directory: $src"
git -C "$src" rev-parse --git-dir >/dev/null 2>&1 || die "$src is not a git checkout"
[[ -f $src/omarchy/manifest.json ]] || die "$src has no omarchy/manifest.json"
if [[ -n $(git -C "$src" ls-files '*.local.*') ]]; then
  die "$src holds *.local.* files: a private checkout. Publish from the public export's."
fi
[[ -z $(git -C "$src" status --porcelain) ]] || die "$src has uncommitted changes"

version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$src/omarchy/manifest.json")
[[ -n $version ]] || die "omarchy/manifest.json has no version"

echo "omarchy-publish: checking the plugin (version $version)"
OMARCHY_PLUGIN_DIR="$src/omarchy" OMARCHY_REQUIRE_BIN=1 \
  python3 "$src/scripts/test_omarchy_plugin.py" -q || die "the plugin's checks failed"

split=$(git -C "$src" subtree split --prefix=omarchy 2>/dev/null) || die "git subtree split failed"
tree=$(git -C "$src" rev-parse "$split^{tree}")
echo "omarchy-publish: split $split (tree $tree)"

# The remote's main, if it has one: fetched into a ref of our own, never
# into DIR's branches.
published=""
pub_version=""
if heads=$(git -C "$src" ls-remote --heads "$remote" main 2>/dev/null); then
  if [[ -n $heads ]]; then
    git -C "$src" fetch --quiet "$remote" "+refs/heads/main:refs/omarchy-publish/main" ||
      die "could not fetch $remote main"
    published=$(git -C "$src" rev-parse refs/omarchy-publish/main)
    pub_version=$(git -C "$src" show "$published:manifest.json" |
      python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))')
  fi
  reachable=1
else
  reachable=0
fi

if ((reachable)) && [[ -n $published ]]; then
  if [[ $(git -C "$src" rev-parse "$published^{tree}") == "$tree" ]]; then
    echo "omarchy-publish: nothing to publish: $remote main already has this tree ($pub_version)"
    exit 0
  fi
  newest=$(printf '%s\n%s\n' "$pub_version" "$version" | sort -V | tail -1)
  if [[ $version == "$pub_version" || $newest != "$version" ]]; then
    die "the plugin changed but its version did not go up ($pub_version published, $version here): bump \"version\" in omarchy/manifest.json"
  fi
  if ! git -C "$src" merge-base --is-ancestor "$published" "$split"; then
    die "$remote main is not an ancestor of this split: a push would not fast-forward the users' checkouts"
  fi
fi

if ((!push)); then
  if ((!reachable)); then
    echo "omarchy-publish: dry run: $remote not reachable, the version not compared"
  fi
  echo "omarchy-publish: dry run: would push $split to $remote main as v$version (${pub_version:-first publish} before it)"
  exit 0
fi

((reachable)) || die "$remote not reachable"
git -C "$src" push "$remote" "$split:refs/heads/main"
git -C "$src" push "$remote" "$split:refs/tags/v$version"
echo "omarchy-publish: published v$version to $remote ($split)"
