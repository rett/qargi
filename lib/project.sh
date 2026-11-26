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
#                                         name already there is kept for the surface you do not set). Prints "was: OLD" ((not set) when the
#                                         key was absent) and writes an audit line. verify.environment (the declaration a whole-suite run is
#                                         started under, lib/suite_env.py) is compared with the one last approved, kept in the state
#                                         (verify-env.json): a first declaration or a lower cpu_quota is plain, every other change loosens it
#                                         and is refused with a plan token (verify-env-change-unapproved) unless --plan TOKEN --approved WORDS
#                                         is given; init, new and attach store no file whose declaration differs from the approved one
#   project.sh unset NAME PATH [--plan T --approved W]   remove one answer: the same refusals as set (the marshal backend, the answers
#                                         that take a plan token; the options are for verify.environment only), refused in a member run, "was: OLD" and an audit line; an answer the project needs is
#                                         refused by validate and nothing changes. A null stored for an optional answer (git.author, gates,
#                                         review.*, backlog.*) is the same as not set; unset removes the key itself
#   project.sh new NAME [--methodology M] [--dir D] [--url U] [--deployment ID] [--param k=v] [--plan T --approved W]
#                       [--provider NAME | --provider-local NAME --provider-cloud NAME]
#                                         create a project directory with a git repository and the methodology's generic files;
#                                         --provider is one name for both surfaces, the other two name a runtime for each
#   project.sh attach [DIR] [--name N] [--methodology M] [--url U] [--plan T --approved W] [--force]
#                       [--provider NAME | --provider-local NAME --provider-cloud NAME]
#                                         read an existing repository, show the answers and the gaps, store on approval
#   project.sh adopt NAME [--methodology M] [--show] [--plan T --approved W]
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
#   project.sh remove NAME [--plan T --approved W]
#                                         retire a project: remove its stored answers and its members (what `agent remove` takes away for each) and forget its
#                                         approved verify.environment declaration, behind a plan and a token; never a git operation that changes anything,
#                                         never a branch or the history, and the checkout only through the member files the plan lists (a runtime that keeps
#                                         them in it: link none); the lines of .git/info/exclude stay. Refused (exit 2, nothing changed) for an unknown project, in a member
#                                         run, and while the project has an open feature, an open run, a live marshal lease, an open release cut, a linked work
#                                         tree, a cloud binding or a registered instance, or a source of those that cannot be read (lib/project_remove.py; the
#                                         refusals project-remove-*). The apply scans again after the token is checked, writes the audit line project:remove
#                                         before the first removal, and a failing step leaves the stored answers and a line that says where it stopped
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

# accepted_lines JSON INDENT LEAD: the lead's accepted deviations (JSON .accepted), apart from the open gaps
accepted_lines() {
  if [ "$(jq -r '.accepted | length' <<<"$1")" != 0 ]; then
    echo "$3accepted deviations (set by the lead in methodology_accepted; not open gaps):"
    jq -r --arg i "$2" '.accepted[] | "\($i)- \(.gap) (\(.status): \(.reason); \(.date))"' <<<"$1"
  fi
}

# provision_reads PATH: succeeds when a provision reads the answer at PATH (or an answer below it: setting an object sets what it holds). The one
# list of them, taken from where provision reads the answers (lib/provision.sh, the helpers in lib/lib.sh it calls, lib/provider.py and lib/packs.sh
# render); a key that is not here is read where it is used (the branch guards, the release, review apply, the lead's context, ...), never by a provision.
provision_reads() {
  case $1 in
    roles.*.push|roles.*.push.*) return 1;;                                     # the push policy is validated, not read: only "none" is implemented
    profiles.*.tier|profiles.*.model|profiles.*.effort|profiles.*.purpose|profiles.*.options) return 1;;   # a profile is read for its base and abilities (class_abilities); its options are read when a run is prepared
    memory.tiers|memory.tiers.*) return 1;;                                     # the memory tiers are read by the memory verbs
    repo|repo.url|repo.long_lived) return 0;;                                   # the lead's teams block names the repository and its branches
    teams|teams.*|roles|roles.*|profiles|profiles.*) return 0;;                 # members, their model, effort, packages, skills, tools, packs, base branch
    budget_cents|memory|memory.memory_store|memory.reference_store) return 0;;  # the budget and the stores to attach
    models|models.provider|models.provider.*|models.extensions|models.extensions.*|models.extra_runtimes|models.extra_runtimes.*|models.run_options|models.run_options.*|models.accept_no_barrier|models.accept_no_barrier.*) return 0;;   # the runtime, its extensions, its run options, the read-only barrier
    lead|lead.model|lead.effort|lead.push|lead.push.*) return 0;;               # the lead agent, and the push rules in its prompt and tools
    packs|packs.none) return 0;;                                                # skills and tools render by what is linked
    cloud|cloud.*) return 0;;                                                   # the cloud profile and workspace every cloud call runs under
  esac
  return 1
}

# gated_path PATH JSON -> prints, and succeeds, when PATH is an answer that only a plan token and an approval may change (the verb that does is
# named); JSON is the value being stored there (set) or the one being removed (unset). A whole models object counts when it holds those keys.
gated_path() {
  case $1 in
    packs.member_skills|packs.member_skills.*) echo "qargi packs member-skills PROJECT --enable|--disable"; return 0;;
    packs) if jq -e 'type == "object" and has("member_skills")' >/dev/null 2>&1 <<<"$2"; then
             echo "qargi packs member-skills PROJECT --enable|--disable"; return 0; fi;;
    models.extensions|models.extensions.*) echo "qargi provider enable PROJECT EXTENSION (and disable)"; return 0;;
    models.extra_runtimes|models.extra_runtimes.*) echo "qargi provider enable PROJECT --runtime NAME (and disable)"; return 0;;
    models.run_options|models.run_options.*) echo "qargi provider enable PROJECT --runtime NAME --option OPTION (and disable)"; return 0;;
    models.accept_no_barrier|models.accept_no_barrier.*) echo "qargi provider accept NAME --surface S --no-barrier"; return 0;;
    models) if jq -e 'type == "object" and (has("extensions") or has("extra_runtimes") or has("run_options") or has("accept_no_barrier"))' >/dev/null 2>&1 <<<"$2"; then
              echo "qargi provider enable PROJECT EXTENSION, qargi provider enable PROJECT --runtime NAME [--option OPTION], qargi provider accept NAME --surface S --no-barrier (models.extensions, models.extra_runtimes, models.run_options and models.accept_no_barrier are set by them)"; return 0; fi;;
  esac
  return 1
}

# answer_was FILE PATH -> the JSON the answer holds now, or the words (not set) when the key is not in the file (a null stored there is null)
answer_was() {
  jq -r --arg p "$2" '($p | split(".")) as $q | if any(paths; . == $q) then (try getpath($q) catch null | tojson) else "(not set)" end' "$1"
}

set_note() { # project path json-value -> what `set` adds to its line: the provision note, for the answers a provision reads (provision_reads)
  provision_reads "$2" || return 0
  printf " (applies to the next provision; use 'instances budget' for a live deployment)"
}

gates_lines() { # ANSWERS_FILE -> with declared gates, a heading and one line each (tier, name, command); nothing when none is declared or they are not valid (validate says so)
  local sel
  sel=$(pymod gates select "$1" feature release 2>/dev/null) || return 0
  [ -n "$sel" ] || return 0
  echo "declared gates (they replace the test command: feature verify and release verify run them in order and stop at the first failure):"
  jq -r '.[] | "  \(.tier)  \(.name)  \(.command)" + (if .covered_by then "  (release verify: covered by \(.covered_by))" else "" end)' <<<"$sel"
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
# models.extra_runtimes.local: the other runtimes of the local surface the project may start members on (qargi provider enable PROJECT --runtime NAME).
# The shape is checked here; whether each can be used (a runtime that exists, sealed, local, started by a command) changes outside the answers and
# is a finding of no_provider, so a pack that is edited later never makes the project invalid
_ex = _m.get("extra_runtimes") if isinstance(_m, dict) else None
if _ex is not None:
    if not isinstance(_ex, dict):
        bad.append("models.extra_runtimes: an object like {local: [runtime names]} (qargi provider enable PROJECT --runtime NAME)")
    else:
        bad.extend("models.extra_runtimes.%s: not a surface with extra runtimes (only local)" % k for k in _ex if k != "local")
        _lst = _ex.get("local")
        if _lst is not None and not (isinstance(_lst, list) and all(isinstance(x, str) and provider.NAME_RE.match(x) for x in _lst)):
            bad.append("models.extra_runtimes.local: a list of runtime names, each by its own name (qargi provider enable PROJECT --runtime NAME)")
        elif isinstance(_lst, list):
            try: _own = provider.resolve_project(c, "local")[0]
            except provider.ProviderError: _own = None
            for _i, _x in enumerate(_lst):
                if _x in _lst[:_i]: bad.append("models.extra_runtimes.local: %s is listed twice" % _x)
                if _x == _own: bad.append("models.extra_runtimes.local: %s is the project's own runtime, not an extra one (qargi provider disable PROJECT --runtime %s)" % (_x, _x))
# models.run_options.local.RUNTIME: the options of the runtime's definition (dispatch.run_config.options) the project enabled, a list of option names
# (qargi provider enable PROJECT --runtime NAME --option OPT). The shape and the runtime being enabled for the project (its own or an extra one) are checked
# here; whether the definition still declares each option changes outside the answers and is a finding of no_provider
_ro = _m.get("run_options") if isinstance(_m, dict) else None
_ro_local = {}
if _ro is not None:
    if not isinstance(_ro, dict):
        bad.append("models.run_options: an object like {local: {RUNTIME: [option names]}} (qargi provider enable PROJECT --runtime NAME --option OPT)")
    else:
        bad.extend("models.run_options.%s: not a surface with run options (only local)" % k for k in _ro if k != "local")
        _rl = _ro.get("local")
        if _rl is not None and not isinstance(_rl, dict):
            bad.append("models.run_options.local: an object of runtime names, each with a list of option names (qargi provider enable PROJECT --runtime NAME --option OPT)")
        elif isinstance(_rl, dict):
            try: _own_o = provider.resolve_project(c, "local")[0]
            except provider.ProviderError: _own_o = None
            _en_o = ([_own_o] if _own_o else []) + [x for x in provider.extra_runtimes_of(c) if x != _own_o]
            for _rn, _ol in _rl.items():
                _p = "models.run_options.local.%s" % _rn
                if not (isinstance(_rn, str) and provider.NAME_RE.match(_rn)):
                    bad.append("models.run_options.local.%s: a runtime name" % _rn); continue
                if not (isinstance(_ol, list) and all(isinstance(x, str) and provider.OPTION_NAME.match(x) for x in _ol)):
                    bad.append("%s: a list of option names, each one the definition of the runtime declares (qargi provider enable PROJECT --runtime %s --option OPT)" % (_p, _rn)); continue
                bad.extend("%s: %s is listed twice" % (_p, x) for _i, x in enumerate(_ol) if x in _ol[:_i])
                if _ol and _rn not in _en_o:
                    bad.append("%s: %s is not enabled for this project, so it has no options (its own runtime or one of models.extra_runtimes.local)" % (_p, _rn))
                _ro_local[_rn] = [x for x in _ol]
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
# methodology: the name of a methodology (qargi methodology list) that passes qargi methodology check; absent means gitflow
if "methodology" in c:
    mth = c["methodology"]
    if not (isinstance(mth, str) and mth):
        bad.append("methodology: the name of a methodology (qargi methodology list), a string")
    else:
        import methodology as _meth
        for _p in _meth.problems(mth):
            bad.append("methodology: %s (qargi methodology check %s says so)" % (_p, mth))
        if _meth.flow(mth) == "plain" and isinstance(ll, list) and len(ll) != 1:
            bad.append("repo.long_lived: a project of the plain methodology %s has exactly one long-lived branch" % mth)
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
# A null stored for an optional answer is the same as not set (as for gates and git.author): review.* and backlog.* drop their null keys here
rvw = c.get("review", {})
if isinstance(rvw, dict): rvw = {k: v for k, v in rvw.items() if v is not None}
need(isinstance(rvw, dict) and set(rvw) <= {"keep_author", "scrub", "trailer_policy", "reject_trailers"}, "review: an object like {keep_author: false, scrub: \"scripts/scrub\", trailer_policy: \"none\", reject_trailers: [\"Signed-off-by\"]} (unknown key: only keep_author, scrub, trailer_policy, reject_trailers)")
if isinstance(rvw, dict):
    need(isinstance(rvw.get("keep_author", False), bool), "review.keep_author: true (qargi review apply keeps the member's author on the applied commits) or false (default: the author is reset to git.author)")
    if "scrub" in rvw:
        sc = rvw["scrub"]
        ctl = lambda t: any(ord(ch) < 32 or ord(ch) == 127 for ch in t)
        need((isinstance(sc, str) and sc.strip() and not ctl(sc)) or (isinstance(sc, list) and sc and all(isinstance(x, str) and x and "\x00" not in x for x in sc)),
             "review.scrub: the command qargi review check runs on the applied series, one command line or a list of words (for example [\"scripts/scrub\"]); it gets the range in QARGI_SCRUB_BASE and QARGI_SCRUB_TIP")
    need(rvw.get("trailer_policy", "none") in ("none", "reject"), "review.trailer_policy: none (default) or reject (a commit with a Co-Authored-By or Generated-with trailer fails qargi review check)")
    # review.reject_trailers: trailer keys added to the built-in two under the policy reject (letters, digits, hyphens; * stands for any run of them)
    if "reject_trailers" in rvw:
        rt = rvw["reject_trailers"]
        keys_ok = isinstance(rt, list) and rt and all(isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9*-]+", x) and re.search(r"[A-Za-z0-9]", x) for x in rt)
        need(keys_ok and len({x.lower() for x in rt}) == len(rt),
             "review.reject_trailers: a list of distinct trailer keys to refuse besides Co-Authored-By and Generated-with, each of letters, digits and hyphens where * stands for any run of them (for example [\"Signed-off-by\", \"Change-Id\", \"X-*\"])")
        need(rvw.get("trailer_policy", "none") == "reject", "review.reject_trailers: it adds to the built-in two under review.trailer_policy reject, which is not set (qargi project set PROJECT review.trailer_policy reject first)")
# gates: the declared gates (optional), an ordered list of {name, command, tier}: feature verify runs the feature tier, release verify the feature
# tier then the release tier, and the CI jobs of a release are compared with the names (lib/gates.py)
import gates as _gates
bad.extend(_gates.problems(c.get("gates")))
# ci.not_gates: the CI jobs that are aggregate or publish jobs and not gates (optional; the scan of release verify leaves them out); gates[].ci_jobs: the jobs that run a gate's check under another name
bad.extend(_gates.ci_problems(c.get("ci")))
# backlog.file: the markdown file of the project's backlog (optional; qargi backlog): a path, ~/... or relative to the repository; it may be outside it
bkl = c.get("backlog", {})
if isinstance(bkl, dict): bkl = {k: v for k, v in bkl.items() if v is not None}
# backlog.archive: where the archived items go (a directory, or a path ending in .md for one archive file; default: beside the file);
# backlog.section: a heading of the file: only the list under it holds items
need(isinstance(bkl, dict) and set(bkl) <= {"file", "archive", "section"}, "backlog: an object like {file: \"/path/backlog.md\", archive: \"/path/archive\", section: \"Now\"} (unknown key: only file, archive, section)")
if isinstance(bkl, dict) and "file" in bkl:
    bf = bkl["file"]
    need(isinstance(bf, str) and bf.strip() and not any(ord(ch) < 32 or ord(ch) == 127 for ch in bf),
         "backlog.file: the path of a markdown file of items written '- [some-id] text', an absolute path, ~/... or a path relative to the repository; no control characters")
if isinstance(bkl, dict):
    noctl = lambda t: not any(ord(ch) < 32 or ord(ch) == 127 for ch in t)
    if "archive" in bkl:
        ba = bkl["archive"]
        need(isinstance(ba, str) and ba.strip() and noctl(ba),
             "backlog.archive: the directory the archived items go to (files NAME-archive-YYYY-MM.md), or a path ending in .md for one archive file; an absolute path, ~/... or a path relative to the repository; no control characters")
    if "section" in bkl:
        bs = bkl["section"]
        need(isinstance(bs, str) and re.sub(r"^#{1,6}(?:[ \t]+|$)", "", bs.strip()).strip() and noctl(bs),
             "backlog.section: the text of a heading of the backlog file (with or without its #s): only the list under it holds items; no control characters")
# methodology_accepted: the lead's accepted deviations from the methodology (optional), a list of {gap, reason, date}: gap is "KIND: WHAT" as `qargi project
# attach` prints a gap (file: CONTRIBUTING.md, branch: develop, env: doctor target), reason says why it is accepted, date is YYYY-MM-DD. attach, adopt and
# marshal handoff print them apart from the open gaps; adopt leaves an accepted file or branch out of what it writes. The lead sets it; a member may not
ma = c.get("methodology_accepted", [])
def _line(v, n):
    return isinstance(v, str) and v.strip() and len(v) <= n and all(ch.isprintable() for ch in v)
need(isinstance(ma, list) and len(ma) <= 100 and all(
        isinstance(x, dict) and set(x) == {"gap", "reason", "date"} and _line(x["gap"], 300) and re.fullmatch(r"[a-z]+: \S.*", x["gap"])
        and _line(x["reason"], 500) and isinstance(x["date"], str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", x["date"]) for x in ma)
     and (not isinstance(ma, list) or len({x["gap"] for x in ma if isinstance(x, dict)}) == len([x for x in ma if isinstance(x, dict)])),
     "methodology_accepted: a list of at most 100 distinct {gap, reason, date}: gap as attach prints it (\"file: CONTRIBUTING.md\", \"branch: develop\"), reason one line, date YYYY-MM-DD")
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
try: _own_local = provider.resolve_project(c, "local")[0]
except provider.ProviderError: _own_local = None
_extra_local = provider.extra_runtimes_of(c)
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
            if k not in ("base", "tier", "model", "effort", "purpose", "abilities", "runtime", "options"):
                bad.append("%s.%s: unknown key (base, tier, model, effort, purpose, abilities, runtime, options)" % (p, k))
        bases = md["bases"]
        b = pf.get("base")
        if b is None and pn in md["profiles"]: b = md["profiles"][pn].get("base")
        if "base" not in pf and pn not in md["profiles"]:
            bad.append("%s.base: required for a profile of your own (%s)" % (p, ", ".join(bases)))
        elif "base" in pf and pf["base"] not in bases:
            bad.append("%s.base: one of %s" % (p, ", ".join(bases))); b = None
        # a profile's tier, model and effort are checked against the runtime the profile runs on: its own `runtime` (the project's own or an enabled
        # extra one), else the project's providers as before
        p_ok, p_aliases, p_like, p_tiers, p_effort = model_ok, aliases, like, tiers_ok, None
        if "runtime" in pf:
            rt = pf["runtime"]
            enabled = ([_own_local] if _own_local else []) + [x for x in _extra_local if isinstance(x, str)]
            if not (isinstance(rt, str) and provider.NAME_RE.match(rt)):
                bad.append("%s.runtime: a runtime name, the project's own or one enabled for it" % p)
            elif rt not in enabled:
                bad.append("%s.runtime: %s is not enabled for this project (qargi provider enable PROJECT --runtime %s)" % (p, rt, rt))
            else:
                _d = _runtime(rt, "local")
                if _d:
                    _rx = re.compile(_d["model_pattern"])
                    p_ok, p_aliases, p_tiers, p_effort = _rx, [a for a in _d["aliases"].values() if a], list(_d["tiers"]), _d["effort"]
                    p_like = lambda tier, _d=_d: "a model id like %s" % _d["tiers"][tier]
        if "tier" in pf: need(pf["tier"] in p_tiers, "%s.tier: one of %s" % (p, ", ".join(p_tiers)))
        if "model" in pf: need(isinstance(pf["model"], str) and (pf["model"] in p_aliases or p_ok.fullmatch(pf["model"])), "%s.model: %s" % (p, (", ".join(p_aliases) + " or " if p_aliases else "") + p_like("balanced")))
        if "effort" in pf:
            need(pf["effort"] in efforts, "%s.effort: %s" % (p, "|".join(sorted(efforts))))
            if p_effort is not None and pf["effort"] in efforts and p_effort.get(pf["effort"]) is None:
                bad.append("%s.effort: %s is not an effort level of the runtime %s" % (p, pf["effort"], pf["runtime"]))
        if "purpose" in pf: need(isinstance(pf["purpose"], str) and len(pf["purpose"]) <= 300, "%s.purpose: a string of at most 300 characters" % p)
        # a profile selects among the options the project enabled for the runtime the profile runs on (models.run_options.local.RUNTIME, set by qargi provider
        # enable PROJECT --runtime NAME --option OPT): a plain list, never a way to enable one. A profile of the reviewer base is a read-only run, which never gets one
        if "options" in pf:
            ol = pf["options"]
            rt_o = pf["runtime"] if isinstance(pf.get("runtime"), str) else _own_local
            if not (isinstance(ol, list) and all(isinstance(x, str) and provider.OPTION_NAME.match(x) for x in ol) and len(set(ol)) == len(ol)):
                bad.append("%s.options: a list of distinct option names the project enabled for the runtime of the profile (qargi provider enable PROJECT --runtime NAME --option OPT)" % p)
            elif ol:
                if b and md["bases"].get(b, {}).get("class") == "read-only":
                    bad.append("%s.options: the profile is on the base %s, a read-only run, which never gets a run option" % (p, b))
                for x in ol:
                    if x not in _ro_local.get(rt_o, []):
                        bad.append("%s.options: %s is not enabled for the runtime %s of this project (qargi provider enable PROJECT --runtime %s --option %s)" % (p, x, rt_o or "of the project", rt_o or "NAME", x))
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
    need(isinstance(pk_, dict) and set(pk_) <= {"none", "member_skills"}
         and all(type(v) is bool for v in pk_.values()),
         "packs: an object of booleans none and member_skills (default off; member_skills uses qargi packs member-skills)")
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
# verify.environment: the declaration a whole-suite run is started under (optional; null or absent: off). The launcher judges it (lib/suite_env.py
# problems), so there is one list of what is valid; a line starts with the refusal code
vf = c.get("verify")
if vf is not None:
    if not isinstance(vf, dict):
        bad.append("verify-env-invalid: verify: an object like {environment: {...}} (the only answer in it is environment)")
    else:
        for k in vf:
            if k != "environment": bad.append("verify-env-invalid: verify.%s: unknown key (the only answer in verify is environment)" % k)
        if "environment" in vf:
            import suite_env   # lib/suite_env.py: the launcher and its declaration
            bad.extend("verify-env-invalid: verify.environment: %s" % p for p in suite_env.problems(vf["environment"]))
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

# reads_warn RUNTIME [INDENT]: when the local runtime RUNTIME (a runtime or a family name) is a command runtime whose definition does not confine reads
# (dispatch.reads), prints the warning of the enable plan as a `warning:` line: members on it can read what the account can read, the owner's own
# sessions among it. Prints nothing for a runtime that confines reads, works in the session or is unknown. The places that make a runtime the project's
# own (new, attach, set) print it and ask for no phrase; validate and every other verb stay silent about it
reads_warn() {
  local w
  w=$(pymod provider reads-warning "$1" </dev/null 2>/dev/null) || return 0
  [ -z "$w" ] || echo "${2:-}warning: $w"
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
# the extra runtimes the project lists (models.extra_runtimes.local) that can no longer be used as they stand: unknown, not sealed or changed since,
# not of the local surface, not started by a command (the shape of the answer is validate's)
_extras = P.extra_runtimes_of(ans)
if _extras:
    try: _own = P.resolve_project(ans, "local", name)[0]
    except P.ProviderError: _own = None
    for x in _extras:
        try: why = P.runtime_problem(x, _own)
        except P.ProviderError as e: out.append("finding: models.extra_runtimes.local '%s' cannot be used: %s" % (x, e)); continue
        if why != "ok" and why != "is-primary": out.append("finding: models.extra_runtimes.local '%s' cannot be used: %s (qargi provider check %s)" % (x, why, x))
# the run options the project enabled (models.run_options.local) that the definition of the runtime no longer declares: an option that is not declared does not exist
for _rt, _ol in P.run_options_of(ans).items():
    try: _declared = P.declared_options(P.definition(_rt, "local"))
    except P.ProviderError: continue                                   # a runtime that cannot be read is the finding of the extra runtimes above
    for _o in _ol:
        if _o not in _declared: out.append("finding: models.run_options.local.%s '%s' is not an option the definition of %s declares (dispatch.run_config.options; qargi provider show %s)" % (_rt, _o, _rt, _rt))
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
    # a file may keep or drop what is stored (that only narrows trust); it may not add or change an entry: a list is narrower when it is a subset (as a set, the
    # order and repeats do not count), an object when each of its keys is stored and its value is the stored one or narrower (a list of an object of lists too:
    # models.extra_runtimes.local, models.run_options.local.RUNTIME), as lib/transfer.py _gated_narrower reads an archive
    def sub($x; $y): (($x - $y) | length) == 0;
    def nar($x; $y):
      if $x == $y then true
      elif ($x | type) == "array" then ($y | type) == "array" and sub($x; $y)
      elif ($x | type) == "object" then ($y | type) == "object" and ($x | to_entries | all(. as $e | ($y | has($e.key)) and nar($e.value; $y[$e.key])))
      else false end;
    def narrower($a; $b; $k): ($a[$k] | norm) as $x | ($b[$k] | norm) as $y
      | if $x == null then true elif $y == null then false else nar($x; $y) end;
    ($n[0] | keys_of) as $a | ($s[0] | keys_of) as $b
    | (["extensions", "extra_runtimes", "run_options", "accept_no_barrier"][] | . as $k | select(narrower($a; $b; $k) | not) | "models." + $k),
      (select(($n[0].packs | type) == "object" and ($n[0].packs | has("member_skills")))
       | select(($n[0].packs.member_skills // false) != ($s[0].packs.member_skills // false)) | "packs.member_skills")'
}
gated_refuse() { # NEWFILE [STOREDFILE]: says so and returns 1 when the file would add or change a gated key
  local bad; bad=$(gated_keys_changed "$@" | paste -sd, | sed 's/,/, /g')
  [ -z "$bad" ] || { echo "qargi: the answers would add or change $bad, which no project verb stores: they change what an agent may run on or accept a surface with no read-only barrier, so they take a plan token and an approval (qargi provider enable PROJECT EXTENSION, qargi provider enable PROJECT --runtime NAME, and for a run option of a runtime qargi provider enable PROJECT --runtime NAME --option OPT; qargi provider accept NAME --surface S --no-barrier); leave them as they are stored, or out of the file; nothing stored" >&2; return 1; }
}

# verify.environment (the declaration a whole-suite run is started under, lib/suite_env.py) is changed by the routes that write the answers, and
# the declaration qargi last accepted is kept apart from the answers, in the state (suite_env.py approved: STATE/verify-env.json), so that an edit
# of the answers file cannot turn it off. The launcher judges everything about the declaration (problems, normalise, hash, id, loosens, approved);
# the functions here only call it and decide what to print. A refusal exits 1 and names its code (verify-env-invalid is validate's).
SUITE_ENV_PY=$(dirname "$(readlink -f "$0")")/suite_env.py
venv_py() { python3 -I "$SUITE_ENV_PY" "$@"; }
venv_decl() { # ANSWERS_FILE -> the declaration it holds as JSON text; null when it has none (the setting is off)
  jq -c 'if (.verify | type) == "object" and (.verify | has("environment")) then .verify.environment else null end' "$1"
}
venv_load() { # NAME -> VENV_OLD, the approved declaration (JSON text; null for off or no entry).
  # Decided from what the launcher printed, never from the exit status alone: "no entry" is status 1 and prints nothing, so a traceback (also status 1)
  # is not "no entry". Fails (the message is on stderr) when the state cannot be read: a damaged file is never taken for "no entry", so never for a first declaration
  local out rc=0
  out=$(venv_py approved get "$1" --state "$DA_STATE" 2>&1) || rc=$?
  case $rc in
    0) VENV_OLD=$(jq -c 'if type == "object" and has("declared") then .declared else error("no declared") end' <<<"$out") \
         || { echo "qargi: the approved entry of $1 cannot be read; nothing changed" >&2; return 1; };;
    1) if [ -n "$out" ]; then printf '%s\n' "$out" >&2; return 1; fi; VENV_OLD=null;;
    *) printf '%s\n' "$out" >&2; return 1;;
  esac
}
# verify_env_lock: one lock for the whole of a change of verify.environment (read the approved entry, compare, store the answers, write the entry), held until
# the verb ends, so two changes cannot interleave and a loosening is never judged against an entry that another change replaces meanwhile. It is not the
# launcher's lock (approved set takes that one inside the entry write, and a flock taken here on the same file would block it): a second file beside it
verify_env_lock() {
  command -v flock >/dev/null 2>&1 || die "could not take the lock for verify.environment: the flock command (util-linux) is not installed, so two changes could not be kept apart; nothing was changed"
  local f=$DA_STATE/verify-env.gate.lock
  { mkdir -p "$DA_STATE" && ( umask 077; : >> "$f" ) && exec {VENV_LK}>>"$f" && flock "$VENV_LK"; } \
    || die "could not take the lock for verify.environment: flock on $f failed; nothing was changed"
}
# verify_env_refuse NEWFILE NAME: the check of the routes that store a whole answers file (init, new, attach, beside gated_refuse): the file's
# declaration must be the approved one, or nothing is stored. With no entry in the state, a file that declares one is a first declaration (plain):
# VENV_FIRST holds it, and verify_env_commit writes the entry once the file is stored
verify_env_refuse() {
  local nd res rc=0 a s sd
  VENV_FIRST=''
  nd=$(venv_decl "$1") || { echo "qargi: cannot read $1; nothing stored" >&2; return 1; }
  # a file that declares verify.environment is compared with the approved entry and then stored, and the entry written, under the lock of project set (held to the
  # end of the verb), so a set and an init cannot interleave; a file that declares nothing takes no lock, as it changes no entry
  [ "$nd" = null ] || verify_env_lock
  res=$(venv_py approved check "$2" "$nd" --state "$DA_STATE") || rc=$?
  case $rc in
    0) return 0;;
    # a state file that cannot be read (the launcher said so on stderr) stops a file that declares verify.environment, which cannot be compared; a file
    # that declares nothing proceeds, unless the answers stored now declare it: the setting would go off with nothing to vouch for what was approved
    3) if [ "$nd" = null ]; then
         sd=null; [ ! -f "$PROJ_DIR/$2.json" ] || sd=$(venv_decl "$PROJ_DIR/$2.json" 2>/dev/null) || sd=null
         [ "$sd" = null ] && return 0
         echo "qargi: verify.environment could not be compared with the approved declaration (the state file cannot be read), and the answers stored for $2 declare it while this file declares none: that would turn it off; nothing stored" >&2; return 1
       fi
       echo "qargi: verify.environment could not be compared with the approved declaration (the state file cannot be read); nothing stored" >&2; return 1;;
    1) jq -e 'type == "object" and has("entry") and has("answers") and has("state")' <<<"$res" >/dev/null 2>&1 \
         || { echo "qargi: verify.environment could not be compared with the approved declaration; nothing stored" >&2; return 1; };;
    *) echo "qargi: verify.environment could not be compared with the approved declaration; nothing stored" >&2; return 1;;
  esac
  if [ "$(jq -r .entry <<<"$res")" = false ]; then VENV_FIRST=$nd; return 0; fi
  venv_load "$2" || { echo "qargi: nothing stored" >&2; return 1; }
  a=$(jq -r .answers <<<"$res"); s=$(jq -r .state <<<"$res")
  echo "qargi: verify-env-change-unapproved: the answers would change verify.environment from the approved declaration ($s) to another ($a); the approved one is $VENV_OLD; leave verify.environment as stored, or change it with: qargi project set $2 verify.environment JSON (a loosening takes a plan token and the owner's words); nothing stored" >&2
  return 1
}
verify_env_commit() { # NAME VERB: after the file is stored, writes the entry of a first declaration that verify_env_refuse found
  [ -n "${VENV_FIRST:-}" ] && [ "$VENV_FIRST" != null ] || return 0
  venv_py approved set "$1" "$VENV_FIRST" --by "$2" --state "$DA_STATE" >/dev/null \
    || die "$1: the answers are stored, but the approved declaration could not be recorded; record it with: qargi project set $1 verify.environment JSON"
}
# verify_env_gate NAME PATH NEWFILE: for project set|unset of verify, verify.environment or a key below it, after validate. The comparison is of the
# whole declaration, the approved one (the state, never the answers file) against the one NEWFILE holds. Tightening (nothing approved before;
# cpu_quota stricter) is plain; everything else loosens, and is refused with a token unless --plan names it ($PLAN_ARG) and the owner's words are
# given ($APPROVED). Returns 1 after printing the refusal. Sets VENV_NEW, VENV_WRITE (the state must be written: the declaration differs from
# the approved one) and VENV_LOOSE (what the audit line says; empty for a plain change)
verify_env_gate() {
  local why rc=0 oid nid tok
  VENV_NEW=$(venv_decl "$3"); VENV_WRITE=0; VENV_LOOSE=''
  venv_load "$1" || { echo "qargi: verify.environment cannot be changed while the approved declarations cannot be read; nothing changed" >&2; return 1; }
  venv_py approved check "$1" "$VENV_NEW" --state "$DA_STATE" 2>/dev/null | jq -e '.equal == true' >/dev/null 2>&1 || VENV_WRITE=1   # written unless the launcher said they are equal
  why=$(venv_py loosens "$VENV_OLD" "$VENV_NEW") || rc=$?
  # the answer is what the launcher printed (its first line) with its status: a failure that also exits 1 prints no "plain", so it is no answer
  case $rc:$(head -n1 <<<"$why") in 0:loosens|1:plain) ;; *) rc=2;; esac
  case $rc in
    1) return 0;;
    0) ;;
    *) echo "qargi: verify.environment could not be compared with the approved declaration; nothing changed" >&2; return 1;;
  esac
  oid=$(venv_py id "$VENV_OLD"); nid=$(venv_py id "$VENV_NEW")
  tok=$(printf '%s\n%s\n%s\n' "$1" "$oid" "$nid" | plan_token --basis "project:name old-declaration:sha new-declaration:sha" --verb "project $verb" --target "$1:$2")
  why=$(sed 1d <<<"$why" | paste -sd, | sed 's/,/, /g')
  if [ -n "$APPROVED" ] && [ -n "$tok" ] && [ "${PLAN_ARG:-}" = "$tok" ]; then   # an empty token is no plan: it never equals an empty --plan
    VENV_LOOSE="${oid:-off} -> ${nid:-off}: $why"
    return 0
  fi
  echo "qargi: verify-env-change-unapproved: $2 would loosen the approved verify.environment ($why); it takes a plan token and the owner's words" >&2
  if [ -n "$PLAN_ARG$APPROVED" ]; then echo "qargi: the plan token or the approval given does not cover this change (both --plan and --approved are needed, and the token is for this declaration)" >&2; fi
  echo "plan token: $tok   (apply with: qargi project $verb $1 $2$([ "$verb" = set ] && echo ' VALUE') --plan $tok --approved \"<the owner's words>\"); nothing changed" >&2
  return 1
}
verify_env_record() { # NAME PATH VERB: after the answers are stored, the approved declaration follows them, and a loosening is audited with the owner's words
  [ "$VENV_WRITE" = 0 ] || venv_py approved set "$1" "$VENV_NEW" --by "$3" --state "$DA_STATE" >/dev/null \
    || die "$1: the answers are stored, but the approved declaration could not be recorded; the next verify refuses until it is: qargi project set $1 verify.environment JSON"
  [ -z "$VENV_LOOSE" ] || audit_log "project:verify-environment-loosened" "$1 $2 ($VENV_LOOSE)"
}

case $verb in
  template)
    n=${1:-}; valid_project "$n" || usage_die "template needs a project name (lower-case letters and digits)"
    shift
    meth=''
    while [ $# -gt 0 ]; do
      case $1 in --methodology) need_val "$1" $#; meth=$2; shift 2;; *) usage_die "unknown option $1 (usage: qargi project template NAME [--methodology M])";; esac
    done
    # the long-lived branches and the role bases come from the methodology; the one that ships as the default (gitflow) adds no answer, as before
    mover='{}'
    if [ -n "$meth" ] && [ "$meth" != gitflow ]; then
      mover=$(python3 -I - "$(dirname "$(readlink -f "$0")")" "$meth" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1]); import methodology as M
bad = M.problems(sys.argv[2])
if bad:
    sys.stderr.write("qargi: the methodology %s does not pass qargi methodology check: %s\n" % (sys.argv[2], "; ".join(bad)))
    sys.exit(1)
m = M.load(sys.argv[2])[2]
print(json.dumps({"methodology": sys.argv[2], "long_lived": m["branches"]["long_lived"],
                  "bases": {r: c["base"] for r, c in (m.get("roles") or {}).items() if isinstance(c, dict) and isinstance(c.get("base"), str)}}))
PY
      ) || exit 1
    fi
    # no model and no provider: the template names no vendor. A role's model is its provider's tier (project set models.provider.local NAME)
    # until you give one; the efforts are the table's, the same for every provider
    jq -n --arg n "$n" --argjson mo "$mover" --slurpfile d "$(dirname "$(readlink -f "$0")")/model-defaults.json" \
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
      budget_cents: 500}
    | if ($mo | has("methodology")) then
        .methodology = $mo.methodology | .repo.long_lived = $mo.long_lived
        | reduce ($mo.bases | to_entries[]) as $b (.; if .roles[$b.key] then .roles[$b.key].base = $b.value else . end)
      else . end';;
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
    verify_env_refuse "$ans" "$n" || exit 1
    jq . "$ans" > "$PROJ_DIR/$n.json.tmp" && chmod 600 "$PROJ_DIR/$n.json.tmp" && mv "$PROJ_DIR/$n.json.tmp" "$PROJ_DIR/$n.json"
    verify_env_commit "$n" init
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
print(M.flow(sys.argv[2]))
PY
    ) || exit 1
    flow=${long#*$'\n'}; long=${long%%$'\n'*}
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$dir" "$meth" "$url" "$dep" "$prov" "$provl" "$provc" "$(jq -S -c . <<<"$files")" \
          | plan_token --basis "directory:path methodology:name url:name deployment:name provider:name provider-local:name provider-cloud:name files:name" --verb "project new" --target "$n:$(printf '%s' "${dir//[[:cntrl:]]/?}" | cut -c1-200)")
    echo "new project $n with the $meth methodology at $dir"
    echo "  git repository with the branches: $long (the first is the initial one; work starts on the last)"
    echo "  files:"; jq -r '.[].dest | "    " + .' <<<"$files"
    if [ -n "$url" ]; then echo "  qargi answers stored for $url (outside the repository)"; else echo "  no --url: the answers are stored later, when the remote exists: qargi project attach $dir --url URL"; fi
    echo "  deployment: ${dep:-not chosen (see below)}"
    echo "  provider: $ptxt"
    reads_warn "${provl:-$prov}" "  "
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
      det=$(python3 -I "$lib/attach.py" detect "$dir" --name "$n" --methodology "$meth" "${PROVARGS[@]}") || exit 1
      # the gates given as --param gates=JSON are in the files just written, so they are stored too (the last --param gates= wins, as in the render,
      # which has refused a value that is not valid; validate below checks the stored list the way project set does); none when empty or []
      gv=''; for p in "${PARAMS[@]}"; do case $p in gates=*) gv=${p#gates=};; esac; done
      f=$(mktemp); jq --arg u "$url" --arg d "$dep" --arg g "$gv" '.answers | .repo.url = $u | if $d == "" then . else .deployment = $d end | (($g | fromjson?) // []) as $gs | if ($gs | length) > 0 then .gates = $gs else . end' <<<"$det" > "$f"
      out=$(validate "$f") || { echo "$out" >&2; rm -f "$f"; die "the project was created but its answers are not valid; nothing stored (qargi project attach $dir --url URL)"; }
      gated_refuse "$f" || { rm -f "$f"; exit 1; }
      verify_env_refuse "$f" "$n" || { rm -f "$f"; exit 1; }
      mkdir -p "$PROJ_DIR"; chmod 700 "$PROJ_DIR"; mv "$f" "$PROJ_DIR/$n.json"; chmod 600 "$PROJ_DIR/$n.json"
      verify_env_commit "$n" new
      echo "project $n stored in $PROJ_DIR/$n.json"
      no_provider "$PROJ_DIR/$n.json" || true
    fi
    if [ -n "$dep" ]; then echo; python3 -I "$lib/methodology.py" deployment "$meth" "$dep"; fi
    echo; echo "next: create the repository on your host and push (git remote add origin URL; git push -u origin ${long// / })"
    [ "$flow" = plain ] || echo "      a first release: qargi release start $(jq -r '.[] | select(.dest == "VERSION") | .content' <<<"$files" | tr -d '\n') (not built yet)";;
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
    n=$(jq -r .answers.project <<<"$det")
    valid_project "$n" || die "the project name '$n' is not valid: --name (lower-case letters and digits)"
    sf=$PROJ_DIR/$n.json; stored=''
    [ ! -f "$sf" ] || stored=1
    # a stored project is read with its answers: the commands it declares (env.*) and its changelog headings are what the gaps are measured against
    [ -z "$stored" ] || det=$(python3 -I "$(dirname "$0")/attach.py" detect "$dir" --name "$n" --methodology "$meth" "${PROVARGS[@]}" --answers "$sf") || exit 1
    [ -z "$url" ] || det=$(jq --arg u "$url" '.answers.repo.url = $u | .questions |= map(select(startswith("repo.url") | not))' <<<"$det")
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
    accepted_lines "$det" "  " ""
    if [ "$(jq -r '.info | length' <<<"$det")" != 0 ]; then
      echo "noted, not gaps (nothing to close):"
      jq -r '.info[] | "  - \(.kind): \(.what) (\(.why))"' <<<"$det"
    fi
    jq -r '.found.env | "development environment found: section in \(.section // "none"); task runner \(.runner // "none"); bootstrap \(.bootstrap_command // "none"); doctor \(.doctor_command // "none"); \(.pins | length) pinned tool(s), \(.submodules) submodule(s) (qargi env show reads it in full)"' <<<"$det"
    # a hint only: the repository's own skills are read from the working tree, nothing is changed or stored. The directory is the project's
    # provider's (layout.project_skills_dir); a project with no provider yet (attach never guesses one) is hinted for every provider's.
    pv='';[ -z "$stored" ] || pv=$(pymod provider of "$n" --conf "$DA_CONF" --surface local 2>/dev/null </dev/null) || pv=''
    while IFS= read -r sd; do
      [ -n "$sd" ] || continue
      rs=$(jq -r .found.path <<<"$det")/$sd
      if [ -d "$rs" ] && [ ! -L "$rs" ]; then
        ns=$(find "$rs" -mindepth 2 -maxdepth 2 -name SKILL.md -type f | wc -l)
        if [ "$ns" -gt 0 ]; then echo "repo has its own $sd ($ns skill$([ "$ns" -eq 1 ] || echo s)): qargi packs link $n offers to use the library's instead and shows which are new"; fi
      fi
    done < <(pymod provider skills-dirs $pv 2>/dev/null </dev/null)
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
      reads_warn "$(jq -r '(.models.provider // "") | if type == "string" then . elif type == "object" then (.local // "") else "" end' <<<"$ans")"
      no_provider /dev/stdin "$n" <<<"$ans" || true   # attach does not guess a provider and stores none
      echo "plan token: $tok   (store with: qargi project attach $dir --plan $tok --approved \"...\"${force:+ --force})"
      exit 0
    fi
    need_plan "$tok"
    f=$(mktemp); jq . <<<"$ans" > "$f"
    out=$(validate "$f") || { echo "$out" >&2; rm -f "$f"; die "the answers are not valid; nothing stored"; }
    gated_refuse "$f" "$sf" || { rm -f "$f"; exit 1; }
    verify_env_refuse "$f" "$n" || { rm -f "$f"; exit 1; }
    mkdir -p "$PROJ_DIR"; chmod 700 "$PROJ_DIR"
    mv "$f" "$sf"; chmod 600 "$sf"
    verify_env_commit "$n" attach
    audit_log "project:attach" "$n"
    echo "project $n stored in $sf (approved: $APPROVED)"
    no_provider "$sf" || true;;
  adopt)
    # an attached repository: create what the methodology has and the repository lacks, only where nothing exists yet; the plan first
    n=${1:-}; shift || true; valid_project "$n" || usage_die "adopt needs the name of an attached project (qargi project list)"
    meth='' PLAN_ARG='' APPROVED='' show=''
    while [ $# -gt 0 ]; do
      case $1 in --show) show=1; shift;; --methodology) need_val "$1" $#; meth=${2:-}; shift 2;; --plan) need_val "$1" $#; PLAN_ARG=${2:-}; shift 2;; --approved) need_val "$1" $#; APPROVED=${2:-}; shift 2;; *) usage_die "unknown option $1";; esac
    done
    export PLAN_ARG   # need_plan reads it
    [ -z "$show" ] || [ -z "$APPROVED$PLAN_ARG" ] || usage_die "adopt --show only prints the plan (it takes neither --plan nor --approved)"
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
      accepted_lines "$plan" "    " "  "
    }
    if [ "$(jq -r '.instructions | length' <<<"$plan")" != 0 ]; then
      echo "  the repository's own instructions (adopt edits no existing file):"
      jq -r '.instructions[] | "    - \(.file): \(.text)"' <<<"$plan"
    fi
    if [ "$(jq -r '.info | length' <<<"$plan")" != 0 ]; then
      echo "  noted, not gaps (nothing to close):"
      jq -r '.info[] | "    - \(.kind): \(.what) (\(.why))"' <<<"$plan"
    fi
    left
    if [ "$(jq -r .nothing_to_do <<<"$plan")" = true ]; then echo; echo "nothing to do: the safe gaps are closed"; exit 0; fi
    if [ -n "$show" ]; then
      # the token is the hash of the plan's basis (the refs it starts from, the branches to create, and the hash of each file to write): print
      # that basis and the content each hash stands for, so what the token covers can be read before it is given
      echo
      echo "covered by the plan token (a hash of this basis; a file is covered by the sha256 of the content shown below it):"
      jq -S .basis <<<"$plan" | sed 's/^/  /'
      while IFS= read -r dest; do
        echo; echo "file $dest:"
        jq -j --arg d "$dest" '.files[] | select(.dest == $d) | .content' <<<"$plan" | sed 's/^/  | /'
      done < <(jq -r '.files[].dest' <<<"$plan")
    fi
    echo
    if [ -z "$APPROVED" ]; then
      echo "plan token: $tok   (create with: qargi project adopt $n --plan $tok --approved \"...\"${meth:+ --methodology $meth})"
      exit 0
    fi
    need_plan "$tok"
    res=$(python3 -I "$lib/attach.py" adopt-apply "$n" "$PROJ_DIR/$n.json" <<<"$plan") || exit $?
    audit_log "project:adopt" "$n"
    jq -r '.branches[] | "created branch " + .' <<<"$res"
    c=$(jq -r .commit <<<"$res")
    [ -z "$c" ] || jq -r --arg c "$c" '"created branch \(.adopt_branch) at \($c[0:7]): " + (.files | map(.dest) | join(", "))' <<<"$plan"
    left
    echo "approved: $APPROVED; nothing was pushed. Review the branch, merge it into $(jq -r .integration.name <<<"$plan") when it suits you.";;
  set)
    n=${1:-}; path=${2:-}; val=${3:-}; PLAN_ARG='' APPROVED=''
    [ -f "$PROJ_DIR/$n.json" ] || die "no project named '$n' (see: project list)"
    [ -n "$path" ] && [ -n "$val" ] || usage_die "set needs NAME PATH VALUE (for example: set $n budget_cents 2500)"
    # --plan and --approved: the token and the owner's words for a change of verify.environment that loosens it (below); no other answer takes them
    shift 3
    while [ $# -gt 0 ]; do
      case $1 in --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;; *) usage_die "unknown option $1";; esac
    done
    case $path in verify|verify.*) ;; *) [ -z "$PLAN_ARG$APPROVED" ] || usage_die "--plan and --approved apply only to verify.environment (a loosening of it takes a plan token and the owner's words); $path takes neither";; esac
    printf '%s' "$path" | grep -Eq '^[a-z_][a-z0-9_.-]*$' || die "PATH: dotted keys such as roles.write.effort"
    # the shared marshal backend is a machine switch with a plan and an audit line, never an answer of the project file
    case $path in marshal.lease_minutes) ;; marshal|marshal.*) die "$path is not a project answer: only marshal.lease_minutes is; to switch the shared backend use 'qargi marshal enable' or 'qargi marshal disable'";; esac
    jq empty >/dev/null 2>&1 <<<"$val" || val=$(jq -Rn --arg v "$val" '$v')
    # the accepted deviations are the lead's decision (they take a gap out of the open ones): a member run may not record them
    case $path in methodology_accepted|methodology_accepted.*)
      if [ -n "${QARGI_MEMBER_RUN:-}" ] || python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import marshal_refs; sys.exit(0 if marshal_refs.in_member_run() else 1)' "$(dirname "$(readlink -f "$0")")"; then
        echo "qargi: $path records a deviation from the methodology that the lead accepts, and is not set in a member run: propose the entry (gap, reason, date) in your report" >&2; exit 2
      fi;; esac
    # verify.environment is how the lead's whole-suite runs are started, and a loosening of it takes the owner's words: a member run never changes it (the
    # plan token is printed to whoever asks, so the words are the only barrier, and an agent's words are no one's approval). As unset: the check answers
    # 0 (a member run) or 3 (not one); any other status is a failure to tell, and an unknown caller is refused (fail closed)
    case $path in verify|verify.*)
      mrc=0; python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import marshal_refs; sys.exit(0 if marshal_refs.in_member_run() else 3)' "$(dirname "$(readlink -f "$0")")" || mrc=$?
      case $mrc in
        3) ;;
        0) echo "qargi: project set of $path is not available in a member run: it changes how the lead's whole-suite runs are started; propose the declaration in your report" >&2; exit 2;;
        *) echo "qargi: project set of $path could not tell whether this is a member run (the check failed with status $mrc); refused: it changes how the lead's whole-suite runs are started" >&2; exit 2;;
      esac
      verify_env_lock;; esac
    # the answers that decide what an agent may run on (extensions) and which surface may go without a read-only barrier (accept_no_barrier) are
    # changed with a plan token and an approval, by their own verbs; this verb has neither, so it refuses them (also as keys of a whole models
    # object), for every caller and always. Those verbs store them through lib/gated_answers.py, which this verb never calls and nothing a
    # caller sets (an environment variable, an option) can reach from here
    gated=$(gated_path "$path" "$val") || gated=''
    if [ -z "$gated" ] && [ "$path" = packs ]; then
      gated=$(gated_path "$path" "$(answer_was "$PROJ_DIR/$n.json" packs)") || gated=''
    fi
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
    was=$(answer_was "$PROJ_DIR/$n.json" "$path")
    tmp=$(mktemp "$PROJ_DIR/.set.XXXXXX")
    jq --argjson v "$val" --arg p "$path" --arg carry "$carry" '
      (if ($p | startswith("models.provider.")) and ((try .models.provider catch null) | type) == "string"
       then .models.provider = (if $carry == "" then {} else {local: $carry, cloud: $carry} end) else . end)
      | setpath($p | split("."); $v)' "$PROJ_DIR/$n.json" > "$tmp"
    out=$(validate "$tmp") || { echo "$out" >&2; rm -f "$tmp"; die "that would make the project invalid; nothing changed"; }
    case $path in verify|verify.*) verify_env_gate "$n" "$path" "$tmp" || { rm -f "$tmp"; exit 1; };; esac
    chmod 600 "$tmp"; mv "$tmp" "$PROJ_DIR/$n.json"
    case $path in verify|verify.*) verify_env_record "$n" "$path" set;; esac
    audit_log "project:set" "$n $path (was: ${was:0:200})"
    echo "$n: $path = $val$(set_note "$n" "$path" "$val")"
    echo "was: $was"
    [ -z "$carry" ] || echo "note: models.provider was the single name '$carry'; it is now one name per surface, and the surface you did not set keeps '$carry'"
    case $path in models.provider|models.provider.*) no_provider "$PROJ_DIR/$n.json" "$n" || true;; esac
    case $path in models.provider|models.provider.local) reads_warn "$(pymod provider of-if-set "$n" --conf "$DA_CONF" --surface local 2>/dev/null </dev/null)";; esac;;
  unset)
    # remove one answer; the same refusals as set (the marshal backend, the answers that take a plan token), and a member never runs it: its guard
    # may not name this verb, so the refusal is made here, from the member's run directory or its marked environment
    n=${1:-}; path=${2:-}; PLAN_ARG='' APPROVED=''
    [ $# -ge 2 ] && [ -n "$path" ] || usage_die "unset needs NAME PATH (for example: unset $n backlog.file)"
    shift 2
    while [ $# -gt 0 ]; do
      case $1 in --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;; *) usage_die "unknown option $1";; esac
    done
    case $path in verify|verify.*) ;; *) [ -z "$PLAN_ARG$APPROVED" ] || usage_die "--plan and --approved apply only to verify.environment (removing it takes a plan token and the owner's words); $path takes neither";; esac
    [ -f "$PROJ_DIR/$n.json" ] || die "no project named '$n' (see: project list)"
    # the check answers 0 (a member run) or 3 (not one); any other status (python missing, the module unreadable, a traceback) is a failure to tell,
    # and an unknown caller is refused (fail closed), with python's own message left on stderr
    mrc=0; python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import marshal_refs; sys.exit(0 if marshal_refs.in_member_run() else 3)' "$(dirname "$(readlink -f "$0")")" || mrc=$?
    case $mrc in
      3) ;;
      0) echo "qargi: project unset is not available in a member run: it removes an answer of the project the lead runs on; propose the removal in your report" >&2; exit 2;;
      *) echo "qargi: project unset could not tell whether this is a member run (the check failed with status $mrc); refused: it removes an answer of the project the lead runs on" >&2; exit 2;;
    esac
    printf '%s' "$path" | grep -Eq '^[a-z_][a-z0-9_.-]*$' || die "PATH: dotted keys such as roles.write.effort"
    case $path in marshal.lease_minutes) ;; marshal|marshal.*) die "$path is not a project answer: only marshal.lease_minutes is; to switch the shared backend use 'qargi marshal enable' or 'qargi marshal disable'";; esac
    case $path in verify|verify.*) verify_env_lock;; esac     # before the answers are read: the lock spans the read, the comparison and both writes
    was=$(answer_was "$PROJ_DIR/$n.json" "$path")
    gated=$(gated_path "$path" "$was") || gated=''
    [ -z "$gated" ] || { echo "qargi: $path is not removed with project unset: it changes what an agent may run on or accepts a surface with no read-only barrier, so it takes a plan token and an approval: $gated" >&2; exit 2; }
    [ "$was" != "(not set)" ] || die "$n: $path is not set; nothing to remove"
    tmp=$(mktemp "$PROJ_DIR/.set.XXXXXX")
    jq --arg p "$path" 'delpaths([$p | split(".")])' "$PROJ_DIR/$n.json" > "$tmp"
    out=$(validate "$tmp") || { echo "$out" >&2; rm -f "$tmp"; die "that would make the project invalid (an answer it needs); nothing changed"; }
    case $path in verify|verify.*) verify_env_gate "$n" "$path" "$tmp" || { rm -f "$tmp"; exit 1; };; esac
    chmod 600 "$tmp"; mv "$tmp" "$PROJ_DIR/$n.json"
    case $path in verify|verify.*) verify_env_record "$n" "$path" unset;; esac
    audit_log "project:unset" "$n $path (was: ${was:0:200})"
    echo "$n: $path removed$(set_note "$n" "$path" "$was")"
    echo "was: $was"
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
    export PLAN_ARG
    [ -f "$PROJ_DIR/$n.json" ] || die "no project named '$n' (see: project list)"
    PLK=$(dirname "$(readlink -f "$0")")/project_link.py
    LW=$(mktemp -d); trap 'rm -rf "$LW"' EXIT
    python3 -I "$PLK" plan "$verb" "$n" "$res" "$LW/token" || exit $?
    [ -s "$LW/token" ] || exit 0       # nothing to do (already linked): no token
    tok=$(cat "$LW/token")
    if [ -z "$APPROVED" ]; then
      echo "plan token: $tok   (apply with: --plan $tok --approved \"<the user's go-ahead>\")"; exit 0
    fi
    need_plan "$tok"
    audit_log "project:$verb" "$n ${res:-all} $tok"
    python3 -I "$PLK" apply "$verb" "$n" "$res" "$tok" || exit $?;;
  remove)
    # retire a project: its stored answers and its members, behind a plan; nothing of the repository, never a branch or the checkout. Refused while an open
    # feature, an open run, a live lease, an open release cut, a linked work tree, a cloud binding or a registered instance names the project (lib/project_remove.py)
    n=${1:-}; shift || true; valid_project "$n" || usage_die "remove needs a project name (lower-case letters and digits)"
    PLAN_ARG='' APPROVED=''
    while [ $# -gt 0 ]; do
      case $1 in --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;; *) usage_die "unknown option $1";; esac
    done
    export PLAN_ARG   # need_plan reads it
    # shellcheck disable=SC2034  # refuse (lib/lib.sh) names the verb and the project of its contract line from these
    QARGI_VERB="project remove" PROJECT=$n
    # a member never runs it (its guard may not name the verb, so the check is made here as well: from the run directory or the marked environment); an unknown caller is refused
    mrc=0; python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import marshal_refs; sys.exit(0 if marshal_refs.in_member_run() else 3)' "$(dirname "$(readlink -f "$0")")" || mrc=$?
    case $mrc in
      3) ;;
      0) refuse member-lead-verb;;
      *) echo "qargi: project remove could not tell whether this is a member run (the check failed with status $mrc); refused: it removes the answers of a project the lead runs on" >&2; exit 2;;
    esac
    [ -f "$PROJ_DIR/$n.json" ] || refuse project-remove-unknown name="$n"
    members_shape_ok || fail "$MEMBERS_FILE is not in the current shape (qargi upgrade); nothing was planned or removed"
    scan=$(python3 -I "$(dirname "$(readlink -f "$0")")/project_remove.py" scan "$n") || exit 1
    remove_refuse_held() { # SCAN: refuse with the first hold the scan names (nothing when it names none); the others are named beside it, so one run says what to clear
      local held
      [ "$(jq -r '.held | length' <<<"$1")" != 0 ] || return 0
      [ "$(jq -r '.held | length' <<<"$1")" = 1 ] || echo "qargi: note: also held: $(jq -r '[.held[1:][].code | sub("^project-remove-"; "")] | join(", ")' <<<"$1")" >&2
      held=$(jq -r '.held[0].code' <<<"$1")
      hv() { jq -r --arg k "$1" '.held[0].values[$k] // ""' <<<"$2"; }   # the values the scan names for the refusal, one text for each field (a list is joined by commas)
      [ "$held" != project-remove-feature ] || refuse project-remove-feature name="$n" features="$(hv features "$1")"
      [ "$held" != project-remove-run ] || refuse project-remove-run name="$n" runs="$(hv runs "$1")"
      [ "$held" != project-remove-lease ] || refuse project-remove-lease name="$n" features="$(hv features "$1")"
      [ "$held" != project-remove-release ] || refuse project-remove-release name="$n" versions="$(hv versions "$1")"
      [ "$held" != project-remove-linked ] || refuse project-remove-linked name="$n" trees="$(hv trees "$1")"
      [ "$held" != project-remove-cloud ] || refuse project-remove-cloud name="$n"
      [ "$held" != project-remove-instances ] || refuse project-remove-instances name="$n" instances="$(hv instances "$1")"
      [ "$held" != project-remove-unreadable ] || refuse project-remove-unreadable name="$n" what="$(hv what "$1")" fix="$(hv fix "$1")"
      fail "project remove: the scan named a hold this verb does not know ($held); nothing was changed"
    }
    remove_refuse_held "$scan"
    # the token covers the answers (their hash), the approved declaration, the raw records of the members (their hash) and each member as the plan shows it: it does not depend on what could hold the removal, so a token stays good after a refusal
    remove_token() { # SCAN: the token of the plan the scan describes
      { printf '%s\n%s\n%s\n%s\n' "$n" "$(jq -r .answers_sha <<<"$1")" "$(jq -r 'if .approved == null then "none" elif .approved == "" then "off" else .approved end' <<<"$1")" "$(jq -r '.members_sha | if . == "" then "none" else . end' <<<"$1")"
        jq -r '.members[] | [.name, (.roles | join(",")), .file, .copy] | join("|")' <<<"$1"; } \
        | plan_token --basis "project answers approved records member" --verb "project remove" --target "$n:answers"
    }
    tok=$(remove_token "$scan")
    echo "remove project $n"
    echo "  the stored answers, removed: $(jq -r .answers <<<"$scan")"
    if [ "$(jq -r '.members | length' <<<"$scan")" = 0 ]; then echo "  members: none"; else
      echo "  members of $n, removed as qargi agent remove removes each (the member file, the copy of its render, the entry in agents.json):"
      jq -r '.members[] | "    \(.name) (\(.roles | join(","))): \(if .file == "" then "no file recorded" else .file + (if .file_exists then "" else " (not there)" end) end); copy \(if .copy == "" then "none" else .copy + (if .copy_exists then "" else " (not there)" end) end)"' <<<"$scan"
    fi
    jq -r 'if .approved == null then empty else "  the approved verify.environment declaration of the project" + (if .approved == "" then " (it declares none)" else " (id " + .approved + ")" end) + " is forgotten with it (verify-env.json)" end' <<<"$scan"
    jq -r '[.members[] | select(.in_repo and .file_exists)] | if length == 0 then empty else "  in the checkout: \(length) member file(s) above are inside the work tree of the repository and are deleted from it (a runtime that keeps its member files there); the lines qargi wrote in .git/info/exclude for them stay" end' <<<"$scan"
    echo "  not touched: the repository's branches, history and files except the member files above (no git operation changes anything); the marshal records, the audit log, the project's memory, the rendered packs and member render, the stored plans"
    jq -r '.stays[] | "  stays: \(.) (a file of the marshal of \($n); the removal leaves it)"' --arg n "$n" <<<"$scan"
    echo "  nothing holds it back: no open feature, run, live lease or release cut, no linked work tree, cloud binding or registered instance names $n"
    echo
    if [ -z "$APPROVED" ]; then
      echo "plan token: $tok   (remove with: qargi project remove $n --plan $tok --approved \"...\")"
      exit 0
    fi
    need_plan "$tok"
    verify_env_lock   # a change of verify.environment that is going on meanwhile finishes before the declaration is forgotten, and the removal before the next begins
    # tests only: QARGI_TEST_REMOVE_HOLD=PATH says PATH.reached and waits (30 s at most) for PATH.go, so a test can change what the scan reads between the plan and the removal
    if [ -n "${QARGI_TEST_REMOVE_HOLD:-}" ]; then
      : > "$QARGI_TEST_REMOVE_HOLD.reached"
      for _ in $(seq 300); do [ -e "$QARGI_TEST_REMOVE_HOLD.go" ] && break; sleep 0.1; done
    fi
    # every read the removal depends on is made before the first change, so that a failure leaves nothing half removed: the approved declarations must be readable now
    venv_load "$n" || fail "the approved declarations could not be read (verify-env.json), so nothing of $n was removed"
    # what held it back is read again just before the first change: a feature, run, lease or link that appeared since the plan refuses the apply, and so does anything the plan covers that moved
    scan=$(python3 -I "$(dirname "$(readlink -f "$0")")/project_remove.py" scan "$n") || exit 1
    remove_refuse_held "$scan"
    need_plan "$(remove_token "$scan")"
    nmt=$(jq -r '.members | length' <<<"$scan"); nm=0
    # the audit line is written before the first removal, so a removal that stops part way is in the log; the steps below stop with a second line that says where
    audit_log "project:remove" "$n ($nmt member(s)) begun: the members are removed one by one, then the approved declaration, then the stored answers"
    remove_stopped() { # WHAT: the removal stopped; what was already removed stays removed, the stored answers stay, and the audit log says so
      audit_log "project:remove" "$n stopped after $nm of $nmt member(s): $1; the stored answers of $n are still there"
      fail "project remove stopped: $1; $nm of $nmt member(s) were removed and the stored answers of $n are still there (the audit log says so): run project remove again for a plan of what is left"
    }
    while IFS= read -r m; do
      mf=$(jq -r '.value.file // ""' <<<"$m"); rp=$(jq -r '.value.render.path // ""' <<<"$m")
      [ -z "$mf" ] || [ ! -f "$mf" ] || rm -f "$mf" || remove_stopped "the member file $mf of $(jq -r .key <<<"$m") could not be removed"
      case $rp in ''|/*|..|../*|*/..|*/../*) ;; *) rm -f "$DA_CONF/agents/$n/$rp" || remove_stopped "the copy $DA_CONF/agents/$n/$rp of $(jq -r .key <<<"$m") could not be removed";; esac
      nm=$((nm + 1))
    done < <(jq -c --arg p "$n" '.projects[$p] // {} | to_entries[]' "$MEMBERS_FILE")
    rmdir "$DA_CONF/agents/$n" 2>/dev/null || true
    [ "$(jq -r --arg p "$n" '.projects | has($p)' "$MEMBERS_FILE")" != true ] || json_update "$MEMBERS_FILE" 'del(.projects[$p])' --arg p "$n" || remove_stopped "the entries of the members in $MEMBERS_FILE could not be removed"
    frc=0; venv_py approved forget "$n" --state "$DA_STATE" >/dev/null || frc=$?
    case $frc in 0|1) ;; *) remove_stopped "the approved declarations could not be written (verify-env.json), so none was forgotten";; esac
    rm -f "$PROJ_DIR/$n.json" || remove_stopped "the stored answers $PROJ_DIR/$n.json could not be removed"
    audit_log "project:remove" "$n ($nm member(s)) removed"
    echo "removed project $n: its stored answers and $nm member(s)"
    echo "approved: $APPROVED; the repository was touched only by the member files listed in the plan (no branch, no git operation that changes anything)";;
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
    [ -n "$n" ] || n=$(pymod help infer 2>/dev/null) || n=''
    af=''
    if [ -n "$n" ]; then af=$PROJ_DIR/$n.json; [ -f "$af" ] || die "no project named '$n' (see: project list)"; fi
    exec python3 -I "$(dirname "$(readlink -f "$0")")/project_profile.py" check "$DA_CONF" "$af" "${pf/#\~/$HOME}";;
  *) usage_die "usage: project.sh template|init|new|attach|adopt|set|unset|link|unlink|remove|show|list|validate|profile ...";;
esac
