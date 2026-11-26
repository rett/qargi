#!/usr/bin/env bash
# A link of dispatch.home.link that is private (the sign-in is a JSON file the runtime refreshes in place): each run gets a copy of its own with a
# placeholder in place of the refresh token, so the runs that share the source overlap and take no lock; a run that would outlive the access token is
# refused before it starts; the source is never written. A fake CLI stands in for the runtime, and every token here is a dummy built by this test
# (nothing real, nothing sent anywhere). Run: tests/test_signin_copy.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
umask 077
unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GIT_AUTHOR_DATE GIT_COMMITTER_DATE
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0
export QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T TMPDIR=$T/tmp
mkdir -p "$T/tmp" "$T/bin" "$T/c/projects"
# shellcheck source=fixtures.sh
. tests/fixtures.sh
copy_tool . "$T/tool"
DA=$T/tool/bin/qargi
LC="git -c user.name=t -c user.email=t@example.net"
git init -q -b main "$T/r" && $LC -C "$T/r" commit -q --allow-empty -m one
proj() { jq -n --arg n "$1" --arg p "$2" --arg v "$3" '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:$v},memory:{},budget_cents:500}' > "$T/c/projects/$1.json"; }
prep() { # slug -> exports RUN CLONE OUT
  eval "$($DA local prepare --repo "$T/r" --base main --slug "$1" --scratch "$T" | sed '/^$/,$d' | sed 's/^/export /')"; }
task() { printf 'TASK: change the thing\nDONE: it is changed\n' > "$RUN/task.md"; }

# the dummy sign-in: a JWT-shaped access token whose payload says when it ends, and two more dummy tokens; nothing of it is a credential
b64() { python3 -c 'import base64,sys; print(base64.urlsafe_b64encode(sys.stdin.buffer.read()).decode().rstrip("="))'; }
jwt() { # SECONDS-FROM-NOW -> a JWT-shaped dummy that ends then
  local h p; h=$(printf '{"alg":"none"}' | b64); p=$(printf '{"exp":%d,"sub":"dummy"}' $(( $(date +%s) + $1 )) | b64); printf '%s.%s.dummy-signature-%s' "$h" "$p" "$RANDOM"; }
MEM=$HOME/.fakesi-members; mkdir -p "$MEM"; chmod 700 "$MEM"; SRC=$MEM/auth.json
REFR=dummy-refresh-$RANDOM$RANDOM; IDT=dummy-id-$RANDOM$RANDOM
signin() { # SECONDS-FROM-NOW -> the source, with an access token that ends then (the token is kept in $T/want-access for the fake to compare)
  ACC=$(jwt "$1"); printf '%s' "$ACC" > "$T/want-access"
  jq -n --arg a "$ACC" --arg i "$IDT" --arg r "$REFR" '{auth_mode:"chatgpt",OPENAI_API_KEY:null,last_refresh:"2026-11-20T10:00:00Z",tokens:{access_token:$a,id_token:$i,refresh_token:$r,account_id:"dummy-account"}}' > "$SRC"; chmod 600 "$SRC"; }
sum() { sha256sum < "$1" | cut -c1-64; }
notokens() { # FILE...: none of the dummy tokens is in any of the files
  ! grep -qF -e "$ACC" -e "$IDT" -e "$REFR" -e dummy-signature "$@"; }
notext() { # TEXT: none of the dummy tokens is in the text
  ! grep -qF -e "$ACC" -e "$IDT" -e "$REFR" -e dummy-signature <<<"$1"; }

# the fake runtime: it says what it finds at $FAKESI_HOME/auth.json without printing a token, then does what $T/mode says
cat > "$T/bin/fakesi" <<SH
#!/usr/bin/env bash
a=\$FAKESI_HOME/auth.json
if [ -L "\$a" ]; then echo ISLINK=yes; else echo ISLINK=no; fi
echo "FILEMODE=\$(stat -c %a "\$a")"
echo "PLACEHOLDER=\$([ "\$(jq -r .tokens.refresh_token "\$a")" = qargi-no-refresh ] && echo yes || echo no)"
echo "ACCESS=\$([ "\$(jq -r .tokens.access_token "\$a")" = "\$(cat "$T/want-access")" ] && echo same || echo other)"
echo "ID=\$([ "\$(jq -r .tokens.id_token "\$a")" = "$IDT" ] && echo same || echo other)"
echo "MEMBER=\$\$"
cat > /dev/null
case \$(cat "$T/mode" 2>/dev/null) in
  pair)    # two runs at once: each waits until the other has started too, so a lock that made them queue fails here
    : > "$T/in.\$\$"
    end=\$((SECONDS + 30))
    until [ "\$(find "$T" -maxdepth 1 -name 'in.*' | wc -l)" -ge 2 ]; do [ "\$SECONDS" -lt "\$end" ] || { echo NOOVERLAP; exit 7; }; sleep 0.05; done
    echo OVERLAP;;
  rewrite) echo '{"rewritten": "by the member"}' > "\$a";;
  replace) rm -f "\$a"; echo '{"replaced": "by the member"}' > "\$a";;
  delete)  rm -f "\$a";;
  hold)    echo \$\$ > "$T/member.pid"; : > "$T/hold-ready"
           while [ ! -e "$T/hold-go" ]; do sleep 0.1; done;;
esac
exit 0
SH
chmod 755 "$T/bin/fakesi"; export PATH=$T/bin:$PATH

LIB=$T/c/packs/providers
mk() { mkdir -p "$LIB/$1"; printf '%s\n' "$2" > "$LIB/$1/definition.json"; python3 -I tests/handseal.py "$LIB/$1"; }
M='{"pattern":"^fake-.+$","tiers":{"*":{"model":"fake-m-1","alias":null,"verified_on":null,"source":"test"}},"effort":{"low":"l","medium":"m","high":"h","xhigh":null,"max":null}}'
PRIV='{"set":{"tokens.refresh_token":"qargi-no-refresh"},"expiry":{"path":"tokens.access_token","encoding":"jwt-exp"}}'
def() { # NAME LINKS-JSON -> a sealed library runtime whose run home links the given entries
  mk "$1" "$(jq -n --arg n "$1" --argjson m "$M" --argjson l "$2" '{schema:2,kind:"provider",provider:$n,family:null,surface:"local",models:$m,
    capabilities:{},agents:null,resources:{},barrier:{kind:"none"},
    dispatch:{mode:"command",argv:["fakesi","--out","{out}"],prompt:{via:"stdin"},cwd:"{clone}",timeout_s:60,home:{env:"FAKESI_HOME",dir:".fk",link:$l},
      output:{format:"text"},exit:{"0":"ok","*":"failed"}}}')"; }
def fakeall "$(jq -n --argjson p "$PRIV" '[{from:"~/.fakesi-members/auth.json",to:"auth.json",private:$p}]')"
def fakemix "$(jq -n --argjson p "$PRIV" '[{from:"~/.fakesi-members/auth.json",to:"auth.json",private:$p},{from:"~/.fakesi-members/settings.json",to:"settings.json"}]')"
def fakemarg "$(jq -n '[{from:"~/.fakesi-members/auth.json",to:"auth.json",private:{set:{"tokens.refresh_token":"qargi-no-refresh"},expiry:{path:"tokens.access_token",encoding:"jwt-exp",margin_seconds:0}}}]')"
def fakeplain '[{"from":"~/.fakesi-members/auth.json","to":"auth.json"}]'
setprov() { proj rproj "$T/r" "$1"; }
LOCKF=$MEM/.qargi-run.lock; DECL=\~/.fakesi-members/auth.json   # the source as the definition declares it: what a message names
printf '{"k": 1}\n' > "$MEM/settings.json"

# --- the dry run and prepare ------------------------------------------------------------------------------------------------------------
signin 259200; setprov fakeall; prep dry1; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -qxF "HOME_COPIES=auth.json<-$(realpath "$SRC")" <<<"$out" && ! grep -q '^HOME_LINKS=' <<<"$out" && notext "$out" \
  && [ ! -e "$RUN/home/.fk" ] && [ ! -e "$LOCKF" ]; } \
  && ok "the dry run names each private copy with its source path (HOME_COPIES=NAME<-PATH), prints no content, and makes nothing, no lock file" || no "dry run: rc=$rc $out"
setprov fakemix; prep dry2; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -qxF "HOME_COPIES=auth.json<-$(realpath "$SRC")" <<<"$out" && grep -qxF "HOME_LINKS=settings.json<-$(realpath "$MEM/settings.json")" <<<"$out"; } \
  && ok "a home with a private and a plain link prints both lines" || no "dry run mixed: rc=$rc $out"
rm -f "$SRC"
out=$($DA local prepare --repo "$T/r" --base main --slug nopre --scratch "$T" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "$DECL" <<<"$out" && grep -qF 'does not exist' <<<"$out"; } \
  && ok "prepare applies the source rule to a private link too: a source that does not exist is refused (exit 2), naming the declared path" || no "prepare no source: rc=$rc $out"
signin 259200

# --- two runs at once overlap, with no lock; each has a private copy -----------------------------------------------------------------------
setprov fakeall; echo pair > "$T/mode"; rm -f "$T"/in.*
prep ov1; R1=$RUN; task; prep ov2; R2=$RUN; task; BEFORE=$(sum "$SRC")
( $DA local run "$R1" > "$T/p1.out" 2>&1; echo $? > "$T/p1.rc" ) &
( $DA local run "$R2" > "$T/p2.out" 2>&1; echo $? > "$T/p2.rc" ) &
wait_until '[ -s "$T/p1.rc" ] && [ -s "$T/p2.rc" ]' 60
{ [ "$(cat "$T/p1.rc")" = 0 ] && [ "$(cat "$T/p2.rc")" = 0 ] && grep -q '^OVERLAP$' "$R1/out/transcript" && grep -q '^OVERLAP$' "$R2/out/transcript"; } \
  && ok "two runs that share one private source run at the same time and both finish" || no "overlap: $(cat "$T"/p?.rc 2>&1) $(cat "$T/p1.out" "$T/p2.out")"
{ ! grep -q 'holds the lock' "$T/p1.out" "$T/p2.out" && ! grep -q 'waiting for it' "$T/p1.out" "$T/p2.out" && [ ! -e "$LOCKF" ]; } \
  && ok "neither run printed a wait note, and no lock file was made beside the sign-in" || no "lock note or file: $(cat "$T/p1.out" "$T/p2.out") $(ls -A "$MEM")"
for r in "$R1" "$R2"; do
  { grep -q '^ISLINK=no$' "$r/out/transcript" && grep -q '^FILEMODE=600$' "$r/out/transcript" && grep -q '^PLACEHOLDER=yes$' "$r/out/transcript" \
    && grep -q '^ACCESS=same$' "$r/out/transcript" && grep -q '^ID=same$' "$r/out/transcript" && [ ! -e "$r/home/.fk/auth.json" ] && [ ! -L "$r/home/.fk/auth.json" ]; } \
    && ok "the member of $(basename "$r") saw a regular file, mode 600, with the placeholder in place of the refresh token and the rest as it was; it is gone when the run ends" \
    || no "copy of $r: $(cat "$r/out/transcript") $(ls -lA "$r/home/.fk")"
done
{ [ "$(sum "$SRC")" = "$BEFORE" ] && [ "$(stat -c %a "$SRC")" = 600 ] && notokens "$R1/dispatch.json" "$R2/dispatch.json" "$T/p1.out" "$T/p2.out"; } \
  && ok "the source is byte for byte as it was, and no token is in an output or in dispatch.json" || no "source or record: $(cat "$R1/dispatch.json")"
want='[{"expires_in_seconds":0,"set":["tokens.refresh_token"],"to":"auth.json"}]'
got=$(jq -c '.home.private | map(.expires_in_seconds |= (if . > 259000 and . <= 259200 then 0 else . end))' "$R1/dispatch.json")
{ [ "$got" = "$want" ] && [ "$(jq -c '.home | {links, private: (.private | length)}' "$R1/dispatch.json")" = '{"links":[],"private":1}' ]; } \
  && ok "dispatch.json records home.private: the name, the paths set and the seconds left at the start, and no link" || no "record: $got $(jq -c .home "$R1/dispatch.json")"
rm -f "$T/mode" "$T"/in.*

# --- what the member does to its copy stays in the run home and is removed: nothing is written to the source ------------------------------
for mode in rewrite replace delete; do
  echo "$mode" > "$T/mode"; prep "cp-$mode"; task
  out=$($DA local run "$RUN" 2>&1); rc=$?
  case $mode in delete) note='the private copy auth.json was removed from the run home during the run';; *) note='the private copy auth.json was changed during the run';; esac
  { [ "$rc" = 0 ] && grep -qF "$note" <<<"$out" && [ "$(sum "$SRC")" = "$BEFORE" ] && [ ! -e "$RUN/home/.fk/auth.json" ] && [ -z "$(ls -A "$RUN/home/.fk")" ] \
    && notext "$out" && notokens "$RUN/dispatch.json" && ! grep -qF 'by the member' <<<"$out"; } \
    && ok "the member $mode its copy: the source is untouched, the copy is removed with a note that names it and holds no value" || no "copy $mode: rc=$rc $out $(ls -lA "$RUN/home/.fk")"
done
rm -f "$T/mode"

# --- a run that would outlive the access token is refused before anything is made or recorded ---------------------------------------------
signin 1100; prep ex1; task
out=$($DA local run "$RUN" --timeout 300 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF '[runtime-signin-expiring]' <<<"$out" \
  && grep -qE "sign-in ~/.fakesi-members/auth.json for fakeall member runs ends in 1[01][0-9][0-9] s, less than the run's bound of 300 s \(set by timeout-option\) plus a margin of 900 s \(margin\)" <<<"$out" \
  && grep -qF 'FAKESI_HOME=~/.fakesi-members fakesi login' <<<"$out" && [ ! -e "$RUN/home/.fk" ] && [ ! -e "$RUN/out/transcript" ] && [ ! -e "$RUN/dispatch.json" ] \
  && notext "$out" && ! grep -qF "$MEM" <<<"$out"; } \
  && ok "a token that ends inside the run's bound plus the margin: refused (runtime-signin-expiring, exit 1) with the seconds left, the bound and where it is set, the margin and the login; nothing made, no record" \
  || no "expiring: rc=$rc $out $(ls -lA "$RUN" 2>&1)"
out=$($DA local run "$RUN" --timeout 100 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -r .outcome "$RUN/dispatch.json")" = ok ]; } \
  && ok "the refusal consumed no attempt: the same run starts without --again once the bound fits before the token ends (the bound is the run's own)" || no "bound fits: rc=$rc $out"
signin 500; prep ex3; task
out=$($DA local run "$RUN" --timeout 600 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF "less than the run's bound of 600 s (set by timeout-option) plus a margin of 900 s (bound-exceeds)" <<<"$out" && grep -qF 'lower --timeout' <<<"$out"; } \
  && ok "a bound longer than the time left says so (bound-exceeds) and names the way (lower --timeout)" || no "bound exceeds: rc=$rc $out"
signin 5; prep ex2; task
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF "run's bound of 60 s (set by definition) plus a margin of 900 s" <<<"$out"; } \
  && ok "without --timeout the bound is the definition's own timeout_s (60 here), and the message says it is the definition's" || no "default bound: rc=$rc $out"
# the margin is the definition's: a declaration with margin_seconds 0 takes a token that outlasts the bound alone
setprov fakemarg; signin 1100; prep mg1; task
out=$($DA local run "$RUN" --timeout 1000 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -r .outcome "$RUN/dispatch.json")" = ok ]; } \
  && ok "expiry.margin_seconds is the definition's value (0 here): a token that outlasts the bound alone starts the run" || no "margin 0: rc=$rc $out"
prep mg2; task; out=$($DA local run "$RUN" --timeout 1200 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF "plus a margin of 0 s (bound-exceeds)" <<<"$out"; } && ok "and with that margin a bound beyond the time left is still refused" || no "margin 0 refuse: rc=$rc $out"
setprov fakeall; signin 259200

# --- a source that is not what a private copy needs ------------------------------------------------------------------------------------------
cp "$SRC" "$T/good.json"
bad() { # LABEL EXPECTED-TEXT: the source (set by the caller) is refused (exit 2) and nothing is made
  prep "bad-$1"; task; out=$($DA local run "$RUN" 2>&1); rc=$?
  { [ "$rc" = 2 ] && grep -qF "$2" <<<"$out" && grep -qF "$DECL" <<<"$out" && [ ! -e "$RUN/home/.fk" ] && [ ! -e "$RUN/out/transcript" ] \
    && [ ! -e "$RUN/dispatch.json" ] && notext "$out"; } \
    && ok "$1: refused (exit 2), naming the declared path, nothing made or recorded" || no "$1: rc=$rc $out"; }
printf 'this is not json, but it holds %s' "$REFR" > "$SRC"; bad notjson 'is not a JSON object'
printf '[1, 2]\n' > "$SRC"; bad array 'is not a JSON object'
jq 'del(.tokens)' "$T/good.json" > "$SRC"; bad notokens 'has no object at tokens'
jq 'del(.tokens.access_token)' "$T/good.json" > "$SRC"; bad noaccess 'has no token with an expiry at tokens.access_token (jwt-exp)'
jq '.tokens.access_token = "dummy-not-a-jwt"' "$T/good.json" > "$SRC"; bad notjwt 'has no token with an expiry at tokens.access_token (jwt-exp)'
jq '.tokens.access_token = "a.e30.c"' "$T/good.json" > "$SRC"; bad noexp 'has no token with an expiry at tokens.access_token (jwt-exp)'
head -c 40 "$T/good.json" > "$SRC"; bad half 'is not a JSON object'
cp "$T/good.json" "$SRC"

# --- the real path is checked again, and a source inside the user's own runtime directory stays refused -----------------------------------------
mkdir -p "$HOME/.codex"; printf '{"tokens":{"access_token":"%s"}}\n' "$(jwt 259200)" > "$HOME/.codex/auth.json"; OWN=$(sum "$HOME/.codex/auth.json")
prep sw1; task; mv "$SRC" "$T/auth.real"; ln -s "$HOME/.codex/auth.json" "$SRC"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && [ ! -e "$RUN/home/.fk/auth.json" ] && [ ! -e "$RUN/out/transcript" ] && [ "$(sum "$HOME/.codex/auth.json")" = "$OWN" ] && [ ! -e "$HOME/.codex/.qargi-run.lock" ]; } \
  && ok "a source swapped for a link into the user's own directory after prepare is refused (exit 2): nothing is copied, the user's file is as it was" || no "swap: rc=$rc $out"
rm -f "$SRC"; mv "$T/auth.real" "$SRC"; rm -rf "$HOME/.codex"
BEFORE=$(sum "$SRC")

# --- a plain link still takes the lock, as before; all private links take none -------------------------------------------------------------
setprov fakeplain; echo hold > "$T/mode"; rm -f "$T/hold-ready" "$T/hold-go"
prep pl1; task; P1=$RUN; prep pl2; task; P2=$RUN
( $DA local run "$P1" > "$T/l1.out" 2>&1; echo $? > "$T/l1.rc" ) &
wait_until '[ -e "$T/hold-ready" ]' 30
{ [ "$(stat -c %a "$LOCKF")" = 600 ] && ! flock -n "$LOCKF" true; } && ok "a plain link: a run holds the lock beside its source (mode 600) as before" || no "plain lock: $(ls -lA "$MEM")"
( $DA local run "$P2" > "$T/l2.out" 2>&1; echo $? > "$T/l2.rc" ) &
wait_until 'grep -q "waiting for it to end" "$T/l2.out"' 30
grep -qxF 'qargi: note: another fakeplain member run holds the lock ~/.fakesi-members/.qargi-run.lock (one run at a time per sign-in); waiting for it to end' "$T/l2.out" \
  && ok "and a second run of it waits with the note, as before" || no "plain wait: $(cat "$T/l2.out")"
: > "$T/hold-go"; wait_until '[ -s "$T/l1.rc" ] && [ -s "$T/l2.rc" ]' 30
{ [ "$(cat "$T/l1.rc")" = 0 ] && [ "$(cat "$T/l2.rc")" = 0 ]; } && ok "both runs end ok, one after the other" || no "plain end: $(cat "$T/l1.rc" "$T/l2.rc")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$LOCKF"
# mixed: the plain link of the home takes the lock, the private one needs none
setprov fakemix; echo hold > "$T/mode"
prep mx1; task; X1=$RUN; prep mx2; task; X2=$RUN
( $DA local run "$X1" > "$T/m1.out" 2>&1; echo $? > "$T/m1.rc" ) &
wait_until '[ -e "$T/hold-ready" ]' 30
{ [ -e "$LOCKF" ] && ! flock -n "$LOCKF" true; } && ok "a home with a private and a plain link: the run holds the lock for the plain one" || no "mixed lock: $(ls -lA "$MEM")"
( $DA local run "$X2" > "$T/m2.out" 2>&1; echo $? > "$T/m2.rc" ) &
wait_until 'grep -q "waiting for it to end" "$T/m2.out"' 30
grep -qF 'another fakemix member run holds the lock ~/.fakesi-members/.qargi-run.lock' "$T/m2.out" \
  && ok "and a second run of it waits for the plain link's lock" || no "mixed wait: $(cat "$T/m2.out")"
: > "$T/hold-go"; wait_until '[ -s "$T/m1.rc" ] && [ -s "$T/m2.rc" ]' 30
{ [ "$(cat "$T/m1.rc")" = 0 ] && [ "$(cat "$T/m2.rc")" = 0 ] && [ "$(sum "$SRC")" = "$BEFORE" ]; } && ok "both end ok, and the source is as it was" || no "mixed end: $(cat "$T/m1.rc" "$T/m2.rc")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$LOCKF"
# the token is checked again once the locks are held: a run that waited while the sign-in was replaced by one that ends too soon is refused when it holds them
echo hold > "$T/mode"; prep lw1; task; W1=$RUN; prep lw2; task; W2=$RUN
( $DA local run "$W1" > "$T/w1.out" 2>&1; echo $? > "$T/w1.rc" ) &
wait_until '[ -e "$T/hold-ready" ]' 30
( $DA local run "$W2" > "$T/w2.out" 2>&1; echo $? > "$T/w2.rc" ) &
wait_until 'grep -q "waiting for it to end" "$T/w2.out"' 30
signin 400
: > "$T/hold-go"; wait_until '[ -s "$T/w1.rc" ] && [ -s "$T/w2.rc" ]' 30
{ [ "$(cat "$T/w1.rc")" = 0 ] && [ "$(cat "$T/w2.rc")" = 1 ] && grep -qF '[runtime-signin-expiring]' "$T/w2.out" && [ ! -e "$W2/out/transcript" ] && [ ! -e "$W2/home/.fk/auth.json" ] \
  && [ "$(jq -r .outcome "$W2/dispatch.json")" = refused ] && notext "$(cat "$T/w2.out")"; } \
  && ok "after a wait for the plain link's lock the token is checked again: the run that waited is refused (exit 1) with nothing started, the one that held the lock ended ok" || no "late expiry: $(cat "$T/w1.rc" "$T/w2.rc") $(cat "$T/w2.out")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$LOCKF"; signin 259200; BEFORE=$(sum "$SRC")

# --- however a run ends, the copy is gone ---------------------------------------------------------------------------------------------------
# a runner that fails in a way nothing planned for, after the member started: the member is stopped and the copy removed (clear_home, the end of
# run_started), the exception is not swallowed
setprov fakeall; echo hold > "$T/mode"; rm -f "$T/hold-ready" "$T/hold-go"; prep crash1; task
got=$(python3 -I - "$T/tool/lib" "$RUN" <<'PY' 2>&1
import json, os, sys
sys.path.insert(0, sys.argv[1])
import local_run as L
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from attempt_fixture import wire
wire(L)
run = os.path.realpath(sys.argv[2])
copy = os.path.join(run, "home/.fk/auth.json")
orig, n, seen = L.write_private, [0], []
original = RuntimeError("injected runner failure")
def wp(path, text):
    n[0] += 1
    if n[0] == 2:
        seen.append(os.path.isfile(copy) and not os.path.islink(copy))   # the copy exists while the member runs
        raise original
    return orig(path, text)
L.write_private = wp
try:
    L.main([run, "--project", "rproj", "--runtime", "fakeall", "--class", "write", "--again"])
    print("NOEXC")
except RuntimeError as e:
    print("RAISED" if e is original else "OTHER")
rec = json.load(open(os.path.join(run, "dispatch.json")))
print("SEEN=%s GONE=%s OUTCOME=%s PRIVATE=%s" % (seen, not os.path.lexists(copy), rec["outcome"], [p["to"] for p in rec["home"]["private"]]))
PY
)
{ grep -q '^RAISED$' <<<"$got" && grep -q "^SEEN=\[True\] GONE=True OUTCOME=refused PRIVATE=\['auth.json'\]$" <<<"$got" && [ "$(sum "$SRC")" = "$BEFORE" ]; } \
  && ok "a crash of the runner after the member started: the member is stopped, the copy is removed, the error is not swallowed (clear_home at the end of run_started)" || no "crash: $got"
kill -TERM -- -"$(cat "$T/member.pid" 2>/dev/null || echo 0)" 2>/dev/null; rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid"
# a signal ends the run as interrupted and the copy is removed
echo hold > "$T/mode"; rm -f "$T/hold-ready" "$T/hold-go"; prep sig1; task; S1=$RUN
( $DA local run "$S1" > "$T/s.out" 2>&1; echo $? > "$T/s.rc" ) &
wait_until '[ -e "$T/hold-ready" ] && [ -f "$S1/home/.fk/auth.json" ]' 30
kill -TERM "$(jq -r .runner "$S1/dispatch.json")"; wait_until '[ -s "$T/s.rc" ]' 30
{ [ "$(cat "$T/s.rc")" = 143 ] && grep -q '^OUTCOME=interrupted' "$T/s.out" && [ ! -e "$S1/home/.fk/auth.json" ] && [ "$(sum "$SRC")" = "$BEFORE" ]; } \
  && ok "SIGTERM to the runner: the member is stopped (interrupted) and the copy is removed" || no "sigterm: rc=$(cat "$T/s.rc") $(cat "$T/s.out") $(ls -lA "$S1/home/.fk")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go"

# SIGKILL: the runner cannot clean up. The copy is residue the lead's verbs name (local list, local verify) and that local run --again replaces and
# local clean removes with the run: the sweep is home_residue of lib/local.sh, which reads home.private of the start record
echo hold > "$T/mode"; rm -f "$T/hold-ready" "$T/hold-go" "$T/member.pid"; prep kill1; task; K1=$RUN; COPY=$K1/home/.fk/auth.json
( $DA local run "$K1" > "$T/k.out" 2>&1; echo $? > "$T/k.rc" ) &
wait_until '[ -e "$T/hold-ready" ] && [ -s "$T/member.pid" ] && [ -f "$COPY" ]' 30
kill -KILL "$(jq -r .runner "$K1/dispatch.json")"; wait_until '[ -s "$T/k.rc" ]' 30
kill -TERM -- -"$(cat "$T/member.pid")"; wait_until '! kill -0 "$(cat "$T/member.pid")" 2>/dev/null' 10
{ [ -f "$COPY" ] && [ ! -L "$COPY" ] && [ "$(jq -r .outcome "$K1/dispatch.json")" = running ] && [ "$(sum "$SRC")" = "$BEFORE" ]; } \
  && ok "SIGKILL: the runner could not remove the copy; the start record stays (running) and names it (home.private)" || no "sigkill state: $(ls -lA "$K1/home/.fk") $(jq -c .home "$K1/dispatch.json")"
out=$($DA local list 2>&1)
grep -qF "  residue: $COPY (a private copy of a sign-in that a start of qargi local run left: its runner did not end)" <<<"$out" \
  && ok "local list names the copy a killed runner left" || no "list residue: $out"
out=$($DA local verify "$K1" 2>&1)
grep -qF "the run home of $K1 holds what a run left there: $COPY (a private copy of a sign-in that a start of qargi local run left: its runner did not end)" <<<"$out" \
  && ok "local verify names it too" || no "verify residue: $out"
echo quick > "$T/mode"; : > "$T/hold-go"
out=$($DA local run "$K1" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$COPY" ] && grep -q '^PLACEHOLDER=yes$' "$K1/out/transcript" && grep -q '^FILEMODE=600$' "$K1/out/transcript" && [ -z "$($DA local list 2>&1 | grep -F "residue: $COPY")" ]; } \
  && ok "local run --again replaces the copy a killed runner left (a new file, mode 600), ends clean, and the list names no residue" || no "again: rc=$rc $out"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid"; echo hold > "$T/mode"
prep kill2; task; K2=$RUN; COPY=$K2/home/.fk/auth.json
( $DA local run "$K2" > "$T/k.out" 2>&1; echo $? > "$T/k.rc" ) &
wait_until '[ -e "$T/hold-ready" ] && [ -s "$T/member.pid" ] && [ -f "$COPY" ]' 30
rm -f "$T/k.rc"; kill -KILL "$(jq -r .runner "$K2/dispatch.json")"; wait_until '[ -s "$T/k.rc" ]' 30
kill -TERM -- -"$(cat "$T/member.pid")"; wait_until '! kill -0 "$(cat "$T/member.pid")" 2>/dev/null' 10
out=$($DA local clean "$K2" --discard 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$K2" ] && grep -qF "removed with the run what its run home held: $COPY (a private copy of a sign-in that a start" <<<"$out" && [ "$(sum "$SRC")" = "$BEFORE" ]; } \
  && ok "local clean --discard removes a SIGKILLed run with its copy, says so, and the source is untouched" || no "clean: rc=$rc $out"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid"

# --- the shipped runtime that declares it ------------------------------------------------------------------------------------------------------
{ [ "$(jq -c '.dispatch.home.link[0].private' lib/providers/codex.json)" = '{"set":{"tokens.refresh_token":"qargi-no-refresh"},"expiry":{"path":"tokens.access_token","encoding":"jwt-exp"}}' ] \
  && [ "$(jq -r '.dispatch.home.link[0].from' lib/providers/codex.json)" = \~/.codex-members/auth.json ] && [ "$(jq '.dispatch.home.link | length' lib/providers/codex.json)" = 1 ]; } \
  && ok "codex declares its members' sign-in as a private copy with the placeholder and the access token's expiry (the default margin)" || no "codex descriptor: $(jq -c .dispatch.home lib/providers/codex.json)"
rm -rf "$T"
exit $fail
