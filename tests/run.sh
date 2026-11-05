#!/usr/bin/env bash
# Runs the tests and the linter listed in tests/suite.txt. No API access, no private data.
#
#   bash tests/run.sh [-j N] [--tier fast|all] [--only PATTERN] [--shard i/K] [--shuffle SEED] [--repeat N] [--enforce-budgets]
#                     [--durations FILE] [--save-durations FILE] [--manifest FILE]
#
#   -j N              run N steps at a time (default: the number of CPUs, at most the cgroup CPU quota when there is one;
#                     -j 1 runs the steps one after the other in the manifest's order)
#   --tier T          fast: the steps marked fast (about a minute); all: every step (default)
#   --only PAT        only the steps whose command matches the extended regular expression PAT
#   --shard i/K       the i-th of K parts (1 <= i <= K) of the selected steps. The steps are dealt longest first, each to the
#                     least loaded part, by their recorded duration (--durations) or else their budget; the plan of all K parts
#                     is printed, and the inventory check runs in every part
#   --shuffle SEED    run the parallel steps in a random order, the same for the same SEED (a number, or auto); the seed is
#                     printed in the summary. The serial steps run last in every mode
#   --repeat N        run every selected step N times (to find a test that fails now and then)
#   --enforce-budgets a step that takes more than 1.5x its budget fails (without it the step is only reported)
#   --durations FILE  read the durations of a former run (lines of `seconds command`) for --shard
#   --save-durations FILE  write this run's durations in that format
#   --manifest FILE   read FILE instead of tests/suite.txt
#
# The manifest has one step per line, fields separated by `|`: tier (fast|full), mode (par: may run beside others; serial: runs
# alone, after the pool), timeout and time budget in seconds, the command, and optionally the `covers` globs (the files the step
# tests, space separated). A step that takes more than 1.5x its budget is reported (a warning). Budgets only shrink.
# Every step runs in a session of its own with a fresh HOME and a TMPDIR of its own, no standard input and no open file but its output;
# one that takes longer than its timeout, or leaves a process running, fails. The directories at the top level of the suite's TMPDIR
# are compared before and after every step: one the step removed, or left, is named in its block and in the summary (a warning: with
# TMPDIR unset that place is /tmp, shared with every other process on the host).
# Output: one block per step, printed when it ends (so in completion order, never interleaved), then a summary. The log of a
# failed step is kept in a directory the block names. `FAILED: <command>` marks a failed step and the last line is
# `total: Ns (passed|FAILED)`; the exit status is 1 on any failure and 2 on a usage error.
set -u
# hermetic: nothing of the caller's cloud binding or qargi setup reaches the tests, and HOME is a fresh directory
# (each test also scrubs itself, see tests/hermetic.sh and tests/hermetic.py)
for _v in $(compgen -e); do case $_v in ANTHROPIC_*|QARGI_*) unset "$_v";; esac; done
SUITE_TMP=${TMPDIR:-/tmp}   # the caller's temporary directory: WORK is made in it, and its top level is watched (dirset below)
WORK=$(mktemp -d) || exit 1
HOME=$WORK/home; export HOME; mkdir -p "$HOME" "$WORK/out"
KEEP=
trap 'for _p in $(jobs -p); do kill "$_p" 2>/dev/null; done; rm -rf "$WORK"' EXIT
trap 'exit 130' INT TERM
cd "$(dirname "$0")/.." || exit 1

usage_die() {
  echo "tests/run.sh: $*" >&2
  echo "usage: bash tests/run.sh [-j N] [--tier fast|all] [--only PATTERN] [--shard i/K] [--shuffle SEED] [--repeat N] [--enforce-budgets] [--durations FILE] [--save-durations FILE] [--manifest FILE]" >&2
  exit 2
}
need_val() { [ "$2" -ge 2 ] || usage_die "$1 needs a value"; }
# the CPUs the run may use: nproc, at most the quota of the cgroup (quota / period, rounded up) when one is set
cpus=$(nproc 2>/dev/null || echo 1)
if [ -r /sys/fs/cgroup/cpu.max ]; then
  read -r _q _p < /sys/fs/cgroup/cpu.max
  if [[ ${_q:-max} =~ ^[0-9]+$ && ${_p:-} =~ ^[1-9][0-9]*$ ]]; then
    _c=$(((_q + _p - 1) / _p)); [ "$_c" -ge 1 ] || _c=1
    [ "$_c" -ge "$cpus" ] || cpus=$_c
  fi
fi
jobs=$cpus; tier=all; only=; shard=; manifest=tests/suite.txt; shuffle=; repeat=1; enforce=0; durfile=; savefile=
while [ $# -gt 0 ]; do
  case $1 in
    -j) need_val "$1" $#; jobs=$2; shift 2;;
    -j[0-9]*) jobs=${1#-j}; shift;;
    --tier) need_val "$1" $#; tier=$2; shift 2;;
    --only) need_val "$1" $#; only=$2; shift 2;;
    --shard) need_val "$1" $#; shard=$2; shift 2;;
    --shuffle) need_val "$1" $#; shuffle=$2; shift 2;;
    --repeat) need_val "$1" $#; repeat=$2; shift 2;;
    --enforce-budgets) enforce=1; shift;;
    --durations) need_val "$1" $#; durfile=$2; shift 2;;
    --save-durations) need_val "$1" $#; savefile=$2; shift 2;;
    --manifest) need_val "$1" $#; manifest=$2; shift 2;;
    -h|--help) sed -n '2,/^set -u/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0;;
    *) usage_die "unknown argument: $1";;
  esac
done
[[ $jobs =~ ^[1-9][0-9]*$ ]] || usage_die "-j needs a positive number: $jobs"
[[ $repeat =~ ^[1-9][0-9]*$ ]] || usage_die "--repeat needs a positive number: $repeat"
case $tier in fast|all) ;; *) usage_die "--tier is fast or all: $tier";; esac
if [ "$shuffle" = auto ]; then shuffle=$((RANDOM * 32768 + RANDOM)); fi
[ -z "$shuffle" ] || [[ $shuffle =~ ^[0-9]+$ ]] || usage_die "--shuffle needs a number or auto: $shuffle"
shard_i=1; shard_k=1
if [ -n "$shard" ]; then
  [[ $shard =~ ^([1-9][0-9]*)/([1-9][0-9]*)$ ]] || usage_die "--shard needs i/K: $shard"
  shard_i=${BASH_REMATCH[1]}; shard_k=${BASH_REMATCH[2]}
  [ "$shard_i" -le "$shard_k" ] || usage_die "--shard i/K needs 1 <= i <= K: $shard"
fi
[ -f "$manifest" ] || usage_die "no manifest: $manifest"
[ -z "$durfile" ] || [ -f "$durfile" ] || usage_die "no durations file: $durfile"

# ---- the manifest
s_tier=(); s_mode=(); s_tmo=(); s_bud=(); s_cmd=(); s_cov=(); bad=()
trim() { local v=$1; v=${v#"${v%%[![:space:]]*}"}; v=${v%"${v##*[![:space:]]}"}; printf '%s' "$v"; }
n=0
while IFS= read -r line || [ -n "$line" ]; do
  n=$((n + 1))
  case $(trim "$line") in ''|'#'*) continue;; esac
  IFS='|' read -r f_tier f_mode f_tmo f_bud f_cmd f_cov extra <<<"$line"
  f_tier=$(trim "$f_tier"); f_mode=$(trim "$f_mode"); f_tmo=$(trim "$f_tmo"); f_bud=$(trim "$f_bud"); f_cmd=$(trim "$f_cmd"); f_cov=$(trim "${f_cov:-}")
  case $f_tier in fast|full) ;; *) bad+=("$manifest:$n: the tier is fast or full: $f_tier"); continue;; esac
  case $f_mode in par|serial) ;; *) bad+=("$manifest:$n: the mode is par or serial: $f_mode"); continue;; esac
  [[ $f_tmo =~ ^[1-9][0-9]*$ && $f_bud =~ ^[1-9][0-9]*$ ]] || { bad+=("$manifest:$n: the timeout and the budget are positive whole seconds"); continue; }
  [ -n "$f_cmd" ] || { bad+=("$manifest:$n: no command"); continue; }
  [ -z "${extra:-}" ] || { bad+=("$manifest:$n: too many fields (a | in the command?)"); continue; }
  s_tier+=("$f_tier"); s_mode+=("$f_mode"); s_tmo+=("$f_tmo"); s_bud+=("$f_bud"); s_cmd+=("$f_cmd"); s_cov+=("$f_cov")
done < "$manifest"
total_steps=${#s_cmd[@]}

# ---- the inventory: every tests/test_* is listed, every tests/ path a step names exists, no step is listed twice
inventory() {
  local f c w i j listed
  local -a ws   # the words of a command, read without expanding them (the linter's step names globs)
  for f in tests/test_*; do
    [ -f "$f" ] || continue
    listed=0
    for c in "${s_cmd[@]+"${s_cmd[@]}"}"; do read -ra ws <<<"$c"; for w in "${ws[@]}"; do [ "$w" = "$f" ] && listed=1; done; done
    [ "$listed" = 1 ] || bad+=("$f is not listed in $manifest")
  done
  for c in "${s_cmd[@]+"${s_cmd[@]}"}"; do
    case $c in shellcheck\ *) continue;; esac
    read -ra ws <<<"$c"
    for w in "${ws[@]}"; do case $w in tests/*) [ -e "$w" ] || bad+=("$manifest lists $w, which does not exist");; esac; done
  done
  for ((i = 0; i < total_steps; i++)); do for ((j = i + 1; j < total_steps; j++)); do
    [ "${s_cmd[i]}" != "${s_cmd[j]}" ] || bad+=("$manifest lists '${s_cmd[i]}' twice")
  done; done
  return 0
}
inventory

# ---- the weight of a step for ordering and sharding: its recorded duration, else its budget
declare -A rec=()
if [ -n "$durfile" ]; then
  while read -r d c; do [[ $d =~ ^[0-9]+$ ]] && [ -n "$c" ] && rec["$c"]=$d; done < "$durfile"
fi
weight() { local c=${s_cmd[$1]}; echo "${rec[$c]:-${s_bud[$1]}}"; }
# the steps given, longest first, ties in manifest order
by_weight() { local i; for i in "$@"; do printf '%s %s\n' "$((100000 - $(weight "$i")))" "$i"; done | sort -n -k1,1 -k2,2n | awk '{print $2}'; }

# ---- the selection
sel=()
for ((i = 0; i < total_steps; i++)); do
  [ "$tier" = all ] || [ "${s_tier[i]}" = fast ] || continue
  if [ -n "$only" ]; then grep -Eq -- "$only" <<<"${s_cmd[i]}" || continue; fi
  sel+=("$i")
done
plan=
if [ "$shard_k" -gt 1 ]; then
  load=(); cnt=(); for ((i = 0; i < shard_k; i++)); do load+=(0); cnt+=(0); done
  mine=()
  if [ ${#sel[@]} -gt 0 ]; then
    # shellcheck disable=SC2046
    for i in $(by_weight "${sel[@]}"); do
      best=0; for ((j = 1; j < shard_k; j++)); do [ "${load[j]}" -ge "${load[best]}" ] || best=$j; done
      load[best]=$((load[best] + $(weight "$i"))); cnt[best]=$((cnt[best] + 1))
      [ "$best" = $((shard_i - 1)) ] && mine+=("$i")
    done
  fi
  sel=("${mine[@]+"${mine[@]}"}")
  plan="shard plan (planned seconds):"
  for ((i = 0; i < shard_k; i++)); do plan+=" $((i + 1))/$shard_k=${load[i]}s(${cnt[i]} steps)"; done
fi

# the work list: the parallel steps (longest first, or shuffled), each repeated, then the serial ones
pool=(); ser=()
for i in "${sel[@]+"${sel[@]}"}"; do
  if [ "${s_mode[i]}" = serial ]; then ser+=("$i"); else pool+=("$i"); fi
done
if [ "$jobs" -gt 1 ] && [ ${#pool[@]} -gt 0 ]; then
  # shellcheck disable=SC2207
  pool=($(by_weight "${pool[@]}"))
fi
it_step=(); it_rep=()
for ((r = 1; r <= repeat; r++)); do for i in "${pool[@]+"${pool[@]}"}"; do it_step+=("$i"); it_rep+=("$r"); done; done
if [ -n "$shuffle" ] && [ ${#it_step[@]} -gt 0 ]; then
  order=$(for ((k = 0; k < ${#it_step[@]}; k++)); do echo "$k"; done | awk -v seed="$shuffle" 'BEGIN { srand(seed) } { printf "%.12f %s\n", rand(), $0 }' | sort -n -k1,1 | awk '{print $2}')
  ns=(); nr=()
  for k in $order; do ns+=("${it_step[k]}"); nr+=("${it_rep[k]}"); done
  it_step=("${ns[@]}"); it_rep=("${nr[@]}")
fi
npool=${#it_step[@]}
for ((r = 1; r <= repeat; r++)); do for i in "${ser[@]+"${ser[@]}"}"; do it_step+=("$i"); it_rep+=("$r"); done; done

# ---- one step. It runs in a session of its own (so a timeout, or the end of the step, reaches every process it started), with
# no standard input and no open file but its output. Its output goes to $WORK/out/K.log, its seconds to K.sec, its process group
# to K.pgid, the processes left over to K.left and its status to K.rc (written last).
step_exec() {   # step_exec PGIDFILE TIMEOUT COMMAND...
  local pf=$1 t=$2 f n
  shift 2
  echo $$ > "$pf"
  for f in /proc/self/fd/*; do n=${f##*/}; [ "$n" -gt 2 ] 2>/dev/null && eval "exec $n>&-"; done 2>/dev/null
  exec timeout -k 5 "$t" "$@"
}
# the linter, in batches of twenty files through xargs, $SC_JOBS at a time, one log per batch: the output of a failed batch is
# printed whole, after all have ended
run_shellcheck() {
  local -a files; local rc f any=0
  # the globs of the step expand here
  # shellcheck disable=SC2206
  files=(${1#shellcheck -x -S warning })
  mkdir -p "$SC_DIR"
  printf '%s\0' "${files[@]}" | xargs -0 -n 20 -P "$SC_JOBS" sh -c 'shellcheck -x -S warning "$@" > "$0/$$.log" 2>&1 || { echo failed >> "$0/$$.failed"; exit 1; }' "$SC_DIR"
  rc=$?
  for f in "$SC_DIR"/*.failed; do [ -e "$f" ] || continue; any=1; cat "${f%.failed}.log"; done
  [ "$rc" -eq 0 ] && [ "$any" -eq 0 ] && return 0
  echo "shellcheck: a batch failed (xargs exit status $rc)"
  return 1
}
# ---- the shared place a step could touch: the top level of the suite's TMPDIR. Every step's own directory is under WORK, so what is there is
# the caller's and the steps' neighbours, and nothing of the suite makes or removes one there while the steps run. The set of directories
# there is taken before and after each step: one that is gone was removed by the step, one that is new was left by it. Both are named in the
# step's block and in the summary, as a warning: with TMPDIR unset the place is /tmp, shared with every process on the host, and a change can
# be another's. (/dev/shm is not watched: on a host that dispatches work, the temporary directories of other runs come and go there during a
# step, and every step running at that moment would be blamed.) The runner's own directory of kept logs is left out of the set.
dirset() {   # the directories at the top level of the suite's TMPDIR, one path per line, sorted
  find "$SUITE_TMP" -mindepth 1 -maxdepth 1 -type d ! -name 'qargi-suite-logs.*' 2>/dev/null | LC_ALL=C sort
}
dirs_changed() {   # dirs_changed BEFORE AFTER -> a line "removed PATH" per directory gone, then "left PATH" per new one; nothing when the sets are the same
  LC_ALL=C comm -23 "$1" "$2" | sed 's/^/removed /'
  LC_ALL=C comm -13 "$1" "$2" | sed 's/^/left /'
}
run_one() {
  local k=$1 i=${it_step[$1]} h=$WORK/home-$1 t=$WORK/tmp-$1 r pg left
  local -a words
  mkdir -p "$h" "$t"
  case ${s_cmd[i]} in
    shellcheck\ -x\ -S\ warning\ *) words=(bash -c "$(declare -f run_shellcheck); run_shellcheck \"\$1\"" _ "${s_cmd[i]}");;
    *) read -ra words <<<"${s_cmd[i]}";;
  esac
  dirset > "$WORK/out/$k.dirs0"
  local s=$SECONDS
  HOME=$h TMPDIR=$t SC_JOBS=$jobs SC_DIR=$WORK/sc-$k setsid -w bash -c "$(declare -f step_exec); step_exec \"\$@\"" _ "$WORK/out/$k.pgid" "${s_tmo[i]}" "${words[@]}" \
    </dev/null >"$WORK/out/$k.log" 2>&1
  r=$?
  echo $((SECONDS - s)) > "$WORK/out/$k.sec"
  pg=$(cat "$WORK/out/$k.pgid" 2>/dev/null)
  if [ -n "$pg" ] && kill -0 -- "-$pg" 2>/dev/null; then
    sleep 0.3
    if kill -0 -- "-$pg" 2>/dev/null; then
      left=$(pgrep -a -g "$pg" 2>/dev/null)
      printf '%s\n' "${left:-process group $pg is still running}" > "$WORK/out/$k.left"
      kill -KILL -- "-$pg" 2>/dev/null
    fi
  fi
  dirset > "$WORK/out/$k.dirs1"
  dirs_changed "$WORK/out/$k.dirs0" "$WORK/out/$k.dirs1" > "$WORK/out/$k.dirs"
  rm -rf "$h" "$t" "$WORK/sc-$k"
  echo $r > "$WORK/out/$k.rc"
}

rc=0; failed=(); slow=(); dirs=(); times=(); done_cmd=(); done_sec=()
keep_log() {   # keep_log K: copies the log of a failed step where it stays after the run, and prints where
  cp "$WORK/out/$1.log" "$KEEP/$1-$(tr -c 'A-Za-z0-9._' '_' <<<"${s_cmd[${it_step[$1]}]}" | cut -c1-80).log"
  ls -d "$KEEP/$1-"*
}
report() {   # the block of one finished step, printed in one piece
  local k=$1 i=${it_step[$1]} r sec text label over=0 fail=0
  r=$(cat "$WORK/out/$k.rc"); sec=$(cat "$WORK/out/$k.sec"); label="== ${s_cmd[i]}"
  [ "$repeat" -le 1 ] || label+=" (run ${it_rep[k]} of $repeat)"
  text=$label
  [ $((2 * sec)) -le $((3 * s_bud[i])) ] || over=1
  { [ "$r" != 0 ] || [ -e "$WORK/out/$k.left" ] || { [ "$over" = 1 ] && [ "$enforce" = 1 ]; }; } && fail=1
  if [ "$fail" = 0 ]; then
    text+=$'\n'$(tail -3 "$WORK/out/$k.log")
  else
    text+=$'\n'$(grep -E -A6 "^FAIL|Error|error:" "$WORK/out/$k.log" | head -60)
    text+=$'\n'$(tail -20 "$WORK/out/$k.log")
    if [ "$r" = 124 ] || [ "$r" = 137 ]; then text+=$'\n'"TIMEOUT: ${s_cmd[i]} was stopped after ${s_tmo[i]}s"; fi
    if [ -e "$WORK/out/$k.left" ]; then text+=$'\n'"LEFT RUNNING after ${s_cmd[i]} (killed):"$'\n'"$(cat "$WORK/out/$k.left")"; fi
    if [ "$r" = 0 ] && [ ! -e "$WORK/out/$k.left" ]; then text+=$'\n'"OVER BUDGET: ${sec}s, budget ${s_bud[i]}s (--enforce-budgets)"; fi
    [ -n "$KEEP" ] || KEEP=$(mktemp -d "${TMPDIR:-/tmp}/qargi-suite-logs.XXXXXX")
    text+=$'\n'"log: $(keep_log "$k")"
    text+=$'\n'"FAILED: ${s_cmd[i]}"; rc=1; failed+=("${s_cmd[i]}")
  fi
  text+=$'\n'"   (${sec}s)"
  if [ "$over" = 1 ]; then
    text+=$'\n'"   WARN over budget: ${sec}s, budget ${s_bud[i]}s"; slow+=("${sec}s (budget ${s_bud[i]}s) ${s_cmd[i]}")
  fi
  if [ -s "$WORK/out/$k.dirs" ]; then
    text+=$'\n'"   WARN directories outside its own changed: $(paste -sd, "$WORK/out/$k.dirs" | sed 's/,/, /g')"
    dirs+=("${s_cmd[i]}: $(paste -sd, "$WORK/out/$k.dirs" | sed 's/,/, /g')")
  fi
  times+=("$sec ${s_cmd[i]}"); done_cmd+=("${s_cmd[i]}"); done_sec+=("$sec")
  printf '%s\n' "$text"
}

t0=$SECONDS
[ -z "$plan" ] || echo "$plan"
if [ ${#bad[@]} -gt 0 ]; then
  echo "== inventory ($manifest, tests/test_*)"
  printf '%s\n' "${bad[@]}"
  echo "FAILED: inventory"; rc=1; failed+=("inventory")
fi

running=()
reap() {   # prints the finished steps not printed yet
  local x
  for x in "${!running[@]}"; do
    if [ -e "$WORK/out/${running[x]}.rc" ]; then report "${running[x]}"; unset "running[$x]"; fi
  done
  running=("${running[@]+"${running[@]}"}")
}
for ((k = 0; k < npool; k++)); do
  while [ ${#running[@]} -ge "$jobs" ]; do wait -n 2>/dev/null; reap; done
  run_one "$k" & running+=("$k")
done
while [ ${#running[@]} -gt 0 ]; do wait -n 2>/dev/null; reap; done
wait
# the steps that run alone (the linter, which uses every CPU itself)
for ((k = npool; k < ${#it_step[@]}; k++)); do run_one "$k"; report "$k"; done

# ---- the summary
read -r l1 l5 l15 _ < /proc/loadavg 2>/dev/null || { l1='?'; l5='?'; l15='?'; }
echo "== summary: ${#sel[@]} of $total_steps steps; -j $jobs (nproc $(nproc 2>/dev/null || echo ?), load $l1 $l5 $l15), tier $tier, only ${only:-none}, shard ${shard:-none}, shuffle seed ${shuffle:-none}, repeat $repeat"
if [ ${#failed[@]} -gt 0 ]; then echo "failed steps (${#failed[@]}):"; printf '  %s\n' "${failed[@]}"; else echo "failed steps: none"; fi
if [ ${#times[@]} -gt 0 ]; then
  echo "slowest:"
  printf '%s\n' "${times[@]}" | sort -rn -k1,1 | head -10 | awk '{t = $1; $1 = ""; printf "  %5ss %s\n", t, substr($0, 2)}'
fi
if [ ${#slow[@]} -gt 0 ]; then echo "over 1.5x their budget$([ "$enforce" = 1 ] || echo ' (warning)'):"; printf '  %s\n' "${slow[@]}"; fi
if [ ${#dirs[@]} -gt 0 ]; then echo "directories outside a step's own changed (warning; the top level of $SUITE_TMP):"; printf '  %s\n' "${dirs[@]}"; fi
[ -z "$KEEP" ] || echo "logs of the failed steps: $KEEP"
if [ -n "$savefile" ]; then
  for ((k = 0; k < ${#done_cmd[@]}; k++)); do echo "${done_sec[k]} ${done_cmd[k]}"; done > "$savefile"
fi
echo "total: $((SECONDS - t0))s ($([ $rc = 0 ] && echo passed || echo FAILED))"
exit $rc
