#!/usr/bin/env bash
# Roles: what a member or a cloud agent is for. A role is a directory with role.json ({class: write|read-only,
# description}) and ROLE.md (its instructions). The four built-in roles (build, write, review, test) ship in <tool>/roles;
# yours live in <config>/roles/<name>/. The class fixes what the guard allows (read-only: nothing in the clone changes);
# the text of a role never changes the guard.
#
#   role.sh list
#   role.sh show NAME
#   role.sh prompt NAME     the instructions as a task block carries them
#   role.sh check [NAME]    validate one role, or all
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true

check_one() { # name -> prints problems, returns 1 if any
  local n=$1 d bad=0 c
  d=$(role_dir "$n") || { echo "$n: no such role (needs role.json and ROLE.md)"; return 1; }
  jq -e . "$d/role.json" >/dev/null 2>&1 || { echo "$n: role.json is not valid JSON"; return 1; }
  c=$(jq -r '.class // empty' "$d/role.json")
  case $c in write|read-only) ;; *) echo "$n: class must be write or read-only (got '${c:-none}')"; bad=1;; esac
  printf '%s' "$n" | grep -Eq '^[a-z][a-z0-9]{0,23}$' || { echo "$n: the name is one lower-case token (letters, digits)"; bad=1; }
  [ "$n" != lead ] || { echo "lead is reserved for the team coordinator"; bad=1; }
  [ -s "$d/ROLE.md" ] || { echo "$n: ROLE.md is empty"; bad=1; }
  return $bad
}

case $verb in
  list)
    printf '%-12s %-10s %-9s %s\n' ROLE CLASS WHERE DESCRIPTION
    for r in $(role_names); do
      d=$(role_dir "$r") || continue
      w=user; case $d in "$QARGI_TOOL"/*) w=built-in;; esac
      printf '%-12s %-10s %-9s %s\n' "$r" "$(jq -r '.class // "write"' "$d/role.json")" "$w" "$(jq -r '.description // ""' "$d/role.json")"
    done;;
  show)
    n=${1:-}; [ -n "$n" ] || die "usage: qargi role show NAME"
    d=$(role_dir "$n") || die "no role named $n (qargi role list)"
    echo "role: $n"; echo "dir: $d"; echo "class: $(role_class "$n")"; jq -r '"description: " + (.description // "")' "$d/role.json"
    echo; cat "$d/ROLE.md";;
  prompt)
    n=${1:-}; [ -n "$n" ] || die "usage: qargi role prompt NAME"
    d=$(role_dir "$n") || die "no role named $n (qargi role list)"
    cat "$d/ROLE.md";;
  check)
    rc=0
    for n in ${1:-$(role_names)}; do check_one "$n" || rc=1; done
    [ $rc = 0 ] && echo "roles: ok"; exit $rc;;
  *) die "usage: qargi role list|show|prompt|check ...";;
esac
