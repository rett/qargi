#!/usr/bin/env bash
# Optional credentials for private git repositories. The token lives in a file you
# own (repo.credential_file in the project answers), outside every repository; it is
# never put on a command line, in the tracker, in the audit log or in a repository.
#
#   cred.sh check PROJECT [--allow-write-token]   probe the token: it must read and should not push
#   cred.sh askpass FILE                          (internal) print the token for git
#
# Prefer a fine-grained, read-only token (contents: read): the policy is that agents never
# push, and a token that cannot push makes that true on the server side as well.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
case $verb in
  askpass) cat "${1:?askpass needs a file}";;
  check)
    PROJECT=${1:-}; shift || true; ALLOW=''
    [ "${1:-}" = --allow-write-token ] && ALLOW=1
    valid_project "$PROJECT" || die "usage: cred.sh check PROJECT [--allow-write-token]"
    f=$(cred_file "$PROJECT"); [ -n "$f" ] || die "the project has no repo.credential_file: nothing to check (public repositories need none)"
    url=$(jq -r .repo.url "$DA_CONF/projects/$PROJECT.json")
    case $url in https://*) ;; *) die "a credential file is for https repository URLs";; esac
    [ -f "$f" ] && [ -z "$(find "$f" -perm /077 2>/dev/null)" ] || die "$f must exist and be readable by you only (chmod 600)"
    tmp=$(mktemp -d); trap 'rm -rf "$tmp" "${ASKPASS:-}"' EXIT
    ( git_auth_env "$f"
      # user name in the URL, the token comes from the askpass helper
      authurl=${url/https:\/\//https://x-access-token@}
      if timeout 60 git ls-remote "$authurl" HEAD >/dev/null 2>"$tmp/read.err" </dev/null; then echo "read:  ok (the token can read $url)"; else echo "read:  FAILED (the token cannot read $url)"; exit 3; fi
      git -C "$tmp" init -q -b probe && git -C "$tmp" -c user.name=probe -c user.email=probe@example.invalid commit -q --allow-empty -m probe
      if timeout 60 git -C "$tmp" push --dry-run "$authurl" HEAD:refs/heads/qargi-write-probe >/dev/null 2>&1 </dev/null; then
        echo "write: the token CAN push (not read-only)"; exit 4
      else echo "write: refused (the token is read-only, as it should be)"; fi
    ); rc=$?
    case $rc in
      0) audit_log credential-check "$PROJECT read-only ok";;
      4) audit_log credential-check "$PROJECT token can push"
         if [ -n "$ALLOW" ]; then echo "accepted with --allow-write-token; agents are still instructed never to push"; else
           echo "Use a read-only token (contents: read). To accept a write-capable token knowingly: --allow-write-token" >&2; exit 1; fi;;
      *) exit 1;;
    esac;;
  *) die "usage: cred.sh check PROJECT | askpass FILE";;
esac
