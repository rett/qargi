#!/usr/bin/env bash
# Build the qargi documentation site on this machine the way .github/workflows/pages.yml does: take the
# generator and the sources of the release from a checkout of the main repository, then check the pages, build
# the site and check the built tree. Nothing is pushed or deployed, and the main repository is only read.
#
#   tools/build-local.sh [MAIN_REPO [OUT_DIR]]
#
# MAIN_REPO  a checkout of the main qargi repository (default: $QARGI_REPO)
# OUT_DIR    where the built site goes; it must not exist or must be empty (default: a new temporary directory)
# QARGI_REF  the ref to build from (default: the tag named by "release" in site/site.json when it carries the
#            generator, else develop, built with --allow-unreleased as the workflow does)
#
# Run it from anywhere; it works on the branch this script is in. Exit status: 0 the site was built and checked,
# 1 a check failed, 2 a usage error.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
main=${1:-${QARGI_REPO:-}}
out=${2:-}
[ -n "$main" ] || { echo "usage: tools/build-local.sh MAIN_REPO [OUT_DIR]  (or set QARGI_REPO)" >&2; exit 2; }
git -C "$main" rev-parse --git-dir >/dev/null 2>&1 || { echo "build-local: $main is not a git repository" >&2; exit 2; }

rel=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["release"])' "$here/site/site.json")
[[ "$rel" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "build-local: site.json release is not X.Y.Z: $rel" >&2; exit 2; }

flags=()
if [ -n "${QARGI_REF:-}" ]; then
  ref=$QARGI_REF
  flags=(--allow-unreleased)
elif git -C "$main" cat-file -e "refs/tags/$rel:lib/site.py" 2>/dev/null; then
  ref="refs/tags/$rel"
else
  echo "build-local: release $rel has no tag with the generator: building from develop, unreleased"
  ref=develop
  flags=(--allow-unreleased)
fi
git -C "$main" cat-file -e "$ref:lib/site.py" 2>/dev/null || { echo "build-local: $ref has no lib/site.py" >&2; exit 2; }

work=$(mktemp -d "${TMPDIR:-/tmp}/qargi-site.XXXXXX")
[ -n "$out" ] || out=$work/site
mkdir -p "$work/src"
git -C "$main" archive "$ref" lib CHANGELOG.md VERSION LICENSE README.md | tar -x -C "$work/src"
echo "build-local: generator and sources from $ref, release $rel"

cd "$here"
gen=(python3 -I "$work/src/lib/site.py")
args=(--release "$rel" --source "$work/src" --pages site/pages --config site/site.json "${flags[@]}")
"${gen[@]}" check "${args[@]}"
"${gen[@]}" build "${args[@]}" --out "$out"
"${gen[@]}" check-output "$out"
echo "build-local: the site is in $out (the sources stay in $work/src)"
