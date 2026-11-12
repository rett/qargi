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
# shellcheck source=fixtures.sh
. tests/fixtures.sh
# the shipped codex declares that its sandbox hides /dev (dispatch.hidden_paths), and this test's directory may lie there (a TMPDIR under /dev/shm):
# the test runs a copy of the tool whose codex hides CXHID, a directory of the test, in its place, so what it shows of codex holds wherever it runs
CXHID=$(realpath "$T")/cxhid
copy_tool . "$T/tool"
jq --arg h "$CXHID" '.dispatch.hidden_paths.prefixes = [$h]' lib/providers/codex.json > "$T/tool/lib/providers/codex.json"
CX=$T/tool/lib/providers/codex.json
DA=$T/tool/bin/qargi
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
echo "SELF0=$0"; echo "MEMBERPATH=$PATH"; echo "PWD=$PWD"; echo "HOME=$HOME"; echo "KEY=${FAKE_KEY-unset}"; echo "OTHER=${OTHER_SECRET-unset}"; echo "GITCFG=${GIT_CONFIG_GLOBAL-unset}"; echo "GITWRAP=${GIT-unset}"; echo "MEMBERMARK=${QARGI_MEMBER_RUN-unset}"
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
finarg() { # the argv on stdin with the value of -o, when it is the run's own new {final_message} file (RUN/final.XXXXXXXXXXXX/message.md), as FINAL
  jq -c --arg r "$RUN/final." '(index(["-o"])) as $i | if $i != null and (.[$i+1] | startswith($r) and endswith("/message.md") and (ltrimstr($r) | test("^[0-9a-f]{12}/message[.]md$"))) then .[$i+1] = "FINAL" else . end'; }

# --- dry run: the exact argv and the prompt, nothing written -----------------------------------------------------------------------
prep "$T/r" w1; task
out=$($DA local run "$RUN" --dry-run 2>"$T/err"); rc=$?
want=$(jq -nc --arg c "$CLONE" --arg o "$OUT" '["fakellm","run","--model","fake-m-1","--clone",$c,"--out",$o]')
[ "$rc" = 0 ] && [ "$(arg0 <<<"$out")" = "$want" ] && ok "dry run: the argv is the data's, with the placeholders filled" || no "dry argv: rc=$rc [$(arg0 <<<"$out")] want [$want] $(cat "$T/err")"
grep -q '^You are a qargi member: a task-scoped worker' <<<"$out" && grep -q '^TASK: change the thing' <<<"$out" && grep -q '^CLASS=write' <<<"$out" \
  && ok "dry run: the prompt is the member body and the task block, with the class qargi recorded" || no "dry prompt: $out"
grep -q '{skills_dir}' <<<"$out" && no "the member body still has {skills_dir}" || ok "the member body's {skills_dir} is filled"
[ ! -e "$RUN/dispatch.json" ] && [ ! -e "$OUT/transcript" ] && [ ! -e "$RUN/prompt" ] && ok "dry run writes nothing" || no "dry run wrote: $(ls "$RUN" "$OUT")"
grep -qxF "COMMAND=$(realpath "$T/bin/fakellm")" <<<"$out" && grep -q '^PROMPT_VIA=stdin' <<<"$out" && grep -q '^ENV_PASS=FAKE_KEY,FAKE_MODE' <<<"$out" && ok "dry run names the command (the absolute path it runs), the prompt route and the environment passed (names only)" || no "dry fields: $out"

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

# --- a runtime whose sandbox hides part of the filesystem (dispatch.hidden_paths): a run whose member would not see a path it works with is ----
# refused, by prepare before it makes anything and by local run before it starts anything. The hidden place is HID, a directory of this test.
HID=$(realpath "$T")/hid; mkdir -p "$HID" "$T/ok"; ln -s "$HID" "$T/lnk"
mk fakehid "$(jq --arg h "$HID" '.provider = "fakehid" | .dispatch.hidden_paths = {prefixes: [$h], shown: {write: ["clone", "out", "tmp"]}, note: "the sandbox mounts its own hid"}' "$LIB/fakecmd/definition.json")"
mk fakehidtmp "$(jq --arg h "$HID" '.provider = "fakehidtmp" | .dispatch.hidden_paths = {prefixes: [$h], note: "the sandbox binds nothing in"}' "$LIB/fakecmd/definition.json")"
verify_ro fakehid
setprov fakehid
out=$($DA local prepare --repo "$T/r" --base main --slug hd1 --scratch "$HID" --role review 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "this read-only run of fakehid" <<<"$out" && grep -qF "CLONE $HID/qargi.XXXXXX/clone lies under $HID" <<<"$out" \
  && grep -qF "CONTRACT $HID/qargi.XXXXXX/contract lies under $HID" <<<"$out" && grep -qF "GIT $HID/qargi.XXXXXX/git lies under $HID" <<<"$out" \
  && grep -qF '(dispatch.hidden_paths: the sandbox mounts its own hid)' <<<"$out" && grep -q 'Nothing was started: prepare the run again with --scratch on another filesystem' <<<"$out" \
  && [ -z "$(ls -A "$HID")" ]; } \
  && ok "hidden paths: prepare refuses a read-only run in a place the sandbox hides, naming each path, the prefix, the note and the fix, and makes nothing" \
  || no "hidden ro prepare: rc=$rc $out $(ls -A "$HID")"
out=$($DA local prepare --repo "$T/r" --base main --slug hd2 --scratch "$HID" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "CONTRACT $HID/qargi.XXXXXX/contract" <<<"$out" && grep -qF "GIT $HID/qargi.XXXXXX/git" <<<"$out" && ! grep -q '^  CLONE\|^  OUT\|^  TMP' <<<"$out" \
  && [ -z "$(ls -A "$HID")" ]; } \
  && ok "and a write run there: its class shows the clone, OUT and TMP, not the contract or the git wrapper" || no "hidden write prepare: rc=$rc $out"
out=$($DA local prepare --repo "$T/r" --base main --slug hd3 --scratch "$T/lnk" --role review 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "CONTRACT $HID/qargi.XXXXXX/contract lies under $HID" <<<"$out" && [ -z "$(ls -A "$HID")" ]; } \
  && ok "a --scratch that is a link into the hidden place is refused by its real path" || no "hidden link scratch: rc=$rc $out"
out=$(QARGI_RUN_TMP=$T/lnk $DA local prepare --repo "$T/r" --base main --slug hd4 --scratch "$T/ok" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^TMP=$T/lnk/qargi-run\." <<<"$out"; } && ok "a write run outside with its TMP in the hidden place is prepared: the class shows TMP" || no "hidden tmp, write: rc=$rc $out"
out=$(QARGI_RUN_TMP=$T/lnk $DA local prepare --repo "$T/r" --base main --slug hd5 --scratch "$T/ok" --role review 2>&1); rc=$?
[ "$rc" = 0 ] && ok "and so is a read-only one: a read-only member writes no TMP" || no "hidden tmp, read-only: rc=$rc $out"
setprov fakehidtmp; n0=$(ls "$T/ok" | wc -l)
out=$(QARGI_RUN_TMP=$T/lnk $DA local prepare --repo "$T/r" --base main --slug hd6 --scratch "$T/ok" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "TMP $T/lnk/qargi-run.XXXXXX (its real path $HID/qargi-run.XXXXXX) lies under $HID" <<<"$out" \
  && grep -q 'set QARGI_RUN_TMP to a directory on another filesystem' <<<"$out" && ! grep -q -- '--scratch on another' <<<"$out" && [ "$(ls "$T/ok" | wc -l)" = "$n0" ]; } \
  && ok "a write run whose sandbox does not show TMP is refused when TMP is hidden, by its real path, with the QARGI_RUN_TMP fix" || no "hidden tmp, not shown: rc=$rc $out"
# local run asks again: the runtime of the project may have changed since prepare (here: prepared on fakecmd, which hides nothing)
setprov fakecmd
eval "$($DA local prepare --repo "$T/r" --base main --slug hd8 --scratch "$HID" --role review | sed '/^$/,$d' | sed 's/^/export /')"; task
setprov fakehid
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "CONTRACT $RUN/contract lies under $HID" <<<"$out" && ! grep -q '^ARGV=' <<<"$out"; } && ok "local run refuses a read-only run in the hidden place (dry run)" || no "hidden ro run, dry: rc=$rc $out"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'Nothing was started' <<<"$out" && [ ! -e "$RUN/dispatch.json" ] && [ ! -e "$OUT/transcript" ]; } && ok "and a real one starts nothing" || no "hidden ro run: rc=$rc $out"
setprov fakecmd; eval "$($DA local prepare --repo "$T/r" --base main --slug hd9 --scratch "$HID" | sed '/^$/,$d' | sed 's/^/export /')"; task
setprov fakehid
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "GIT $RUN/git lies under $HID" <<<"$out" && ! grep -qF "CLONE $RUN" <<<"$out"; } && ok "and a write run there, for what its class does not show" || no "hidden write run: rc=$rc $out"
prep "$T/r" hd10 review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^ARGV=' <<<"$out"; } && ok "a read-only run of the same runtime outside the hidden place goes on" || no "hidden ro outside: rc=$rc $out"
setprov fakecmd

# --- the shipped codex runtime: the argv of each class comes from its data alone (a fake codex on PATH; nothing reaches the vendor) ----------
cp "$T/bin/fakellm" "$T/bin/codex"
setprov codex; prep "$T/r" cx1; task
out=$($DA local run "$RUN" --dry-run 2>"$T/err"); rc=$?
want=$(jq -nc --arg c "$CLONE" --arg o "$OUT" '["codex","exec","--json","--ephemeral","--ignore-rules","--strict-config","-C",$c,"-m","gpt-6.1-terra","-o","FINAL","--sandbox","workspace-write","--add-dir",$o,"--add-dir",($c + "/.git")]')
{ [ "$rc" = 0 ] && [ "$(arg0 <<<"$out" | finarg)" = "$want" ] && grep -qxF "COMMAND=$(realpath "$T/bin/codex")" <<<"$out" && grep -q '^PROMPT_VIA=stdin$' <<<"$out" && grep -q '^CLASS=write$' <<<"$out"; } \
  && ok "codex, write: codex exec in the clone, the balanced model, the last message to the run's own new file, the workspace-write sandbox with OUT and the clone's .git added" || no "codex write argv: rc=$rc [$(arg0 <<<"$out")] want [$want] $(cat "$T/err")"
# the clone's .git is a writable root of the sandbox: one an earlier run left as a link (to anywhere) refuses the run, so the grant never leaves the run
mv "$CLONE/.git" "$CLONE/.git.real"; ln -s "$CLONE/.git.real" "$CLONE/.git"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "$CLONE/.git ({clone}/.git in dispatch.argv of codex) passes through a link" <<<"$out" && ! grep -q '^ARGV=' <<<"$out"; } \
  && ok "codex: a clone whose .git is a link is refused before the sandbox is told to let the member write it" || no "codex .git link: rc=$rc $out"
rm -f "$CLONE/.git"; mv "$CLONE/.git.real" "$CLONE/.git"
out=$($DA local run "$RUN" --dry-run --model fast --effort max 2>&1); rc=$?
want=$(jq -nc --arg c "$CLONE" --arg o "$OUT" '["codex","exec","--json","--ephemeral","--ignore-rules","--strict-config","-C",$c,"-m","gpt-6-luna","-c","model_reasoning_effort=max","-o","FINAL","--sandbox","workspace-write","--add-dir",$o,"--add-dir",($c + "/.git")]')
{ [ "$rc" = 0 ] && [ "$(arg0 <<<"$out" | finarg)" = "$want" ] && ! grep -q '^NOTE=effort' <<<"$out"; } && ok "codex: a tier is passed as the catalog's id and an effort as -c model_reasoning_effort" || no "codex model and effort: rc=$rc [$(arg0 <<<"$out")] want [$want]"
if [ "$(command -v codex)" = "$T/bin/codex" ]; then out=$($DA local run "$RUN" 2>"$T/err"); rc=$?; else rc=x; out="the first codex on PATH is $(command -v codex), not the fake: the real run is not made"; : > "$T/err"; fi
{ [ "$rc" = 0 ] && grep -q '^ARG\[--sandbox\]$' "$OUT/transcript" && grep -q '^ARG\[workspace-write\]$' "$OUT/transcript" \
  && sed -n '/^STDIN-BEGIN/,/^STDIN-END/p' "$OUT/transcript" | grep -q 'TASK: change the thing'; } && ok "codex: a real run of the fake gets the argv as separate arguments and the prompt on its standard input" || no "codex run: rc=$rc $out $(cat "$T/err")"
{ grep -q '^USAGE=none: no line of the transcript is a usage report' <<<"$out" && [ "$(jq -c .usage.events "$RUN/dispatch.json")" = 0 ]; } \
  && ok "a transcript with no usage event says so (USAGE=none) and records 0 events" || no "usage none: $(grep '^USAGE' <<<"$out") $(jq -c .usage "$RUN/dispatch.json" 2>&1)"
out=$($DA local prepare --repo "$T/r" --base main --slug cxr0 --scratch "$T" --role review 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^RUN=' <<<"$out" && ! grep -q 'no-barrier' <<<"$out"; } \
  && ok "codex, read-only: its sandbox barrier is dated (partial), so prepare takes the review role with no acceptance" || no "codex ro prepare: rc=$rc $out"
prep "$T/r" cxr review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
want=$(jq -nc --arg c "$CLONE" '["codex","exec","--json","--ephemeral","--ignore-rules","--strict-config","-C",$c,"-m","gpt-6.1-terra","-o","FINAL","--sandbox","read-only"]')
{ [ "$rc" = 0 ] && [ "$(arg0 <<<"$out" | finarg)" = "$want" ] && grep -q '^CLASS=read-only$' <<<"$out" && ! grep -q -e '--add-dir' -e '[.]git' <<<"$(arg0 <<<"$out")" \
  && grep -q '^NOTE=codex has only a partial read-only barrier on local' <<<"$out"; } \
  && ok "codex, read-only: the read-only sandbox, no write group (no writable directory, the clone's .git included) and the partial barrier's note" || no "codex ro argv: rc=$rc [$(arg0 <<<"$out")] want [$want] $out"
# its sandbox hides /dev (here CXHID, the copy's place for it): a review run there would see neither its clone nor its contract, and a build run
# no contract; a run outside with only its TMP there (as prepare puts TMP on /dev/shm) is a run that works
mkdir -p "$CXHID"
out=$($DA local prepare --repo "$T/r" --base main --slug cxh1 --scratch "$CXHID" --role review 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "this read-only run of codex" <<<"$out" && grep -qF "CLONE $CXHID/qargi.XXXXXX/clone lies under $CXHID" <<<"$out" \
  && grep -q 'mounts a /dev of its own' <<<"$out" && [ -z "$(ls -A "$CXHID")" ]; } \
  && ok "codex: prepare refuses a review run where its sandbox hides the run, and makes nothing" || no "codex hidden ro: rc=$rc $out"
out=$($DA local prepare --repo "$T/r" --base main --slug cxh2 --scratch "$CXHID" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "CONTRACT $CXHID/qargi.XXXXXX/contract" <<<"$out" && ! grep -q '^  CLONE' <<<"$out"; } \
  && ok "codex: and a build run there, whose clone, OUT and TMP the sandbox binds in but whose contract it hides" || no "codex hidden write: rc=$rc $out"
for r in build review; do
  out=$(QARGI_RUN_TMP=$CXHID $DA local prepare --repo "$T/r" --base main --slug "cxh3$r" --scratch "$T" --role "$r" 2>&1); rc=$?
  [ "$rc" = 0 ] && ok "codex: a $r run on disk with its TMP in the hidden place is prepared" || no "codex hidden tmp $r: rc=$rc $out"
done
# a copy with the barrier's date removed (in the library, with no record either): the claim counts as none, so the review role needs the acceptance
mk codexundated "$(jq '.provider = "codexundated" | del(.resources.contract_addenda) | .capabilities.read_only_barrier.verified_on = null' "$CX")"
setprov codexundated
out=$($DA local prepare --repo "$T/r" --base main --slug cxu0 --scratch "$T" --role review 2>&1); rc=$?
{ [ "$rc" != 0 ] && grep -q 'qargi provider accept codexundated --surface local --no-barrier --project rproj' <<<"$out"; } \
  && ok "codex undated, read-only: the barrier counts as none and prepare refuses the review role with the accept command" || no "codex undated ro prepare: rc=$rc $out"
jq '.models.accept_no_barrier = {local: {by: "owner", at: "2026-11-11", reason: "test"}}' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
prep "$T/r" cxu review; task
jq 'del(.models.accept_no_barrier)' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'qargi provider accept codexundated --surface local --no-barrier --project rproj' <<<"$out" && ! grep -q '^ARGV=' <<<"$out"; } \
  && ok "and local run refuses it too, once the acceptance it was prepared under is gone" || no "codex undated ro: rc=$rc $out"
jq '.models.accept_no_barrier = {local: {by: "owner", at: "2026-11-11", reason: "test"}}' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
want=$(jq -nc --arg c "$CLONE" '["codex","exec","--json","--ephemeral","--ignore-rules","--strict-config","-C",$c,"-m","gpt-6.1-terra","-o","FINAL","--sandbox","read-only"]')
{ [ "$rc" = 0 ] && [ "$(arg0 <<<"$out" | finarg)" = "$want" ] && grep -q '^CLASS=read-only$' <<<"$out"; } \
  && ok "codex undated, read-only (accepted): the same read-only sandbox" || no "codex undated ro argv: rc=$rc [$(arg0 <<<"$out")] want [$want]"
jq 'del(.models.accept_no_barrier)' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
# copies in the library, attested: with the read-only group the barrier holds (partial, with its note); without it a read-only run is refused
mk codexro "$(jq '.provider = "codexro" | del(.resources.contract_addenda)' "$CX")"
mk codexnoro "$(jq '.provider = "codexnoro" | del(.resources.contract_addenda) | .dispatch.argv |= map(select((type == "object" and .class == "read-only") | not))' "$CX")"
verify_ro codexro; verify_ro codexnoro
setprov codexro; prep "$T/r" cxr2 review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(arg0 <<<"$out" | jq -c '.[-2:]')" = '["--sandbox","read-only"]' ] && grep -q '^NOTE=codexro has only a partial read-only barrier on local' <<<"$out"; } \
  && ok "codex attested, read-only: the run goes on with the read-only sandbox and the partial barrier's note" || no "codex ro attested: rc=$rc $out"
setprov codexnoro; prep "$T/r" cxr3 review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'sandbox-args but its dispatch supplies no read-only arguments' <<<"$out" && ! grep -q '^ARGV=' <<<"$out"; } \
  && ok "codex without its read-only sandbox group: a read-only run is refused, even attested" || no "codex ro without group: rc=$rc $out"
prep "$T/r" cxw3; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '"workspace-write"' <<<"$out"; } && ok "and its write run is not affected" || no "codex without group, write: rc=$rc $out"

# --- the run home of codex (dispatch.home): CODEX_HOME is RUN/home/.codex, the user's ~/.codex/auth.json is linked into it for the run only ---
# The fake codex says where CODEX_HOME is, whether auth.json is a link and the sha256 of what it reads through it (never the content), and
# does what $T/codex-mode says: replace the link by a file, or put a link to the user's ~/.codex in place of the run home.
cat > "$T/bin/codex" <<SH
#!/usr/bin/env bash
echo "CODEX_HOME=\${CODEX_HOME-unset}"
a=\${CODEX_HOME:-/nonexistent}/auth.json
if [ -L "\$a" ]; then echo AUTHLINK=yes; else echo AUTHLINK=no; fi
[ ! -f "\$a" ] || echo "AUTHSUM=\$(sha256sum < "\$a" | cut -c1-64)"
cat > /dev/null
# the events of codex exec --json: two turns report their usage (the second without one count and with a count that is not a number);
# a line that is not JSON and another event's usage are not counted; in the mode unreported, one turn reports two of the five counts
echo '{"type":"thread.started","thread_id":"t-1"}'
if [ "\$(cat "$T/codex-mode" 2>/dev/null)" = unreported ]; then
  echo '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}'
else
  echo '{"type":"turn.completed","usage":{"input_tokens":1200,"cached_input_tokens":200,"output_tokens":300,"reasoning_output_tokens":50}}'
  echo 'not a JSON line'
  echo '{"type":"item.completed","usage":{"input_tokens":99999,"output_tokens":99999}}'
  echo '{"type":"turn.completed","usage":{"input_tokens":800,"cached_input_tokens":100,"cache_write_input_tokens":7,"output_tokens":150,"reasoning_output_tokens":true}}'
fi
case \$(cat "$T/codex-mode" 2>/dev/null) in
  replace) rm -f "\$a"; echo 'sign-in-written-anew-v2' > "\$a";;
  through) echo 'sign-in-refreshed-in-place' > "\$a";;
  delete) rm -f "\$a";;
  race) src=\$(readlink "\$a"); echo 'sign-in-of-the-lead-meanwhile' > "\$src"; rm -f "\$a"; echo 'sign-in-written-anew-v3' > "\$a";;
  second) rm -f "\$a"; ln "$T/victim-h" "\$a";;
  big) rm -f "\$a"; head -c 1048600 /dev/zero | tr '\0' a > "\$a";;
  swap) src=\$(readlink "\$a"); mv "\$CODEX_HOME" "\$CODEX_HOME.moved"; ln -s "\$(dirname "\$src")" "\$CODEX_HOME";;
esac
exit 0
SH
chmod 755 "$T/bin/codex"
SECRET=sk-test-$RANDOM$RANDOM-marker
mkdir -p "$HOME/.codex"; printf '{"token": "%s"}\n' "$SECRET" > "$HOME/.codex/auth.json"
SUM=$(sha256sum < "$HOME/.codex/auth.json" | cut -c1-64)
setprov codex; prep "$T/r" hm1; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^HOME_ENV=CODEX_HOME$' <<<"$out" && grep -q "^HOME_DIR=$RUN/home/.codex\$" <<<"$out" && grep -q '^HOME_LINKS=auth.json$' <<<"$out"; } \
  && ok "codex dry run: the run home is named by CODEX_HOME, and HOME_LINKS names the link" || no "home dry run: rc=$rc $(grep '^HOME' <<<"$out")"
{ ! grep -q "$SECRET" <<<"$out" && ! grep -qF "$HOME/.codex" <<<"$out" && [ ! -e "$RUN/home/.codex" ]; } \
  && ok "the dry run prints no content and no source path of the link, and makes nothing" || no "home dry run printed or made: $(grep -nF -e "$SECRET" -e "$HOME/.codex" <<<"$out") $(ls -A "$RUN/home")"
out=$($DA local run "$RUN" 2>&1); rc=$?; tr=$OUT/transcript
{ [ "$rc" = 0 ] && grep -q "^CODEX_HOME=$RUN/home/.codex\$" "$tr" && grep -q '^AUTHLINK=yes$' "$tr" && grep -q "^AUTHSUM=$SUM\$" "$tr"; } \
  && ok "a codex run sees CODEX_HOME=RUN/home/.codex with auth.json a link to the user's file" || no "home run: rc=$rc $out $(grep -E '^(CODEX_HOME|AUTH)' "$tr")"
# the usage of the run (dispatch.output.usage): the two turn.completed events are added up, field by field
{ [ "$(jq -cS .usage "$RUN/dispatch.json")" = '{"events":2,"tokens":{"cache_write_input_tokens":7,"cached_input_tokens":300,"input_tokens":2000,"output_tokens":450,"reasoning_output_tokens":50}}' ] \
  && grep -q '^USAGE=input_tokens=2000 cached_input_tokens=300 cache_write_input_tokens=7 output_tokens=450 reasoning_output_tokens=50 (2 events)$' <<<"$out"; } \
  && ok "a codex run records the sum of its two turn.completed usages in dispatch.json and prints it as USAGE=" || no "usage: $(jq -c .usage "$RUN/dispatch.json") $(grep '^USAGE' <<<"$out")"
# a count no event reports is not recorded as 0: it is left out of tokens and named in unreported
echo unreported > "$T/codex-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -cS .usage "$RUN/dispatch.json")" = '{"events":1,"tokens":{"input_tokens":10,"output_tokens":2},"unreported":["cached_input_tokens","cache_write_input_tokens","reasoning_output_tokens"]}' ] \
  && grep -q '^USAGE=input_tokens=10 output_tokens=2 (1 event; not reported, so not counted: cached_input_tokens,cache_write_input_tokens,reasoning_output_tokens)$' <<<"$out"; } \
  && ok "a usage count no event reports is left out and named, never recorded as 0" || no "usage unreported: rc=$rc $(jq -c .usage "$RUN/dispatch.json") $(grep '^USAGE' <<<"$out")"
rm -f "$T/codex-mode"
{ [ ! -e "$RUN/home/.codex/auth.json" ] && [ ! -L "$RUN/home/.codex/auth.json" ] && [ "$(sha256sum < "$HOME/.codex/auth.json" | cut -c1-64)" = "$SUM" ]; } \
  && ok "the link is removed when the run ends, and the user's file is as it was" || no "home link left: $(ls -lA "$RUN/home/.codex")"
{ [ "$(jq -c .home "$RUN/dispatch.json")" = '{"dir":".codex","env":"CODEX_HOME","left":[],"links":["auth.json"],"not_linked":[]}' ] \
  && ! grep -q -e "$SECRET" -e "$HOME/.codex" "$RUN/dispatch.json" && ! grep -q "$SECRET" <<<"$out" && ! grep -qF "$HOME/.codex" <<<"$out"; } \
  && ok "dispatch.json records the link by name; neither it nor the output holds the content or the source path" || no "home record: $(jq -c .home "$RUN/dispatch.json") $out"
# what the runtime does to the link during the run (a sign-in refreshed) loses nothing, and no value reaches an output or a record
src_is() { [ "$(cat "$HOME/.codex/auth.json")" = "$1" ] && [ "$(stat -c %a "$HOME/.codex/auth.json")" = 600 ]; }
noval() { ! grep -q -e "$SECRET" -e 'sign-in-' <<<"$out" && ! grep -q -e "$SECRET" -e 'sign-in-' "$RUN/dispatch.json"; }
reset_src() { printf '{"token": "%s"}\n' "$SECRET" > "$HOME/.codex/auth.json"; chmod 600 "$HOME/.codex/auth.json"; }
reset_src; HD=$RUN/home/.codex
# an atomic replace (a file of its own renamed over the link), the source unchanged since the start: the file is written back, mode 600, no copy stays
echo replace > "$T/codex-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && src_is sign-in-written-anew-v2 && [ ! -e "$HD/auth.json" ] && [ ! -L "$HD/auth.json" ] && [ ! -e "$HD/auth.json.from-run" ] \
  && grep -q 'auth.json in the run home was replaced during the run by a file of its own (a sign-in written anew); the source was unchanged since the run started, so it now holds that file (mode 600)' <<<"$out" \
  && [ -z "$(find "$HOME/.codex" -name '.auth.json.qargi-*')" ] && noval; } \
  && ok "atomic replace: the runtime's new file is written back to the unchanged source (mode 600), the run home keeps no copy, no value is printed" || no "home replaced: rc=$rc $out $(ls -lA "$HD" "$HOME/.codex")"
# written through the link: the source keeps it, the link goes, a note says the source changed
reset_src; echo through > "$T/codex-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(cat "$HOME/.codex/auth.json")" = sign-in-refreshed-in-place ] && [ ! -L "$HD/auth.json" ] && [ ! -e "$HD/auth.json" ] \
  && grep -q 'the source of auth.json changed during the run (written through the link' <<<"$out" && noval; } \
  && ok "write-through: the source keeps what the runtime wrote through the link, the link is removed, with a note" || no "home through: rc=$rc $out"
# deleted: the source is untouched, a note says so
reset_src; echo delete > "$T/codex-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && src_is "{\"token\": \"$SECRET\"}" && grep -q 'auth.json was removed from the run home during the run (by the runtime or the member); its source is untouched' <<<"$out"; } \
  && ok "deleted: the source is untouched, with a note" || no "home delete: rc=$rc $out"
# an atomic replace while the source changed (you signed in again meanwhile): the source keeps yours, the runtime's file is kept as auth.json.from-run (mode 600)
reset_src; echo race > "$T/codex-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(cat "$HOME/.codex/auth.json")" = sign-in-of-the-lead-meanwhile ] && [ "$(cat "$HD/auth.json.from-run")" = sign-in-written-anew-v3 ] \
  && [ "$(stat -c %a "$HD/auth.json.from-run")" = 600 ] && [ ! -e "$HD/auth.json" ] \
  && grep -qF "it was not written back: the source changed since the run started (another sign-in, or another program). It is kept as $HD/auth.json.from-run (mode 600)" <<<"$out" && noval \
  && [ "$(jq -r '.home.left[0] | test("kept as")' "$RUN/dispatch.json")" = true ]; } \
  && ok "replace while the source changed: the source keeps the newer one, the runtime's file is kept as auth.json.from-run (mode 600) and said" || no "home race: rc=$rc $out $(ls -lA "$HD")"
out=$($DA local list 2>&1)
grep -qF "  residue: $HD/auth.json.from-run (a file the runtime wrote in place of the link, not written back to its source: compare it with your own)" <<<"$out" \
  && ok "local list names the kept file" || no "list kept: $out"
rm -f "$HD/auth.json.from-run"
# a second name of another file in place of the link: the name is removed, the file and the source untouched
reset_src; echo precious > "$T/victim-h"; echo second > "$T/codex-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(cat "$T/victim-h")" = precious ] && [ "$(stat -c %h "$T/victim-h")" = 1 ] && src_is "{\"token\": \"$SECRET\"}" && [ ! -e "$HD/auth.json" ] \
  && grep -q 'replaced during the run by a second name of another file; the name is removed' <<<"$out"; } \
  && ok "a second name of another file in place of the link: the name is removed, nothing is written back" || no "home second: rc=$rc $out"
# over the bound: kept, not written back
reset_src; echo big > "$T/codex-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && src_is "{\"token\": \"$SECRET\"}" && [ -f "$HD/auth.json.from-run" ] && grep -q 'not written back: it is over 1048576 bytes' <<<"$out"; } \
  && ok "a file over 1 MiB in place of the link is kept, not written back" || no "home big: rc=$rc $out"
rm -f "$HD/auth.json.from-run" "$T/victim-h"; reset_src
# a CODEX_HOME of yours that is another directory: said, the value never printed
out=$(CODEX_HOME=$T/my-codex-home $DA local run "$RUN" --dry-run 2>&1)
{ grep -q '^NOTE=CODEX_HOME is set in your environment to another directory than the one the run home.s links come from (~/.codex): the run links ~/.codex/auth.json from there' <<<"$out" \
  && ! grep -q 'my-codex-home' <<<"$out"; } && ok "a CODEX_HOME of yours elsewhere is a note, without its value" || no "codex home note: $out"
out=$(CODEX_HOME=$HOME/.codex $DA local run "$RUN" --dry-run 2>&1)
! grep -q '^NOTE=CODEX_HOME is set' <<<"$out" && ok "a CODEX_HOME that is ~/.codex is no note" || no "codex home same: $out"
# a member puts a link to the user's ~/.codex in place of the run home and moves the run home: the end of the run removes nothing through the link,
# and finds the link it made where the run home was moved, under RUN/home
echo swap > "$T/codex-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(sha256sum < "$HOME/.codex/auth.json" | cut -c1-64)" = "$SUM" ] && grep -q 'not the directory the run made (a link the member put there, left in place and not followed)' <<<"$out" \
  && grep -qF "the link qargi made was found under $RUN/home and removed: $RUN/home/.codex.moved/auth.json" <<<"$out" && [ ! -L "$RUN/home/.codex.moved/auth.json" ]; } \
  && ok "a run home replaced by a link to the user's directory: nothing is removed through it, the user's file stays, the moved link is found and removed" || no "home swap: rc=$rc $out; source $(ls -l "$HOME/.codex" 2>&1)"
rm -f "$RUN/home/.codex"; rm -rf "$RUN/home/.codex.moved"; rm -f "$T/codex-mode"
# what a member left in the run directory before the run: a link in place of the run home is not followed, a file in place of the link is not replaced
mkdir -p "$T/elsewhere"; ln -s "$T/elsewhere" "$RUN/home/.codex"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'not a plain directory of the run' <<<"$out" && [ -z "$(ls -A "$T/elsewhere")" ] && ! grep -q Traceback <<<"$out"; } \
  && ok "a run home that is a link is refused, nothing is made where it points" || no "home planted link: rc=$rc $out $(ls -A "$T/elsewhere")"
rm -f "$RUN/home/.codex"; mkdir -p "$RUN/home/.codex"; echo planted > "$RUN/home/.codex/auth.json"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'is not a link qargi made' <<<"$out" && [ "$(cat "$RUN/home/.codex/auth.json")" = planted ]; } \
  && ok "a file in place of the link is refused and left alone" || no "home planted file: rc=$rc $out"
rm -f "$RUN/home/.codex/auth.json"
# the source: absent (signed out: no link, a note), or a link into a credential store (refused, the message names no path)
mv "$HOME/.codex/auth.json" "$HOME/.codex/auth.keep"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^HOME_LINKS=$' <<<"$out" && grep -q "^NOTE=the source of the run home's link 'auth.json' does not exist" <<<"$out"; } \
  && ok "a source that does not exist is not linked, with a note (the runtime starts signed out)" || no "home missing source: rc=$rc $(grep -E '^(HOME|NOTE)' <<<"$out")"
mkdir -p "$HOME/.ssh"; echo key > "$HOME/.ssh/id_test"; ln -s "$HOME/.ssh/id_test" "$HOME/.codex/auth.json"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q "the source of 'auth.json' is refused: it resolves into qargi's own directories or a credential store" <<<"$out" && ! grep -qF "$HOME" <<<"$out" && [ ! -e "$RUN/home/.codex/auth.json" ]; } \
  && ok "a source that is a link into the user's ssh keys is refused, without naming where it resolves" || no "home source into .ssh: rc=$rc $out"
rm -f "$HOME/.codex/auth.json"; rm -rf "$HOME/.ssh"; mv "$HOME/.codex/auth.keep" "$HOME/.codex/auth.json"
# a definition whose run home breaks a rule is refused before anything runs (the rules are provider.home_problems, tested in test_provider.py)
mk codexbad "$(jq '.provider = "codexbad" | del(.resources.contract_addenda) | .dispatch.home.link[0].from = "~/.ssh/id_ed25519"' "$CX")"
setprov codexbad; prep "$T/r" hm2; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q "never linked into a run: the user's ssh keys" <<<"$out" && ! grep -q '^ARGV=' <<<"$out"; } && ok "a run home that links an ssh key is refused" || no "home bad definition: rc=$rc $out"

# --- the configuration file of a codex run (dispatch.run_config): CODEX_HOME/config.toml in the run home, with the baseline of the definition in every
# run and, for the run's role (the lead's registry) and class, the tools a member may call in each server's enabled_tools. The dry run names the file,
# the tools and the baseline. A run with no MCP server and a run with one get the same settings.
tomljson() { python3 -I -c 'import json, sys, tomllib; print(json.dumps(tomllib.load(open(sys.argv[1], "rb")), sort_keys=True))' "$1"; }
BASE=$(jq -cS .dispatch.run_config.baseline lib/providers/codex.json)
settings() { tomljson "$1" | jq -cS 'del(.mcp_servers)'; }     # what the file sets besides the MCP servers
setprov codex; prep "$T/r" mc1; task
CFG=$RUN/home/.codex/config.toml
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^RUN_CONFIG=$CFG\$" <<<"$out" && grep -q '^RUN_CONFIG_TOOLS=$' <<<"$out" && [ "$(sed -n 's/^RUN_CONFIG_BASELINE=//p' <<<"$out" | jq -cS .)" = "$BASE" ]; } \
  && ok "codex with no tool pack: the dry run names CODEX_HOME/config.toml, no tool, and the baseline" || no "no mcp dry: rc=$rc $(grep '^RUN_CONFIG' <<<"$out")"
mkdir -p "$RUN/home/.codex"; printf '[mcp_servers.left]\nurl = "https://left.example.net"\n[projects."/x"]\ntrust_level = "trusted"\n' > "$CFG"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(tomljson "$CFG" | jq -cS .)" = "$BASE" ] && [ "$(stat -c %a "$CFG")" = 600 ] \
  && [ "$(jq -cS .run_config "$RUN/dispatch.json")" = "$(jq -ncS --arg f "$CFG" --argjson b "$BASE" '{file:$f,role:"build",tools:[],baseline:$b}')" ]; } \
  && ok "and the run writes the baseline alone over what an earlier run or a member left there (no server, no trust entry)" || no "no mcp run: rc=$rc $out $(cat "$CFG")"
NOMCP=$(settings "$CFG")
jq -e '.approval_policy == "never" and .sandbox_workspace_write.network_access == false and .sandbox_workspace_write.exclude_slash_tmp == true
  and .web_search == "disabled" and .features.hooks == false and .features.apps == false and .features.plugins == false and .skills.bundled.enabled == false
  and (has("projects") | not)' <<<"$NOMCP" >/dev/null \
  && ok "the baseline: no approval asked, no shell network, no slash-tmp, no hosted search, hooks, apps, plugins or bundled skills, no trust entry" || no "baseline keys: $NOMCP"
printf '%s' '{"name":"cx","url":"https://mcp.example.net/cx-endpoint","vault_ids":["vlt_runtest"],"write_ok":true,"tools":{"platform.list_items":"always_allow","getStatus":"always_allow","repo/push":"auto","issue-close":"always_ask"}}' > "$T/cx.json"
ctok=$($DA tool import "$T/cx.json" --compatible any | tok_of); $DA tool import "$T/cx.json" --compatible any --plan "$ctok" --approved test >/dev/null || no "import cx"
$DA tool link cx --scope project --project rproj >/dev/null || no "link cx"
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^RUN_CONFIG=$CFG\$" <<<"$out" && grep -q '^RUN_CONFIG_TOOLS=mcp__cx__getStatus,mcp__cx__platform_list_items,mcp__cx__repo_push$' <<<"$out" \
  && ! grep -q -e 'cx-endpoint' -e 'vlt_runtest' <<<"$out" && [ "$(arg0 <<<"$out" | jq -c 'map(select(test("config[.]toml") or . == "-p")) | length')" = 0 ]; } \
  && ok "codex, write: the dry run names CODEX_HOME/config.toml and the tools a member may call (not the always_ask one), never the server's address" || no "mcp dry: rc=$rc $out"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
want='{"cx":{"enabled_tools":["getStatus","platform.list_items","repo/push"],"url":"https://mcp.example.net/cx-endpoint"}}'
{ [ "$rc" = 0 ] && [ "$(tomljson "$CFG" | jq -cS .mcp_servers)" = "$want" ] && [ "$(stat -c %a "$CFG")" = 600 ] && grep -q "^CODEX_HOME=$RUN/home/.codex\$" "$OUT/transcript" \
  && [ "$(jq -cS 'del(.baseline)' <<<"$(jq -c .run_config "$RUN/dispatch.json")")" = "$(jq -ncS --arg f "$CFG" '{file:$f,role:"build",tools:["mcp__cx__getStatus","mcp__cx__platform_list_items","mcp__cx__repo_push"]}')" ] \
  && ! grep -q 'cx-endpoint' "$RUN/dispatch.json"; } \
  && ok "codex, write: the run's CODEX_HOME/config.toml lists the role's tools in enabled_tools, mode 600; dispatch.json records the names only" || no "mcp run: rc=$rc $out; $(cat "$CFG" 2>&1); $(jq -c .run_config "$RUN/dispatch.json")"
[ "$(settings "$CFG")" = "$NOMCP" ] && ok "a run with an MCP server gets the same settings, key for key, as the run with none" || no "settings differ with mcp: $(settings "$CFG") vs $NOMCP"
# the raw tool names stay raw in enabled_tools (a dot, a slash, a hyphen); the names the model is given are the mcp__ form of resources.mcp.permission_rule
{ tomljson "$CFG" | jq -e '.mcp_servers.cx.enabled_tools | index("platform.list_items") and index("repo/push")' >/dev/null \
  && ! tomljson "$CFG" | grep -q 'mcp__' && [ "$(jq -c .run_config.tools "$RUN/dispatch.json")" = '["mcp__cx__getStatus","mcp__cx__platform_list_items","mcp__cx__repo_push"]' ]; } \
  && ok "enabled_tools holds the server's own names; dispatch.json the mcp__ names, with every other character written as _" || no "raw vs native names: $(cat "$CFG")"
# a link a member put in place of the file is replaced, not written through
echo precious > "$T/victim2"; rm -f "$CFG"; ln -s "$T/victim2" "$CFG"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(cat "$T/victim2")" = precious ] && [ ! -L "$CFG" ] && [ "$(tomljson "$CFG" | jq -cS .mcp_servers)" = "$want" ]; } \
  && ok "a link in place of the run's MCP file is replaced by the file, and what it pointed to is untouched" || no "mcp planted link: rc=$rc $out; victim=$(cat "$T/victim2")"
# the read-only class: the declared reads only
jq '.models.accept_no_barrier = {local: {by: "owner", at: "2026-11-11", reason: "test"}}' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
prep "$T/r" mc2 review; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^RUN_CONFIG_TOOLS=mcp__cx__getStatus,mcp__cx__platform_list_items$' <<<"$out"; } \
  && ok "codex, read-only: the run's MCP file lists only the declared reads (no auto tool, no write-like one)" || no "mcp ro dry: rc=$rc $(grep '^RUN_CONFIG' <<<"$out")"
out=$($DA local run "$RUN" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(tomljson "$RUN/home/.codex/config.toml" | jq -c '.mcp_servers.cx.enabled_tools')" = '["getStatus","platform.list_items"]' ] \
  && [ "$(settings "$RUN/home/.codex/config.toml")" = "$NOMCP" ] \
  && ok "and the file the read-only run gets holds just those, with the same settings as a write run" || no "mcp ro run: rc=$rc $out"
# the role is the lead's registry's, never the run's own ability file
prep "$T/r" mc3 review; task; echo build > "$RUN/ability"
out=$($DA local run "$RUN" --dry-run 2>&1)
grep -q '^RUN_CONFIG_TOOLS=mcp__cx__getStatus,mcp__cx__platform_list_items$' <<<"$out" && ok "an ability file rewritten in the run directory does not change the tools of the run" || no "mcp role source: $(grep '^RUN_CONFIG' <<<"$out")"
jq 'del(.models.accept_no_barrier)' "$T/c/projects/rproj.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/rproj.json"
# --- a Codex member gets no qargi skill: the lead's skills, linked where a Codex lead session finds them (~/.codex/skills, ~/.agents/skills, and
# untracked in the lead's checkout under .agents/skills), are in none of the places Codex reads skills from in a run (CODEX_HOME/skills, HOME/.agents/skills,
# the clone's .agents/skills), and the run's configuration turns the bundled skills off. The fake codex lists every skill it could load.
mkdir -p "$T/skillbin" "$HOME/.codex/skills" "$HOME/.agents/skills" "$T/r/.agents/skills"
ln -s "$PWD/skills/qargi-flow" "$HOME/.codex/skills/qargi-flow"; ln -s "$PWD/skills/qargi-verify" "$HOME/.agents/skills/qargi-verify"
ln -s "$PWD/skills/qargi-task" "$T/r/.agents/skills/qargi-task"
cat > "$T/skillbin/codex" <<'SH'
#!/usr/bin/env bash
cat > /dev/null
for d in "$CODEX_HOME/skills" "$HOME/.agents/skills" "$PWD/.agents/skills"; do
  for s in "$d"/*/SKILL.md; do [ ! -f "$s" ] || echo "SKILL=$s"; done
done
echo "SKILLROOTS-CHECKED"
SH
chmod 755 "$T/skillbin/codex"
setprov codex; prep "$T/r" sk1; task
out=$(PATH=$T/skillbin:$PATH $DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^SKILLROOTS-CHECKED$' "$OUT/transcript" && ! grep -q '^SKILL=' "$OUT/transcript" && [ ! -e "$CLONE/.agents" ] \
  && [ "$(tomljson "$RUN/home/.codex/config.toml" | jq -c .skills)" = '{"bundled":{"enabled":false}}' ]; } \
  && ok "a codex member sees no skill of the lead (qargi-flow, qargi-verify, qargi-task), and its bundled skills are off" || no "member skills: rc=$rc $(grep -E '^SKILL' "$OUT/transcript")"
rm -rf "$T/skillbin" "$HOME/.codex/skills" "$HOME/.agents" "$T/r/.agents"
# the same file for a runtime that takes it by a flag: in run, RUN/config/FILE, and {run_config} in its argv (no flag without a tool)
mk fakecfg "$(jq -n --argjson m "$M" '{schema:2,kind:"provider",provider:"fakecfg",family:null,surface:"local",models:$m,capabilities:{},agents:null,barrier:{kind:"none"},
  resources:{mcp:{file:"mcp.json",format:"json",root_pointer:"/servers",entry:{type:"http",url:"{url}"},permission_rule:"mcp__{server}__{tool}",name_key:"nonword-underscore",tool_lists:{allow:"/allow",deny:"/deny"}}},
  dispatch:{mode:"command",argv:["fakellm",{"if":"run_config","then":["--mcp-file","{run_config}"]},"--out","{out}"],prompt:{via:"stdin"},output:{format:"text"},run_config:{in:"run",file:"mcp.json"}}}')"
setprov fakecfg; prep "$T/r" mc4; task
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^ARG\[--mcp-file\]$" "$OUT/transcript" && grep -q "^ARG\[$RUN/config/mcp.json\]$" "$OUT/transcript" \
  && [ "$(jq -c '.servers.cx | [.allow, .deny, .url]' "$RUN/config/mcp.json")" = '[["getStatus","platform.list_items","repo/push"],["issue-close"],"https://mcp.example.net/cx-endpoint"]' ]; } \
  && ok "another runtime: the file goes to RUN/config in its own format with its allow and deny lists, and {run_config} passes its path" || no "fakecfg: rc=$rc $out $(cat "$RUN/config/mcp.json" 2>&1)"
# with a baseline (dispatch.run_config.baseline) the file always holds the definition's settings, with or without a server: the same settings either way
mk fakecfgb "$(jq '.provider = "fakecfgb" | .dispatch.run_config.baseline = {ask: "never", net: {on: false, roots: ["a"]}}' "$LIB/fakecfg/definition.json")"
setprov fakecfgb; prep "$T/r" mc5; task
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -cS '[.ask, .net, (.servers | keys)]' "$RUN/config/mcp.json")" = '["never",{"on":false,"roots":["a"]},["cx"]]' ] \
  && [ "$(jq -cS .run_config.baseline "$RUN/dispatch.json")" = '{"ask":"never","net":{"on":false,"roots":["a"]}}' ]; } \
  && ok "a baseline: the run's file holds the settings beside the servers, and dispatch.json records them" || no "baseline with mcp: rc=$rc $out $(cat "$RUN/config/mcp.json" 2>&1)"
withmcp=$(jq -cS 'del(.servers)' "$RUN/config/mcp.json")
$DA tool unlink cx --scope project --project rproj >/dev/null
out=$($DA local run "$RUN" --dry-run 2>&1)
{ grep -q -- '"--mcp-file"' <<<"$(arg0 <<<"$out")" && grep -q "^RUN_CONFIG=$RUN/config/mcp.json\$" <<<"$out" && grep -q '^RUN_CONFIG_TOOLS=$' <<<"$out" \
  && grep -q '^RUN_CONFIG_BASELINE={"ask":"never","net":{"on":false,"roots":\["a"\]}}$' <<<"$out"; } \
  && ok "a baseline and no tool for the role: the dry run still names the file, and prints the baseline" || no "baseline dry: $out"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -cS . "$RUN/config/mcp.json")" = "$withmcp" ] && [ "$(jq -c .run_config.tools "$RUN/dispatch.json")" = '[]' ]; } \
  && ok "and the run writes the baseline alone, the same settings the run with a server got" || no "baseline no mcp: rc=$rc $out $(cat "$RUN/config/mcp.json" 2>&1)"
setprov fakecfg; prep "$T/r" mc6; task
out=$($DA local run "$RUN" --dry-run 2>&1)
{ ! grep -q -- '--mcp-file' <<<"$(arg0 <<<"$out")" && grep -q '^RUN_CONFIG=none' <<<"$out" && ! grep -q '^RUN_CONFIG_BASELINE=' <<<"$out"; } && ok "and without a baseline or a tool for the role the flag is left out" || no "fakecfg none: $out"
rm -rf "$HOME/.codex"
rm -f "$T/bin/codex"
# without the fake, the first codex on PATH is the stub of tests/hermetic.sh: a real codex installed on the machine never runs in a test
out=$(codex exec 2>&1); rc=$?
{ [ "$(command -v codex)" = "$HERMETIC/bin/codex" ] && [ "$rc" = 127 ] && grep -q 'the real codex is not available' <<<"$out"; } \
  && ok "with no fake, codex is the hermetic stub, which fails" || no "codex stub: $(command -v codex) rc=$rc $out"
setprov fakecmd

# --- the member's last message ({final_message}): codex writes it to a new private file of the run, which the lead checks and publishes as OUT/report.md ---
# The fake codex does what $T/fin-mode says with the file -o names (and, with outlink, first plants a link to the victim as OUT/report.md, as a write member can).
cat > "$T/bin/codex" <<SH
#!/usr/bin/env bash
cat > /dev/null
o='' od=''
while [ \$# -gt 0 ]; do case \$1 in -o) o=\$2;; --add-dir) od=\$2;; esac; shift; done
echo "FINAL=\$o"
for m in \$(cat "$T/fin-mode" 2>/dev/null); do
  case \$m in
    report) printf '# Findings\n\nnone\n\n# Checked\n\nls (exit 0)\n\nverdict: accept\n' > "\$o";;
    second) printf '# Findings\n\nthe second run\n\nverdict: revise\n' > "\$o";;
    empty) : > "\$o";;
    link) ln -s "$T/victim3" "\$o";;
    hard) ln "$T/victim3" "\$o";;
    fifo) mkfifo "\$o";;
    dir) mkdir "\$o"; echo inner > "\$o/inner";;
    big) head -c 1048600 /dev/zero | tr '\0' a > "\$o";;
    binary) printf 'a\0b\n' > "\$o";;
    outlink) rm -f "\$od/report.md"; ln -s "$T/victim3" "\$od/report.md";;
    fail) exit 7;;
  esac
done
exit 0
SH
chmod 755 "$T/bin/codex"
echo precious > "$T/victim3"
fin() { printf '%s\n' "$1" > "$T/fin-mode"; }
finrun() { out=$($DA local run "$RUN" "$@" 2>&1); rc=$?; }
victim_ok() { [ "$(cat "$T/victim3")" = precious ] && [ "$(stat -c %h "$T/victim3")" = 1 ]; }
nostage() { [ -z "$(find "$RUN" -maxdepth 1 -name 'final.*' 2>/dev/null)" ]; }
setprov codex; prep "$T/r" fm1; task
out=$($DA local run "$RUN" --dry-run 2>&1); rc=$?
fp=$(arg0 <<<"$out" | jq -r '.[(index(["-o"]) + 1)]')
{ [ "$rc" = 0 ] && [[ $fp =~ ^$RUN/final\.[0-9a-f]{12}/message\.md$ ]] && grep -qF "FINAL_MESSAGE=$fp (its directory is made new when the run starts; the file is published as $OUT/report.md)" <<<"$out" && nostage; } \
  && ok "codex -o names a new file of the run, never one of OUT; the dry run names it and makes nothing" || no "final dry: rc=$rc [$fp] $out"
fin report; finrun
fp=$(jq -r '.argv[(.argv | index(["-o"])) + 1]' "$RUN/dispatch.json" 2>/dev/null)
{ [ "$rc" = 0 ] && grep -qxF "FINAL=$fp" "$OUT/transcript" && [[ $fp == "$RUN"/final.* ]] && [ -f "$OUT/report.md" ] && [ ! -L "$OUT/report.md" ] && grep -q '^verdict: accept$' "$OUT/report.md" \
  && grep -q "^REPORT=$OUT/report.md ([0-9]* bytes: the member's last message)\$" <<<"$out" && ! grep -q '^PREVIOUS_REPORT=' <<<"$out" && nostage \
  && [ "$(jq -c '.report | [.state, .previous, .report, .final_message]' "$RUN/dispatch.json")" = "$(jq -nc --arg r "$OUT/report.md" --arg f "$fp" '["published","none",$r,$f]')" ]; } \
  && ok "the last message is published as OUT/report.md, its directory removed; dispatch.json records it" || no "final published: rc=$rc $out $(jq -c .report "$RUN/dispatch.json" 2>&1)"
[ "$(stat -c %a "$OUT/report.md")" = 644 ] && ok "the published report is mode 644" || no "report mode $(stat -c %a "$OUT/report.md")"
fin second; finrun --again
{ [ "$rc" = 0 ] && grep -q 'the second run' "$OUT/report.md" && [ ! -e "$OUT/report.md.previous" ] && grep -q '^PREVIOUS_REPORT=replaced' <<<"$out" && [ "$(jq -r .report.previous "$RUN/dispatch.json")" = replaced ]; } \
  && ok "--again with a new report: the earlier one is replaced, and the output says so" || no "final replaced: rc=$rc $out"
fin fail; finrun --again
{ [ "$rc" = 1 ] && [ ! -e "$OUT/report.md" ] && grep -q 'the second run' "$OUT/report.md.previous" && grep -q '^REPORT=none: the runtime wrote no last message' <<<"$out" \
  && grep -qF "PREVIOUS_REPORT=kept as $OUT/report.md.previous: this run published no report" <<<"$out" && [ "$(jq -c '.report | [.state, .previous]' "$RUN/dispatch.json")" = '["none","kept"]' ] && nostage; } \
  && ok "a failed rerun with no last message leaves no report.md: the earlier one is kept as report.md.previous, and the output and dispatch.json say so" || no "final failed rerun: rc=$rc $out $(ls -A "$OUT")"
fin report; finrun --again
{ [ "$rc" = 0 ] && [ -f "$OUT/report.md" ] && [ ! -e "$OUT/report.md.previous" ] && grep -q '^PREVIOUS_REPORT=replaced' <<<"$out"; } && ok "the next run that publishes a report replaces the set-aside one, and says so" || no "final after kept: rc=$rc $out $(ls -A "$OUT")"
# what the runtime (or a member) leaves at the private file instead of a report: never followed, published or waited on; a name only is removed
for m in link hard fifo dir empty big binary; do
  fin "$m"; finrun --again
  case $m in empty) why='is empty';; link) why='is a link';; hard) why='has another name';; fifo) why='is a pipe';; dir) why='is a directory';; big) why='is over 1048576 bytes';; binary) why='is not text';; esac
  { [ "$rc" = 0 ] && victim_ok && [ ! -e "$OUT/report.md" ] && [ ! -L "$OUT/report.md" ] && grep -q "^REPORT=none: .*$why" <<<"$out" && [ -f "$OUT/report.md.previous" ] \
    && grep -q '^PREVIOUS_REPORT=kept' <<<"$out" && ! grep -q Traceback <<<"$out"; } \
    && ok "a final message that $why is not published, the earlier report is kept aside, a file it points to is untouched" || no "final $m: rc=$rc $out; victim=$(cat "$T/victim3") $(ls -A "$OUT")"
  case $m in
    dir) [ -d "$(jq -r .report.final_message "$RUN/dispatch.json")" ] && ok "a directory there is left in place" || no "final dir removed";;
    big|binary) { kp=$(jq -r .report.kept "$RUN/dispatch.json"); [ -f "$kp" ] && grep -q 'kept for you to read' <<<"$out"; } && ok "a file of its own that $why is kept for the lead to read" || no "final $m not kept: $(jq -c .report "$RUN/dispatch.json")";;
    *) nostage && ok "the name is removed with its directory" || no "final $m stage left: $(ls -A "$RUN")";;
  esac
  rm -rf "$RUN"/final.*; fin report; finrun --again   # a published report again, for the next case to set aside
done
# a link a write member planted as OUT/report.md during the run is replaced by the published report, never written through
fin "outlink report"; finrun --again
{ [ "$rc" = 0 ] && victim_ok && [ -f "$OUT/report.md" ] && [ ! -L "$OUT/report.md" ] && grep -q '^verdict: accept$' "$OUT/report.md"; } \
  && ok "a link planted as OUT/report.md during the run is replaced by the report; what it points to is untouched" || no "final outlink: rc=$rc $out; victim=$(cat "$T/victim3")"
# what is left as OUT/report.md before a run, other than a report of its own, refuses the run before anything starts
for m in link hard fifo dir; do
  rm -rf "$OUT/report.md"
  case $m in
    link) ln -s "$T/victim3" "$OUT/report.md"; what='link';; hard) ln "$T/victim3" "$OUT/report.md"; what='second name of a file';;
    fifo) mkfifo "$OUT/report.md"; what='pipe';; dir) mkdir "$OUT/report.md"; what='directory';;
  esac
  cp "$RUN/dispatch.json" "$T/dispatch.keep"
  fin report; out=$(timeout 30 $DA local run "$RUN" --again 2>&1); rc=$?
  { [ "$rc" = 2 ] && grep -qF "the report of an earlier run ($OUT/report.md) is not a plain file of its own" <<<"$out" && [ "$(cat "$T/victim3")" = precious ] && cmp -s "$RUN/dispatch.json" "$T/dispatch.keep" && nostage; } \
    && ok "an OUT/report.md that is a $what refuses the run before anything starts; nothing is written through it" || no "report.md $m: rc=$rc $out; victim=$(cat "$T/victim3")"
done
rm -rf "$OUT/report.md" "$T/fin-mode" "$T/victim3" "$T/dispatch.keep"
rm -f "$T/bin/codex"

# --- a read-only run whose report is the runtime's last message is packaged by the lead: report.md and the minimal manifest, from the run's record ---
# End to end with the conformance stub of codex in place of the command (its last message is a review report with Findings and a verdict), on the
# attested copy codexro: what the stub writes is chosen by $T/stub-final (a file, or empty for none); $T/stub-patch makes it leave a patch in OUT.
STUBX=$PWD/tests/providers/codex/stub
cat > "$T/bin/codex" <<SH
#!/usr/bin/env bash
c='' a=("\$@")
while [ \$# -gt 0 ]; do [ "\$1" = -C ] && c=\$2; shift; done
if [ -f "$T/stub-patch" ]; then mkdir -p "\$(dirname "\$c")/out/patches"; printf 'From 0 Mon Sep 17 00:00:00 2001\nSubject: [PATCH] x\n\nx\n' > "\$(dirname "\$c")/out/patches/0001-x.patch"; fi
if [ -f "$T/stub-final" ]; then QARGI_STUB_FINAL=\$(cat "$T/stub-final"); export QARGI_STUB_FINAL; fi
exec "$STUBX" "\${a[@]}"
SH
chmod 755 "$T/bin/codex"
setprov codexro; prep "$T/r" pk1 review; task
BSHA=$(git -C "$T/r" rev-parse main)
out=$($DA local run "$RUN" --effort low 2>&1); rc=$?
{ [ "$rc" = 0 ] && cmp -s tests/providers/codex/final-message.md "$OUT/report.md" && grep -q "^MANIFEST=$OUT/manifest.json (written by the lead: status DONE" <<<"$out" \
  && [ "$(jq -r .manifest.state "$RUN/dispatch.json")" = written ]; } && ok "e2e: a read-only codex run (the stub) returns its report as OUT/report.md and the lead writes OUT/manifest.json" || no "e2e run: rc=$rc $out"
jq -e --arg b "$BSHA" --arg id "${RUN##*/}" '.status == "DONE" and .commits == [] and .gates == [] and .done.exit_code == null and .touched_paths == [] and .scope == []
  and .base == {branch: "main", sha: $b} and .artifacts == [{path: "report.md", kind: "report"}] and (has("verdict") | not)
  and .run.id == $id and .run.role == "review" and .run.runtime == "codexro" and .run.class == "read-only" and .run.model == "gpt-6.1-terra"
  and .run.effort == "low" and .run.effort_native == "low" and .run.outcome == "ok" and .run.exit == 0 and .run.packaged_by == "qargi local run"' "$OUT/manifest.json" >/dev/null \
  && ok "the manifest is the minimal report-only one, with the run's id, role, runtime, class, model, effort and base from the lead's record; no test, no verdict" || no "e2e manifest: $(cat "$OUT/manifest.json")"
out=$($DA local verify "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && ! grep -q 'holds no report' <<<"$out"; } && ok "e2e: qargi local verify passes" || no "e2e verify: rc=$rc $out"
out=$($DA review check "$OUT" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^OK report-only run: report.md holds a Findings section and ends with its verdict' <<<"$out"; } && ok "e2e: qargi review check passes the package" || no "e2e review check: rc=$rc $out"
pkrun=$RUN
out=$($DA local clean "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$pkrun" ]; } && ok "e2e: qargi local clean closes it" || no "e2e clean: rc=$rc $out"
# a rerun that returns no report leaves neither the report nor the lead's manifest of the earlier run as this run's
prep "$T/r" pk2 review; task
out=$($DA local run "$RUN" 2>&1); rc=$?; [ "$rc" = 0 ] && [ -f "$OUT/manifest.json" ] || no "pk2 first run: rc=$rc $out"
: > "$T/stub-final"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$OUT/report.md" ] && [ ! -e "$OUT/manifest.json" ] && [ -f "$OUT/report.md.previous" ] && [ -f "$OUT/manifest.json.previous" ] \
  && grep -q '^MANIFEST=none: no report was published' <<<"$out" && grep -q '^PREVIOUS_MANIFEST=kept as' <<<"$out" && grep -q '^PREVIOUS_REPORT=kept as' <<<"$out"; } \
  && ok "missing report: no manifest is written, and the earlier report and manifest are set aside, not taken for this run's" || no "pk2 missing: rc=$rc $out $(ls -A "$OUT")"
out=$($DA review check "$OUT" 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q 'FAIL no patches found in .*, and no report.md (or PREFIXreport.md) with a Findings section' <<<"$out"; } && ok "missing report: review check fails as before" || no "pk2 review check: rc=$rc $out"
out=$($DA local verify "$RUN" 2>&1); grep -q 'holds no report' <<<"$out" && ok "missing report: local verify says OUT holds no report" || no "pk2 verify: $out"
out=$($DA local clean "$RUN" 2>&1); rc=$?
{ [ "$rc" != 0 ] && grep -q 'holds no manifest' <<<"$out" && [ -d "$RUN" ]; } && ok "missing report: local clean refuses it, as before" || no "pk2 clean: rc=$rc $out"
rm -f "$T/stub-final"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -f "$OUT/manifest.json" ] && [ ! -e "$OUT/manifest.json.previous" ] && [ ! -e "$OUT/report.md.previous" ] && grep -q '^PREVIOUS_MANIFEST=replaced' <<<"$out"; } \
  && ok "the next run with a report writes the manifest again and drops the set-aside ones" || no "pk2 again: rc=$rc $out $(ls -A "$OUT")"
# an invalid verdict, or no Findings heading: the report is published and packaged, and review check refuses it with its own words
printf '# Findings\n\nnone\n\nverdict: maybe\n' > "$T/badverdict.md"; printf '%s\n' "$T/badverdict.md" > "$T/stub-final"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
out=$($DA review check "$OUT" 2>&1); rc2=$?
{ [ "$rc" = 0 ] && [ "$rc2" = 1 ] && grep -q 'report.md: the last line must be `verdict: accept` or `verdict: revise` (it is: verdict: maybe)' <<<"$out"; } \
  && ok "invalid verdict: review check fails with today's refusal" || no "invalid verdict: rc=$rc rc2=$rc2 $out"
printf 'all fine\n\nverdict: accept\n' > "$T/badverdict.md"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
out=$($DA review check "$OUT" 2>&1); rc2=$?
{ [ "$rc" = 0 ] && [ "$rc2" = 1 ] && grep -q 'and no report.md (or PREFIXreport.md) with a Findings section' <<<"$out"; } && ok "no Findings heading: review check fails as before" || no "no findings: rc=$rc rc2=$rc2 $out"
printf 'BLOCKED\nthe clone cannot be read\n\n# Findings\n\nnone\n\nverdict: revise\n' > "$T/badverdict.md"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -r .status "$OUT/manifest.json")" = BLOCKED ] && grep -q 'status BLOCKED' <<<"$out"; } && ok "a report that begins with BLOCKED is packaged as status BLOCKED" || no "blocked: rc=$rc $out"
rm -f "$T/stub-final" "$T/badverdict.md"
got=$(python3 -I - <<'PY'
import sys; sys.path.insert(0, "lib")
import local_run as L
yes = ["BLOCKED", "BLOCKED: the clone cannot be read", "**BLOCKED**", "# BLOCKED", "## BLOCKED - no contract", "> BLOCKED", "`BLOCKED`", "_BLOCKED_",
       "Status: BLOCKED", "status:BLOCKED", "**Status:** BLOCKED", "# Status: BLOCKED", "\n\n  **BLOCKED**\nwhy"]
no = ["DONE", "# Findings", "Not BLOCKED", "BLOCKEDNESS", "blocked", "Status: DONE", "Nothing is BLOCKED", ""]
print(" ".join(repr(t) for t in yes if not L.report_blocked(t)) + "|" + " ".join(repr(t) for t in no if L.report_blocked(t)))
PY
)
[ "$got" = "|" ] && ok "a first line that says BLOCKED under Markdown marks or as Status: BLOCKED is a BLOCKED report; DONE and prose are not" || no "report_blocked: missed|wrong: $got"
# a read-only run that leaves patches in OUT: no manifest, and local verify refuses it as before
touch "$T/stub-patch"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -f "$OUT/patches/0001-x.patch" ] && [ ! -e "$OUT/manifest.json" ] && grep -q '^MANIFEST=none: OUT holds patches' <<<"$out"; } && ok "read-only patches: no manifest is written" || no "ro patches: rc=$rc $out"
out=$($DA local verify "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'is a read-only run (review) and its output holds patches' <<<"$out"; } && ok "read-only patches: local verify refuses them, as before" || no "ro patches verify: rc=$rc $out"
out=$($DA review check "$OUT" 2>&1); rc=$?; [ "$rc" = 1 ] && ok "read-only patches: review check fails" || no "ro patches review check: rc=$rc $out"
rm -f "$T/stub-patch"; rm -rf "$OUT/patches"
# a write run is not packaged: its manifest is the member's
setprov codexro; prep "$T/r" pk3; task
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ -f "$OUT/report.md" ] && [ ! -e "$OUT/manifest.json" ] && ! grep -q '^MANIFEST=' <<<"$out" && [ "$(jq -r 'has("manifest")' "$RUN/dispatch.json")" = false ]; } \
  && ok "a write run publishes the report and writes no manifest (the member's own)" || no "pk3 write: rc=$rc $out"
# a manifest.json left in a read-only OUT that is not a plain file of its own refuses the run before anything starts
prep "$T/r" pk4 review; task; echo precious > "$T/victim4"; ln -s "$T/victim4" "$OUT/manifest.json"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -qF "the manifest of an earlier run ($OUT/manifest.json) is not a plain file of its own" <<<"$out" && [ "$(cat "$T/victim4")" = precious ] && [ ! -e "$RUN/dispatch.json" ]; } \
  && ok "a link as the manifest of a read-only run refuses the run; what it points to is untouched" || no "pk4 link: rc=$rc $out"
rm -f "$OUT/manifest.json" "$T/victim4" "$T/bin/codex"

# --- a write run of codex returns the normal series: the member commits in its clone (its .git is a writable root of the sandbox) and collects ---
# End to end with the conformance stub in place of the command: before the stub writes the last message, the fake does what a build member does with
# the run's git wrapper ($GIT): a change, a commit with a body, git format-patch into OUT/patches, the manifest and series.md. The lead then verifies,
# checks the series, applies it in a disposable clone of the repository and runs DONE there.
cat > "$T/bin/codex" <<SH
#!/usr/bin/env bash
c='' a=("\$@")
while [ \$# -gt 0 ]; do [ "\$1" = -C ] && c=\$2; shift; done
r=\$(dirname "\$c"); o=\$r/out
b=\$(awk '\$1 == "local" && \$2 == "refs/heads/main" {print \$3}' "\$r/refs.before")
( cd "\$c" || exit 1
  printf 'ok\n' > CHANGED.txt; "\$GIT" add CHANGED.txt
  printf 'Changed: the file the task asks for\n\nCHANGED.txt holds ok, which DONE checks.\n' > "\$r/tmp-msg"
  "\$GIT" commit -q -F "\$r/tmp-msg"; rm -f "\$r/tmp-msg"
  mkdir -p "\$o/patches"; "\$GIT" format-patch -q --binary -o "\$o/patches" "\$b..HEAD"
  s=\$("\$GIT" rev-parse HEAD)
  jq -n --arg b "\$b" --arg s "\$s" '{status: "DONE", base: {branch: "main", sha: \$b}, branch: "agent/wx1", scope: ["CHANGED.txt"],
    done: {command: "grep -qx ok CHANGED.txt", exit_code: 0, output_tail: ""}, gates: [], commits: [{sha: \$s, subject: "Changed: the file the task asks for"}],
    commit_advice: [{sha: \$s, subject: "Changed: the file the task asks for", why_separate: "one change", depends_on: [], builds_alone: true}],
    patch_groups: [{name: "the change", why: "the task", commits: [\$s]}], touched_paths: [{path: "CHANGED.txt", reason: "the task"}]}' > "\$o/manifest.json"
  printf '0001 Changed: the file the task asks for\n' > "\$o/series.md" ) || exit 9
exec "$STUBX" "\${a[@]}"
SH
chmod 755 "$T/bin/codex"
setprov codex; prep "$T/r" wx1; printf 'TASK: add CHANGED.txt holding ok\nDONE: grep -qx ok CHANGED.txt\n\nBASE: main\nSCOPE: CHANGED.txt\n' > "$RUN/task.md"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^OUTCOME=ok' <<<"$out" && [ -f "$OUT/patches/0001-Changed-the-file-the-task-asks-for.patch" ] && [ -f "$OUT/manifest.json" ] && [ -f "$OUT/report.md" ] \
  && [ "$(jq -c --arg g "$CLONE/.git" '.argv | index(["--add-dir", $g]) != null' "$RUN/dispatch.json")" = true ]; } \
  && ok "e2e write: a codex build run (the stub) given its clone's .git commits and returns the series, the manifest and the report" || no "e2e write run: rc=$rc $out $(ls -A "$OUT")"
out=$($DA local verify "$RUN" 2>&1); rc=$?; [ "$rc" = 0 ] && ok "e2e write: qargi local verify passes" || no "e2e write verify: rc=$rc $out"
out=$($DA review check "$OUT" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^0 fail' <<<"$out"; } && ok "e2e write: qargi review check passes the series" || no "e2e write review check: rc=$rc $out"
git clone -q "$T/r" "$T/apply-wx1"
{ $LC -C "$T/apply-wx1" am -q "$OUT"/patches/*.patch && ( cd "$T/apply-wx1" && grep -qx ok CHANGED.txt ); } \
  && ok "e2e write: the lead applies the series in a disposable clone and DONE passes there" || no "e2e write apply: $(ls "$T/apply-wx1")"
rm -rf "$T/apply-wx1"; rm -f "$T/bin/codex"

# --- a write run that leaves its change uncommitted and returns no patches is a refusal, in local run and in review check, never DONE ---
# The fake member edits a tracked file and/or adds an untracked one, collects nothing and writes a manifest with no commits ($T/wu-mode: tracked,
# untracked, and the status DONE or BLOCKED).
printf 'a\n' > "$T/r/tracked.txt"; git -C "$T/r" add tracked.txt; $LC -C "$T/r" commit -q -m tracked
cat > "$T/bin/codex" <<SH
#!/usr/bin/env bash
c='' a=("\$@")
while [ \$# -gt 0 ]; do [ "\$1" = -C ] && c=\$2; shift; done
o=\$(dirname "\$c")/out; st=DONE
for m in \$(cat "$T/wu-mode"); do
  case \$m in tracked) printf 'b\n' > "\$c/tracked.txt";; untracked) printf 'new\n' > "\$c/new.txt";; blocked) st=BLOCKED;; esac
done
jq -n --arg s "\$st" '{status: \$s, blocked_reason: (if \$s == "BLOCKED" then "the commit was refused" else "" end), base: {branch: "main", sha: ""}, commits: [], gates: [], touched_paths: [], scope: []}' > "\$o/manifest.json"
QARGI_STUB_FINAL=$T/wu-final.md exec "$STUBX" "\${a[@]}"
SH
chmod 755 "$T/bin/codex"; printf 'the change is made in the clone\n' > "$T/wu-final.md"
setprov codex; prep "$T/r" wu1; task
echo tracked untracked > "$T/wu-mode"
out=$($DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q '^OUTCOME=refused (the runtime ended ok, but the clone holds uncommitted changes and OUT holds no patches)$' <<<"$out" \
  && grep -qF "WORKTREE=uncommitted: $CLONE holds 1 changed tracked file(s) and 1 untracked file(s) and OUT holds no patches" <<<"$out" \
  && [ "$(jq -c '[.outcome, .exit, .worktree]' "$RUN/dispatch.json")" = '["refused",0,{"patches":false,"refused":true,"tracked":1,"untracked":1}]' ]; } \
  && ok "a write run that leaves a tracked change uncommitted and no patches is refused (exit 2), however the runtime ended" || no "uncommitted: rc=$rc $out $(jq -c . "$RUN/dispatch.json")"
out=$($DA review check "$OUT" --allow-empty 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF "FAIL $CLONE holds 1 uncommitted change(s) to tracked files (tracked.txt) and OUT holds no patches: that is a refusal, not a finished task" <<<"$out"; } \
  && ok "review check fails a DONE manifest with no commits whose clone holds the change uncommitted, --allow-empty or not" || no "review check uncommitted: rc=$rc $out"
cp "$OUT/report.md" "$T/wu-report.keep"; cp tests/providers/codex/final-message.md "$OUT/report.md"
out=$($DA review check "$OUT" 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -qF "FAIL $CLONE holds 1 uncommitted change(s) to tracked files (tracked.txt)" <<<"$out"; } \
  && ok "and a report with Findings and a verdict does not make it a report-only run that passes" || no "report-only uncommitted: rc=$rc $out"
mv "$T/wu-report.keep" "$OUT/report.md"
echo tracked untracked blocked > "$T/wu-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
out=$($DA review check "$OUT" 2>&1); rc2=$?
{ [ "$rc" = 2 ] && [ "$rc2" = 0 ] && grep -q '^OK no commits (status BLOCKED): the commit was refused$' <<<"$out" && grep -q '^NOTE .*holds 1 uncommitted change(s) to tracked files (tracked.txt); the run is BLOCKED' <<<"$out" \
  && grep -q '^WARN .*holds 1 untracked file(s) no commit has (new.txt)' <<<"$out"; } \
  && ok "a BLOCKED manifest with the change left uncommitted passes review check as a refusal, with a note and a warning" || no "blocked uncommitted: rc=$rc rc2=$rc2 $out"
git -C "$CLONE" checkout -q tracked.txt; echo untracked > "$T/wu-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^OUTCOME=ok$' <<<"$out" && grep -qF "WORKTREE=untracked: $CLONE holds 1 untracked file(s) no commit has and OUT holds no patches" <<<"$out" \
  && [ "$(jq -c '.worktree.refused' "$RUN/dispatch.json")" = false ]; } && ok "untracked files alone are said (WORKTREE=untracked), not a refusal" || no "untracked only: rc=$rc $out"
rm -f "$CLONE/new.txt"; : > "$T/wu-mode"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 0 ] && ! grep -q '^WORKTREE=' <<<"$out" && [ "$(jq -r 'has("worktree")' "$RUN/dispatch.json")" = false ]; } && ok "a clean clone says nothing of it" || no "clean clone: rc=$rc $out"
# the lead reads the clone's state with git, but nothing the member put in the clone's git configuration runs: no fsmonitor, every filter driver it names
# emptied, the work tree named outright, no system or global configuration, no optional locks (a git on PATH records how it is called)
REALGIT=$(command -v git); mkdir -p "$T/fgit"
cat > "$T/fgit/git" <<SH
#!/usr/bin/env bash
printf '%s\n' "ARGS \$*" "WT=\${GIT_WORK_TREE-} GD=\${GIT_DIR-} NOSYS=\${GIT_CONFIG_NOSYSTEM-} GLOBAL=\${GIT_CONFIG_GLOBAL-} LOCKS=\${GIT_OPTIONAL_LOCKS-}" >> "$T/fgit.log"
case " \$* " in *" config "*) cat "$T/fgit.names"; exit 0;; esac
exec "$REALGIT" "\$@"
SH
chmod 755 "$T/fgit/git"; : > "$T/fgit.log"; printf 'c\n' > "$CLONE/tracked.txt"; printf 'filter.evil.clean\0filter.a.b.process\0' > "$T/fgit.names"
got=$(PATH="$T/fgit:$PATH" python3 -I -c 'import sys; sys.path.insert(0, "lib"); import local_run as L; print(L.worktree_changes(sys.argv[1]))' "$CLONE" 2>&1)
st=$(grep '^ARGS .*status' "$T/fgit.log")
{ [ "$got" = "(['tracked.txt'], [])" ] && grep -q -- '-c core.fsmonitor=false' <<<"$st" && grep -q -- '-c filter.evil.clean= -c filter.evil.smudge= -c filter.evil.process= -c filter.evil.required=false' <<<"$st" \
  && grep -q -- '-c filter.a.b.process=' <<<"$st" && grep -qx "WT=$CLONE GD=$CLONE/.git NOSYS=1 GLOBAL=/dev/null LOCKS=0" "$T/fgit.log"; } \
  && ok "the lead's git status of the clone turns off fsmonitor and every filter driver the clone names, and names the work tree itself" || no "worktree git: $got $(cat "$T/fgit.log")"
printf 'filter.x=y.clean\0' > "$T/fgit.names"
got=$(PATH="$T/fgit:$PATH" python3 -I -c 'import sys; sys.path.insert(0, "lib"); import local_run as L; print(L.worktree_changes(sys.argv[1]))' "$CLONE" 2>&1)
[ "$got" = None ] && ok "a filter driver whose name cannot be emptied on the command line: git status is not run, the state is unknown" || no "bad filter name: $got $(cat "$T/fgit.log")"
git -C "$CLONE" checkout -q tracked.txt; rm -rf "$T/fgit" "$T/fgit.log" "$T/fgit.names" "$T/wu-mode" "$T/wu-final.md" "$T/bin/codex"

# --- however a run ends, the member's processes are stopped, the run home's link is removed and dispatch.json says how it ended (synthetic sign-in) ---
# The fake codex records its pid and starts a child in its process group, then waits ($T/ir-mode: wait, or quick to end at once). The signal goes to the
# runner, whose pid the start record in dispatch.json names.
mkdir -p "$HOME/.codex"; printf '{"token": "sk-test-%s-interrupt"}\n' "$RANDOM" > "$HOME/.codex/auth.json"; ISUM=$(sha256sum < "$HOME/.codex/auth.json")
cat > "$T/bin/codex" <<SH
#!/usr/bin/env bash
cat > /dev/null
[ "\$(cat "$T/ir-mode" 2>/dev/null)" = quick ] && exit 0
sleep 3571 & echo \$! > "$T/ir-child"
echo \$\$ > "$T/ir-member"
wait
SH
chmod 755 "$T/bin/codex"
setprov codex; prep "$T/r" ir1; task
LINK=$RUN/home/.codex/auth.json
gone() { ! kill -0 "$1" 2>/dev/null; }
ir_start() { # [launcher...]: local run --again in the background; waits for the member to have started
  rm -f "$T/ir-child" "$T/ir-member" "$T/ir.rc" "$T/ir.out"; echo wait > "$T/ir-mode"
  ( "$@" $DA local run "$RUN" --again > "$T/ir.out" 2>&1; echo $? > "$T/ir.rc" ) &
  wait_until '[ -s "$T/ir-child" ] && [ -s "$T/ir-member" ] && [ "$(jq -r .member "$RUN/dispatch.json" 2>/dev/null)" = "$(cat "$T/ir-member")" ]' 30
}
ir_after() { # SIGNAL CODE: the run ended interrupted by SIGNAL with exit CODE, its processes are gone, the link removed, the source unchanged
  wait_until '[ -s "$T/ir.rc" ]' 30
  { [ "$(cat "$T/ir.rc")" = "$2" ] && grep -q "^OUTCOME=interrupted (SIG$1: the member's process group was stopped)\$" "$T/ir.out" \
    && [ "$(jq -c '[.outcome, .signal]' "$RUN/dispatch.json")" = "[\"interrupted\",\"SIG$1\"]" ] && gone "$(cat "$T/ir-member")" && gone "$(cat "$T/ir-child")" \
    && [ ! -e "$LINK" ] && [ ! -L "$LINK" ] && [ "$(sha256sum < "$HOME/.codex/auth.json")" = "$ISUM" ] && ! grep -q 'interrupt"' "$T/ir.out" "$RUN/dispatch.json"; } \
    && ok "SIG$1 to the runner: the member and its child are stopped, the run home's link is removed, dispatch.json says interrupted (exit $2)" \
    || no "SIG$1: rc=$(cat "$T/ir.rc" 2>/dev/null) $(cat "$T/ir.out") $(jq -c . "$RUN/dispatch.json") link=$(ls -lA "$RUN/home/.codex" 2>&1)"
  for p in "$T/ir-member" "$T/ir-child"; do [ ! -s "$p" ] || kill -KILL "$(cat "$p")" 2>/dev/null; done
}
echo quick > "$T/ir-mode"; out=$($DA local run "$RUN" 2>&1) || no "ir1 first run: $out"
for s in TERM HUP; do
  if ir_start; then kill -"$s" "$(jq -r .runner "$RUN/dispatch.json")"; ir_after "$s" "$([ "$s" = TERM ] && echo 143 || echo 129)"; else no "SIG$s: the member did not start: $(cat "$T/ir.out")"; fi
done
# a background job of a script starts with SIGINT ignored, which the runner keeps (as under nohup): this launcher restores it first, as a terminal has it
if ir_start python3 -I -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execvp(sys.argv[1], sys.argv[1:])'; then
  kill -INT "$(jq -r .runner "$RUN/dispatch.json")"; ir_after INT 130
else no "SIGINT: the member did not start: $(cat "$T/ir.out")"; fi
# the bound: the same, as failed and timed out
echo wait > "$T/ir-mode"; rm -f "$T/ir-child" "$T/ir-member"
out=$(timeout 120 $DA local run "$RUN" --again --timeout 1 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q 'timed out after 1s' <<<"$out" && gone "$(cat "$T/ir-member")" && gone "$(cat "$T/ir-child")" && [ ! -L "$LINK" ] && [ ! -e "$LINK" ] \
  && [ "$(jq -c '[.outcome, .timed_out]' "$RUN/dispatch.json")" = '["failed",true]' ]; } \
  && ok "the bound: the member and its child are killed and the run home's link is removed" || no "timeout: rc=$rc $out"
# the command cannot be started: the earlier outcome does not stay, dispatch.json says transport with the error, and the link is removed
printf '#!/nonexistent/interpreter\n' > "$T/bin/codex"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 4 ] && grep -q '^qargi: could not start codex: ' <<<"$out" && grep -q '^OUTCOME=transport$' <<<"$out" && [ "$(jq -r .outcome "$RUN/dispatch.json")" = transport ] \
  && jq -e '.error | startswith("could not start codex: ")' "$RUN/dispatch.json" >/dev/null && [ "$(jq -r .exit "$RUN/dispatch.json")" = null ] && [ ! -L "$LINK" ] && [ ! -e "$LINK" ] \
  && [ -z "$(find "$RUN" -maxdepth 1 -name 'final.*')" ]; } \
  && ok "a command that cannot be started: dispatch.json is rewritten as transport with the error (the earlier outcome does not stay), the link is removed" || no "launch failure: rc=$rc $out $(jq -c . "$RUN/dispatch.json")"
# the run's configuration file cannot be written (a directory in its place): refused, recorded, the link removed
echo quick > "$T/ir-mode"; cp "$T/bin/fakellm" "$T/bin/codex"; rm -f "$RUN/home/.codex/config.toml"; mkdir -p "$RUN/home/.codex/config.toml"
out=$($DA local run "$RUN" --again 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q "is in the place of the run's configuration file and is not a file" <<<"$out" && [ "$(jq -r .outcome "$RUN/dispatch.json")" = refused ] \
  && jq -e '.error | test("configuration file")' "$RUN/dispatch.json" >/dev/null && [ ! -L "$LINK" ] && [ ! -e "$LINK" ]; } \
  && ok "the run's configuration file cannot be made: the run is refused and recorded so, and the link is removed" || no "run config failure: rc=$rc $out $(jq -c . "$RUN/dispatch.json")"
rmdir "$RUN/home/.codex/config.toml"
# SIGKILL cannot be caught: the start record says running, the link stays, and the member runs on. The next start refuses while the member runs,
# needs --again once it is stopped; list and verify name the link; --again replaces it and the run ends clean; local clean removes a run with it
cat > "$T/bin/codex" <<SH
#!/usr/bin/env bash
cat > /dev/null
[ "\$(cat "$T/ir-mode" 2>/dev/null)" = quick ] && exit 0
sleep 3571 & echo \$! > "$T/ir-child"
echo \$\$ > "$T/ir-member"
wait
SH
chmod 755 "$T/bin/codex"
if ir_start; then
  kill -KILL "$(jq -r .runner "$RUN/dispatch.json")"; wait_until '[ -s "$T/ir.rc" ]' 30
  { [ "$(jq -r .outcome "$RUN/dispatch.json")" = running ] && [ -L "$LINK" ] && ! gone "$(cat "$T/ir-member")"; } && ok "SIGKILL: the start record stays (running), the link stays, the member runs on" || no "sigkill state: $(jq -c . "$RUN/dispatch.json")"
  out=$($DA local run "$RUN" --again 2>&1); rc=$?
  { [ "$rc" = 2 ] && grep -qF "the member of an earlier start of $RUN is still running (process group $(cat "$T/ir-member")), its runner is gone: stop it first (kill -TERM -- -$(cat "$T/ir-member"))" <<<"$out"; } \
    && ok "the next start refuses while the member of the killed runner still runs, naming its process group" || no "sigkill member alive: rc=$rc $out"
  kill -TERM -- -"$(cat "$T/ir-member")"; wait_until 'gone "$(cat "$T/ir-member")" && gone "$(cat "$T/ir-child")"' 10 || no "the member's process group did not stop"
  out=$($DA local run "$RUN" 2>&1); rc=$?
  { [ "$rc" = 2 ] && grep -q 'was started and did not end: its runner is gone' <<<"$out" && grep -qF "qargi local run $RUN --again" <<<"$out"; } && ok "without --again the start is refused with the way on" || no "sigkill no again: rc=$rc $out"
  out=$($DA local list 2>&1)
  grep -qF "  residue: $LINK (a link a start of qargi local run left: its runner did not end); qargi local run RUN --again replaces a link left there" <<<"$out" \
    && ok "local list names the link left in the run home" || no "list residue: $out"
  out=$($DA local verify "$RUN" 2>&1)
  grep -qF "qargi: note: the run home of $RUN holds what a run left there: $LINK (a link a start of qargi local run left: its runner did not end)." <<<"$out" \
    && ok "local verify names it too" || no "verify residue: $out"
  [ -z "$(find "$RUN" -maxdepth 1 -name 'final.*')" ] && no "a SIGKILLed codex run left no last-message directory (the test expects one)"
  echo quick > "$T/ir-mode"
  out=$($DA local run "$RUN" --again 2>&1); rc=$?
  { [ "$rc" = 0 ] && [ ! -L "$LINK" ] && [ ! -e "$LINK" ] && [ -z "$(find "$RUN" -maxdepth 1 -name 'final.*')" ] && [ "$(jq -r .outcome "$RUN/dispatch.json")" = ok ] \
    && [ -z "$($DA local list 2>&1 | grep -F "residue: $LINK")" ]; } \
    && ok "--again replaces the link, clears the stale last-message directory and ends clean; list names no residue" || no "sigkill again: rc=$rc $out"
else no "SIGKILL: the member did not start: $(cat "$T/ir.out")"; fi
prep "$T/r" ir2; task; LINK=$RUN/home/.codex/auth.json
if ir_start; then
  kill -KILL "$(jq -r .runner "$RUN/dispatch.json")"; wait_until '[ -s "$T/ir.rc" ]' 30
  kill -TERM -- -"$(cat "$T/ir-member")"; wait_until 'gone "$(cat "$T/ir-member")"' 10
  ir2=$RUN; out=$($DA local clean "$RUN" --discard 2>&1); rc=$?
  { [ "$rc" = 0 ] && [ ! -e "$ir2" ] && grep -qF "removed with the run what its run home held: $LINK (a link a start" <<<"$out" && [ "$(sha256sum < "$HOME/.codex/auth.json")" = "$ISUM" ]; } \
    && ok "local clean --discard removes a SIGKILLed run with its link (the link only: the sign-in file is untouched)" || no "sigkill clean: rc=$rc $out"
else no "SIGKILL 2: the member did not start: $(cat "$T/ir.out")"; fi
rm -f "$T/ir-child" "$T/ir-member" "$T/ir.rc" "$T/ir.out" "$T/ir-mode" "$T/bin/codex"; rm -rf "$HOME/.codex"

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

# --- the command runs as the real program of its name on the lead's PATH: a wrapper or a shim linked to a program of another name (a version
# manager's multi-call program, which under the run's HOME would look for the tool there) is passed over, and the member's PATH is unchanged ---
setprov fakecmd
w6=("$RUN" "$CLONE" "$OUT"); prep "$T/r" rs1; task                      # a run of its own; the checks below go on with w6
mkdir -p "$T/vm" "$T/wrap" "$T/same" "$T/ext" "$T/real" "$T/noexec"
printf '#!/bin/sh\necho "the wrapper ran as $0" > "%s"\nexit 9\n' "$T/wrapper-ran" > "$T/vm/vmgr"; chmod 755 "$T/vm/vmgr"
ln -s "$T/vm/vmgr" "$T/wrap/fakellm"
cp "$T/bin/fakellm" "$T/real/fakellm"; cp "$T/bin/fakellm" "$T/real/fakellm.js"
ln -s "$T/real/fakellm" "$T/same/fakellm"; ln -s "$T/real/fakellm.js" "$T/ext/fakellm"
printf '#!/bin/sh\nexit 0\n' > "$T/noexec/fakellm"; chmod 644 "$T/noexec/fakellm"
nofake=$(tr ':' '\n' <<<"$PATH" | grep -vxF "$T/bin" | paste -sd: -)     # the PATH of the test without the fake's directory
realfake=$(realpath "$T/bin/fakellm")
out=$(PATH="$T/wrap:$PATH" $DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -qxF "COMMAND=$realfake" <<<"$out" && grep -qF "NOTE=$T/wrap/fakellm on PATH is passed over (it resolves to $(realpath "$T/vm/vmgr"), a program named vmgr, not fakellm" <<<"$out"; } \
  && ok "a wrapper linked to a program of another name first on PATH is passed over with a note; the real program second is the command" || no "wrapper first: rc=$rc $out"
out=$(PATH="$T/wrap:$PATH" $DA local run "$RUN" 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ ! -e "$T/wrapper-ran" ] && grep -qxF "SELF0=$realfake" "$OUT/transcript" && [ "$(jq -r .command "$RUN/dispatch.json")" = "$realfake" ] \
  && [ "$(jq -r '.argv[0]' "$RUN/dispatch.json")" = fakellm ] && grep -q "^MEMBERPATH=$T/wrap:" "$OUT/transcript" && grep -q 'note: .*wrap/fakellm on PATH is passed over' <<<"$out"; } \
  && ok "a run starts the real program by its absolute path (recorded as command in dispatch.json), never the wrapper; the member's PATH is the lead's, wrapper first" \
  || no "wrapper run: rc=$rc $out $(cat "$T/wrapper-ran" 2>/dev/null) $(head -3 "$OUT/transcript" 2>/dev/null)"
out=$(PATH="$T/wrap:$nofake" $DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 3 ] && grep -qF "passed over: $T/wrap/fakellm (it resolves to $(realpath "$T/vm/vmgr"), a program named vmgr, not fakellm" <<<"$out" \
  && grep -q 'a run never starts a wrapper' <<<"$out" && ! grep -q '^COMMAND=' <<<"$out" && [ ! -e "$T/wrapper-ran" ]; } \
  && ok "a wrapper alone on PATH is refused (exit 3), naming the entry and why" || no "wrapper only: rc=$rc $out"
out=$(PATH="$T/same:$nofake" $DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -qxF "COMMAND=$(realpath "$T/real/fakellm")" <<<"$out" && ! grep -q 'passed over' <<<"$out"; } \
  && ok "a link to a program of the same name is accepted and its real path is the command" || no "same-name link: rc=$rc $out"
out=$(PATH="$T/ext:$nofake" $DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -qxF "COMMAND=$(realpath "$T/real/fakellm.js")" <<<"$out"; } \
  && ok "a link to the name with an extension (a launcher fakellm.js) is accepted" || no "extension link: rc=$rc $out"
mkdir -p "$T/rel"; cp "$T/bin/fakellm" "$T/real/fakellm-x86_64-unknown-linux-musl"; ln -s "$T/real/fakellm-x86_64-unknown-linux-musl" "$T/rel/fakellm"
out=$(PATH="$T/rel:$nofake" $DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -qxF "COMMAND=$(realpath "$T/real/fakellm-x86_64-unknown-linux-musl")" <<<"$out" && ! grep -q 'passed over' <<<"$out"; } \
  && ok "a link to the name with a suffix after a dash (a release binary fakellm-x86_64-unknown-linux-musl) is accepted" || no "suffix link: rc=$rc $out"
out=$(PATH="$T/noexec:$PATH" $DA local run "$RUN" --dry-run 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -qxF "COMMAND=$realfake" <<<"$out" && grep -qF "NOTE=$T/noexec/fakellm on PATH is passed over (not executable)" <<<"$out"; } \
  && ok "a file of that name that is not executable is passed over with a note" || no "noexec: rc=$rc $out"
rm -rf "$T/vm" "$T/wrap" "$T/same" "$T/ext" "$T/rel" "$T/real" "$T/noexec" "$T/wrapper-ran"
RUN=${w6[0]} CLONE=${w6[1]} OUT=${w6[2]}
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
