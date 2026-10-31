#!/usr/bin/env bash
# LIVE smoke test, opt-in, NOT part of tests/run.sh: does a real Claude Code session load a skill from the directory
# that `qargi packs apply --target claude-code` renders, through --add-dir?
#
#   QARGI_LIVE=1 tests/live/claude_addir_smoke.sh
#
# COST: one small model call (claude -p --model haiku --max-turns 3), a few cents at most. It needs the real
# `claude` binary, logged in. It uses a temporary QARGI_CONF and QARGI_STATE in a temporary directory and a scratch
# working directory; qargi never reads or writes the real ~/.qargi or ~/.claude (the claude binary itself uses the
# caller's login and keeps its own session record, as any claude run does).
set -u
if [ "${QARGI_LIVE:-}" != 1 ]; then
  echo "refusing to run: this test makes one real (small, paid) model call. Set QARGI_LIVE=1 to run it." >&2
  exit 2
fi
cd "$(dirname "$0")/../.." || exit 1
command -v claude >/dev/null 2>&1 || { echo "claude is not on PATH" >&2; exit 2; }
echo "COST WARNING: one claude -p call with --model haiku and --max-turns 3 (a few cents at most)."

REAL_HOME=$HOME
for _v in $(compgen -e); do case $_v in QARGI_*) unset "$_v";; esac; done
unset _v
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export QARGI_CONF=$T/conf QARGI_STATE=$T/state
mkdir -p "$QARGI_CONF/projects" "$QARGI_STATE" "$T/cwd"
DA=$PWD/bin/qargi
fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }

PROBE=qargi-probe-skill
jq -n '{schema:1,project:"smoke",repo:{url:"https://github.com/example/x",path:"",long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$QARGI_CONF/projects/smoke.json"
tok_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
"$DA" skill new "$PROBE" >/dev/null
sed -i "s/^description: .*/description: Use when asked about the qargi probe; it only exists to prove that skills are loaded./" "$QARGI_CONF/packs/skills/$PROBE/SKILL.md"
t=$("$DA" skill seal "$PROBE" | tok_of); "$DA" skill seal "$PROBE" --plan "$t" --approved "live smoke" >/dev/null
"$DA" skill link "$PROBE" --scope project --project smoke >/dev/null
t=$("$DA" packs apply --target claude-code smoke | tok_of)
"$DA" packs apply --target claude-code smoke --plan "$t" --approved "live smoke" >/dev/null || { echo "FAIL: packs apply" >&2; exit 1; }
R=$QARGI_STATE/claude/smoke
[ -f "$R/.claude/skills/$PROBE/SKILL.md" ] && ok "the probe skill is rendered in $R" || { no "the render is missing the probe skill"; exit 1; }
"$DA" packs check --target claude-code smoke >/dev/null && ok "check passes on the render" || no "check on the render"

# The call itself: from a scratch cwd, with the render as the only added directory. HOME stays the caller's (the login
# lives there); nothing of qargi's is passed on.
cd "$T/cwd" || exit 1
PROMPT="List the names of the available skills that start with 'qargi-probe'. Reply with just the names, one per line, or NONE if there are none."
out=$(HOME=$REAL_HOME claude -p --add-dir "$R" --model haiku --max-turns 3 "$PROMPT" </dev/null 2>&1); rc=$?
echo "claude exit $rc; reply:"; echo "$out" | sed 's/^/  | /'
[ "$rc" = 0 ] && ok "claude -p exited 0" || no "claude -p exited $rc"
grep -q "$PROBE" <<<"$out" && ok "the reply names $PROBE: --add-dir loaded the rendered skill" || no "the reply does not name $PROBE"
exit $fail
