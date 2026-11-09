#!/usr/bin/env bash
# qargi local run: the command line of a member is made from the data of the project's local runtime, and a fake CLI stands in for
# the real one (nothing here spends or reaches a network). Run: tests/test_local_run.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0
export QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T TMPDIR=$T/tmp
mkdir -p "$T/tmp" "$T/bin" "$T/c/projects"
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
DA=./bin/qargi
LC="git -c user.name=t -c user.email=t@example.net"
git init -q -b main "$T/r" && $LC -C "$T/r" commit -q --allow-empty -m one
git init -q -b main "$T/r2" && $LC -C "$T/r2" commit -q --allow-empty -m one
proj() { jq -n --arg n "$1" --arg p "$2" --arg v "$3" '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:$v},memory:{},budget_cents:500}' > "$T/c/projects/$1.json"; }
setprov() { jq --arg v "$1" '.models.provider = $v' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"; }

# the fake CLI, on PATH: it shows what it was given and writes a report where --out says
cat > "$T/bin/fakellm" <<'SH'
#!/usr/bin/env bash
out=''
for a in "$@"; do printf 'ARG[%s]\n' "$a"; done
while [ $# -gt 0 ]; do [ "$1" = --out ] && out=$2; shift; done
echo "PWD=$PWD"; echo "HOME=$HOME"; echo "KEY=${FAKE_KEY-unset}"; echo "OTHER=${OTHER_SECRET-unset}"; echo "GITCFG=${GIT_CONFIG_GLOBAL-unset}"; echo "GITWRAP=${GIT-unset}"; echo "MEMBERMARK=${QARGI_MEMBER_RUN-unset}"
echo "STDIN-BEGIN"; if [ -t 0 ]; then echo "(tty)"; else cat; fi; echo "STDIN-END"
[ -z "$out" ] || echo "report of the fake" > "$out/report.md"
case ${FAKE_MODE-} in
  exit3) exit 3;; exit5) exit 5;;
  sleep) sleep 3571 & echo $! > "${out:-.}/child.pid"; wait;;
esac
exit 0
SH
chmod 755 "$T/bin/fakellm"; export PATH=$T/bin:$PATH

# the runtimes, in the library (no record: used as they are); the one with a barrier is verified for read_only_barrier
LIB=$T/c/packs/providers
mk() { # name definition-json -> the library definition
  mkdir -p "$LIB/$1"; printf '%s\n' "$2" > "$LIB/$1/definition.json"; python3 -I tests/handseal.py "$LIB/$1"; }   # a library pack counts only once sealed
M='{"pattern":"^fake-.+$","tiers":{"*":{"model":"fake-m-1","alias":null,"verified_on":null,"source":"test"}},"effort":{"low":"l","medium":"m","high":"h","xhigh":null,"max":null}}'
ROCELL='{"value":"yes","verified_on":"2026-11-02","source":"test","note":"sandbox flags"}'
mk fakecmd "$(jq -n --argjson m "$M" --argjson c "$ROCELL" '{schema:2,kind:"provider",provider:"fakecmd",family:null,surface:"local",models:$m,
  capabilities:{read_only_barrier:$c},agents:null,resources:{},barrier:{kind:"sandbox-args"},
  dispatch:{mode:"command",argv:["fakellm","run","--model","{model}",{"if":"effort","then":["--effort","{effort}"]},"--clone","{clone}","--out","{out}"],
    class_argv:{"read-only":["--sandbox","read-only"]},prompt:{via:"stdin"},cwd:"{clone}",env_pass:["FAKE_KEY","FAKE_MODE"],timeout_s:60,
    output:{format:"text"},exit:{"0":"ok","3":"refused","*":"failed"}}}')"
mk fakearg "$(jq -n --argjson m "$M" '{schema:2,kind:"provider",provider:"fakearg",family:null,surface:"local",models:$m,
  capabilities:{},agents:null,resources:{},barrier:{kind:"none"},
  dispatch:{mode:"command",argv:["fakellm","-p","{prompt_arg}","--out","{out}"],prompt:{via:"arg"},cwd:"{clone}",output:{format:"text"}}}')"
mk fakeobj "$(jq -n --argjson m "$M" '{schema:2,kind:"provider",provider:"fakeobj",family:null,surface:"local",models:$m,
  capabilities:{},agents:null,resources:{},barrier:{kind:"none"},
  dispatch:{mode:"command",argv:["fakellm","-p","{prompt_file}",{"class":"read-only","then":["--ro"]},"--out","{out}"],prompt:{via:"file"},output:{format:"text"}}}')"
verify_ro() { # NAME -> the verification record of read_only_barrier for the definition as it is now
  python3 -I - "$1" <<'PY'
import sys; sys.path.insert(0, "lib")
import provider as P
n = sys.argv[1]
P.record_verification(n, {"read_only_barrier": {"hash": P.definition_hash(n), "by": "attest", "at": "2026-11-02", "note": "test"}})
PY
}
verify_ro fakecmd
proj rproj "$T/r" fakecmd; proj cproj "$T/r2" claude-code

prep() { # repo slug [ability] -> exports RUN CLONE OUT
  eval "$($DA local prepare --repo "$1" --base main --slug "$2" --scratch "$T" ${3:+--role "$3"} | sed '/^$/,$d' | sed 's/^/export /')"; }
task() { printf 'TASK: change the thing\nDONE: it is changed\n' > "$RUN/task.md"; }
arg0() { sed -n 's/^ARGV=//p'; }

# --- dry run: the exact argv and the prompt, nothing written -----------------------------------------------------------------------
prep "$T/r" w1; task
out=$($DA local run "$RUN" --dry-run 2>"$T/err"); rc=$?
want=$(jq -nc --arg c "$CLONE" --arg o "$OUT" '["fakellm","run","--model","fake-m-1","--clone",$c,"--out",$o]')
[ "$rc" = 0 ] && [ "$(arg0 <<<"$out")" = "$want" ] && ok "dry run: the argv is the data's, with the placeholders filled" || no "dry argv: rc=$rc [$(arg0 <<<"$out")] want [$want] $(cat "$T/err")"
grep -q '^You are a qargi member: a task-scoped worker' <<<"$out" && grep -q '^TASK: change the thing' <<<"$out" && grep -q '^CLASS=write' <<<"$out" \
  && ok "dry run: the prompt is the member body and the task block, with the class qargi recorded" || no "dry prompt: $out"
grep -q '{skills_dir}' <<<"$out" && no "the member body still has {skills_dir}" || ok "the member body's {skills_dir} is filled"
[ ! -e "$RUN/dispatch.json" ] && [ ! -e "$OUT/transcript" ] && [ ! -e "$RUN/prompt" ] && ok "dry run writes nothing" || no "dry run wrote: $(ls "$RUN" "$OUT")"
grep -q '^COMMAND=fakellm' <<<"$out" && grep -q '^PROMPT_VIA=stdin' <<<"$out" && grep -q '^ENV_PASS=FAKE_KEY,FAKE_MODE' <<<"$out" && ok "dry run names the command, the prompt route and the environment passed (names only)" || no "dry fields: $out"

out=$($DA local run "$RUN" --dry-run --effort high --model deep 2>&1); rc=$?
want=$(jq -nc --arg c "$CLONE" --arg o "$OUT" '["fakellm","run","--model","fake-m-1","--effort","h","--clone",$c,"--out",$o]')
[ "$rc" = 0 ] && [ "$(arg0 <<<"$out")" = "$want" ] && ok "--effort high gives the runtime's native effort in its {if} group" || no "effort argv: [$(arg0 <<<"$out")] $out"
out=$($DA local run "$RUN" --dry-run --effort max 2>&1)
{ ! grep -q -- '--effort' <<<"$(arg0 <<<"$out")"; } && grep -q '^NOTE=effort max is dropped' <<<"$out" && ok "an effort the runtime has no control for is dropped with a note" || no "max effort: $out"
out=$($DA local run "$RUN" --dry-run --model fake-m-9 2>&1); grep -q '"--model","fake-m-9"' <<<"$out" && ok "--model takes a model of the runtime's pattern" || no "model id: $out"
out=$($DA local run "$RUN" --dry-run --model other 2>&1); rc=$?; [ "$rc" != 0 ] && grep -q 'neither a tier' <<<"$out" && ok "a model outside the pattern is refused" || no "bad model: rc=$rc $out"

# --- the read-only class adds the definition's class arguments ---------------------------------------------------------------------
prep "$T/r" rv review; task
out=$($DA local run "$RUN" --dry-run 2>"$T/err"); rc=$?
want=$(jq -nc --arg c "$CLONE" --arg o "$OUT" '["fakellm","run","--model","fake-m-1","--clone",$c,"--out",$o,"--sandbox","read-only"]')
[ "$rc" = 0 ] && [ "$(arg0 <<<"$out")" = "$want" ] && grep -q '^CLASS=read-only' <<<"$out" && ok "read-only: class_argv (the sandbox arguments) is in the argv" || no "ro argv: rc=$rc [$(arg0 <<<"$out")] want [$want] $(cat "$T/err")"

# --- what a run writes in the member-writable run directory is never written through a link, a pipe or a second name ---------------------------------------
echo precious > "$T/victim"
for what in transcript transcript.err dispatch.json; do
  prep "$T/r" "lk-${what%%.*}"; task
  case $what in dispatch.json) place=$RUN/dispatch.json;; *) place=$OUT/$what;; esac
  ln -s "$T/victim" "$place"
  out=$($DA local run "$RUN" --again 2>&1); rc=$?
  { [ "$rc" = 2 ] && [ "$(cat "$T/victim")" = precious ] && ! grep -q Traceback <<<"$out"; } && ok "a $what that is a link is refused (also with --again), the file it points to is untouched" || no "$what link: rc=$rc $out; victim=$(cat "$T/victim")"
  rm -f "$place"; ln "$T/victim" "$place"
  out=$($DA local run "$RUN" --again 2>&1); rc=$?
  { [ "$rc" = 2 ] && [ "$(cat "$T/victim")" = precious ]; } && ok "a $what that is another name of a file is refused, the file is untouched" || no "$what hard link: rc=$rc $out; victim=$(cat "$T/victim")"
  rm -f "$place"; mkfifo "$place"
  out=$(timeout 30 $DA local run "$RUN" --again 2>&1); rc=$?
  { [ "$rc" = 2 ] && grep -q 'plain file' <<<"$out"; } && ok "a $what that is a pipe is refused, without waiting for a reader" || no "$what pipe: rc=$rc $out"
  rm -f "$place"
done
prep "$T/r" lk-out; task; rm -rf "$OUT"; ln -s "$T" "$OUT"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && [ ! -e "$T/transcript" ]; } && ok "an out directory that is a link elsewhere is refused" || no "out link: rc=$rc $out"
rm -f "$OUT"; mkdir "$OUT"
# the run's own files are read as files: a pipe in place of the ability or the task block does not stop the lead, and no ability is a refusal, not a traceback
prep "$T/r" lk-ab; task; rm -f "$RUN/ability"
out=$(python3 -I lib/local_run.py "$RUN" --project rproj --runtime fakecmd --class write --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'ability' <<<"$out" && ! grep -q Traceback <<<"$out"; } && ok "a run with no ability file is refused with a message" || no "no ability: rc=$rc $out"
echo build > "$RUN/ability"; rm -f "$RUN/task.md"; mkfifo "$RUN/task.md"
out=$(timeout 30 $DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'not a regular file' <<<"$out"; } && ok "a task block that is a pipe is refused, without waiting for a writer" || no "task pipe: rc=$rc $out"
rm -f "$RUN/task.md" "$T/victim"
# --- the project of a run is found from the lead's registry: a repo.path a member rewrote (to a repository of another project, so another runtime) is refused ---
prep "$T/r" fg1; task; cp "$RUN/repo.path" "$T/repo.path.keep"; echo "$T/r2" > "$RUN/repo.path"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "registry" <<<"$out" && ! grep -q '^COMMAND=' <<<"$out" && ok "run: a repo.path that differs from the registry's is refused, no runtime is looked up for it" || no "forged repo.path: rc=$rc $out"
cp "$T/repo.path.keep" "$RUN/repo.path"; rm -f "$T/repo.path.keep"
# --- a real run with the fake CLI --------------------------------------------------------------------------------------------------
prep "$T/r" w2; task
export OTHER_SECRET=leak GIT_AUTH_TOKEN=leak2
out=$(FAKE_KEY=envval-k1 $DA local run "$RUN" 2>"$T/err"); rc=$?
tr=$OUT/transcript
[ "$rc" = 0 ] && grep -q '^OUTCOME=ok' <<<"$out" && [ -f "$tr" ] && ok "a real run: exit 0, outcome ok, the transcript is in OUT" || no "real run: rc=$rc $out $(cat "$T/err")"
grep -q '^ARG\[run\]' "$tr" && grep -q '^ARG\[--model\]' "$tr" && grep -q '^ARG\[fake-m-1\]' "$tr" && grep -q "^ARG\[$CLONE\]" "$tr" && ok "the fake CLI got the argv as separate arguments" || no "transcript args: $(head -20 "$tr")"
[ "$(cat "$OUT/report.md" 2>/dev/null)" = "report of the fake" ] && ok "what the CLI wrote to OUT is there" || no "no report in OUT"
grep -q "^PWD=$CLONE\$" "$tr" && ok "it ran in the clone" || no "cwd: $(grep PWD "$tr")"
grep -q '^STDIN-BEGIN' "$tr" && sed -n '/^STDIN-BEGIN/,/^STDIN-END/p' "$tr" | grep -q 'TASK: change the thing' && sed -n '/^STDIN-BEGIN/,/^STDIN-END/p' "$tr" | grep -q 'You are a qargi member' \
  && ok "the prompt came on its standard input" || no "stdin: $(sed -n '/STDIN-BEGIN/,$p' "$tr" | head)"
grep -q '^KEY=envval-k1$' "$tr" && grep -q '^OTHER=unset$' "$tr" && ok "only env_pass names reach it (FAKE_KEY did, OTHER_SECRET did not)" || no "env: $(grep -E 'KEY|OTHER' "$tr")"
grep -q "^HOME=$RUN/home\$" "$tr" && grep -q '^GITCFG=/dev/null$' "$tr" && grep -q "^GITWRAP=$RUN/git\$" "$tr" && ok "it has the git wrapper's environment (no home, no global git configuration)" || no "git env: $(grep -E 'HOME|GIT' "$tr")"
grep -q "^MEMBERMARK=$RUN\$" "$tr" && ok "it carries the member mark QARGI_MEMBER_RUN (the run directory), so the marshal knows it from any directory" || no "member mark: $(grep MEMBERMARK "$tr")"
[ "$(jq -r .outcome "$RUN/dispatch.json")" = ok ] && [ "$(jq -r '.argv | join(" ")' "$RUN/dispatch.json")" = "fakellm run --model fake-m-1 --clone $CLONE --out $OUT" ] && ! grep -q 'envval-k1' "$RUN/dispatch.json" \
  && ok "dispatch.json records the argv and the outcome, not an environment value" || no "dispatch.json: $(jq -c . "$RUN/dispatch.json" 2>&1) (wanted outcome ok, argv: fakellm run --model fake-m-1 --clone $CLONE --out $OUT)"
$DA local verify "$RUN" >/dev/null 2>&1 && ok "verify passes after the run" || no "verify after run"
out=$($DA local run "$RUN" 2>&1); rc=$?; [ "$rc" = 2 ] && grep -q 'has been run already' <<<"$out" && ok "a second run is refused" || no "second run: rc=$rc $out"
out=$(FAKE_KEY=k2 $DA local run "$RUN" --again 2>&1); rc=$?; [ "$rc" = 0 ] && grep -q '^KEY=k2$' "$tr" && ok "--again runs it again and replaces the transcript" || no "again: rc=$rc $out"

# the run's temporary directory is the registry's (as `local clean` reads it), never the run's own tmpdir file, which a member can write
REGTMP=$(jq -r --arg r "$RUN" 'select(.run == $r) | .tmpdir' "$T/s/local-runs.jsonl" | tail -1)
mv "$RUN/tmpdir" "$RUN/tmpdir.real"; printf '%s\n' "$T/forged-tmp" > "$RUN/tmpdir"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -n "$REGTMP" ] && grep -q "^TMP=$REGTMP\$" <<<"$out" && ! grep -q 'forged-tmp' <<<"$out"; } \
  && ok "the run's temporary directory is the registry's: a forged RUN/tmpdir is not read" || no "forged tmpdir: rc=$rc $(grep -n 'TMP=' <<<"$out")"
mv "$RUN/tmpdir.real" "$RUN/tmpdir"

# --- the exit status maps to an outcome; a timeout is bounded ---------------------------------------------------------------------
out=$(FAKE_MODE=exit3 $DA local run "$RUN" --again 2>&1); rc=$?; [ "$rc" = 2 ] && grep -q '^OUTCOME=refused' <<<"$out" && ok "dispatch.exit maps status 3 to refused (exit 2)" || no "exit3: rc=$rc $out"
out=$(FAKE_MODE=exit5 $DA local run "$RUN" --again 2>&1); rc=$?; [ "$rc" = 1 ] && grep -q '^OUTCOME=failed' <<<"$out" && ok "any other status is failed (exit 1)" || no "exit5: rc=$rc $out"
out=$(FAKE_MODE="sleep" timeout 600 $DA local run "$RUN" --again --timeout 1 2>&1); rc=$?   # the deadline of the test: the run must end by itself
{ [ "$rc" = 1 ] && grep -q 'timed out after 1s' <<<"$out" && [ "$(jq -r .timed_out "$RUN/dispatch.json")" = true ]; } && ok "a run past the bound is stopped and reported" || no "timeout: rc=$rc $out"
kid=$(cat "$OUT/child.pid" 2>/dev/null)
if [ -n "$kid" ] && ! kill -0 "$kid" 2>/dev/null; then ok "the whole process group was killed"; else no "a child of the timed-out run is still alive (pid '${kid:-none}')"; [ -z "$kid" ] || kill -KILL "$kid" 2>/dev/null; fi

# --- the prompt as an argument, or as a file ----------------------------------------------------------------------------------------
setprov fakearg; prep "$T/r" w3; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
n=$(arg0 <<<"$out" | jq -r 'length'); p=$(arg0 <<<"$out" | jq -r '.[2]')
{ [ "$rc" = 0 ] && [ "$n" = 5 ] && [ "$(arg0 <<<"$out" | jq -r '.[1]')" = -p ] && [[ $p == "You are a qargi member"* ]] && [[ $p == *"TASK: change the thing"* ]]; } && ok "via arg: the whole prompt is one argument" || no "arg via: rc=$rc $out"
out=$($DA local run "$RUN" 2>&1); rc=$?; grep -q '^ARG\[You are a qargi member' "$OUT/transcript" && [ "$rc" = 0 ] && ok "and a real run passes it" || no "arg run: rc=$rc $out"
setprov fakeobj; prep "$T/r" w4; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(arg0 <<<"$out" | jq -c '.')" = "$(jq -nc --arg f "$RUN/prompt/prompt.md" --arg o "$OUT" '["fakellm","-p",$f,"--out",$o]')" ] && ok "via file: {prompt_file} is the run's prompt/prompt.md, and a write run has no class group" || no "file via: rc=$rc $out"
out=$($DA local run "$RUN" 2>&1); rc=$?; grep -q "^ARG\[$RUN/prompt/prompt.md\]" "$OUT/transcript" && grep -q "TASK: change the thing" "$RUN/prompt/prompt.md" && ok "a real run writes the prompt file" || no "file run: rc=$rc $out"

# --- the prompt file stays in its own directory of the run, never over a control file of the run (A8) --------------------------------
mk fakectl "$(jq -n --argjson m "$M" '{schema:2,kind:"provider",provider:"fakectl",family:null,surface:"local",models:$m,
  capabilities:{},agents:null,resources:{},barrier:{kind:"none"},
  dispatch:{mode:"command",argv:["fakellm","-p","{prompt_file}","--out","{out}"],prompt:{via:"file",file:"refs.before"},output:{format:"text"}}}')"
setprov fakectl; prep "$T/r" w4b; task
refs=$(cat "$RUN/refs.before"); cls=$(cat "$RUN/class" 2>/dev/null || true)
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$(cat "$RUN/refs.before")" = "$refs" ] && [ "$(cat "$RUN/class" 2>/dev/null || true)" = "$cls" ] && ! grep -q 'You are a qargi member' "$RUN/refs.before"; } \
  && ok "prompt.file named refs.before: the run's refs.before is untouched" || no "prompt.file overwrote a control file: $(head -c 200 "$RUN/refs.before")"
[ "$(sed -n 's/^ARG\[\(.*refs.before\)\]$/\1/p' "$OUT/transcript" 2>/dev/null | head -1)" = "$RUN/prompt/refs.before" ] && grep -q 'TASK: change the thing' "$RUN/prompt/refs.before" \
  && ok "the prompt went to RUN/prompt/, the dedicated directory, under that name" || no "prompt dir: rc=$rc $out $(ls "$RUN" "$RUN/prompt" 2>&1)"
$DA local verify "$RUN" >/dev/null 2>&1 && ok "verify still passes after that run" || no "verify after prompt.file run"
prep "$T/r" w4c; task
mkdir -p "$T/elsewhere"; ln -s "$T/elsewhere" "$RUN/prompt"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && [ -z "$(ls "$T/elsewhere")" ] && [ ! -e "$RUN/dispatch.json" ]; } && ok "a prompt directory that is a link elsewhere is refused and nothing is written through it" || no "prompt dir link: rc=$rc $out $(ls "$T/elsewhere")"
rm -f "$RUN/prompt"; mkdir "$RUN/prompt"; ln -s "$RUN/refs.before" "$RUN/prompt/refs.before"; refs=$(cat "$RUN/refs.before")
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && [ "$(cat "$RUN/refs.before")" = "$refs" ] && [ ! -e "$RUN/dispatch.json" ]; } && ok "a prompt file that is a link to a control file is refused and the target is untouched" || no "prompt file link: rc=$rc $out"
setprov fakeobj

# --- a read-only run needs a barrier, or the project's acceptance --------------------------------------------------------------------
setprov fakecmd; prep "$T/r" rv2 review; task
setprov fakeobj
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'has no read-only barrier on local' <<<"$out" && grep -q 'qargi provider accept fakeobj --surface local --no-barrier --project rproj' <<<"$out"; } \
  && ok "read-only on a runtime with no barrier: refused, with the accept command" || no "no barrier: rc=$rc $out"
jq '.models.accept_no_barrier = {local: {by: "owner", at: "2026-11-02", reason: "test"}}' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q '"--ro"' <<<"$out" && ok "with the project's acceptance it goes on, and the class group adds its arguments" || no "accepted: rc=$rc $out"
jq 'del(.models.accept_no_barrier)' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"

# a runtime whose definition claims read_only_barrier (and the owner attested it) with barrier kind none and no read-only arguments in its
# dispatch: nothing would hold the member, so the capability reads as no, however it was attested (a fail-closed answer): the read-only run is refused
# like any barrier-less one, and the refusal says the claim has nothing behind it
mk fakeclaim "$(jq -n --argjson m "$M" --argjson c "$ROCELL" '{schema:2,kind:"provider",provider:"fakeclaim",family:null,surface:"local",models:$m,
  capabilities:{read_only_barrier:$c},agents:null,resources:{},barrier:{kind:"none"},
  dispatch:{mode:"command",argv:["fakellm","run","--model","{model}","--out","{out}"],prompt:{via:"stdin"},cwd:"{clone}",timeout_s:60,output:{format:"text"}}}')"
verify_ro fakeclaim
setprov fakeclaim; prep "$T/r" rv2c review; task
[ "$(python3 -I lib/provider.py effective fakeclaim local read_only_barrier 2>&1)" = no ] && ok "fail-open claim: the attested claim with nothing behind it reads as no" || no "fail-open setup: $(python3 -I lib/provider.py effective fakeclaim local read_only_barrier 2>&1)"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'fakeclaim' <<<"$out" && grep -q 'on local' <<<"$out" && grep -q 'barrier.kind is none' <<<"$out" && grep -q 'qargi provider accept fakeclaim --surface local --no-barrier --project rproj' <<<"$out" && ! grep -q '^ARGV=' <<<"$out"; } \
  && ok "a read-only run of a runtime that claims a barrier it does not have is refused (exit 2) with the accept command" || no "fail-open claim, dry: rc=$rc $out"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && [ ! -e "$RUN/dispatch.json" ] && [ ! -e "$OUT/transcript" ]; } && ok "and a real one starts nothing" || no "fail-open claim, real: rc=$rc $out"
prep "$T/r" w2c; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a write run of the same runtime is not affected" || no "fail-open claim, write: rc=$rc $out"
jq '.models.accept_no_barrier = {local: {by: "owner", at: "2026-11-02", reason: "test"}}' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
prep "$T/r" rv2d review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
[ "$rc" = 0 ] && ok "with the project's acceptance of no barrier the same read-only run goes on" || no "fail-open claim, accepted: rc=$rc $out"
jq 'del(.models.accept_no_barrier)' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"

# arguments for another class, or an empty read-only list, hold no read-only member either: the same claim with nothing behind it
for v in write empty; do
  case $v in
    write) CA='{"write":["--w"]}';;
    empty) CA='{"read-only":[]}';;
  esac
  mk "fakeclaim$v" "$(jq -n --arg n "fakeclaim$v" --argjson ca "$CA" --argjson m "$M" --argjson c "$ROCELL" '{schema:2,kind:"provider",provider:$n,family:null,surface:"local",models:$m,
    capabilities:{read_only_barrier:$c},agents:null,resources:{},barrier:{kind:"none"},
    dispatch:{mode:"command",argv:["fakellm","run","--model","{model}","--out","{out}"],class_argv:$ca,prompt:{via:"stdin"},cwd:"{clone}",timeout_s:60,output:{format:"text"}}}')"
  verify_ro "fakeclaim$v"
  setprov "fakeclaim$v"; prep "$T/r" "rv2$v" review; task
  out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
  { [ "$rc" = 2 ] && grep -q "fakeclaim$v" <<<"$out" && grep -q "qargi provider accept fakeclaim$v --surface local --no-barrier" <<<"$out" && ! grep -q '^ARGV=' <<<"$out"; } \
    && ok "a read-only run whose only class arguments are $v ones is refused: they hold no read-only member" || no "class arguments ($v): rc=$rc $out"
done

# a runtime whose own barrier is a hook or an adapter: the hook lives in a member file that a local run never writes (it has no agent file), and a local run
# never calls the adapter's barrier-check, so nothing in the run applies the barrier its capability claims. The owner attested it, so the capability reads as yes
HOOK='{"input":"json-stdin","tool_pointer":"/event/tool","command_pointer":"/event/args/cmd","cwd_pointer":"/workdir","path_pointers":{"write":["/event/args/target"],"read":["/event/args/target"]},
  "tool_names":{"shell":["run_shell"],"write":["patch_file"],"read":["open_file"]},"deny":{"exit":2,"stream":"stderr"},"allow":{"exit":0}}'
mk fakehook "$(jq -n --argjson m "$M" --argjson c "$ROCELL" --argjson h "$HOOK" '{schema:2,kind:"provider",provider:"fakehook",family:null,surface:"local",models:$m,
  capabilities:{read_only_barrier:$c},agents:null,resources:{},barrier:{kind:"hook",hook:$h},
  dispatch:{mode:"command",argv:["fakellm","run","--model","{model}","--out","{out}"],prompt:{via:"stdin"},cwd:"{clone}",timeout_s:60,output:{format:"text"}}}')"
mk fakehookargs "$(jq -n --argjson m "$M" --argjson c "$ROCELL" --argjson h "$HOOK" '{schema:2,kind:"provider",provider:"fakehookargs",family:null,surface:"local",models:$m,
  capabilities:{read_only_barrier:$c},agents:null,resources:{},barrier:{kind:"hook",hook:$h},
  dispatch:{mode:"command",argv:["fakellm","run","--model","{model}","--out","{out}"],class_argv:{"read-only":["--ro"]},prompt:{via:"stdin"},cwd:"{clone}",timeout_s:60,output:{format:"text"}}}')"
mk fakeadapt "$(jq -n --argjson m "$M" --argjson c "$ROCELL" '{schema:2,kind:"provider",provider:"fakeadapt",family:null,surface:"local",models:$m,
  capabilities:{read_only_barrier:$c},agents:null,resources:{},barrier:{kind:"adapter"},adapter:"adapter",adapter_verbs:["resolve","dispatch-local","barrier-check"],
  dispatch:{mode:"command",argv:["fakellm","run","--model","{model}","--out","{out}"],prompt:{via:"stdin"},cwd:"{clone}",timeout_s:60,output:{format:"text"}}}')"
for n in fakehook fakehookargs fakeadapt; do verify_ro "$n"; done
for n in fakehook fakeadapt; do
  setprov "$n"; prep "$T/r" "rv6$n" review; task
  out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
  { [ "$rc" = 2 ] && grep -q "$n" <<<"$out" && grep -q 'on local' <<<"$out" && grep -q "qargi provider accept $n --surface local --no-barrier --project rproj" <<<"$out" && ! grep -q '^ARGV=' <<<"$out"; } \
    && ok "a read-only run of $n, whose own barrier nothing in a local run applies, is refused (exit 2) with the accept command" || no "$n barrier, dry: rc=$rc $out"
  out=$($DA local run "$RUN" 2>&1); rc=$?
  { [ "$rc" = 2 ] && [ ! -e "$RUN/dispatch.json" ] && [ ! -e "$OUT/transcript" ]; } && ok "and a real one starts nothing" || no "$n barrier, real: rc=$rc $out"
  prep "$T/r" "w6$n"; task
  out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
  [ "$rc" = 0 ] && ok "a write run of $n is not affected" || no "$n barrier, write: rc=$rc $out"
  jq '.models.accept_no_barrier = {local: {by: "owner", at: "2026-11-02", reason: "test"}}' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
  prep "$T/r" "rv6a$n" review; task
  out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
  [ "$rc" = 0 ] && ok "with the project's acceptance of no barrier the same read-only run goes on" || no "$n barrier, accepted: rc=$rc $out"
  jq 'del(.models.accept_no_barrier)' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
done
# the read-only arguments a local run does apply are the barrier it has: a hook runtime that also declares them goes on
setprov fakehookargs; prep "$T/r" rv6c review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '"--ro"' <<<"$out"; } && ok "a hook runtime whose dispatch carries read-only arguments: the run applies them and goes on" || no "hook with arguments: rc=$rc $out"
setprov fakeobj

# --- the project's extensions are part of the definition a run acts on (A2) ---------------------------------------------------------
# fakenobar has a command dispatch and no barrier; sandext gives it a sandbox-args barrier and claims read_only_barrier, and the owner
# attested it. The extension adds no read-only arguments (an extension cannot add class_argv), so nothing in a local run applies that
# barrier: the capability is true of the composition but the run would start with full write access.
mk fakenobar "$(jq -n --argjson m "$M" '{schema:2,kind:"provider",provider:"fakenobar",family:null,surface:"local",models:$m,
  capabilities:{},agents:null,resources:{},barrier:{kind:"none"},
  dispatch:{mode:"command",argv:["fakellm","run","--model","{model}","--out","{out}"],prompt:{via:"stdin"},cwd:"{clone}",timeout_s:60,output:{format:"text"}}}')"
mk sandext "$(jq -n '{schema:2,kind:"extension",extension:"sandext",description:"a sandbox-args barrier",extends:"fakenobar",surface:"local",provides:["read_only_barrier"],
  adds:{capabilities:{read_only_barrier:{value:"yes",note:"sandbox flags"}},barrier:{kind:"sandbox-args"}}}')"
mk skillext "$(jq -n '{schema:2,kind:"extension",extension:"skillext",description:"a skills directory",extends:"fakenobar",surface:"local",provides:["skills"],
  adds:{capabilities:{skills:{value:"yes",note:"n"}},resources:{skills:{project_dir:".ext/skills",items:"dir-per-item",entry:"SKILL.md",format:"skill-md",link:{project:"dir-symlink",user:"none"}}}}}')"
attest_ext() { # EXT BASE -> the verification record of read_only_barrier, bound to the extension on the base
  python3 -I - "$1" "$2" <<'PY'
import sys; sys.path.insert(0, "lib")
import provider as P
x, b = sys.argv[1:3]
P.record_verification(x, {"read_only_barrier": {"hash": P.extension_hash(x, b, "local"), "by": "attest", "at": "2026-11-02", "note": "test"}})
PY
}
attest_ext sandext fakenobar
jq '.models.provider = "fakenobar" | .models.extensions = ["sandext", "skillext"]' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
[ "$(python3 -I lib/provider.py effective fakenobar local read_only_barrier --project rproj 2>&1)" = yes ] && ok "extension barrier: the composition counts the attested barrier as yes" || no "extension barrier setup: $(python3 -I lib/provider.py effective fakenobar local read_only_barrier --project rproj 2>&1)"
prep "$T/r" rv3 review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'sandext' <<<"$out" && ! grep -q '^ARGV=' <<<"$out"; } && ok "a read-only run whose barrier an extension provides and a local run does not apply is refused (dry run)" || no "extension barrier, dry: rc=$rc $out"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'sandext' <<<"$out" && [ ! -e "$RUN/dispatch.json" ] && [ ! -e "$OUT/transcript" ]; } && ok "and a real one starts nothing" || no "extension barrier, real: rc=$rc $out"
jq '.models.accept_no_barrier = {local: {by: "owner", at: "2026-11-02", reason: "test"}}' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
prep "$T/r" rv4 review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
[ "$rc" = 0 ] && ok "with the project's own acceptance of no barrier the same run goes on" || no "extension barrier, accepted: rc=$rc $out"
jq 'del(.models.accept_no_barrier)' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
# an extension that claims the capability and adds no barrier at all is no barrier either
mk capext "$(jq -n '{schema:2,kind:"extension",extension:"capext",description:"claims only",extends:"fakenobar",surface:"local",provides:["read_only_barrier"],
  adds:{capabilities:{read_only_barrier:{value:"yes",note:"claim"}}}}')"
attest_ext capext fakenobar
jq '.models.extensions = ["capext"]' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
prep "$T/r" rv5 review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'capext' <<<"$out"; } && ok "an extension that only claims read_only_barrier is refused the same way" || no "extension claim: rc=$rc $out"
jq '.models.extensions = ["sandext", "skillext"]' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
prep "$T/r" w7; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '\.ext/skills' <<<"$out"; } && ok "a write run uses the composed definition: the member body names the skills directory an extension adds" || no "extension skills dir: rc=$rc $(grep -i skills <<<"$out" | head -3)"
jq 'del(.models.extensions)' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
setprov fakecmd

# --- an in-session runtime is not started here ----------------------------------------------------------------------------------------
prep "$T/r2" c1; task
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'dispatch the member with the Agent tool' <<<"$out" && grep -q 'claude-code' <<<"$out" && [ ! -e "$RUN/dispatch.json" ]; } && ok "claude-code (in-session): refused, dispatch with the Agent tool" || no "in-session: rc=$rc $out"
out=$($DA local run "$RUN" --dry-run 2>&1); [ $? = 2 ] && ok "and the dry run refuses too" || no "in-session dry: $out"

# --- the sealed pack executable runs from the exec copy only after approval -------------------------------------------------------------
setprov fakecmd
mkdir -p "$LIB/fakepack/bin"
cat > "$LIB/fakepack/bin/pack-llm" <<'SH'
#!/usr/bin/env bash
echo "SELF=$0"; echo "DIR=$(dirname "$(readlink -f "$0")")"; cat >/dev/null
exit 0
SH
chmod 755 "$LIB/fakepack/bin/pack-llm"
jq -n --argjson m "$M" '{schema:2,kind:"provider",provider:"fakepack",family:null,surface:"local",models:$m,capabilities:{},agents:null,resources:{},barrier:{kind:"none"},
  dispatch:{mode:"command",argv:["bin/pack-llm","--model","{model}"],prompt:{via:"stdin"},output:{format:"text"}}}' > "$LIB/fakepack/definition.json"
seal() { # NAME approved-executables-json -> the pack record
  python3 -I - "$LIB/$1" "$2" <<'PY'
import sys, json, hashlib, os; sys.path.insert(0, "lib")
import provider as P
d, ex = sys.argv[1], json.loads(sys.argv[2])
rec = {"kind": "provider", "sealed": True, "sha256": P.tree_hash(d), "approved": True, "source": "test",
       "executables": {r: hashlib.sha256(open(os.path.join(d, r), "rb").read()).hexdigest() for r in ex}}
json.dump(rec, open(os.path.join(d, ".pack.json"), "w"))
PY
}
setprov fakepack; seal fakepack '[]'; prep "$T/r" w5; task   # prepare refuses a provider that is set but does not resolve (an unsealed pack), so seal first
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q "not an executable approved for the pack 'fakepack'" <<<"$out" && [ ! -e "$OUT/transcript" ]; } && ok "a pack executable the record does not approve is not run" || no "unapproved: rc=$rc $out"
seal fakepack '["bin/pack-llm"]'
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^COMMAND=<sealed copy of pack fakepack>/bin/pack-llm' <<<"$out"; } && ok "dry run on an approved pack executable names the sealed copy and checks it" || no "pack dry: rc=$rc $out"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -Eq "^SELF=$T/tmp/qargi-exec\..+/fakepack/bin/pack-llm\$" "$OUT/transcript"; } && ok "approved: it ran from the private exec copy, not from the library" || no "pack run: rc=$rc $out $(cat "$OUT/transcript" 2>/dev/null)"
[ -z "$(ls -d "$T"/tmp/qargi-exec.* 2>/dev/null)" ] && ok "the copy is removed afterwards" || no "exec copy left: $(ls "$T/tmp")"
echo '# changed after the seal' >> "$LIB/fakepack/bin/pack-llm"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'changed since it was sealed' <<<"$out"; } && ok "a pack changed since it was sealed is not run (drift)" || no "drift: rc=$rc $out"

# --- refusals of the definition itself --------------------------------------------------------------------------------------------
bad() { # NAME dispatch-json: a runtime with this dispatch, project set to it
  mk "$1" "$(jq -n --arg n "$1" --argjson m "$M" --argjson d "$2" '{schema:2,kind:"provider",provider:$n,family:null,surface:"local",models:$m,capabilities:{},agents:null,resources:{},barrier:{kind:"none"},dispatch:$d}')"
  setprov "$1"; }
setprov fakecmd; prep "$T/r" w6; task   # the pack above has drifted: prepare would refuse it
tryrun() { out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?; }
bad fakeb1 '{"mode":"command","argv":["fakellm","{bogus}"],"prompt":{"via":"stdin"}}'; tryrun
[ "$rc" = 2 ] && grep -q 'unknown placeholder {bogus}' <<<"$out" && ok "an unknown placeholder is refused" || no "bogus: rc=$rc $out"
bad fakeb2 '{"mode":"command","argv":"fakellm run","prompt":{"via":"stdin"}}'; tryrun
[ "$rc" = 2 ] && grep -q 'never a shell string' <<<"$out" && ok "a shell string for the argv is refused" || no "string argv: rc=$rc $out"
bad fakeb3 '{"mode":"command","argv":["fakellm"],"prompt":{"via":"stdin"},"env_pass":["GIT_DIR"]}'; tryrun
[ "$rc" = 2 ] && grep -q 'names GIT_DIR' <<<"$out" && ok "env_pass may not replace the git wrapper's variables" || no "env_pass: rc=$rc $out"
for ev in HOME GH_TOKEN GITHUB_TOKEN SSH_AUTH_SOCK LD_PRELOAD PATH PYTHONPATH BASH_ENV; do
  bad fakeb3e "{\"mode\":\"command\",\"argv\":[\"fakellm\"],\"prompt\":{\"via\":\"stdin\"},\"env_pass\":[\"$ev\"]}"; tryrun
  [ "$rc" = 2 ] && grep -q "env_pass of fakeb3e names $ev" <<<"$out" && ok "env_pass may not hand on $ev (the member's home, search path, loaders and credentials are the run's)" || no "env_pass $ev: rc=$rc $out"
done
bad fakeb4 '{"mode":"command","argv":["fakellm"],"prompt":{"via":"arg"}}'; tryrun
[ "$rc" = 2 ] && grep -q 'has no {prompt_arg}' <<<"$out" && ok "a prompt route the argv does not use is refused" || no "via mismatch: rc=$rc $out"
bad fakeb5 '{"mode":"command","argv":["no-such-cli-here","x"],"prompt":{"via":"stdin"}}'; tryrun
[ "$rc" = 3 ] && grep -q 'not on PATH' <<<"$out" && ok "a command that is not on PATH is exit 3" || no "no cli: rc=$rc $out"
bad fakeb6 '{"mode":"command","argv":["/bin/echo","x"],"prompt":{"via":"stdin"}}'; tryrun
[ "$rc" = 2 ] && grep -q "not a path inside the definition's directory" <<<"$out" && ok "an absolute command path is refused" || no "abs: rc=$rc $out"
bad fakeb7 '{"mode":"command","argv":["fakellm","{agent_file}"],"prompt":{"via":"stdin"}}'; tryrun
[ "$rc" = 3 ] && grep -q 'does not provide' <<<"$out" && ok "{agent_file} is not available to a runtime with no agent files" || no "agent_file: rc=$rc $out"
bad fakeb8 '{"mode":"adapter"}'; tryrun
[ "$rc" = 3 ] && ok "mode adapter is exit 3 (not run here)" || no "adapter mode: rc=$rc $out"
bad fakeb9 '{"mode":"command","argv":["fakellm"],"prompt":{"via":"stdin"},"timeout_s":0}'; tryrun
[ "$rc" = 2 ] && grep -q 'timeout' <<<"$out" && ok "a timeout of 0 is refused" || no "timeout: rc=$rc $out"
# a pack somebody put in the library by hand (no record: nobody read it, nobody sealed it) is not loaded, so its argv never runs
mkdir -p "$LIB/handrun"
jq -n --argjson m "$M" --arg f "$T/PWNED" '{schema:2,kind:"provider",provider:"handrun",family:null,surface:"local",models:$m,capabilities:{},agents:null,resources:{},barrier:{kind:"none"},
  dispatch:{mode:"command",argv:["bash","-c",("touch " + $f)],prompt:{via:"stdin"},output:{format:"text"}}}' > "$LIB/handrun/definition.json"
setprov handrun
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q "provider 'handrun' has no record" <<<"$out" && grep -q 'qargi provider seal handrun' <<<"$out" && [ ! -e "$T/PWNED" ]; } \
  && ok "a pack put in the library by hand is refused with the way in (seal it), and its command did not run" || no "hand-placed pack: rc=$rc $out"

# --- the run itself ---------------------------------------------------------------------------------------------------------------------
setprov fakecmd
rm -f "$RUN/task.md"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?; [ "$rc" = 1 ] && grep -q 'no task block' <<<"$out" && ok "no task block: stated, exit 1" || no "no task: rc=$rc $out"
echo 'TASK: x' > "$T/other-task.md"
out=$($DA local run "$RUN" --dry-run --task "$T/other-task.md" 2>&1); rc=$?; [ "$rc" = 0 ] && grep -q '^TASK: x' <<<"$out" && ok "--task FILE names the task block" || no "--task: rc=$rc $out"
out=$($DA local run "$T" --dry-run 2>&1); rc=$?; [ "$rc" != 0 ] && grep -q 'RUN dir made by prepare' <<<"$out" && ok "a directory prepare did not make is refused" || no "not a run: rc=$rc $out"
out=$($DA local run "$RUN" --dry-run --project other 2>&1); rc=$?; [ "$rc" != 0 ] && ok "the project is not an option" || no "--project accepted: $out"
rm -f "$T/c/projects/rproj.json"
out=$($DA local run "$RUN" --dry-run --task "$T/other-task.md" 2>&1); rc=$?; [ "$rc" = 2 ] && grep -q 'no stored project has the repository' <<<"$out" && ok "a run whose repository belongs to no stored project is refused" || no "no project: rc=$rc $out"

rm -rf "$T"
exit $fail
