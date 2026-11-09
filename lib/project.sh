#!/usr/bin/env bash
# Project configuration: the answers given once at project initialization
# (repository, long-lived branches, which roles exist and, per role, base
# branch, push policy, model, packages, skills; memory stores; budget).
# Stored under the user's config directory, never in a repository.
#
#   project.sh template NAME              print an answers file with defaults (models.provider is there as an empty string: there is no
#                                         default provider, so set it to a provider's name before the pack verbs, skill accept and
#                                         marshal handoff can serve the project; `project validate` reports it while it is empty; a role's model
#                                         is null: it takes its provider's tier once one is set)
#   project.sh init NAME --answers FILE [--force]   validate and store
#   project.sh set NAME PATH VALUE        change one answer, e.g. budget_cents 2500 or
#                                         roles.write.effort high (VALUE is JSON, or a plain string). The provider has one runtime
#                                         per surface: models.provider.local NAME / models.provider.cloud NAME set one (a single
#                                         name already there is kept for the surface you do not set)
#   project.sh new NAME [--methodology M] [--dir D] [--url U] [--deployment ID] [--param k=v] [--plan T --approved W]
#                       [--provider NAME | --provider-local NAME --provider-cloud NAME]
#                                         create a project directory with a git repository and the methodology's generic files;
#                                         --provider is one name for both surfaces, the other two name a runtime for each
#   project.sh attach [DIR] [--name N] [--methodology M] [--url U] [--plan T --approved W] [--force]
#                       [--provider NAME | --provider-local NAME --provider-cloud NAME]
#                                         read an existing repository, show the answers and the gaps, store on approval
#   project.sh adopt NAME [--methodology M] [--plan T --approved W]
#                                         close the safe gaps of an attached repository: create the missing long-lived branches
#                                         (locally, from the default branch) and write the methodology's missing files as one commit
#                                         on a new branch agent/adopt-M cut from the integration branch; never changes an existing
#                                         branch or file, never pushes; refused (exit 2) when dirty, detached, empty, unattached
#                                         or in a member run
#   project.sh link|unlink NAME [--resource skills,agents,memory] [--plan T --approved W]
#                                         link what the project uses, kept under ~/.qargi, into the checkout (skills, agents) and into the
#                                         runtime's memory directory (memory), as the runtime's definition says (lib/project_link.py, on
#                                         lib/linker.py); one plan and one token for all of it. Run it inside a worktree of the project
#                                         to link that worktree: nothing records the worktrees, the links are the record. unlink undoes
#                                         the same links and puts back what they replaced
#   project.sh profile check [NAME] [--profile FILE]   read only: the repository's profile (CONFIG/profiles/<repository>.md, or FILE): exit 1 when it still
#                                         carries the shipped template header; a gate command the repository's instruction files and Makefile targets do not
#                                         know is a warning (exit 0). project validate prints the header finding as a WARN line
#   project.sh show NAME | list | validate FILE|NAME   (a missing or empty models.provider is reported as a `finding:` line, and a pack linked to
#                                         a role of the project that is not in the pack library as a `WARN:` line; neither changes the exit
#                                         status, so storing and the flows after it work as before)
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

# provision_reads PATH: succeeds when a provision reads the answer at PATH (or an answer below it: setting an object sets what it holds). The one
# list of them, taken from where provision reads the answers (lib/provision.sh, the helpers in lib/lib.sh it calls, lib/provider.py and lib/packs.sh
# render); a key that is not here is read where it is used (the branch guards, the release, review apply, the lead's context, ...), never by a provision.
provision_reads() {
  case $1 in
    roles.*.push|roles.*.push.*) return 1;;                                     # the push policy is validated, not read: only "none" is implemented
    profiles.*.tier|profiles.*.model|profiles.*.effort|profiles.*.purpose) return 1;;   # a profile is read for its base and abilities (class_abilities)
    memory.tiers|memory.tiers.*) return 1;;                                     # the memory tiers are read by the memory verbs
    repo|repo.url|repo.long_lived) return 0;;                                   # the lead's teams block names the repository and its branches
    teams|teams.*|roles|roles.*|profiles|profiles.*) return 0;;                 # members, their model, effort, packages, skills, tools, packs, base branch
    budget_cents|memory|memory.memory_store|memory.reference_store) return 0;;  # the budget and the stores to attach
    models|models.provider|models.provider.*|models.extensions|models.extensions.*|models.accept_no_barrier|models.accept_no_barrier.*) return 0;;   # the runtime, its extensions, the read-only barrier
    lead|lead.model|lead.effort|lead.push|lead.push.*) return 0;;               # the lead agent, and the push rules in its prompt and tools
    packs|packs.none) return 0;;                                                # skills and tools render by what is linked
    cloud|cloud.*) return 0;;                                                   # the cloud profile and workspace every cloud call runs under
  esac
  return 1
}

set_note() { # project path json-value -> what `set` adds to its line: the provision note, for the answers a provision reads (provision_reads)
  provision_reads "$2" || return 0
  printf " (applies to the next provision; use 'instances budget' for a live deployment)"
}

gates_lines() { # ANSWERS_FILE -> with declared gates, a heading and one line each (tier, name, command); nothing when none is declared or they are not valid (validate says so)
  local sel
  sel=$(python3 -I "$(dirname "$(readlink -f "$0")")/gates.py" select "$1" feature release 2>/dev/null) || return 0
  [ -n "$sel" ] || return 0
  echo "declared gates (they replace the test command: feature verify and release verify run them in order and stop at the first failure):"
  jq -r '.[] | "  \(.tier)  \(.name)  \(.command)"' <<<"$sel"
}

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
# the models and the model-id pattern are the project's provider's (models.provider: one name, or {local, cloud}). There is no default
# provider: with none named, or none that has a descriptor, the provider-specific checks (the model-id pattern and the tier names) are
# skipped and a model id only has to look like one; the `finding:` lines for that are printed by no_provider after a successful validate.
# With a runtime per surface, a model id passes when the runtime of any surface named accepts it (a role's model may be a member's or an
# instance's), and the keys and values of the object are checked here: a surface is local or cloud, its value a provider or family name.
_m = c.get("models") if isinstance(c, dict) else None
pname = _m.get("provider") if isinstance(_m, dict) else None
bad = []
Ds = []
def _runtime(name, surface):
    try:
        return provider.summary(provider.resolve_runtime(name, surface), surface)
    except provider.ProviderError:
        return None
if isinstance(pname, str) and pname.strip():       # a runtime or a family: the runtime each surface resolves it to
    Ds.extend(d for d in (_runtime(pname.strip(), sf) for sf in provider.SURFACES) if d)
elif isinstance(pname, dict):
    for sf, nm in pname.items():
        if sf not in provider.SURFACES:
            bad.append("models.provider.%s: not a surface (%s)" % (sf, ", ".join(provider.SURFACES)))
        elif not isinstance(nm, str) or not provider.NAME_RE.match(nm.strip()):
            bad.append("models.provider.%s: a provider or family name (qargi provider list), as a string" % sf)
        else:
            d = _runtime(nm.strip(), sf)
            if d: Ds.append(d)
seen = set(); Ds = [d for d in Ds if not ((d["provider"], d["surface"]) in seen or seen.add((d["provider"], d["surface"])))]
if Ds:
    _pats = [re.compile(d["model_pattern"]) for d in Ds]
    class _AnyOf:
        def fullmatch(self, v): return any(p.fullmatch(v) for p in _pats)
    model_ok = _AnyOf()
    aliases = [a for a in dict.fromkeys(a for d in Ds for a in d["aliases"].values()) if a]
    tier_names = list(Ds[0]["tiers"])
    def like(tier): return "a model id like %s" % " or ".join(dict.fromkeys(d["tiers"][tier] for d in Ds))
else:
    model_ok = re.compile(r"[a-z0-9][a-z0-9.-]*")
    aliases = []
    tier_names = list(provider.TIERS)
    def like(tier): return "a model id (lower-case letters, digits, . and -; the provider's own pattern is checked once models.provider names one)"
def need(cond, msg):
    if not cond: bad.append(msg)
need(c.get("schema") == 1, "schema must be 1")
need(re.fullmatch(r"[a-z][a-z0-9]{0,23}", c.get("project", "") or ""), "project: one lower-case token (letters, digits)")
repo = c.get("repo", {})
need(isinstance(repo.get("url"), str) and repo["url"] and "OWNER/REPO" not in repo["url"], "repo.url is required (replace the placeholder)")
ll = repo.get("long_lived", [])
need(isinstance(ll, list) and ll and all(isinstance(x, str) and x for x in ll), "repo.long_lived: the branches no agent may ever touch (e.g. master, develop)")
# repo.detached: long-lived branches that never meet develop, master, release, hotfix or feature branches (a documentation site, say).
# Names only: qargi refuses the merges between them and the git-flow branches (lib/gitflow.sh detached_mix)
def branch_name(x):
    return isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", x) and ".." not in x and "//" not in x and not x.endswith(("/", ".", ".lock"))
FLOW_NAMES = ("master", "develop")
FLOW_PREFIXES = ("feature/", "agent/", "release/", "hotfix/")
det = repo.get("detached", [])
need(isinstance(det, list) and all(branch_name(x) for x in det) and len(set(det)) == len(det),
     "repo.detached: a list of distinct branch names (for example a documentation site's branch) that never merge with develop, master, release, hotfix or feature branches")
if isinstance(det, list):
    for x in det:
        if isinstance(x, str) and (x in FLOW_NAMES or x.startswith(FLOW_PREFIXES)):
            bad.append("repo.detached: %s is a git-flow branch (master, develop, feature/*, agent/*, release/*, hotfix/*); a detached branch is another long-lived branch" % x)
# repo.parking_branch: the branch the main checkout rests on (default scratch); qargi fast-forwards it to develop, never pushes or merges it
pk = repo.get("parking_branch", "scratch")
need(branch_name(pk), "repo.parking_branch: a branch name (default scratch): the branch the project's main checkout rests on while qargi moves develop")
if branch_name(pk):
    if pk in FLOW_NAMES or pk.startswith(FLOW_PREFIXES): bad.append("repo.parking_branch: %s is a git-flow branch; use a branch of its own such as scratch" % pk)
    if isinstance(ll, list) and pk in ll: bad.append("repo.parking_branch: %s is also in repo.long_lived; the parking branch is reset to develop, so it is not long-lived" % pk)
    if isinstance(det, list) and pk in det: bad.append("repo.parking_branch: %s is also in repo.detached" % pk)
# branches.delete_merged, branches.push_features and branches.push_develop: what the flow does on origin (lib/feature.sh)
brs = c.get("branches", {})
need(isinstance(brs, dict), "branches: an object like {delete_merged: local, push_features: never, push_develop: true}")
if isinstance(brs, dict):
    for k in brs:
        if k not in ("delete_merged", "push_features", "push_develop"): bad.append("branches.%s: unknown key (delete_merged, push_features, push_develop)" % k)
    need(isinstance(brs.get("push_develop", True), bool), "branches.push_develop: true (default: feature finish pushes develop when the repository has an origin) or false (develop stays local)")
    need(brs.get("delete_merged", "local") in ("local", "local+remote"), "branches.delete_merged: local (default) or local+remote (feature finish also deletes the branch on origin)")
    need(brs.get("push_features", "never") in ("never", "when-shared", "always"), "branches.push_features: never (default), when-shared (only a branch origin already has) or always")
# git.author: the identity qargi review apply gives the applied commits (a string 'Name <email>'; unset: the repository's user.name and user.email)
# review.keep_author: true keeps the member's author on the applied commits instead (default false)
gt = c.get("git", {})
need(isinstance(gt, dict) and set(gt) <= {"author"}, "git: an object like {author: \"Example Author <author@example.com>\"} (unknown key: only author)")
if isinstance(gt, dict) and gt.get("author") is not None:
    ga = gt["author"]
    need(isinstance(ga, str) and re.fullmatch(r"[^<>]*[^<>\s] <[^<>\s@]+@[^<>\s@]+>", ga) and not any(ord(ch) < 32 or ord(ch) == 127 for ch in ga),
         "git.author: a name and an email as 'Name <email>' (for example Example Author <author@example.com>), no control characters")
# review.scrub: the command qargi review check runs in a temporary checkout of the applied series (a command line, or a list of words), with the range in
# QARGI_SCRUB_BASE and QARGI_SCRUB_TIP; review.trailer_policy: none (default) or reject (a commit with a co-author or generated-with trailer fails the check)
rvw = c.get("review", {})
need(isinstance(rvw, dict) and set(rvw) <= {"keep_author", "scrub", "trailer_policy"}, "review: an object like {keep_author: false, scrub: \"scripts/scrub\", trailer_policy: \"none\"} (unknown key: only keep_author, scrub, trailer_policy)")
if isinstance(rvw, dict):
    need(isinstance(rvw.get("keep_author", False), bool), "review.keep_author: true (qargi review apply keeps the member's author on the applied commits) or false (default: the author is reset to git.author)")
    if "scrub" in rvw:
        sc = rvw["scrub"]
        ctl = lambda t: any(ord(ch) < 32 or ord(ch) == 127 for ch in t)
        need((isinstance(sc, str) and sc.strip() and not ctl(sc)) or (isinstance(sc, list) and sc and all(isinstance(x, str) and x and "\x00" not in x for x in sc)),
             "review.scrub: the command qargi review check runs on the applied series, one command line or a list of words (for example [\"scripts/scrub\"]); it gets the range in QARGI_SCRUB_BASE and QARGI_SCRUB_TIP")
    need(rvw.get("trailer_policy", "none") in ("none", "reject"), "review.trailer_policy: none (default) or reject (a commit with a Co-Authored-By or Generated-with trailer fails qargi review check)")
# gates: the declared gates (optional), an ordered list of {name, command, tier}: feature verify runs the feature tier, release verify the feature
# tier then the release tier, and the CI jobs of a release are compared with the names (lib/gates.py)
import gates as _gates
bad.extend(_gates.problems(c.get("gates")))
# backlog.file: the markdown file of the project's backlog (optional; qargi backlog): a path, ~/... or relative to the repository; it may be outside it
bkl = c.get("backlog", {})
need(isinstance(bkl, dict) and set(bkl) <= {"file"}, "backlog: an object like {file: \"/path/backlog.md\"} (unknown key: only file)")
if isinstance(bkl, dict) and "file" in bkl:
    bf = bkl["file"]
    need(isinstance(bf, str) and bf.strip() and not any(ord(ch) < 32 or ord(ch) == 127 for ch in bf),
         "backlog.file: the path of a markdown file of items written '- [some-id] text', an absolute path, ~/... or a path relative to the repository; no control characters")
# worktrees.root: where qargi makes worktrees (ROOT/<branch>); an absolute path (or ~/...), not inside the repository
wts = c.get("worktrees", {})
need(isinstance(wts, dict) and set(wts) <= {"root"}, "worktrees: an object like {root: \"/path\"}")
if isinstance(wts, dict) and "root" in wts:
    import os
    wr = wts["root"]
    if not (isinstance(wr, str) and wr.strip() and (wr.startswith("/") or wr.startswith("~/"))):
        bad.append("worktrees.root: an absolute path (or ~/...) such as /home/you/work/worktrees (default: the state directory's worktrees/PROJECT)")
    elif isinstance(repo.get("path"), str) and repo["path"]:
        rr = os.path.realpath(os.path.expanduser(repo["path"])); wp = os.path.realpath(os.path.expanduser(wr))
        if wp == rr or wp.startswith(rr + os.sep): bad.append("worktrees.root: %s is inside the repository; a worktree inside the working tree is a mess" % wr)
# upstream: a fork that follows an upstream repository (lib/upstream.sh): the remote, the branch it follows, the local branch that carries the
# upstream line (default upstream; never a git-flow branch) and, optionally, the command array that checks the overlay
up = c.get("upstream", {})
need(isinstance(up, dict), "upstream: an object like {remote: \"upstream\", branch: \"main\", into: \"upstream\", overlay_check: [\"make\", \"check\"]}")
if isinstance(up, dict):
    for k in up:
        if k not in ("remote", "branch", "into", "overlay_check"): bad.append("upstream.%s: unknown key (remote, branch, into, overlay_check)" % k)
    if up:
        need(isinstance(up.get("remote"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", up.get("remote") or ""), "upstream.remote: the name of a git remote of the repository, such as upstream")
        need(branch_name(up.get("branch")), "upstream.branch: the upstream branch the fork follows, such as main")
    into = up.get("into", "upstream")
    need(branch_name(into), "upstream.into: a branch name (default upstream): the local branch that carries the upstream line and nothing else")
    if branch_name(into) and (into in FLOW_NAMES or into.startswith(FLOW_PREFIXES)): bad.append("upstream.into: %s is a git-flow branch; the upstream line needs a branch of its own, such as upstream" % into)
    if branch_name(into) and branch_name(pk) and into == pk: bad.append("upstream.into: %s is also the parking branch" % into)
    oc = up.get("overlay_check", [])
    need(isinstance(oc, list) and all(isinstance(x, str) and x for x in oc), "upstream.overlay_check: a command as an array of words, such as [\"make\", \"check\"]")
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
mz = c.get("marshal")
if mz is not None:
    need(isinstance(mz, dict), "marshal: an object (the only answer in it is lease_minutes)")
    ls = mz.get("lease_minutes") if isinstance(mz, dict) else None
    if ls is not None:
        need(isinstance(ls, int) and not isinstance(ls, bool) and 1 <= ls <= 1440, "marshal.lease_minutes: a whole number of minutes from 1 to 1440 (default 15)")
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
    if not isinstance(cfg, dict):   # roles.NAME = "x" or null: nothing below can be read from it
        bad.append("%s: an object" % p); continue
    need(isinstance(cfg.get("base"), str) and cfg["base"], "%s.base: base branch, or @dispatcher for the dispatching session's branch" % p)
    push = cfg.get("push", {})
    mode = push.get("mode")
    need(mode in ("none", "coordinator", "agent"), "%s.push.mode: none (the only implemented policy)" % p)
    if mode in ("coordinator", "agent"):
        bad.append("%s.push.mode: only 'none' is implemented; the coordinator and agent push policies are not built yet" % p)
    po = cfg.get("packs_off", [])
    need(isinstance(po, list) and all(isinstance(x, str) and re.fullmatch(r"(skill|tool):[a-z0-9][a-z0-9-]{0,40}", x) for x in po), "%s.packs_off: a list like [\"skill:name\", \"tool:name\"]" % p)
    need(cfg.get("model") is None or (isinstance(cfg["model"], str) and model_ok.fullmatch(cfg["model"])), "%s.model: %s (or leave it out: the provider's balanced model)" % (p, like("balanced")))
    need(cfg.get("effort") in efforts, "%s.effort: %s" % (p, "|".join(sorted(efforts))))
    need(isinstance(cfg.get("apt", []), list), "%s.apt: a list of packages" % p)
    need(isinstance(cfg.get("pip", []), list), "%s.pip: a list of Python packages" % p)
    if "go" in cfg:
        bad.append("%s.go: no such answer; a Go tool is an entry of %s.tools: {kind: go, name: PACKAGE, version: vX.Y.Z}" % (p, p))
    import tools as _tools   # lib/tools.py: the pinned tools of a role (go, binary, submodule) and what each entry needs
    bad.extend(_tools.problems(p, cfg.get("tools")))
    off = cfg.get("tools_off", [])
    need(isinstance(off, list) and all(x in ("web_search", "web_fetch", "edit", "write", "read", "bash", "glob", "grep") for x in off), "%s.tools_off: built-in tools to disable (web_search, web_fetch, edit, ...)" % p)
    sk = cfg.get("skills", [])
    need(isinstance(sk, list) and all(x in ("pdf", "docx", "pptx", "xlsx") for x in sk), "%s.skills: any of pdf, docx, pptx, xlsx" % p)
if isinstance(r, dict):
    import tools as _tools
    bad.extend(_tools.conflicts(r))
prof = c.get("profiles")
if prof is not None:
    import os
    md = json.load(open(os.path.join(sys.argv[3], "model-defaults.json")))
    tiers_ok = tier_names
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
        if "model" in pf: need(isinstance(pf["model"], str) and (pf["model"] in aliases or model_ok.fullmatch(pf["model"])), "%s.model: %s" % (p, (", ".join(aliases) + " or " if aliases else "") + like("balanced")))
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
pk_ = c.get("packs")
if pk_ is not None:
    need(isinstance(pk_, dict) and set(pk_) <= {"none"} and isinstance(pk_.get("none", False), bool),
         "packs: an object like {none: true} (none: the project uses no project packs, so packs check passes without a render)")
rn = c.get("runs")
if rn is not None:
    need(isinstance(rn, dict) and set(rn) <= {"owned_refs"}, "runs: an object like {owned_refs: [\"refs/heads/foo-*\"]} (owned_refs: the refs a runtime or harness creates in the repository; verify and clean accept them)")
    if isinstance(rn, dict) and "owned_refs" in rn:
        import owned_refs as _owned   # lib/owned_refs.py: what a pattern may be (a literal prefix, never develop, master, a long-lived or git-flow branch)
        bad.extend(_owned.problems(rn["owned_refs"], ll if isinstance(ll, list) else []))
need(isinstance(c.get("budget_cents", 0), int) and c.get("budget_cents", 0) > 0, "budget_cents: a positive whole number (set on the deployment)")
if "env" in c:
    import env as _env   # lib/env.py: the keys of the environment overrides and what each takes
    bad.extend(_env.problems(c["env"]))
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
    need(model_ok.fullmatch((ld or {}).get("model", "") or ""), "lead.model: %s (needed when teams are defined)" % like("deep"))
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
cw = (c.get("lead") or {}).get("context_window") if isinstance(c.get("lead"), dict) else None
need(cw is None or (isinstance(cw, int) and not isinstance(cw, bool) and cw >= 1000),
     "lead.context_window: a number of tokens (at least 1000), or null to derive the window from the model of the session (its runtime's table); set it when your session's window is known, for example 1000000")
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
import release_sign   # the signing, assets and notes answers of a release (lib/release_sign.py)
bad.extend(release_sign.problems(c.get("release")))
import release_site   # the documentation site of a release: site.enabled, site.branch, site.config (lib/release_site.py)
bad.extend(release_site.problems(c))
print("\n".join(bad) if bad else "ok")
sys.exit(1 if bad else 0)
EOF
}

# pack_warn FILE: a `WARN:` line for each pack linked at a scope that reaches a role of the project but is not in the pack library (one
# removed or never imported: the role loses it, or fails its check, at the next render). Never an error: validate still exits 0.
pack_warn() {
  local f=$1 prj links pack rs kind n
  links=$DA_CONF/packs/links.json; [ -f "$links" ] || return 0
  prj=$(jq -r '.project // empty' "$f" 2>/dev/null); [ -n "$prj" ] || return 0
  while IFS=$'\t' read -r pack rs; do
    [ -n "$pack" ] || continue; kind=${pack%%:*}; n=${pack#*:}
    if [ "$kind" = skill ]; then [ -e "$DA_CONF/packs/skills/$n" ] && continue; else [ -e "$DA_CONF/packs/tools/$n.json" ] && continue; fi
    echo "WARN: $pack is linked to $rs of $prj but is not in the pack library (qargi $kind list); import it, or unlink it: qargi $kind unlink $n"
  done < <(jq -r --arg p "$prj" --slurpfile c "$f" '
    ($c[0].roles // {} | keys - ["lead"]) as $rs
    | [.links[] | select(.scope == "user" or .scope == "user-role" or .project == $p) | . as $l
       | $rs[] | select($l.scope == "user" or $l.scope == "project" or $l.role == .) | [$l.pack, .]]
    | group_by(.[0])[] | .[0][0] + "\t" + (map(.[1]) | unique | join(", "))' "$links" 2>/dev/null)
}

# no_provider FILE [NAME]: prints the findings and returns 0 when the answers name no provider (models.provider missing, not a string or an
# object, or blank: the same rule as provider.py project_provider), or leave a surface without one (the object form), or name one that
# has no definition, or a name that serves only one surface, or a single name resolved through its family (the notice of
# provider.resolve_project: name a runtime for each surface). Never an error: a project without one is stored and used as before, but the
# verbs that need a provider on a surface (agent, provision, packs apply/check --target, packs link/unlink, skill accept, marshal handoff, a
# session) refuse it with exit 2, and validate skips the provider's model checks.
no_provider() { # the script is an argument, not stdin: FILE may be /dev/stdin
  local src
  src=$(cat <<'EOF'
import json, sys
sys.path.insert(0, sys.argv[3])
import provider as P
try:
    with open(sys.argv[1]) as f: ans = json.load(f)
except (OSError, ValueError):
    sys.exit(1)
name = sys.argv[2] or (ans.get("project") if isinstance(ans, dict) else None) or "NAME"
p = P._provider_answer(ans)
out = []
if p is None or (isinstance(p, dict) and not p):
    out.append("finding: models.provider is not set and there is no default provider: qargi project set %s models.provider PROVIDER (qargi provider list)" % name)
elif isinstance(p, dict):
    for sf in P.SURFACES:
        v = p.get(sf)
        if not isinstance(v, str) or not v.strip():
            out.append("finding: models.provider.%s is not set, so the verbs that run on the %s surface refuse this project: qargi project set %s models.provider.%s NAME (qargi provider list)" % (sf, sf, name, sf))
            continue
        try:
            P.resolve_project(ans, sf, name)
        except P.ProviderError as e:
            out.append("finding: models.provider.%s '%s' cannot be used: %s" % (sf, v.strip(), e))
else:
    notices, refused, served = [], [], 0
    for sf in P.SURFACES:
        try:
            notice = P.resolve_project(ans, sf, name)[1]
            served += 1
            if notice: notices.append(notice)
        except P.NoProvider as e:
            served += 1
            refused.append(str(e))
        except P.ProviderError:
            pass
    if not served:
        out.append("finding: models.provider '%s' has no descriptor under lib/providers/ (qargi provider list): its model ids and tiers were not checked" % p)
    else:
        out.extend("finding: " + n for n in notices)
        out.extend("finding: " + r for r in refused)
print("\n".join(out))
sys.exit(0 if out else 1)
EOF
  )
  python3 -I -c "$src" "$1" "${2:-}" "$(dirname "$(readlink -f "$0")")"
}

# the keys no verb here stores: models.extensions and models.accept_no_barrier change what an agent may run on or accept a surface with no
# read-only barrier, so they take a plan token and an approval (qargi provider enable|disable|accept, which store through lib/gated_answers.py).
# Every route that writes a whole answers file (init, attach, new) checks them here: the keys of the file that differ from the stored ones
# that add or change an entry (none stored: the keys the file has; an empty list or object counts as absent; dropping an entry is allowed), one per line
gated_keys_changed() { # NEWFILE [STOREDFILE]
  [ -f "${2:-}" ] || set -- "$1" /dev/null
  jq -rn --slurpfile n "$1" --slurpfile s "$2" '
    def norm: if . == null or . == [] or . == {} then null else . end;
    def keys_of: if type == "object" and (.models | type) == "object" then .models else {} end;
    # a file may keep or drop what is stored (that only narrows trust); it may not add or change an entry
    def narrower($a; $b; $k): ($a[$k] | norm) as $x | ($b[$k] | norm) as $y
      | if $x == null then true elif $y == null then false
        elif ($x | type) == "array" then (($x - $y) | length) == 0
        elif ($x | type) == "object" then ($x | to_entries | all(. as $e | $y[$e.key] == $e.value))
        else $x == $y end;
    ($n[0] | keys_of) as $a | ($s[0] | keys_of) as $b
    | ["extensions", "accept_no_barrier"][] | . as $k | select(narrower($a; $b; $k) | not) | "models." + $k'
}
gated_refuse() { # NEWFILE [STOREDFILE]: says so and returns 1 when the file would add or change a gated key
  local bad; bad=$(gated_keys_changed "$@" | paste -sd, | sed 's/,/, /g')
  [ -z "$bad" ] || { echo "qargi: the answers would add or change $bad, which no project verb stores: they change what an agent may run on or accept a surface with no read-only barrier, so they take a plan token and an approval (qargi provider enable PROJECT EXTENSION, qargi provider accept NAME --surface S --no-barrier); leave them as they are stored, or out of the file; nothing stored" >&2; return 1; }
}

case $verb in
  template)
    n=${1:-}; valid_project "$n" || usage_die "template needs a project name (lower-case letters and digits)"
    # no model and no provider: the template names no vendor. A role's model is its provider's tier (project set models.provider.local NAME)
    # until you give one; the efforts are the table's, the same for every provider
    jq -n --arg n "$n" --slurpfile d "$(dirname "$(readlink -f "$0")")/model-defaults.json" \
    '$d[0].profiles as $t | {
      schema: 1, project: $n,
      repo: {url: "https://github.com/OWNER/REPO", path: "", credential_file: "", long_lived: ["master", "develop"]},
      roles: {
        build: {base: "@dispatcher", push: {mode: "none"}, model: null, effort: $t.build.effort, apt: [], tools: [], skills: []},
        write: {base: "gh-pages", push: {mode: "none"}, model: null, effort: $t.write.effort, apt: [], tools: [], skills: ["pdf"]}
      },
      lead: {context_window: null},
      models: {provider: ""},
      memory: {memory_store: "", reference_store: "", tiers: {}},
      budget_cents: 500}';;
  init)
    n=${1:-}; shift || true; valid_project "$n" || usage_die "init needs a project name"
    ans='' force=''
    while [ $# -gt 0 ]; do case $1 in --answers) need_val "$1" $#; ans=$2; shift 2;; --force) force=1; shift;; *) usage_die "unknown option $1";; esac; done
    [ -f "$ans" ] || usage_die "init needs --answers FILE (see: project template $n)"
    out=$(validate "$ans") || { echo "$out" >&2; die "the answers are not valid; nothing stored"; }
    [ "$(jq -r .project "$ans")" = "$n" ] || die "the answers are for project '$(jq -r .project "$ans")', not '$n'"
    mkdir -p "$PROJ_DIR"; chmod 700 "$PROJ_DIR"
    [ ! -e "$PROJ_DIR/$n.json" ] || [ -n "$force" ] || die "project $n is already initialised (--force to replace)"
    gated_refuse "$ans" "$PROJ_DIR/$n.json" || exit 1
    jq . "$ans" > "$PROJ_DIR/$n.json.tmp" && chmod 600 "$PROJ_DIR/$n.json.tmp" && mv "$PROJ_DIR/$n.json.tmp" "$PROJ_DIR/$n.json"
    echo "project $n stored in $PROJ_DIR/$n.json"
    no_provider "$PROJ_DIR/$n.json" || true
    jq -r '"lead context window: " + (if (.lead.context_window // null) == null then "derived from the model of the session (qargi project set \($n) lead.context_window TOKENS to fix it)" else "\(.lead.context_window) tokens" end)' --arg n "$n" "$PROJ_DIR/$n.json"
    jq -r '.roles | to_entries[] | "  role \(.key): base \(.value.base), push \(.value.push.mode)" + (if .value.push.branch_pattern then " (\(.value.push.branch_pattern))" else "" end) + ", \(.value.model // "provider tier")/\(.value.effort)"' "$PROJ_DIR/$n.json";;
  new)
    # a new project: its directory, a git repository on the methodology's branches and the generic files; the plan first
    n=${1:-}; shift || true; valid_project "$n" || usage_die "new needs a project name (lower-case letters and digits)"
    meth=gitflow dir='' url='' dep='' force='' prov='' provl='' provc='' PLAN_ARG='' APPROVED='' PARAMS=()
    while [ $# -gt 0 ]; do
      case $1 in --methodology) need_val "$1" $#; meth=$2; shift 2;; --dir) need_val "$1" $#; dir=$2; shift 2;; --url) need_val "$1" $#; url=$2; shift 2;; --deployment) need_val "$1" $#; dep=$2; shift 2;; --provider) need_val "$1" $#; prov=${2:-}; shift 2;;
        --provider-local) need_val "$1" $#; provl=${2:-}; shift 2;; --provider-cloud) need_val "$1" $#; provc=${2:-}; shift 2;;
        --param) need_val "$1" $#; PARAMS+=(--param "$2"); shift 2;; --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;; *) usage_die "unknown option $1";; esac
    done
    export PLAN_ARG   # need_plan reads it
    lib=$(dirname "$0")
    [ -n "$dir" ] || dir=$PWD/$n
    dir=${dir/#\~/$HOME}; case $dir in /*) ;; *) dir=$PWD/$dir;; esac
    [ -d "$(dirname "$dir")" ] || die "$(dirname "$dir") does not exist: create it first, or give --dir"
    if [ -e "$dir" ]; then [ -d "$dir" ] && [ -z "$(ls -A "$dir")" ] || die "$dir exists and is not an empty directory"; fi
    files=$(python3 -I "$lib/methodology.py" files "$meth" --param "project=$n" "${PARAMS[@]}") || exit 1
    if [ -n "$dep" ]; then python3 -I "$lib/methodology.py" deployment "$meth" "$dep" >/dev/null || exit 1; fi
    # the provider options name providers that can be used (--provider: one name for both surfaces; --provider-local, --provider-cloud: one per
    # surface, each a runtime or a family), before anything is created
    PROVARGS=(); [ -z "$prov" ] || PROVARGS+=(--provider "$prov"); [ -z "$provl" ] || PROVARGS+=(--provider-local "$provl"); [ -z "$provc" ] || PROVARGS+=(--provider-cloud "$provc")
    [ "${#PROVARGS[@]}" = 0 ] || python3 -I "$lib/attach.py" check-provider "${PROVARGS[@]}" || exit 1
    ptxt=${prov:-not chosen (none is stored; set one with qargi project set $n models.provider NAME, or models.provider.local / models.provider.cloud)}
    [ -z "$provl$provc" ] || ptxt="local ${provl:-not chosen}, cloud ${provc:-not chosen}$([ -n "$provl" ] && [ -n "$provc" ] || echo " (a surface left out refuses its verbs until: qargi project set $n models.provider.SURFACE NAME)")"
    [ ! -e "$PROJ_DIR/$n.json" ] || die "project $n is already initialised (qargi project show $n)"
    long=$(python3 -I - "$lib" "$meth" <<'PY'
import sys; sys.path.insert(0, sys.argv[1]); import methodology as M
print(" ".join(M.load(sys.argv[2])[2]["branches"]["long_lived"]))
PY
    ) || exit 1
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$dir" "$meth" "$url" "$dep" "$prov" "$provl" "$provc" "$(jq -S -c . <<<"$files")" | plan_token)
    echo "new project $n with the $meth methodology at $dir"
    echo "  git repository with the branches: $long (the first is the initial one; work starts on the last)"
    echo "  files:"; jq -r '.[].dest | "    " + .' <<<"$files"
    if [ -n "$url" ]; then echo "  qargi answers stored for $url (outside the repository)"; else echo "  no --url: the answers are stored later, when the remote exists: qargi project attach $dir --url URL"; fi
    echo "  deployment: ${dep:-not chosen (see below)}"
    echo "  provider: $ptxt"
    echo
    if [ -z "$APPROVED" ]; then
      python3 -I "$lib/methodology.py" deployment "$meth"
      echo; echo "choose one with --deployment ID (qargi methodology deployment $meth ID shows how); you can do it by hand or ask for it to be done for you"
      echo; echo "plan token: $tok   (create with: qargi project new $n --plan $tok --approved \"...\" plus the same options)"
      exit 0
    fi
    QARGI_NESTED='' need_plan "$tok"
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
      det=$(python3 -I "$lib/attach.py" detect "$dir" --name "$n" --methodology "$meth" "${PROVARGS[@]}") || exit 1
      # the gates given as --param gates=JSON are in the files just written, so they are stored too (the last --param gates= wins, as in the render,
      # which has refused a value that is not valid; validate below checks the stored list the way project set does); none when empty or []
      gv=''; for p in "${PARAMS[@]}"; do case $p in gates=*) gv=${p#gates=};; esac; done
      f=$(mktemp); jq --arg u "$url" --arg d "$dep" --arg g "$gv" '.answers | .repo.url = $u | if $d == "" then . else .deployment = $d end | (($g | fromjson?) // []) as $gs | if ($gs | length) > 0 then .gates = $gs else . end' <<<"$det" > "$f"
      out=$(validate "$f") || { echo "$out" >&2; rm -f "$f"; die "the project was created but its answers are not valid; nothing stored (qargi project attach $dir --url URL)"; }
      gated_refuse "$f" || { rm -f "$f"; exit 1; }
      mkdir -p "$PROJ_DIR"; chmod 700 "$PROJ_DIR"; mv "$f" "$PROJ_DIR/$n.json"; chmod 600 "$PROJ_DIR/$n.json"
      echo "project $n stored in $PROJ_DIR/$n.json"
      no_provider "$PROJ_DIR/$n.json" || true
    fi
    if [ -n "$dep" ]; then echo; python3 -I "$lib/methodology.py" deployment "$meth" "$dep"; fi
    echo; echo "next: create the repository on your host and push (git remote add origin URL; git push -u origin ${long// / })"
    echo "      a first release: qargi release start $(jq -r '.[] | select(.dest == "VERSION") | .content' <<<"$files" | tr -d '\n') (not built yet)";;
  attach)
    # an existing repository: read it, show what qargi would store and what the methodology has that it lacks; store only after approval
    dir=. name='' meth=gitflow url='' force='' prov='' provl='' provc='' PLAN_ARG='' APPROVED=''
    while [ $# -gt 0 ]; do
      case $1 in --name) need_val "$1" $#; name=$2; shift 2;; --methodology) need_val "$1" $#; meth=$2; shift 2;; --url) need_val "$1" $#; url=$2; shift 2;; --force) force=1; shift;; --provider) need_val "$1" $#; prov=${2:-}; shift 2;;
        --provider-local) need_val "$1" $#; provl=${2:-}; shift 2;; --provider-cloud) need_val "$1" $#; provc=${2:-}; shift 2;;
        --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;; -*) usage_die "unknown option $1";; *) dir=$1; shift;; esac
    done
    export PLAN_ARG   # need_plan reads it
    PROVARGS=(); [ -z "$prov" ] || PROVARGS+=(--provider "$prov"); [ -z "$provl" ] || PROVARGS+=(--provider-local "$provl"); [ -z "$provc" ] || PROVARGS+=(--provider-cloud "$provc")
    det=$(python3 -I "$(dirname "$0")/attach.py" detect "$dir" ${name:+--name "$name"} --methodology "$meth" "${PROVARGS[@]}") || exit 1
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
      # a stored project keeps its provider: the provider options only fill in what is not set (a name, or a surface of the object), never replace
      # one (qargi project set does that)
      if [ "${#PROVARGS[@]}" != 0 ]; then
        pm=$(jq -c --arg p "$prov" --arg l "$provl" --arg c "$provc" '
          (try .models.provider catch null) as $s0
          | ($s0 | if type == "string" then gsub("^\\s+|\\s+$"; "") else . end) as $s
          | (if $p != "" then $p else ((if $l != "" then {local: $l} else {} end) + (if $c != "" then {cloud: $c} else {} end)) end) as $w
          | if $s == null or $s == "" or $s == {} then {ok: $w}
            elif ($s | type) == "string" and ($w | type) == "string" then (if $s == $w then {ok: $w} else {err: "str", stored: $s} end)
            elif ($s | type) == "object" and ($w | type) == "object" then
              (if [$w | to_entries[] | select((($s[.key] // "") | tostring) != "" and $s[.key] != .value)] | length > 0
               then {err: "obj", stored: ($s | tojson)} else {ok: ($s + $w)} end)
            elif ($s | type) == "object" then {err: "obj", stored: ($s | tojson)}
            elif ($s | type) == "string" then {err: "strobj", stored: $s}
            else {err: "other", stored: ($s | tojson)} end' "$sf" 2>/dev/null) || pm='{"err":"other","stored":"unreadable"}'
        case $(jq -r '.err // "ok"' <<<"$pm") in
          ok) ;;
          str) die "project $n is stored with the provider '$(jq -r .stored <<<"$pm")'; --provider does not replace it (qargi project set $n models.provider NAME)";;
          obj) die "project $n is stored with a provider per surface ($(jq -r .stored <<<"$pm")); the provider options do not replace one that is set (qargi project set $n models.provider.SURFACE NAME)";;
          strobj) die "project $n is stored with the provider '$(jq -r .stored <<<"$pm")'; --provider-local and --provider-cloud do not replace it (qargi project set $n models.provider.SURFACE NAME)";;
          *) die "project $n is stored with $(jq -r .stored <<<"$pm") as its provider, which the options given do not fit; they do not replace it (qargi project set $n models.provider NAME)";;
        esac
        ans=$(jq -c --argjson v "$(jq -c .ok <<<"$pm")" '.models = ((.models // {}) | if type == "object" then . else {} end) + {provider: $v}' <<<"$ans")
      fi
    fi
    tok=$(jq -S -c . <<<"$ans" | plan_token)
    jq -r '"project \(.answers.project) from \(.found.path)\nread from: \(.found.ref | if . == "" then "no commit" else . end) (\(.found.ref_why); the checked-out branch is \(.found.current_branch | if . == "" then "none" else . end), the working tree is not read)\nmethodology: \(.methodology)\nremote (origin as read): \(.found.remote // "none")" + (if (.found.remote // "") != "" and .found.url != .found.remote then "\nrepo.url (normalised to https, no .git, no credentials): \(.found.url)" else "" end) + "\nlong-lived branches: \(.answers.repo.long_lived | join(", "))\nversion: \(.found.version.file // "not found") \(.found.version.value // "")\ntags: \(.found.tags.count) (\(.found.tags.pattern | if . == "" then "no semantic pattern" else . end))\nchangelog: \(.found.changelog.file // "none")\ntest command: \(.found.test_command | if . == "" then "not found" else . end)\nCI workflows: \(.found.ci_workflows | if length == 0 then "none" else join(", ") end)"' <<<"$det"
    [ -z "$stored" ] || gates_lines "$sf"   # the stored answers' gates: they replace the detected test command in the verify verbs
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
    echo "gaps against the $meth methodology (nothing is changed in the repository; qargi project adopt $n closes the safe ones as a branch to review):"
    jq -r 'if (.gaps | length) == 0 then "  none" else .gaps[] | "  - \(.kind): \(.what) (\(.why))" end' <<<"$det"
    jq -r '.found.env | "development environment found: section in \(.section // "none"); task runner \(.runner // "none"); bootstrap \(.bootstrap_command // "none"); doctor \(.doctor_command // "none"); \(.pins | length) pinned tool(s), \(.submodules) submodule(s) (qargi env show reads it in full)"' <<<"$det"
    # a hint only: the repository's own skills are read from the working tree, nothing is changed or stored. The directory is the project's
    # provider's (layout.project_skills_dir); a project with no provider yet (attach never guesses one) is hinted for every provider's.
    plib=$(dirname "$0"); pv=''; [ -z "$stored" ] || pv=$(python3 -I "$plib/provider.py" of "$n" --conf "$DA_CONF" --surface local 2>/dev/null </dev/null) || pv=''
    while IFS= read -r sd; do
      [ -n "$sd" ] || continue
      rs=$(jq -r .found.path <<<"$det")/$sd
      if [ -d "$rs" ] && [ ! -L "$rs" ]; then
        ns=$(find "$rs" -mindepth 2 -maxdepth 2 -name SKILL.md -type f | wc -l)
        if [ "$ns" -gt 0 ]; then echo "repo has its own $sd ($ns skill$([ "$ns" -eq 1 ] || echo s)): qargi packs link $n offers to use the library's instead and shows which are new"; fi
      fi
    done < <(python3 -I "$plib/provider.py" skills-dirs $pv 2>/dev/null </dev/null)
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
      no_provider /dev/stdin "$n" <<<"$ans" || true   # attach does not guess a provider and stores none
      echo "plan token: $tok   (store with: qargi project attach $dir --plan $tok --approved \"...\"${force:+ --force})"
      exit 0
    fi
    QARGI_NESTED='' need_plan "$tok"
    f=$(mktemp); jq . <<<"$ans" > "$f"
    out=$(validate "$f") || { echo "$out" >&2; rm -f "$f"; die "the answers are not valid; nothing stored"; }
    gated_refuse "$f" "$sf" || { rm -f "$f"; exit 1; }
    mkdir -p "$PROJ_DIR"; chmod 700 "$PROJ_DIR"
    mv "$f" "$sf"; chmod 600 "$sf"
    audit_log "project:attach" "$n"
    echo "project $n stored in $sf (approved: $APPROVED)"
    no_provider "$sf" || true;;
  adopt)
    # an attached repository: create what the methodology has and the repository lacks, only where nothing exists yet; the plan first
    n=${1:-}; shift || true; valid_project "$n" || usage_die "adopt needs the name of an attached project (qargi project list)"
    meth='' PLAN_ARG='' APPROVED=''
    while [ $# -gt 0 ]; do
      case $1 in --methodology) need_val "$1" $#; meth=${2:-}; shift 2;; --plan) need_val "$1" $#; PLAN_ARG=${2:-}; shift 2;; --approved) need_val "$1" $#; APPROVED=${2:-}; shift 2;; *) usage_die "unknown option $1";; esac
    done
    export PLAN_ARG   # need_plan reads it
    lib=$(dirname "$0")
    plan=$(python3 -I "$lib/attach.py" adopt-plan "$n" "$PROJ_DIR/$n.json" ${meth:+--methodology "$meth"}) || exit $?
    tok=$(jq -S -c .basis <<<"$plan" | plan_token)
    jq -r '"adopt project \(.project) in \(.path) with the \(.methodology) methodology\n  default branch: \(.base.name) (\(.base.sha[0:7])); integration branch: \(.integration.name)\n  nothing is pushed, merged or checked out; no existing branch or file is changed"' <<<"$plan"
    if [ "$(jq -r '.branches | length' <<<"$plan")" != 0 ]; then
      echo "  local branches to create, at the tip of the default branch:"
      jq -r '.branches[] | "    " + .name' <<<"$plan"
    fi
    if [ "$(jq -r '.files | length' <<<"$plan")" != 0 ]; then
      jq -r '"  files to write (missing from \(.integration.name); one commit on the new branch \(.adopt_branch), cut from \(.integration.name)):"' <<<"$plan"
      jq -r '.files[] | "    " + .dest' <<<"$plan"
    fi
    if [ "$(jq -r '.adopt_exists' <<<"$plan")" = true ]; then
      jq -r '"  the branch \(.adopt_branch) already exists: it is not touched; review and merge it"' <<<"$plan"
    fi
    left() { # the gaps no one should close for you: the report names them before and after
      if [ "$(jq -r '.left | length' <<<"$plan")" != 0 ]; then
        echo "  left for you to judge (changed by nothing here):"
        jq -r '.left[] | "    - \(.kind): \(.what) (\(.why))"' <<<"$plan"
      fi
    }
    left
    if [ "$(jq -r .nothing_to_do <<<"$plan")" = true ]; then echo; echo "nothing to do: the safe gaps are closed"; exit 0; fi
    echo
    if [ -z "$APPROVED" ]; then
      echo "plan token: $tok   (create with: qargi project adopt $n --plan $tok --approved \"...\"${meth:+ --methodology $meth})"
      exit 0
    fi
    QARGI_NESTED='' need_plan "$tok"
    res=$(python3 -I "$lib/attach.py" adopt-apply "$n" "$PROJ_DIR/$n.json" <<<"$plan") || exit $?
    audit_log "project:adopt" "$n"
    jq -r '.branches[] | "created branch " + .' <<<"$res"
    c=$(jq -r .commit <<<"$res")
    [ -z "$c" ] || jq -r --arg c "$c" '"created branch \(.adopt_branch) at \($c[0:7]): " + (.files | map(.dest) | join(", "))' <<<"$plan"
    left
    echo "approved: $APPROVED; nothing was pushed. Review the branch, merge it into $(jq -r .integration.name <<<"$plan") when it suits you.";;
  set)
    n=${1:-}; path=${2:-}; val=${3:-}
    [ -f "$PROJ_DIR/$n.json" ] || die "no project named '$n' (see: project list)"
    [ -n "$path" ] && [ -n "$val" ] || usage_die "set needs NAME PATH VALUE (for example: set $n budget_cents 2500)"
    printf '%s' "$path" | grep -Eq '^[a-z_][a-z0-9_.]*$' || die "PATH: dotted keys such as roles.write.effort"
    # the shared marshal backend is a machine switch with a plan and an audit line, never an answer of the project file
    case $path in marshal.lease_minutes) ;; marshal|marshal.*) die "$path is not a project answer: only marshal.lease_minutes is; to switch the shared backend use 'qargi marshal enable' or 'qargi marshal disable'";; esac
    jq empty >/dev/null 2>&1 <<<"$val" || val=$(jq -Rn --arg v "$val" '$v')
    # the answers that decide what an agent may run on (extensions) and which surface may go without a read-only barrier (accept_no_barrier) are
    # changed with a plan token and an approval, by their own verbs; this verb has neither, so it refuses them (also as keys of a whole models
    # object), for every caller and always. Those verbs store them through lib/gated_answers.py, which this verb never calls and nothing a
    # caller sets (an environment variable, an option) can reach from here
    gated=''
    case $path in
      models.extensions|models.extensions.*) gated="qargi provider enable PROJECT EXTENSION (and disable)";;
      models.accept_no_barrier|models.accept_no_barrier.*) gated="qargi provider accept NAME --surface S --no-barrier";;
      models) jq -e 'type == "object" and (has("extensions") or has("accept_no_barrier"))' >/dev/null 2>&1 <<<"$val" \
                && gated="qargi provider enable PROJECT EXTENSION, qargi provider accept NAME --surface S --no-barrier (models.extensions and models.accept_no_barrier are set by them)";;
    esac
    [ -z "$gated" ] || { echo "qargi: $path is not set with project set: it changes what an agent may run on or accepts a surface with no read-only barrier, so it takes a plan token and an approval: $gated" >&2; exit 2; }
    # a runtime that exists but does not serve that surface cannot be what the project runs there: refused (exit 2), as attach and new refuse it,
    # before anything is changed. A name with no definition, an ambiguous family or a clash is stored with a finding, as before
    case $path in models.provider.local|models.provider.cloud)
      sname=$(jq -r 'select(type == "string")' <<<"$val") || sname=''
      [ -z "$sname" ] || python3 -I - "${path#models.provider.}" "$sname" "$(dirname "$(readlink -f "$0")")" <<'PY' || exit $?
import sys
sys.path.insert(0, sys.argv[3])
import provider as P
try:
    P.resolve_runtime(sys.argv[2].strip(), sys.argv[1])
except P.NotServed as e:
    print("qargi: models.provider.%s: %s; nothing changed" % (sys.argv[1], e), file=sys.stderr)
    sys.exit(2)
except P.ProviderError:
    pass
PY
    ;; esac
    # models.provider.local|cloud sets one surface of the object form. When models.provider is still a single name (or blank), the object is made
    # first: the surface being set takes the new name, the other keeps the name it had (the same name resolves per surface exactly as before, so
    # nothing else changes) or stays unset when there was none
    carry=''
    case $path in models.provider.*) jq -e '(try .models.provider catch null) | type == "string" and test("\\S")' "$PROJ_DIR/$n.json" >/dev/null 2>&1 && carry=$(jq -r '.models.provider | gsub("^\\s+|\\s+$"; "")' "$PROJ_DIR/$n.json");; esac
    tmp=$(mktemp "$PROJ_DIR/.set.XXXXXX")
    jq --argjson v "$val" --arg p "$path" --arg carry "$carry" '
      (if ($p | startswith("models.provider.")) and ((try .models.provider catch null) | type) == "string"
       then .models.provider = (if $carry == "" then {} else {local: $carry, cloud: $carry} end) else . end)
      | setpath($p | split("."); $v)' "$PROJ_DIR/$n.json" > "$tmp"
    out=$(validate "$tmp") || { echo "$out" >&2; rm -f "$tmp"; die "that would make the project invalid; nothing changed"; }
    chmod 600 "$tmp"; mv "$tmp" "$PROJ_DIR/$n.json"
    echo "$n: $path = $val$(set_note "$n" "$path" "$val")"
    [ -z "$carry" ] || echo "note: models.provider was the single name '$carry'; it is now one name per surface, and the surface you did not set keeps '$carry'"
    case $path in models.provider|models.provider.*) no_provider "$PROJ_DIR/$n.json" "$n" || true;; esac;;
  link|unlink)
    # the project's resources, linked from where qargi keeps them: the plan first (one token for all), the change only for that plan. A link
    # changes what a session loads, so the token is always needed (an approved caller has not approved this plan) and a member never applies
    n=${1:-}; shift || true; valid_project "$n" || usage_die "$verb needs a project name (lower-case letters and digits)"
    res='' PLAN_ARG='' APPROVED=''
    while [ $# -gt 0 ]; do
      case $1 in --resource) need_val "$1" $#; res=${2// /}; shift 2;;
        --plan) need_val "$1" $#; PLAN_ARG=${2:-}; shift 2;; --approved) need_val "$1" $#; APPROVED=${2:-}; shift 2;; *) usage_die "unknown option $1";; esac
    done
    export PLAN_ARG; unset QARGI_NESTED
    [ -f "$PROJ_DIR/$n.json" ] || die "no project named '$n' (see: project list)"
    PLK=$(dirname "$(readlink -f "$0")")/project_link.py
    LW=$(mktemp -d); trap 'rm -rf "$LW"' EXIT
    python3 -I "$PLK" plan "$verb" "$n" "$res" "$LW/token" || exit $?
    [ -s "$LW/token" ] || exit 0       # nothing to do (already linked): no token
    tok=$(cat "$LW/token")
    if [ -z "$APPROVED" ]; then
      echo "plan token: $tok   (apply with: --plan $tok --approved \"<the user's go-ahead>\")"; exit 0
    fi
    [ -n "$tok" ] && need_plan "$tok"
    audit_log "project:$verb" "$n ${res:-all} $tok"
    python3 -I "$PLK" apply "$verb" "$n" "$res" "$tok" || exit $?;;
  show) n=${1:-}; [ -f "$PROJ_DIR/$n.json" ] || die "no project named '$n' (see: project list)"; jq . "$PROJ_DIR/$n.json"
    # the answers stay the JSON on standard output (it is piped); the declared gates, which replace test_command, are named on standard error
    gates_lines "$PROJ_DIR/$n.json" >&2;;
  list) ls "$PROJ_DIR" 2>/dev/null | sed -n 's/\.json$//p';;
  validate) f=${1:-}; [ -f "$f" ] || f="$PROJ_DIR/$f.json"; [ -f "$f" ] || usage_die "validate needs a file or a project name"
    validate "$f" && { no_provider "$f" || true; pack_warn "$f" || true; python3 -I "$(dirname "$(readlink -f "$0")")/project_profile.py" warn "$DA_CONF" "$f" || true; };;
  profile)
    # profile check [NAME] [--profile FILE]: read only; the profile of the project's repository, the shipped template header (exit 1), gates the repository does not know (warnings)
    [ "${1:-}" = check ] || usage_die "usage: project profile check [NAME] [--profile FILE]"; shift
    n='' pf=''
    while [ $# -gt 0 ]; do
      case $1 in --profile) need_val "$1" $#; pf=$2; shift 2;; -*) usage_die "unknown option $1";; *) [ -z "$n" ] || usage_die "profile check takes one project name"; n=$1; shift;; esac
    done
    [ -n "$n" ] || n=$(python3 -I "$(dirname "$(readlink -f "$0")")/help.py" infer 2>/dev/null) || n=''
    af=''
    if [ -n "$n" ]; then af=$PROJ_DIR/$n.json; [ -f "$af" ] || die "no project named '$n' (see: project list)"; fi
    exec python3 -I "$(dirname "$(readlink -f "$0")")/project_profile.py" check "$DA_CONF" "$af" "${pf/#\~/$HOME}";;
  *) usage_die "usage: project.sh template|init|new|attach|adopt|set|link|unlink|show|list|validate|profile ...";;
esac
