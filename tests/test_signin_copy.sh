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
if [ "\${1:-}" = --refresh ]; then   # the refresh command (private.refresh): it says what it finds, never a token, then does what $T/refmode says to the source
  { echo "ARGS=\$*"; echo "HOMEVAR=\$FAKESI_HOME"; echo "STDIN=\$(cat)"; echo "LEAK=\${FAKESI_LEAK:-no}"; echo "CWD=\$PWD"
    echo "LOCKED=\$(flock -n "$MEM/.qargi-run.lock" true && echo no || echo yes)"
    echo "MEMBERENV=\$([ -n "\${QARGI_MEMBER_RUN:-}" ] && echo yes || echo no)"; echo "PID=\$\$"; } >> "$T/refresh.log"
  echo x >> "$T/refresh.count"
  newtok() { python3 -c 'import base64, json, sys, time
def b(o): return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
print("%s.%s.dummy-signature-new" % (b({"alg": "none"}), b({"exp": int(time.time()) + int(sys.argv[1]), "sub": "dummy"})))' "\$1"; }
  put() { n=\$(newtok "\$1"); jq --arg a "\$n" '.tokens.access_token = \$a' "\$a" > "$T/refresh.tmp" && cat "$T/refresh.tmp" > "\$a"; printf '%s' "\$n" > "$T/want-access"; }
  case \$(cat "$T/refmode") in
    ok)      if [ -e "$T/refresh-gate" ]; then end=\$((SECONDS + 60)); until [ -e "$T/refresh-go" ] || [ "\$SECONDS" -ge "\$end" ]; do sleep 0.1; done; fi
             put 864000;;
    short)   put 300;;
    fail)    exit 3;;
    nochange) exit 0;;
    hang)    sleep 60;;
  esac
  exit 0
fi
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
  move)    mv "\$a" "\$FAKESI_HOME/renamed.bak";;
  holdmove) mv "\$a" "\$FAKESI_HOME/renamed.bak"; echo \$\$ > "$T/member.pid"; : > "$T/hold-ready"
           while [ ! -e "$T/hold-go" ]; do sleep 0.1; done;;
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
# private.refresh: the command that makes the runtime refresh the real sign-in (here the fake itself, told by --refresh); {scratch} and {model} are filled by qargi
refr() { # TIMEOUT-SECONDS -> the private object with a refresh
  jq -n --argjson p "$PRIV" --argjson t "$1" '$p + {refresh: {argv: ["fakesi", "--refresh", "{scratch}", "{model}"], prompt: "ok", min_remaining_seconds: 0, timeout_seconds: $t}}'; }
def fakeref "$(jq -n --argjson p "$(refr 20)" '[{from:"~/.fakesi-members/auth.json",to:"auth.json",private:$p}]')"
def fakereft "$(jq -n --argjson p "$(refr 2)" '[{from:"~/.fakesi-members/auth.json",to:"auth.json",private:$p}]')"
def fakemixr "$(jq -n --argjson p "$(refr 20)" '[{from:"~/.fakesi-members/auth.json",to:"auth.json",private:$p},{from:"~/.fakesi-members/settings.json",to:"settings.json"}]')"
setprov() { proj rproj "$T/r" "$1"; }
LOCKF=$MEM/.qargi-run.lock; LDECL=\~/.fakesi-members/.qargi-run.lock; DECL=\~/.fakesi-members/auth.json   # the source as the definition declares it: what a message names
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
want='[{"expires_in_seconds":0,"refreshed":false,"set":["tokens.refresh_token"],"sha256":"x","to":"auth.json"}]'
got=$(jq -c '.home.private | map(.expires_in_seconds |= (if . > 259000 and . <= 259200 then 0 else . end) | .sha256 |= (if test("^[0-9a-f]{64}$") then "x" else . end))' "$R1/dispatch.json")
{ [ "$got" = "$want" ] && [ "$(jq -c '.home | {links, private: (.private | length)}' "$R1/dispatch.json")" = '{"links":[],"private":1}' ]; } \
  && ok "dispatch.json records home.private: the name, the paths set, the seconds left at the start, whether the run refreshed the real sign-in (no), the sha256 of the copy as written, and no link" || no "record: $got $(jq -c .home "$R1/dispatch.json")"
rm -f "$T/mode" "$T"/in.*

# --- what the member does to its copy stays in the run home and is removed: nothing is written to the source ------------------------------
for mode in rewrite replace delete move; do
  echo "$mode" > "$T/mode"; prep "cp-$mode"; task
  out=$($DA local run "$RUN" 2>&1); rc=$?
  case $mode in
    delete) note='the private copy auth.json was not found at its name in the run home at the end of the run (removed or moved, by the runtime or the member); your sign-in is untouched';;
    move) note='the private copy auth.json was not found at its name in the run home at the end of the run (removed or moved, by the runtime or the member); a file with its content, '"$RUN/home/.fk/renamed.bak"', was found and removed; your sign-in is untouched';;
    *) note='the private copy auth.json was changed during the run';;
  esac
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
stop_member() { # stop the process group of the fake member the pid file names: only a non-empty file that names a live process is acted on, never a guess (kill -- -0 is the caller's own group)
  local p; p=$(cat "$T/member.pid" 2>/dev/null) || return 0
  [[ $p =~ ^[1-9][0-9]*$ ]] && kill -0 "$p" 2>/dev/null && kill -TERM -- "-$p" 2>/dev/null
  return 0; }
setprov fakeall; echo hold > "$T/mode"; rm -f "$T/hold-ready" "$T/hold-go" "$T/member.pid"; prep crash1; task
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
stop_member; rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid"
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
wait_until '[ -e "$T/hold-ready" ] && [ -s "$T/member.pid" ] && [ -f "$COPY" ] && [ -n "$(jq -r ".member // empty" "$K1/dispatch.json")" ]' 30   # the record names the member: the runner has recorded it
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
wait_until '[ -e "$T/hold-ready" ] && [ -s "$T/member.pid" ] && [ -f "$COPY" ] && [ -n "$(jq -r ".member // empty" "$K2/dispatch.json")" ]' 30
rm -f "$T/k.rc"; kill -KILL "$(jq -r .runner "$K2/dispatch.json")"; wait_until '[ -s "$T/k.rc" ]' 30
kill -TERM -- -"$(cat "$T/member.pid")"; wait_until '! kill -0 "$(cat "$T/member.pid")" 2>/dev/null' 10
out=$($DA local clean "$K2" --discard 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$K2" ] && grep -qF "removed with the run what its run home held: $COPY (a private copy of a sign-in that a start" <<<"$out" && [ "$(sum "$SRC")" = "$BEFORE" ]; } \
  && ok "local clean --discard removes a SIGKILLed run with its copy, says so, and the source is untouched" || no "clean: rc=$rc $out"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid"
# a member that renamed its copy inside the run home and whose runner was killed: local list finds the file by the sha256 the start record names
echo holdmove > "$T/mode"; prep kill3; task; K3=$RUN; MOVED=$K3/home/.fk/renamed.bak
( $DA local run "$K3" > "$T/k.out" 2>&1; echo $? > "$T/k.rc" ) &
wait_until '[ -e "$T/hold-ready" ] && [ -s "$T/member.pid" ] && [ -f "$MOVED" ] && [ -n "$(jq -r ".member // empty" "$K3/dispatch.json")" ]' 30
rm -f "$T/k.rc"; kill -KILL "$(jq -r .runner "$K3/dispatch.json")"; wait_until '[ -s "$T/k.rc" ]' 30
kill -TERM -- -"$(cat "$T/member.pid")"; wait_until '! kill -0 "$(cat "$T/member.pid")" 2>/dev/null' 10
out=$($DA local list 2>&1)
{ grep -qF "  residue: $MOVED (a private copy of a sign-in, moved from auth.json inside the run home, that a start of qargi local run left: its runner did not end)" <<<"$out" \
  && ! grep -qF "residue: $K3/home/.fk/auth.json" <<<"$out" && notokens "$K3/dispatch.json"; } \
  && ok "a copy the member renamed inside the run home, runner killed: local list finds the file by the sha256 of the start record (and the record holds no token)" || no "moved residue: $out $(jq -c .home "$K3/dispatch.json")"
out=$($DA local clean "$K3" --discard 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$K3" ]; } && ok "and local clean --discard removes that run with the moved copy" || no "clean moved: rc=$rc $out"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid"

# --- the automatic refresh of the real sign-in (private.refresh) ---------------------------------------------------------------------------------
export FAKESI_LEAK=yes                      # a variable of the caller that the refresh command must not see (dispatch.env_pass names none)
setprov fakeref; echo quick > "$T/mode"; echo ok > "$T/refmode"; rm -f "$T/refresh.log" "$T/refresh.count" "$T/refresh-gate" "$T/refresh-go"; rm -f "$LOCKF"
signin 259200; prep rn1; task
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$T/refresh.count" ] && [ ! -e "$LOCKF" ] && ! grep -q 'refreshing the sign-in' <<<"$out" && [ "$(jq -r '.home.private[0].refreshed' "$RUN/dispatch.json")" = false ]; } \
  && ok "a token that lasts the run is not refreshed: the command is not run, no lock file is made, the record says refreshed false" || no "no refresh needed: rc=$rc $out"
signin 500; BEFORE=$(sum "$SRC"); OLDACC=$ACC; prep rn2; R=$RUN; task
out=$($DA local run "$R" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -qF 'HOME_REFRESH=auth.json: when the sign-in would not last the run' <<<"$out" && grep -qF '["fakesi","--refresh","{scratch}","fake-m-1"]' <<<"$out" \
  && grep -qF 'a dry run refreshes nothing' <<<"$out" && [ ! -e "$T/refresh.count" ] && [ ! -e "$LOCKF" ] && [ "$(sum "$SRC")" = "$BEFORE" ] && notext "$out"; } \
  && ok "a dry run prints what it would do (HOME_REFRESH=) and refreshes nothing: no command, no lock file, the source as it was" || no "dry refresh: rc=$rc $out"
out=$($DA local prepare --repo "$T/r" --base main --slug rnprep --scratch "$T" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$T/refresh.count" ] && [ "$(sum "$SRC")" = "$BEFORE" ]; } && ok "local prepare never refreshes" || no "prepare refresh: rc=$rc $out"
out=$($DA local run "$R" 2>&1); rc=$?
NEWACC=$(jq -r .tokens.access_token "$SRC")
{ [ "$rc" = 0 ] && grep -qE '^qargi: refreshing the sign-in of fakeref \(expires in [0-9]+ s\)$' <<<"$out" && [ "$(wc -l < "$T/refresh.count")" = 1 ] \
  && [ "$NEWACC" != "$OLDACC" ] && [ "$(sum "$SRC")" != "$BEFORE" ] && [ "$(stat -c %a "$SRC")" = 600 ]; } \
  && ok "a source about to expire is refreshed once by the declared command, and the run goes on" || no "refresh: rc=$rc $out $(cat "$T/refresh.log" 2>&1)"
{ grep -qE "^ARGS=--refresh $T/.*/work fake-m-1\$" "$T/refresh.log" && grep -qxF "HOMEVAR=$MEM" "$T/refresh.log" && grep -qx 'STDIN=ok' "$T/refresh.log" && grep -qx 'LEAK=no' "$T/refresh.log" \
  && grep -qE "^CWD=$T/.*/work\$" "$T/refresh.log" && grep -qx 'LOCKED=yes' "$T/refresh.log" && grep -qx 'MEMBERENV=yes' "$T/refresh.log"; } \
  && ok "the command ran with the default model and a scratch directory, the variable of the home naming the source's directory, the prompt on its input, a scrubbed environment, and the source's lock held" || no "refresh facts: $(cat "$T/refresh.log")"
PID=$(sed -n 's/^PID=//p' "$T/refresh.log")
{ [ ! -d "$(sed -n 's/^CWD=//p' "$T/refresh.log")" ] && ! kill -0 "$PID" 2>/dev/null && flock -n "$LOCKF" true; } \
  && ok "the scratch directory is gone, the command has ended and the lock is free again" || no "refresh cleanup: $(ls -lA "$MEM")"
{ grep -q '^ACCESS=same$' "$R/out/transcript" && grep -q '^PLACEHOLDER=yes$' "$R/out/transcript" && [ "$(jq -r '.home.private[0].refreshed' "$R/dispatch.json")" = true ] \
  && [ "$(jq -c '.home.private[0] | keys' "$R/dispatch.json")" = '["expires_in_seconds","refreshed","set","sha256","to"]' ] && [ "$(jq -r .outcome "$R/dispatch.json")" = ok ]; } \
  && ok "the member got a copy of the refreshed token; dispatch.json says refreshed true and holds nothing else of it" || no "refresh record: $(cat "$R/out/transcript") $(jq -c .home "$R/dispatch.json")"
{ ! grep -qF -e "$OLDACC" -e "$NEWACC" -e "$IDT" -e "$REFR" -e dummy-signature "$R/dispatch.json" "$R/out/transcript" "$R/out/transcript.err" && ! grep -qF -e "$OLDACC" -e "$NEWACC" -e "$IDT" -e "$REFR" -e dummy-signature <<<"$out"; } \
  && ok "no token text is in dispatch.json, the transcripts or the output of a run that refreshed" || no "refresh leaked: $out"

# a command that fails, one that changes nothing, one that leaves a token that still does not last, and one that does not end: refused, no second try
refuse_case() { # LABEL MODE DEF TEXT: signin 500, the refresh in MODE is refused (exit 1, cause refresh-failed), nothing is recorded, the command ran once
  signin 500; echo "$2" > "$T/refmode"; rm -f "$T/refresh.count" "$T/refresh.log"; setprov "$3"; prep "rf-$2"; task; B=$(sum "$SRC")
  out=$($DA local run "$RUN" 2>&1); rc=$?
  { [ "$rc" = 1 ] && grep -qF '[runtime-signin-expiring]' <<<"$out" && grep -qF '(refresh-failed)' <<<"$out" && grep -qF "$4" <<<"$out" && grep -qF 'FAKESI_HOME=~/.fakesi-members fakesi login' <<<"$out" \
    && [ "$(wc -l < "$T/refresh.count")" = 1 ] && [ ! -e "$RUN/dispatch.json" ] && [ ! -e "$RUN/home/.fk" ] && notext "$out"; } \
    && ok "$1: refused (runtime-signin-expiring, refresh-failed), the command ran once, nothing was made or recorded" || no "$1: rc=$rc $out $(cat "$T/refresh.count" 2>&1)"; }
refuse_case "a failing refresh command" fail fakeref 'the command exited with status 3'
[ "$(sum "$SRC")" = "$B" ] && ok "and the source is unchanged" || no "failing refresh changed the source"
refuse_case "a command that changes nothing" nochange fakeref 'the command left the sign-in file as it was'
refuse_case "a command that leaves a token that is too short" short fakeref 'the token it left ends in'
PID=$(sed -n 's/^PID=//p' "$T/refresh.log")
refuse_case "a command that does not end" hang fakereft 'the command did not end in 2 s'
PID=$(sed -n 's/^PID=//p' "$T/refresh.log")
wait_until '! kill -0 "$PID" 2>/dev/null' 10 && ok "the command that did not end was stopped with its group" || no "hang left $PID running"
[ "$(sum "$SRC")" = "$B" ] && ok "a hung refresh leaves the source as it was" || no "hang changed the source"

# two runs started together: the second waits for the lock, finds the source refreshed and does not run the command again; both finish
setprov fakeref; echo ok > "$T/refmode"; echo quick > "$T/mode"; signin 500; rm -f "$T/refresh.count" "$T/refresh.log" "$T/refresh-go" "$LOCKF"; : > "$T/refresh-gate"
prep rt1; R1=$RUN; task; prep rt2; R2=$RUN; task
( $DA local run "$R1" > "$T/t1.out" 2>&1; echo $? > "$T/t1.rc" ) &
wait_until '[ -s "$T/refresh.log" ]' 30
( $DA local run "$R2" > "$T/t2.out" 2>&1; echo $? > "$T/t2.rc" ) &
wait_until 'grep -q "waiting for it to end" "$T/t2.out"' 30
: > "$T/refresh-go"; wait_until '[ -s "$T/t1.rc" ] && [ -s "$T/t2.rc" ]' 60
{ [ "$(cat "$T/t1.rc")" = 0 ] && [ "$(cat "$T/t2.rc")" = 0 ] && [ "$(wc -l < "$T/refresh.count")" = 1 ] && [ "$(cat "$T"/t?.out | grep -c 'refreshing the sign-in')" = 1 ] \
  && grep -q '^ACCESS=same$' "$R1/out/transcript" && grep -q '^ACCESS=same$' "$R2/out/transcript" \
  && [ "$(jq -r '.home.private[0].refreshed' "$R1/dispatch.json")" = true ] && [ "$(jq -r '.home.private[0].refreshed' "$R2/dispatch.json")" = false ]; } \
  && ok "two runs started together refresh once and both finish: the one that waited read the source again, found it refreshed and went on" || no "two runs: $(cat "$T"/t?.rc) $(cat "$T/t1.out" "$T/t2.out") $(cat "$T/refresh.count")"
rm -f "$T/refresh-gate" "$T/refresh-go" "$T/mode"

# a runner killed with SIGKILL while its refresh command runs: the refresh got the lock descriptor, so the lane stays held until the command ends, and the lane record names it
setprov fakeref; echo ok > "$T/refmode"; echo quick > "$T/mode"; signin 500; rm -f "$T/refresh.count" "$T/refresh.log" "$T/refresh-go" "$LOCKF"; : > "$T/refresh-gate"
KREC=$MEM/.qargi-lane.json; prep rk1; RK1=$RUN; task
( $DA local run "$RK1" > "$T/k1.out" 2>&1; echo $? > "$T/k1.rc" ) &
wait_until 'grep -q "^PID=" "$T/refresh.log" 2>/dev/null && [ "$(jq -r .member.pid "$KREC" 2>/dev/null)" = "$(sed -n "s/^PID=//p" "$T/refresh.log")" ]' 30
KPID=$(sed -n 's/^PID=//p' "$T/refresh.log"); KRUN=$(jq -r .runner.pid "$KREC")
kill -KILL "$KRUN"; wait_until '[ -s "$T/k1.rc" ]' 30
out=$($DA local list --lanes 2>&1)
{ ! kill -0 "$KRUN" 2>/dev/null && kill -0 "$KPID" 2>/dev/null && ! flock -n "$LOCKF" true && [ "$(jq -r .kind "$KREC")" = refresh ] \
  && grep -qE '^fakeref +~/.fakesi-members/.qargi-run.lock +held, member alive, runner gone +lead .* \(refresh, ' <<<"$out"; } \
  && ok "SIGKILL of the runner during a refresh: the lane stays held while the refresh command lives (it holds the lock descriptor), and the lane record and local list --lanes name it" || no "lane after SIGKILL in a refresh: runner $KRUN refresh $KPID $(cat "$KREC" 2>&1) $out"
: > "$T/refresh-go"; wait_until '! kill -0 "$KPID" 2>/dev/null && flock -n "$LOCKF" true' 30 && ok "when the refresh command ends the lane is free" || no "lane after the refresh: $(ls -lA "$MEM")"
rm -f "$T/refresh-gate" "$T/refresh-go" "$T/mode" "$KREC" "$T/k1.rc"
# a refresh command that leaves a process of its group that cannot be stopped (the stop is faked to report it): the refresh failed, its result is not read, and the lane stays held (the
# descendant has the descriptor) with its record
got=$(python3 -I - "$T/tool/lib" "$T" <<'PY' 2>&1
import fcntl, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
import local_run as L
import lane as LN
d = tempfile.mkdtemp(dir=sys.argv[2])
src, pidf = os.path.join(d, "auth.json"), os.path.join(d, "descendant.pid")
open(src, "w").write("{}")
spec = {"argv": ["sh", "-c", 'sleep 60 & echo $! >> "$1"; exit 0', "sh", pidf], "prompt": "ok", "timeout_seconds": 20}
home = {"private": {"auth.json": {"refresh": spec}}, "from": {"auth.json": "~/.x/auth.json"}, "refresh_tried": set(), "refreshed": {}, "locked": set(), "runtime": "fakeref", "env": "X_HOME", "wait": None}
plan = {"env": {}, "env_pass": [], "exe": "sh", "project": "p"}
reads = []
L.models_values = lambda *a: ["m"]
L.refresh_argv = lambda home, plan, spec, exe=None: list(spec["argv"])
L.load_copy = lambda home, to, src: (reads.append(1), (b"copy", 10))[1]
L.signin_refusal = lambda home, to, left, plan, cause=None: RuntimeError("refused:%s" % cause)
L.kill_group = lambda proc, grace=0: 1
try:
    L.refresh_signin(home, "auth.json", src, plan, L.Signals(), b"copy", 10, 1000)
    print("NOEXC")
except RuntimeError as e:
    print(e)
pid = int(open(pidf).read())
fd = os.open(os.path.join(d, L.LOCK_NAME), os.O_RDWR)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("LOCK-FREE")
except BlockingIOError:
    print("LOCK-HELD")
rec = LN.read_record(d)
print("RECORD member=%s reads=%d" % (bool(rec and rec["member"]), len(reads)))
os.killpg(os.getpgid(pid), 9)
PY
)
{ grep -qx 'refused:refresh-failed' <<<"$got" && grep -qx 'LOCK-HELD' <<<"$got" && grep -qx 'RECORD member=True reads=1' <<<"$got" && grep -qF 'could not be stopped' <<<"$got"; } \
  && ok "a refresh command that leaves a process that cannot be stopped is a refresh-failed: the result is not read, and the lane stays held with its record while the process lives" || no "refresh survivors: $got"

# --wait bounds the wait for the lock of a refresh too, while the run is not recorded: lane-busy, with no record and no refresh
setprov fakeref; echo ok > "$T/refmode"; signin 500; rm -f "$T/refresh.count" "$T/refresh.log" "$T/lk-held" "$T/lk-release" "$LOCKF"; prep rw1; task; W1=$RUN
spawn_bg bash -c 'flock 9; : > "$1/lk-held"; for _ in $(seq 600); do [ -e "$1/lk-release" ] && break; sleep 0.1; done' _ "$T" 9> "$LOCKF"; LKP=$SPAWNED_PID
wait_until '[ -e "$T/lk-held" ]' 30
out=$($DA local run "$W1" --wait 1 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF '[lane-busy]' <<<"$out" && grep -qF 'the wait of 1 s ended' <<<"$out" && grep -qF 'no attempt is recorded' <<<"$out" && [ ! -e "$W1/dispatch.json" ] && [ ! -e "$T/refresh.count" ]; } \
  && ok "--wait bounds the wait for the lock of a refresh: refused as lane-busy before anything is recorded, and the refresh does not run" || no "wait for a refresh lock: rc=$rc $out"
: > "$T/lk-release"; wait "$LKP" 2>/dev/null; rm -f "$T/lk-held" "$T/lk-release" "$LOCKF"
# once the run is recorded (home["recorded"]) the wait for the lock of a refresh has no bound, so lane-busy is never raised for a run that has a record (a fake clock)
got=$(python3 -I - "$T/tool/lib" "$T" <<'PY' 2>&1
import fcntl, os, sys, tempfile, time, types
sys.path.insert(0, sys.argv[1])
import local_run as L
path = os.path.join(tempfile.mkdtemp(dir=sys.argv[2]), ".qargi-run.lock")
def take(**more):
    holder = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    clock = [0.0]
    def sleep(seconds):
        clock[0] += seconds
        if clock[0] >= 5.0:                                # the holder lets go five seconds in
            os.close(holder)
    L.time = types.SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep, time=time.time)
    home = dict({"declared": [], "runtime": "fakeref", "wait": 0}, **more)
    try:
        os.close(L.lock_one(path, home, "fakeref", L.Signals(), "refresh"))
        return "took it at %.2f" % clock[0]
    except L.Stop as e:
        return "refused code=%d" % e.code
    finally:
        try:
            os.close(holder)
        except OSError:
            pass
print("before the record:", take())
print("after the record:", take(recorded=True))
PY
)
{ grep -qx 'before the record: refused code=1' <<<"$got" && grep -qx 'after the record: took it at 5.00' <<<"$got"; } \
  && ok "a refresh that is needed only once the run is recorded waits for its lock without a bound (--wait 0 does not refuse it), so lane-busy never says nothing was recorded of a recorded run" || no "recorded refresh lock: $got"

# a home with a plain link beside the private one holds the lock for the whole run: a refresh that is needed after the wait takes no second lock (no deadlock) and goes on
setprov fakemixr; echo hold > "$T/mode"; echo ok > "$T/refmode"; signin 259200; rm -f "$T/hold-ready" "$T/hold-go" "$T/refresh.count" "$T/refresh.log" "$LOCKF"
prep mr1; M1=$RUN; task; prep mr2; M2=$RUN; task
( $DA local run "$M1" > "$T/r1.out" 2>&1; echo $? > "$T/r1.rc" ) &
wait_until '[ -e "$T/hold-ready" ]' 30
( $DA local run "$M2" > "$T/r2.out" 2>&1; echo $? > "$T/r2.rc" ) &
wait_until 'grep -q "waiting for it to end" "$T/r2.out"' 30
signin 400
: > "$T/hold-go"; wait_until '[ -s "$T/r1.rc" ] && [ -s "$T/r2.rc" ]' 60
{ [ "$(cat "$T/r1.rc")" = 0 ] && [ "$(cat "$T/r2.rc")" = 0 ] && [ "$(wc -l < "$T/refresh.count")" = 1 ] && grep -qE '^qargi: refreshing the sign-in of fakemixr' "$T/r2.out" \
  && [ "$(jq -r '.home.private[0].refreshed' "$M2/dispatch.json")" = true ] && grep -q '^ACCESS=same$' "$M2/out/transcript"; } \
  && ok "a refresh needed once the lock of a plain link is held runs under that lock, takes no second one, and the run goes on" || no "refresh under held lock: $(cat "$T/r1.rc" "$T/r2.rc") $(cat "$T/r2.out")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$LOCKF" "$T/refmode" "$T/refresh.log" "$T/refresh.count"; unset FAKESI_LEAK; signin 259200; setprov fakeall

# --- the lane lock of a plain link: it outlives a killed runner, and a lock file replaced under a waiting run is noticed ------------------------------------
# SIGKILL of the runner: the member got the lock descriptor, so the lane stays held until the member's group ends, and a second run waits
setprov fakeplain; echo hold > "$T/mode"; rm -f "$T/hold-ready" "$T/hold-go" "$T/member.pid" "$LOCKF"
prep ln1; task; N1=$RUN; prep ln2; task; N2=$RUN
( $DA local run "$N1" > "$T/n1.out" 2>&1; echo $? > "$T/n1.rc" ) &
wait_until '[ -e "$T/hold-ready" ] && [ -s "$T/member.pid" ] && [ -n "$(jq -r ".member // empty" "$N1/dispatch.json")" ]' 30
NR=$(jq -r .runner "$N1/dispatch.json"); NM=$(cat "$T/member.pid")
kill -KILL "$NR"; wait_until '[ -s "$T/n1.rc" ]' 30
{ ! kill -0 "$NR" 2>/dev/null && kill -0 "$NM" 2>/dev/null && ! flock -n "$LOCKF" true; } \
  && ok "SIGKILL of the runner: the lane stays held while the member lives (the member holds the lock descriptor)" || no "lane after SIGKILL: runner $NR member $NM $(ls -lA "$MEM")"
( $DA local run "$N2" > "$T/n2.out" 2>&1; echo $? > "$T/n2.rc" ) &
wait_until 'grep -q "waiting for it to end" "$T/n2.out"' 30
{ [ ! -s "$T/n2.rc" ] && [ ! -e "$N2/out/transcript" ] && [ ! -e "$N2/home/.fk/auth.json" ]; } \
  && ok "a second run of another run id waits for the member of the killed runner, and starts nothing" || no "second run beside a live member: $(cat "$T/n2.out")"
: > "$T/hold-go"; wait_until '[ -s "$T/n2.rc" ]' 60
{ [ "$(cat "$T/n2.rc")" = 0 ] && grep -qF 'is free; the run starts' "$T/n2.out" && flock -n "$LOCKF" true; } \
  && ok "when the member ends the lane is free: the second run starts, ends ok, and the lock is free again" || no "after the member: rc=$(cat "$T/n2.rc") $(cat "$T/n2.out")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid" "$T/n1.rc" "$T/n2.rc" "$LOCKF"
# a lock file removed and made anew while a run waits on the old one: when the old one is let go the run notices that it holds a file that is no longer the lock, and takes the new one
echo hold > "$T/mode"; prep rp1; task; Q1=$RUN; prep rp2; task; Q2=$RUN
( $DA local run "$Q1" > "$T/q1.out" 2>&1; echo $? > "$T/q1.rc" ) &
wait_until '[ -e "$T/hold-ready" ]' 30
( $DA local run "$Q2" > "$T/q2.out" 2>&1; echo $? > "$T/q2.rc" ) &
wait_until 'grep -q "waiting for it to end" "$T/q2.out"' 30
rm -f "$LOCKF"; : > "$LOCKF"; chmod 600 "$LOCKF"
: > "$T/hold-go"; wait_until '[ -s "$T/q1.rc" ] && [ -s "$T/q2.rc" ]' 60
{ [ "$(cat "$T/q1.rc")" = 0 ] && [ "$(cat "$T/q2.rc")" = 0 ] && grep -qxF 'qargi: note: the lock file ~/.fakesi-members/.qargi-run.lock was replaced or removed while this run took it; taking the file that is there now' "$T/q2.out" \
  && grep -qF 'is free; the run starts' "$T/q2.out" && [ -s "$Q2/out/transcript" ] && flock -n "$LOCKF" true; } \
  && ok "a lock file replaced under a waiting run is noticed (the descriptor is not the file at the path): the run retries onto the new file, then runs" || no "replaced lock file: $(cat "$T/q1.rc" "$T/q2.rc") $(cat "$T/q2.out")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$LOCKF"
# a lock file replaced while a run HOLDS it is a new file nobody holds: a run that starts then gets its flock, but the lane record beside the lock names the live holder, so it waits (and --wait refuses it
# as lane-busy) and never runs beside it
echo hold > "$T/mode"; prep rh1; task; H1=$RUN; prep rh2; task; H2=$RUN; prep rh3; task; H3=$RUN
( $DA local run "$H1" > "$T/h1.out" 2>&1; echo $? > "$T/h1.rc" ) &
wait_until '[ -e "$T/hold-ready" ]' 30
rm -f "$LOCKF"; : > "$LOCKF"; chmod 600 "$LOCKF"
out=$($DA local run "$H2" --wait 2 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF '[lane-busy]' <<<"$out" && grep -qF 'is held by lead ' <<<"$out" && [ ! -e "$H2/dispatch.json" ] && [ ! -e "$H2/out/transcript" ] && flock -n "$LOCKF" true; } \
  && ok "a lock file replaced while a run holds it: a second run with --wait is refused (lane-busy), not started beside the holder, and holds nothing" || no "replaced under the holder, --wait: rc=$rc $out"
( $DA local run "$H3" > "$T/h3.out" 2>&1; echo $? > "$T/h3.rc" ) &
wait_until 'grep -q "waiting for it to end" "$T/h3.out"' 30
{ [ ! -s "$T/h3.rc" ] && [ ! -e "$H3/out/transcript" ] && [ ! -s "$T/h1.rc" ]; } \
  && ok "and a run without --wait waits for the holder of the replaced file, and starts nothing" || no "replaced under the holder, wait: $(cat "$T/h3.out")"
: > "$T/hold-go"; wait_until '[ -s "$T/h1.rc" ] && [ -s "$T/h3.rc" ]' 60
{ [ "$(cat "$T/h1.rc")" = 0 ] && [ "$(cat "$T/h3.rc")" = 0 ] && grep -qF 'is free; the run starts' "$T/h3.out" && [ -s "$H3/out/transcript" ] && flock -n "$LOCKF" true; } \
  && ok "when the holder ends the waiting run starts and ends ok" || no "after the replaced file's holder: $(cat "$T/h1.rc" "$T/h3.rc") $(cat "$T/h3.out")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$LOCKF" "$T"/h?.rc
# the retries are bounded: a file that is replaced every time refuses the run (exit 2) and holds nothing
got=$(python3 -I - "$T/tool/lib" "$MEM" <<'PY' 2>&1
import os, sys
sys.path.insert(0, sys.argv[1])
import local_run as L
home = {"declared": [], "runtime": "fakeplain"}
path = os.path.join(sys.argv[2], ".qargi-run.lock")
n = [0]
L.same_file = lambda fd, p: (n.__setitem__(0, n[0] + 1), False)[1]
try:
    L.lock_one(path, home, "fakeplain", L.Signals())
    print("NOEXC")
except L.Stop as e:
    print("STOP code=%d tries=%d %s" % (e.code, n[0], "replaced" in str(e)))
PY
)
{ grep -q '^STOP code=2 tries=6 True$' <<<"$got" && [ "$(grep -c 'was replaced or removed' <<<"$got")" = 6 ] && flock -n "$LOCKF" true; } \
  && ok "a lock file that is replaced every time is tried six times, then the run is refused (exit 2), and no descriptor is left holding the lock" || no "replace bound: $got"
rm -f "$LOCKF"
# a bounded wait is counted once: a file replaced one second into a wait of two seconds does not start the two seconds again (a fake clock, advanced by the polling)
got=$(python3 -I - "$T/tool/lib" "$T" <<'PY' 2>&1
import fcntl, os, sys, tempfile, time, types
sys.path.insert(0, sys.argv[1])
import local_run as L
path = os.path.join(tempfile.mkdtemp(dir=sys.argv[2]), ".qargi-run.lock")
first = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(first, fcntl.LOCK_EX)
clock, second = [0.0], []
def sleep(seconds):
    clock[0] += seconds
    if clock[0] >= 1.0 and not second:                 # the file is replaced and the first holder lets go; another run holds the new file
        os.unlink(path)
        second.append(os.open(path, os.O_RDWR | os.O_CREAT, 0o600))
        fcntl.flock(second[0], fcntl.LOCK_EX)
        os.close(first)
L.time = types.SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep, time=time.time)
try:
    L.lock_one(path, {"declared": [], "runtime": "fakeplain", "wait": 2}, "fakeplain", L.Signals())
    print("NOEXC")
except L.Stop as e:
    print("STOP code=%d at=%.2f replaced=%s %s" % (e.code, clock[0], bool(second), "the wait of 2 s ended" in str(e)))
PY
)
{ grep -q '^STOP code=1 at=2.00 replaced=True True$' <<<"$got" && grep -c 'was replaced or removed' <<<"$got" | grep -qx 1; } \
  && ok "a bounded wait is counted once: a lock file replaced during it does not start the wait again (refused as lane-busy at the second second)" || no "wait deadline: $got"

# the order of the queue: only the first of the live waiters polls the flock, a run that has not waited yet goes ahead only when nobody waits, and a waiter of a process that is gone does not count
got=$(python3 -I - "$T/tool/lib" "$T" <<'PY' 2>&1
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
import local_run as L
import lane as LN
d = tempfile.mkdtemp(dir=sys.argv[2])
def waiter(pid, since):
    start = LN.token(pid)
    with open(os.path.join(d, "%s%d.%s" % (LN.WAIT, pid, start)), "w") as f:
        json.dump({"pid": pid, "start": start, "lead": "l", "run": "r", "runtime": "x", "since": since}, f)
me, other = os.getpid(), os.getppid()
print("nobody waits:", L.my_turn(d, False, False), L.my_turn(d, True, True))
waiter(other, 1)
print("another waits, not queued:", L.my_turn(d, False, False))
waiter(me, 2)
print("another waits ahead:", L.my_turn(d, True, True))
print("no waiter file made:", L.my_turn(d, True, False))
for n in os.listdir(d):
    os.unlink(os.path.join(d, n))
waiter(me, 1)
waiter(other, 2)
print("first in the queue:", L.my_turn(d, True, True))
open(os.path.join(d, "%s999999.1" % LN.WAIT), "w").write("{}")                  # a process that is not there
print("a ghost ahead is ignored:", L.my_turn(d, True, True))
PY
)
{ grep -qx 'nobody waits: True True' <<<"$got" && grep -qx 'another waits, not queued: False' <<<"$got" && grep -qx 'another waits ahead: False' <<<"$got" && grep -qx 'no waiter file made: True' <<<"$got" \
  && grep -qx 'first in the queue: True' <<<"$got" && grep -qx 'a ghost ahead is ignored: True' <<<"$got"; } \
  && ok "the queue: a run polls the flock only as the first of the live waiters, a newcomer goes ahead only when nobody waits, a ghost waiter is ignored" || no "queue turn: $got"

# --- coordination: the lane record, the holder line and the queue, --wait, local list --lanes ------------------------------------------------------
export QARGI_LEAD=lead-one
LREC=$MEM/.qargi-lane.json
setprov fakeplain; echo hold > "$T/mode"; rm -f "$T/hold-ready" "$T/hold-go" "$T/member.pid" "$LOCKF" "$LREC"
prep ca; task; CA=$RUN; prep cb; task; CB=$RUN; prep cc; task; CC=$RUN; prep cd; task; CD=$RUN; prep ce; task; CE=$RUN
( $DA local run "$CA" > "$T/ca.out" 2>&1; echo $? > "$T/ca.rc" ) &
wait_until '[ -e "$T/hold-ready" ] && [ -s "$T/member.pid" ] && [ -n "$(jq -r ".member // empty" "$CA/dispatch.json")" ]' 30
{ [ "$(stat -c %a "$LREC")" = 600 ] && [ "$(jq -r .lead "$LREC")" = lead-one ] && [ "$(jq -r .run "$LREC")" = ca ] && [ "$(jq -r .kind "$LREC")" = run ] \
  && [ "$(jq -r .runner.pid "$LREC")" = "$(jq -r .runner "$CA/dispatch.json")" ] && [ "$(jq -r .member.pid "$LREC")" = "$(cat "$T/member.pid")" ] \
  && [[ $(jq -r .runner.start "$LREC") =~ ^[0-9]+$ ]] && [[ $(jq -r .member.start "$LREC") =~ ^[0-9]+$ ]] && [ "$(jq -r .started "$LREC")" -gt 1700000000 ] \
  && [ "$(grep -c -e "$HOME" -e "$T" "$LREC")" = 0 ]; } \
  && ok "while a run holds the lane, a record beside the lock (mode 600) names the lead, the run, the runner and the member with their start tokens, and no path" || no "lane record: $(cat "$LREC" 2>&1)"
( $DA local run "$CB" > "$T/cb.out" 2>&1; echo $? > "$T/cb.rc" ) &
wait_until 'grep -q "holder is" "$T/cb.out"' 30
( $DA local run "$CC" > "$T/cc.out" 2>&1; echo $? > "$T/cc.rc" ) &
wait_until 'grep -q "holder is" "$T/cc.out"' 30
{ grep -qE '^qargi: note: holder is lead lead-one, run ca, holding it for [0-9]+s$' "$T/cb.out" && grep -qE '^qargi: note: holder is lead lead-one, run ca, holding it for [0-9]+s; you are number 2 of 2 waiting$' "$T/cc.out"; } \
  && ok "a waiting run prints one line naming the holder (lead, run, how long) and, when several wait, its place among them" || no "holder line: $(cat "$T/cb.out" "$T/cc.out")"
echo x > "$MEM/.qargi-lane-wait.1.1"; true & DEADP=$!; wait "$DEADP"; echo '{"pid": 1, "start": "1", "lead": "ghost-waiter-never-listed", "run": "ghost-waiter-never-listed", "since": 1}' > "$MEM/.qargi-lane-wait.$DEADP.5"
ino=$(stat -c %i "$LOCKF"); before=$(grep -c ":$ino " /proc/locks)
out=$(timeout 20 $DA local list --lanes 2>&1); rc=$?
after=$(grep -c ":$ino " /proc/locks)
{ [ "$rc" = 0 ] && grep -qE '^fakeplain +~/.fakesi-members/.qargi-run.lock +held +lead lead-one run ca \(run, [0-9]+s\)$' <<<"$out" \
  && grep -qE '^  waiting 1: lead lead-one run cb \([0-9]+s\)$' <<<"$out" && grep -qE '^  waiting 2: lead lead-one run cc \([0-9]+s\)$' <<<"$out" && ! grep -q ghost-waiter-never-listed <<<"$out" \
  && [ "$before" = "$after" ] && [ ! -s "$T/ca.rc" ] && [ ! -s "$T/cb.rc" ] && notext "$out"; } \
  && ok "local list --lanes shows the holder and the waiters in the order they began to wait, ignores a waiter of a process that is gone, and does not block or disturb a live run (no lock taken)" || no "lanes: rc=$rc $out before=$before after=$after"
rm -f "$MEM"/.qargi-lane-wait.1.1 "$MEM/.qargi-lane-wait.$DEADP.5"
out=$($DA local list --lanes --scratch "$T" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF -e '--lanes takes no other option' <<<"$out"; } && ok "--lanes takes no other option" || no "lanes with an option: rc=$rc $out"
# --wait: a bounded wait ends in lane-busy before the attempt is recorded; 0 does not wait
out=$($DA local run "$CD" --wait 2 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF '[lane-busy]' <<<"$out" && grep -qF 'is held by lead lead-one run ca (for ' <<<"$out" && grep -qF 'the wait of 2 s ended' <<<"$out" && grep -qF "$LDECL" <<<"$out" \
  && [ ! -e "$CD/dispatch.json" ] && [ ! -e "$CD/out/transcript" ] && [ ! -e "$CD/home/.fk" ]; } \
  && ok "--wait 2: still held at the bound, the run is refused (lane-busy, exit 1) naming the holder and the wait; nothing is made, no record written" || no "wait 2: rc=$rc $out"
out=$($DA local run "$CE" --wait 0 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF '[lane-busy]' <<<"$out" && grep -qF 'the wait of 0 s ended' <<<"$out" && ! grep -q 'waiting for it to end' <<<"$out" && [ ! -e "$CE/dispatch.json" ] && [ ! -e "$CE/home/.fk" ]; } \
  && ok "--wait 0 fails at once when the lane is held, without the waiting note" || no "wait 0: rc=$rc $out"
out=$($DA local run "$CE" --wait abc 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF -e '--wait: a whole number of seconds' <<<"$out"; } && ok "--wait takes a whole number of seconds" || no "wait abc: rc=$rc $out"
: > "$T/hold-go"; wait_until '[ -s "$T/ca.rc" ] && [ -s "$T/cb.rc" ] && [ -s "$T/cc.rc" ]' 90
{ [ "$(cat "$T/ca.rc")" = 0 ] && [ "$(cat "$T/cb.rc")" = 0 ] && [ "$(cat "$T/cc.rc")" = 0 ] && [ ! -e "$LREC" ] && [ -z "$(find "$MEM" -maxdepth 1 -name '.qargi-lane-wait.*')" ] && flock -n "$LOCKF" true; } \
  && ok "the holder and both waiters end ok; the record and the waiters' files are gone and the lane is free" || no "queue end: $(cat "$T"/c?.rc) $(ls -lA "$MEM")"
{ [ "$CA/out/transcript" -ot "$CB/out/transcript" ] && [ "$CB/out/transcript" -ot "$CC/out/transcript" ]; } \
  && ok "the waiters start in the order they began to wait: the one that waited longest takes the lane first (only the first polls it)" || no "queue order: $(stat -c '%n %y' "$CA/out/transcript" "$CB/out/transcript" "$CC/out/transcript")"
out=$($DA local list --lanes 2>&1)
grep -qE '^fakeplain +~/.fakesi-members/.qargi-run.lock +free *$' <<<"$out" && ok "local list --lanes of a free lane says free" || no "lanes free: $out"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid" "$T"/c?.rc
echo quick > "$T/mode"
out=$($DA local run "$CD" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -r .outcome "$CD/dispatch.json")" = ok ]; } && ok "the run that was refused as lane-busy starts with a plain local run once the lane is free: the refusal used up no attempt" || no "after lane-busy: rc=$rc $out"
# a --wait that is long enough: the run waits, the holder ends, the run starts
echo hold > "$T/mode"; prep cf; task; CF=$RUN; prep cg; task; CG=$RUN
( $DA local run "$CF" > "$T/cf.out" 2>&1; echo $? > "$T/cf.rc" ) &
wait_until '[ -e "$T/hold-ready" ]' 30
( $DA local run "$CG" --wait 60 > "$T/cg.out" 2>&1; echo $? > "$T/cg.rc" ) &
wait_until 'grep -q "holder is" "$T/cg.out"' 30
: > "$T/hold-go"; wait_until '[ -s "$T/cf.rc" ] && [ -s "$T/cg.rc" ]' 90
{ [ "$(cat "$T/cf.rc")" = 0 ] && [ "$(cat "$T/cg.rc")" = 0 ] && grep -qF 'is free; the run starts' "$T/cg.out"; } \
  && ok "--wait 60: the run queues behind the holder and starts when it ends" || no "wait long: $(cat "$T/cf.rc" "$T/cg.rc") $(cat "$T/cg.out")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid" "$T"/c?.rc "$LOCKF"
# a killed runner: the member keeps the lane and the record says so, local list --lanes too; once the member ends the stale record is not a holder
echo hold > "$T/mode"; prep cs1; task; CS1=$RUN
( $DA local run "$CS1" > "$T/cs1.out" 2>&1; echo $? > "$T/cs1.rc" ) &
wait_until '[ -e "$T/hold-ready" ] && [ -s "$T/member.pid" ] && [ -n "$(jq -r ".member // empty" "$CS1/dispatch.json")" ]' 30
kill -KILL "$(jq -r .runner "$CS1/dispatch.json")"; wait_until '[ -s "$T/cs1.rc" ]' 30
out=$($DA local list --lanes 2>&1)
grep -qE '^fakeplain +~/.fakesi-members/.qargi-run.lock +held, member alive, runner gone +lead lead-one run cs1 ' <<<"$out" \
  && ok "SIGKILL of the runner: the record and local list --lanes say member alive, runner gone" || no "lanes after SIGKILL: $out"
prep cs2; task; CS2=$RUN
( $DA local run "$CS2" > "$T/cs2.out" 2>&1; echo $? > "$T/cs2.rc" ) &
wait_until 'grep -q "holder is" "$T/cs2.out"' 30
grep -qE '^qargi: note: holder is lead lead-one, run cs1, holding it for [0-9]+s \(member alive, runner gone\)$' "$T/cs2.out" \
  && ok "and a run that waits for it says so in its holder line" || no "holder line after SIGKILL: $(cat "$T/cs2.out")"
: > "$T/hold-go"; wait_until '[ -s "$T/cs2.rc" ]' 60
[ "$(cat "$T/cs2.rc")" = 0 ] && ok "when the member ends the waiting run starts and ends ok" || no "after the killed runner's member: $(cat "$T/cs2.out")"
rm -f "$T/mode" "$T/hold-ready" "$T/hold-go" "$T/member.pid" "$LOCKF" "$LREC"; unset QARGI_LEAD

# --- the shipped runtime that declares it ------------------------------------------------------------------------------------------------------
{ [ "$(jq -c '.dispatch.home.link[0].private | del(.refresh)' lib/providers/codex.json)" = '{"set":{"tokens.refresh_token":"qargi-no-refresh"},"expiry":{"path":"tokens.access_token","encoding":"jwt-exp"}}' ] \
  && [ "$(jq -r '.dispatch.home.link[0].from' lib/providers/codex.json)" = \~/.codex-members/auth.json ] && [ "$(jq '.dispatch.home.link | length' lib/providers/codex.json)" = 1 ]; } \
  && ok "codex declares its members' sign-in as a private copy with the placeholder and the access token's expiry (the default margin)" || no "codex descriptor: $(jq -c .dispatch.home lib/providers/codex.json)"
{ [ "$(jq -r '.dispatch.home.link[0].private.refresh | .argv[0] == "codex" and .argv[1] == "exec" and (.argv | index("{scratch}")) != null and (.argv | index("{model}")) != null and (.argv | index("read-only")) != null and (.prompt | length) > 0 and .timeout_seconds == 120' lib/providers/codex.json)" = true ] \
  && [ "$(jq -r '.dispatch.argv[0]' lib/providers/codex.json)" = codex ] && ! jq -e '.dispatch.home.link[0].private.refresh | tostring | test("token|secret|key"; "i")' lib/providers/codex.json >/dev/null; } \
  && ok "and its refresh: the runtime's own read-only exec in a scratch directory with the default model, a short prompt, 120 s, no secret in it" || no "codex refresh: $(jq -c .dispatch.home.link[0].private.refresh lib/providers/codex.json)"
rm -rf "$T"
exit $fail
