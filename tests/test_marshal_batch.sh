#!/usr/bin/env bash
# qargi marshal: reading the cache of the shared refs backend on a project with strict integrity and 14 signed records.
# A read lists the refs with one for-each-ref and reads their objects with two cat-file processes, however many refs there are; the
# processes are counted with a git shim and an ssh-keygen shim first on PATH. What the speed-up must not change: every signature is
# verified on every read (a record that was tampered with after an earlier read is refused by the next one, and the shim counts one
# verification per record per read), and a push still loses to a writer that got in between the fetch and the push (compare and swap).
# Everything is local: a scratch bare origin in a temp dir, two machines with their own HOME, QARGI_CONF, QARGI_STATE and clone.
# Run: tests/test_marshal_batch.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
trap 'jobs -p | xargs -r kill 2>/dev/null; rm -rf "$T" "$HERMETIC"' EXIT
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
unset GIT_TERMINAL_PROMPT
REALGIT=$(command -v git); REALSSHK=$(command -v ssh-keygen || echo /nonexistent/ssh-keygen)
git() { "$REALGIT" "$@"; }                 # the test's own git is never counted
ORIGIN=$T/origin.git; LOG=$T/shim.log; SKLOG=$T/sshk.log; GLOG=$T/git.log; : > "$LOG"; : > "$SKLOG"; : > "$GLOG"
mkdir -p "$T/m" "$T/shimbin" "$T/countbin" "$T/hooks" "$T/slow"
WORDS="the signed records are fine for this project"
TTL=900

# --- the shims. countbin/git logs the subcommand of every git process qargi starts (one line each) and runs shimbin/git, which logs
# fetches and pushes and can run a command right after a machine's fetch (to make a race deterministic); ssh-keygen logs its arguments.
git_shim "$T/shimbin" "$LOG" "$REALGIT" "$T"; sshk_shim "$T/shimbin" "$SKLOG" "$REALSSHK" "$T/sk.slow"
{
  printf '#!/usr/bin/env bash\nGLOG=%q NEXT=%q\n' "$GLOG" "$T/shimbin/git"
  cat <<'SHIM'
sub=''; skip=0
for a in "$@"; do
  if [ $skip = 1 ]; then skip=0; continue; fi
  case $a in -C|-c) skip=1;; -*) ;; *) sub=$a; break;; esac
done
printf '%s\n' "$sub" >> "$GLOG"
exec "$NEXT" "$@"
SHIM
} > "$T/countbin/git"
chmod +x "$T/countbin/git"
export PATH=$T/countbin:$T/shimbin:$PATH
gcount() { grep -c "^$1\$" "$GLOG"; }                                   # git processes of a subcommand since the last reset
gall() { wc -l < "$GLOG"; }
gcount0() { : > "$GLOG"; : > "$SKLOG"; }                                # reset the counters
vcount() { grep -c -e '-Y verify' "$SKLOG"; }                           # signature verifications since the last reset

XE() {
  local m=$1; shift; local -a ev=()
  while [[ ${1:-} =~ ^[A-Z_0-9]+= ]]; do ev+=("$1"); shift; done
  env HOME="$T/m/$m/home" QARGI_CONF="$T/m/$m/c" QARGI_STATE="$T/m/$m/s" "${ev[@]}" "$DA" "$@" >"$T/o" 2>"$T/e"
}
S() { echo "$T/m/$1/s"; }
OWN() { # MACHINE ARGS...: an owner verb of the marshal: the plan, then the apply with the token and the words
  local m=$1 tk; shift
  XE "$m" marshal "$@"; tk=$(tokof)
  [ -n "$tk" ] || return 97
  XE "$m" marshal "$@" --plan "$tk" --approved "$WORDS"
}
OG() { git --git-dir="$ORIGIN" "$@"; }
oref() { OG rev-parse -q --verify "$1" 2>/dev/null || echo none; }
ocount() { OG rev-list --count "$1" 2>/dev/null || echo 0; }
orec() { OG cat-file -p "$1:record.json" 2>/dev/null; }
hook_after_fetch() { # TARGET SRC ARGS...: right after TARGET's next fetch, run qargi as SRC with ARGS
  local t=$1 s=$2; shift 2
  { printf 'env HOME=%q QARGI_CONF=%q QARGI_STATE=%q QARGI_PROJECT=app %q' "$T/m/$s/home" "$T/m/$s/c" "$T/m/$s/s" "$DA"; printf ' %q' "$@"; echo; } > "$T/hooks/$(printf '%s' "$T/m/$t/home" | tr / _)"
}

# --- the origin; machine a is enabled, keyed (it trusts its own key) and strict; machine b is a copy of it
make_origin "$ORIGIN"
make_machine a
OWN a enable >/dev/null 2>&1 || no "setup: enable of a"
OWN a key init --principal a@ms >/dev/null 2>&1
LINE=$(grep -m1 'namespaces="qargi-marshal" ssh-ed25519 ' "$T/o" | sed 's/^[[:space:]]*//')
OWN a signers add --line "$LINE" >/dev/null 2>&1
OWN a enable --integrity strict >/dev/null 2>&1
[ "$(jq -r '.integrity // "off"' "$(S a)/marshal/app.enabled" 2>/dev/null)" = strict ] && [ -f "$T/m/a/c/credentials/marshal_ed25519" ] \
  && ok "setup: machine a is enabled with strict integrity and has a key it trusts" || no "setup of the strict machine a: $(out)"
clone_machine a b
FEATS="f01 f02 f03 f04 f05 f06 f07 f08 f09 f10 f11 f12 f13 f14"
for d in "$T"/m/*; do for n in $FEATS cas1 cas2; do git -C "$d/app" branch "feature/$n" develop; done; done
for n in $FEATS; do XE a marshal claim "$n" --as alice --goal "goal $n" >/dev/null 2>&1 || no "setup: claim of $n: $(out)"; done
[ "$(git -C "$T/m/a/app" for-each-ref refs/qargi | wc -l)" = 14 ] && ok "setup: the cache holds 14 signed records" || no "setup: the cache of a: $(git -C "$T/m/a/app" for-each-ref refs/qargi)"

# ============================================================ (1) one read of 14 refs: a constant number of git processes, one verification each
gcount0
XE a marshal status --all --brief --no-fetch; rc=$?
[ $rc = 0 ] && [ "$(grep -c '\[signed\]' "$T/o")" = 14 ] && ! grep -q Traceback "$T/e" \
  && ok "status --all --brief --no-fetch: exit 0, 14 records, every one tagged signed" || no "status --all --brief --no-fetch (rc=$rc): $(out)"
cp "$T/o" "$T/o.first"
[ "$(gcount cat-file)" = 2 ] && [ "$(gcount ls-tree)" = 0 ] \
  && ok "the cache is read by 2 cat-file processes and no ls-tree, not one process per ref and object (cat-file $(gcount cat-file), ls-tree $(gcount ls-tree))" \
  || no "a read of 14 refs must use 2 cat-file processes and no ls-tree (cat-file $(gcount cat-file), ls-tree $(gcount ls-tree), all $(gall))"
[ "$(vcount)" = 14 ] && ok "each of the 14 signatures was verified once (ssh-keygen -Y verify x $(vcount))" || no "14 verifications expected, got $(vcount): $(cat "$SKLOG")"
for i in $(seq 1 14); do printf 'f%02d  lead=alice  active  goal f%02d  [signed]\n' "$i" "$i"; done > "$T/o.want"
grep '^f[0-9]' "$T/o" | cmp -s - "$T/o.want" && ok "the 14 lines of the brief listing are the ones a record per ref gives" || no "the brief listing differs: $(diff "$T/o.want" "$T/o")"
# the listing asks git once about what is the same for every feature (the work trees, the list of branches), not once per feature
[ "$(gcount worktree)" = 1 ] && [ "$(gall)" -le 45 ] \
  && ok "git is started $(gall) times for 14 features (the work trees are listed once, not per feature)" \
  || no "a listing of 14 features must start at most 45 git processes and list the work trees once (worktree $(gcount worktree), all $(gall)): $(sort "$GLOG" | uniq -c | tr '\n' ' ')"

# ============================================================ (2) every read verifies again; a record changed after a read is refused by the next
gcount0
XE a marshal status --all --brief --no-fetch; rc=$?
[ $rc = 0 ] && cmp -s "$T/o" "$T/o.first" && [ "$(vcount)" = 14 ] \
  && ok "a second read gives the same output and verifies all 14 signatures again (nothing is remembered between reads)" \
  || no "second read: rc=$rc, verifications $(vcount), output differs: $(diff "$T/o.first" "$T/o")"
# f05 becomes a commit with the same parent and message and a changed record (the signature no longer covers it)
R5=$(git -C "$T/m/a/app" rev-parse refs/qargi/features/f05)
MSG=$(git -C "$T/m/a/app" cat-file commit "$R5" | sed '1,/^$/d')
BAD=$(git -C "$T/m/a/app" cat-file -p "$R5:record.json" | jq '.goal = "tampered"' | git -C "$T/m/a/app" hash-object -w --stdin)
TREE=$(printf '100644 blob %s\trecord.json\n' "$BAD" | git -C "$T/m/a/app" mktree)
BADC=$(printf '%s\n' "$MSG" | git -C "$T/m/a/app" commit-tree "$TREE")
git -C "$T/m/a/app" update-ref refs/qargi/features/f05 "$BADC"
gcount0
XE a marshal status --all --brief --no-fetch; rc=$?
if grep -q 'warning.*f05' "$T/e" && ! grep -q tampered "$T/o" && [ "$(vcount)" -ge 14 ] && [ "$(gcount cat-file)" -le 6 ]; then
  ok "a record changed after an earlier read is refused by the next one (strict: a warning naming f05, the tampered goal not shown), all 14 verified again"
else no "tampered f05 must be refused with a warning (rc=$rc, verifications $(vcount), cat-file $(gcount cat-file)): $(out)"; fi
XE a marshal status f05 --json --no-fetch
grep -q tampered "$T/o" && no "status f05 --json shows the tampered goal" || ok "status f05 --json does not show the tampered goal"
git -C "$T/m/a/app" update-ref refs/qargi/features/f05 "$R5"

# ============================================================ (3) compare and swap: a writer that gets in between the fetch and the push wins
XE b marshal status --all --brief >/dev/null 2>&1
hook_after_fetch b a marshal claim cas1 --as alice
XE b marshal claim cas1 --as bob; rc=$?
[ ! -e "$T/hooks/$(printf '%s' "$T/m/b/home" | tr / _)" ] && [ "$(orec refs/qargi/features/cas1 | jq -r .lead.id)" = alice ] && [ "$(ocount refs/qargi/features/cas1)" = 1 ] \
  && [ $rc = 1 ] && grep -q "led by" <(out) \
  && ok "CAS (create): a created the ref between b's fetch and b's push; b refuses (exit 1, 'led by'), the origin keeps a's record" \
  || no "CAS create: rc=$rc, lead $(orec refs/qargi/features/cas1 | jq -r .lead.id), count $(ocount refs/qargi/features/cas1): $(out)"
XE a marshal claim cas2 --as alice >/dev/null 2>&1
XE b QARGI_MARSHAL_MONO=0 marshal status cas2 --as bob >/dev/null
hook_after_fetch b a marshal renew cas2 --as alice
XE b QARGI_MARSHAL_MONO=$((TTL + 1)) marshal takeover cas2 --as bob --approved "$WORDS"; rc=$?
if [ $rc = 1 ] && [ "$(ocount refs/qargi/features/cas2)" = 2 ] && [ "$(orec refs/qargi/features/cas2 | jq -r .lead.id)" = alice ]; then
  ok "CAS (update): a renewed between b's fetch and b's takeover push; the takeover is refused and the origin keeps a's two commits"
else no "CAS update: rc=$rc, count $(ocount refs/qargi/features/cas2), lead $(orec refs/qargi/features/cas2 | jq -r .lead.id): $(out)"; fi

[ "$fail" = 0 ] && echo "all ok" || echo "FAILED"
exit "$fail"
