"""The description of the qargi command line: the single source of the terminal help, the man page and
the bash completion. tests/test_help.py checks it against the scripts, so a flag or a verb that is added
without being described here fails the suite.

A verb is  verb(summary, args=[(NAME, type[, optional])], opts=[opt(...)], desc=..., examples=[...])
Argument and option value types drive completion: project, instance, team, role, session, pack-skill,
pack-tool, member, file, dir, none, or a tuple of fixed words."""

TAGLINE = "A gathering place for agent work: dispatch, review, remember."

INTRO = (
    "qargi dispatches one-off, task-scoped development tasks to sandboxed agents and takes the work back as "
    "reviewable patches. An agent is a Claude Code subagent on this machine (local, the default) or an Anthropic "
    "Managed Agents agent (cloud, only when you ask for it in that request). Agents work in their own clone and "
    "never push. A team adds a lead that coordinates members for build, write and review on one task. "
    "Everything qargi stores about you and your projects lives outside every repository. Inside a project's repository you can leave out its name."
)

ROLES = ("build", "write", "review", "test", "lead")
ABILITIES = ROLES[:-1]   # the work roles; each is defined by the skill qargi-<ability>
def _provider_models():
    """The model ids and aliases of the provider descriptors (lib/providers/NAME.json), for completion."""
    import glob, json, os
    out = []
    for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers", "*.json"))):
        if os.path.basename(f) in ("schema.json", "adapter-schema.json"):
            continue
        try:
            d = json.load(open(f))
            out += [m for m in list((d.get("tiers") or {}).values()) + list((d.get("aliases") or {}).values()) if isinstance(m, str)]
        except (OSError, ValueError, AttributeError):
            pass
    return tuple(dict.fromkeys(out))


MODELS = _provider_models()
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def opt(flag, help, arg=None, type="none"):
    return {"flag": flag, "arg": arg, "help": help, "type": type}


def verb(summary, args=(), opts=(), desc="", examples=()):
    return {"summary": summary, "args": [tuple(a) + (False,) if len(a) == 2 else tuple(a) for a in args],
            "opts": list(opts), "desc": desc, "examples": list(examples)}


HOOK_REC = ("Reads the hook's JSON on stdin and appends one small line to the run's event file under the state directory "
            "(ids, times, names and hashes; never command, message or error text). It always exits 0 at once, even on malformed input, "
            "so it cannot block an agent. Register it with qargi supervise hooks.")
ASKED = opt("--asked", "the request, in your words, that names the cloud instance; recorded in the audit log", "REQUEST")
PLAN = opt("--plan", "the plan token printed by the same command without --approved", "TOKEN")
APPROVED = opt("--approved", "your go-ahead for exactly that plan, in your words; recorded in the audit log", "WORDS")
TARGET = opt("--target", "claude-code renders for a local Claude Code session; managed-agents (the default for apply) is the cloud update", "TARGET", ("claude-code", "managed-agents"))
PREFIX = opt("--prefix", "pick the notes under this path (repeat for several)", "PATH")
ROLE_SEL = opt("--role", "pick the notes under /roles/ROLE/", "ROLE", ROLES)
NOTE_KIND = opt("--note-kind", "pick the notes whose Kind: header is KIND (setup, gate, rule, ...)", "KIND")
POLICY = opt("--policy", "what to do when a note differs: conflicts (put the incoming one in /_conflicts/<date>/, default) or keep (leave it and report)", "POLICY", ("conflicts", "keep"))
KIND = opt("--kind", "which store: memory or reference (default: both)", "KIND", ("memory", "reference"))

REASONS = ("wrong-scope", "broke-check", "style", "too-slow", "too-costly", "skill-ignored", "skill-wrong", "brief-unclear", "gate-noise", "other")

PROJECT_OPT = opt("--project", "the project, instead of the one inferred from here", "PROJECT", "project")
AS_OPT = opt("--as", "act as this lead identity (default: the session id in QARGI_LEAD, else user@host)", "ID")
RESOLVED_OPT = opt("--resolved", "use the merge you resolved and committed in the conflict worktree")
REMOTE_NOTE = ("It asks the live origin with git ls-remote (QARGI_REMOTE_TIMEOUT seconds, default 10) where the branches are, not the last fetch, "
               "and says 'remote not checked' when origin cannot be reached.")
HOTFIX_OPT = opt("--hotfix", "a hotfix: branch from master, finish into master and the open release branch (or develop)")

GROUPS = [
    ("Set up", ["project", "methodology", "cloud", "agent", "role", "provider", "provision", "instances", "skill", "tool", "packs", "discover"]),
    ("Run a task", ["feature", "marshal", "release", "start", "send", "status", "report", "noticed", "watch", "collect", "stop", "close", "mark", "track", "local", "supervise"]),
    ("Review and apply", ["review", "team"]),
    ("Memory", ["memory", "canon"]),
    ("Lead and credentials", ["lead", "credential", "hook"]),
    ("Export and import", ["export", "import", "migrate"]),
    ("Other", ["upgrade", "help", "version"]),
]

COMMANDS = {
    "project": {
        "summary": "Store the answers about a project, once, outside the repository",
        "desc": ("The answers are the repository, its long-lived branches, the roles that exist (build, write, review, test) "
                 "with each role's base branch, model, effort, packages and skills, the memory stores, the budget, and "
                 "optionally a lead with teams and a push grant. Provisioning and dispatch read them. Push policy per role "
                 "is none: an agent never pushes; the lead's grant is separate (qargi help push)."),
        "scripts": ["project.sh"],
        "verbs": {
            "template": verb("Print an answers file with defaults", [("NAME", "none")], desc="Edit it, then store it with init."),
            "init": verb("Validate and store an answers file", [("NAME", "none")],
                         [opt("--answers", "the answers file to store", "FILE", "file"), opt("--force", "replace stored answers")],
                         examples=["qargi project template acme > acme.json", "qargi project init acme --answers acme.json"]),
            "new": verb("Start a new project: its directory, a git repository on the methodology's branches and generic files", [("NAME", "none")],
                        [opt("--methodology", "the methodology (default gitflow)", "NAME", "methodology"), opt("--dir", "where to create it (default ./NAME; must be absent or empty)", "DIR", "dir"),
                         opt("--param", "a methodology parameter as name=value (repeat), for example test_command", "NAME=VALUE"),
                         opt("--url", "the repository URL; with it the qargi answers are stored too", "URL"),
                         opt("--deployment", "a deployment option to record and explain (see qargi methodology deployment)", "ID"), PLAN, APPROVED],
                        desc=("Prints the plan (directory, branches, files, deployment options with instructions) and a token; with --plan and --approved it creates the "
                              "directory, runs git init, writes the generic files in a first commit and creates the long-lived branches. Nothing is pushed and no remote "
                              "is created: say where it goes with git. The files mention no tool of yours."),
                        examples=["qargi project new acme --param test_command='make test'", "qargi project new acme --dir ~/src/acme --url https://github.com/me/acme"]),
            "attach": verb("Attach to an existing repository: read it, show the answers and the gaps, store on approval", [("[DIR]", "dir")],
                           [opt("--name", "the project name (default: from the remote or the directory)", "NAME"),
                            opt("--methodology", "the methodology to compare with (default gitflow)", "NAME", "methodology"),
                            opt("--url", "the repository URL, when it has no origin remote", "URL"),
                            PLAN, APPROVED, opt("--force", "replace the detected answers, keep the rest")],
                           desc=("Reads the repository (branches, tags, version and changelog files, test command, CI) and changes nothing in it. Prints the answers it "
                                 "would store, the gaps against the methodology and what it could not determine, and a plan token. With --plan and --approved it "
                                 "stores the answers outside the repository. The gaps are closed, if you want that, by a separate reviewed change. It reads the tree of the "
                                 "methodology's integration branch (develop), else of the default branch, else of HEAD, and says which; never the working tree. It prints "
                                 "origin as read and the https url it normalises to. If answers are already stored it shows stored against detected, lists the fields "
                                 "the stored file lacks, stays read-only and gives no plan token; with --force the plan replaces what it detects and keeps what it "
                                 "cannot (the roles' models and effort, cloud, memory, budget).")),
            "set": verb("Change one answer", [("NAME", "project"), ("PATH", "key"), ("VALUE", "value")],
                        desc="PATH is dotted (budget_cents, roles.write.effort, lead.push); VALUE is JSON or a plain string.",
                        examples=["qargi project set acme roles.write.effort high"]),
            "show": verb("Print the stored answers and what they mean", [("NAME", "project")]),
            "list": verb("List the stored projects"),
            "validate": verb("Check an answers file without storing it", [("FILE", "file")]),
        },
    },
    "agent": {
        "summary": "Name the members: the local agents that do the work",
        "desc": ("A member is a Claude Code subagent you name, rendered from the one member definition qargi ships, with the "
                 "abilities it serves: build, write, review, test (all four by default). The task block names the ability and carries its role "
                 "text (roles/<role>/ROLE.md); there is no skill to load. Review is read-only as a "
                 "rule: the guard refuses changes to the clone under that ability. Under every ability it refuses the verbs that change "
                 "a skill (qargi skill|tool new, import, seal, remove, link, unlink, enable, disable; qargi discover install; qargi packs apply) "
                 "and writes in the pack library, the credentials directory and install.json, ~/.claude/skills and any .claude/skills directory; it fails closed. Dispatch spawns the member qargi agent for "
                 "ABILITY prints."),
        "scripts": ["agent.sh"],
        "verbs": {
            "add": verb("Create a member under a name you choose", [("NAME", "none")],
                        [opt("--abilities", "comma-separated abilities it serves (default build,write,review,test)", "LIST", ABILITIES),
                         opt("--model", "model alias or id for the definition (default: the project's model for the first ability, else the shipped default; see agent models)", "MODEL", "model"),
                         opt("--effort", "effort level, written into the definition and recorded with the member (default as for --model)", "LEVEL", EFFORTS),
                         opt("--project", "put it in that project's repository (.claude/agents, hidden from git) instead of ~/.claude/agents", "PROJECT", "project")],
                        desc="Refuses a name that exists, a name that is not kebab-case, and the name of a built-in Claude Code agent type.",
                        examples=["qargi agent add forge --abilities build,test", "qargi agent add scribe --abilities write --model opus",
                                  "qargi agent add worker    # one member for all four abilities"]),
            "list": verb("List the members, their abilities and definitions"),
            "rename": verb("Rename a member and its definition", [("OLD", "member"), ("NEW", "none")]),
            "refresh": verb("Re-render a member from the member definition qargi ships now", [("NAME", "member")],
                            desc="Keeps its name, abilities and model. Use it after an upgrade changes the definition (for example its hook); an unchanged member is left alone. Sessions started afterwards use the new definition."),
            "models": verb("Show the base members, the profiles with their resolved models and efforts, and each member",
                           [], [PROJECT_OPT,
                                opt("--json", "machine-readable")],
                           desc="Two base members, one per guard class: worker (build, write, test; may write) and reviewer (review; read-only). "
                                "Everything else is a profile {base, tier, effort, purpose} resolved at dispatch: the shipped ones are in lib/model-defaults.json "
                                "(build, write, test, review, auditor, advisor, researcher, lead), a project adds or overrides its own under profiles.NAME in its answers, "
                                "and a provider file (lib/providers/claude.json; the project's models.provider) maps the tiers fast, balanced, deep and frontier to models. "
                                "The frontier tier (researcher) is opt-in. Problems are flagged on their row, never fatal: a legacy member (one per ability, retire it after the "
                                "base exists), a missing base, a refused project profile, a mixed-class member, a tier with no alias, a frontier member outside researcher. Read-only."),
            "remove": verb("Delete a member's definition and its record", [("NAME", "member")]),
            "for": verb("Print how to dispatch a role: the base member, the model alias and the effort", [("ROLE", "workrole")],
                        [opt("--project", "prefer that project's own members and read its profiles (default: the project of the current directory)", "PROJECT", "project"),
                         opt("--profile", "a profile of the role's class (a shipped one such as auditor, advisor or researcher, or the project's own; default: the role's own)", "NAME"),
                         opt("--surface", "local (default) or cloud: with cloud, resolve the registered cloud instance instead of a member", "SURFACE"),
                         opt("--opt-in", "cloud only: confirm an opt-in profile such as researcher"),
                         opt("--json", "machine-readable: role, class, profile, base, member, tier, model alias, model id, effort (cloud: instance, base, legacy, model, effort)")],
                        desc="The base member is the one the profile names (worker for build, write and test, reviewer for review) when it is registered; otherwise the first registered member of the role's class (shown as legacy). A read-only role never resolves to a member that can write. Plain output is one line: MEMBER MODEL EFFORT PROFILE; pass MODEL and EFFORT to the Agent tool with the member as subagent_type."),
        },
    },
    "role": {
        "summary": "List and check the roles: what a member or cloud agent is for",
        "desc": ("A role is a directory with role.json (its class, write or read-only, and a description) and ROLE.md (its instructions). "
                 "Four ship with qargi: build, write, review and test (review is read-only). Add your own under ~/.qargi/config/roles/NAME/: "
                 "a name of one lower-case token, never lead. The class decides what the guard allows a member (read-only: nothing in the clone "
                 "changes); the text of a role cannot change it. A task block carries the role's text; a cloud agent of the role has it in its system prompt."),
        "scripts": ["role.sh"],
        "verbs": {
            "list": verb("List the roles, their class and where they live"),
            "show": verb("Print a role: its class, description and instructions", [("NAME", "workrole")]),
            "prompt": verb("Print a role's instructions as a task block carries them", [("NAME", "workrole")]),
            "check": verb("Validate one role, or all of them", [("[NAME]", "workrole")]),
        },
    },
    "feature": {
        "summary": "Develop on a feature branch; merge it into develop once, when complete",
        "desc": ("A feature branch is cut from develop and can be as broad as a theme. The lead merges the verified series of each related "
                 "task into it with --no-ff; tasks get targeted checks only. When the feature is complete the whole suite runs once on it and it is "
                 "merged into develop with --no-ff and deleted. The merges are made in temporary worktrees and a branch moves only after every merge "
                 "succeeded, so your checkout is never touched and a conflict changes nothing. Merging into develop and pushing need the plan token "
                 "and an approval."),
        "scripts": ["feature.sh"],
        "verbs": {
            "start": verb("Cut feature/NAME from develop", [("NAME", "none")], [PROJECT_OPT, opt("--purpose", "what the feature is about; related work only goes into one feature", "TEXT")],
                          desc="Refuses a name origin already has (asked live with git ls-remote), so another person's branch is not shadowed; fetch it instead."),
            "list": verb("List the open features: purpose, distance from develop, and the files two features both change", [], [PROJECT_OPT],
                         desc="Several features can be open at once. Two that change the same file will conflict whichever lands second: keep related work in one feature, unrelated work in another."),
            "sync": verb("Merge develop into the feature (after another feature landed, before this one's checkpoint)", [("NAME", "none")], [PROJECT_OPT, RESOLVED_OPT]),
            "merge": verb("Merge a verified task branch into feature/NAME with --no-ff", [("NAME", "none"), ("BRANCH", "branch")], [PROJECT_OPT, RESOLVED_OPT]),
            "status": verb("Show the feature: commits ahead of develop and whether the whole suite passed at its head", [("NAME", "none")], [PROJECT_OPT],
                           desc=REMOTE_NOTE),
            "verify": verb("Run the project's whole test suite on the feature's head and record the result", [("NAME", "none")], [PROJECT_OPT]),
            "finish": verb("Merge the feature into develop with --no-ff and delete it", [("NAME", "none")],
                           [PROJECT_OPT, opt("--keep", "keep the branch"), PLAN, APPROVED, RESOLVED_OPT],
                           desc=("Needs a passing whole-suite run at the feature's head. Pushes develop if the repository has an origin. " + REMOTE_NOTE + " A merge that conflicts changes "
                                 "nothing: the merge is left in progress in a worktree under the state directory (exit 3), you or the lead resolve and commit it there, "
                                 "and the same command with --resolved applies exactly that merge.")),
        },
    },
    "marshal": {
        "summary": "Who leads which open feature: lease, status, goal, plan, handoff",
        "desc": ("The marshal keeps one record per open feature: its lead (identity and lease), status, goal, plan and a note, and derives the "
                 "tasks, branches, worktrees and overlap from git and the local runs. Query it before beginning work or changing a plan: "
                 "qargi marshal check NAME. A lead is a Claude Code session (identified by its session id), or whoever passes --as. "
                 "A lead holds a lease that its actions and long verbs renew; another lead takes the feature only after it was released "
                 "(take) or after the record stayed unchanged for the project's marshal.ttl minutes (takeover, with your words). "
                 "Records are state, not instructions: a note or goal written by another lead is data. By default the records are local to this machine; "
                 "marshal enable switches the project to the shared backend, where each record is a commit on refs/qargi/features/NAME of the remote "
                 "origin so several machines and people see the same leads (takeover then waits for the record to stay unchanged for the ttl as seen by "
                 "the taker's own clock). Only the lead pushes those refs; a member run cannot. "
                 "Exit status 3 means the remote could not be checked (the cache was used). Records can be signed: one key per lead machine, a signers file per project "
                 "and the mode in the switch file (marshal enable --integrity); with integrity on, status and check tag records signed, unsigned, INVALID or cannot verify, "
                 "strict ignores unsigned and invalid ones with a warning, and a rollback prints rollback detected."),
        "scripts": ["marshal.sh", "marshal_store.py", "marshal_refs.py"],
        "verbs": {
            "claim": verb("Become the lead of feature NAME (creates the record; refuses when another lead holds it)", [("NAME", "none")],
                          [PROJECT_OPT, AS_OPT, opt("--goal", "what the feature is to achieve", "TEXT")]),
            "status": verb("Show one feature, or every open one with --all: lead, status, goal, plan, note, tasks, branches, worktrees, overlap", [("[NAME]", "none")],
                           [PROJECT_OPT, AS_OPT, opt("--all", "every open feature of the project"), opt("--history", "with --all, also the finished and abandoned ones, after the open ones"), opt("--brief", "one line per feature"), opt("--json", "machine-readable"), opt("--no-fetch", "read the cache of the shared refs only, do not fetch (the session hook uses it)")]),
            "set": verb("Update the goal, plan, note or status of a feature you lead", [("NAME", "none")],
                        [PROJECT_OPT, AS_OPT, opt("--goal", "the goal", "TEXT"), opt("--plan", "the plan, free text or a checklist", "TEXT"), opt("--note", "a note for the next reader", "TEXT"),
                         opt("--status", "planned, active, blocked or verifying", "STATE", ("planned", "active", "blocked", "verifying"))]),
            "check": verb("Before starting work or changing a plan: is the feature free for you, is anything else in its way (exit 1: refuse; warnings go to stderr)", [("[NAME]", "none")],
                          [PROJECT_OPT, AS_OPT, opt("--no-fetch", "read the cache of the shared refs only, do not fetch (the session hook uses it)")]),
            "renew": verb("Renew your lease on a feature (long verbs do this themselves)", [("NAME", "none")], [PROJECT_OPT, AS_OPT]),
            "release": verb("Give the feature up, leaving a handoff note; it has no lead until someone takes it", [("NAME", "none")],
                            [PROJECT_OPT, AS_OPT, opt("--note", "what the next lead must know", "TEXT")]),
            "take": verb("Become the lead of a feature that was released", [("NAME", "none")], [PROJECT_OPT, AS_OPT]),
            "takeover": verb("Take a feature from a lead that stopped (no change for the project's marshal.ttl); needs your words", [("NAME", "none")],
                             [PROJECT_OPT, AS_OPT, APPROVED]),
            "finish": verb("Mark the feature finished (feature finish does this)", [("NAME", "none")], [PROJECT_OPT, AS_OPT]),
            "enable": verb("Switch this machine's marshal to the shared refs backend (refs/qargi/ on the remote origin)", [],
                           [PROJECT_OPT, opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED,
                            opt("--integrity", "off, advisory or strict: how records are signed and checked", "MODE", ("off", "advisory", "strict"))],
                           desc=("Without options it prints the plan and a plan token; apply with --plan TOKEN --approved WORDS (audited as marshal:enable). It needs a remote named origin. "
                                 "--integrity sets the mode: off signs and checks nothing; advisory signs when a key exists and tags records signed, unsigned or INVALID without ignoring any; "
                                 "strict ignores records not signed by a trusted key and falls back to the last accepted record. Not available in a member run.")),
            "key": verb("Create this machine's signing key for the marshal records (key init)", [("SUBCOMMAND", "none")],
                        [PROJECT_OPT, opt("--principal", "the name the key is trusted under (default person@machine)", "ID"), opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED],
                        desc=("`key init` makes $QARGI_CONF/credentials/marshal_ed25519 (mode 600), never overwrites it, and prints the signers line to trust on every lead machine. "
                              "Audited as marshal:key-init. Not available in a member run.")),
            "signers": verb("List, add or remove the keys trusted to sign this project's marshal records (add | remove | list)", [("SUBCOMMAND", "none"), ("[PRINCIPAL]", "none")],
                            [PROJECT_OPT, opt("--line", "the signers line printed by key init (add)", "LINE"), opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED],
                            desc=("Edits $STATE/marshal/PROJECT.signers, which never goes into the repository or the refs. add and remove are audited as marshal:signers and refused in a member run; list is open to members.")),
            "resign": verb("Sign an unsigned open record (writes one more revision on top of it)", [("NAME", "none")], [PROJECT_OPT, opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED],
                           desc=("Used when moving from advisory to strict. The plan shows the head, its lead and goal and its token covers exactly that head; it is refused for a lead other than the accepted one. "
                                 "Audited as marshal:resign. Not available in a member run.")),
            "disable": verb("Switch back to the local records; the refs already on the remote stay (audited as marshal:disable)", [], [PROJECT_OPT, opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED],
                            desc="While integrity is advisory or strict it needs the plan token and your words (it drops the setting). Not available in a member run."),
        },
    },
    "release": {
        "summary": "Releases and hotfixes by the git-flow rules",
        "desc": ("release/<version> is cut from develop (a hotfix/<version> from master); its first commit bumps VERSION and dates the changelog and the man page. "
                 "It is pushed and a pull request into master runs CI on the commit that will be released. Finishing merges it into master with --no-ff, "
                 "tags it, merges it into develop (a hotfix: into the open release branch, if there is one) with --no-ff and deletes it. A release starts only from "
                 "a develop whose head passed the whole suite. Pushing, merging and tagging need the plan token and an approval."),
        "scripts": ["release.sh"],
        "verbs": {
            "start": verb("Cut release/VERSION from develop (hotfix/VERSION from master) and bump the version", [("VERSION", "none")], [PROJECT_OPT, HOTFIX_OPT, opt("--date", "the changelog and man page date (default today)", "YYYY-MM-DD"),
                                                                                                    opt("--allow-empty-notes", "release although '## [Unreleased]' in CHANGELOG.md is empty")],
                          desc=("Before anything changes it checks what a release must update and refuses, naming the file and the fix: a man page (man/*.1) needs a .TH line "
                                "with a date and a version field, which the first commit sets to the date and VERSION; a CHANGELOG.md needs content under '## [Unreleased]'. "
                                "A project without a man page or changelog is not checked for that part.")),
            "status": verb("Show the branch, its commits and whether the whole suite passed at its head", [("VERSION", "none")], [PROJECT_OPT, HOTFIX_OPT], desc=REMOTE_NOTE),
            "verify": verb("Run the project's whole test suite on the release branch (develop's head before it starts) and record the result", [("VERSION", "none")], [PROJECT_OPT, HOTFIX_OPT]),
            "push": verb("Push the branch and open the pull request into master", [("VERSION", "none")], [PROJECT_OPT, HOTFIX_OPT, PLAN, APPROVED], desc=REMOTE_NOTE),
            "finish": verb("After the checks pass: merge into master, tag, merge back, delete the branch, push", [("VERSION", "none")],
                           [PROJECT_OPT, HOTFIX_OPT, opt("--keep", "keep the branch"), PLAN, APPROVED, RESOLVED_OPT],
                           desc=("Merging back may conflict, usually over the version number (the model says so). Nothing moves then: resolve in the worktree "
                                 "the message names, commit, and run the same command with --resolved. " + REMOTE_NOTE)),
        },
    },
    "provision": {
        "summary": "Create the cloud agent, deployment and environment of an instance",
        "desc": ("Renders the agent, the shared environment, the memory stores it attaches and a manual-run deployment, "
                 "shows the plan, and creates them only with your go-ahead. Names follow qargi help naming. Provision the "
                 "role agents first; the lead (PROJECT-lead) needs them to exist."),
        "scripts": ["provision.sh"],
        "verbs": {
            "plan": verb("Render the files and print the plan (changes nothing)", [("NAME", "instance", True)],
                         [opt("--project", "the project, instead of NAME", "PROJECT", "project"), opt("--role", "the role (default build)", "ROLE", ROLES),
                          opt("--model", "model id, overriding the project's answers", "MODEL", "model"), opt("--effort", "effort level", "LEVEL", EFFORTS),
                          opt("--apt", "extra packages for the shared environment, space separated", "PACKAGES"),
                          opt("--networking", "the sandbox's network access", "MODE", ("unrestricted", "limited")),
                          opt("--budget", "spend ceiling of the deployment, in cents", "CENTS", "cents"),
                          opt("--memory-store", "attach this memory store instead of the project's", "ID", "store"),
                          opt("--reference-store", "attach this reference store", "ID", "store")],
                         examples=["qargi provision plan acme-write"]),
            "apply": verb("Create the resources of an approved plan", [("NAME", "instance", True)],
                          [ASKED, PLAN, APPROVED, opt("--project", "the project, instead of NAME", "PROJECT", "project"), opt("--role", "the role", "ROLE", ROLES)],
                          desc="Brings new memory stores to the canon, seeds the roles, records the ids and registers the instance."),
            "add-reference": verb("Create and attach a reference store to an existing instance", [("NAME", "instance")], [ASKED, APPROVED]),
        },
    },
    "instances": {
        "summary": "Register, inspect and manage agent instances",
        "desc": ("An instance is <project>-<role>, for example acme-build, or the lead acme-lead. The registry records where it "
                 "runs and which resources it uses. Verbs that change cloud resources need --asked, and show a plan first."),
        "scripts": ["registry.sh"],
        "verbs": {
            "init": verb("Register an instance", [],
                         [opt("--location", "where it runs", "WHERE", ("cloud", "local")), opt("--deployment", "an existing cloud deployment", "ID", "deployment"),
                          opt("--agent", "a local subagent definition file", "FILE", "file"), opt("--name", "the instance name", "NAME"),
                          opt("--provision", "create new resources through provision"), opt("--model", "model id", "MODEL", "model"),
                          opt("--effort", "effort level", "LEVEL", EFFORTS), opt("--budget", "spend ceiling in cents", "CENTS", "cents"),
                          opt("--apt", "packages for a provisioned environment", "PACKAGES"),
                          opt("--networking", "network access", "MODE", ("unrestricted", "limited")),
                          opt("--no-session", "do not start a standby session"), ASKED, PLAN, APPROVED],
                         desc="Usually you provision (qargi provision) and the instance is registered for you.",
                         examples=["qargi instances init --location local --agent ./agent.md --name acme-build"]),
            "list": verb("List the instances (cloud ones whose prompt is out of date are marked STALE) and their active sessions", [], [opt("--reconcile", "flag live sessions the tracker does not know")]),
            "show": verb("Show an instance and what is stale or misnamed", [("NAME", "instance")], [opt("--reconcile", "also flag untracked live sessions")]),
            "remove": verb("Forget an instance (the registry entry only)", [("NAME", "instance")], desc="Refused while it has open sessions."),
            "budget": verb("Change the spend ceiling of the instance's deployment", [("NAME", "instance:cloud"), ("CENTS", "cents")], [ASKED, opt("--session", "also change this running session", "SID", "session:active")]),
            "refresh-prompt": verb("Rebuild the agent's system prompt from the current contract", [("NAME", "instance")], [opt("--if-stale", "do nothing, and say so, when the prompt rendered now has the hash recorded at the last refresh (no cloud call)"), ASKED, PLAN, APPROVED],
                                   desc=("Prints what changes, then creates a new agent version and re-points the deployment. The hash of the prompt (and of the "
                                         "skill in it) is recorded when an agent is provisioned or refreshed; instances list marks a changed one with STALE and "
                                         "instances show says which part changed. An instance with no recorded hash is unknown, not stale.")),
            "normalize": verb("Rename the instance's cloud resources to the naming convention", [("NAME", "instance")], [ASKED, PLAN, APPROVED]),
        },
    },
    "skill": {
        "summary": "Create or import skills and attach them by scope",
        "desc": ("Skills and tools share one library with globally unique names; a link attaches one at a scope: user (every project "
                 "and role), user-role, project, or project-role. Imported content is shown, hashed and approved before it is stored, and "
                 "any later change is drift until you seal it again. Only you, with the person present, change a skill: a local member's "
                 "guard refuses the verbs new, import, seal, remove, link, unlink, enable and disable, and writes in the pack library, "
                 "and QARGI_NESTED does not stand in for the plan token of import and seal."),
        "scripts": ["packs.sh"],
        "verbs": "PACK",
    },
    "tool": {
        "summary": "Create or import tools (MCP servers with an allowlist) and attach them by scope",
        "desc": ("A tool is an MCP server with an explicit list of allowed tools and a permission policy for each. A write-like tool "
                 "cannot run unattended unless the tool is marked write_ok. Everything else works as for skills (qargi help skill)."),
        "scripts": ["packs.sh"],
        "verbs": "PACK",
    },
    "packs": {
        "summary": "Render, load or apply the skills and tools a role gets",
        "scripts": ["packs.sh"],
        "verbs": {
            "render": verb("Write what a role gets into a directory (used by provisioning)", [("PROJECT", "project"), ("ROLE", "role"), ("OUTDIR", "dir")]),
            "load": verb("Show what a role has enabled, or print one pack's text", [("[PACK]", "pack")], [opt("--role", "the role whose packs (required)", "ROLE", ROLES), opt("--project", "the project (default: inferred from here)", "PROJECT", "project")],
                         desc="Read-only, and evaluated from the links when called, so enabling or disabling a pack takes effect at once. Refuses a pack that fails its review or changed since it was approved."),
            "apply": verb("Update an existing cloud agent, or render for a local Claude Code session", [("INSTANCE|PROJECT", "instance")], [TARGET, ASKED, PLAN, APPROVED],
                          desc=("Without --target (or with managed-agents) this updates the existing cloud agent INSTANCE with its skills and tools; "
                                "the lead's GitHub tool arrives this way when the project grants a cloud push. It needs --asked, and always needs --plan "
                                "(QARGI_NESTED does not skip it); a local member's guard refuses it.\n"
                                "With --target claude-code it takes PROJECT instead of INSTANCE and needs no --asked. Without --approved it prints a plan token. "
                                "With --plan and --approved it renders the project's enabled skills and tools into $QARGI_STATE/claude/PROJECT, replacing the "
                                "previous render atomically, and prints the exact `claude --add-dir ...` launch line (with --mcp-config and --settings when the "
                                "render has them). Claude Code cannot enforce role scoping, so the render is the union of the project's roles and role scoping "
                                "is advisory there. Skills render under .claude/skills; tool packs render mcp.json and settings.json. Nothing is written into a "
                                "repository or into ~/.claude, and members cannot write under the state's claude/ directory.\n"
                                "The plan refuses, naming the pack and writing nothing, a skill whose SKILL.md name differs from the pack name, whose "
                                "front matter is not closed or has more than one name key; a skill and a tool with the same name; and a tool allowlist "
                                "name outside letters, digits, _, . and -. Each plan stages into its own hidden directory and a lock serializes "
                                "concurrent applies; the second refuses if the render changed meanwhile. The swap installs only the tree the token "
                                "approved; the token also covers the file modes, which the manifest records.")),
            "seed": verb("Add or update the baseline packs shipped with qargi in your library", [],
                         [opt("--install", "only add the packs the library lacks, without a token (install.sh --user runs this)"), PLAN, APPROVED],
                         desc=("qargi ships a few packs (packs/ in its tree). Seeding stores them in your library. Without --approved it prints one line per pack "
                               "(add, update, current or kept) and a plan token. A pack you edited and sealed, or one of your own with the same name, is kept and "
                               "never overwritten; an untouched shipped copy is updated when qargi ships a newer text. Seeding never links a pack: nothing "
                               "reaches a project or an agent until you link it.")),
            "check": verb("Check a Claude Code render for drift (read only)", [("PROJECT", "project")], [TARGET],
                          desc=("Needs --target claude-code. Writes nothing and exits 1 on any finding: library drift (a pack changed or failed review since it "
                                "was rendered), rendered tampering (a file differs from the manifest, or an extra or missing file), enablement drift (a pack "
                                "enabled or disabled, or its roles changed, since the render), shadowing of a rendered skill by ~/.claude/skills or by the "
                                "checkout's .claude/skills, and a missing manifest (nothing rendered yet). It also reports a rendered file that differs from "
                                "the library copy (even when the manifest was edited with it), a changed file mode, a group- or world-writable "
                                "render, a malformed manifest, and a manifest that names another project or whose role scoping is not advisory.")),
        },
    },
    "start": {
        "summary": "Start a standby cloud session for an instance",
        "desc": "Cloud only, and only when your request names it. The session's spend ceiling comes from the deployment.",
        "scripts": ["session.sh"],
        "usage": [("NAME", "instance:cloud")],
        "opts": [opt("--label", "a task slug for the session title", "SLUG"),
                 opt("--role", "the role a base session runs (required for <project>-worker and <project>-reviewer)", "ROLE"),
                 opt("--profile", "the profile of the role (default: the role's own)", "PROFILE"),
                 opt("--opt-in", "confirm an opt-in profile such as researcher"), ASKED],
    },
    "send": {
        "summary": "Send a task to an idle cloud session",
        "desc": ("The text is the whole brief: TASK, DONE (a command whose exit status decides it), BASE, SCOPE and so on. The session "
                 "is titled <instance>-<label>; use the same slug for the agent/<slug> branch."),
        "scripts": ["session.sh"],
        "usage": [("NAME", "instance:cloud"), ("TASK", "none")],
        "opts": [opt("--label", "the task slug (required)", "SLUG"), opt("--session", "send to this session", "SID", "session:idle"),
                 opt("--new", "start a new session first"),
                 opt("--role", "the role a base session runs (required for <project>-worker and <project>-reviewer)", "ROLE"),
                 opt("--profile", "the profile of the role (default: the role's own)", "PROFILE"),
                 opt("--opt-in", "confirm an opt-in profile such as researcher"), ASKED],
        "examples": ['qargi send acme-build "$BRIEF" --label rename-verb --asked "use the cloud builder for this"'],
    },
    "status": {
        "summary": "Show tracked cloud sessions, or one session",
        "scripts": ["session.sh"],
        "usage": [("SID|NAME", "target", True)],
    },
    "report": {
        "summary": "Cost per applied change, what waits for review, what looks stuck",
        "desc": ("Read-only. From the session tracker: per instance and in total, the sessions by review state and status, the spend "
                 "(list_cost, in the units of the budget flags: cents, per the docs) and the spend per applied session, how long each "
                 "session pending review has waited (oldest first), the sessions that look stale (running, or idle and pending review, "
                 "with no refresh for --stale-after), the idle sessions split by why they stopped when that is recorded, and the time "
                 "from creation to close. A second section lists local runs from the run directories qargi local prepare made: finished "
                 "(manifest DONE or BLOCKED), no manifest and still changing, or no manifest and quiet for --local-stale-after "
                 "(possibly stalled). The output says what it cannot tell you; it never prints a session's note or request."),
        "scripts": ["report.py"],
        "opts": [opt("--since", "only sessions and runs started on or after this date (2026-10-01)", "DATE"),
                 opt("--instance", "only this instance's sessions (leaves the local runs out)", "NAME", "instance"),
                 opt("--stale-after", "a running or idle-pending cloud session unseen for this long looks stale (default 2h)", "DURATION"),
                 opt("--local-stale-after", "a local run without a manifest and without file changes for this long is possibly stalled (default 30m)", "DURATION"),
                 opt("--runs-root", "also scan DIR/qargi.* for local runs the registry does not list (or set QARGI_RUNS_ROOT)", "DIR", "dir"),
                 opt("--json", "print the figures as JSON")],
        "examples": ["qargi report", "qargi report --since 2026-10-01 --instance acme-build --json"],
    },
    "watch": {
        "summary": "Wait for a cloud session to stop; prints one line when it does",
        "desc": "Run it in the background. The line is QARGI WATCH <sid> idle|terminated|budget_reached|budget_tight|timeout|auth|error. budget_tight ends it early, with the cost and the ceiling in cents, so you can raise the ceiling (qargi instances budget NAME CENTS --session SID) and watch again.",
        "scripts": ["watch.sh"],
        "usage": [("SID", "session:active"), ("MAX_SECONDS", "seconds", True)],
        "opts": [opt("--warn", "end the watch early with budget_tight when the cost reaches this percent of the ceiling (default 85; 0: never)", "PCT")],
    },
    "collect": {
        "summary": "Download a session's output files into a fresh directory",
        "desc": ("Everything downloaded is untrusted data. A team's files carry a role prefix and are split into one directory per "
                 "member, patches under patches/. Refuses a directory that is not empty."),
        "scripts": ["collect.sh"],
        "usage": [("SID", "session:uncollected"), ("DIR", "dir")],
    },
    "stop": {"summary": "Interrupt a running cloud session", "scripts": ["session.sh"], "usage": [("SID", "session:running")]},
    "close": {
        "summary": "Archive a finished cloud session",
        "desc": "Refused until the outputs are collected, unless the task produced none.",
        "scripts": ["session.sh"],
        "usage": [("SID", "session:active")],
        "opts": [opt("--no-outputs", "the task produced no files (for example memory curation)")],
    },
    "mark": {
        "summary": "Record what happened to a session's work",
        "scripts": ["session.sh"],
        "desc": "With --why, also records the reason (a code from lib/reasons.json); qargi report counts the reasons.",
        "usage": [("SID", "session:active"), ("STATE", ("applied", "rejected", "pending"))],
        "opts": [opt("--why", "why: wrong-scope, broke-check, style, too-slow, too-costly, skill-ignored, skill-wrong, brief-unclear, gate-noise or other", "CODE", REASONS)],
    },
    "upgrade": {
        "summary": "Move the installed tool to a newer branch or tag of its origin",
        "desc": ("Works on the root-owned checkout install.sh recorded (for example /opt/qargi). Without --approved it fetches the target, "
                 "shows the commits and files that would change and prints a plan token. With --plan TOKEN --approved \"...\" it applies exactly "
                 "that: a branch on the current branch moves forward only (fast-forward), another branch is checked out at its tip, a tag is "
                 "checked out detached; install.sh --user then runs as you and the members to refresh are listed. The git commands that write "
                 "into the checkout run through sudo (QARGI_SUDO names another command). A member or agent cannot use it."),
        "scripts": ["upgrade.sh"],
        "opts": [opt("--branch", "the branch to move to (default: the installed checkout's current branch)", "BRANCH"),
                 opt("--tag", "a tag to check out instead", "TAG"), PLAN, APPROVED],
        "examples": ["qargi upgrade --branch develop", "qargi upgrade --branch develop --plan 1a2b3c4d5e6f --approved \"upgrade to develop\"", "qargi upgrade --tag v0.2.0"],
    },
    "methodology": {
        "summary": "List and inspect the development and release methodologies",
        "desc": ("A methodology is the way a project is developed and released, as data: its branches, versioning and changelog, test tiers, "
                 "CI, release steps and deployment options, and the generic files a new project starts with. One ships with qargi (gitflow); "
                 "add your own under ~/.qargi/config/methodologies/NAME/ (methodology.json and a scaffold/ directory). These verbs only read; "
                 "qargi project new and adopt write, and only after a plan."),
        "scripts": ["methodology.py"],
        "verbs": {
            "list": verb("List the methodologies and where they live"),
            "show": verb("Print a methodology: branches, tests, CI, release steps, parameters, scaffold, deployment options", [("NAME", "methodology")]),
            "check": verb("Validate one methodology, or all of them", [("[NAME]", "methodology")]),
            "files": verb("Print the scaffold rendered with the parameters, writing nothing", [("NAME", "methodology")],
                          [opt("--param", "a parameter as name=value (repeat)", "NAME=VALUE")],
                          examples=["qargi methodology files gitflow --param project=acme --param test_command='make test'"]),
            "deployment": verb("List the deployment options, or print one option's instructions", [("NAME", "methodology"), ("[ID]", "none")]),
        },
    },
    "cloud": {
        "summary": "Which ant profile and workspace each project uses",
        "desc": ("A project can be bound to an ant profile and the workspace that profile must reach (the project's optional cloud answer). "
                 "Every qargi command about that project then runs ant under that profile, and a cloud call is refused if the profile no "
                 "longer reaches the workspace, so work never lands in another project's workspace. A project without a binding uses ant's "
                 "active profile. qargi stores and checks the binding; it never reads or writes a token. login runs ant auth login on your "
                 "terminal; a member or a script cannot."),
        "scripts": ["cloud.py"],
        "verbs": {
            "list": verb("Print every project's binding"),
            "show": verb("Print one project's binding", [("PROJECT", "project", True)]),
            "set": verb("Bind a project to an ant profile and a workspace", [("PROJECT", "project")],
                        [opt("--profile", "the ant profile name", "NAME"), opt("--workspace-id", "the workspace the profile must reach (wrkspc_...)", "ID")]),
            "unset": verb("Remove a project's binding", [("PROJECT", "project")]),
            "check": verb("Check that the profile exists and reaches the workspace (reads the ant profile only)", [("PROJECT", "project", True)]),
            "login": verb("Log the project's profile in, bound to its workspace (your terminal only)", [("PROJECT", "project")]),
        },
        "examples": ["qargi cloud set qargi --profile qargi --workspace-id wrkspc_01AbC...", "qargi cloud login qargi", "qargi cloud check"],
    },
    "provider": {
        "summary": "List and check the model providers: tiers, models and what each can do",
        "desc": ("A provider is a descriptor, lib/providers/NAME.json, with one schema for every provider: the model each tier "
                 "(fast, balanced, deep, frontier) maps to, with the date and source it was verified, the effort levels it understands, "
                 "which surfaces it serves (local, cloud) and a capability matrix per surface: model and effort overrides at dispatch, a fixed tool "
                 "list per agent, a read-only barrier, a session budget ceiling, memory stores, skills and MCP. A capability that is not "
                 "verified counts as not supported. A provider with no read-only barrier on a surface cannot serve the review role there "
                 "unless you accept that with qargi provider accept. The project's models.provider chooses the provider (default claude)."),
        "scripts": ["provider.py"],
        "verbs": {
            "list": verb("List the providers with the surfaces they serve and whether the descriptor is clean"),
            "show": verb("Print one provider: tiers and models, effort levels and the capability matrix per surface", [("NAME", "none")],
                         [opt("--json", "machine-readable")]),
            "accept": verb("Record that you accept a provider surface that has no read-only barrier", [("NAME", "none")],
                           [opt("--surface", "the surface the acceptance covers", "SURFACE", ("local", "cloud")),
                            opt("--no-barrier", "accept running the review role without a read-only barrier on that surface"),
                            opt("--project", "the project whose answers record it (default: the project of the current directory)", "PROJECT", "project"),
                            opt("--asked", "your words asking for it", "WORDS"), opt("--approved", "your words approving the plan", "WORDS"),
                            opt("--plan", "the plan token printed without it", "TOKEN")],
                           desc="Without --plan and --approved it prints what would be recorded and a plan token. Applied, it writes models.accept_no_barrier.SURFACE "
                                "(who, when, why) to the project's answers and the audit log. It is the only way a provider surface whose read-only barrier "
                                "is not supported can serve the review role."),
            "check": verb("Validate a descriptor and say what degrades", [("NAME", "none")],
                          desc="Fails on a descriptor that breaks the schema, a name that differs from its file, a missing tier or an unknown capability. "
                               "Warns on a verified date that is missing and says which capabilities count as not supported because of it, and which roles "
                               "therefore cannot be served (for example review where the read-only barrier is not supported)."),
        },
    },
    "noticed": {
        "summary": "What members noticed and did not act on, and what became of it",
        "desc": ("Collecting a session's outputs records each noticed_not_acted_on note of its manifest (stored short, secret-looking strings "
                 "redacted) in the append-only events file beside the audit log. Each note stays open until you give it a disposition: "
                 "followup, dismissed (with --why), accepted or superseded. qargi report shows how many are open and how old the oldest is."),
        "scripts": ["noticed.py"],
        "verbs": {
            "list": verb("Print the open notes, oldest first", [], [opt("--all", "every note, with its disposition")]),
            "resolve": verb("Give a note a disposition", [("ID", "none"), ("DISPOSITION", ("followup", "dismissed", "accepted", "superseded"))],
                            [opt("--why", "the reason; required to dismiss", "CODE", REASONS)]),
        },
    },
    "track": {
        "summary": "Track a session that was started elsewhere (for example in the console)",
        "scripts": ["session.sh"],
        "usage": [("NAME", "instance:cloud"), ("SID", "none")],
        "opts": [ASKED],
    },
    "local": {
        "summary": "Prepare, verify and clean a local run that has no way to push",
        "desc": ("The agent works in a clone of a bare copy that has no remote, runs git through a credential-less wrapper, and "
                 "verify compares every ref of the real repository before and after. It is a guard, not a sandbox."),
        "scripts": ["local.sh"],
        "verbs": {
            "prepare": verb("Make the clone and the wrapper for a local agent", [],
                            [opt("--repo", "the local repository", "DIR", "dir"), opt("--repo-url", "clone a private repository from this URL", "URL"),
                             opt("--credential-file", "token file for --repo-url", "FILE", "file"), opt("--base", "the base branch", "BRANCH", "branch"),
                             opt("--slug", "the task slug (branch agent/<slug>)", "SLUG"), opt("--scratch", "where to put the run", "DIR", "dir"),
                             opt("--role", "the task's role, written to RUN/ability with its class in RUN/class; a read-only role keeps the clone unchanged (default build)", "ROLE", "workrole"),
                             opt("--profile", "the profile to dispatch under (for example advisor or auditor for review); resolved before any clone, refused when its class does not fit the role, recorded in RUN/profile and printed with MEMBER, MODEL and EFFORT", "NAME"),
                             opt("--ability", "the earlier name of --role", "ABILITY", ABILITIES)],
                            desc=("Prints RUN, ROLE, CLASS, CLONE, OUT, TMP, GIT and BASE_SHA, then a blank line and a TASK-BLOCK PATHS block (RUN_DIR, CLONE, OUT, TMP, GIT, "
                                  "BASE_SHA) to copy into the task. A caller that evals the output must stop at the blank line.\n"
                                  "When the project (found by matching the repository against the stored answers) has a Claude Code render "
                                  "(packs apply --target claude-code) that has drifted, prepare also prints a WARNING block to stderr with the "
                                  "findings and the fix, packs apply --target claude-code PROJECT. The run goes on, and stdout and the "
                                  "TASK-BLOCK PATHS block are unchanged.")),
            "verify": verb("Compare the repository's refs with the snapshot taken by prepare", [("RUN_DIR", "dir")],
                           desc=("Exits 2 when refs changed (1 before). After a passing verify the run records RUN/verified, and later verify and clean compare with that: "
                                 "your own fast-forwards of develop and master and of agent|feature|release|hotfix/* branches, and new branches there, are accepted; remote "
                                 "refs, tags, deletions and rewrites still fail. Run it on every run before merging any of them.")),
            "clean": verb("Remove a collected, verified run and its temporary directory", [("RUN_DIR", "dir")],
                          [opt("--discard", "also clean a run whose output holds no manifest")],
                          desc=("Prepare makes a private temporary directory for the run (TMP, on /dev/shm when it exists) that the agent puts its test "
                                "sandboxes in; clean removes it with the clone, the bare copy and the output. It refuses a run whose output has no "
                                "manifest (collect first) and one whose repository refs changed (that is evidence).")),
        },
    },
    "review": {
        "summary": "Check what an agent returned and put it on a task branch",
        "scripts": ["review_check.py", "review.sh"],
        "verbs": {
            "check": verb("Check a run: numbered patches, messages, manifest, groups", [("RUN_DIR", "dir")],
                          [opt("--allow-empty", "accept a manifest with no commits (a team member that was blocked or had nothing to change)")],
                          desc=("Refuses a monolithic patch, a commit without a message body and a manifest that does not match the patches. "
                                "A review run passes with a report.md that has a Findings section instead of patches.")),
            "apply": verb("Apply a collected, checked run to a task branch of the repository", [("RUN_DIR", "dir")],
                          [PROJECT_OPT, opt("--branch", "the branch to create (default agent/<slug> of the run)", "BRANCH", "branch")],
                          desc=("Refuses a run applied already, and unless review check passes for RUN_DIR/out (warnings allowed) and local verify accepts the run (a refs-changed result "
                                "prints the diff). Creates the branch at the commit the run's base branch had when the run was prepared and applies every patch "
                                "of out/patches in order with git am, in a temporary worktree of the project's repository: your checkout is never touched and no "
                                "other ref changes. The committer is the one the repository has configured, else the author of the patches. It refuses a "
                                "branch that exists; a patch that does not apply removes the worktree and the branch and names the patch. On success it prints "
                                "the commits and the next commands, and records branch and tip in RUN_DIR/applied and the branch in the run's ref snapshot, so "
                                "local clean still accepts the run."),
                          examples=["qargi review apply ./run", "qargi feature merge search agent/fix-names", "qargi local clean ./run"]),
            "prune": verb("List, or with --yes delete, the agent/* branches already merged into develop or a feature", [],
                          [PROJECT_OPT, opt("--yes", "delete them (without it nothing changes)")],
                          desc=("A branch is merged when it is an ancestor of develop or of any feature/* branch (the test git branch -d makes, against that target "
                                "rather than the checked-out branch). Only local agent/* branches are considered; a branch checked out in a worktree is kept; "
                                "no other branch is touched. Prints each branch it lists or deleted."),
                          examples=["qargi review prune", "qargi review prune --yes"]),
        },
    },
    "team": {
        "summary": "Run a task with a lead and role agents (opt-in)",
        "desc": ("For a change that affects usage: the build member changes the code, the write member updates the operational docs, the "
                 "review member judges both. The lead is this Claude Code session, a cloud lead, or a session started in the console; all follow "
                 "the lead contract. Each member returns its own series against its own base."),
        "scripts": ["team.sh"],
        "verbs": {
            "brief": verb("Print the brief a lead needs for one task", [("PROJECT", "project:teams"), ("TEAM", "team")],
                          [opt("--task", "what to do", "TEXT"), opt("--done", "an executable check for the builder's part", "COMMAND"),
                           opt("--base", "the builder's base branch (needed when the project says @dispatcher)", "BRANCH", "branch"),
                           opt("--write-done", "the writer's check", "COMMAND"), opt("--review-done", "the reviewer's check", "COMMAND")]),
            "check": verb("Check a collected team run: every member and the lead's report", [("RUN_DIR", "dir")]),
            "contract": verb("Print the lead's contract", desc="The procedure every lead follows, whoever it is."),
        },
    },
    "memory": {
        "summary": "Check a memory store, list its tiers, read a note, split, merge or copy stores",
        "desc": ("split, merge and copy work between two stores, each a directory of notes, a .jsonl dump (read-only: a source, never a "
                 "target) or a memstore_ id. A note with a name starting with a dot, or that a store cannot hold, makes the plan refuse and name it. Nothing is "
                 "deleted: what a split moves out of a store goes to /_archive/<date>/ and a collision to /_conflicts/<date>/, and the "
                 "origin of every note written is added to its Sources: line, so each change can be undone. Without --approved they "
                 "print the plan and its token and change nothing; a store whose notes changed since the plan is refused."),
        "scripts": ["memory.sh", "tierwrite.sh", "tierplan.py", "tiers.py"],
        "verbs": {
            "lint": verb("Check a store against the canon", [("STORE_ID", "store")], [opt("--kind", "recipes or reference (for a store before the canon)", "KIND", ("recipes", "reference"))]),
            "get": verb("Print one note", [("STORE_ID", "store"), ("PATH", "none")], examples=["qargi memory get memstore_01ABC /shared/INDEX.md"]),
            "tiers": verb("List the project's memory tiers (repo, cloud, project, shared, system): where each is, whether it exists, its notes", [],
                          [PROJECT_OPT, opt("--json", "machine-readable")],
                          desc=("A tier is one memory store of the standard layout at a fixed rank, highest first: repo > cloud > project > shared > system. "
                                "Where they are comes from the project's answers (memory.tiers; each key is optional and has a default). "
                                "The reference store is not a tier. Reads only; nothing is created or changed.")),
            "check": verb("Check every existing memory tier against the canon, and that no note lives in two tiers", [], [PROJECT_OPT],
                          desc=("Runs the canon check on each tier that exists, then reports a note path present in two or more tiers (structural files such as "
                                "README.md and INDEX.md repeat per tier and are fine). A tier that does not exist (memory init creates it) or cannot be reached is information, not a failure. "
                                "Exit 1 when anything failed.")),
            "init": verb("Create a memory tier (repo, project, shared or system) as an empty store of the standard layout", [("TIER", "none")],
                         [PROJECT_OPT, PLAN, APPROVED],
                         desc=("Without --approved it shows what would be created and a plan token and changes nothing. It refuses a tier that holds files that are not "
                               "a standard store, one whose place overlaps another tier, a repo tier outside the checkout, and the cloud tier (provision creates that). "
                               "The repo tier is written inside your repository checkout: qargi never commits it, so review it and commit or ignore it yourself. "
                               "A tier that is already set up says so and exits 0.")),
            "move": verb("Move notes from one tier to another, with the original archived in the first", [("PATH", "none")],
                         [PROJECT_OPT, opt("--from", "the tier the notes are in", "TIER", ("repo", "cloud", "project", "shared", "system")),
                          opt("--to", "the tier they go to", "TIER", ("repo", "cloud", "project", "shared", "system")), PLAN, APPROVED],
                         desc=("PATH is one note (ending in .md) or a folder prefix under shared/ or roles/ROLE/. Only notes move, never indexes. A note must live in one tier, "
                               "so it refuses a path that is also in another tier. Nothing is deleted: the original goes to /_archive/<date>/ of the first tier and each copy "
                               "records its origin. Without --approved it prints the plan and its token and changes nothing; a tier whose notes changed since the plan is refused.")),
            "split": verb("Copy the notes a selector picks into another store, optionally archiving the originals", [("FROM", "file"), ("TO", "file")],
                          [PREFIX, ROLE_SEL, NOTE_KIND, opt("--archive", "move the originals to /_archive/<date>/ in FROM (with their origin in Sources:)"), PLAN, APPROVED],
                          desc="At least one of --prefix, --role and --note-kind is needed; a note must match every one given. Notes already in TO are left; a different one goes to /_conflicts/<date>/ in TO.",
                          examples=["qargi memory split ./memory ./build --role build --archive", "qargi memory split ./memory ./build --role build --archive --plan TOKEN --approved \"go\""]),
            "merge": verb("Add every note of FROM that TO lacks", [("FROM", "file"), ("TO", "file")],
                          [POLICY, PLAN, APPROVED],
                          desc="FROM is only read. A note whose original sits in TO's archive is moved back from it, so merging what a split wrote undoes the split.",
                          examples=["qargi memory merge ./build ./memory"]),
            "copy": verb("Copy notes into another store, leaving the source as it is", [("FROM", "file"), ("TO", "file")],
                         [PREFIX, ROLE_SEL, NOTE_KIND, POLICY, PLAN, APPROVED],
                         desc="Without a selector every note is copied except /CANON.md. Each copy records its origin in Sources:."),
        },
    },
    "canon": {
        "summary": "Bring a project's two memory stores to the standard layout and keep them there",
        "desc": ("The canon fixes the layout and the note format of both stores (shared/ and roles/<role>/, a header on every note, an "
                 "index with a Load column). plan and apply move a store from any older version without losing a note."),
        "scripts": ["canon.sh"],
        "verbs": {
            "check": verb("Report conformance and the version of each store", [("PROJECT", "project")], [KIND]),
            "plan": verb("Print every step needed to reach the current canon (changes nothing)", [("PROJECT", "project")],
                         [KIND, opt("--default-role", "where an old reference store's files go", "ROLE", ROLES)]),
            "apply": verb("Run the plan", [("PROJECT", "project")], [KIND, PLAN, APPROVED, opt("--default-role", "as for plan", "ROLE", ROLES)]),
            "import": verb("Merge a foreign store (the old documentation store) under a role", [("PROJECT", "project")],
                           [opt("--from", "the source store id", "STORE_ID", "store"), opt("--role", "the role to import under", "ROLE", ROLES),
                            opt("--map", "the layout of the source", "NAME", ("docs-v0",)), PLAN, APPROVED]),
            "seed-role": verb("Write a role's baseline notes without overwriting anything", [("PROJECT", "project")],
                              [opt("--role", "the role, or shared", "ROLE", ROLES + ("shared",)), APPROVED]),
            "promote": verb("Move a role's note to shared/", [("PROJECT", "project")],
                            [KIND, opt("--path", "the note, /roles/<role>/...", "PATH"), APPROVED]),
            "audit": verb("Report a session that wrote under another role's folder", [("PROJECT", "project")], [KIND]),
        },
    },
    "credential": {
        "summary": "Check or set up the tokens qargi uses",
        "desc": "Tokens live in files only you can read, outside every repository, and never in a command line, the tracker or the audit log.",
        "scripts": ["cred.sh"],
        "verbs": {
            "check": verb("Probe the repository token: it must read and should not push", [("PROJECT", "project")],
                          [opt("--allow-write-token", "accept a token that can push, knowingly")]),
            "setup": verb("Set up the cloud lead's write token (prefer: qargi lead grant)", [("KIND", ("lead-push",)), ("PROJECT", "project")],
                          [opt("--from-file", "read the token from a file instead of stdin", "FILE", "file"),
                           opt("--allow-more-repos", "accept a token that can also write to other repositories"), ASKED, PLAN, APPROVED],
                          desc=("Checks the token itself against GitHub (fine-grained, this repository only, no Administration), stores it mode 600, "
                                "creates a vault with a bearer credential, attaches it to the lead's deployment and records the grant.")),
        },
    },
    "discover": {
        "summary": "Find, recommend and install tools for the roles of a project",
        "desc": ("A tool is a skill, an MCP server, a package for the sandbox or a built-in tool of the agent. search looks in the reviewed "
                 "catalog and your library and, with --online, in the official MCP registry and Anthropic's skills. recommend ranks the catalog for "
                 "each role of a project by the stack it sees in the repository, leaving out what the role has. install asks which scope the tool "
                 "should reach (user, user-role, project, project-role), then goes through the existing gates: a skill or an MCP server is "
                 "imported with its review and your approval of exactly that content, linked at the scope, and offered to the cloud agents it "
                 "reaches with the plan shown first. Nothing found online is installed on trust. install changes skills, so a local "
                 "member's guard refuses it."),
        "scripts": ["discover.py"],
        "verbs": {
            "sources": verb("List what is searched", []),
            "search": verb("Search the catalog, your library and, with --online, the registries", [("QUERY", "none")],
                           [opt("--kind", "only this kind: skill, mcp, package or agent-tool", "KIND", ("skill", "mcp", "package", "agent-tool")),
                            opt("--role", "only tools recommended for this role", "ROLE", ROLES),
                            opt("--online", "also search the MCP registry and Anthropic's skills")],
                           examples=["qargi discover search pdf", "qargi discover search github --online --kind mcp"]),
            "recommend": verb("Rank the catalog for the roles of a project", [("PROJECT", "project", True)],
                              [opt("--role", "only this role", "ROLE", ROLES)], examples=["qargi discover recommend acme --role build"]),
            "show": verb("Show one entry: what it is, its risk and how it installs", [("ID", "entry")]),
            "install": verb("Install an entry: review, approval, scope, link", [("ID", "entry")],
                            [opt("--scope", "user, user-role, project or project-role (default: ask)", "SCOPE", ("user", "user-role", "project", "project-role")),
                             opt("--project", "the project, for the project scopes", "PROJECT", "project"),
                             opt("--role", "the role, for the role scopes", "ROLE", ROLES),
                             opt("--dry-run", "print the plan and stop; changes nothing")],
                            desc="Interactive: it asks at the terminal, and your answers are the recorded approvals.",
                            examples=["qargi discover install skill-pdf --project acme --role write"]),
        },
    },
    "export": {
        "summary": "Save a project's setup, definitions and memories to one file",
        "desc": ("Writes one archive of the parts you select: config (project answers, instances, profiles, the skill and tool library), "
                 "definitions (the cloud agents, deployments and environment as they are now, secrets removed), memories (every note of the "
                 "memory and reference stores), state (session tracker, audit log) and credentials (token files; only in an encrypted "
                 "archive). It asks what to include and for an optional password; with one, the whole archive is encrypted by gpg (AES-256) and "
                 "the password never goes into a command line. It only reads: nothing is changed or deleted."),
        "scripts": ["transfer.py"],
        "usage": [],
        "opts": [opt("--project", "only these projects, comma separated (default: ask, or all)", "NAMES", "project"),
                 opt("--only", "the parts: config, definitions, memories, state, credentials (default: ask)", "PARTS", ("config", "definitions", "memories", "state", "credentials")),
                 opt("--out", "the file to write (default: qargi-export-<time>.tar.gz[.gpg] here)", "FILE", "file"),
                 opt("--password-file", "encrypt with the first line of this file", "FILE", "file"),
                 opt("--no-encrypt", "write the archive without a password (for scripts)")],
        "examples": ["qargi export", "qargi export --project acme --only config,memories --no-encrypt --out acme.tar.gz"],
    },
    "import": {
        "summary": "Restore from an export, choosing what and how",
        "desc": ("Reads an archive made by qargi export (asking for the password when it is encrypted), shows what is inside, asks which "
                 "parts and projects to import and, for each part, how to treat what already exists: merge (add what is missing), overwrite "
                 "(also replace what differs) or replace (make it match the archive, removing the rest). It then prints the plan and writes "
                 "nothing until you confirm; replaced and removed items are saved under the state directory first. The archive is treated as "
                 "untrusted data: names and checksums are verified. Definitions are restored as files only (rebuild with provision). Memory "
                 "notes go to the stores named in the project's answers. It asks at a terminal; --dry-run shows the plan without one."),
        "scripts": ["transfer.py"],
        "usage": [("FILE", "file")],
        "opts": [opt("--only", "the parts to import (default: ask)", "PARTS", ("config", "definitions", "memories", "state", "credentials")),
                 opt("--project", "only these projects of the archive, comma separated", "NAMES", "project"),
                 opt("--mode", "merge, overwrite or replace for every part (default: ask for each)", "MODE", ("merge", "overwrite", "replace")),
                 opt("--password-file", "the password is the first line of this file", "FILE", "file"),
                 opt("--dry-run", "print the plan and stop; changes nothing")],
        "examples": ["qargi import acme.tar.gz.gpg", "qargi import acme.tar.gz --dry-run --only memories"],
    },
    "migrate": {
        "summary": "Bring an installation made with older names to the current ones",
        "desc": ("home copies your qargi data from the earlier XDG directories ($XDG_CONFIG_HOME/qargi, default ~/.config/qargi, and "
                 "$XDG_STATE_HOME/qargi, default ~/.local/state/qargi) to ~/.qargi/config and ~/.qargi/state (QARGI_HOME replaces ~/.qargi). "
                 "Until it has run, every other command stops and tells you to run it. Without --approved it prints the plan, with every "
                 "directory, file and link it will create (modes and digests), the lock files it skips and the files in which it rewrites "
                 "old absolute paths (a project's credential file, local-runs.jsonl; the records audit.log, supervisor.log and run-events/ are copied byte for byte and listed as such), and a plan token, and changes nothing. With the token "
                 "and your go-ahead it copies: the old directories stay untouched as a backup, modes are kept, every copy is checked by "
                 "digest, and a failure removes what was made. It refuses when the new root exists and is not empty, and in a dev run "
                 "(a checkout other than the installed one) unless QARGI_HOME is set. Run again afterwards, it says there is nothing to do. "
                 "roles renames what was made with the role names dev and docs (now build and write) and the four fixed local "
                 "agents (now members you name): on this machine the registry, tracker, project answers, pack links and saved "
                 "definitions; in every project's two memory stores the role folders and the role names in indexes, README and "
                 "marker; in the cloud the agents and deployments, named as qargi instances normalize names them, and their "
                 "prompts, rebuilt as refresh-prompt does; and the old agent symlinks, replaced by members (qargi agent add). "
                 "Without --apply it prints the plan, with every cloud call, and a plan token. It is re-runnable: what is renamed "
                 "already is left out, and it stops at the first failure."),
        "scripts": ["migrate.py", "migrate_home.py"],
        "verbs": {
            "home": verb("Plan, then copy, the data from the XDG directories to ~/.qargi", [], [PLAN, APPROVED],
                         examples=["qargi migrate home", 'qargi migrate home --plan TOKEN --approved "yes, copy it"']),
            "roles": verb("Plan, then apply, the move to the ability names and to named members", [],
                          [opt("--member-names", "ability=name pairs for the members that replace the old agents (default builder, writer, reviewer, tester)", "LIST"),
                           opt("--apply", "apply the plan the token names"), PLAN,
                           opt("--asked", "the request, in your words, for this migration; needed when the plan changes cloud resources", "REQUEST")],
                          examples=["qargi migrate roles", "qargi migrate roles --member-names build=forge,write=scribe",
                                    'qargi migrate roles --apply --plan TOKEN --asked "migrate the roles of myproject"']),
        },
    },
    "lead": {
        "summary": "Give, inspect or take away the cloud lead's right to push",
        "desc": ("Only the lead ever pushes, never a member. With a grant it creates agent/* branches and opens pull requests; every merge is "
                 "asked of you, and it cannot publish releases. grant and revoke are interactive: each step prints its plan and asks you at the "
                 "terminal, and your answer is the recorded approval. From Claude Code run them with !."),
        "scripts": ["lead.sh"],
        "verbs": {
            "grant": verb("Guided: create or rotate the grant in three confirmed steps", [("PROJECT", "project:teams")],
                          [opt("--from-file", "read the token from a file instead of asking", "FILE", "file")],
                          desc="Explains how to create the fine-grained token, checks it, then: token and vault; the GitHub tool; the Push rules. Skips what is in place.",
                          examples=["qargi lead grant acme"]),
            "status": verb("Show what is in place and what is missing", [("PROJECT", "project:teams")]),
            "revoke": verb("Take the grant away", [("PROJECT", "project:teams")],
                           desc="Removes the tool and the Push rules, detaches and archives the credential, deletes the token file. Revoke the token on GitHub yourself."),
        },
    },
    "hook": {
        "summary": "Claude Code hooks",
        "desc": ("session-start loads the lead role's READMEs and indexes from both stores (about 4 KB) for the project whose repository the "
                 "session is in, and the push grant. Register it as a SessionStart hook; it prints nothing outside a registered project."),
        "scripts": ["hook.sh"],
        "verbs": {
            "session-start": verb("Print the SessionStart hook output for the current project",
                                  opts=[opt("--project", "the project, instead of finding it from the directory", "PROJECT", "project"),
                                        opt("--role", "the role to load (default lead)", "ROLE", ROLES)]),
            "subagent-start": verb("Record that a subagent started (SubagentStart hook)", desc=HOOK_REC),
            "subagent-stop": verb("Record that a subagent stopped and how many background tasks it still had (SubagentStop hook)", desc=HOOK_REC),
            "tool-use": verb("Record a successful tool call: its name and a hash of its input (PostToolUse hook)", desc=HOOK_REC),
            "tool-failure": verb("Record a failed tool call: its name, a hash of its input, whether it was an interrupt (PostToolUseFailure hook)", desc=HOOK_REC),
            "notification": verb("Record the type of a notification, for example permission_prompt (Notification hook)", desc=HOOK_REC),
            "stop-failure": verb("Record the error type a turn ended with, for example rate_limit (StopFailure hook)", desc=HOOK_REC),
            "pre-compact": verb("Record that the context is being compacted (PreCompact hook)", desc=HOOK_REC),
        },
    },
    "supervise": {
        "summary": "Find stalled agent runs: notify, prepare a nudge, never act alone",
        "desc": ("Hooks only record (the run-event verbs of qargi hook append ids, times, a tool name and a hash to a per-run file under "
                 "the state directory; no command, message or error text). One idempotent "
                 "tick is the only actor: it folds those files, the local-run registry and the session tracker into runs.json and classifies "
                 "each unfinished run in a fixed order: waiting on an approval (not a stall), stopped by an API error, interim (turn ended, "
                 "background work running, a cap of about 35 minutes), looping (three identical tool digests in a row), suspected dead (no "
                 "activity for too long); for cloud sessions requires_action, budget_reached, stale while running, idle awaiting review. It acts "
                 "only by printing `QARGI SUPERVISE <class> <run> <next-action>` lines, appending to supervisor.log and the audit log "
                 "(origin supervisor), and PREPARING a nudge in nudges.jsonl. A nudge is a fixed template, at most 2 per run with at least "
                 "10 minutes between them, never while the run waits on an approval or has little budget left, and never an approval. A "
                 "script cannot message a local subagent: the coordinating session delivers the prepared nudge and records it with delivered, "
                 "and only then does it count. A cloud nudge is sent only by nudge, which needs --asked. Nothing sends automatically; the "
                 "thresholds are data in lib/supervise-defaults.json, conservative floors until `qargi report` shows real run lengths. "
                 "Run the tick on a timer or a loop; status warns when it has not run for twice its interval."),
        "scripts": ["supervise.sh", "supervise.py"],
        "verbs": {
            "tick": verb("Fold the events, classify the runs, print what needs attention, prepare nudges",
                         opts=[opt("--now", "act as of this time (2026-10-30T12:00:00Z); for tests and replays", "ISO"), opt("--json", "print the result as JSON")],
                         desc="Run twice with nothing new it prints nothing the second time.",
                         examples=["qargi supervise tick"]),
            "status": verb("Show the runs by class and the nudges waiting; warns when the tick is overdue",
                           opts=[opt("--now", "compare the last tick with this time", "ISO"), opt("--json", "print the registry as JSON")]),
            "nudge": verb("Send the fixed nudge to a cloud session, only when the caps allow", [("SID", "session:active")],
                          [ASKED, opt("--now", "act as of this time; for tests and replays", "ISO")],
                          desc=("Refused when the session waits on an approval or has little budget left, when 2 nudges were already counted, or "
                                "within 10 minutes of the last one. The message is the fixed template, never text from the agent."),
                          examples=["qargi supervise nudge sesn_abc --asked \"nudge it, it has been quiet for hours\""]),
            "delivered": verb("Record that you delivered a local run's prepared nudge", [("KEY", "none")],
                              [opt("--now", "record this delivery time; for tests and replays", "ISO")],
                              desc="KEY is the agent id the tick printed. Only then does the nudge count against the cap."),
            "hooks": verb("Print the settings.json hook snippet for the run-event handlers",
                          opts=[opt("--qargi", "the command to put in the snippet (default qargi)", "COMMAND")],
                          desc="It never writes the file: merge the entries into your Claude Code settings.json yourself."),
        },
    },
    "help": {
        "summary": "Show help",
        "desc": "qargi help shows the commands; qargi help COMMAND the verbs and options of one; qargi help TOPIC explains an idea. Every command also takes --help.",
        "scripts": [],
        "usage": [("COMMAND|TOPIC", "help", True)],
        "opts": [opt("--man", "print the manual page source (roff); view it with: qargi help --man | man -l -")],
    },
    "version": {"summary": "Print the version", "scripts": [], "usage": []},
}

# skill and tool share one set of verbs
PACK_VERBS = {
    "new": verb("Create a pack from a template", [("NAME", "none")]),
    "import": verb("Import a pack from a directory, file or pinned git URL, after a review", [("SOURCE", "file")],
                   [opt("--name", "store it under this name", "NAME"), opt("--ref", "the git ref to pin", "REF"), opt("--path", "a subdirectory of the source", "SUB"), PLAN, APPROVED]),
    "list": verb("List the library, or what a project and role get", [("PROJECT", "project", True), ("ROLE", "role", True)]),
    "show": verb("Show a pack", [("NAME", "pack")]),
    "seal": verb("Approve the current content of a pack (after you edited it)", [("NAME", "pack")], [PLAN, APPROVED]),
    "link": verb("Attach a pack at a scope", [("NAME", "pack")],
                 [opt("--scope", "where it applies", "SCOPE", ("user", "user-role", "project", "project-role")),
                  opt("--project", "for the project scopes", "PROJECT", "project"), opt("--role", "for the role scopes", "ROLE", ROLES)]),
    "unlink": verb("Detach a pack from a scope (same options as link)", [("NAME", "pack")],
                   [opt("--scope", "the scope it was linked at", "SCOPE", ("user", "user-role", "project", "project-role")),
                    opt("--project", "the project", "PROJECT", "project"), opt("--role", "the role", "ROLE", ROLES)]),
    "enable": verb("Re-enable a pack for a role that opted out", [("PROJECT", "project"), ("ROLE", "role"), ("NAME", "pack")]),
    "disable": verb("Opt a role out of a pack", [("PROJECT", "project"), ("ROLE", "role"), ("NAME", "pack")]),
    "effective": verb("List what a role gets", [("PROJECT", "project"), ("ROLE", "role")]),
    "check": verb("Review, drift and missing packs of a role", [("PROJECT", "project"), ("ROLE", "role")]),
    "remove": verb("Delete a pack", [("NAME", "pack")], desc="Refused while it is linked."),
}
for _c in ("skill", "tool"):
    COMMANDS[_c]["verbs"] = PACK_VERBS

TOPICS = {
    "concepts": ("The model in one page", [
        "Task: you describe one task and an executable check that decides it is done. An agent works on it in its own clone and hands back "
        "numbered patches, one per commit, with a manifest. Nothing is pushed.",
        "Roles are the four abilities and the lead: build changes code, write writes the operational docs, review judges a change and changes no file, test writes and runs tests, lead coordinates a team. Each ability is defined by its role text, which comes with the task block. The local workers are members you name and give abilities (qargi agent add NAME --abilities build,test); qargi agent for ABILITY prints the member that serves it. "
        "A role has its own model, effort, skills and packages, stored in the project's answers.",
        "Local or cloud: local (a Claude Code subagent) is the default. The cloud is used only when your request for that task names it, "
        "and every cloud verb records your words with --asked.",
        "You decide: the coordinator re-verifies everything an agent returns (qargi review check), applies it as separate commits, and "
        "asks you before anything is pushed."]),
    "roles": ("Roles, abilities and members", [
        "Role build: the ability build; changes the code with its tests, manual page, help and changelog.",
        "Role write: the ability write; writes the operational documentation on its own branch.",
        "Role review: the ability review; reads a change, runs its checks and reports a verdict, and changes no file.",
        "Role test: the ability test; writes and repairs tests and proves them failing first and stable.",
        "Role lead: no ability of its own; it coordinates a team of members on one task (qargi team, the skill qargi-team).",
        "A member is a local agent you name (qargi agent add forge --abilities build,test), rendered from the one member definition "
        "qargi ships. The task block names the ability and carries its role text; there is no ability skill to load. qargi agent for ABILITY prints the member "
        "dispatch spawns. A cloud agent serves one role, is named <project>-<role> and carries its ability's role text in its prompt.",
        "Earlier installations (roles dev and docs, and the agents named qargi-<role> that served them) move with qargi migrate roles."]),
    "approvals": ("Plans, tokens and your go-ahead", [
        "A command that changes something shared prints a plan first. The plan ends with a plan token, a hash of what would be done.",
        "To apply, run the same command with --plan TOKEN --approved \"your words\". If the plan changed in between, the token no longer "
        "matches and nothing happens.",
        "--asked \"your request\" is required by every cloud verb: it records that you asked for the cloud. Both are written to an "
        "append-only audit log in the state directory.",
        "qargi lead grant and revoke are interactive instead: you confirm each step at the terminal, and that is the approval."]),
    "naming": ("How resources are named", [
        "Project and role are single lower-case tokens. An instance is <project>-<role>, for example acme-build. A session is "
        "<instance>-<task-slug>, and the agent's branch is agent/<task-slug>.",
        "Cloud resources follow <project>-<component>[-<role>]: the agent <project>-<role> (acme-build), the deployment "
        "<project>-deployment-<role>, the shared <project>-environment, and the stores <project>-memory and <project>-reference. "
        "The lead is <project>-lead, and so is its agent.",
        "qargi instances normalize renames existing resources to match."]),
    "memory": ("The two memory stores", [
        "<project>-memory is where agents write verified how-to facts they learn, under their own role folder (shared/ is curated and reached by promotion). <project>-reference is read-only: rules, workflow and "
        "conventions you and the coordinator curate. Both have shared/ for every role and roles/<role>/ for one.",
        "An agent reads each store's README.md, then shared/INDEX.md and its role's index, then only the notes its task needs. "
        "The canon (qargi canon) fixes the layout and the note format. Read one note with qargi memory get.",
        "qargi memory split, merge and copy move notes between two stores (directories, .jsonl dumps or store ids). Nothing is deleted: "
        "what leaves a store is archived under /_archive/<date>/, a collision goes to /_conflicts/<date>/, and the origin of every "
        "note written is added to its Sources: line."]),
    "push": ("Who may push", [
        "Only the lead ever pushes, never a member, and only as the project's lead.push grant says. The default is nothing.",
        "This Claude Code session as lead: lead.push.local lets it push agent/* branches and open pull requests without asking each time.",
        "A cloud lead, or one started in the console: lead.push.cloud = branches. It has a GitHub tool with a fixed allowlist and the merge "
        "tool asked of you. Set it up with qargi lead grant. A merge or a release always needs your explicit approval.",
        "The GitHub tool cannot create releases; those stay with this session."]),
    "files": ("Where things are", [
        "Configuration: ~/.qargi/config: projects/, instances.json, profiles/, packs/, credentials/, install.json.",
        "State: ~/.qargi/state: sessions.json, local-runs.jsonl, audit.log, runs/, backups/, provision/.",
        "Overrides: QARGI_HOME replaces ~/.qargi; QARGI_CONF and QARGI_STATE replace the two directories and win over it. XDG_CONFIG_HOME and XDG_STATE_HOME are not used "
        "(the earlier layout under them is copied by qargi migrate home; until then qargi stops and says so). QARGI_PROJECT names the project when you are not inside its repository. QARGI_ROLES replaces the list of roles. "
        "QARGI_DRY_RUN prints a session request with secrets masked instead of sending it.",
        "Nothing is stored in a repository."]),
    "dev": ("Running a branch checkout", [
        "install.sh --user records the tool it installed in ~/.qargi/config/install.json. A checkout run from any other place (its own bin/qargi, "
        "for example in a worktree) is then a dev run: it keeps its configuration and state in <checkout>/.qargi (ignored by version control), prints "
        "'qargi: dev run from ...' on stderr once per command, and never touches your live data. Without install.json every checkout is the installed one.",
        "QARGI_HOME, QARGI_CONF or QARGI_STATE, when set, win: QARGI_HOME=~/.qargi makes a dev run use live data on purpose.",
        "help, version, completion, the guard and the run-event hooks print no banner. Members call qargi __guard from PATH, which is the installed "
        "copy; put <checkout>/bin first on PATH to test the guard or the hooks of a branch."]),
}

ENVIRONMENT = [
    ("QARGI_HOME", "the directory that holds config/ and state/ (default ~/.qargi; a dev run: <checkout>/.qargi, see qargi help dev)"),
    ("QARGI_CONF", "the configuration directory (default $QARGI_HOME/config); wins over QARGI_HOME"),
    ("QARGI_STATE", "the state directory (default $QARGI_HOME/state); wins over QARGI_HOME"),
    ("QARGI_RUNS_ROOT", "a directory to scan for local run directories (qargi.*) in qargi report, besides the registry"),
    ("QARGI_PROJECT", "the project to use when the current directory is not inside its repository"),
    ("QARGI_ROLES", "the list of work roles (default: build review write test)"),
    ("QARGI_DRY_RUN", "print a session request, with secrets masked, instead of sending it"),
    ("NO_COLOR", "turn off bold in the terminal help"),
]

FILES = [
    ("~/.qargi/config/projects/NAME.json", "the answers about a project"),
    ("~/.qargi/config/instances.json", "the registry of instances"),
    ("~/.qargi/config/profiles/NAME.md", "a repository's gates and review rules, given to agents with a task"),
    ("~/.qargi/config/packs/", "the library of skills and tools, and their links"),
    ("~/.qargi/config/credentials/", "token files, mode 600"),
    ("~/.qargi/config/install.json", "the tool root install.sh recorded; a checkout run from elsewhere is a dev run"),
    ("~/.qargi/state/sessions.json", "the tracker of cloud sessions"),
    ("~/.qargi/state/audit.log", "append-only record of every approved or cloud verb, with your words"),
    ("~/.qargi/state/runs/", "collected outputs of runs"),
]

WORKFLOW = [
    ("Once per project", ["qargi project template acme > acme.json   # edit it", "qargi project init acme --answers acme.json",
                          "qargi provision plan acme-build    # then apply it with --plan and --approved"]),
    ("One task, cloud", ['qargi send acme-build "$BRIEF" --label rename-verb --asked "use the cloud builder"',
                         "qargi watch SID    # in the background", "qargi collect SID ./run", "qargi review check ./run"]),
    ("A team", ["qargi team brief acme code-docs --task \"rename the verb\" --done \"make test\" --base develop",
                "qargi lead status acme", "qargi team check ./run"]),
]
