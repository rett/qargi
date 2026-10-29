#!/usr/bin/env bash
# The cloud lead's push grant as one guided flow. Only the lead ever pushes; members never do.
#
#   lead.sh grant  PROJECT [--from-file F]   create or rotate the grant: token, vault, GitHub tool, prompt
#   lead.sh status PROJECT                   what is in place and what is missing (read-only)
#   lead.sh revoke PROJECT                   take the grant away again
#
# grant and revoke are interactive: each step prints its plan and asks you at the terminal, and your
# answer is the approval that is recorded. They never run without a terminal; an agent uses the
# separate verbs (credential setup, packs apply, instances refresh-prompt) with your words in --approved.
. "$(dirname "$0")/lib.sh"

here=$(dirname "$(readlink -f "$0")")
TTY_IN=${QARGI_TTY_IN:-/dev/tty}; TTY_OUT=${QARGI_TTY_OUT:-/dev/tty}    # the tests answer the prompts through these

verb=${1:-}; PROJECT=${2:-}; shift 2 || true
valid_project "$PROJECT" || die "usage: lead.sh grant|status|revoke PROJECT"
PCFG=$DA_CONF/projects/$PROJECT.json
[ -f "$PCFG" ] || die "no stored answers for $PROJECT: run /qargi-project first"
LEAD=$PROJECT-lead
FROM=''
while [ $# -gt 0 ]; do
  case $1 in
    --from-file) FROM=$2; shift 2;;
    *) die "unknown option $1";;
  esac
done

interactive() { [ -r "$TTY_IN" ] && [ -w "$TTY_OUT" ]; }
need_tty() { interactive || die "$verb is interactive: run it in a terminal (from Claude Code: ! qargi lead $verb $PROJECT)"; }
ask() { local a=; printf '%s ' "$1" > "$TTY_OUT"; read -r a < "$TTY_IN" || true; printf '%s' "$a"; }
confirm() { case $(ask "$1 [y/N]") in y|Y|yes|YES) return 0;; *) return 1;; esac; }
ASKED="interactive: qargi lead $verb $PROJECT"
APPROVAL="interactive: confirmed at the terminal by $(id -un) at $(now)"
ok() { printf '  %-9s %s\n' "$1" "$2"; }

# step TITLE COMMAND...: print the command's plan, ask, then apply exactly that plan.
step() {
  local title=$1 out tok; shift
  echo; echo "== $title"
  out=$("$@" 2>&1) || { echo "$out"; die "could not plan: $title"; }
  sed '/^plan token:/d' <<<"$out"
  tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out" | head -1)
  [ -n "$tok" ] || return 0
  confirm "Apply this?" || { echo "skipped: $title"; return 1; }
  QARGI_NESTED='' "$@" --plan "$tok" --approved "$APPROVAL" 2>&1 | tail -4
}

lead_state() { # sets: INST AGENT AVER HAS_TOOL HAS_PUSH HAS_MEMBERS VAULT DEPVAULTS
  INST=$(jq -c --arg n "$LEAD" '.[$n] // empty' "$REG" 2>/dev/null)
  AGENT='' AVER='' HAS_TOOL='' HAS_PUSH='' DEPVAULTS=''
  [ -n "$INST" ] || return 0
  AGENT=$(jq -r .agent.id <<<"$INST")
  local ag; ag=$(ant beta:agents retrieve --agent-id "$AGENT" </dev/null 2>/dev/null) || return 0
  AVER=$(jq -r .version <<<"$ag")
  HAS_TOOL=$(jq -r '[.mcp_servers[]? | select(.name == "github")] | length > 0' <<<"$ag")
  HAS_PUSH=$(jq -r '(.system // "") | contains("# Push") and contains("branches named")' <<<"$ag")
  MEMBERS=$(jq -c '[.multiagent.agents[]? | {id, version}]' <<<"$ag")
  DEPVAULTS=$(ant beta:deployments retrieve --deployment-id "$(jq -r .deployment_id <<<"$INST")" </dev/null 2>/dev/null | jq -r '(.vault_ids // []) | join(" ")')
}

status() {
  ant_ok
  local lp tf vid mode
  lp=$(jq -c '.lead.push // {}' "$PCFG")
  echo "Lead of $PROJECT: who may push"
  echo "  members     never (they have no GitHub tool and the repository mount is read-only)"
  ok "this session" "$(jq -r 'if .local then "may push agent branches and open pull requests; merges and releases need your explicit word" else "no grant: asks before every push" end' <<<"$lp")"
  if [ "$(jq -r '.cloud // "none"' <<<"$lp")" != branches ]; then
    ok "cloud lead" "no grant: it never pushes   (create one: qargi lead grant $PROJECT)"; return 0
  fi
  ok "cloud lead" "may push $(jq -r '.branch_pattern // "agent/*"' <<<"$lp") and open pull requests; merge: $(jq -r '.merge // "ask"' <<<"$lp"); releases: not through this tool"
  tf=$(jq -r '.credential_file // ""' <<<"$lp"); vid=$(jq -r '.vault_id // ""' <<<"$lp")
  if [ -f "$tf" ]; then mode=$(stat -c %a "$tf"); [ "$mode" = 600 ] && ok "token file" "$tf (mode 600)" || ok "token file" "$tf has mode $mode: chmod 600 it"; else ok "token file" "MISSING ($tf)"; fi
  if [ -n "$vid" ]; then
    local n; n=$(ant beta:vaults:credentials list --vault-id "$vid" </dev/null 2>/dev/null | jq -r 'select((.archived_at // null) == null) | .id' | grep -c . || true)
    [ "$n" -ge 1 ] && ok "vault" "$vid with $n active credential" || ok "vault" "$vid has NO active credential: qargi lead grant $PROJECT"
  else ok "vault" "MISSING: qargi lead grant $PROJECT"; fi
  lead_state
  if [ -z "$INST" ]; then ok "lead agent" "not provisioned: qargi provision plan $LEAD"; return 0; fi
  ok "lead agent" "$AGENT v$AVER"
  [ "$HAS_TOOL" = true ] && ok "GitHub tool" "attached" || ok "GitHub tool" "MISSING: qargi packs apply $LEAD"
  [ "$HAS_PUSH" = true ] && ok "Push rules" "in its prompt" || ok "Push rules" "MISSING from its prompt: qargi instances refresh-prompt $LEAD"
  case " $DEPVAULTS " in *" $vid "*) ok "deployment" "the vault is attached";; *) ok "deployment" "the vault is NOT attached: qargi lead grant $PROJECT";; esac
  # members are pinned by version; a newer member version means the lead should be updated
  local line id v cur stale=0
  for line in $(jq -r '.[] | "\(.id):\(.version)"' <<<"$MEMBERS"); do
    id=${line%%:*}; v=${line##*:}
    cur=$(ant beta:agents retrieve --agent-id "$id" </dev/null 2>/dev/null | jq -r .version)
    [ "$cur" = "$v" ] || { stale=1; ok "member" "$id pinned at v$v, current v$cur: re-point the lead: qargi instances refresh-prompt $LEAD"; }
  done
  [ "$stale" = 0 ] && ok "members" "all pinned at their current versions"
  return 0
}

grant() {
  need_tty; ant_ok
  jq -e '(.teams // {}) | length > 0' "$PCFG" >/dev/null || die "$PROJECT defines no teams, so there is no lead to grant"
  lead_state
  [ -n "$INST" ] || die "the lead is not provisioned yet: qargi provision plan $LEAD, then apply it"
  local slug; slug=$(jq -r .repo.url "$PCFG"); slug=${slug#https://github.com/}; slug=${slug%.git}
  echo "Grant the cloud lead of $PROJECT the right to push to $slug."
  echo "Only the lead pushes, never a member. It may create agent/* branches and open pull requests;"
  echo "merging is asked of you each time. It cannot publish releases."
  tmp=$(mktemp -d); chmod 700 "$tmp"; trap 'rm -rf "$tmp"' EXIT
  tf=$tmp/token
  if [ -n "$FROM" ]; then tr -d ' \t\r\n' < "$FROM" > "$tf"
  else
    cat <<EOF

You need a fine-grained token for this one repository. Create it at
  https://github.com/settings/personal-access-tokens/new
  Resource owner: $(printf '%s' "$slug" | cut -d/ -f1)    Repository access: Only select repositories -> $slug
  Repository permissions: Contents = Read and write, Pull requests = Read and write (Metadata read is added)
  Nothing else: no Administration, no Workflows, no other repositories.
EOF
    confirm "Have you created it?" || { echo "Come back with it: qargi lead grant $PROJECT"; return 1; }
    printf 'Paste the token (input is hidden): ' > "$TTY_OUT"; local t; read -rs t < "$TTY_IN"; echo > "$TTY_OUT"
    ( umask 077; printf '%s' "$t" | tr -d ' \t\r\n' > "$tf" ); t=''
  fi
  [ -s "$tf" ] || die "no token given"
  step "1/3 Check the token, store it, create the vault and record the grant" \
    "$here/cred.sh" setup lead-push "$PROJECT" --from-file "$tf" --asked "$ASKED" || return 1
  lead_state
  if [ "$HAS_TOOL" = true ]; then echo; echo "== 2/3 GitHub tool: already attached to the lead"; else
    step "2/3 Give the lead the GitHub tool" "$here/packs.sh" packs apply "$LEAD" --asked "$ASKED" || return 1
  fi
  lead_state
  if [ "$HAS_PUSH" = true ]; then echo; echo "== 3/3 Push rules: already in the lead's prompt"; else
    step "3/3 Give the lead its Push rules" "$here/registry.sh" refresh-prompt "$LEAD" --asked "$ASKED" || return 1
  fi
  audit_log lead-grant "$PROJECT"
  echo; status
  echo; echo "Done. Releases stay with the Claude Code session ('release it'). To undo this: qargi lead revoke $PROJECT"
}

revoke() {
  need_tty; ant_ok
  local lp vid tf; lp=$(jq -c '.lead.push // {}' "$PCFG")
  [ "$(jq -r '.cloud // "none"' <<<"$lp")" = branches ] || { echo "The cloud lead of $PROJECT has no push grant."; return 0; }
  vid=$(jq -r '.vault_id // ""' <<<"$lp"); tf=$(jq -r '.credential_file // ""' <<<"$lp")
  echo "Take the push grant away from the cloud lead of $PROJECT:"
  echo "  - record cloud: none in the project answers, remove the GitHub tool and the Push rules from the lead"
  echo "  - detach and archive the vault credential ($vid) and delete the token file ($tf)"
  confirm "Revoke?" || { echo "Nothing changed."; return 1; }
  "$here/project.sh" set "$PROJECT" lead.push "$(jq -c '.cloud = "none" | del(.credential_file, .vault_id)' <<<"$lp")" >/dev/null || die "could not update the project answers"
  step "1/2 Remove the GitHub tool from the lead" "$here/packs.sh" packs apply "$LEAD" --asked "$ASKED" || true
  step "2/2 Rebuild the lead's prompt without the Push rules" "$here/registry.sh" refresh-prompt "$LEAD" --asked "$ASKED" || true
  local li did c
  li=$(jq -c --arg n "$LEAD" '.[$n] // empty' "$REG")
  if [ -n "$li" ] && [ -n "$vid" ]; then
    did=$(jq -r .deployment_id <<<"$li")
    ant beta:deployments update --deployment-id "$did" --vault-id '[]' </dev/null >/dev/null 2>&1 && echo "vault detached from the deployment" || echo "could not detach the vault from the deployment: do it by hand"
    for c in $(ant beta:vaults:credentials list --vault-id "$vid" </dev/null 2>/dev/null | jq -r 'select((.archived_at // null) == null) | .id'); do
      ant beta:vaults:credentials archive --vault-id "$vid" --credential-id "$c" </dev/null >/dev/null 2>&1 && echo "credential $c archived"
    done
  fi
  [ -z "$tf" ] || { rm -f "$tf" && echo "token file deleted"; }
  audit_log lead-revoke "$PROJECT"
  echo
  echo "Last step, which only you can do: revoke the token on GitHub (Settings -> Developer settings -> Fine-grained tokens)."
}

case $verb in
  grant) grant;;
  status) status;;
  revoke) revoke;;
  *) die "usage: lead.sh grant|status|revoke PROJECT";;
esac
