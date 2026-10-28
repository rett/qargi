#!/usr/bin/env bash
# Project configuration: the answers given once at project initialization
# (repository, long-lived branches, which roles exist and, per role, base
# branch, push policy, model, packages, skills; memory stores; budget).
# Stored under the user's config directory, never in a repository.
#
#   project.sh template NAME              print an answers file with defaults
#   project.sh init NAME --answers FILE [--force]   validate and store
#   project.sh set NAME PATH VALUE        change one answer, e.g. budget_cents 2500 or
#                                         roles.docs.effort high (VALUE is JSON, or a plain string)
#   project.sh show NAME | list | validate FILE
#
# Push policy per role (push.mode). Only "none" is implemented: an agent never
# pushes. The "coordinator" and "agent" policies below are designed but not built, so
# the validator refuses them rather than accept an answer nothing would honour.
#
#   none         the agent returns patches; nothing is pushed unless the user asks
#   coordinator  the agent returns patches; after review the coordinator pushes a
#                branch matching push.branch_pattern (e.g. docs/<slug>), with the
#                user's go-ahead each time
#   agent        the agent itself may push branches matching push.branch_pattern,
#                with the credential named in push.credential (a token read from
#                push.credential_file when a session starts); never anything else.
#                Choose it only on purpose, for example for a docs agent that
#                already pushes docs/<slug> and should keep doing so.
. "$(dirname "$0")/lib.sh"

PROJ_DIR=$DA_CONF/projects
verb=${1:-}; shift || true

validate() { # file -> prints problems, exit 1 if any
  python3 -I - "$1" "$DA_ROLES" <<'EOF'
import json, re, sys
path, roles = sys.argv[1], sys.argv[2].split()
try:
    c = json.load(open(path))
except Exception as e:
    print("not valid JSON: %s" % e); sys.exit(1)
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
r = c.get("roles", {})
need(isinstance(r, dict) and r, "roles: enable at least one role")
efforts = {"low", "medium", "high", "xhigh", "max"}
for name, cfg in (r.items() if isinstance(r, dict) else []):
    p = "roles.%s" % name
    need(name in roles, "%s: not a known role (%s)" % (p, ", ".join(roles)))
    need(isinstance(cfg.get("base"), str) and cfg["base"], "%s.base: base branch, or @dispatcher for the dispatching session's branch" % p)
    push = cfg.get("push", {})
    mode = push.get("mode")
    need(mode in ("none", "coordinator", "agent"), "%s.push.mode: none (the only implemented policy)" % p)
    if mode in ("coordinator", "agent"):
        bad.append("%s.push.mode: only 'none' is implemented; the coordinator and agent push policies are not built yet" % p)
    po = cfg.get("packs_off", [])
    need(isinstance(po, list) and all(isinstance(x, str) and re.fullmatch(r"(skill|tool):[a-z0-9][a-z0-9-]{0,40}", x) for x in po), "%s.packs_off: a list like [\"skill:name\", \"tool:name\"]" % p)
    need(re.fullmatch(r"claude-[a-z0-9.-]+", cfg.get("model", "") or ""), "%s.model: a model id like claude-sonnet-5-5" % p)
    need(cfg.get("effort") in efforts, "%s.effort: %s" % (p, "|".join(sorted(efforts))))
    need(isinstance(cfg.get("apt", []), list), "%s.apt: a list of packages" % p)
    sk = cfg.get("skills", [])
    need(isinstance(sk, list) and all(x in ("pdf", "docx", "pptx", "xlsx") for x in sk), "%s.skills: any of pdf, docx, pptx, xlsx" % p)
need(isinstance(c.get("budget_cents", 0), int) and c.get("budget_cents", 0) > 0, "budget_cents: a positive whole number (set on the deployment)")
m = c.get("memory", {})
for k in ("memory_store", "reference_store"):
    v = m.get(k)
    need(v in (None, "") or re.fullmatch(r"memstore_[A-Za-z0-9]+", v), "memory.%s: a memstore id or empty (created on provisioning)" % k)
teams = c.get("teams", {})
need(isinstance(teams, dict), "teams: an object of named teams")
if isinstance(teams, dict) and teams:
    ld = c.get("lead", {})
    need(re.fullmatch(r"claude-[a-z0-9.-]+", (ld or {}).get("model", "") or ""), "lead.model: a model id like claude-opus-5-5 (needed when teams are defined)")
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
if "lead" in (r if isinstance(r, dict) else {}):
    bad.append("roles.lead: the lead is defined by teams, not by a role")
print("\n".join(bad) if bad else "ok")
sys.exit(1 if bad else 0)
EOF
}

case $verb in
  template)
    n=${1:-}; valid_project "$n" || die "template needs a project name (lower-case letters and digits)"
    jq -n --arg n "$n" '{
      schema: 1, project: $n,
      repo: {url: "https://github.com/OWNER/REPO", path: "", credential_file: "", long_lived: ["master", "develop"]},
      roles: {
        dev:  {base: "@dispatcher", push: {mode: "none"}, model: "claude-sonnet-5-5", effort: "high", apt: [], skills: []},
        docs: {base: "gh-pages", push: {mode: "none"}, model: "claude-opus-5-5", effort: "medium", apt: [], skills: ["pdf"]}
      },
      memory: {memory_store: "", reference_store: ""},
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
  set)
    n=${1:-}; path=${2:-}; val=${3:-}
    [ -f "$PROJ_DIR/$n.json" ] || die "no project named '$n' (see: project list)"
    [ -n "$path" ] && [ -n "$val" ] || die "set needs NAME PATH VALUE (for example: set $n budget_cents 2500)"
    printf '%s' "$path" | grep -Eq '^[a-z_][a-z0-9_.]*$' || die "PATH: dotted keys such as roles.docs.effort"
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
