#!/usr/bin/env bash
# Project configuration: the answers given once at project initialization
# (repository, long-lived branches, which roles exist and, per role, base
# branch, push policy, model, packages, skills; memory stores; budget).
# Stored under the user's config directory, never in a repository.
#
#   project.sh template NAME              print an answers file with defaults
#   project.sh init NAME --answers FILE [--force]   validate and store
#   project.sh set NAME PATH VALUE        change one answer, e.g. budget_cents 2500 or
#                                         roles.write.effort high (VALUE is JSON, or a plain string)
#   project.sh new NAME [--methodology M] [--dir D] [--url U] [--deployment ID] [--param k=v] [--plan T --approved W]
#                                         create a project directory with a git repository and the methodology's generic files
#   project.sh attach [DIR] [--name N] [--methodology M] [--url U] [--plan T --approved W] [--force]
#                                         read an existing repository, show the answers and the gaps, store on approval
#   project.sh show NAME | list | validate FILE
#
# Push policy per role (push.mode). Only "none" is implemented: an agent never
# pushes. The "coordinator" and "agent" policies below are designed but not built, so
# the validator refuses them rather than accept an answer nothing would honour.
#
#   none         the agent returns patches; nothing is pushed unless the user asks
#   coordinator  the agent returns patches; after review the coordinator pushes a
#                branch matching push.branch_pattern (e.g. agent/<slug>), with the
#                user's go-ahead each time
#   agent        the agent itself may push branches matching push.branch_pattern,
#                with the credential named in push.credential (a token read from
#                push.credential_file when a session starts); never anything else.
#                Choose it only on purpose, for example for a writer agent that
#                already pushes its own branch and should keep doing so.
. "$(dirname "$0")/lib.sh"

PROJ_DIR=$DA_CONF/projects
verb=${1:-}; shift || true

validate() { # file -> prints problems, exit 1 if any
  python3 -I - "$1" "$DA_ROLES" "$(dirname "$(readlink -f "$0")")" "$QARGI_TOOL" "$DA_CONF" <<'EOF'
import json, os, re, sys
path, roles = sys.argv[1], sys.argv[2].split()
sys.path.insert(0, sys.argv[3])
import provider
try:
    c = json.load(open(path))
except Exception as e:
    print("not valid JSON: %s" % e); sys.exit(1)
# the models and the model-id pattern are the project's provider's (models.provider, default claude)
pname = (c.get("models") or {}).get("provider", "claude") if isinstance(c, dict) and isinstance(c.get("models"), dict) else "claude"
try:
    D = provider.load(pname)
except provider.ProviderError:
    D = provider.load("claude")
model_ok = re.compile(D["model_pattern"])
aliases = [a for a in D["aliases"].values() if a]
bad = []
def need(cond, msg):
    if not cond: bad.append(msg)
need(c.get("schema") == 1, "schema must be 1")
need(re.fullmatch(r"[a-z][a-z0-9]{0,23}", c.get("project", "") or ""), "project: one lower-case token (letters, digits)")
repo = c.get("repo", {})
need(isinstance(repo.get("url"), str) and repo["url"] and "OWNER/REPO" not in repo["url"], "repo.url is required (replace the placeholder)")
ll = repo.get("long_lived", [])
need(isinstance(ll, list) and ll and all(isinstance(x, str) and x for x in ll), "repo.long_lived: the branches no agent may ever touch (e.g. master, develop)")
cf = repo.get("credential_file", "")
if cf:
    import os, subprocess
    pth = os.path.expanduser(cf)
    if not os.path.isfile(pth): bad.append("repo.credential_file: %s is not a file" % cf)
    else:
        st = os.stat(pth)
        if st.st_mode & 0o077: bad.append("repo.credential_file: %s must be readable by you only (chmod 600)" % cf)
        if st.st_size == 0: bad.append("repo.credential_file: %s is empty" % cf)
        inside = subprocess.run(["git", "-C", os.path.dirname(pth) or ".", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if inside.returncode == 0 and inside.stdout.strip() == "true":
            bad.append("repo.credential_file: %s is inside a git working tree; keep it outside every repository" % cf)
cl = c.get("cloud")
if cl is not None:
    need(isinstance(cl, dict) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", str(cl.get("profile", ""))) and re.fullmatch(r"wrkspc_[A-Za-z0-9]{10,}", str(cl.get("workspace_id", ""))),
         "cloud: {profile: an ant profile name, workspace_id: wrkspc_...} (qargi cloud set)")
r = c.get("roles", {})
# the two cloud bases (worker, reviewer) are instance names too: a roles.<base> entry is allowed (it sets that base's defaults)
# but never required, and the bases are never roles of their own
try: base_names = list(json.load(open(os.path.join(sys.argv[3], "model-defaults.json"))).get("bases", {}))
except Exception: base_names = ["worker", "reviewer"]
need(isinstance(r, dict) and r, "roles: enable at least one role")
efforts = {"low", "medium", "high", "xhigh", "max"}
for name, cfg in (r.items() if isinstance(r, dict) else []):
    p = "roles.%s" % name
    need(name in roles or name in base_names, "%s: not a known role (%s) or base (%s)" % (p, ", ".join(roles), ", ".join(base_names)))
    need(isinstance(cfg.get("base"), str) and cfg["base"], "%s.base: base branch, or @dispatcher for the dispatching session's branch" % p)
    push = cfg.get("push", {})
    mode = push.get("mode")
    need(mode in ("none", "coordinator", "agent"), "%s.push.mode: none (the only implemented policy)" % p)
    if mode in ("coordinator", "agent"):
        bad.append("%s.push.mode: only 'none' is implemented; the coordinator and agent push policies are not built yet" % p)
    po = cfg.get("packs_off", [])
    need(isinstance(po, list) and all(isinstance(x, str) and re.fullmatch(r"(skill|tool):[a-z0-9][a-z0-9-]{0,40}", x) for x in po), "%s.packs_off: a list like [\"skill:name\", \"tool:name\"]" % p)
    need(model_ok.fullmatch(cfg.get("model", "") or ""), "%s.model: a model id like %s" % (p, D["tiers"]["balanced"]))
    need(cfg.get("effort") in efforts, "%s.effort: %s" % (p, "|".join(sorted(efforts))))
    need(isinstance(cfg.get("apt", []), list), "%s.apt: a list of packages" % p)
    need(isinstance(cfg.get("pip", []), list), "%s.pip: a list of Python packages" % p)
    need(isinstance(cfg.get("go", []), list), "%s.go: a list of Go modules, each with a version (module@version)" % p)
    off = cfg.get("tools_off", [])
    need(isinstance(off, list) and all(x in ("web_search", "web_fetch", "edit", "write", "read", "bash", "glob", "grep") for x in off), "%s.tools_off: built-in tools to disable (web_search, web_fetch, edit, ...)" % p)
    sk = cfg.get("skills", [])
    need(isinstance(sk, list) and all(x in ("pdf", "docx", "pptx", "xlsx") for x in sk), "%s.skills: any of pdf, docx, pptx, xlsx" % p)
prof = c.get("profiles")
if prof is not None:
    import os
    md = json.load(open(os.path.join(sys.argv[3], "model-defaults.json")))
    tiers_ok = D["tiers"]
    def role_class(rn):
        for d in (os.path.join(sys.argv[4], "roles", rn), os.path.join(sys.argv[5], "roles", rn)):
            try: return json.load(open(os.path.join(d, "role.json"))).get("class", "write")
            except Exception: pass
        return None
    if not isinstance(prof, dict): bad.append("profiles: an object of named profiles")
    for pn, pf in (prof.items() if isinstance(prof, dict) else []):
        p = "profiles.%s" % pn
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", pn): bad.append("%s: a lower-case name (letters, digits, hyphen; at most 31 characters)" % p); continue
        if not isinstance(pf, dict): bad.append("%s: an object like {base, tier, model, effort, purpose, abilities}" % p); continue
        for k in pf:
            if k not in ("base", "tier", "model", "effort", "purpose", "abilities"):
                bad.append("%s.%s: unknown key (base, tier, model, effort, purpose, abilities)" % (p, k))
        bases = md["bases"]
        b = pf.get("base")
        if b is None and pn in md["profiles"]: b = md["profiles"][pn].get("base")
        if "base" not in pf and pn not in md["profiles"]:
            bad.append("%s.base: required for a profile of your own (%s)" % (p, ", ".join(bases)))
        elif "base" in pf and pf["base"] not in bases:
            bad.append("%s.base: one of %s" % (p, ", ".join(bases))); b = None
        if "tier" in pf: need(pf["tier"] in tiers_ok, "%s.tier: one of %s" % (p, ", ".join(tiers_ok)))
        if "model" in pf: need(isinstance(pf["model"], str) and (pf["model"] in aliases or model_ok.fullmatch(pf["model"])), "%s.model: %s or a model id like %s" % (p, ", ".join(aliases), D["tiers"]["balanced"]))
        if "effort" in pf: need(pf["effort"] in efforts, "%s.effort: %s" % (p, "|".join(sorted(efforts))))
        if "purpose" in pf: need(isinstance(pf["purpose"], str) and len(pf["purpose"]) <= 300, "%s.purpose: a string of at most 300 characters" % p)
        if "abilities" in pf:
            ab = pf["abilities"]
            if not (isinstance(ab, list) and all(isinstance(x, str) for x in ab)):
                bad.append("%s.abilities: a list of roles (%s)" % (p, ", ".join(roles))); continue
            want = bases.get(b, {}).get("class") if b else None
            for x in ab:
                cl2 = role_class(x) if x != "lead" else None
                if cl2 is None: bad.append("%s.abilities: %s is not a known role (%s)" % (p, x, ", ".join(roles)))
                elif want and cl2 != want: bad.append("%s.abilities: %s is %s, but base %s is %s" % (p, x, cl2, b, want))
# models.accept_no_barrier.<surface> = {by, at, reason}: the owner's acceptance of a provider surface with no read-only barrier
# (written only by `qargi provider accept`; nothing else in models is checked here)
anb = c.get("models", {}).get("accept_no_barrier") if isinstance(c.get("models"), dict) else None
if anb is not None:
    if not isinstance(anb, dict): bad.append("models.accept_no_barrier: an object of surfaces (%s), each {by, at, reason}" % ", ".join(provider.SURFACES))
    else:
        for sf, rec in anb.items():
            p = "models.accept_no_barrier.%s" % sf
            if sf not in provider.SURFACES: bad.append("%s: not a surface (%s)" % (p, ", ".join(provider.SURFACES))); continue
            if not isinstance(rec, dict) or set(rec) != {"by", "at", "reason"}: bad.append("%s: exactly {by, at, reason}" % p); continue
            for k in ("by", "reason"):
                need(isinstance(rec[k], str) and rec[k].strip(), "%s.%s: a non-empty string" % (p, k))
            need(isinstance(rec["at"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", rec["at"]), "%s.at: a UTC time like 2026-10-31T12:00:00Z" % p)
need(isinstance(c.get("budget_cents", 0), int) and c.get("budget_cents", 0) > 0, "budget_cents: a positive whole number (set on the deployment)")
m = c.get("memory", {})
for k in ("memory_store", "reference_store"):
    v = m.get(k)
    need(v in (None, "") or re.fullmatch(r"memstore_[A-Za-z0-9]+", v), "memory.%s: a memstore id or empty (created on provisioning)" % k)
if isinstance(m, dict) and m.get("tiers") is not None:
    import tiers   # lib/tiers.py is the one place that knows the tiers and where each may be placed
    bad.extend(tiers.problems(m["tiers"]))
teams = c.get("teams", {})
need(isinstance(teams, dict), "teams: an object of named teams")
if isinstance(teams, dict) and teams:
    ld = c.get("lead", {})
    need(model_ok.fullmatch((ld or {}).get("model", "") or ""), "lead.model: a model id like %s (needed when teams are defined)" % D["tiers"]["deep"])
    need((ld or {}).get("effort") in efforts, "lead.effort: %s" % "|".join(sorted(efforts)))
    for tn, t in teams.items():
        p = "teams.%s" % tn
        need(re.fullmatch(r"[a-z][a-z0-9-]{0,23}", tn), "%s: a lower-case name" % p)
        mem = t.get("members", [])
        need(isinstance(mem, list) and len(mem) >= 2 and len(set(mem)) == len(mem) and all(m in (r if isinstance(r, dict) else {}) for m in mem),
             "%s.members: two or more distinct roles enabled in this project" % p)
        need(isinstance(t.get("max_rounds", 2), int) and 0 <= t.get("max_rounds", 2) <= 5, "%s.max_rounds: a whole number from 0 to 5" % p)
        need(isinstance(t.get("budget_cents", 1), int) and t.get("budget_cents", 1) > 0, "%s.budget_cents: a positive whole number" % p)
        st = t.get("standards", [])
        need(isinstance(st, list) and all(isinstance(x, str) and x and not x.startswith("/") and ".." not in x for x in st), "%s.standards: store paths such as shared/rules/rules.md (no leading slash)" % p)
        sc = t.get("scopes", {})
        need(isinstance(sc, dict) and all(k in mem and isinstance(v, list) and all(isinstance(x, str) and x and not x.startswith("/") and ".." not in x for x in v) for k, v in sc.items()),
             "%s.scopes: {member role: [paths it may change]}" % p)
lp = (c.get("lead") or {}).get("push", {})
if lp:
    need(isinstance(lp, dict), "lead.push: an object")
    if isinstance(lp, dict):
        need(isinstance(lp.get("local", False), bool), "lead.push.local: true if the Claude Code session leading may push agent branches and open pull requests")
        need(lp.get("cloud", "none") in ("none", "branches"), "lead.push.cloud: none or branches (a cloud lead pushes agent branches and opens pull requests)")
        for k in ("merge", "release"):
            need(lp.get(k, "ask") in ("ask", "never"), "lead.push.%s: ask (the person confirms each one) or never; there is no automatic merge or release" % k)
        pat = lp.get("branch_pattern", "agent/*")
        need(isinstance(pat, str) and re.fullmatch(r"agent/[A-Za-z0-9._*-]*", pat or ""), "lead.push.branch_pattern: agent/ followed by a name or *")
        need(lp.get("vault_id", "") in ("",) or re.fullmatch(r"vlt_[A-Za-z0-9]+", lp.get("vault_id", "")), "lead.push.vault_id: a vault id (set by qargi credential setup lead-push)")
        if lp.get("cloud") == "branches":
            cf2 = lp.get("credential_file", "")
            need(cf2, "lead.push.credential_file: a fine-grained token file (contents and pull requests write, this repository only) for the cloud lead")
            if cf2:
                import os, subprocess
                pth = os.path.expanduser(cf2)
                if not os.path.isfile(pth): bad.append("lead.push.credential_file: %s is not a file" % cf2)
                else:
                    st = os.stat(pth)
                    if st.st_mode & 0o077: bad.append("lead.push.credential_file: %s must be readable by you only (chmod 600)" % cf2)
                    if st.st_size == 0: bad.append("lead.push.credential_file: %s is empty" % cf2)
                    ins = subprocess.run(["git", "-C", os.path.dirname(pth) or ".", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
                    if ins.returncode == 0 and ins.stdout.strip() == "true":
                        bad.append("lead.push.credential_file: %s is inside a git working tree; keep it outside every repository" % cf2)
                    if cf and os.path.realpath(os.path.expanduser(cf)) == os.path.realpath(pth):
                        bad.append("lead.push.credential_file must not be the read-only repo.credential_file: the repository mount keeps a token that cannot write")
if "lead" in (r if isinstance(r, dict) else {}):
    bad.append("roles.lead: the lead is defined by teams, not by a role")
print("\n".join(bad) if bad else "ok")
sys.exit(1 if bad else 0)
EOF
}

case $verb in
  template)
    n=${1:-}; valid_project "$n" || die "template needs a project name (lower-case letters and digits)"
    jq -n --arg n "$n" --slurpfile d "$(dirname "$(readlink -f "$0")")/model-defaults.json" --slurpfile p "$(dirname "$(readlink -f "$0")")/providers/claude.json" \
    '$p[0].tiers as $m | ($d[0].profiles | map_values(. + {model: $m[.tier]})) as $t | {
      schema: 1, project: $n,
      repo: {url: "https://github.com/OWNER/REPO", path: "", credential_file: "", long_lived: ["master", "develop"]},
      roles: {
        build: {base: "@dispatcher", push: {mode: "none"}, model: $t.build.model, effort: $t.build.effort, apt: [], skills: []},
        write: {base: "gh-pages", push: {mode: "none"}, model: $t.write.model, effort: $t.write.effort, apt: [], skills: ["pdf"]}
      },
      memory: {memory_store: "", reference_store: "", tiers: {}},
      budget_cents: 500}';;
  init)
    n=${1:-}; shift || true; valid_project "$n" || die "init needs a project name"
    ans='' force=''
    while [ $# -gt 0 ]; do case $1 in --answers) ans=$2; shift 2;; --force) force=1; shift;; *) die "unknown option $1";; esac; done
    [ -f "$ans" ] || die "init needs --answers FILE (see: project template $n)"
    out=$(validate "$ans") || { echo "$out" >&2; die "the answers are not valid; nothing stored"; }
    [ "$(jq -r .project "$ans")" = "$n" ] || die "the answers are for project '$(jq -r .project "$ans")', not '$n'"
    mkdir -p "$PROJ_DIR"; chmod 700 "$PROJ_DIR"
    [ ! -e "$PROJ_DIR/$n.json" ] || [ -n "$force" ] || die "project $n is already initialised (--force to replace)"
    jq . "$ans" > "$PROJ_DIR/$n.json.tmp" && chmod 600 "$PROJ_DIR/$n.json.tmp" && mv "$PROJ_DIR/$n.json.tmp" "$PROJ_DIR/$n.json"
    echo "project $n stored in $PROJ_DIR/$n.json"
    jq -r '.roles | to_entries[] | "  role \(.key): base \(.value.base), push \(.value.push.mode)" + (if .value.push.branch_pattern then " (\(.value.push.branch_pattern))" else "" end) + ", \(.value.model)/\(.value.effort)"' "$PROJ_DIR/$n.json";;
  new)
    # a new project: its directory, a git repository on the methodology's branches and the generic files; the plan first
    n=${1:-}; shift || true; valid_project "$n" || die "new needs a project name (lower-case letters and digits)"
    meth=gitflow dir='' url='' dep='' force='' PLAN_ARG='' APPROVED='' PARAMS=()
    while [ $# -gt 0 ]; do
      case $1 in --methodology) meth=$2; shift 2;; --dir) dir=$2; shift 2;; --url) url=$2; shift 2;; --deployment) dep=$2; shift 2;;
        --param) PARAMS+=(--param "$2"); shift 2;; --plan) PLAN_ARG=$2; shift 2;; --approved) APPROVED=$2; shift 2;; *) die "unknown option $1";; esac
    done
    export PLAN_ARG   # need_plan reads it
    lib=$(dirname "$0")
    [ -n "$dir" ] || dir=$PWD/$n
    dir=${dir/#\~/$HOME}; case $dir in /*) ;; *) dir=$PWD/$dir;; esac
    [ -d "$(dirname "$dir")" ] || die "$(dirname "$dir") does not exist: create it first, or give --dir"
    if [ -e "$dir" ]; then [ -d "$dir" ] && [ -z "$(ls -A "$dir")" ] || die "$dir exists and is not an empty directory"; fi
    files=$(python3 -I "$lib/methodology.py" files "$meth" --param "project=$n" "${PARAMS[@]}") || exit 1
    if [ -n "$dep" ]; then python3 -I "$lib/methodology.py" deployment "$meth" "$dep" >/dev/null || exit 1; fi
    [ ! -e "$PROJ_DIR/$n.json" ] || die "project $n is already initialised (qargi project show $n)"
    long=$(python3 -I - "$lib" "$meth" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import methodology as M
print(" ".join(M.load(sys.argv[2])[2]["branches"]["long_lived"]))
PY
    ) || exit 1
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n' "$dir" "$meth" "$url" "$dep" "$(jq -S -c . <<<"$files")" | plan_token)
    echo "new project $n with the $meth methodology at $dir"
    echo "  git repository with the branches: $long (the first is the initial one; work starts on the last)"
    echo "  files:"; jq -r '.[].dest | "    " + .' <<<"$files"
    if [ -n "$url" ]; then echo "  qargi answers stored for $url (outside the repository)"; else echo "  no --url: the answers are stored later, when the remote exists: qargi project attach $dir --url URL"; fi
    echo "  deployment: ${dep:-not chosen (see below)}"
    echo
    if [ -z "$APPROVED" ]; then
      python3 -I "$lib/methodology.py" deployment "$meth"
      echo; echo "choose one with --deployment ID (qargi methodology deployment $meth ID shows how); you can do it by hand or ask for it to be done for you"
      echo; echo "plan token: $tok   (create with: qargi project new $n --plan $tok --approved \"...\" plus the same options)"
      exit 0
    fi
    need_plan "$tok"
    mkdir -p "$dir"
    jq -r '.[] | [.dest, (.content | @base64)] | @tsv' <<<"$files" | while IFS=$'\t' read -r rel b64; do
      mkdir -p "$dir/$(dirname "$rel")"; printf '%s' "$b64" | base64 -d > "$dir/$rel"
    done
    first=${long%% *}; last=${long##* }
    git -C "$dir" init -q -b "$first" || die "git init failed in $dir"
    git -C "$dir" add -A
    git -C "$dir" commit -q -m "Start $n" || die "the first commit failed (is a git user.name and user.email set?); the files are in $dir"
    for b in $long; do [ "$b" = "$first" ] || git -C "$dir" branch "$b"; done
    git -C "$dir" checkout -q "$last"
    audit_log "project:new" "$n"
    echo "created $dir (on $last, $(git -C "$dir" rev-parse --short HEAD))"
    if [ -n "$url" ]; then
      det=$(python3 -I "$lib/attach.py" detect "$dir" --name "$n" --methodology "$meth") || exit 1
      f=$(mktemp); jq --arg u "$url" --arg d "$dep" '.answers | .repo.url = $u | if $d == "" then . else .deployment = $d end' <<<"$det" > "$f"
      out=$(validate "$f") || { echo "$out" >&2; rm -f "$f"; die "the project was created but its answers are not valid; nothing stored (qargi project attach $dir --url URL)"; }
      mkdir -p "$PROJ_DIR"; chmod 700 "$PROJ_DIR"; mv "$f" "$PROJ_DIR/$n.json"; chmod 600 "$PROJ_DIR/$n.json"
      echo "project $n stored in $PROJ_DIR/$n.json"
    fi
    if [ -n "$dep" ]; then echo; python3 -I "$lib/methodology.py" deployment "$meth" "$dep"; fi
    echo; echo "next: create the repository on your host and push (git remote add origin URL; git push -u origin ${long// / })"
    echo "      a first release: qargi release start $(jq -r '.[] | select(.dest == "VERSION") | .content' <<<"$files" | tr -d '\n') (not built yet)";;
  attach)
    # an existing repository: read it, show what qargi would store and what the methodology has that it lacks; store only after approval
    dir=. name='' meth=gitflow url='' force='' PLAN_ARG='' APPROVED=''
    while [ $# -gt 0 ]; do
      case $1 in --name) name=$2; shift 2;; --methodology) meth=$2; shift 2;; --url) url=$2; shift 2;; --force) force=1; shift;;
        --plan) PLAN_ARG=$2; shift 2;; --approved) APPROVED=$2; shift 2;; -*) die "unknown option $1";; *) dir=$1; shift;; esac
    done
    export PLAN_ARG   # need_plan reads it
    det=$(python3 -I "$(dirname "$0")/attach.py" detect "$dir" ${name:+--name "$name"} --methodology "$meth") || exit 1
    [ -z "$url" ] || det=$(jq --arg u "$url" '.answers.repo.url = $u | .questions |= map(select(startswith("repo.url") | not))' <<<"$det")
    n=$(jq -r .answers.project <<<"$det")
    valid_project "$n" || die "the project name '$n' is not valid: --name (lower-case letters and digits)"
    sf=$PROJ_DIR/$n.json; stored=''
    [ ! -f "$sf" ] || stored=1
    ans=$(jq -c .answers <<<"$det")
    if [ -n "$stored" ] && [ -n "$force" ]; then
      # replace only what was detected; keep every answer that cannot be detected (roles, cloud, memory, budget, ...)
      ans=$(jq -c --argjson det "$det" --arg urlgiven "$url" '
        ($det.answers) as $d | ($det.found) as $f
        | ($d * .) as $m
        | $m | .methodology = $d.methodology | .repo.path = $d.repo.path
        | (if $urlgiven != "" or $f.remote != "" then .repo.url = $d.repo.url else . end)
        | (if ($f.long_lived | length) > 0 then .repo.long_lived = $d.repo.long_lived else . end)
        | (if $d.test_command then .test_command = $d.test_command else . end)' "$sf")
    fi
    tok=$(jq -S -c . <<<"$ans" | plan_token)
    jq -r '"project \(.answers.project) from \(.found.path)\nread from: \(.found.ref | if . == "" then "no commit" else . end) (\(.found.ref_why); the checked-out branch is \(.found.current_branch | if . == "" then "none" else . end), the working tree is not read)\nmethodology: \(.methodology)\nremote (origin as read): \(.found.remote // "none")" + (if (.found.remote // "") != "" and .found.url != .found.remote then "\nrepo.url (normalised to https, no .git, no credentials): \(.found.url)" else "" end) + "\nlong-lived branches: \(.answers.repo.long_lived | join(", "))\nversion: \(.found.version.file // "not found") \(.found.version.value // "")\ntags: \(.found.tags.count) (\(.found.tags.pattern | if . == "" then "no semantic pattern" else . end))\nchangelog: \(.found.changelog.file // "none")\ntest command: \(.found.test_command | if . == "" then "not found" else . end)\nCI workflows: \(.found.ci_workflows | if length == 0 then "none" else join(", ") end)"' <<<"$det"
    if [ -n "$stored" ]; then
      echo
      echo "ALREADY STORED: the answers of project $n are in $sf; stored vs detected (only what is detected):"
      jq -r --argjson det "$det" '
        [["repo.url", .repo.url, $det.answers.repo.url], ["repo.long_lived", (.repo.long_lived | join(",")), ($det.answers.repo.long_lived | join(","))],
         ["repo.path", .repo.path, $det.answers.repo.path], ["test_command", .test_command, $det.answers.test_command], ["methodology", .methodology, $det.answers.methodology]]
        | map(select(.[2] != null and .[1] != .[2])) | if length == 0 then "  no difference" else .[] | "  \(.[0]): stored \(.[1] // "(missing)" | tojson), detected \(.[2] | tojson)" end' "$sf"
      miss=$(jq -r --argjson det "$det" '. as $s | [$det.answers | paths(type != "object") | select(.[-1] | type == "string") | select(. as $p | $s | getpath($p) == null) | join(".")] | .[]' "$sf")
      if [ -n "$miss" ]; then echo "  answers the current schema wants and the stored file lacks (--force adds them with defaults):"; sed 's/^/    - /' <<<"$miss"; fi
    fi
    echo
    echo "gaps against the $meth methodology (nothing is changed in the repository; adopting them is a separate, reviewed change):"
    jq -r 'if (.gaps | length) == 0 then "  none" else .gaps[] | "  - \(.kind): \(.what) (\(.why))" end' <<<"$det"
    qs=$(jq -r --arg st "$stored" 'if $st == "" then .questions[] else empty end' <<<"$det")
    if [ -n "$qs" ]; then echo; echo "questions:"; sed 's/^/  - /' <<<"$qs"; fi
    echo
    if [ -n "$stored" ] && [ -z "$force" ]; then
      echo "nothing to store: project $n is already initialised. To replace the detected fields and keep the rest (roles, cloud, memory, budget): qargi project attach $dir --force"
      [ -z "$APPROVED" ] || die "project $n is already initialised (--force to replace)"
      exit 0
    fi
    if [ -z "$APPROVED" ]; then
      echo "stored answers would be:"; jq . <<<"$ans"
      echo "plan token: $tok   (store with: qargi project attach $dir --plan $tok --approved \"...\"${force:+ --force})"
      exit 0
    fi
    need_plan "$tok"
    f=$(mktemp); jq . <<<"$ans" > "$f"
    out=$(validate "$f") || { echo "$out" >&2; rm -f "$f"; die "the answers are not valid; nothing stored"; }
    mkdir -p "$PROJ_DIR"; chmod 700 "$PROJ_DIR"
    mv "$f" "$sf"; chmod 600 "$sf"
    audit_log "project:attach" "$n"
    echo "project $n stored in $sf (approved: $APPROVED)";;
  set)
    n=${1:-}; path=${2:-}; val=${3:-}
    [ -f "$PROJ_DIR/$n.json" ] || die "no project named '$n' (see: project list)"
    [ -n "$path" ] && [ -n "$val" ] || die "set needs NAME PATH VALUE (for example: set $n budget_cents 2500)"
    printf '%s' "$path" | grep -Eq '^[a-z_][a-z0-9_.]*$' || die "PATH: dotted keys such as roles.write.effort"
    jq -e . >/dev/null 2>&1 <<<"$val" || val=$(jq -Rn --arg v "$val" '$v')
    tmp=$(mktemp "$PROJ_DIR/.set.XXXXXX"); jq --argjson v "$val" --arg p "$path" 'setpath($p | split("."); $v)' "$PROJ_DIR/$n.json" > "$tmp"
    out=$(validate "$tmp") || { echo "$out" >&2; rm -f "$tmp"; die "that would make the project invalid; nothing changed"; }
    chmod 600 "$tmp"; mv "$tmp" "$PROJ_DIR/$n.json"
    echo "$n: $path = $val (applies to the next provision; use 'instances budget' for a live deployment)";;
  show) n=${1:-}; [ -f "$PROJ_DIR/$n.json" ] || die "no project named '$n' (see: project list)"; jq . "$PROJ_DIR/$n.json";;
  list) ls "$PROJ_DIR" 2>/dev/null | sed -n 's/\.json$//p';;
  validate) f=${1:-}; [ -f "$f" ] || f="$PROJ_DIR/$f.json"; [ -f "$f" ] || die "validate needs a file or a project name"; validate "$f";;
  *) die "usage: project.sh template|init|show|list|validate ...";;
esac
