#!/usr/bin/env bash
# Optional credentials for private git repositories. The token lives in a file you
# own (repo.credential_file in the project answers), outside every repository; it is
# never put on a command line, in the tracker, in the audit log or in a repository.
#
#   cred.sh check PROJECT [--allow-write-token]   probe the token: it must read and should not push
#   cred.sh setup lead-push PROJECT ...           store, check and wire the cloud lead's write token (see below)
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
  setup)
    # setup lead-push PROJECT [--from-file F] [--allow-more-repos] --asked "..." [--plan T --approved "..."]
    # One command for the cloud lead's write token: the token is read from a file or from stdin (never
    # from an argument), checked against GitHub (fine-grained, this repository only, no administration),
    # stored in a file only you can read, put in a vault of its own as a bearer credential for the GitHub
    # tool, attached to the lead's deployment, and recorded in the project's answers. Without --approved it
    # only checks and prints the plan.
    kind=${1:-}; PROJECT=${2:-}; shift 2 || true
    [ "$kind" = lead-push ] && valid_project "$PROJECT" || die "usage: cred.sh setup lead-push PROJECT [--from-file F] [--allow-more-repos] --asked \"...\" [--plan T --approved \"...\"]"
    FROM='' MORE='' ASKED='' APPROVED='' PLAN_ARG=''
    while [ $# -gt 0 ]; do
      case $1 in
        --from-file) FROM=$2; shift 2;;
        --allow-more-repos) MORE=1; shift;;
        --asked) ASKED=$2; shift 2;;
        --approved) APPROVED=$2; shift 2;;
        --plan) PLAN_ARG=$2; shift 2;;
        *) die "unknown option $1";;
      esac
    done
    export PLAN_ARG ASKED
    PCFG=$DA_CONF/projects/$PROJECT.json; [ -f "$PCFG" ] || die "no stored answers for $PROJECT"
    jq -e '(.teams // {}) | length > 0' "$PCFG" >/dev/null || die "project $PROJECT defines no teams, so it has no lead to grant"
    url=$(jq -r .repo.url "$PCFG"); slug=${url#https://github.com/}; slug=${slug%.git}
    printf '%s' "$slug" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' || die "the repository URL is not a github.com/OWNER/REPO URL: $url"
    tmp=$(mktemp -d); chmod 700 "$tmp"; trap 'rm -rf "$tmp"' EXIT
    if [ -n "$FROM" ]; then tok=$(tr -d ' \t\r\n' < "$FROM")
    elif [ ! -t 0 ]; then tok=$(tr -d ' \t\r\n')
    else printf 'Paste the fine-grained token (input is hidden): ' >&2; read -rs tok; echo >&2; tok=$(printf '%s' "$tok" | tr -d ' \t\r\n'); fi
    [ -n "$tok" ] || die "no token given (--from-file F, stdin, or type it when asked)"
    case $tok in github_pat_*) ;; *) die "that is not a fine-grained token (it should start with github_pat_). Classic tokens reach every repository you can; create a fine-grained one for $slug only";; esac
    umask 077; { printf 'Authorization: Bearer %s\n' "$tok"; } > "$tmp/h"
    # GitHub answers with the body, a newline and the HTTP status.
    gh_api() { curl -sS --max-time 30 -w '\n%{http_code}' -H @"$tmp/h" -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' "https://api.github.com$1"; }
    resp=$(gh_api "/repos/$slug") || die "could not reach api.github.com"
    code=${resp##*$'\n'}; repo=${resp%$'\n'*}
    [ "$code" = 200 ] && [ "$(jq -r '.full_name // empty' <<<"$repo" | tr A-Z a-z)" = "$(printf '%s' "$slug" | tr A-Z a-z)" ] || die "the token cannot see $slug (HTTP $code): $(jq -r '.message // "no answer"' <<<"$repo")"
    # What the token itself may do, not what your account may do (the repository answer shows your role).
    # Write: a push dry-run over https asks GitHub for write access with this token and sends nothing.
    printf '%s' "$tok" > "$tmp/tok"; chmod 600 "$tmp/tok"
    probe_write() { # OWNER/REPO: succeeds if this token can push there (a dry run sends nothing)
      ( git_auth_env "$tmp/tok"
        d=$(mktemp -d "$tmp/p.XXXXXX")
        git -C "$d" init -q -b probe 2>/dev/null && git -C "$d" -c user.name=probe -c user.email=probe@example.invalid commit -q --allow-empty -m probe
        timeout 30 git -C "$d" push --dry-run "https://x-access-token@github.com/$1.git" HEAD:refs/heads/agent/qargi-write-probe >/dev/null 2>&1 </dev/null )
    }
    wrote=0; probe_write "$slug" && wrote=1
    [ "$wrote" = 1 ] || die "the token cannot push to $slug: grant Contents (read and write) for this repository"
    # Administration: reading branch protection needs it, so a token without it is refused with 403.
    branch=$(jq -r '.default_branch // "main"' <<<"$repo")
    aresp=$(gh_api "/repos/$slug/branches/$branch/protection"); acode=${aresp##*$'\n'}; abody=${aresp%$'\n'*}
    if [ "$acode" = 200 ] || { [ "$acode" = 404 ] && [ "$(jq -r '.message // ""' <<<"$abody")" = "Branch not protected" ]; }; then
      die "the token has Administration on $slug (it should not): create one without it"
    elif [ "$acode" = 403 ]; then admin_note="cannot administer it"
    else admin_note="could not confirm it cannot administer it (HTTP $acode): check that Administration is not granted"; fi
    # A fine-grained token can read every public repository, so what matters is where it can write.
    others=$(gh_api "/user/repos?per_page=100" | sed '$d' | jq -r 'if type == "array" then .[].full_name else empty end' | grep -vix "$slug" | head -60 || true)
    writable=''
    for r in $others; do probe_write "$r" && writable="$writable $r"; done
    nw=$(printf '%s\n' $writable | grep -c . || true)
    echo "token: ok, fine-grained, can push to $slug, $admin_note; checked $(printf '%s\n' $others | grep -c .) other repositories: $([ "$nw" = 0 ] && echo "it can write to none" || echo "it can write to$writable"); Pull requests write cannot be checked without opening one"
    if [ "$nw" -gt 0 ] && [ -z "$MORE" ]; then die "the token can also write to:$writable. Limit it to $slug (or accept this knowingly with --allow-more-repos)"; fi
    dest=$DA_CONF/credentials/$PROJECT-lead-push
    echo "plan: store the token in $dest (mode 600); create the vault $PROJECT-vault-lead with a bearer credential for the GitHub tool; attach it to the lead's deployment; record it in the project answers (lead.push)"
    tok_plan=$(printf '%s|%s|%s' "$PROJECT" "$slug" "$dest" | plan_token)
    if [ -z "$APPROVED" ]; then echo "plan token: $tok_plan   (apply with: --plan $tok_plan --approved \"<the user's go-ahead>\" --asked \"...\"; nothing was changed)"; exit 0; fi
    need_asked; ant_ok; need_plan "$tok_plan"; audit_log credential-setup "$PROJECT lead-push $slug"
    mkdir -p "$(dirname "$dest")"; chmod 700 "$(dirname "$dest")"
    ( umask 077; printf '%s' "$tok" > "$dest" ); chmod 600 "$dest"
    vname=$PROJECT-vault-lead
    vid=$(ant beta:vaults list </dev/null 2>/dev/null | jq -r --arg n "$vname" 'select(.display_name == $n and (.archived_at // null) == null) | .id' | head -1)
    if [ -z "$vid" ]; then vid=$(ant beta:vaults create --display-name "$vname" </dev/null 2>/dev/null | jq -r '.id // empty'); fi
    [ -n "$vid" ] || die "could not create the vault $vname (the token file is stored at $dest)"
    old=$(ant beta:vaults:credentials list --vault-id "$vid" </dev/null 2>/dev/null | jq -r 'select((.archived_at // null) == null) | .id')
    jq -nc --arg t "$tok" --arg u "https://api.githubcopilot.com/mcp/" --arg n "$PROJECT lead: GitHub write token" \
      '{display_name: $n, auth: {type: "static_bearer", mcp_server_url: $u, token: $t}}' \
      | ant beta:vaults:credentials create --vault-id "$vid" >/dev/null 2>&1 || die "could not store the credential in $vid"
    for c in $old; do ant beta:vaults:credentials archive --vault-id "$vid" --credential-id "$c" </dev/null >/dev/null 2>&1 || true; done   # a rotation replaces the old one
    cur=$(jq -c '.lead.push // {}' "$PCFG")
    merged=$(jq -c --arg f "$dest" --arg v "$vid" '. + {cloud: "branches", credential_file: $f, vault_id: $v} + {branch_pattern: (.branch_pattern // "agent/*"), merge: (.merge // "ask"), release: (.release // "ask")}' <<<"$cur")
    "$(dirname "$0")/project.sh" set "$PROJECT" lead.push "$merged" >/dev/null || die "could not record the grant in the project answers (vault $vid is ready)"
    li=$(jq -c --arg n "$PROJECT-lead" '.[$n] // empty' "$REG" 2>/dev/null)
    if [ -n "$li" ]; then
      did=$(jq -r .deployment_id <<<"$li")
      vs=$(ant beta:deployments retrieve --deployment-id "$did" </dev/null 2>/dev/null | jq -c --arg v "$vid" '(.vault_ids // []) + [$v] | unique')
      ant beta:deployments update --deployment-id "$did" --vault-id "$vs" </dev/null >/dev/null 2>&1 || die "could not attach the vault to the lead's deployment $did"
    fi
    echo "done: token file $dest, vault $vid, grant recorded (lead.push: agent branches and pull requests; merges asked of you; no releases through this tool)"
    echo "next: qargi packs apply $PROJECT-lead (adds the GitHub tool to the lead agent) and qargi instances refresh-prompt $PROJECT-lead (adds its Push section); each shows a plan first";;
  *) die "usage: cred.sh check PROJECT | setup lead-push PROJECT | askpass FILE";;
esac
