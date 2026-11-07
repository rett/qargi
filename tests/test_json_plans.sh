#!/usr/bin/env bash
# `qargi AREA VERB ... --json`: the plan of a gated verb as one JSON object (lib/jsonplan.py, called by bin/qargi). The real dispatcher with a cheap
# gated verb (packs seed) in a temporary library, and lib/jsonplan.py with a stand-in qargi for the shapes no cheap verb prints. Offline, hermetic.
# Run: tests/test_json_plans.sh
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
trap 'rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
DA=$ROOT/bin/qargi
export QARGI_CONF=$T/c QARGI_STATE=$T/s
mkdir -p "$T/c/projects" "$T/s"
LIB=$T/c/packs
j() { jq -r "$1" <<<"$OUT"; }
tok_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
empty_lib() { [ -z "$(ls -A "$LIB/skills" 2>/dev/null)" ]; }

# --- 1. a plan: one JSON object with the plan text, the token, the command that applies it and the exit status
OUT=$("$DA" packs seed --json 2>"$T/err"); RC=$?
if [ "$RC" = 0 ] && [ "$(wc -l <<<"$OUT")" = 1 ] && jq -e . >/dev/null <<<"$OUT"; then ok "a plan is one line of JSON and the exit status is the verb's"; else no "plan output (rc=$RC)"; echo "$OUT" | head -5; fi
TOK=$(j .token)
[[ $TOK =~ ^[0-9a-f]{12}$ ]] && ok "the token has the form the verb prints" || no "token: $TOK"
PLAIN=$("$DA" packs seed 2>&1); PTOK=$(tok_of <<<"$PLAIN")
{ [ -n "$TOK" ] && [ "$TOK" = "$PTOK" ]; } && ok "and it equals the token of the same call without --json" || no "token differs from the plain call ($PTOK)"
{ [ "$(j .verb)" = "packs seed" ] && [ "$(j .exit)" = 0 ]; } && ok "verb and exit are set" || no "verb/exit: $(j '[.verb,.exit]')"
if [ "$(j '.plan|type')" = string ] && ! grep -q 'plan token' <<<"$(j .plan)" && grep -q 'skill' <<<"$(j .plan)"; then ok "the plan is the text without the token line"; else no "plan text"; j .plan | head -3; fi
[ "$(j .apply)" = "qargi packs seed --plan $TOK --approved \"<the user's go-ahead>\"" ] && ok "apply is the call, --plan TOKEN and --approved with the words to fill in" || no "apply: $(j .apply)"
[ "$(j 'has("output")')" = false ] && ok "a plan has no output key" || no "plan has an output key"
empty_lib && ok "asking for the plan stored nothing" || no "the plan stored something"

# --- 2. --json never approves: with --plan alone nothing is stored
OUT=$("$DA" packs seed --plan "$TOK" --json 2>/dev/null); RC=$?
{ empty_lib && [ "$(j .token)" = null ]; } && ok "--plan with --json and no --approved stores nothing and offers no token" || { no "--plan alone stored something or offered a token"; echo "$OUT" | head -3; }

# --- 3. a refusal keeps the verb's exit status, its message stays on stderr, and the object still comes out
OUT=$("$DA" packs seed --plan 000000000000 --approved x --json 2>"$T/err"); RC=$?
{ [ "$RC" != 0 ] && [ "$(j .exit)" = "$RC" ] && [ "$(j .token)" = null ] && [ -s "$T/err" ] && grep -q "plan changed" "$T/err"; } && ok "a refused apply: exit kept, token null, the message on stderr" || { no "refusal (rc=$RC)"; echo "$OUT"; cat "$T/err"; }
OUT=$("$DA" bogus --json 2>/dev/null); RC=$?
{ [ "$RC" != 0 ] && [ "$(j .exit)" = "$RC" ]; } && ok "an unknown command is still an error" || no "bogus command (rc=$RC)"

# --- 4. wherever --json stands the call is the same
OUT=$("$DA" packs --json seed 2>/dev/null)
{ [ "$(j .verb)" = "packs seed" ] && [ "$(j .apply)" = "qargi packs seed --plan $(j .token) --approved \"<the user's go-ahead>\"" ]; } && ok "--json between the command and the verb: same verb, --json left out of apply" || no "packs --json seed: $OUT"

# --- 5. the apply: --plan and --approved with --json run the verb and wrap its output with a null token
OUT=$("$DA" packs seed --plan "$TOK" --approved "test go-ahead" --json 2>"$T/err"); RC=$?
if [ "$RC" = 0 ] && [ "$(j .exit)" = 0 ] && [ "$(j .token)" = null ] && [ "$(j .plan)" = null ] && grep -q 'seeded' <<<"$(j .output)"; then ok "--plan and --approved with --json apply, output wrapped, token null"; else no "apply (rc=$RC)"; echo "$OUT" | head -5; fi
empty_lib && no "nothing was stored" || ok "and the library holds the packs"
OUT=$("$DA" packs seed --json 2>/dev/null)
{ [ "$(j .token)" = null ] && grep -q 'nothing to seed' <<<"$(j .output)" && [ "$(j .exit)" = 0 ]; } && ok "a run with nothing to plan has token null and the text in output" || { no "empty plan"; echo "$OUT" | head -3; }

# --- 6. a verb with an option --json of its own keeps it, unwrapped
mkdir -p "$T/repo"
OUT=$("$DA" env show --repo "$T/repo" --json 2>/dev/null)
if jq -e . >/dev/null 2>&1 <<<"$OUT" && [ "$(j 'has("verb")')" = false ]; then ok "env show --json is the verb's own JSON, not wrapped"; else no "env show was wrapped"; echo "$OUT" | head -3; fi

# --- 7. the marker that says "this is the wrapped run" is honoured and is not passed on
OUT=$(QARGI_NO_JSON_WRAP=1 "$DA" packs seed --json 2>&1); RC=$?
{ [ "$RC" != 0 ] && grep -q 'unknown option' <<<"$OUT"; } && ok "with the marker set bin/qargi does not wrap again (the verb sees --json and refuses it)" || { no "marker (rc=$RC)"; echo "$OUT" | head -3; }
grep -q 'unset QARGI_NO_JSON_WRAP' bin/qargi && ok "bin/qargi takes the marker out before it runs a verb" || no "bin/qargi keeps the marker"

# --- 8. the shapes no cheap verb prints, with a stand-in bin/qargi beside a copy of lib/jsonplan.py: arguments with spaces, a token inside a line, stderr, a failing exit
mkdir -p "$T/mini/bin" "$T/mini/lib"
cp lib/jsonplan.py lib/commands.py "$T/mini/lib/"
cat > "$T/mini/bin/qargi" <<'F'
#!/usr/bin/env bash
printf 'args:'; printf ' [%s]' "$@"; echo
case " $* " in
  *" mode-line "*) echo "first line"; echo "plan only, nothing was changed; plan token: 0123456789ab   (apply with: --plan 0123456789ab --approved \"...\")"; echo "last line";;
  *" exit3 "*) echo "plan token: abcdef012345"; echo "to stderr" >&2; exit 3;;
  *" plain "*) echo "hello";;
  *" gated "*) echo "plan token: 111111111111   (apply with: ...)";;
esac
F
chmod +x "$T/mini/bin/qargi"
jp() { python3 -I "$T/mini/lib/jsonplan.py" "$@" 2>"$T/err"; }
OUT=$(jp feature finish "my feature" mode-line --keep --json); RC=$?
{ [ "$RC" = 0 ] && [ "$(j .token)" = 0123456789ab ] && [ "$(j .plan)" = $'args: [feature] [finish] [my feature] [mode-line] [--keep]\nfirst line\nplan only, nothing was changed\nlast line' ]; } && ok "a token inside a line leaves the rest of the line in the plan" || { no "mixed line"; echo "$OUT"; }
{ [ "$(j .apply)" = "qargi feature finish 'my feature' mode-line --keep --plan 0123456789ab --approved \"<the user's go-ahead>\"" ] && [ "$(j .verb)" = "feature finish" ]; } && ok "apply quotes the arguments that need it and keeps their order" || no "apply: $(j .apply)"
OUT=$(jp release exit3 --json); RC=$?
{ [ "$RC" = 3 ] && [ "$(j .exit)" = 3 ] && [ "$(j .token)" = abcdef012345 ] && grep -q 'to stderr' "$T/err" && ! grep -q 'to stderr' <<<"$OUT"; } && ok "the exit status of a plan is kept and stderr stays on stderr" || { no "exit3 (rc=$RC)"; echo "$OUT"; }
OUT=$(jp upgrade gated --json)
{ [ "$(j .verb)" = upgrade ] && [ "$(j .apply)" = "qargi upgrade gated --plan 111111111111 --approved \"<the user's go-ahead>\"" ]; } && ok "a command without verbs is named alone" || { no "upgrade shape"; echo "$OUT"; }
OUT=$(jp packs seed gated --approved yes --json)
{ [ "$(j .token)" = null ] && [ "$(j .plan)" = null ] && grep -q '111111111111' <<<"$(j .output)"; } && ok "--approved with --json never yields a token to apply" || { no "--approved"; echo "$OUT"; }
OUT=$(jp packs seed gated --plan=aaaaaaaaaaaa --json)
[ "$(j .token)" = null ] && ok "--plan=TOKEN is recognised too" || no "--plan=TOKEN"
OUT=$(jp packs seed plain --json)
{ [ "$(j .token)" = null ] && [ "$(j .output)" = $'args: [packs] [seed] [plain]\nhello' ]; } && ok "no token: output holds the text, and the verb never saw --json" || { no "plain"; echo "$OUT"; }

exit "$fail"
