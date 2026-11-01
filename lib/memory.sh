#!/usr/bin/env bash
# Manage the structure of a qargi recipes memory store.
#   memory.sh lint STORE_ID [--kind recipes|reference]   read-only structure and content check
#   memory.sh get STORE_ID /path.md                       read one note
#   memory.sh split FROM TO (--prefix PATH | --role R | --note-kind K) [--archive] [--plan TOKEN --approved "..."]
#   memory.sh copy  FROM TO [selector] [--policy conflicts|keep] [--plan TOKEN --approved "..."]
#   memory.sh merge FROM TO [--policy conflicts|keep] [--plan TOKEN --approved "..."]
# Checks stores in the pre-canon layout; canon stores are handed to `qargi canon check`
# (structure, note format, indexes and hygiene). split, copy and merge work between two stores, each a
# directory, a .jsonl dump or a memstore_ id; memplan.py plans them and nothing is deleted (see lib/memplan.py).
. "$(dirname "$0")/lib.sh"

here=$(dirname "$(readlink -f "$0")")

# Without --approved this prints the plan and its token and changes nothing. The write happens only for
# the plan the token names, and every store is checked against the notes the plan read before the first change.
store_verbs() {
  v=$1; shift
  unset QARGI_NESTED   # a caller that is itself approved has not approved this plan: the token is always needed
  [ $# -ge 2 ] || die "usage: memory.sh $v FROM TO [options]"
  FROM=$1 TO=$2; shift 2
  PREFIX=() ROLE='' NKIND='' ARCHIVE='' POLICY=conflicts PLAN_ARG='' APPROVED=''
  export PLAN_ARG
  while [ $# -gt 0 ]; do
    case $1 in
      --prefix) PREFIX+=("$2"); shift 2;;
      --role) ROLE=$2; shift 2;;
      --note-kind) NKIND=$2; shift 2;;
      --archive) ARCHIVE=1; shift;;
      --policy) POLICY=$2; shift 2;;
      --plan) PLAN_ARG=$2; shift 2;;
      --approved) APPROVED=$2; shift 2;;
      *) die "unknown option $1";;
    esac
  done
  [ "$v" != split ] || [ "$POLICY" = conflicts ] || die "split puts a collision in /_conflicts/; --policy is for copy and merge"
  for r in "$FROM" "$TO"; do case $r in memstore_*) ant_ok;; esac; done
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  args=(plan "$v" --source "$FROM" --target "$TO" --policy "$POLICY" --out "$tmp/plan.json")
  for p in ${PREFIX[@]+"${PREFIX[@]}"}; do args+=(--prefix "$p"); done
  [ -z "$ROLE" ] || args+=(--role "$ROLE")
  [ -z "$NKIND" ] || args+=(--note-kind "$NKIND")
  [ -z "$ARCHIVE" ] || args+=(--archive)
  python3 -I "$here/memplan.py" "${args[@]}" || exit 1
  tok=$(jq -S -c . "$tmp/plan.json" | plan_token)
  python3 -I "$here/memplan.py" show "$tmp/plan.json"
  if [ -z "$APPROVED" ]; then
    echo "plan only, nothing was changed; plan token: $tok   (apply with: --plan $tok --approved \"...\")"; exit 0
  fi
  [ -n "$tok" ] || die "no plan token could be computed; nothing was changed"
  [ -n "$PLAN_ARG" ] || die "$v needs --plan $tok (the token of the plan shown above) with --approved; nothing was changed"
  need_plan "$tok"
  # what was approved goes to the audit log: token, selector, options and every step; a second line says it was applied
  detail=$(jq -nc --arg from "$FROM" --arg to "$TO" --arg tok "$tok" --arg role "$ROLE" --arg nkind "$NKIND" \
    --arg archive "$ARCHIVE" --arg policy "$POLICY" --slurpfile plan "$tmp/plan.json" \
    '{from:$from, to:$to, token:$tok, prefix:$ARGS.positional, role:$role, note_kind:$nkind, archive:($archive != ""), policy:$policy,
      steps:[$plan[0] | ("target","source") as $k | (.[$k].ops // [])[] | {store:$k, op:.op, path:(.path // .from), to:(.to // null)}]}' \
    --args ${PREFIX[@]+"${PREFIX[@]}"})
  audit_log "memory-$v" "$detail"
  python3 -I "$here/memplan.py" apply "$tmp/plan.json" || exit 1
  audit_log "memory-$v-applied" "$tok"
  echo "$v done (approved: $APPROVED); nothing was deleted"
}

case ${1:-} in split|merge|copy) store_verbs "$@"; exit;; esac
case ${1:-} in init|move) exec "$here/tierwrite.sh" "$@";; esac   # writing a tier: lib/tierwrite.sh (init, move)
case ${1:-} in tiers|check) exec python3 -I "$here/tiers.py" "$@";; esac   # the memory tiers: lib/tiers.py (tiers, check; --project, --json)

verb=${1:-}; store=${2:-}; shift 2 || true
if [ "$verb" = get ]; then   # memory.sh get STORE_ID /path.md: read one note
  case $store in memstore_*) ;; *) die "usage: memory.sh get memstore_ID /path.md";; esac
  [ -n "${1:-}" ] || die "usage: memory.sh get memstore_ID /path.md"
  ant_ok
  id=$(mem_index "$store" | jq -r --arg p "$1" 'select(.path==$p) | .id' | head -1)
  [ -n "$id" ] || die "no such note: $1"
  mem_read "$store" "$id"; exit 0
fi
KIND=recipes
while [ $# -gt 0 ]; do
  case $1 in
    --kind) KIND=$2; shift 2;;
    *) die "unknown option $1";;
  esac
done
case $store in memstore_*) ;; *) die "usage: memory.sh lint|get memstore_ID [/path.md], or split|merge|copy FROM TO";; esac
[ -n "${QARGI_MEMORY_FIXTURE:-}" ] || ant_ok

mem_list() {
  if [ -n "${QARGI_MEMORY_FIXTURE:-}" ]; then cat "$QARGI_MEMORY_FIXTURE"; return; fi   # tests
  ant beta:memory-stores:memories list --memory-store-id "$store" --path-prefix / \
    --view "$1" --max-items -1 2>/dev/null | jq -c 'select(.type=="memory")'
}

create() { # path file
  printf 'content: "@%s"\n' "$2" \
    | ant beta:memory-stores:memories create --memory-store-id "$store" --path "$1" >/dev/null
}

case $verb in
  lint)
    if [ -z "${QARGI_MEMORY_FIXTURE:-}" ]; then
      ctmp=$(mktemp); mem_list full | jq -c '{type, id, path, content}' > "$ctmp"
      if jq -e 'select(.path=="/CANON.md")' "$ctmp" >/dev/null 2>&1; then
        marker=$(jq -r 'select(.path=="/CANON.md")|.content' "$ctmp")
        ck=$(sed -n 's/^kind: *//p' <<<"$marker"); cp=$(sed -n 's/^project: *//p' <<<"$marker"); cr=$(sed -n 's/^roles: *//p' <<<"$marker" | tr ' ' ',')
        python3 -I "$here/canon.py" check --kind "$ck" --project "$cp" --roles "$cr" --store "$ctmp"; rc=$?
        rm -f "$ctmp"; exit $rc
      fi
      rm -f "$ctmp"
    fi
    if [ "$KIND" = reference ]; then
      mem_list full | python3 -I -c '
import sys, json, re
mems = {}
for line in sys.stdin:
    m = json.loads(line); mems[m["path"]] = m.get("content", "")
fails, warns = [], []
F = lambda p, s: fails.append("FAIL %s: %s" % (p, s))
W = lambda p, s: warns.append("WARN %s: %s" % (p, s))
readme = mems.get("/README.md")
if readme is None: F("/README.md", "missing (run: qargi canon plan)")
secrets = [r"sk-ant-[A-Za-z0-9_-]{8,}", r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}", r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY", r"(?i)(password|passwd|secret|token)\s*[:=]\s*\S{8,}"]
for p, c in sorted(mems.items()):
    for pat in secrets:
        if re.search(pat, c): F(p, "looks like a secret")
    if re.search(r"/home/[a-z][a-z0-9_-]*/", c): W(p, "contains a home path")
    if p == "/README.md": continue
    if not re.fullmatch(r"/\d\d-[a-z0-9-]+/[a-z0-9._-]+\.md", p): F(p, "expected /NN-folder/file.md"); continue
    if readme is not None and p.lstrip("/") not in readme: F(p, "not listed in README.md")
    if "<Fill in from" in c: W(p, "still the empty skeleton")
    elif not re.search(r"(?m)^Sources:\s*\S", c) or "<list the repository files" in c: F(p, "no Sources: line")
    if len(c) > 40000: W(p, "%d chars; split it" % len(c))
if readme:
    for ref in set(re.findall(r"`(\d\d-[a-z0-9-]+/[a-z0-9._-]+\.md)`", readme)):
        if "/" + ref not in mems: W("/README.md", "lists %s, which does not exist" % ref)
out = fails + warns
print("\n".join(out) if out else "clean: %d files" % len(mems))
print("%d fail, %d warn, %d files" % (len(fails), len(warns), len(mems)))
sys.exit(1 if fails else 0)
'
      exit $?
    fi
    mem_list full | python3 -I -c '
import sys, json, re, datetime
mems = {}
for line in sys.stdin:
    m = json.loads(line); mems[m["path"]] = m.get("content", "")
fails, warns = [], []
F = lambda p, s: fails.append("FAIL %s: %s" % (p, s))
W = lambda p, s: warns.append("WARN %s: %s" % (p, s))
today = datetime.datetime.now(datetime.timezone.utc).date()

readme = mems.get("/README.md")
if readme is None:
    F("/README.md", "missing (run: qargi canon plan)")
else:
    if len(readme) > 3000: F("/README.md", "%d chars, limit 3000; move detail into INDEX.md" % len(readme))
if "/_template.md" not in mems: W("/_template.md", "missing")

kinds = {"setup": "setup", "gates": "gate", "pitfalls": "pitfall"}
secrets = [r"sk-ant-[A-Za-z0-9_-]{8,}", r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}",
           r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY", r"(?i)(password|passwd|secret|token)\s*[:=]\s*\S{8,}"]
example_ip = re.compile(r"^(192\.0\.2|198\.51\.100|203\.0\.113|127\.|0\.)")
banned = re.compile(r"(?i)\b(backlog|roadmap|todo|planned|plans?|later|ideas?)\b")

def indexed(text, rel):
    return rel in text

for p, c in sorted(mems.items()):
    parts = p.strip("/").split("/")
    for pat in secrets:
        if re.search(pat, c): F(p, "looks like a secret (%s)" % pat[:18])
    if re.search(r"/home/[a-z][a-z0-9_-]*/", c): W(p, "contains a home path")
    for ip in re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", c):
        if not example_ip.match(ip) and not ip.startswith(("10.", "172.", "192.168.")) and all(int(x) <= 255 for x in ip.split(".")):
            W(p, "contains address %s (use documentation addresses)" % ip)
    if p in ("/README.md", "/_template.md"): continue
    top = parts[0]
    if top not in ("sandbox", "repos"):
        F(p, "outside the layout (allowed: README.md, _template.md, sandbox/, repos/)"); continue
    if banned.search(p): W(p, "path suggests backlog or planning material")
    name = parts[-1]
    if top == "repos":
        if len(parts) < 3: F(p, "expected repos/<repo>/..."); continue
        repo = parts[1]; sub = parts[2]
        if sub == "INDEX.md" and len(parts) == 3:
            if readme is not None and ("repos/%s/INDEX.md" % repo) not in readme:
                W(p, "not listed in README.md")
            continue
        if sub not in kinds or len(parts) != 4:
            F(p, "expected repos/<repo>/(setup|gates|pitfalls)/<topic>.md"); continue
        idx = mems.get("/repos/%s/INDEX.md" % repo)
        rel = "/".join(parts[2:])
        if idx is None: F(p, "repos/%s/INDEX.md is missing" % repo)
        elif rel not in idx: F(p, "not listed in repos/%s/INDEX.md" % repo)
        want = kinds[sub]
    else:
        if len(parts) != 2: F(p, "expected sandbox/<topic>.md"); continue
        if readme is not None and ("sandbox/" + name) not in readme: F(p, "not listed in README.md")
        want = "sandbox"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.md", name): W(p, "file name should be kebab-case")
    if len(c) > 3000: W(p, "%d chars; one fact per file, split it" % len(c))
    m = re.search(r"(?m)^Kind:\s*(\S+)", c)
    if not m: F(p, "no Kind: line")
    elif m.group(1) != want: F(p, "Kind is %s, this directory holds %s" % (m.group(1), want))
    if not re.search(r"(?m)^Applies to:\s*\S", c): F(p, "no Applies to: line")
    if not re.search(r"(?m)^Check:\s*\S", c): F(p, "no Check: line")
    v = re.search(r"(?m)^Verified:\s*(\d{4}-\d{2}-\d{2})", c)
    if not v: F(p, "no Verified: YYYY-MM-DD line")
    else:
        d = datetime.date.fromisoformat(v.group(1))
        if d > today: F(p, "Verified date is in the future")
        elif (today - d).days > 90: W(p, "verified %d days ago; re-check" % (today - d).days)

# index rows that point at files that do not exist
for ip_, text in [("/README.md", readme or "")] + [(k, v) for k, v in mems.items() if k.endswith("/INDEX.md")]:
    base = ip_.rsplit("/", 1)[0]
    for ref in set(re.findall(r"`?((?:repos/[a-z0-9._-]+/)?(?:sandbox|setup|gates|pitfalls)/[a-z0-9._-]+\.md|repos/[a-z0-9._-]+/INDEX\.md)`?", text)):
        cands = ["/" + ref] if ref.startswith(("repos/", "sandbox/")) else [base + "/" + ref]
        if not any(c in mems for c in cands): W(ip_, "lists %s, which does not exist" % ref)

out = fails + warns
print("\n".join(out) if out else "clean: %d memories" % len(mems))
print("%d fail, %d warn, %d memories" % (len(fails), len(warns), len(mems)))
sys.exit(1 if fails else 0)
';;
  *) die "usage: memory.sh lint memstore_ID (stores are created and seeded by qargi canon)";;
esac
