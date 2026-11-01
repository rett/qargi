#!/usr/bin/env bash
# qargi marshal, slice 3: signed records (integrity off | advisory | strict) on the shared refs backend. Written from the SPEC of the
# feature, not from its code. Everything is local: a scratch bare origin in a temp dir, several "machines" (each with its own HOME,
# QARGI_CONF, QARGI_STATE and clone of that origin) and a git shim and an ssh-keygen shim first on PATH (the shims log every call, and
# the ssh-keygen shim can make a verification hang). Forged, replayed, rewound and tampered records are written with git plumbing
# straight to the scratch origin; the test signs forged records itself, with ssh-keygen, from the format of the spec (an independent
# implementation of the payload, which is also how the test checks that a record qargi signed verifies). Nothing leaves the temp dir.
# Run: tests/test_marshal_sign.sh
#
# Interfaces beyond the spec's wording that this test ASSUMES (the commit message of this file lists them as well):
#   - the owner verbs `marshal key init`, `marshal signers add|remove` and `marshal enable --integrity MODE` work like `marshal enable`:
#     without --plan/--approved they print `plan token: TOK` and change nothing; they apply with `--plan TOK --approved WORDS`; any of
#     the two missing, or a wrong token, is refused (exit nonzero). `marshal resign NAME` takes only `--approved WORDS` (as the spec says).
#   - `marshal key init [--principal P]` names the key's principal P (default: person@machine); it prints the signers line
#     `P namespaces="qargi-marshal" ssh-ed25519 AAAA...` (the test takes the line from the output) and does not add it to the signers
#     file; a second `key init` while the key exists is refused and leaves the key as it was. Its audit line has a verb containing
#     `marshal:key`. The key is written as $QARGI_CONF/credentials/marshal_ed25519 (the public half beside it is not looked at).
#   - `marshal signers add --line L` takes one single line; text that is not a signers line, or a line with a newline in it, is refused.
#     `marshal signers remove P` drops every line of the principal P; `marshal signers list` prints the lines.
#   - `marshal enable --integrity MODE` also works on a project that is already enabled and keeps backend and remote; a mode other than
#     off, advisory or strict is refused. The mode is the field `integrity` of $STATE/marshal/app.enabled (absent or "off" = off).
#   - the signature armor is in the commit message as plain lines (not indented) and the signed payload has no trailing newline; the
#     reader rebuilds the canonical payload from the record AS STORED (sig_v and signer included in record_sha256).
#   - `marshal status NAME` prints the tag signed, unsigned or INVALID (or "cannot verify" for an unknown sig_v) for the record it shows
#     in advisory mode, and `--json` carries the record's fields; in strict mode an ignored record is not shown and a warning
#     (the word "warning" and the ref's name) goes to stderr. `status --all --history` shows done records.
#   - rollback, a forked record at the same rev, and a head that does not descend from the accepted one all print `rollback detected`
#     in both advisory and strict (strict also falls back to the accepted record; what an advisory reader shows is not asserted).
#     A vanished ref (no done/ record) prints a warning naming the ref.
#   - a signed done record is a root commit whose record carries `features_oid`, the oid of the last features record (null when there was
#     none); that oid is the `parent` of its signed payload (review fix: an old done cannot be replayed to clear the mark of a feature
#     that is open again, and a done clears the mark only when its features_oid is the accepted oid).
#   - the verification of a record gives up in well under 60 seconds when ssh-keygen hangs (the test hangs it for 60 s and allows 90).
#   - the "member run" and the exit status 2 with "member" on stderr are the ones of test_marshal_refs.sh.
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
trap 'jobs -p | xargs -r kill 2>/dev/null; rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
unset GIT_TERMINAL_PROMPT
REALGIT=$(command -v git); REALSSHK=$(command -v ssh-keygen || echo /nonexistent/ssh-keygen)
git() { "$REALGIT" "$@"; }                 # the test's own git is never logged by the shim
ORIGIN=$T/origin.git; LOG=$T/shim.log; SKLOG=$T/sshk.log; : > "$LOG"; : > "$SKLOG"
mkdir -p "$T/m" "$T/shimbin"
WORDS="the signed records are fine for this project"
TTL=900

# --- the shims: git logs push, fetch, pull, ls-remote and clone; ssh-keygen logs its argument list and hangs verifications while $T/sk.slow exists
cat > "$T/shimbin/git" <<SHIM
#!/usr/bin/env bash
sub=''; i=0; skip=0
for a in "\$@"; do
  i=\$((i + 1))
  if [ \$skip = 1 ]; then skip=0; continue; fi
  case \$a in -C|-c) skip=1;; -*) ;; *) sub=\$a; break;; esac
done
case \$sub in
  push|fetch|pull|ls-remote|clone) printf '%s\t%s\t%s\n' "\$sub" "\$PWD" "\${*:\$((i + 1))}" >> "$LOG";;
esac
exec "$REALGIT" "\$@"
SHIM
cat > "$T/shimbin/ssh-keygen" <<SHIM
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$SKLOG"
case "\$*" in *verify*|*find-principals*) [ -f "$T/sk.slow" ] && exec sleep 60;; esac
exec "$REALSSHK" "\$@"
SHIM
chmod +x "$T/shimbin/git" "$T/shimbin/ssh-keygen"; export PATH=$T/shimbin:$PATH
nall() { wc -l < "$LOG"; }

# --- the origin, seeded from a scratch repository, and the machines
git init -q --bare "$ORIGIN"
git init -q -b master "$T/seed"; echo 0.1.0 > "$T/seed/VERSION"
git -C "$T/seed" add -A && git -C "$T/seed" commit -q -m one && git -C "$T/seed" branch develop
git -C "$T/seed" remote add origin "$ORIGIN" && git -C "$T/seed" push -q origin master develop
mk() { # NAME: a machine with its own home, conf, state and a clone of the origin
  local d=$T/m/$1
  mkdir -p "$d/home" "$d/c/projects" "$d/s"
  git clone -q "$ORIGIN" "$d/app" && git -C "$d/app" branch develop origin/develop >/dev/null 2>&1
  env HOME="$d/home" QARGI_CONF="$d/c" QARGI_STATE="$d/s" "$DA" project template app \
    | jq --arg p "$d/app" '.repo.path = $p | .repo.url = "https://github.com/acme/app" | .methodology = "gitflow" | .test_command = "true"' > "$d/c/projects/app.json"
}
# XE MACHINE [VAR=val...] ARGS...: qargi as that machine, output in $T/o and $T/e, the exit status returned
XE() {
  local m=$1; shift; local -a ev=()
  while [[ ${1:-} =~ ^[A-Z_0-9]+= ]]; do ev+=("$1"); shift; done
  env HOME="$T/m/$m/home" QARGI_CONF="$T/m/$m/c" QARGI_STATE="$T/m/$m/s" "${ev[@]}" "$DA" "$@" >"$T/o" 2>"$T/e"
}
out() { cat "$T/o" "$T/e"; }
S() { echo "$T/m/$1/s"; }                  # the state directory of a machine
KEY() { echo "$T/m/$1/c/credentials/marshal_ed25519"; }
SIG() { echo "$(S "$1")/marshal/app.signers"; }
EN() { echo "$(S "$1")/marshal/app.enabled"; }
fb() { local n d; for n in "$@"; do for d in "$T"/m/*; do git -C "$d/app" branch "feature/$n" develop; done; done; }
tokof() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' "$T/o"; }
en() { local tk; XE "$1" marshal enable; tk=$(tokof); XE "$1" marshal enable --plan "$tk" --approved "$WORDS"; }
OWN() { # MACHINE ARGS...: an owner verb of the marshal, the plan and then the apply with the token and the words; the apply's status (97: no token)
  local m=$1 tk; shift
  XE "$m" marshal "$@"; tk=$(tokof)
  [ -n "$tk" ] || return 97
  XE "$m" marshal "$@" --plan "$tk" --approved "$WORDS"
}
OG() { git --git-dir="$ORIGIN" "$@"; }
oref() { OG rev-parse -q --verify "$1" 2>/dev/null || echo none; }
ocount() { OG rev-list --count "$1" 2>/dev/null || echo 0; }
orec() { OG cat-file -p "$1:record.json" 2>/dev/null; }
jsf() { orec "$1" | jq -r "$2" 2>/dev/null; }                  # a field of the record at an origin ref
js() { XE "$1" marshal status "$2" --json; tr -d ' \n' < "$T/o"; }   # `status NAME --json` of a machine, without blanks

# --- the independent implementation of the spec's signing format (the test's own, never qargi's)
cat > "$T/sigtool.py" <<'PY'
import hashlib, json, os, re, subprocess, sys, tempfile
SSHK, GIT = os.environ["REAL_SSHK"], os.environ["REAL_GIT"]
def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
def payload(project, feature, kind, rec, parent):
    lead = rec.get("lead"); lid = lead.get("id") if isinstance(lead, dict) else None
    return canon({"v": 1, "ns": "qargi-marshal", "project": project, "feature": feature, "kind": kind, "rev": rec["rev"], "parent": parent,
                  "lead": lid, "record_sha256": hashlib.sha256(canon(rec).encode()).hexdigest()}).encode()
def git(gd, *a): return subprocess.run([GIT, "--git-dir", gd, *a], capture_output=True, check=True).stdout
def main():
    cmd = sys.argv[1]
    if cmd == "sign":      # KEY NS PROJECT FEATURE KIND PARENT|- RECFILE: the armored signature on stdout
        key, ns, project, feature, kind, parent, recfile = sys.argv[2:9]
        rec = json.load(open(recfile))
        data = payload(project, feature, kind, rec, None if parent == "-" else parent)
        r = subprocess.run([SSHK, "-Y", "sign", "-f", key, "-n", ns], input=data, capture_output=True)
        if r.returncode: sys.stderr.write(r.stderr.decode()); sys.exit(1)
        sys.stdout.write(r.stdout.decode())
    elif cmd == "check":   # GITDIR COMMIT PROJECT KIND SIGNERS: 0 when the commit's signature verifies by the spec's rules
        gd, c, project, kind, signers = sys.argv[2:7]
        msg = git(gd, "cat-file", "commit", c).decode().split("\n\n", 1)[1]
        blocks = re.findall(r"-----BEGIN SSH SIGNATURE-----\n.*?-----END SSH SIGNATURE-----", msg, re.S)
        if len(blocks) != 1 or len(msg.encode()) > 8192 or len(blocks[0].encode()) > 2048: sys.exit("bad block count or size")
        rec = json.loads(git(gd, "cat-file", "-p", c + ":record.json"))
        if rec.get("sig_v") != 1 or not isinstance(rec.get("signer"), str): sys.exit("no sig_v 1 or signer")
        if kind == "done": parent = rec.get("features_oid")   # a done commit is a root; the oid of the last features record is in the record and signed
        else:
            try: parent = git(gd, "rev-parse", "-q", "--verify", c + "^").decode().strip()
            except subprocess.CalledProcessError: parent = None
        data = payload(project, rec["feature"], kind, rec, parent)
        with tempfile.TemporaryDirectory() as d:
            sf = os.path.join(d, "sig"); open(sf, "w").write(blocks[0] + "\n")
            r = subprocess.run([SSHK, "-Y", "verify", "-f", signers, "-I", rec["signer"], "-n", "qargi-marshal", "-s", sf], input=data, capture_output=True)
        if r.returncode: sys.exit("verify failed: " + r.stderr.decode() + r.stdout.decode())
main()
PY
ST() { REAL_SSHK=$REALSSHK REAL_GIT=$REALGIT python3 -I "$T/sigtool.py" "$@"; }
: > "$T/ste"
vok() { ST check "$ORIGIN" "$1" app "$2" "$3" 2>"$T/ste"; }          # COMMIT KIND SIGNERS-FILE
chain_ok() { # REF SIGNERS: every commit on the ref verifies, parent signed, and the revs go up
  local c kind=${1#refs/qargi/} prev=0 rv; kind=${kind%%/*}
  for c in $(OG rev-list --reverse "$1"); do
    vok "$c" "$kind" "$2" || { echo "commit $c: $(cat "$T/ste" 2>/dev/null)"; return 1; }
    rv=$(OG cat-file -p "$c:record.json" | jq -r .rev); [ "$rv" -gt "$prev" ] 2>/dev/null || { echo "rev $rv not above $prev"; return 1; }; prev=$rv
  done
  [ "$prev" -gt 0 ]
}
mkrec() { # NAME LEAD REV SIGNER [JQFILTER]: $T/rec.NAME holds a record; SIGNER - adds no sig_v and signer
  jq -nc --arg f "$1" --arg l "$2" --argjson r "$3" --arg s "$4" '{feature:$f, project:"app", status:"active", goal:("g"+$f), rev:$r, lead:{id:$l, user:"m", host:"h", since:"2026-01-01T00:00:00Z"}, renewed_at:"2026-01-01T00:00:00Z", updated_at:"2026-01-01T00:00:00Z"} | if $s == "-" then . else . + {sig_v:1, signer:$s} end | '"${5:-.}" > "$T/rec.$1"
}
head -c 3000 /dev/zero | tr '\0' A | fold -w 64 > "$T/pad.txt"
forge() { # KIND FEATURE PARENT|- KEYFILE NS RECFILE [MODE]: a commit with a signed record, written to the origin; prints its oid
  local kind=$1 feat=$2 parent=$3 key=$4 ns=$5 rec=$6 mode=${7:-ok} sig blob trr msg
  sig=$(ST sign "$key" "$ns" app "$feat" "$kind" "$parent" "$rec") || return 1
  case $mode in
    ok) ;;
    nosig) sig='' ;;
    twice) sig=$sig$'\n'$sig ;;
    bigblk) sig=$(printf '%s\n' "$sig" | sed "1r $T/pad.txt") ;;
    badb64) sig=$(printf '%s\n' "$sig" | sed '1a !!!not~base64***') ;;
    hugemsg) sig=$sig$'\n'$(head -c 9000 /dev/zero | tr '\0' x) ;;
  esac
  msg=$(printf 'marshal %s\n\n%s\n' "$feat" "$sig")
  blob=$(OG hash-object -w "$rec"); trr=$(printf '100644 blob %s\trecord.json\n' "$blob" | OG mktree)
  if [ "$parent" = - ]; then OG commit-tree -m "$msg" "$trr"; else OG commit-tree -p "$parent" -m "$msg" "$trr"; fi
}
plantf() { local c; c=$(forge "$@") && OG update-ref "refs/qargi/$1/$2" "$c"; }    # plantf KIND FEATURE ... (as forge)
copyto() { # SRCREF DSTREF JQFILTER: a root commit at DSTREF with the message of SRCREF's head and its record changed by the filter
  local c blob trr msg new
  c=$(oref "$1"); msg=$(OG show -s --format=%B "$c")
  blob=$(orec "$1" | jq -c "$3" | OG hash-object -w --stdin); trr=$(printf '100644 blob %s\trecord.json\n' "$blob" | OG mktree)
  new=$(OG commit-tree -m "$msg" "$trr") && OG update-ref "$2" "$new"
}
tamper() { # NAME JQFILTER: features/NAME becomes a commit with the same parent and message and a changed record
  local ref=refs/qargi/features/$1 c blob trr msg par new
  c=$(oref "$ref"); msg=$(OG show -s --format=%B "$c"); par=$(OG rev-parse -q --verify "$c^" 2>/dev/null || true)
  blob=$(orec "$ref" | jq -c "$2" | OG hash-object -w --stdin); trr=$(printf '100644 blob %s\trecord.json\n' "$blob" | OG mktree)
  if [ -n "$par" ]; then new=$(OG commit-tree -p "$par" -m "$msg" "$trr"); else new=$(OG commit-tree -m "$msg" "$trr"); fi
  OG update-ref "$ref" "$new"
}
# Where an owner verb is missing the test does the same thing by hand (the key file, the signers file and the switch file are
# plain files named in the spec) AFTER the case about the verb has been judged, so that every later case is judged on its own.
hand() { echo "note: $1 (done by hand so that the later cases can be judged)"; }
ensure_key() { # MACHINE PRINCIPAL: a key made by hand when key init did not make one
  [ -f "$(KEY "$1")" ] && return 0
  mkdir -p "$(dirname "$(KEY "$1")")"; "$REALSSHK" -q -t ed25519 -N '' -C "$2" -f "$(KEY "$1")" >/dev/null 2>&1; chmod 600 "$(KEY "$1")"; hand "key of $1"
}
lineof() { # MACHINE PRINCIPAL: the signers line of the key of a machine
  printf '%s namespaces="qargi-marshal" %s\n' "$2" "$(cut -d' ' -f1,2 "$(KEY "$1").pub" 2>/dev/null)"
}
addsig() { # MACHINE LINE
  grep -qxF -- "$2" "$(SIG "$1")" 2>/dev/null && return 0
  mkdir -p "$(dirname "$(SIG "$1")")"; printf '%s\n' "$2" >> "$(SIG "$1")"; hand "signers line on $1"
}
delsig() { # MACHINE PRINCIPAL
  grep -q "^$2 " "$(SIG "$1")" 2>/dev/null || return 0
  grep -v "^$2 " "$(SIG "$1")" > "$T/sig.tmp"; cp "$T/sig.tmp" "$(SIG "$1")"; hand "signers remove on $1"
}
setmode() { # MACHINE MODE: the switch file's field integrity
  [ "$(jq -r '.integrity // "off"' "$(EN "$1")" 2>/dev/null)" = "$2" ] && return 0
  jq --arg m "$2" '.integrity = $m' "$(EN "$1")" > "$T/en.tmp" && cp "$T/en.tmp" "$(EN "$1")"; hand "integrity $2 on $1"
}
mode() { OWN "$1" enable --integrity "$2" >/dev/null 2>&1; setmode "$1" "$2"; }
nocntrl() { ! LC_ALL=C grep -q '[[:cntrl:]]' <(tr -d '\n\t' < "$1"); }
cleanrun() { ! grep -q Traceback "$T/e" "$T/o"; }
# INVALID_ADV MACHINE NAME PATTERN DESC: advisory reader shows the record (pattern in --json) and tags it INVALID, not unsigned
adv_invalid() {
  local j; j=$(js "$1" "$2"); XE "$1" marshal status "$2"
  if [[ $j == *"$3"* ]] && grep -qE 'INVALID|cannot verify' <(out) && ! grep -qw unsigned <(out) && cleanrun; then ok "advisory: $4 is used and tagged INVALID"
  else no "SPEC advisory: $4 must be used and tagged INVALID (json has pattern $3: $([[ $j == *"$3"* ]] && echo yes || echo no)): $(out)"; fi
}
# strict_ignored MACHINE NAME PATTERN DESC: strict reader does not show the record and warns naming the ref
strict_ignored() {
  local j; j=$(js "$1" "$2"); XE "$1" marshal status "$2"
  if [[ $j != *"$3"* ]] && grep -qi warn <(out) && grep -qF -e "$2" <(out) && cleanrun; then ok "strict: $4 is ignored with a warning naming the ref"
  else no "SPEC strict: $4 must be ignored with a warning naming $2 (json has pattern $3: $([[ $j == *"$3"* ]] && echo yes || echo no)): $(out)"; fi
}

mk a; mk b; mk ra; mk rs; mk ro; mk km
fb off1 s1 s2 tmo tamlead tamrev tamstat cpsrc cpk2 cppx rp1 tmj tmj2 tmr tw3 st1 rsg1 del1 fin1 rot1 rot2 rv1 rv2 sl1
for m in a b ra rs ro; do en "$m" || no "setup: enable of $m"; done

# ============================================================ (1) integrity is off by default; an unkeyed machine writes unsigned records
jq -e '(.integrity // "off") == "off"' "$(EN a)" >/dev/null 2>&1 && ok "default: after enable the switch file has no integrity field or off" || no "SPEC integrity defaults to off: $(cat "$(EN a)" 2>&1)"
XE a marshal claim off1 --as alice --goal local; rc=$?
orec refs/qargi/features/off1 | jq -e 'has("sig_v") == false and has("signer") == false' >/dev/null 2>&1 && ! OG cat-file commit "$(oref refs/qargi/features/off1)" | grep -q 'BEGIN SSH SIGNATURE' && [ $rc = 0 ] \
  && ok "off: with integrity off a claim has no sig_v, no signer and no signature in the commit" || no "SPEC off = today: record $(orec refs/qargi/features/off1), rc=$rc: $(out)"
XE ro marshal status off1; rc=$?
[ $rc = 0 ] && grep -q alice <(out) && ok "off: the unsigned record is read as before" || no "SPEC off reads unsigned records (rc=$rc): $(out)"
[ ! -e "$(KEY a)" ] && ok "default: no key exists before key init" || no "a key exists before key init: $(ls "$(KEY a)")"

# ============================================================ (2) key init: owner-gated, 0600, never overwritten
PA=alice@ms; PB=bob@ms; PS=sam@ms; PA2=alice2@ms
XE a marshal key init --principal "$PA"; ra1=$?; tk=$(tokof)
if [ -n "$tk" ] && [ ! -e "$(KEY a)" ]; then ok "key init: without options it prints a plan token and creates no key"; else no "SPEC key init plan: token '$tk', key: $(ls "$(KEY a)" 2>&1), rc=$ra1: $(out)"; fi
XE a marshal key init --principal "$PA" --approved "$WORDS"; r1=$?
XE a marshal key init --principal "$PA" --plan "${tk:-none}"; r2=$?
XE a marshal key init --principal "$PA" --plan 000000000000 --approved "$WORDS"; r3=$?
if [ $r1 != 0 ] && [ $r2 != 0 ] && [ $r3 != 0 ] && [ ! -e "$(KEY a)" ]; then ok "key init: refused without the plan token, without words and with a wrong token (nothing created)"
else no "SPEC key init gate: rc without token $r1, without words $r2, wrong token $r3, key: $(ls "$(KEY a)" 2>&1)"; fi
OWN a key init --principal "$PA"; rc=$?; cp "$T/o" "$T/ki.a"; cp "$T/e" "$T/ki.a.e"
LA=$(grep -m1 'namespaces="qargi-marshal" ssh-ed25519 ' "$T/ki.a" | sed 's/^[[:space:]]*//')
if [ $rc = 0 ] && [ -f "$(KEY a)" ] && [ "$(stat -c %a "$(KEY a)" 2>/dev/null)" = 600 ] && [ "${LA%% *}" = "$PA" ]; then
  ok "key init: exit 0, \$QARGI_CONF/credentials/marshal_ed25519 is mode 0600 and the signers line is printed"
else no "SPEC key init (rc=$rc): key mode $(stat -c %a "$(KEY a)" 2>&1), line '$LA': $(cat "$T/ki.a" "$T/ki.a.e")"; fi
jq -e --arg w "$WORDS" 'select((.verb // "") | startswith("marshal:key")) | select(.approved == $w)' "$(S a)/audit.log" >/dev/null 2>&1 \
  && ok "key init: an audit line marshal:key... with the words" || no "SPEC key init is audited: $(cat "$(S a)/audit.log" 2>&1)"
cp "$(KEY a)" "$T/keya.before"
OWN a key init --principal other@ms; rc=$?
[ $rc != 0 ] && cmp -s "$(KEY a)" "$T/keya.before" && ok "key init: a second run is refused and the key is untouched" || no "SPEC key init must not overwrite a key (rc=$rc): $(out)"
OWN b key init --principal "$PB"; cp "$T/o" "$T/ki.b"; LB=$(grep -m1 'namespaces="qargi-marshal" ssh-ed25519 ' "$T/ki.b" | sed 's/^[[:space:]]*//')
OWN rs key init --principal "$PS"; cp "$T/o" "$T/ki.rs"; LS=$(grep -m1 'namespaces="qargi-marshal" ssh-ed25519 ' "$T/ki.rs" | sed 's/^[[:space:]]*//')
[ -n "$LB" ] && [ -n "$LS" ] && [ -f "$(KEY b)" ] && [ -f "$(KEY rs)" ] || no "SPEC key init of b and rs (lines '$LB' '$LS')"
ensure_key a "$PA"; ensure_key b "$PB"; ensure_key rs "$PS"
[ -n "$LA" ] || LA=$(lineof a "$PA"); [ -n "$LB" ] || LB=$(lineof b "$PB"); [ -n "$LS" ] || LS=$(lineof rs "$PS")
NEEDLE_A=$(sed -n 3p "$(KEY a)" 2>/dev/null)          # a line of the private key, to look for in places it must never be

# ============================================================ (3) the signers file
XE a marshal signers list; [[ -z $(cat "$T/o") || $(cat "$T/o") != *"$PA"* ]] && ok "signers: nothing trusted before the first add" || no "signers list before add: $(out)"
OWN a signers add --line "this is not a signers line"; rc=$?
[ $rc != 0 ] && { [ ! -e "$(SIG a)" ] || ! grep -q 'not a signers' "$(SIG a)"; } && ok "signers add: a text that is not a signers line is refused" || no "SPEC signers add must refuse garbage (rc=$rc): $(out)"
OWN a signers add --line "$LB"$'\n'"$LS"; rc=$?
{ [ $rc != 0 ] || [ ! -e "$(SIG a)" ] || [ "$(grep -c . "$(SIG a)")" -le 1 ]; } && ! { [ -e "$(SIG a)" ] && grep -q "$PS" "$(SIG a)"; } && ok "signers add: a line with a newline in it is refused (no second line smuggled in)" || no "SPEC signers add one line only (rc=$rc): $(cat "$(SIG a)" 2>&1)"
XE a marshal signers add --line "$LA" --approved "$WORDS"; rc=$?
{ [ $rc != 0 ] && { [ ! -e "$(SIG a)" ] || ! grep -q "$PA" "$(SIG a)"; }; } && ok "signers add: refused without the plan token" || no "SPEC signers add needs the plan token (rc=$rc)"
trust() { local m=$1 l; shift; for l in "$@"; do OWN "$m" signers add --line "$l" >/dev/null 2>&1; done; }
trust a "$LA" "$LB"; trust b "$LA" "$LB"; trust ra "$LA" "$LB"; trust rs "$LA" "$LB" "$LS"; trust ro "$LA" "$LB"
{ grep -qF "$LA" "$(SIG a)" && grep -qF "$LB" "$(SIG a)"; } 2>/dev/null && ok "signers add: the lines are in \$STATE/marshal/app.signers" || no "SPEC signers file $(SIG a): $(cat "$(SIG a)" 2>&1)"
XE a marshal signers list; grep -q "$PA" "$T/o" && grep -q "$PB" "$T/o" && ok "signers list: prints the trusted principals" || no "SPEC signers list: $(out)"
# the signers file and the key are never in the repository
! git -C "$T/m/a/app" ls-files | grep -qE 'signers|marshal_ed25519' && ok "signers: not in the repository" || no "signers or key tracked in the repository"
for m in a b ra ro; do addsig "$m" "$LA"; addsig "$m" "$LB"; done; addsig rs "$LA"; addsig rs "$LB"; addsig rs "$LS"

# ============================================================ (4) the integrity switch
cp "$(EN rs)" "$T/en.before"
XE rs marshal enable --integrity strict --approved "$WORDS"; r1=$?
XE rs marshal enable --integrity strict --plan 000000000000 --approved "$WORDS"; r2=$?
XE rs marshal enable --integrity paranoid; tk=$(tokof); XE rs marshal enable --integrity paranoid --plan "${tk:-x}" --approved "$WORDS"; r3=$?
if [ $r1 != 0 ] && [ $r2 != 0 ] && [ $r3 != 0 ] && cmp -s "$(EN rs)" "$T/en.before"; then ok "integrity: refused without a plan token, with a wrong token and for an unknown mode (switch file unchanged)"
else no "SPEC enable --integrity gate: rc $r1 $r2 $r3, file: $(cat "$(EN rs)")"; fi
OWN rs enable --integrity strict; rc=$?
jq -e --arg w "$WORDS" '.integrity == "strict" and .backend == "refs" and (.remote | length > 0)' "$(EN rs)" >/dev/null 2>&1 && [ $rc = 0 ] && ok "integrity: strict with the plan token and the words; backend and remote stay" || no "SPEC enable --integrity strict (rc=$rc): $(cat "$(EN rs)"; out)"
jq -e --arg w "$WORDS" 'select(.verb == "marshal:enable" and .approved == $w)' "$(S rs)/audit.log" >/dev/null 2>&1 && ok "integrity: audited as marshal:enable" || no "SPEC integrity audit: $(cat "$(S rs)/audit.log" 2>&1)"
for m in a b ra; do OWN "$m" enable --integrity advisory >/dev/null 2>&1; done
jq -e '.integrity == "advisory"' "$(EN a)" >/dev/null 2>&1 && ok "integrity: advisory is the field integrity of the switch file" || no "SPEC switch file field integrity: $(cat "$(EN a)")"
jq -e '(.integrity // "off") == "off"' "$(EN ro)" >/dev/null 2>&1 && ok "integrity: ro is still off" || no "ro changed: $(cat "$(EN ro)")"
for m in a b ra; do setmode "$m" advisory; done; setmode rs strict

# ============================================================ (5) a signed claim and the chain after it
XE a marshal claim s1 --as alice --goal "signed goal"; rc=$?; S1=refs/qargi/features/s1
C1=$(oref $S1)
if [ $rc = 0 ] && orec $S1 | jq -e --arg p "$PA" '.sig_v == 1 and .signer == $p and .lead.id == "alice"' >/dev/null 2>&1; then ok "signed claim: the record has sig_v 1 and signer ($PA)"
else no "SPEC signed claim fields (rc=$rc): $(orec $S1; out)"; fi
{ [ "$(OG cat-file commit "$C1" | grep -c 'BEGIN SSH SIGNATURE')" = 1 ] && [ "$(OG cat-file commit "$C1" | wc -c)" -le 8192 ]; } && vok "$C1" features "$(SIG a)" \
  && ok "signed claim: one armored block in the commit message (<= 8 KiB) that ssh-keygen verifies against the spec's payload" || no "SPEC signed claim signature does not verify: $(cat "$T/ste" 2>/dev/null)"
for step in "set s1 --as alice --goal g2" "renew s1 --as alice" "set s1 --as alice --status blocked"; do
  # shellcheck disable=SC2086  # the words of a step
  XE a marshal $step || no "signed chain step '$step': $(out)"
done
r=$(chain_ok $S1 "$(SIG a)") && [ "$(ocount $S1)" = 4 ] && ok "signed chain: all four commits verify, each signs its real parent, revs go up" || no "SPEC signed chain: $r"
XE b marshal claim s2 --as bob; rc=$?
{ [ $rc = 0 ] && chain_ok refs/qargi/features/s2 "$(SIG b)" >/dev/null && [ "$(jsf refs/qargi/features/s2 .signer)" = "$PB" ]; } && ok "signed claim: machine b signs with its own key (signer $PB)" || no "SPEC b's signed claim (rc=$rc): $(orec refs/qargi/features/s2; out)"
XE ra marshal status s1 --as zed; rc=$?; ra_out=$(out)
{ [ $rc = 0 ] && grep -q alice <<<"$ra_out" && grep -qw signed <<<"$ra_out" && ! grep -q INVALID <<<"$ra_out"; } && ok "advisory reader: status shows the record tagged signed" || no "SPEC advisory status tags signed (rc=$rc): $ra_out"
XE rs marshal status s1 --as zed; rc=$?
{ [ $rc = 0 ] && grep -q alice <(out) && grep -qw signed <(out) && ! grep -qi warn "$T/e"; } && ok "strict reader: a valid signed record is shown, tagged signed, without a warning" || no "SPEC strict reads valid records (rc=$rc): $(out)"
jq -e --arg r "$(jsf $S1 .rev)" --arg o "$(oref $S1)" '.s1 == [($r | tonumber), $o]' "$(S rs)/features/.accepted-app.json" >/dev/null 2>&1 \
  && ok "high-water mark: \$STATE/features/.accepted-app.json {s1: [rev, oid]} holds the head just read" || no "SPEC accepted mark: $(cat "$(S rs)/features/.accepted-app.json" 2>&1)"
XE ro marshal status s2; rc=$?
{ [ $rc = 0 ] && grep -q bob <(out) && ! grep -qi 'warn\|invalid' <(out); } && ok "old client: an integrity-off reader reads a signed record (extra keys, signature in the message) without complaint" || no "SPEC old clients read signed records (rc=$rc): $(out)"
XE a marshal finish s1 --as alice; rc=$?
[ $rc = 0 ] && [ "$(oref $S1)" = none ] && chain_ok refs/qargi/done/s1 "$(SIG a)" >/dev/null && ok "signed finish: refs/qargi/done/s1 is signed with kind done" || no "SPEC signed finish (rc=$rc): $(out); $(cat "$T/ste" 2>&1)"
! OG cat-file --batch-all-objects --batch | grep -aq 'namespaces="qargi-marshal"' && [ "$(OG for-each-ref --format='%(refname)' | grep -vc '^refs/\(qargi/\(features\|done\)/\|heads/\)')" = 0 ] \
  && ok "refs: no signers line and no ref outside refs/qargi/features, done and heads on the origin" || no "signers line or a stray ref on the origin: $(OG for-each-ref)"

# ============================================================ (6) ssh-keygen that hangs: bounded, cannot verify
XE a marshal claim tmo --as alice >/dev/null 2>&1
touch "$T/sk.slow"; t0=$(date +%s)
timeout 100 env HOME="$T/m/rs/home" QARGI_CONF="$T/m/rs/c" QARGI_STATE="$T/m/rs/s" QARGI_REMOTE_TIMEOUT=2 "$DA" marshal status tmo >"$T/o" 2>"$T/e"; rc=$?
el=$(( $(date +%s) - t0 )); rm -f "$T/sk.slow"
if [ $rc != 124 ] && [ $el -lt 90 ] && cleanrun && ! grep -q '"id": *"alice"' "$T/o" && grep -qi warn <(out) && grep -q 'verify' "$SKLOG"; then
  ok "hang: a verification that hangs ends in $el s; in strict the record is ignored with a warning, no crash"
else no "SPEC ssh-keygen verification needs a timeout (rc=$rc after ${el}s, verify calls: $(grep -c verify "$SKLOG")): $(out)"; fi

# ============================================================ (7) forged records: a positive control, then the rejections
EVIL=$T/evilkey; "$REALSSHK" -q -t ed25519 -N '' -C evil -f "$EVIL" >/dev/null 2>&1
mkrec fkctl xfkctl 1 "$PA"; plantf features fkctl - "$(KEY a)" qargi-marshal "$T/rec.fkctl"
CT1=$(oref refs/qargi/features/fkctl)
mkrec fkctl xfkctl 2 "$PA"; plantf features fkctl "$CT1" "$(KEY a)" qargi-marshal "$T/rec.fkctl"
adv_ctl=$(js ra fkctl); XE ra marshal status fkctl; rcs=$?
{ [[ $adv_ctl == *'"id":"xfkctl"'* && $adv_ctl == *'"rev":2'* ]] && [ $rcs = 0 ] && grep -qw signed <(out) && ! grep -qE 'INVALID|rollback' <(out); } \
  && ok "positive control: a record the test signed by the spec's format (two revs, a chain) is shown signed by an advisory reader" || no "SPEC format: the test's own validly signed chain must verify: $(out)"
js rs fkctl | grep -q '"id":"xfkctl"' && XE rs marshal status fkctl && grep -qw signed <(out) && ! grep -qi 'warn' "$T/e" && ok "positive control: and by a strict reader, tagged signed, no warning" || no "SPEC format: strict must accept the test's validly signed chain: $(out)"
mkrec fkunk xfkunk 1 mallory@evil; plantf features fkunk - "$EVIL" qargi-marshal "$T/rec.fkunk"
mkrec fkkey xfkkey 1 "$PA"; plantf features fkkey - "$EVIL" qargi-marshal "$T/rec.fkkey"
mkrec fkbkey xfkbkey 1 "$PA"; plantf features fkbkey - "$(KEY b)" qargi-marshal "$T/rec.fkbkey"
mkrec fkns xfkns 1 "$PA"; plantf features fkns - "$(KEY a)" some-other-ns "$T/rec.fkns"
mkrec fknosig xfknosig 1 "$PA"; plantf features fknosig - "$(KEY a)" qargi-marshal "$T/rec.fknosig" nosig
mkrec fkv2 xfkv2 1 "$PA" '.sig_v = 2'; plantf features fkv2 - "$(KEY a)" qargi-marshal "$T/rec.fkv2"
# a genuine record changed after signing: lead, rev, status
for n in tamlead tamrev tamstat; do XE a marshal claim "$n" --as alice >/dev/null 2>&1 || no "setup: claim $n"; done
tamper tamlead '.lead.id = "xtamlead"'; tamper tamrev '.rev = 7'; tamper tamstat '.status = "blocked"'
# copied to another feature, another kind, another project
XE a marshal claim cpsrc --as xcpsrc >/dev/null 2>&1; XE a marshal claim cpk2 --as xcpsrc >/dev/null 2>&1; XE a marshal claim cppx --as xcppx >/dev/null 2>&1
copyto refs/qargi/features/cpsrc refs/qargi/features/cpfeat '.feature = "cpfeat"'
copyto refs/qargi/features/cpk2 refs/qargi/done/cpk2 '.'; OG update-ref -d refs/qargi/features/cpk2
for spec in 'fkunk|"id":"xfkunk"|a record signed by an unknown key' 'fkkey|"id":"xfkkey"|a record naming a trusted signer but signed with another key' \
            'fkbkey|"id":"xfkbkey"|a record signed by b'"'"'s key but claiming to be alice'"'"'s' 'fkns|"id":"xfkns"|a record signed in another namespace' \
            'fknosig|"id":"xfknosig"|a record with sig_v 1 and no signature block' 'fkv2|"id":"xfkv2"|a record with an unknown sig_v' \
            'tamlead|"id":"xtamlead"|a record whose lead was changed after signing' 'tamrev|"rev":7|a record whose rev was changed after signing' \
            'tamstat|"status":"blocked"|a record whose status was changed after signing' 'cpfeat|"id":"xcpsrc"|a record copied to another feature'; do
  IFS='|' read -r n pat desc <<<"$spec"; adv_invalid ra "$n" "$pat" "$desc"
done
XE ra marshal status --all --history; { grep -E 'cpk2.*INVALID|INVALID.*cpk2' <(out) >/dev/null || grep -qi 'warn.*cpk2' "$T/e"; } && ok "advisory: a features record copied to done/ (another kind) is not accepted as valid" || no "SPEC copied across kinds must be tagged INVALID: $(out)"
for spec in 'fkunk|"id":"xfkunk"|a record signed by an unknown key' 'fkkey|"id":"xfkkey"|a record naming a trusted signer but signed with another key' \
            'fkbkey|"id":"xfkbkey"|a record signed by b'"'"'s key but claiming to be alice'"'"'s' 'fkns|"id":"xfkns"|a record signed in another namespace' \
            'fknosig|"id":"xfknosig"|a record with sig_v 1 and no signature block' 'fkv2|"id":"xfkv2"|a record with an unknown sig_v' \
            'tamlead|"id":"xtamlead"|a record whose lead was changed after signing' 'tamrev|"rev":7|a record whose rev was changed after signing' \
            'tamstat|"status":"blocked"|a record whose status was changed after signing' 'cpfeat|"id":"xcpsrc"|a record copied to another feature'; do
  IFS='|' read -r n pat desc <<<"$spec"; strict_ignored rs "$n" "$pat" "$desc"
done
XE rs marshal status --all --history; grep -qi 'warn' "$T/e" && grep -qF cpk2 "$T/e" && ok "strict: a features record copied to done/ is ignored with a warning" || no "SPEC strict: done/cpk2 copied from a features record must warn: $(out)"
# another project: app2 on the same origin and the same keys must not accept app's record
jq '.project = "app2"' "$T/m/rs/c/projects/app.json" > "$T/m/rs/c/projects/app2.json"
XE rs QARGI_PROJECT=app2 marshal enable; tk=$(tokof); XE rs QARGI_PROJECT=app2 marshal enable --plan "$tk" --approved "$WORDS"
cp "$(SIG rs)" "$(S rs)/marshal/app2.signers" 2>/dev/null
XE rs QARGI_PROJECT=app2 marshal enable --integrity strict; tk=$(tokof); XE rs QARGI_PROJECT=app2 marshal enable --integrity strict --plan "$tk" --approved "$WORDS"
j=$(js rs cppx); XE rs QARGI_PROJECT=app2 marshal status cppx; j2=$(tr -d ' \n' < "$T/o")
{ [[ $j == *'"id":"xcppx"'* ]] && [[ $j2 != *'"id":"xcppx"'* ]] && grep -qi warn "$T/e"; } && ok "strict: a record of project app is not accepted by project app2 (same origin, same keys)" || no "SPEC a record copied to another project must be refused (json under app2: ${j2:0:200}): $(out)"
for n in fkunk fkkey fkbkey fkns fknosig fkv2 tamlead tamrev tamstat cpfeat; do
  XE ra marshal status "$n" >/dev/null 2>&1; XE rs marshal status "$n" >/dev/null 2>&1
done
jq -e '(has("fkunk") or has("fkkey") or has("fkbkey") or has("fkns") or has("fknosig") or has("fkv2") or has("tamlead") or has("tamrev") or has("tamstat") or has("cpfeat")) | not' "$(S rs)/features/.accepted-app.json" >/dev/null 2>&1 \
  && ok "high-water mark: a record that did not verify never enters it" || no "SPEC accepted mark holds an invalid record: $(cat "$(S rs)/features/.accepted-app.json" 2>&1)"

# ============================================================ (8) hostile signature payloads
mkrec hbigblk xhbigblk 1 "$PA"; plantf features hbigblk - "$(KEY a)" qargi-marshal "$T/rec.hbigblk" bigblk
mkrec h2blk xh2blk 1 "$PA"; plantf features h2blk - "$(KEY a)" qargi-marshal "$T/rec.h2blk" twice
mkrec hb64 xhb64 1 "$PA"; plantf features hb64 - "$(KEY a)" qargi-marshal "$T/rec.hb64" badb64
mkrec hmsg xhmsg 1 "$PA"; plantf features hmsg - "$(KEY a)" qargi-marshal "$T/rec.hmsg" hugemsg
mkrec hsigd xhsigd 1 "-oProxyCommand=false"; plantf features hsigd - "$(KEY a)" qargi-marshal "$T/rec.hsigd"
mkrec hsigc xhsigc 1 "ali"$'\033'"[31mce"$'\a'; plantf features hsigc - "$(KEY a)" qargi-marshal "$T/rec.hsigc"
mkrec hsign xhsign 1 "alice@ms -n x"; plantf features hsign - "$(KEY a)" qargi-marshal "$T/rec.hsign"
HOST="hbigblk h2blk hb64 hmsg hsigd hsigc hsign"
for n in $HOST; do strict_ignored rs "$n" "\"id\":\"x$n\"" "hostile signature '$n'"; done
for n in $HOST; do [ "$n" = hsigc ] || adv_invalid ra "$n" "\"id\":\"x$n\"" "hostile signature '$n'"; done
j=$(js ra hsigc); XE ra marshal status hsigc
{ nocntrl "$T/o" && nocntrl "$T/e" && cleanrun && { [[ $j != *'"id":"xhsigc"'* ]] && grep -qi warn "$T/e" || grep -q INVALID "$T/o"; }; } \
  && ok "advisory: a signer with control characters is either ignored with a warning or shown INVALID, and never echoed raw" || no "SPEC advisory: hostile signer with control characters: $(out | od -c | head -5)"
for who in ra rs; do
  XE $who marshal status --all --json; rc=$?
  { [ $rc = 0 ] && jq -e . "$T/o" >/dev/null 2>&1 && cleanrun && nocntrl "$T/o"; } && ok "hostile: $who: status --all --json is valid JSON, exit 0, no traceback, no control character" || no "SPEC hostile signatures, status --all --json on $who (rc=$rc): $(head -c 500 "$T/e")"
  XE $who marshal status --all --brief; rc=$?
  { [ $rc = 0 ] && nocntrl "$T/o" && nocntrl "$T/e" && cleanrun; } && ok "hostile: $who: --brief and the warnings print no control character (the signer field is not echoed raw)" || no "SPEC hostile: control characters in output of $who (rc=$rc)"
done
# the signers file as a symlink: nothing is trusted through it and nothing is written through it
XE a marshal claim sl1 --as xsl1 >/dev/null 2>&1
cp "$(SIG rs)" "$T/signers.real"; rm -f "$(SIG rs)"; ln -s "$T/signers.real" "$(SIG rs)"
strict_ignored rs sl1 '"id":"xsl1"' "a genuine record when the signers file is a symlink"
"$REALSSHK" -q -t ed25519 -N '' -C ev2 -f "$T/ev2" >/dev/null 2>&1
OWN rs signers add --line "evil@x namespaces=\"qargi-marshal\" $(cut -d' ' -f1,2 "$T/ev2.pub")" >/dev/null 2>&1
cmp -s "$T/signers.real" <(cat "$T/signers.real") && ! grep -q 'evil@x' "$T/signers.real" && ok "signers: nothing is written through a symlinked signers file" || no "SPEC a signers symlink must not be written through: $(cat "$T/signers.real")"
rm -f "$(SIG rs)"; cp "$T/signers.real" "$(SIG rs)"
for n in $HOST fkunk fkkey fkbkey fkns fknosig fkv2 tamlead tamrev tamstat cpfeat sl1; do OG update-ref -d "refs/qargi/features/$n"; done
OG update-ref -d refs/qargi/done/cpk2

# ============================================================ (9) rollback: replayed, forked and rewritten history
XE a marshal claim rp1 --as alice --goal gtone >/dev/null 2>&1; R1=$(oref refs/qargi/features/rp1)
XE a marshal set rp1 --as alice --goal gttwo >/dev/null 2>&1; R2=$(oref refs/qargi/features/rp1)
XE a marshal set rp1 --as alice --goal gtthree >/dev/null 2>&1; R3=$(oref refs/qargi/features/rp1)
XE ra marshal status rp1 >/dev/null 2>&1; XE rs marshal status rp1 >/dev/null 2>&1
jq -e --arg o "$R3" '.rp1[1] == $o' "$(S rs)/features/.accepted-app.json" >/dev/null 2>&1 && ok "rollback: the readers accepted rev 3 of rp1" || no "setup: accepted mark of rp1: $(cat "$(S rs)/features/.accepted-app.json" 2>&1)"
rb() { # DESC GOALNOTSHOWN: both readers say rollback detected; strict still shows the accepted goal
  local who j
  for who in ra rs; do
    XE $who marshal status rp1
    grep -q 'rollback detected' <(out) && cleanrun && ok "rollback: $1: $who says 'rollback detected'" || no "SPEC rollback ($1) on $who must say 'rollback detected': $(out)"
  done
  j=$(js rs rp1); [[ $j == *'"goal":"gtthree"'* && $j != *"$2"* ]] && ok "rollback: $1: the strict reader keeps the accepted record" || no "SPEC rollback ($1): strict must fall back to the accepted gtthree, not show $2: ${j:0:300}"
}
OG update-ref refs/qargi/features/rp1 "$R1"; rb "an older valid record replayed" '"goal":"gtone"'
OG update-ref refs/qargi/features/rp1 "$R2"; rb "the previous valid record replayed" '"goal":"gttwo"'
mkrec rp1 alice 3 "$PA" '.goal = "gtfork"'; plantf features rp1 "$R2" "$(KEY a)" qargi-marshal "$T/rec.rp1"
rb "a validly signed sibling at the same rev but another oid" '"goal":"gtfork"'
mkrec rp1 alice 9 "$PA" '.goal = "gtroot"'; plantf features rp1 - "$(KEY a)" qargi-marshal "$T/rec.rp1"
rb "a validly signed record at a higher rev that does not descend from the accepted one" '"goal":"gtroot"'
OG update-ref refs/qargi/features/rp1 "$R3"
XE rs marshal status rp1; XE rs marshal status rp1 >/dev/null 2>&1
jq -e --arg o "$R3" '.rp1[1] == $o' "$(S rs)/features/.accepted-app.json" >/dev/null 2>&1 && ok "rollback: the mark was not lowered by the attacks" || no "SPEC the mark must not go down: $(cat "$(S rs)/features/.accepted-app.json" 2>&1)"
OG update-ref refs/qargi/features/rp1 "$R1"
rm -f "$(S rs)/features/.accepted-app.json"
j=$(js rs rp1); XE rs marshal status rp1
{ [[ $j == *'"goal":"gtone"'* ]] && ! grep -q 'rollback detected' <(out); } && ok "rollback: a machine with no mark yet trusts what it first sees" || no "SPEC no mark: trust on first sight (json ${j:0:200}): $(out)"
OG update-ref refs/qargi/features/rp1 "$R3"

# ============================================================ (10) junk and replays do not renew a lease timer and do not block a feature
XE a marshal claim tmj --as alice >/dev/null 2>&1; XE a marshal claim tmj2 --as alice >/dev/null 2>&1
XE rs QARGI_MARSHAL_MONO=0 marshal status tmj --as sam >/dev/null 2>&1; XE rs QARGI_MARSHAL_MONO=0 marshal status tmj2 --as sam >/dev/null 2>&1
for n in tmj tmj2; do
  mkrec "$n" xjunk 99 -; c=$(OG commit-tree -p "$(oref refs/qargi/features/$n)" -m junk "$(printf '100644 blob %s\trecord.json\n' "$(OG hash-object -w "$T/rec.$n")" | OG mktree)") && OG update-ref refs/qargi/features/$n "$c"
done
XE rs QARGI_MARSHAL_MONO=$((TTL - 100)) marshal status tmj --as sam >/dev/null 2>&1
XE rs QARGI_MARSHAL_MONO=$((TTL + 1)) marshal takeover tmj --as sam --approved "$WORDS"; rc=$?
{ [ $rc = 0 ] && [ "$(jsf refs/qargi/features/tmj .lead.id)" = sam ] && [ "$(jsf refs/qargi/features/tmj .signer)" = "$PS" ] && vok "$(oref refs/qargi/features/tmj)" features "$(SIG rs)"; } \
  && ok "junk: a junk push on top of A's record did not restart the lease timer (takeover after the ttl from the first sight works, signed)" || no "SPEC junk pushes must not renew a lease (rc=$rc, lead $(jsf refs/qargi/features/tmj .lead.id)): $(out)"
XE a marshal renew tmj2 --as alice; rc=$?
{ [ $rc = 0 ] && [ "$(jsf refs/qargi/features/tmj2 .lead.id)" = alice ] && [ "$(jsf refs/qargi/features/tmj2 .signer)" = "$PA" ] && vok "$(oref refs/qargi/features/tmj2)" features "$(SIG a)"; } \
  && ok "junk: the lead can still renew the feature after a junk push (signed again); the feature is not blocked" || no "SPEC junk pushes must not block the lead (rc=$rc): $(out)"
XE rs marshal status tmj2 --as sam; [ "$(jsf refs/qargi/features/tmj2 .lead.id)" = alice ] && grep -q alice <(out) && ok "junk: a strict reader sees the lead's renewal" || no "strict reader after junk and renewal: $(out)"
XE a marshal claim tmr --as alice >/dev/null 2>&1; M1=$(oref refs/qargi/features/tmr)
XE a marshal renew tmr --as alice >/dev/null 2>&1; M2=$(oref refs/qargi/features/tmr)
XE rs QARGI_MARSHAL_MONO=0 marshal status tmr --as sam >/dev/null 2>&1
OG update-ref refs/qargi/features/tmr "$M1"; XE rs QARGI_MARSHAL_MONO=600 marshal status tmr --as sam >/dev/null 2>&1
OG update-ref refs/qargi/features/tmr "$M2"; XE rs QARGI_MARSHAL_MONO=601 marshal status tmr --as sam >/dev/null 2>&1
XE rs QARGI_MARSHAL_MONO=$((TTL + 1)) marshal takeover tmr --as sam --approved "$WORDS"; rc=$?
[ $rc = 0 ] && [ "$(jsf refs/qargi/features/tmr .lead.id)" = sam ] && ok "replay: a replayed older record did not restart the lease timer (the observed oid is the last accepted one)" || no "SPEC replays must not renew a lease (rc=$rc): $(out)"
XE a QARGI_MARSHAL_NOW=$(( $(date +%s) + 86400 )) marshal claim tw3 --as alice >/dev/null 2>&1
XE rs QARGI_MARSHAL_MONO=0 marshal status tw3 --as sam >/dev/null 2>&1
XE rs QARGI_MARSHAL_MONO=$((TTL + 1)) marshal takeover tw3 --as sam --approved "$WORDS"; rc=$?
[ $rc = 0 ] && [ "$(jsf refs/qargi/features/tw3 .lead.id)" = sam ] && ok "clock: a signed renewed_at a day in the future does not keep the lease alive (never compared with the local clock)" || no "SPEC signed timestamps are not compared with the local clock (rc=$rc): $(out)"

# ============================================================ (11) unsigned records: advisory uses and tags them, strict falls back, resign signs on top
XE a marshal claim st1 --as alice --goal gtsigned >/dev/null 2>&1
XE ra marshal status st1 >/dev/null 2>&1; XE rs marshal status st1 >/dev/null 2>&1
mode a off; XE a marshal set st1 --as alice --goal gtunsigned; rc=$?
mode a advisory
{ [ $rc = 0 ] && jsf refs/qargi/features/st1 'has("sig_v")' | grep -q false; } && ok "off: a writer with integrity off writes an unsigned record on top of a signed one" || no "setup: unsigned write on st1 (rc=$rc): $(orec refs/qargi/features/st1)"
j=$(js ra st1); XE ra marshal status st1
{ [[ $j == *'"goal":"gtunsigned"'* ]] && grep -qw unsigned <(out) && ! grep -q INVALID <(out); } && ok "advisory: an unsigned record is used and tagged unsigned" || no "SPEC advisory uses unsigned records and tags them (json ${j:0:200}): $(out)"
j=$(js rs st1); XE rs marshal status st1
{ [[ $j == *'"goal":"gtsigned"'* && $j != *'"goal":"gtunsigned"'* ]] && grep -qi warn <(out) && grep -qF st1 <(out); } && ok "strict: an unsigned record is ignored with a warning; the last accepted record (gtsigned) is shown" || no "SPEC strict falls back to the last accepted record (json ${j:0:200}): $(out)"
j=$(js ro st1); XE ro marshal status st1
{ [[ $j == *'"goal":"gtunsigned"'* ]] && ! grep -qi 'warn\|invalid' <(out); } && ok "off: an integrity-off reader uses the unsigned record as before" || no "SPEC off = today (json ${j:0:200}): $(out)"
XE a marshal claim rsg1 --as alice >/dev/null 2>&1; mode a off; XE a marshal set rsg1 --as alice --note unsignedwrite >/dev/null 2>&1
mode a advisory
G0=$(oref refs/qargi/features/rsg1); REV0=$(jsf refs/qargi/features/rsg1 .rev)
XE a marshal resign rsg1; r1=$?; [ "$(oref refs/qargi/features/rsg1)" = "$G0" ] && ok "resign: refused without --approved, nothing changed" || no "SPEC resign needs --approved W (rc=$r1)"
XE a marshal resign nosuchfeature --approved "$WORDS"; r2=$?; [ $r2 != 0 ] && ok "resign: a feature that is not open is refused" || no "SPEC resign of a missing feature must fail"
XE a marshal resign rsg1 --approved "$WORDS"; rc=$?
if [ $rc = 0 ] && [ "$(OG rev-parse "$(oref refs/qargi/features/rsg1)^")" = "$G0" ] && [ "$(jsf refs/qargi/features/rsg1 .rev)" = $((REV0 + 1)) ] && vok "$(oref refs/qargi/features/rsg1)" features "$(SIG a)"; then
  ok "resign: a signed commit, rev+1, on top of the unsigned open record"
else no "SPEC resign (rc=$rc): $(orec refs/qargi/features/rsg1; out; cat "$T/ste" 2>&1)"; fi
jq -e --arg w "$WORDS" 'select(.verb == "marshal:resign" and .approved == $w)' "$(S a)/audit.log" >/dev/null 2>&1 && ok "resign: audited as marshal:resign with the words" || no "SPEC resign audit line: $(tail -3 "$(S a)/audit.log")"
XE rs marshal status rsg1; grep -qw signed <(out) && ok "resign: a strict reader shows the re-signed record" || no "SPEC strict reads the re-signed record: $(out)"

# ============================================================ (12) a vanished ref warns, a finished one does not
XE a marshal claim del1 --as alice >/dev/null 2>&1; XE a marshal claim fin1 --as alice >/dev/null 2>&1
for who in ra rs; do XE $who marshal status --all --brief >/dev/null 2>&1; done
OG update-ref -d refs/qargi/features/del1; XE a marshal finish fin1 --as alice >/dev/null 2>&1
for who in ra rs; do
  XE $who marshal status --all --brief
  grep -i warn "$T/e" | grep -qF del1 && ok "deleted ref: $who warns that features/del1 vanished without a done record" || no "SPEC a ref that vanishes without a done/ record warns ($who): $(out)"
  ! grep -i warn "$T/e" | grep -qF fin1 && ok "deleted ref: $who does not warn about the finished fin1" || no "SPEC a finished feature must not warn ($who): $(out)"
done

# ============================================================ (13) revoked key and key rotation
XE b marshal claim rv1 --as bob >/dev/null 2>&1; XE b marshal claim rv2 --as bob >/dev/null 2>&1
XE ra marshal status rv1 >/dev/null 2>&1
OWN ra signers remove "$PB"; rc=$?; XE ra marshal signers list
{ [ $rc = 0 ] && ! grep -q "$PB" "$T/o" && grep -q "$PA" "$T/o"; } && ok "revoke: signers remove drops the principal" || no "SPEC signers remove (rc=$rc): $(out)"
delsig ra "$PB"
adv_invalid ra rv1 '"id":"bob"' "a record of a revoked key (advisory, seen before the revocation)"
OWN rs signers remove "$PB" >/dev/null 2>&1; delsig rs "$PB"; strict_ignored rs rv2 '"id":"bob"' "a record of a revoked key (strict)"
OWN ra signers add --line "$LB" >/dev/null 2>&1; OWN rs signers add --line "$LB" >/dev/null 2>&1; addsig ra "$LB"; addsig rs "$LB"
XE ra marshal status rv1; grep -qw signed <(out) && ! grep -q INVALID <(out) && ok "revoke: adding the key back makes its records valid again" || no "SPEC re-adding the key: $(out)"
# rotation: a's key is replaced by a new one under a new principal; the old principal is removed on the readers and on a
XE a marshal claim rot1 --as alice >/dev/null 2>&1; XE a marshal claim rot2 --as alice >/dev/null 2>&1
XE ra marshal status rot1 >/dev/null 2>&1; XE rs marshal status rot1 >/dev/null 2>&1
NEEDLE_A_BEFORE=$NEEDLE_A
rm -f "$T"/m/a/c/credentials/marshal_*
OWN a key init --principal "$PA2"; cp "$T/o" "$T/ki.a2"; LA2=$(grep -m1 'namespaces="qargi-marshal" ssh-ed25519 ' "$T/ki.a2" | sed 's/^[[:space:]]*//')
[ -f "$(KEY a)" ] && [ -n "$LA2" ] && ok "rotation: after the old key file is removed key init makes the new key" || no "SPEC key init after the removal of the old key (line '$LA2'): $(out)"
ensure_key a "$PA2"; [ -n "$LA2" ] || LA2=$(lineof a "$PA2")
NEEDLE_A2=$(sed -n 3p "$(KEY a)" 2>/dev/null)
for m in a ra rs; do OWN "$m" signers add --line "$LA2" >/dev/null 2>&1; OWN "$m" signers remove "$PA" >/dev/null 2>&1; addsig "$m" "$LA2"; delsig "$m" "$PA"; done
adv_invalid ra rot1 '"id":"alice"' "a record signed only by the removed old key (advisory)"
strict_ignored rs rot2 '"id":"alice"' "a never-read record signed only by the removed old key (strict)"
XE a marshal renew rot1 --as alice; r1=$?; XE a marshal renew rot2 --as alice; r2=$?
if [ $r1 = 0 ] && [ $r2 = 0 ] && [ "$(jsf refs/qargi/features/rot1 .signer)" = "$PA2" ] && vok "$(oref refs/qargi/features/rot1)" features "$(SIG a)" && vok "$(oref refs/qargi/features/rot2)" features "$(SIG a)"; then
  ok "rotation: a renewal re-signs with the new key (signer $PA2)"
else no "SPEC rotation, renewal re-signs (rc $r1 $r2): $(orec refs/qargi/features/rot1; out)"; fi
XE ra marshal status rot1; ra_out=$(out); j=$(js rs rot2); XE rs marshal status rot2
{ grep -qw signed <<<"$ra_out" && ! grep -q INVALID <<<"$ra_out" && [[ $j == *'"id":"alice"'* ]] && ! grep -qi warn "$T/e"; } && ok "rotation: after the renewal both readers show the records valid again" || no "SPEC rotation, valid again: $ra_out; $(out)"

# ============================================================ (14) member runs: key, signers, integrity and resign are refused
mkdir -p "$T/run/work"; echo build > "$T/run/ability"; : > "$T/run/refs.before"
cp "$(SIG a)" "$T/sig.a.before"; cp "$(EN a)" "$T/en.a.before"; cp "$(KEY a)" "$T/key.a.before"
n_all=$(nall); good=1
for v in "key init" "key init --principal x --approved w" "signers add --line $LB" "signers remove $PB" "enable --integrity strict" "enable --integrity strict --approved w" "resign rsg1 --approved w"; do
  # shellcheck disable=SC2086  # the words of a verb
  ( cd "$T/run/work" && XE km marshal $v ); rc=$?
  if [ $rc != 2 ] || ! grep -qi member "$T/e"; then good=0; no "SPEC member run: 'marshal $v' must exit 2 and say 'member' on stderr (rc=$rc): $(out)"; fi
done
( cd "$T/run/work" && XE a marshal key init ); rc=$?; [ $rc = 2 ] || { good=0; no "SPEC member run on a machine with a key: key init rc=$rc"; }
( cd "$T/run/work" && XE a marshal signers add --line "$LB" ); [ $? = 2 ] || good=0
( cd "$T/run/work" && XE a marshal signers remove "$PB" ); [ $? = 2 ] || good=0
( cd "$T/run/work" && XE a marshal enable --integrity strict ); [ $? = 2 ] || good=0
( cd "$T/run/work" && XE a marshal resign rsg1 --approved w ); [ $? = 2 ] || good=0
[ $good = 1 ] && [ "$(nall)" = "$n_all" ] && [ ! -e "$(KEY km)" ] && cmp -s "$(SIG a)" "$T/sig.a.before" && cmp -s "$(EN a)" "$T/en.a.before" && cmp -s "$(KEY a)" "$T/key.a.before" \
  && ok "member: key init, signers add|remove, enable --integrity and resign exit 2, run no git, change no key, signers or switch file" || no "SPEC member run changed something or ran git (good=$good, git calls +$(( $(nall) - n_all )), key on km: $(ls "$(KEY km)" 2>&1))"

# ============================================================ (15) the private key never leaves its file
N_OK=1; leaks=''
for nd in "$NEEDLE_A_BEFORE" "$NEEDLE_A2"; do
  [ -n "$nd" ] || { N_OK=0; continue; }
  for f in "$LOG" "$SKLOG" "$T"/ki.*; do grep -qF -e "$nd" "$f" 2>/dev/null && leaks="$leaks $f"; done
  grep -rlF -e "$nd" "$T"/m/*/s "$T"/m/*/home "$T"/m/*/c 2>/dev/null | grep -v '/credentials/marshal_ed25519$' > "$T/leakfiles"; [ -s "$T/leakfiles" ] && leaks="$leaks $(tr '\n' ' ' < "$T/leakfiles")"
  for g in "$ORIGIN" "$T"/m/*/app/.git; do git --git-dir="$g" cat-file --batch-all-objects --batch 2>/dev/null | grep -qaF -e "$nd" && leaks="$leaks objects-of-$g"; done
done
[ $N_OK = 1 ] && [ -z "$leaks" ] && ok "key: no line of either private key is in a ref or object, the state, the audit log, a key-init output, the git shim log or the ssh-keygen argument log" || no "SPEC the private key must stay in its file (readable needles: $N_OK; found in:$leaks)"
grep -q -- '-Y' "$SKLOG" && ok "ssh-keygen shim log: qargi used ssh-keygen -Y (the signature goes through the OpenSSH tool)" || no "SPEC signing and verifying go through ssh-keygen -Y; shim log: $(head -c 300 "$SKLOG")"
grep -q -- '-Y sign' "$SKLOG" && grep -q -- '-Y verify' "$SKLOG" && ! grep -E -- '-Y sign.* -n [^q]|-Y verify.* -n [^q]' "$SKLOG" | grep -q . && ok "ssh-keygen shim log: the namespace is always qargi-marshal" || no "SPEC ssh-keygen was called with another namespace: $(grep -E -- '-n [^q]' "$SKLOG" | head -3)"
[ "$(stat -c %a "$(KEY a)" 2>/dev/null)" = 600 ] && [ "$(stat -c %a "$(KEY b)" 2>/dev/null)" = 600 ] && ok "key: both key files are still mode 0600 after all the runs" || no "SPEC key mode 0600: $(stat -c %a "$(KEY a)" "$(KEY b)" 2>&1)"

# ============================================================ (16) fixes found by the adversarial review: the machines
# wa and wb are strict machines with their own keys, wc is advisory with a key, wk advisory without one (it writes unsigned records);
# every one of them trusts the three keys. Each case below is a scenario that was a hole before it was closed.
mk wa; mk wb; mk wc; mk wk
fb f1 f2 f3 f4 f5 f6 f6t w1 w2 w3
for m in wa wb wc wk; do en "$m" || no "setup: enable of $m"; done
kl() { OWN "$1" key init --principal "$1@ms" >/dev/null 2>&1; grep -m1 'namespaces="qargi-marshal" ssh-ed25519 ' "$T/o" | sed 's/^[[:space:]]*//'; }
LWA=$(kl wa); LWB=$(kl wb); LWC=$(kl wc)
for m in wa wb wc wk; do for l in "$LWA" "$LWB" "$LWC"; do OWN "$m" signers add --line "$l" >/dev/null 2>&1; done; done
mode wa strict; mode wb strict; mode wc advisory; mode wk advisory
{ [ -f "$(KEY wa)" ] && [ -f "$(KEY wb)" ] && [ -f "$(KEY wc)" ] && [ "$(jq -r .integrity "$(EN wb)")" = strict ] && [ "$(jq -r .integrity "$(EN wc)")" = advisory ] && grep -qF "$LWC" "$(SIG wk)"; } \
  && ok "review fixes: the fixture (wa, wb strict, wc, wk advisory, keys trusted everywhere) is in place" || no "setup of the review-fix machines"
F=refs/qargi/features
JUNK=''
junk() { # REF JQFILTER: an unsigned commit on top of REF's head (no sig_v, no signer, the filter applied to the record); JUNK is its oid
  local h blob trr; h=$(oref "$1")
  blob=$(orec "$1" | jq -c "del(.sig_v, .signer) | $2" | OG hash-object -w --stdin); trr=$(printf '100644 blob %s\trecord.json\n' "$blob" | OG mktree)
  JUNK=$(OG commit-tree -p "$h" -m junk "$trr") && OG update-ref "$1" "$JUNK"
}
markof() { jq -c --arg n "$2" '.[$n] // empty' "$(S "$1")/features/.accepted-app.json" 2>/dev/null; }     # MACHINE NAME: the high-water mark of a feature
anc() { OG merge-base --is-ancestor "$1" "$2"; }                                                          # OLD NEW: OLD is NEW or one of its ancestors

# ------------------------------------------------------------ (16a) strict: junk on top of newer valid records must not hide them
XE wa marshal claim f1 --as alice --goal g1 >/dev/null 2>&1
XE wb marshal status f1 >/dev/null 2>&1                                  # wb's mark is rev 1 and stays there while wa works
XE wa marshal set f1 --as alice --goal g2 >/dev/null 2>&1; XE wa marshal set f1 --as alice --goal g3 --plan PLAN-LEGIT >/dev/null 2>&1
LEG=$(oref $F/f1); junk $F/f1 '.goal = "junk" | .rev = 99'
j=$(js wb f1)
{ [[ $j == *'"goal":"g3"'* && $j == *'"plan":"PLAN-LEGIT"'* ]] && [ "$(markof wb f1)" = "[3,\"$LEG\"]" ]; } \
  && ok "strict: unsigned junk on top of valid rev 2 and 3: a reader with the mark at rev 1 shows rev 3 and moves its mark to it" || no "SPEC strict fallback must find the newest valid signed record under the junk (json ${j:0:300}; mark $(markof wb f1))"
XE wb marshal set f1 --as alice --goal from-b; rc=$?
{ [ $rc = 0 ] && anc "$LEG" $F/f1 && [ "$(jsf $F/f1 .rev)" = 4 ] && [ "$(jsf $F/f1 .goal)" = from-b ] && [ "$(jsf $F/f1 .plan)" = PLAN-LEGIT ] && vok "$(oref $F/f1)" features "$(SIG wb)"; } \
  && ok "strict: the write of the lagging machine builds on rev 3 (still in the chain, plan kept, signed, rev 4) and replaces the junk" || no "SPEC strict: a write must never drop a valid signed newer record (rc=$rc, origin rev $(jsf $F/f1 .rev), plan '$(jsf $F/f1 .plan)', rev 3 kept: $(anc "$LEG" $F/f1 && echo yes || echo NO)): $(out)"
j=$(js wa f1); j2=$(js wb f1)
{ [[ $j == *'"goal":"from-b"'* && $j == *'"rev":4'* ]] && [[ $j2 == *'"goal":"from-b"'* ]] && ! grep -q 'rollback detected' "$T/e"; } && ok "strict: both machines see the write on top of rev 3, no rollback" || no "SPEC wa/wb after the write: ${j:0:200} / ${j2:0:200}: $(cat "$T/e")"

# ------------------------------------------------------------ (16b) advisory: an unsigned or INVALID head is built on, not replaced
PWC=wc@ms
XE wc marshal claim f2 --as alice --goal g2c >/dev/null 2>&1; C2=$(oref $F/f2)
XE wk marshal set f2 --as alice --goal from-k >/dev/null 2>&1; K2=$(oref $F/f2)
{ [ "$K2" != "$C2" ] && [ "$(jsf $F/f2 'has("sig_v")')" = false ] && [ "$(OG rev-parse "$K2^")" = "$C2" ]; } && ok "setup: the keyless advisory machine wk wrote an unsigned record on top of wc's signed one" || no "setup: wk's unsigned write on f2"
XE wc marshal set f2 --as alice --plan P-wc; rc=$?
{ [ $rc = 0 ] && anc "$K2" $F/f2 && [ "$(jsf $F/f2 .goal)" = from-k ] && [ "$(jsf $F/f2 .plan)" = P-wc ] && [ "$(jsf $F/f2 .signer)" = "$PWC" ] && vok "$(oref $F/f2)" features "$(SIG wc)"; } \
  && ok "advisory: a write builds on wk's unsigned head (its goal is kept, the head is in the chain) and is signed" || no "SPEC advisory must build on the actual unsigned head, not on the mark (rc=$rc, goal '$(jsf $F/f2 .goal)', unsigned head kept: $(anc "$K2" $F/f2 && echo yes || echo NO)): $(cat "$T/e")"
# the lease timer follows the head that was used: wk's unsigned renewals keep the lease of alice alive on wc
XE wc QARGI_MARSHAL_MONO=0 marshal claim f3 --as alice >/dev/null 2>&1
XE wk marshal renew f3 --as alice >/dev/null 2>&1
XE wc QARGI_MARSHAL_MONO=800 marshal status f3 --as sam >/dev/null 2>&1
XE wc QARGI_MARSHAL_MONO=$((TTL + 1)) marshal takeover f3 --as sam --approved "$WORDS"; rc=$?
{ [ $rc != 0 ] && [ "$(jsf $F/f3 .lead.id)" = alice ]; } && ok "advisory: the lease timer counts the unsigned head the lead's other machine renewed (the takeover at ttl+1 s is refused)" || no "SPEC advisory: the timer must follow the head that is used, not the mark (rc=$rc, lead $(jsf $F/f3 .lead.id)): $(out)"
# an INVALID head (changed after signing) is used in advisory too, and a write builds on it
XE wc marshal claim f4 --as alice --goal g4 >/dev/null 2>&1
tamper f4 '.goal = "tampered"'; K4=$(oref $F/f4)
XE wc marshal set f4 --as alice --plan P4; rc=$?
{ [ $rc = 0 ] && anc "$K4" $F/f4 && [ "$(jsf $F/f4 .goal)" = tampered ] && [ "$(jsf $F/f4 .plan)" = P4 ]; } \
  && ok "advisory: an INVALID head is the base of a write as well (the head is in the chain)" || no "SPEC advisory must build on an INVALID head too (rc=$rc, goal '$(jsf $F/f4 .goal)'): $(cat "$T/e")"

# ------------------------------------------------------------ (16c) a signed done/ ref does not clear the mark of a feature that is open again, and an old one cannot be replayed
XE wa marshal claim f5 --as alice --goal life1 >/dev/null 2>&1; XE wa marshal finish f5 --as alice >/dev/null 2>&1
D5=refs/qargi/done/f5; DONE1=$(oref $D5)
XE wa marshal claim f5 --as alice --goal l2r1 >/dev/null 2>&1; G1=$(oref $F/f5)
XE wa marshal set f5 --as alice --goal l2r2 >/dev/null 2>&1; XE wa marshal set f5 --as alice --goal l2r3 >/dev/null 2>&1; G3=$(oref $F/f5)
XE wb marshal status f5 >/dev/null 2>&1
{ [ "$DONE1" != none ] && [ "$(markof wb f5)" = "[3,\"$G3\"]" ]; } && ok "reuse of a name: with done/f5 of the first life still there, the mark of the second life (rev 3) is kept" || no "SPEC the mark of an open feature must stay when done/ exists (mark '$(markof wb f5)', done $DONE1)"
OG update-ref $F/f5 "$G1"
j=$(js wb f5); XE wb marshal status f5
{ grep -q 'rollback detected' <(out) && [[ $j == *'"goal":"l2r3"'* ]]; } && ok "reuse of a name: a rewind to rev 1 of the second life is a rollback, the accepted rev 3 is kept" || no "SPEC a rewind next to an old done/ must be detected (json ${j:0:200}): $(cat "$T/e")"
OG update-ref -d $F/f5                                                          # features/f5 deleted, the old done/f5 replayed
XE wb marshal status f5; cp "$T/e" "$T/e.f5"
{ [ "$(markof wb f5)" = "[3,\"$G3\"]" ] && grep -qi 'warn' "$T/e.f5" && grep -qF f5 "$T/e.f5"; } && ok "replay: the old signed done/f5 does not clear the mark of the second life and the vanished ref warns" || no "SPEC an old done must not drop the mark (mark '$(markof wb f5)'): $(cat "$T/e.f5")"
OG update-ref $F/f5 "$G1"; XE wb marshal status f5
grep -q 'rollback detected' <(out) && ok "replay: and the rewound rev 1 behind it is still a rollback" || no "SPEC replayed done + rewind must be detected: $(out)"
OG update-ref $F/f5 "$G3"
XE wa marshal finish f5 --as alice; rc=$?; DONE2=$(oref $D5)
{ [ $rc = 0 ] && [ "$DONE2" != "$DONE1" ] && [ "$(jsf $D5 .features_oid)" = "$G3" ] && chain_ok $D5 "$(SIG wa)" >/dev/null; } && ok "finish: the signed done record carries the oid of the last features record in its signed payload (and verifies by the spec's payload)" || no "SPEC signed done carries the features oid (rc=$rc, features_oid '$(jsf $D5 .features_oid)', G3 $G3): $(chain_ok $D5 "$(SIG wa)"; cat "$T/ste" 2>/dev/null)"
XE wb marshal status f5; rc=$?
{ [ -z "$(markof wb f5)" ] && ! grep -qi 'warn' "$T/e"; } && ok "finish: the legitimate done record (its features oid is the accepted oid) clears the mark, without a warning" || no "SPEC the matching done clears the mark (mark '$(markof wb f5)'): $(cat "$T/e")"

# ------------------------------------------------------------ (16d) a record is what its signature covers, not the oid of the commit that carries it
XE wa marshal claim f6 --as alice --goal g6 >/dev/null 2>&1; XE wb marshal status f6 >/dev/null 2>&1
XE wa marshal set f6 --as alice --goal g6b >/dev/null 2>&1; R6=$(oref $F/f6)
R6P=$(OG rev-parse "$R6^"); R6M=$(OG show -s --format=%B "$R6"); R6T=$(OG rev-parse "$R6^{tree}")
R6B=$(GIT_COMMITTER_DATE="2001-01-01T00:00:00Z" OG commit-tree -p "$R6P" -m "$R6M" "$R6T")      # the same tree, parent and message, another committer date
{ [ "$R6B" != "$R6" ] && vok "$R6B" features "$(SIG wb)"; } && ok "setup: a re-committed head with another oid still carries a valid signature" || no "setup: the re-committed head does not verify: $(cat "$T/ste" 2>/dev/null)"
OG update-ref $F/f6 "$R6B"
j=$(js wb f6); XE wb marshal status f6
{ [[ $j == *'"goal":"g6b"'* ]] && ! grep -q 'rollback detected' <(out); } && ok "identity: the re-committed head (same rev, record and signed parent) is the same record, not a rollback" || no "SPEC the same signed record under another commit oid is not a rollback (json ${j:0:200}): $(cat "$T/e")"
OG update-ref $F/f6 "$R6"
j=$(js wb f6); XE wb marshal status f6
{ [[ $j == *'"goal":"g6b"'* ]] && ! grep -q 'rollback detected' <(out); } && ok "identity: the original commit of that record, seen after the re-committed one, is the same record too" || no "SPEC the original oid after a re-committed one is not a rollback (json ${j:0:200}): $(cat "$T/e")"
XE wa marshal set f6 --as alice --goal g6c >/dev/null 2>&1
j=$(js wb f6); XE wb marshal status f6
{ [[ $j == *'"goal":"g6c"'* ]] && ! grep -q 'rollback detected' <(out); } && ok "identity: the real chain after it is accepted, the descent check follows the chain by record identity" || no "SPEC the real chain must not be flagged as rollback after a re-committed head (json ${j:0:200}): $(cat "$T/e")"
# a re-committed head does not renew the lease timer
XE wa marshal claim f6t --as alice >/dev/null 2>&1; XE wa marshal renew f6t --as alice >/dev/null 2>&1; T6=$(oref $F/f6t)
XE wb QARGI_MARSHAL_MONO=0 marshal status f6t --as sam >/dev/null 2>&1
T6B=$(GIT_COMMITTER_DATE="2001-01-01T00:00:00Z" OG commit-tree -p "$(OG rev-parse "$T6^")" -m "$(OG show -s --format=%B "$T6")" "$(OG rev-parse "$T6^{tree}")"); OG update-ref $F/f6t "$T6B"
XE wb QARGI_MARSHAL_MONO=600 marshal status f6t --as sam >/dev/null 2>&1
XE wb QARGI_MARSHAL_MONO=$((TTL + 1)) marshal takeover f6t --as sam --approved "$WORDS"; rc=$?
{ [ $rc = 0 ] && [ "$(jsf $F/f6t .lead.id)" = sam ]; } && ok "identity: re-committing a head does not restart the lease timer (takeover at ttl+1 s from the first sight works)" || no "SPEC a re-committed head must not renew a lease (rc=$rc, lead $(jsf $F/f6t .lead.id)): $(out)"

echo
[ $fail = 0 ] && echo "marshal signing: all ok" || echo "marshal signing: FAILURES"
exit $fail
