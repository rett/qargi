#!/usr/bin/env bash
# qargi upgrade: move the installed tool (the root-owned checkout install.sh recorded, for example /opt/qargi) to a newer
# branch or tag of its origin, relink it, and say which members need `qargi agent refresh`.
#
#   upgrade.sh [--branch B | --tag T]                         plan: fetch, show what would change and print a plan token
#   upgrade.sh [--branch B | --tag T] --plan TOKEN --approved "<your go-ahead>"    apply exactly that plan
#
# Without --branch or --tag the checkout's current branch is used. A branch on the current branch moves only forward
# (merge --ff-only); another branch is checked out at the fetched tip; a tag is checked out detached. The git commands that
# write into the root-owned checkout run through sudo (QARGI_SUDO names another command, '' none); install.sh --user then
# runs as you. Members and agents cannot use it (the guard refuses the verb). Nothing is pushed anywhere.
. "$(dirname "$0")/lib.sh"

BRANCH='' TAG=''
while [ $# -gt 0 ]; do
  case $1 in
    --branch) BRANCH=$2; shift 2;;
    --tag) TAG=$2; shift 2;;
    --plan) PLAN_ARG=$2; shift 2;;
    --approved) APPROVED=$2; shift 2;;
    *) die "usage: qargi upgrade [--branch B | --tag T] [--plan TOKEN --approved \"...\"]";;
  esac
done
PLAN_ARG=${PLAN_ARG:-}; APPROVED=${APPROVED:-}
[ -z "$BRANCH" ] || [ -z "$TAG" ] || die "give --branch or --tag, not both"
for v in "$BRANCH" "$TAG"; do
  [ -n "$v" ] || continue
  printf '%s' "$v" | grep -Eq '^[A-Za-z0-9._/-]*$' && [ "${v#-}" = "$v" ] || die "a branch or tag name: letters, digits, . _ / - only"
done

root=$(python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import paths; print(paths.installed_tool_root() or "")' "$(dirname "$(readlink -f "$0")")")
[ -n "$root" ] && [ -d "$root/.git" ] || die "no installed tool is recorded (install.json): install it first, for example sudo git clone https://github.com/rett/qargi /opt/qargi && /opt/qargi/install.sh --user"
[ -x "$root/install.sh" ] || die "$root has no install.sh"

SUDO=${QARGI_SUDO-sudo}
if [ -w "$root/.git" ]; then SUDO=''; fi
g() { git -c safe.directory="$root" -C "$root" "$@"; }             # read as you
gw() { if [ -n "$SUDO" ]; then $SUDO git -c safe.directory="$root" -C "$root" "$@"; else g "$@"; fi; }   # write (root-owned checkout)

cur_branch=$(g branch --show-current)
cur_sha=$(g rev-parse HEAD)
if [ -n "$TAG" ]; then ref="refs/tags/$TAG"; label="tag $TAG"; fetch_spec="+refs/tags/$TAG:refs/tags/$TAG"
else BRANCH=${BRANCH:-$cur_branch}; [ -n "$BRANCH" ] || die "the installed tool is on a detached HEAD; give --branch or --tag"
  ref="refs/remotes/origin/$BRANCH"; label="branch $BRANCH"; fetch_spec="+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"; fi

gw fetch --quiet origin "$fetch_spec" || die "could not fetch $label from origin (git -C $root remote -v shows where it points; the sudo prompt needs a terminal)"
new_sha=$(g rev-parse --verify --quiet "$ref^{commit}") || die "$label is not on origin"
token=$(printf '%s\n%s\n%s\n' "$root" "$cur_sha" "$new_sha" | sha256sum | cut -c1-12)

if [ "$cur_sha" = "$new_sha" ]; then echo "the installed tool at $root is already at $label ($(g rev-parse --short HEAD))"; exit 0; fi

mode=checkout
if [ -z "$TAG" ] && [ "$BRANCH" = "$cur_branch" ]; then
  g merge-base --is-ancestor "$cur_sha" "$new_sha" || die "$label is not a fast-forward of the installed tool ($(g rev-parse --short HEAD)); the installed checkout is not changed"
  mode=ff
fi

if [ -z "$APPROVED" ] || [ -z "$PLAN_ARG" ]; then
  echo "upgrade $root: ${cur_branch:-detached} $(g rev-parse --short "$cur_sha") -> $label $(g rev-parse --short "$new_sha") ($mode)"
  echo "version: $(cat "$root/VERSION" 2>/dev/null || echo ?) -> $(g show "$new_sha:VERSION" 2>/dev/null || echo ?)"
  echo "commits:"; g log --oneline --no-decorate -30 "$cur_sha..$new_sha" 2>/dev/null | sed 's/^/  /'
  g diff --stat "$cur_sha" "$new_sha" | tail -1 | sed 's/^/files:/'
  echo "plan token: $token   (apply with: --plan $token --approved \"...\")"
  exit 0
fi

[ "$PLAN_ARG" = "$token" ] || die "the plan changed or --plan is wrong: run the plan again, then apply exactly that with --plan $token"
audit_log upgrade "$label $(g rev-parse --short "$new_sha")"
if [ "$mode" = ff ]; then gw merge --quiet --ff-only "$ref" || die "could not fast-forward $root"
elif [ -n "$TAG" ]; then gw checkout --quiet --detach "$ref" || die "could not check out $label"
else gw checkout --quiet -B "$BRANCH" "$ref" || die "could not check out $label"; fi
"$root/install.sh" --user || die "the checkout moved but install.sh --user failed; run $root/install.sh --user yourself"
echo "upgraded $root to $label $(g rev-parse --short HEAD) (approved: $APPROVED)"
n=$(jq -r 'keys | join(" ")' "$MEMBERS_FILE" 2>/dev/null || true)
[ -z "$n" ] || echo "members to refresh if the member definition changed: for m in $n; do qargi agent refresh \$m; done"
