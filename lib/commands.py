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
MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
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
PREFIX = opt("--prefix", "pick the notes under this path (repeat for several)", "PATH")
ROLE_SEL = opt("--role", "pick the notes under /roles/ROLE/", "ROLE", ROLES)
NOTE_KIND = opt("--note-kind", "pick the notes whose Kind: header is KIND (setup, gate, rule, ...)", "KIND")
POLICY = opt("--policy", "what to do when a note differs: conflicts (put the incoming one in /_conflicts/<date>/, default) or keep (leave it and report)", "POLICY", ("conflicts", "keep"))
KIND = opt("--kind", "which store: memory or reference (default: both)", "KIND", ("memory", "reference"))

GROUPS = [
    ("Set up", ["project", "agent", "provision", "instances", "skill", "tool", "packs", "discover"]),
    ("Run a task", ["start", "send", "status", "report", "watch", "collect", "stop", "close", "mark", "track", "local", "supervise"]),
    ("Review and apply", ["review", "team"]),
    ("Memory", ["memory", "canon"]),
    ("Lead and credentials", ["lead", "credential", "hook"]),
    ("Export and import", ["export", "import", "migrate"]),
    ("Other", ["help", "version"]),
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
                 "abilities it serves: build, write, review, test (all four by default). Each ability is a skill (qargi-build, "
                 "qargi-write, qargi-review, qargi-test) the member loads when the task block names it. Review is read-only as a "
                 "rule: the guard refuses changes to the clone under that ability. Dispatch spawns the member qargi agent for "
                 "ABILITY prints."),
        "scripts": ["agent.sh"],
        "verbs": {
            "add": verb("Create a member under a name you choose", [("NAME", "none")],
                        [opt("--abilities", "comma-separated abilities it serves (default build,write,review,test)", "LIST", ABILITIES),
                         opt("--model", "model alias or id for the definition (default sonnet)", "MODEL", "model"),
                         opt("--effort", "effort level, recorded with the member", "LEVEL", EFFORTS),
                         opt("--project", "put it in that project's repository (.claude/agents, hidden from git) instead of ~/.claude/agents", "PROJECT", "project")],
                        desc="Refuses a name that exists, a name that is not kebab-case, and the name of a built-in Claude Code agent type.",
                        examples=["qargi agent add forge --abilities build,test", "qargi agent add scribe --abilities write --model opus",
                                  "qargi agent add worker    # one member for all four abilities"]),
            "list": verb("List the members, their abilities and definitions"),
            "rename": verb("Rename a member and its definition", [("OLD", "member"), ("NEW", "none")]),
            "remove": verb("Delete a member's definition and its record", [("NAME", "member")]),
            "for": verb("Print the member that serves an ability", [("ABILITY", ABILITIES)],
                        [opt("--project", "prefer that project's own members (default: the project of the current directory)", "PROJECT", "project")],
                        desc="The first member registered for the ability; a project's own members come first. Dispatch spawns this one."),
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
                 "any later change is drift until you seal it again."),
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
        "summary": "Render or apply the skills and tools a role gets",
        "scripts": ["packs.sh"],
        "verbs": {
            "render": verb("Write what a role gets into a directory (used by provisioning)", [("PROJECT", "project"), ("ROLE", "role"), ("OUTDIR", "dir")]),
            "apply": verb("Update an existing cloud agent with its skills and tools", [("INSTANCE", "instance")], [ASKED, PLAN, APPROVED],
                          desc="The lead's GitHub tool arrives this way when the project grants a cloud push."),
        },
    },
    "start": {
        "summary": "Start a standby cloud session for an instance",
        "desc": "Cloud only, and only when your request names it. The session's spend ceiling comes from the deployment.",
        "scripts": ["session.sh"],
        "usage": [("NAME", "instance:cloud")],
        "opts": [opt("--label", "a task slug for the session title", "SLUG"), ASKED],
    },
    "send": {
        "summary": "Send a task to an idle cloud session",
        "desc": ("The text is the whole brief: TASK, DONE (a command whose exit status decides it), BASE, SCOPE and so on. The session "
                 "is titled <instance>-<label>; use the same slug for the agent/<slug> branch."),
        "scripts": ["session.sh"],
        "usage": [("NAME", "instance:cloud"), ("TASK", "none")],
        "opts": [opt("--label", "the task slug (required)", "SLUG"), opt("--session", "send to this session", "SID", "session:idle"),
                 opt("--new", "start a new session first"), ASKED],
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
        "usage": [("SID", "session:active"), ("STATE", ("applied", "rejected", "pending"))],
    },
    "track": {
        "summary": "Track a session that was started elsewhere (for example in the console)",
        "scripts": ["session.sh"],
        "usage": [("NAME", "instance:cloud"), ("SID", "none")],
        "opts": [ASKED],
    },
    "local": {
        "summary": "Prepare and verify a local run that has no way to push",
        "desc": ("The agent works in a clone of a bare copy that has no remote, runs git through a credential-less wrapper, and "
                 "verify compares every ref of the real repository before and after. It is a guard, not a sandbox."),
        "scripts": ["local.sh"],
        "verbs": {
            "prepare": verb("Make the clone and the wrapper for a local agent", [],
                            [opt("--repo", "the local repository", "DIR", "dir"), opt("--repo-url", "clone a private repository from this URL", "URL"),
                             opt("--credential-file", "token file for --repo-url", "FILE", "file"), opt("--base", "the base branch", "BRANCH", "branch"),
                             opt("--slug", "the task slug (branch agent/<slug>)", "SLUG"), opt("--scratch", "where to put the run", "DIR", "dir"),
                             opt("--ability", "the task's ability, written to RUN/ability; under review the guard keeps the clone unchanged (default build)", "ABILITY", ABILITIES)]),
            "verify": verb("Compare the repository's refs with the snapshot taken by prepare", [("RUN_DIR", "dir")]),
        },
    },
    "review": {
        "summary": "Check what an agent returned",
        "scripts": ["review_check.py"],
        "verbs": {
            "check": verb("Check a run: numbered patches, messages, manifest, groups", [("RUN_DIR", "dir")],
                          [opt("--allow-empty", "accept a manifest with no commits (a team member that was blocked or had nothing to change)")],
                          desc=("Refuses a monolithic patch, a commit without a message body and a manifest that does not match the patches. "
                                "A review run passes with a report.md that has a Findings section instead of patches.")),
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
        "summary": "Check a memory store, read a note, split, merge or copy stores",
        "desc": ("split, merge and copy work between two stores, each a directory of notes, a .jsonl dump (read-only: a source, never a "
                 "target) or a memstore_ id. A note with a name starting with a dot, or that a store cannot hold, makes the plan refuse and name it. Nothing is "
                 "deleted: what a split moves out of a store goes to /_archive/<date>/ and a collision to /_conflicts/<date>/, and the "
                 "origin of every note written is added to its Sources: line, so each change can be undone. Without --approved they "
                 "print the plan and its token and change nothing; a store whose notes changed since the plan is refused."),
        "scripts": ["memory.sh"],
        "verbs": {
            "lint": verb("Check a store against the canon", [("STORE_ID", "store")], [opt("--kind", "recipes or reference (for a store before the canon)", "KIND", ("recipes", "reference"))]),
            "get": verb("Print one note", [("STORE_ID", "store"), ("PATH", "none")], examples=["qargi memory get memstore_01ABC /shared/INDEX.md"]),
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
                 "reaches with the plan shown first. Nothing found online is installed on trust."),
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
        "desc": ("roles renames what was made with the role names dev and docs (now build and write) and the four fixed local "
                 "agents (now members you name): on this machine the registry, tracker, project answers, pack links and saved "
                 "definitions; in every project's two memory stores the role folders and the role names in indexes, README and "
                 "marker; in the cloud the agents and deployments, named as qargi instances normalize names them, and their "
                 "prompts, rebuilt as refresh-prompt does; and the old agent symlinks, replaced by members (qargi agent add). "
                 "Without --apply it prints the plan, with every cloud call, and a plan token. It is re-runnable: what is renamed "
                 "already is left out, and it stops at the first failure."),
        "scripts": ["migrate.py"],
        "verbs": {
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
        "Roles are the four abilities and the lead: build changes code, write writes the operational docs, review judges a change and changes no file, test writes and runs tests, lead coordinates a team. Each ability is defined by a skill (qargi-build, qargi-write, qargi-verify, qargi-test). The local workers are members you name and give abilities (qargi agent add NAME --abilities build,test); qargi agent for ABILITY prints the member that serves it. "
        "A role has its own model, effort, skills and packages, stored in the project's answers.",
        "Local or cloud: local (a Claude Code subagent) is the default. The cloud is used only when your request for that task names it, "
        "and every cloud verb records your words with --asked.",
        "You decide: the coordinator re-verifies everything an agent returns (qargi review check), applies it as separate commits, and "
        "asks you before anything is pushed."]),
    "roles": ("Roles, abilities, skills and members", [
        "Role build: the ability build, defined by the skill qargi-build; changes the code with its tests, manual page, help and changelog.",
        "Role write: the ability write, skill qargi-write; writes the operational documentation on its own branch.",
        "Role review: the ability review, skill qargi-review; reads a change, runs its checks and reports a verdict, and changes no file.",
        "Role test: the ability test, skill qargi-test; writes and repairs tests and proves them failing first and stable.",
        "Role lead: no ability of its own; it coordinates a team of members on one task (qargi team, the skill qargi-team).",
        "A member is a local agent you name (qargi agent add forge --abilities build,test), rendered from the one member definition "
        "qargi ships. The task block names the ability and its skill; the member loads it. qargi agent for ABILITY prints the member "
        "dispatch spawns. A cloud agent serves one role, is named <project>-<role> and carries its ability's skill in its prompt.",
        "Earlier installations (roles dev and docs, the agents qargi-dev, qargi-docs, qargi-review, qargi-test) move with qargi migrate roles."]),
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
        "<project>-memory is read-write for agents: verified how-to facts they learn. <project>-reference is read-only: rules, workflow and "
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
        "Configuration: $XDG_CONFIG_HOME/qargi (default ~/.config/qargi): projects/, instances.json, profiles/, packs/, credentials/.",
        "State: $XDG_STATE_HOME/qargi (default ~/.local/state/qargi): sessions.json, local-runs.jsonl, audit.log, runs/, backups/, provision/.",
        "Overrides: QARGI_CONF and QARGI_STATE replace those two directories. QARGI_PROJECT names the project when you are not inside its repository. QARGI_ROLES replaces the list of roles. "
        "QARGI_DRY_RUN prints a session request with secrets masked instead of sending it.",
        "Nothing is stored in a repository."]),
}

ENVIRONMENT = [
    ("QARGI_CONF", "the configuration directory (default $XDG_CONFIG_HOME/qargi)"),
    ("QARGI_STATE", "the state directory (default $XDG_STATE_HOME/qargi)"),
    ("QARGI_RUNS_ROOT", "a directory to scan for local run directories (qargi.*) in qargi report, besides the registry"),
    ("QARGI_PROJECT", "the project to use when the current directory is not inside its repository"),
    ("QARGI_ROLES", "the list of work roles (default: build review write test)"),
    ("QARGI_DRY_RUN", "print a session request, with secrets masked, instead of sending it"),
    ("NO_COLOR", "turn off bold in the terminal help"),
]

FILES = [
    ("$XDG_CONFIG_HOME/qargi/projects/NAME.json", "the answers about a project"),
    ("$XDG_CONFIG_HOME/qargi/instances.json", "the registry of instances"),
    ("$XDG_CONFIG_HOME/qargi/profiles/NAME.md", "a repository's gates and review rules, given to agents with a task"),
    ("$XDG_CONFIG_HOME/qargi/packs/", "the library of skills and tools, and their links"),
    ("$XDG_CONFIG_HOME/qargi/credentials/", "token files, mode 600"),
    ("$XDG_STATE_HOME/qargi/sessions.json", "the tracker of cloud sessions"),
    ("$XDG_STATE_HOME/qargi/audit.log", "append-only record of every approved or cloud verb, with your words"),
    ("$XDG_STATE_HOME/qargi/runs/", "collected outputs of runs"),
]

WORKFLOW = [
    ("Once per project", ["qargi project template acme > acme.json   # edit it", "qargi project init acme --answers acme.json",
                          "qargi provision plan acme-build    # then apply it with --plan and --approved"]),
    ("One task, cloud", ['qargi send acme-build "$BRIEF" --label rename-verb --asked "use the cloud builder"',
                         "qargi watch SID    # in the background", "qargi collect SID ./run", "qargi review check ./run"]),
    ("A team", ["qargi team brief acme code-docs --task \"rename the verb\" --done \"make test\" --base develop",
                "qargi lead status acme", "qargi team check ./run"]),
]
