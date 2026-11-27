"""The description of the qargi command line: the single source of the terminal help, the man page and
the bash completion. tests/test_help.py checks it against the scripts, so a flag or a verb that is added
without being described here fails the suite.

A verb is  verb(summary, args=[(NAME, type[, optional])], opts=[opt(...)], desc=..., examples=[...])
Argument and option value types drive completion: project (left out inside the project's repository; project:named is always given, as
the verbs that remove a project take it), instance, team, role, session, pack-skill,
pack-tool, member, file, dir, none, or a tuple of fixed words."""

TAGLINE = "A gathering place for agent work: dispatch, review, remember."

INTRO = (
    "qargi dispatches one-off, task-scoped development tasks to agents and takes the work back as "
    "reviewable patches. An agent is a member on this machine (local, the default) or a "
    "cloud agent (only when you ask for it in that request). Members are instructed to work in their own clone and "
    "return patches without pushing. Lead push grants are separate (qargi help push). A team adds a lead that "
    "coordinates members for build, write and review on one task. User installations default to ~/.qargi for "
    "configuration and state. Paths are configurable, and development mode uses checkout-local .qargi (qargi help dev). "
    "Inside a project's repository you can leave out its name."
)

ROLES = ("build", "write", "review", "test", "lead")
ABILITIES = ROLES[:-1]   # the work roles; each is defined by roles/<role>/ROLE.md
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _provider_models():
    """The model ids and aliases of the shipped runtimes (lib/provider.py, their catalogs followed), for completion."""
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import provider as P
    out = []
    for n in P.names(P.PROVIDERS):
        try:
            rows = list(P.models_of(n, root=P.PROVIDERS)["tiers"].values())
        except P.ProviderError:
            continue
        out += [r["model"] for r in rows] + [r.get("alias") for r in rows]
    return tuple(dict.fromkeys(m for m in out if isinstance(m, str)))


def __getattr__(name):
    """MODELS is read from the runtime descriptors the first time it is asked for (completion of a model value), not at import:
    every qargi command imports this table before it runs, and reading the descriptors is the costly part."""
    if name == "MODELS":
        globals()["MODELS"] = _provider_models()
        return globals()["MODELS"]
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def opt(flag, help, arg=None, type="none"):
    return {"flag": flag, "arg": arg, "help": help, "type": type}


def verb(summary, args=(), opts=(), desc="", examples=()):
    return {"summary": summary, "args": [tuple(a) + (False,) if len(a) == 2 else tuple(a) for a in args],
            "opts": list(opts), "desc": desc, "examples": list(examples)}


HOOK_REC = ("Reads the hook's JSON on stdin and appends one small line to the run's event file under the state directory "
            "(ids, times, names and hashes; never command, message or error text). It always exits 0 at once, even on malformed input, "
            "so it cannot block an agent. Register it with qargi supervise hooks.")
ASKED = opt("--asked", "your request, in your words, naming the cloud instance for this operation", "REQUEST")
WORKTREE = opt("--worktree", "write the repo tier into DIR, another worktree of the project's repository (the same path inside it), instead of its checkout; the plan says on which branch to commit it", "DIR", "dir")
RUNTIME_GATE = opt("--runtime", "the extra local runtime to allow or stop for the project (models.extra_runtimes.local), in place of an extension", "NAME")
OPTION_GATE = opt("--option", "with --runtime: a run option of that runtime's definition (dispatch.run_config.options) to enable or stop for the project (models.run_options.local.RUNTIME), in place of the runtime itself", "OPTION")
ASKED_WORDS = opt("--asked", "your request, in your words (with --runtime)", "WORDS")
PLAN = opt("--plan", "the plan token printed by the same command without --approved", "TOKEN")
APPROVED = opt("--approved", "your go-ahead for exactly that plan, in your words", "WORDS")
DRY = opt("--dry-run", "print what the apply would do and change nothing: the plan with its token, then each refusal the apply would meet, ending with 'dry-run: N would refuse; nothing was changed'")
DRY_NOTE = ("--dry-run changes nothing: no ref, no push, no pull request, no audit line, no lock and no file in the state directory (QARGI_DRY=1 inside the verb: a helper that writes, "
            "or a git or gh command that is not a read, stops it with exit 70, a defect of the verb). It prints the plan with the same token the plain plan has, and ends with 'invalidated by: ...', "
            "the labels of the plan (what changing any of them makes the token stale). Given --plan TOKEN it also says what the apply would meet: the token is compared with the plan as it is now "
            "(plan-stale names the labels that moved), and each other refusal is printed in the normal format of a refusal, with dry=1 first in the detail of the contract line; the first refusal "
            "stops it, as it would the apply, except a check that is independent of the others, which is listed and the run goes on, so several may be shown. Origin is asked with git ls-remote "
            "and never fetched (the plan says 'not fetched'). The last line of standard output is 'dry-run: N would refuse; nothing was changed', and the exit status is what the apply would exit with: 0, "
            "or 1 when N is not 0. Ask it just before asking the owner: a token dies when what it hashed changes.")
EXEC = opt("--approve-exec", "name every executable the pack holds, separated by commas, to approve running them", "NAMES")
LOCAL_TARGET = opt("--target", "session.render_target of an eligible local runtime; omitted selects the project's member runtime", "TARGET")
TARGET = opt("--target", "claude-code renders for a local session; any eligible local session.render_target is supported; managed-agents (the default for apply) is the cloud update", "TARGET", ("claude-code", "managed-agents"))
PREFIX = opt("--prefix", "pick the notes under this path (repeat for several)", "PATH")
ROLE_SEL = opt("--role", "pick the notes under /roles/ROLE/", "ROLE", ROLES)
NOTE_KIND = opt("--note-kind", "pick the notes whose Kind: header is KIND (setup, gate, rule, ...)", "KIND")
POLICY = opt("--policy", "what to do when a note differs: conflicts (put the incoming one in /_conflicts/<date>/, default) or keep (leave it and report)", "POLICY", ("conflicts", "keep"))
KIND = opt("--kind", "which store: memory or reference (default: both)", "KIND", ("memory", "reference"))

REASONS = ("wrong-scope", "broke-check", "style", "too-slow", "too-costly", "skill-ignored", "skill-wrong", "brief-unclear", "gate-noise", "other")

# Options every verb takes, handled once by bin/qargi (lib/jsonplan.py), not by the verb. A verb that documents an option of the same name keeps it.
GLOBAL_OPTS = [opt("--json", "print the result as one JSON object with the verb, the plan, the token, the command that applies it and the exit status "
                             "(the output instead, when the verb printed no plan token); never supplies --plan or --approved")]

PROJECT_OPT = opt("--project", "the project, instead of the one inferred from here", "PROJECT", "project")
MEMBER_PROJECT_OPT = opt("--project", "the project the member belongs to (default: the one in effect when it has the member, else the only project that has it)", "PROJECT", "project")
AS_OPT = opt("--as", "act as this lead identity (default: the identity in QARGI_LEAD, else the anonymous user@host)", "ID")
FLOW_UNREACHABLE_OPT = opt("--assume-unreachable-ok", "go on although the shared marshal cannot be asked because its remote cannot be reached (without it that is a refusal, exit 3, nothing changed); recorded as marshal:unreachable-ok in the audit log")
FLOW_UNREACHABLE_NOTE = ("It asks the marshal first. With the shared refs backend a remote that cannot be reached is a refusal (exit 3, nothing changed; the message says what could not be reached and why) "
                         "unless --assume-unreachable-ok is given: then it goes on and the audit log gets a marshal:unreachable-ok line. A project whose marshal is local is not affected.")
UNREACHABLE_OPT = opt("--assume-unreachable-ok", "go on although the remote of the shared records cannot be reached (a claim stays provisional, a check answers from the cache); recorded as marshal:unreachable-ok in the audit log")
NOWRITE_OPT = opt("--no-write", "write nothing and fetch nothing: no record marked abandoned (a record whose branch is gone is still shown abandoned, as the writing call answers, but not stored), no audit line, no cache of the shared records updated, and no directory or file made, not even by the first load (it implies --no-fetch; the document of --json then says remote not-asked)")
RESOLVED_OPT = opt("--resolved", "use the merge you resolved and committed in the conflict worktree")
REMOTE_NOTE = ("It asks the live origin with git ls-remote (QARGI_REMOTE_TIMEOUT seconds, default 10) where the branches are, not the last fetch, "
               "and says 'remote not checked' when origin cannot be reached.")
SUITE_FAIL_NOTE = ("The output of the suite is kept in STATE/suite-logs/PROJECT.feature-NAME.log (PROJECT.release-VERSION.log for a release; the last run of each). When "
                   "the suite fails, the last lines of the output are the failing steps and tests that its report names, where the runner kept the logs of the failed steps, and the path of that log. "
                   "Any gate or test command may print the lines that are named, at the start of a line: a failing step is a line matching ^FAILED: (the step follows); a failing test is a line "
                   "matching ^FAIL( |:) or ^--- FAIL: (the name follows; the second is a Go test run's); the logs of the failed steps are a line ^logs of the failed steps: (the directory follows). "
                   "A command that prints none shows its last lines instead.")
WAIVE_ENV_OPT = opt("--waive-environment", "run once without these parts of verify.environment, which a refusal named (comma separated: signals, fds, tty, cpu; never env); needs --plan and --approved", "PARTS")
VERIFY_ENV_ANSWER = ("verify.environment (an object, or null for off) is the environment the whole-suite runs of feature verify and release verify start under: "
                     "fds (close or ci-like), ci_fds, cpu_quota (null, max or N%), env_pass (names taken from the caller) and env_set (names and values); an invalid declaration refuses with verify-env-invalid and the line that is wrong. "
                     "qargi keeps the declaration it last accepted in the state, apart from the answers. A first declaration, and a lower cpu_quota (from null, from max, or from a higher N%), apply at once; "
                     "every other change (removal, a higher quota, any change of fds, ci_fds, env_pass or env_set) loosens the environment and refuses with verify-env-change-unapproved and a plan token: "
                     "the same command with --plan TOKEN --approved WORDS (the owner's words) applies it and writes the audit line project:verify-environment-loosened. "
                     "A member's guard refuses it, and a member run refuses it with exit 2: the token is printed to whoever asks, so the owner's words are the only approval.")
VERIFY_ENV_UNSET = ("Removing verify.environment (or verify) turns the environment off, which loosens it: it refuses with verify-env-change-unapproved and a plan token unless --plan TOKEN --approved WORDS is given "
                    "(the owner's words), and then writes the audit line project:verify-environment-loosened; the two options apply to verify and the keys below it only.")
ENV_NOTE = ("With the project answer verify.environment set, the suite, or each declared gate, starts through the launcher lib/suite_env.py, from a known state like a hosted runner's: "
            "default signal dispositions and an empty mask, only the descriptors the declaration allows, a session of its own with no terminal (the output goes to the log), "
            "a transient cgroup below qargi-verify.slice with the cpu controller on, and an environment built from an allowlist; each is read back. The verb makes the launcher's attempt before it makes the worktree. "
            "A part that cannot be applied refuses the run (exit 1, nothing run, nothing recorded) with a code (verify-env-signals, verify-env-fds, verify-env-tty, verify-env-cpu-no-systemd-run, verify-env-cpu-systemd-too-old, "
            "verify-env-cpu-no-user-manager, verify-env-cpu-readback), the part, what was found and a plan token; the same is printed for a part the launcher refuses during the run. "
            "A suite log or a directory for the reports that cannot be made is verify-env-no-log (exit 1, nothing run, no part and no token; under a waiver the log is made after the waiver is claimed, so the token is spent and the audit line is written). "
            "--waive-environment PARTS --plan TOKEN --approved WORDS runs the suite once without the parts a refusal named: only a refusal yields a token, which covers the project, the branch, its head, the declaration and exactly those parts, "
            "and is good for one run at that head (used again: verify-env-waive-used). A waived part is still attempted; when it fails it is recorded waived-failed with its code, the verdict line says so "
            "(full suite: pass at SHA (verify.environment: cpu waived-failed)) and status and finish show it again; the run is audited as verify:environment-waived. "
            "A setting that is off, a part that is off, env or another word is verify-env-waive-unknown; no token or words, or a token of other parts or another head, is verify-env-waive-unapproved. "
            "The words are the owner's: in a member run --waive-environment with --approved is refused (exit 2). A declaration in the answers that is not the one last accepted refuses with verify-env-change-unapproved. "
            "Without the answer nothing changes and there is nothing to waive.")
GATES_NOTE = ("Declared gates: the project answer gates is an ordered list of {name, command, tier} (command: a command line or a list of words, as test_command; tier: feature or release; names unique). "
              "Absent, test_command (release.test_command for a release) is run, as before. Declared, the gates run instead and test_command is not also run (a gate whose command is the same runs it): "
              "feature verify runs the gates of tier feature in order and release verify the feature tier, then the release tier, each stopping at the first failure (the rest are listed as not run). "
              "The verdict line is still 'full suite: pass|fail at SHA', and the run record and the status lines list each gate with its result. "
              "A gate may also list ci_jobs, the CI jobs (names or ids) that run its check under another name: the CI scan of release verify reports them as covered by the gate. "
              "A feature gate may name a release gate in covered_by when that gate's command runs the same check: release verify then lists the gate as covered by it and does not run it "
              "(its result is 'covered by NAME' when NAME passed, 'not run' when NAME failed or was not reached); feature verify still runs it. The name must be a release gate.")
OTHER_RUNS_NOTE = ("Before it starts it warns on standard error, and goes on, when another suite may be running: a whole-suite run of the project in progress, a local run "
                   "of the repository with a file changed in the last QARGI_ACTIVE_MINUTES minutes (default 10), or a tests/run.sh process in the repository (Linux).")
TAG_NOTE = ("When the tag VERSION exists it also warns about a tag that has no GitHub release (asked with a read-only gh release view, through QARGI_GH, default gh; "
            "a gh that is missing or not logged in is a note) and about a tagged commit that lacks .github/workflows/release.yml while the branch has it, because "
            "a pushed tag starts that workflow only when its own commit contains it. Warnings and notes never fail the verb.")
HOTFIX_OPT = opt("--hotfix", "a hotfix: branch from master, finish into master and the open release branch (or develop)")

GROUPS = [
    ("Set up", ["project", "methodology", "cloud", "agent", "role", "provider", "provision", "env", "doctor", "instances", "skill", "tool", "packs", "discover"]),
    ("Run a task", ["feature", "marshal", "release", "branch", "changelog", "upstream", "backlog", "campaign", "ref", "start", "send", "status", "report", "noticed", "plan", "watch", "collect", "stop", "close", "mark", "track", "local", "supervise"]),
    ("Review and apply", ["review", "team"]),
    ("Memory", ["memory", "canon"]),
    ("Lead and credentials", ["lead", "credential", "hook"]),
    ("Export and import", ["export", "import"]),
    ("Other", ["upgrade", "help", "version"]),
]

COMMANDS = {
    "project": {
        "summary": "Store the answers about a project, once, outside the repository",
        "desc": ("The answers are the repository, its long-lived branches, the roles that exist (build, write, review, test) "
                 "with each role's base branch, model, effort, packages and skills, the memory stores, the budget, and "
                 "optionally a lead with teams and a push grant. Provisioning and dispatch read them. Push policy per role "
                 "is none for members: they are instructed to return patches without pushing. The lead's grant is separate (qargi help push)."),
        "scripts": ["project.sh"],
        "verbs": {
            "template": verb("Print an answers file with defaults", [("NAME", "none")], [opt("--methodology", "the methodology the answers follow (default gitflow, which adds no methodology answer)", "NAME", "methodology")],
                             desc="Edit it, then store it with init. models.provider is empty and must be set (the provider the project's agents run on; there is no default); project validate reports it while it is not. No role names a model: it takes the provider's tier once one is set. With --methodology the answers carry its name, its long-lived branches (plain: main only, not master and develop) and the bases of its roles; a methodology that does not pass qargi methodology check is refused. project validate refuses a methodology answer that does not pass it either.",
                             examples=["qargi project template notes --methodology plain > notes.json"]),
            "init": verb("Validate and store an answers file", [("NAME", "none")],
                         [opt("--answers", "the answers file to store", "FILE", "file"), opt("--force", "replace stored answers")],
                         examples=["qargi project template acme > acme.json", "qargi project init acme --answers acme.json"]),
            "new": verb("Start a new project: its directory, a git repository on the methodology's branches and generic files", [("NAME", "none")],
                        [opt("--methodology", "the methodology (default gitflow; plain for a project whose output is documents)", "NAME", "methodology"), opt("--dir", "where to create it (default ./NAME; must be absent or empty)", "DIR", "dir"),
                         opt("--param", "a methodology parameter as name=value (repeat), for example test_command; gates=JSON declares gates, which are stored in the answers too when --url is given", "NAME=VALUE"),
                         opt("--url", "the repository URL; with it the qargi answers are stored too", "URL"),
                         opt("--deployment", "a deployment option to record and explain (see qargi methodology deployment)", "ID"),
                         opt("--provider", "the provider the project's agents run on (models.provider, with its models); not stored when omitted (qargi provider list)", "NAME"),
                         opt("--provider-local", "the runtime of the local surface (models.provider.local); use it with --provider-cloud instead of --provider", "NAME"),
                         opt("--provider-cloud", "the runtime of the cloud surface (models.provider.cloud)", "NAME"), PLAN, APPROVED],
                        desc=("Prints the plan (directory, branches, files, deployment options with instructions) and a token; with --plan and --approved it creates the "
                              "directory, runs git init, writes the generic files in a first commit and creates the long-lived branches. With --url (the answers are stored) a --provider or --provider-local runtime that does not confine reads (a command runtime whose definition has no dispatch.reads that confines them) adds the warning line members on NAME can read ... reads are not confined to the plan; it asks for no phrase. Nothing is pushed and no remote "
                              "is created: say where it goes with git. The files mention no tool of yours. They include an AGENTS.md with a Development environment section and a Makefile "
                              "with stub bootstrap and doctor targets (the doctor fails until you fill it in); see qargi help environment. With --methodology plain the repository has the one branch main and holds README.md, CONTRIBUTING.md, AGENTS.md, artifacts/ and BACKLOG.md: no develop, no VERSION, no changelog, no CI and no Makefile (the answers stored with --url name BACKLOG.md as the backlog file). --json prints the plan and its token as one object; the token approves the same plan."),
                        examples=["qargi project new acme --param test_command='make test'", "qargi project new acme --dir ~/src/acme --url https://github.com/me/acme", "qargi project new notes --methodology plain --url https://github.com/me/notes"]),
            "attach": verb("Attach to an existing repository: read it, show the answers and the gaps, store on approval", [("[DIR]", "dir")],
                           [opt("--name", "the project name (default: from the remote or the directory)", "NAME"),
                            opt("--methodology", "the methodology to compare with (default gitflow)", "NAME", "methodology"),
                            opt("--url", "the repository URL, when it has no origin remote", "URL"),
                            opt("--provider", "the provider the project's agents run on (models.provider, with its models); not stored when omitted (qargi provider list)", "NAME"),
                         opt("--provider-local", "the runtime of the local surface (models.provider.local); use it with --provider-cloud instead of --provider", "NAME"),
                         opt("--provider-cloud", "the runtime of the cloud surface (models.provider.cloud)", "NAME"),
                            PLAN, APPROVED, opt("--force", "replace the detected answers, keep the rest")],
                           desc=("Reads the repository (branches, tags, version and changelog files, test command, CI) and changes nothing in it. Prints the answers it "
                                 "would store, the gaps against the methodology and what it could not determine, and a plan token. With --plan and --approved it "
                                 "stores the answers outside the repository. The safe gaps are closed by qargi project adopt, the rest by hand. It reads the tree of the "
                                 "methodology's integration branch (develop), else of the default branch, else of HEAD, and says which; never the working tree. It prints "
                                 "origin as read and the https url it normalises to. When the stored answers declare gates it lists them after the test command line (tier, name, command, "
                                 "the feature tier first) and says they replace the detected test command. If answers are already stored it shows stored against detected, lists the fields "
                                 "the stored file lacks, stays read-only and gives no plan token; with --force the plan replaces what it detects and keeps what it "
                                 "cannot (the roles' models and effort, cloud, memory, budget). It reports what it found of the development environment (section, task runner, "
                                 "bootstrap and doctor commands; a command the stored answers declare in env.* is in effect) and lists the pieces that are missing as gaps. A declared setting or a "
                                 "versioned unreleased heading right after a release is printed apart, as noted, not a gap. The lead's accepted deviations (the answer methodology_accepted, a list of "
                                 "{gap, reason, date}, the gap written as it is printed here: file: CONTRIBUTING.md) are printed apart from the open gaps, and one whose gap is gone says "
                                 "'accepted, no longer applies'. It never guesses a provider: models.provider (and the roles' models) are stored only with "
                                 "--provider NAME, and without it the output says so; with --force --provider fills in a provider that is not set and never replaces one. "
                                 "A runtime that does not confine reads, named with --provider or --provider-local, adds the line warning: members on NAME can read the real ~/.codex ... reads are not confined; it asks for no phrase.")),
            "adopt": verb("Adopt an attached repository: create the missing long-lived branches and the missing methodology files on a branch to review", [("NAME", "project")],
                          [opt("--methodology", "the methodology (default: the project's, else gitflow)", "NAME", "methodology"),
                           opt("--show", "also print everything the plan token covers: the refs it starts from, the branches, and the full content of each file to write (changes nothing; not with --plan)"), PLAN, APPROVED],
                          desc=("Prints the plan and a token: the local branches it would create (at the default branch tip; main stands for master; none is moved) and the files from the "
                                "methodology that do not exist, written as one commit on agent/adopt-NAME cut from develop. With --plan and --approved it creates exactly that. Existing "
                                "branches and files are never changed, nothing is pushed or checked out, and a second run finds nothing to do. Changelog format, tag format and CI content "
                                "are listed as left for you, and so are the bootstrap and doctor targets a repository with a task runner lacks (an existing file is not edited), and long-lived branches "
                                "that share no history (a master made as a snapshot has no merge base with develop): none is joined here, and the line says that release push joins the history of master. "
                                "The AGENTS.md section it drafts names the repository's own runner and only the bootstrap, dry-run and doctor commands the repository has or declares (env.* in the answers); a line for a command it lacks is left out. "
                                "The changelog sentence of the runtime's instruction file and CONTRIBUTING.md is rendered from the project's release.changelog.unreleased heading and release.changelog.numbered. A declared setting (release.version_file none) "
                                "and a versioned unreleased heading right after a release (no unreleased section yet; the last release is X) are printed apart as noted, not gaps. A repository that has AGENTS.md or the runtime's own instruction file "
                                "gets a list of what adopt does about each (it edits neither): with an instruction file of the runtime and no AGENTS.md it writes AGENTS.md with the Development environment section only, and says to add the @AGENTS.md import line to that file. "
                                "An accepted deviation (methodology_accepted: a gap named file: X or branch: X) is left out of the files and branches it would write, and printed apart from what is left for you; one whose gap is gone says 'accepted, no longer applies'. "
                                "Refused (exit 2) with a dirty working tree, a detached HEAD, no commits, a project that is not attached, and in a member run."),
                          examples=["qargi project adopt acme", 'qargi project adopt acme --plan TOKEN --approved "go ahead"']),
            "set": verb("Change one answer", [("NAME", "project"), ("PATH", "key"), ("VALUE", "value")], [PLAN, APPROVED],
                        desc=("PATH is dotted (budget_cents, roles.write.effort, lead.push), with no empty segment (a..b and a. are refused, naming the path); VALUE is JSON or a plain string. packs.member_skills uses qargi packs member-skills PROJECT --enable|--disable and refuses direct set/unset or whole packs-object replacement. models.extensions, models.extra_runtimes, models.run_options and models.accept_no_barrier are refused here: they change only through qargi provider enable|disable (an extension, a runtime with --runtime, or an option of a runtime with --runtime NAME --option OPT) and qargi provider accept. "
                              "profiles.NAME.options (a list of the options of the profile's runtime that the project enabled with qargi provider enable PROJECT --runtime NAME --option OPT) is a plain set that only selects among them; project validate refuses one that is not enabled and one on a profile of the reviewer base. "
                              "profiles.NAME.runtime (the runtime a profile's members run on: the project's own, or one enabled with qargi provider enable PROJECT --runtime NAME) is a plain set, with a hyphen allowed in the profile's name (profiles.codex-build.runtime), and a member's guard refuses it as it does roles.NAME.tools. "
                              "Setting models.provider.local (or models.provider) to a runtime that does not confine reads prints a warning line: members on NAME can read the real ~/.codex ... reads are not confined; it asks for no phrase. "
                              "methodology_accepted (a list of {gap, reason, date}: the deviations from the methodology the lead accepts) is the lead's: a member run is refused. "
                              "roles.ROLE.tools is the list of the tools a role needs beyond its apt packages, each {kind, name, ...}: kind go (name a package path, version a tag: go install NAME@VERSION), "
                              "kind binary (name the file name, version, url of the file itself, sha256 of it: downloaded to ~/.local/bin and kept only when the hash matches) and kind submodule "
                              "(name as in .gitmodules, path: checked out in each member clone by qargi local prepare). env plan lists them, env apply installs them and env check reports one that is "
                              "missing or wrong; a member's guard refuses setting them (and a whole role), as it refuses release.*, test_command, gates, env.*, upstream.*, site.*, backlog.*, ci.*, methodology_accepted, verify.environment, git.* and review.*. "
                              "backlog.file is the markdown file of the project's backlog (qargi backlog); a path outside the repository is fine. "
                              "git.author ('Name <email>') is the author qargi review apply gives the commits it applies, and review.keep_author true keeps the member's author instead; "
                              "review.scrub (a command line or a list of words) is run by qargi review check (and by qargi review apply, unless a passing check recorded the same series) on the applied series with the range in QARGI_SCRUB_BASE and QARGI_SCRUB_TIP, and review.trailer_policy reject fails a commit with a "
                              "Co-Authored-By or Generated-with trailer (none is the default); review.reject_trailers is a list of further trailer keys (letters, digits and hyphens, * for any run of them, for example "
                              "[\"Signed-off-by\", \"X-*\"]) refused under the policy reject (setting it while the policy is not reject is refused), and the failing verdict names the commit, the line of its "
                              "message and the entry that matched; a member's guard refuses setting them. "
                              "runs.owned_refs is a list of glob patterns for the refs a runtime or harness creates in the repository, which local verify and clean accept and name (see local verify); "
                              "the guard refuses it to a member too. "
                              "It prints the new value and then 'was: OLD' (the JSON the answer held, or '(not set)' when the key was absent) and writes an audit line (project:set, with the old value). "
                              "A null stored for an optional answer (git.author, gates, review.*, backlog.*) is the same as not set, and project validate accepts it; qargi project unset removes the key itself. "
                              + VERIFY_ENV_ANSWER + " --plan and --approved apply to this answer only (verify, verify.environment or a key below it); any other path refuses them (exit 2)."),
                        examples=["qargi project set acme roles.write.effort high", "qargi project set acme packs.none true", "qargi project set acme git.author 'Example Author <author@example.com>'",
                                  "qargi project set acme roles.test.tools '[{\"kind\":\"go\",\"name\":\"acme.test/ci\",\"version\":\"v1.2.0\"}]'"]),
            "unset": verb("Remove one answer", [("NAME", "project"), ("PATH", "key")], [PLAN, APPROVED],
                          desc=("PATH is dotted, as for set. Prints 'was: OLD' (the JSON the answer held) and writes an audit line (project:unset, with the old value). It refuses what set refuses: "
                                "the marshal backend (marshal.backend: qargi marshal enable|disable) and models.extensions, models.extra_runtimes and models.accept_no_barrier, also as keys of a whole models object (exit 2: "
                                "qargi provider enable|disable and qargi provider accept take a plan token and an approval). PATH may name a profile with a hyphen (profiles.codex-build.runtime). A key that is not set is an error and changes nothing, and so is the removal of an answer the "
                                "project needs (repo.url, a role's base): validate refuses it and the file is not touched. A member never runs it: it is refused in a member's run directory "
                                "or with the member mark in the environment (exit 2); propose the removal in the report. "
                                + VERIFY_ENV_UNSET),
                          examples=["qargi project unset acme backlog.file", "qargi project unset acme review.scrub"]),
            "show": verb("Print the stored answers and what they mean", [("NAME", "project")],
                         desc=("The answers go to standard output as JSON (so they can be piped). When the project declares gates, which replace the test command in feature verify and release verify, "
                               "they are listed on standard error (tier, name, command, the feature tier first).")),
            "list": verb("List the stored projects"),
            "validate": verb("Check an answers file without storing it (a WARN line for each pack linked to a role that is not in the pack library, and for a profile that still carries the shipped template header)", [("FILE", "file")]),
            "profile": verb("Check the repository's profile: the shipped template header, and gate commands the repository does not know (check)", [("SUBCOMMAND", "none"), ("NAME", "project", True)],
                            [opt("--profile", "the profile file to read (default: ~/.qargi/config/profiles/<repository>.md, the repository being the project's directory name)", "FILE", "file")],
                            desc=("Read only, so a member may run it. check reads the profile (the gates, rules and review steps of a repository, outside the repository) and prints "
                                  "FAIL for each line at the top that is still the shipped example's (the Example profile title and the Copy to line of examples/myproject/profile.md), "
                                  "exit 1; and WARN for each backticked command in its Gates section that is found in none of the repository's instruction files and Makefile targets "
                                  "(a make target of the Makefile, the command's text in one of the three files, or a script that exists), exit 0. No profile is fine (said, exit 0); "
                                  "a --profile file that is not there is exit 2. Without NAME the project is the one in effect, else the repository of the current directory. "
                                  "project validate prints the header finding as a WARN line."),
                            examples=["qargi project profile check acme", "qargi project profile check --profile ./profile.md"]),
            "link": verb("Make this work tree load the project's skills, agents and memory from ~/.qargi", [("PROJECT", "project", True)],
                         [opt("--resource", "what to link: skills, agents, memory (comma separated; default every one the runtime links and that exists)", "LIST", ("skills", "agents", "memory")), PLAN, APPROVED],
                         desc=("One plan and one token for every resource, each placed and linked the way the project's runtime says (a directory link, one link per entry, or a copy). "
                               "A real directory in the way is moved to NAME.qargi-backup, never deleted. Run it inside a work tree to link that one; nothing records which work trees exist. "
                               "A member's guard refuses it.")),
            "unlink": verb("Undo project link in this work tree and restore the backups", [("PROJECT", "project", True)], [opt("--resource", "what to link: skills, agents, memory (comma separated; default every one the runtime links and that exists)", "LIST", ("skills", "agents", "memory")), PLAN, APPROVED]),
            "remove": verb("Retire a project: remove its stored answers and its members, behind a plan", [("NAME", "project:named")], [PLAN, APPROVED],
                           desc=("Without --approved it prints the plan and a token and changes nothing. The plan lists exactly what the apply removes: the stored answers (~/.qargi/config/projects/NAME.json), "
                                 "the members of the project (what qargi agent remove takes away for each: the member file, the copy of its render under ~/.qargi/config/agents/NAME and its entry in agents.json), "
                                 "and the approved verify.environment declaration the state keeps for the project (verify-env.json), so that a project made again under the name is not compared with it. "
                                 "With --plan TOKEN and --approved WORDS it reads what could hold the removal back once more (a hold that appeared since the plan refuses the apply as the plan does, and so does a change of what the token covers) and the approved declarations, writes the audit line project:remove with the words (begun) and only then removes the members one by one, the approved declaration and the stored answers, and ends with a second line (removed). A step that fails part way leaves what was removed removed and the stored answers in place, writes a line that says after how many members it stopped, and exits 1; a new plan then lists what is left. It touches the repository only through the member files the plan lists (a runtime that keeps them in the checkout, link none, for example a member file in the runtime's agents directory: the apply deletes those files, "
                                 "and the lines qargi wrote in .git/info/exclude for them stay) and runs no git command that changes anything: no branch, no commit, no other file of the work tree. The marshal records, the audit log, the project's memory, the rendered packs and member render, and the stored plans stay (the plan lists the marshal's own files that are there, the switch file and the allowed signers, as stays lines). "
                                 "The token covers the project, the hash of the answers file, the approved declaration, the hash of the project's raw record in agents.json (so a change the plan does not print is another token) and each member, and nothing that could hold the removal back, so it stays good after a refusal. "
                                 "Refused (exit 2, nothing changed, with a plan or with an apply) when the project has no stored answers (project-remove-unknown) and while something names it that the removal would strand, each refusal "
                                 "naming the one command that clears it: an open feature (project-remove-feature; qargi feature finish), an open run of the project (project-remove-run; qargi local clean), "
                                 "a live marshal lease (project-remove-lease; qargi marshal release FEATURE --project NAME --note TEXT from the session that leads it; another lead's lease is released from that lead's session or waited out), an open release cut (project-remove-release; qargi release finish), a work tree of the repository where project link left a link "
                                 "(project-remove-linked; qargi project unlink, run in it), a cloud binding (project-remove-cloud; qargi cloud unset) and a registered instance (project-remove-instances; qargi instances remove). "
                                 "A source that exists and cannot be read holds it too (project-remove-unreadable: stored answers that are not a JSON object, git failing or too slow in the repository, a plan of project unlink that did not run, "
                                 "instances.json, the registry of runs or a directory of the state that cannot be read, or a project on the shared refs backend of the marshal, whose switch file is there and whose leases are in refs of the remote and cannot be read in the state), naming what and the one command or file to fix; a plan that says nothing holds it back has read all of them. "
                                 "When several hold it the first of those is the refusal and a note names the rest. A member never runs it: the guard refuses it, and so does the verb in a member's run directory or with the member mark in the environment. "
                                 "A coordinator session (QARGI_ACTOR) may not run it."),
                           examples=["qargi project remove acme", 'qargi project remove acme --plan TOKEN --approved "retire acme"']),
        },
    },
    "agent": {
        "summary": "Name the members: the local agents that do the work",
        "desc": ("A member is a local agent you name, rendered from the one member definition qargi ships, with the "
                 "roles it serves: build, write, review, test (all four by default). The render is kept in the configuration directory "
                 "(agents/PROJECT/NAME.EXT beside agents.json, outside every repository) and written from there to the runtime's agents "
                 "location; a checkout cleaned or cloned afresh gets it back with agent refresh. The task block names the role and carries its role "
                 "text (roles/<role>/ROLE.md); there is no skill to load. Review is read-only as a "
                 "rule: the guard refuses changes to the clone under that role. Under every role it refuses the verbs that change "
                 "a skill (qargi skill|tool new, import, seal, remove, link, unlink, enable, disable; qargi discover install; qargi packs apply) "
                 "and writes in the pack library, the credentials directory, the install records (install.json, install.d/, install.lock), ~/.claude/skills and any .claude/skills directory, and running the tool's own install.sh or lib/install_record.py, the engine install.sh runs, in any use (those of the clone stay the member's); it fails closed. Dispatch spawns the member qargi agent for "
                 "ROLE prints."),
        "scripts": ["agent.sh"],
        "verbs": {
            "add": verb("Create a member under a name you choose", [("NAME", "none")],
                        [opt("--roles", "comma-separated roles it serves (default build,write,review,test)", "LIST", ABILITIES),
                         opt("--model", "model alias or id for the definition (default: the project's model for the first role, else the shipped default; see agent models)", "MODEL", "model"),
                         opt("--effort", "effort level, written into the definition and recorded with the member (default as for --model)", "LEVEL", EFFORTS),
                         opt("--project", "the project the member belongs to (required): its models.provider renders it, the render is kept in the configuration directory (agents/PROJECT/) and the runtime's file goes where the runtime links project agents (the checkout, hidden from git, or the project render once `project link` is applied)", "PROJECT", "project")],
                        desc=("A member belongs to a project, and the definition is rendered by the provider of that project. "
                              "Refuses a name that exists, a name that is not kebab-case, the name of a built-in agent type of that provider, no --project (exit 2), and a project with no provider (exit 2: there is no default provider). Nothing is written to a runtime's user-level directory."),
                        examples=["qargi agent add forge --roles build,test --project myproject", "qargi agent add scribe --roles write --model opus --project myproject",
                                  "qargi agent add worker --project myproject    # the write-class base: build, write and test"]),
            "list": verb("List the members of every project, their roles and definitions", [],
                         [opt("--project", "only the members of this project", "PROJECT", "project")],
                         desc="One row per member, with no header line: PROJECT, NAME, ROLES (comma separated), MODEL/EFFORT, FILE, then in brackets MISSING (the runtime's file is gone), "
                              "STALE (the copy in the configuration directory is gone or changed, or the definition, catalog, renderer or an extension changed since the render) or DRIFT (the file was edited by hand), "
                              "each followed by the command that fixes it: qargi agent refresh NAME --project P. Members are kept per project, so two projects can each have a worker. "
                              "It also keeps, for each project it lists, the time and each member's STALE or DRIFT in STATE/agent-states.json (mode 600; the reading of a project it did not list is kept, "
                              "a listing of every project replaces the file's projects; a write that fails is ignored and the listing is printed as before): the lead card's line "
                              "'members STALE or DRIFT as of TIME' (qargi role card lead) is read from it, and without a stored reading there is no line."),
            "rename": verb("Rename a member and its definition", [("OLD", "member"), ("NEW", "none")], [MEMBER_PROJECT_OPT],
                           desc="Within its project. The project is --project, else the one in effect, else the only project that has a member OLD; a name two or more projects hold, with none named or in effect, is refused (exit 2) and lists them."),
            "refresh": verb("Re-render a member from the member definition qargi ships now", [("NAME", "member")], [MEMBER_PROJECT_OPT],
                            desc="The project is found as for rename. Keeps its name, roles and model, and writes the copy in the configuration directory and the runtime's file again: a file that is gone (a cleaned checkout, a fresh clone) comes back, a file edited by hand is replaced (the output says so). "
                                 "Use it after an upgrade changes the definition (for example its hook); an unchanged member is left alone. Sessions started afterwards use the new definition."),
            "models": verb("Show the bases, profiles with their requested models and efforts, and in-session members",
                           [], [PROJECT_OPT,
                                opt("--json", "machine-readable")],
                           desc="Two base members, one per guard class: worker (build, write, test; may write) and reviewer (review; read-only). "
                                "Everything else is a profile {base, tier, effort, purpose} resolved at dispatch: the shipped ones are in lib/model-defaults.json "
                                "(build, write, test, review, auditor, advisor, researcher, lead), a project adds or overrides its own under profiles.NAME in its answers, "
                                "and a provider file (lib/providers/NAME.json; the project's models.provider) maps the tiers fast, balanced, deep and frontier to models. "
                                "The frontier tier (researcher) is opt-in. In-session member registration and alias problems are flagged on their row: a member that is not a base (nothing "
                                "dispatches it), a missing base, a refused project profile, a mixed-class member, a tier with no alias, a frontier member outside researcher. "
                                "For command runtimes, bases are logical: no member registration is needed. Rows use the same resolver as agent for, ignoring legacy roles/lead answers, and show the selected model ID or alias, requested effort level and source. "
                                "JSON keeps the existing keys and profile metadata, adding mode: command, profile selected and requested_effort, and base logical: true; members and base registration flags are empty. Refused profiles carry the resolver's reason. "
                                "effort_control describes native support; a requested level remains visible with null native control. A null profiles container is absent; malformed non-null containers and selected entries refuse. The lead row is informational (never dispatched), while agent for --profile lead still refuses. "
                                "Row flags do not fail the display; command-mode extension composition or load errors may fail the command. "
                                "A project with extra runtimes (models.extra_runtimes.local) gets the line runtimes: OWN (the project's own), EXTRA..., a RUNTIME column, and each profile resolved in its own runtime (profiles.NAME.runtime, else the project's own); a row whose runtime is not enabled, cannot be used or does not offer the profile's model is a refused row. The JSON gains runtimes and, in each profile, runtime. A project without extra runtimes gets the output it had. "
                                "A project is needed, because its models.provider decides the models: --project, else the one in effect (with none, exit 2). In-session members shown are that project's (`agent list` shows all projects'). Read-only."),
            "remove": verb("Delete a member's definition and its record", [("NAME", "member")], [MEMBER_PROJECT_OPT],
                           desc="The project is found as for rename: --project, else the one in effect, else the only project that has the member; a name in two or more projects with none named is refused (exit 2)."),
            "for": verb("Print how to dispatch a role: the base member, the model alias and the effort", [("ROLE", "workrole")],
                        [opt("--project", "the project whose members serve and whose profiles apply (default: the project of the current directory)", "PROJECT", "project"),
                         opt("--profile", "a profile of the role's class (a shipped one such as auditor, advisor or researcher, or the project's own; default: the role's own)", "NAME"),
                         opt("--surface", "local (default) or cloud: with cloud, resolve the registered base instance (<project>-worker or -reviewer) instead of a member; needs --project", "SURFACE", ("local", "cloud")),
                         opt("--runtime", "the local runtime to resolve the profile in: the project's own or one it enabled (provider enable --runtime); default the profile's own runtime (profiles.NAME.runtime), else the project's own. A runtime not enabled is refused (runtime-not-enabled)", "NAME"),
                         opt("--opt-in", "cloud only: confirm an opt-in profile such as researcher"),
                         opt("--json", "machine-readable: role, class, profile, base, member, tier, model alias, model id, effort (cloud: instance, base, model, effort, profile, class)")],
                        desc="For an in-session runtime, the base member is the one the profile names (worker for build, write and test, reviewer for review) when the project has registered it; no other member serves, and without it the verb says which base to add. A read-only role never resolves to a member that can write. Plain output is one line: MEMBER MODEL EFFORT PROFILE. "
                             "How the project's runtime starts a member with them is in its notes: qargi provider notes spawn. "
                             "For command runtimes, MEMBER is the logical base, requiring no registration or member file. MODEL is the selected ID or alias (an alias only for use: alias with a nonempty tier alias); EFFORT is the requested level even without native control. JSON marks mode: command. Legacy roles/lead answers do not select command profiles; profiles: null is absent, while malformed non-null containers and selected entries refuse. "
                             "The runtime is chosen in this order: --runtime, then the runtime the profile names, then the project's own; the profile's tier is resolved through that runtime's catalog and its effort through its levels, so --runtime against a profile that names another runtime resolves the tier again in the one asked for, "
                             "and a profile whose own model that runtime neither lists nor matches is the refusal runtime-profile-model (give the profile a tier). A runtime that is not the project's own and not enabled is runtime-not-enabled, also for a project without extra runtimes. "
                             "A project with extra runtimes (models.extra_runtimes.local not empty) gets a fifth word, MEMBER MODEL EFFORT PROFILE RUNTIME, on every answer, the project's own runtime's too, and the JSON the key runtime last; a project without them gets the output it had."),
        },
    },
    "role": {
        "summary": "List and check the roles: what a member or cloud agent is for",
        "desc": ("A role is a directory with role.json (its class, write or read-only, and a description) and ROLE.md (its instructions). "
                 "Four ship with qargi: build, write, review and test (review is read-only). Add your own under ~/.qargi/config/roles/NAME/: "
                 "a name of one lower-case token, never lead. The class decides what the guard allows a member (read-only: nothing in the clone "
                 "changes); the text of a role cannot change it. A task block carries the role's text; a cloud agent of the role has it in its system prompt. "
                 "The card of a role says, before a refusal does, what the role is held to: a member finds it at the end of its task block (CARD:), the lead's session loads it at its start."),
        "scripts": ["role.py", "rolecard.py"],
        "verbs": {
            "list": verb("List the roles, their class and where they live"),
            "show": verb("Print a role: its class, description and instructions", [("NAME", "workrole")]),
            "prompt": verb("Print a role's instructions as a task block carries them", [("NAME", "workrole")]),
            "check": verb("Validate one role, or all of them", [("[NAME]", "workrole")]),
            "card": verb("Print the card of a role: what it is held to, said before the guard or a verb refuses it", [("ROLE", "role")],
                         [PROJECT_OPT, opt("--run", "fill in the real paths of this prepared run (RUN/clone, RUN/out, its temporary directory); without it the words CLONE, OUT and TMP stand for them", "RUN", "dir"),
                          opt("--json", "one object: role, class, card, words, chars, project, run and members_stale")],
                         desc=("Read only, and open to a member: nothing is written and no remote is asked. The card is generated from the role's class, the guard's tables, the command description and the catalogue "
                               "of refusals, and names no runtime. A role of class write gets a short card (work in CLONE, patches and the report in OUT; refused: push, the lead's verbs and directories; a plan you compute "
                               "goes in the report with its token, never applied; report a refusal's code; run the checks that cover your change, the whole suite is the lead's). A role of class read-only gets the paths "
                               "it may write (OUT and TMP), how to write its report, how to test patches in a copy, and what is refused. The lead's card lists the gated verbs by area, the verbs only a terminal runs, "
                               "that a token dies when what it hashed changes (qargi release fix VERSION --record and the dry run before asking), whose words --approved is, and the line 'members STALE or DRIFT as of TIME', "
                               "read from STATE/agent-states.json, which qargi agent list writes (no stored reading, no line); a line that names a rule whose code is not live in the catalogue is left out. "
                               "The task block carries the member card, and the lead's session-start hook loads the lead card; a runtime with no start hook runs qargi role card lead. "
                               "--project is where the lead card reads the stored member states. Exit status: 0; 1 for a role or a run that is not there; 2 for a usage error."),
                         examples=["qargi role card lead", "qargi role card review --run RUN", "qargi role card build --json"]),
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
            "start": verb("Cut feature/NAME from develop", [("NAME", "none")], [PROJECT_OPT, opt("--purpose", "what the feature is about; related work only goes into one feature", "TEXT"),
                                                  opt("--worktree", "also make the feature's worktree at <worktrees.root>/feature/NAME and print its path"), FLOW_UNREACHABLE_OPT],
                          desc="Refuses a name origin already has (asked live with git ls-remote), so another person's branch is not shadowed; fetch it instead. Refuses the name of a detached branch (repo.detached). The marshal record is made before the branch: " + FLOW_UNREACHABLE_NOTE),
            "list": verb("List the open features: purpose, distance from develop, and the files two features both change", [], [PROJECT_OPT],
                         desc=("Several features can be open at once. Two that change the same file will conflict whichever lands second: keep related work in one feature, unrelated work in another. "
                               "It also flags each worktree of the project outside the worktree root (answers worktrees.root, default <state>/worktrees/PROJECT) with the git worktree move that "
                               "fixes it; the main checkout, the worktrees inside it (the agent runtime makes its own there) and qargi's temporary worktrees are not flagged.")),
            "park": verb("Put the project's main checkout on its parking branch, reset to develop", [], [PROJECT_OPT],
                         desc=("qargi moves develop without touching a working tree, so develop cannot be checked out in the project's main checkout. The checkout rests on a "
                               "parking branch instead (answers repo.parking_branch, default scratch). This makes it: git checkout -B BRANCH develop in the main checkout, creating the "
                               "branch when missing. Refused for tracked working tree changes, colliding untracked or ignored files, or when the parking branch has commits develop lacks (they are listed; re-implement "
                               "them with an agent task based on develop, or keep them on a branch of their own). After feature finish, release finish and hotfix finish moved "
                               "develop, a main checkout on the parking branch with no tracked changes or commits of its own is fast-forwarded to develop if no untracked or ignored files collide, and one status line says why it was not. "
                               "The parking branch is never pushed or merged.")),
            "sync": verb("Merge develop into the feature (after another feature landed, before this one's checkpoint)", [("NAME", "none")], [PROJECT_OPT, RESOLVED_OPT, FLOW_UNREACHABLE_OPT],
                         desc=("With the answer release.changelog.numbered true it then checks the changelog for duplicate item numbers and warns (exit status unchanged); "
                               "feature finish refuses them. See qargi changelog. " + FLOW_UNREACHABLE_NOTE)),
            "merge": verb("Merge a verified task branch into feature/NAME with --no-ff", [("NAME", "none"), ("BRANCH", "branch")], [PROJECT_OPT, PLAN, APPROVED, RESOLVED_OPT, FLOW_UNREACHABLE_OPT],
                          desc=("NAME may be a detached long-lived branch of the answers (repo.detached) instead of a feature: BRANCH must then be an agent/* branch, "
                                "and the merge, local only, prints a plan and token like a merge into develop (--plan, --approved). A detached branch never meets develop, master, "
                                "release, hotfix or feature branches: a merge between them, in either direction and by name or by history, is refused here, in sync, in finish and in release finish. "
                                "For a feature, --plan and --approved are not used. When the registry of local runs names a run of BRANCH (its slug) that still exists and has no passing "
                                "local verify, a warning names the run; the merge goes on. " + FLOW_UNREACHABLE_NOTE)),
            "status": verb("Show the feature: commits ahead of develop and whether the whole suite passed at its head", [("NAME", "none")], [PROJECT_OPT],
                           desc=REMOTE_NOTE + " With declared gates a 'gates:' line lists each with its result at the last run. Flags worktrees outside the worktree root like list. When the whole-suite result is for an older head it says why (the commits on the branch since the run, a merge of a task branch or of develop named as such) and that the next step is qargi feature verify NAME."),
            "verify": verb("Run the project's whole test suite on the feature's head and record the result", [("NAME", "none")], [PROJECT_OPT, FLOW_UNREACHABLE_OPT, WAIVE_ENV_OPT, PLAN, APPROVED],
                           desc=GATES_NOTE + " " + ENV_NOTE + " " + OTHER_RUNS_NOTE + " " + SUITE_FAIL_NOTE + " " + FLOW_UNREACHABLE_NOTE,
                           examples=["qargi feature verify login", 'qargi feature verify login --waive-environment cpu --plan TOKEN --approved "go ahead"']),
            "finish": verb("Merge the feature into develop with --no-ff and delete it", [("NAME", "none")],
                           [PROJECT_OPT, opt("--keep", "keep the branch"), PLAN, APPROVED, RESOLVED_OPT, FLOW_UNREACHABLE_OPT, DRY],
                           desc=("Needs a passing whole-suite run at the feature's head. A feature behind develop is refused (exit 1, nothing changed); when both sides "
                                 "changed the same files since their merge base, the message lists them and says to run qargi feature sync first. With the answer release.changelog.numbered true it also refuses a changelog with duplicate item numbers (qargi changelog renumber). Pushes develop if the repository has an origin. With the answer branches.delete_merged "
                                 "local+remote (default local) it also deletes the feature branch on origin when origin has it (asked live) and holds nothing the feature lacks; the plan shows "
                                 "it and its token covers origin's tip. The answer branches.push_features (never, when-shared, always; default never) decides whether feature start, "
                                 "merge and sync push the feature branch: when-shared only when origin already has it. A plain push, never forced. With the answer branches.push_develop false (default true) finish does not push develop either; the first line of its plan says 'will push develop to origin' or 'local only, will not push' with the reason (no origin, or the answer). A clean worktree of the feature under the "
                                 "worktree root is detached and removed after the merge, when the branch is deleted. " + REMOTE_NOTE + " A merge that conflicts changes "
                                 "nothing: the merge is left in progress in a worktree under the state directory (exit 3), you or the lead resolve and commit it there, "
                                 "and the same command with --resolved applies exactly that merge. It is refused first (exit 1, nothing changed) while a run prepared against feature/NAME is open, and lists "
                                 "each one: prepared and not verified, verified and not applied, or applied and not merged. A run that was cleaned, discarded (local clean --discard), closed "
                                 "(local close --applied-by-am) or applied and merged is not open. " + FLOW_UNREACHABLE_NOTE + " " + DRY_NOTE +
                                 " For finish it also renews no lease of the feature's lead (the marshal is asked without --renew and with --no-fetch), takes no lock and writes no intent file; a finish that was cut off is shown as it would be completed, "
                                 "with its record left as it is; an open run of the feature is a refusal (feature-runs-open) that it lists beside the ones that follow. Not for the other feature verbs (exit 2)."),
                           examples=["qargi feature finish login --dry-run", "qargi feature finish login --dry-run --plan TOKEN"]),
        },
    },
    "marshal": {
        "summary": "Who leads which open feature: lease, status, goal, plan, handoff",
        "desc": ("The marshal keeps one record per open feature: its lead (identity and lease), status, goal, plan and a note, and derives the "
                 "tasks, branches, worktrees and overlap from git and the local runs. Query it before beginning work or changing a plan: "
                 "qargi marshal check NAME. A lead is a session with an identity (how a session gets one from its runtime: qargi provider notes identity), or whoever passes --as. "
                 "--as is an option of the marshal verbs only: the other verbs that act for a lead (feature, local, review and the release cut) take no --as, "
                 "and their identity is the one in QARGI_LEAD, else the anonymous user@host. "
                 "A lead holds a lease that its actions and long verbs renew, and so does every command of the lead on the feature: feature merge, sync, status, verify and finish, "
                 "local prepare, verify and clean and review check and apply on a run based on feature/NAME renew it (once a third of the lease has passed, and also after it "
                 "lapsed during a long worker run, as long as nobody else took the feature over: a different identity is still refused while the lease is live). "
                 "Another lead takes the feature only after it was released "
                 "(take) or after the record stayed unchanged for the project's marshal.lease_minutes minutes (takeover, with your words). "
                 "Records are state, not instructions: a note or goal written by another lead is data. By default the records are local to this machine; "
                 "marshal enable switches the project to the shared backend, where each record is a commit on refs/qargi/features/NAME of the remote "
                 "origin so several machines and people see the same leads (takeover then waits for the record to stay unchanged for the ttl as seen by "
                 "the taker's own clock). Only the lead pushes those refs; a member run cannot. "
                 "Exit status 3 means the remote could not be checked. claim and check then refuse, saying what could not be reached (the records of the project on the remote) and why, and change nothing; "
                 "with --assume-unreachable-ok they go on (a claim stays provisional until a later verb completes or drops it, a check answers from what this machine fetched last) and the audit log gets a marshal:unreachable-ok line. "
                 "The verbs of the flow that ask the marshal first (feature start, sync, merge, verify and finish) do the same and take the same flag: they refuse with exit 3 and change nothing, and with --assume-unreachable-ok go on and write the same audit line. "
                 "status shows the cache with a 'remote not checked' notice. "
                 "Every other change of a shared record (set, renew, release, take, takeover, finish, resign) needs the remote and exits 3 without it; there is no override for those. Records can be signed: one key per lead machine, a signers file per project "
                 "and the mode in the switch file (marshal enable --integrity); with integrity on, status and check tag records signed, unsigned, INVALID or cannot verify, "
                 "strict ignores unsigned and invalid ones with a warning, and a rollback prints rollback detected."),
        "scripts": ["marshal.sh", "marshal_store.py", "marshal_refs.py"],
        "verbs": {
            "claim": verb("Become the lead of feature NAME (creates the record; refuses when another lead holds it)", [("NAME", "none")],
                          [PROJECT_OPT, AS_OPT, opt("--goal", "what the feature is to achieve", "TEXT"),
                           opt("--as-successor-of", "continue as the lead after a restart: the old lead's id (see marshal handoff)", "ID"), UNREACHABLE_OPT],
                          desc=("With --as-successor-of ID you take over from the lead ID without the owner's words when that lead's lease is stale and its host, OS user and "
                                "work tree are yours (a restart gives the session a new id and nothing else that tells it apart). The record keeps its goal, plan and note and "
                                "names the succession; it is audited as marshal:succession. Any other case is refused: the owner's marshal takeover covers it. "
                                "feature start continues the same way on its own, and status and check name the command when you look like the restarted lead."),
                          examples=["qargi marshal claim lead-context --as-successor-of 3f2a9c1e"]),
            "status": verb("Show one feature, or every open one with --all: lead, status, goal, plan, note, tasks, branches, worktrees, overlap", [("[NAME]", "none")],
                           [PROJECT_OPT, AS_OPT, opt("--all", "every open feature of the project"), opt("--history", "with --all, also the finished and abandoned ones, after the open ones"), opt("--brief", "one line per feature"), opt("--json", "one document of the kind qargi-marshal-status (qargi help json qargi-marshal-status)"), opt("--no-fetch", "read the cache of the shared refs only, do not fetch (the session hook uses it)"), NOWRITE_OPT],
                           desc=("--json prints one document, always the same shape: schema, kind, project, backend (local or refs), remote (none, checked, unchecked or not-asked: whether the answer was checked against the remote of the shared records), features (one row, or one for each feature with NAME or --all) and agent_unattributed. "
                                 "A row has lease and minutes_since_renewal (a whole number) as lease_clock says: wall (local records, the wall clock) or observed-here (shared records, how long this machine saw the record unchanged). "
                                 "Without --no-write the verb writes: on the local backend it marks a record whose branch is gone abandoned, and on the shared backend it fetches and keeps this machine's own cache; the shared records are never changed. With --no-write it shows such a record abandoned (ghost true) without storing it. "
                                 "The tasks of a feature are the local runs prepared against it (local prepare --base feature/NAME, as the registry of local runs records), and an unmerged "
                                 "agent branch is listed under that feature only. The agent branches of no open feature (no run recorded, or a base that is no feature branch) that are "
                                 "merged into neither develop nor a feature are said once, after the features, on an `unattributed agent branches` line (not in --brief).")),
            "set": verb("Update the goal, plan, note or status of a feature you lead", [("NAME", "none")],
                        [PROJECT_OPT, AS_OPT, opt("--goal", "the goal", "TEXT"), opt("--plan", "the plan, free text or a checklist", "TEXT"), opt("--note", "a note for the next reader", "TEXT"),
                         opt("--status", "planned, active, blocked or verifying", "STATE", ("planned", "active", "blocked", "verifying"))]),
            "check": verb("Before starting work or changing a plan: is the feature free for you, is anything else in its way (exit 1: refuse; warnings go to stderr)", [("[NAME]", "none")],
                          [PROJECT_OPT, AS_OPT, opt("--json", "one document of the kind qargi-marshal-check (qargi help json qargi-marshal-check)"), opt("--no-fetch", "read the cache of the shared refs only, do not fetch (the session hook uses it)"), NOWRITE_OPT, UNREACHABLE_OPT],
                          desc="With the shared refs backend it asks the remote and refuses (exit 3, code marshal-remote-unreachable, a refusal a retry may cure) when it cannot be reached, unless --assume-unreachable-ok. It renews no lease, but it is not a pure read: unless --no-write is given it marks a record whose branch is gone abandoned (local backend), fetches into this machine's cache (shared backend), and with --assume-unreachable-ok appends one audit line; with --no-write it writes nothing and fetches nothing and answers as the writing call does (a record whose branch is gone counts as abandoned, with no lead, in the answer, and is not stored). --json prints one document: schema, kind, project, backend, remote, feature, answer (yours, free, free-stale; null without NAME), lead, warnings (the warnings the text form prints on standard error) and, without NAME, features (one row for each open feature). A feature held by another live lead is a refusal, exit 1, code marshal-feature-held, with a refusal line on standard error and no document, with or without --json. The commands of the flow that ask the marshal first (feature merge, sync, status, verify and finish; local prepare, verify and clean; review check and apply) renew the lease of their own lead as they ask."),
            "renew": verb("Renew your lease on a feature (long verbs and the lead's other commands on the feature do this themselves)", [("NAME", "none")], [PROJECT_OPT, AS_OPT]),
            "release": verb("Give the feature up, leaving a handoff note; it has no lead until someone takes it", [("NAME", "none")],
                            [PROJECT_OPT, AS_OPT, opt("--note", "what the next lead must know", "TEXT")],
                            desc=("When there is nothing to give up, because the feature was finished (feature finish deletes the branch and ends the claim), abandoned or released "
                                  "already, it exits 0 with one line, 'nothing to release', and needs no --note. A name with no record and no branch is refused (no feature NAME: a typo), "
                                  "and so is a feature that another lead holds or that has a branch and was never claimed.")),
            "take": verb("Become the lead of a feature that was released", [("NAME", "none")], [PROJECT_OPT, AS_OPT]),
            "takeover": verb("Take a feature from a lead that stopped (no change for the project's marshal.lease_minutes); needs your words", [("NAME", "none")],
                             [PROJECT_OPT, AS_OPT, APPROVED]),
            "finish": verb("Mark the feature finished (feature finish does this)", [("NAME", "none")], [PROJECT_OPT, AS_OPT]),
            "enable": verb("Switch this machine's marshal to the shared refs backend (refs/qargi/ on the remote origin)", [],
                           [PROJECT_OPT, opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED,
                            opt("--integrity", "off, advisory or strict: how records are signed and checked", "MODE", ("off", "advisory", "strict"))],
                           desc=("Without options it prints the plan and a plan token; apply with --plan TOKEN --approved WORDS (audited as marshal:enable). It needs a remote named origin. "
                                 "--integrity sets the mode: off signs and checks nothing; advisory signs when a key exists and tags records signed, unsigned or INVALID without ignoring any; "
                                 "strict ignores records not signed by a trusted key and falls back to the last accepted record. Not available in a member run.")),
            "key": verb("Create this machine's signing key for the marshal records (key init)", [("SUBCOMMAND", "none")],
                        [opt("--principal", "the name the key is trusted under (default person@machine)", "ID"), opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED],
                        desc=("`key init` makes $QARGI_CONF/credentials/marshal_ed25519 (mode 600), never overwrites it, and prints the signers line to trust on every lead machine. "
                              "Audited as marshal:key-init. Not available in a member run.")),
            "signers": verb("List, add or remove the keys trusted to sign this project's marshal records (add | remove | list)", [("SUBCOMMAND", "none"), ("[PRINCIPAL]", "none")],
                            [PROJECT_OPT, opt("--line", "the signers line printed by key init (add)", "LINE"), opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED],
                            desc=("Edits $STATE/marshal/PROJECT.signers, which never goes into the repository or the refs. add and remove are audited as marshal:signers and refused in a member run; list is open to members.")),
            "resign": verb("Sign an unsigned open record (writes one more revision on top of it)", [("NAME", "none")], [PROJECT_OPT, opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED],
                           desc=("Used when moving from advisory to strict. The plan shows the head, its lead and goal and its token covers exactly that head; it is refused for a lead other than the accepted one. "
                                 "Audited as marshal:resign. Not available in a member run.")),
            "forget": verb("Drop this machine's accepted mark of a feature, so a stale mark stops reporting rollback detected", [("NAME", "none")], [PROJECT_OPT, opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED],
                           desc=("Only with integrity advisory or strict, and only for a feature that has a mark. The plan shows the mark's revision and commit and its token covers both, so a mark that moved since is refused. "
                                 "After it the next record found for the feature is trusted on first sight again and a rollback against the old revision is no longer detected; the refs on the remote are not touched. "
                                 "Audited as marshal:forget. Not available in a member run.")),
            "handoff": verb("Print the note a fresh session starts from, built only from stored facts", [("[NAME]", "none")],
                            [PROJECT_OPT, AS_OPT, opt("--write", "write the note to this new file (mode 600) instead of printing it (with --json: print the document first, then create the file)", "FILE", "file"), opt("--json", "print the same facts as one JSON object of the kind qargi-handoff (qargi help json qargi-handoff)")],
                            desc=("It needs no lease and changes no record, ref or audit line; only --write FILE makes a file and records when and where the note was written. Nothing is fetched: shared records are read from the cache this host holds, with a note, and a shared marshal that is off or unreachable falls back to the local records. "
                                  "The note has the repository path, HEAD there (a detached HEAD is said plainly), develop's sha, the host and whether the qargi data is present on it. "
                                  "Per feature it has the tip, whether the whole-suite run applies to it (the run's command is the project's test_command now, or with declared gates the feature-tier gates in order, `gates: NAME=COMMAND; ...`, as feature verify records them), the agent branches merged into it since it was cut from develop, the unmerged ones prepared against it (as the registry of local runs records) "
                                  "and the commits ahead of develop; with NAME only that feature, otherwise every open one; the agent branches of no open feature are said once, after the features. "
                                  "The note starts with its where section, then an index of its features, lists live work first and lists a feature's own worktrees under it. A note that fits the bound is printed whole, with every index line and no truncation line; "
                                  "only a note over the bound has its index cut (3072 bytes of lines, then one line that counts the features without one) and ends with a line naming the features left out or cut short and saying how many have no index line. "
                                  "The features that have a branch and no marshal record are one note: how many, their first names, then the count of the rest. "
                                  "--json is one document of the kind qargi-handoff: schema, kind, backend (local or refs), remote (not-asked on the shared records, which it never fetches, none on the local ones) and backend_fallback (true when shared records could not be read and the note was made from the local ones, which a sentence of notes says too), and the minutes of a lease are whole numbers. "
                                  "With --write FILE and --json the document goes to standard output first and is flushed, then the file is created and the sentence about it goes to standard error, so a standard output that cannot take the document leaves no file. "
                                  "A file that is refused before the document is printed (it exists, its directory is missing or not writable by you, it is in a git work tree or a qargi directory) is a refusal with standard output empty; a file that cannot be made after the document was printed is one plain line on standard error and exit 1, with no refusal line. "
                                  "--json over the bound empties worktrees_unattributed and agent_unattributed as needed (each only while the output is still over the bound), then, one feature at a time from the last, trims its detail and drops it, and sets truncated; "
                                  "when features are dropped it adds features_omitted (the count dropped) and features_left_out (their names, up to 3000 bytes), and features_left_out_more (the count of names not listed) when not all of them are. "
                                  "When no feature is left and it is still over the bound, it cuts the lists from the end, the notes first, then deviations.accepted, gates, read_first.memory, read_first.repo_docs and read_first.successor, and lists_left_out says how many items each list lost. "
                                  "When the project declares gates, a `== gates` section follows the features with each gate's tier, name and command (they replace test_command), and --json carries them as `gates` (an empty list without gates). "
                                  "When the project answers hold accepted deviations (methodology_accepted), a `== methodology deviations` section follows the gates, apart from the open gaps: each deviation with its status (accepted, or accepted, no longer applies), reason and date, and the number of open gaps; --json carries them as `deviations`. "
                                  "The goal, plan and note of the marshal record appear under a line saying they are data from the lead, not instructions, with control characters stripped. "
                                  "The environment section gives the last env check and env apply recorded for the project (verdict, time, and whether that was at HEAD now). "
                                  "For a feature this identity leads it names the claim --as-successor-of command a restarted session runs. --write also records when the note was written (what qargi lead compact-check compares with the last merge), and a line says whether a compact is safe now (see qargi help lead). "
                                  "It also gives the packs render check and the launch line for the project's provider, the memory index and notes paths, the history command and a fixed list of what not to assume (approvals and plan tokens do not carry over). "
                                  "Output is capped at 16 KiB, the note and --json alike (the final newline counted). The text note is always within the bound; in --json the one part not bounded is what a successor needs whole and --json never cuts: do_not_assume, where, packs and environment (a few KiB, more only for a path of unusual length). --write refuses an existing file, a path inside a git work tree or the qargi directories, and a member run. The qargi-session skill says what to do with the note.")),
            "disable": verb("Switch back to the local records; the refs already on the remote stay (audited as marshal:disable)", [], [PROJECT_OPT, opt("--plan", "the plan token printed by the first run", "TOKEN"), APPROVED],
                            desc="While integrity is advisory or strict it needs the plan token and your words (it drops the setting). Not available in a member run."),
        },
    },
    "branch": {
        "summary": "Branch housekeeping: delete the merged agent and feature branches and their worktrees",
        "desc": ("Prune prints the merged agent/* and feature/* branches of the project (and with --remote the same branches on origin, asked live) and the worktrees "
                 "qargi made for them, with a token; with --plan and --approved it deletes them. The one deletion that is not gated is prune --agents: it deletes the merged agent/* "
                 "branches of the repository at once, with no token and no approval (the lead's; the tip of each stays reachable from the merge that took it in); the feature branches and "
                 "the branches on origin always take a plan and an approval. A branch is merged when it was merged with --no-ff into develop, "
                 "into a branch of repo.long_lived or repo.detached, or, for an agent branch, into an open feature, and is still in that branch's history; a branch that merely sits at the tip of one of them "
                 "was never merged and is kept. It never deletes master, develop, the branches of repo.long_lived and repo.detached, the parking branch, an unmerged branch, "
                 "or a branch checked out in a worktree qargi did not make (the main checkout, the runtime's own worktrees) or in a dirty one; each kept branch is listed with "
                 "the reason. A remote branch is deleted as a lease on the tip the plan showed."),
        "scripts": ["branch.sh"],
        "verbs": {
            "prune": verb("List, or with the token and an approval delete, the merged agent/* and feature/* branches and their worktrees; --agents deletes the merged agent/* ones at once", [],
                          [PROJECT_OPT, opt("--remote", "also the merged agent/* and feature/* branches on origin (fetches first)"),
                           opt("--agents", "only the merged agent/* branches of this repository, deleted at once with no --plan, --approved or --remote: plan lines printed, journaled, one audit line; the lead's"),
                           PLAN, APPROVED, DRY],
                          desc=("A branch is merged when it was merged with --no-ff into develop, into a branch of repo.long_lived or repo.detached or the remote-tracking branch origin/BRANCH of a detached one "
                                "(a detached branch that origin changes only through a pull request lags behind it locally; fetch first, --remote does), or, for an agent branch, into an open feature. "
                                "A branch that only sits at a tip was never merged and is kept. " + DRY_NOTE + " For prune it asks origin, with --remote, with git ls-remote: a branch of origin whose tip this repository does not have "
                                "is kept ('its tip is not fetched') where the apply, which fetches first, might prune it. "
                                "--agents is local only and the exception to the gate: it takes no --plan, --approved or --remote (a usage error, exit 2) and deletes only merged agent/* branches, never a feature branch. "
                                "It prints what it deletes (the lines of the plan: each branch, the commit and the branch it was merged into, the worktree qargi made that goes with it, the commits made with git "
                                "that the journal takes in, and the branches kept with the reason), then for each branch brings the commits made with git on it into the ref journal first (so a run prepared before them still verifies), "
                                "deletes it only if it is still at the tip the plan showed, and journals the deletion; one audit line records it. A member run, or a call nested in an approved apply, is refused (exit 2). "
                                "With --dry-run it prints the plan and deletes nothing."),
                          examples=["qargi branch prune", "qargi branch prune --agents", "qargi branch prune --dry-run", "qargi branch prune --remote --plan TOKEN --approved \"yes, prune them\""]),
        },
    },
    "changelog": {
        "summary": "Numbered changelog items: find duplicate numbers and renumber them",
        "desc": ("For a project whose changelog numbers its items, which it says with the answer release.changelog.numbered: true (off by default). "
                 "Under the unreleased heading (release.changelog.unreleased, default '## [Unreleased]'), an item is a line that starts with a number, a dot and a space "
                 "('12. text') or with '- ', the number, a dot and a space ('- 12. text'); the lines up to the next item belong to it. "
                 "Two branches that each added an item 5 leave two items numbered 5 once merged. feature sync and feature finish run the check when the answer is true: "
                 "sync warns, finish refuses (exit 1, nothing changed) until the numbers are renumbered, committed and the suite has run again."),
        "scripts": ["changelog.sh"],
        "verbs": {
            "renumber": verb("Find the duplicate item numbers under the unreleased heading and renumber them in file order", [],
                             [PROJECT_OPT, opt("--check", "only report: write nothing, exit 1 when a number is duplicated")],
                             desc=("Works on the CHANGELOG.md of the work tree around the current directory, which must belong to the project (the feature's worktree, not the main checkout "
                                   "while it rests on the parking branch). Only when a number is duplicated, the items are numbered again, consecutively in file order from the number of the "
                                   "first one, and every '(item N)' cross-reference inside the section follows the item it means: with a duplicated N, the nearest item numbered N at or "
                                   "before the reference, else the nearest after it. The file is rewritten and not committed. Without --check it is the lead's: a member run may only use --check."),
                             examples=["qargi changelog renumber --check", "qargi changelog renumber"]),
        },
    },
    "upstream": {
        "summary": "Follow an upstream repository: how far behind, what is new, sync its branch",
        "desc": ("A project that is a fork keeps its own changes, the overlay, on top of an upstream repository. The answers name the remote (upstream.remote), "
                 "the branch it follows (upstream.branch) and the local branch that carries the upstream line and nothing else (upstream.into, default upstream); "
                 "upstream.overlay_check, optional, is a command array that checks the overlay still applies or builds. status fetches that one branch of that "
                 "remote (the only verb that reaches the network) and says where the branch stands; review and sync work from the last fetch. The upstream line "
                 "never meets develop directly: after a sync, cut a feature and merge the branch into it (qargi feature start upstream-X, then qargi feature merge "
                 "upstream-X BRANCH), fix the overlay there, and let the feature land as any other. Nothing is pushed."),
        "scripts": ["upstream.sh"],
        "verbs": {
            "status": verb("Fetch the upstream branch and say how far the local branch is behind and ahead of it, with the newest upstream commits", [], [PROJECT_OPT],
                           desc="The fetch is of that one branch of that remote, with no tags; it changes the remote-tracking ref and nothing else."),
            "review": verb("List the upstream commits not yet in the local branch, with the files each one touches; a commit that touches a file the overlay changed is marked", [],
                           [PROJECT_OPT, opt("--limit", "show at most N commits, newest first (default 30)", "N")],
                           desc="The overlay is what develop changed since it parted from the upstream line (their merge base). Reads the last fetch (qargi upstream status); changes nothing."),
            "sync": verb("Fast-forward the local branch to the fetched upstream branch (--ff-only), with the token and an approval", [], [PROJECT_OPT, PLAN, APPROVED],
                         desc=("Refused when the branch has commits of its own (not a fast-forward): it carries the upstream line only. Creates the branch at the upstream tip "
                               "when it does not exist yet. The move is journaled; nothing is pushed and nothing is merged into develop: the next step is printed. With "
                               "upstream.overlay_check set, the command then runs on a trial merge of the branch into develop in a temporary worktree (the fast-forward "
                               "stands either way; a failure or a merge conflict exits 1)."),
                         examples=["qargi upstream sync", "qargi upstream sync --plan TOKEN --approved \"yes, take the upstream commits\""]),
        },
    },
    "campaign": {
        "summary": "Record and inspect local campaign declarations",
        "scripts": ["campaign.py"],
        "desc": ("Campaign v1 records declarations only: it grants no participant, execution, acceptance or merge authority. "
                 "Invalidation policy is undecided. Participant locators, source refs and link targets are never opened. "
                 "State verbs are lead-only and need no project registration, repository adoption or cloud configuration. "
                 "Pure check --spec reads only the selected regular file (including a user-selected symlink), with no configuration or state resolution. "
                 "Spec input is bounded to 512 KiB before parsing; special files are refused. "
                 "JSON is a native campaign-report v1, with valid false and exit 1 for data, conflict, lock, storage and uncertain outcomes. "
                 "Usage errors exit 2 on stderr. Exit 0 qualifies only the reported declaration scope. "
                 "Text prints fixed summaries and identifiers; show --json includes the supplied document. "
                 "Historical responses prove selected-head ancestry within one 4096-edge traversal bound; exhaustion returns no successful partial history. "
                 "Reads never repair state and report durability not-assessed. Writes use a permanent local lock and compare-and-swap head; "
                 "publication and durability are separate outcomes. Fsync-acknowledged describes returned syscalls on a trusted local filesystem, not power-loss safety. "
                 "No retry, rollback, orphan adoption or acceptance inference is automatic."),
        "verbs": {
            "commit": verb("Publish a declaration or settle an exact-current retry", [("ID", "none")],
                           [opt("--spec", "required declaration document", "FILE", "file"),
                            opt("--create", "create revision 1; requires exactly one of --create or --expected-head"),
                            opt("--expected-head", "compare-and-swap from this sha256 digest", "DIGEST"),
                            opt("--json", "print the native campaign report")],
                           desc="Supply --spec FILE and exactly one of --create or --expected-head DIGEST. An exact-current retry settles the selected candidate and reports already-current; a stale expectation otherwise conflicts without rebasing or checking candidate history. Failures preserve publication (not-assessed, none, visible or unknown), durability and any parent uncertainty. Retry only by explicitly issuing the same command after inspecting the outcome."),
            "show": verb("Read the current declaration or a proven historical revision", [("ID", "none")],
                         [opt("--revision", "select a retained sha256 revision digest", "DIGEST"),
                          opt("--json", "include the declaration in the native campaign report")],
                         desc="Historical selection must prove ancestry from one selected head within 4096 predecessor edges. Exhaustion reports history-walk-limit. Current reads remain available beyond that bound."),
            "check": verb("Check current state or only a supplied declaration", [("ID", "none", True)],
                          [opt("--spec", "check this supplied document instead of an ID; no transition or state check", "FILE", "file"),
                           opt("--json", "print the native campaign report")],
                          desc="Choose ID or --spec FILE, never both. Only the pure supplied-document form is available to members; it reports transition not-checked and coordination scope supplied-document. A current-state check verifies the actual parent transition."),
            "log": verb("Read a bounded page of proven declaration history", [("ID", "none")],
                        [opt("--cursor", "continue a page; an untrusted cursor grants no ancestry proof", "CURSOR"),
                         opt("--limit", "page entries: decimal integer 1 to 200 (default 50)", "N"),
                         opt("--json", "print the native campaign report")],
                        desc="Each response proves selected-head ancestry within one 4096-edge bound shared by proof and page traversal. Exhaustion fails with no partial entries and complete false. Complete means the page reached revision 1. A cursor pins a selected start and next revision; every page proves them again. Current reads and commits have no history-length limit."),
        },
    },
    "backlog": {
        "summary": "The project's backlog: list, inspect a graph, add, and archive the done ones",
        "desc": ("The backlog is a markdown file that the project answer backlog.file names (a path: ~/ works, a relative path is taken from the repository, "
                 "and the file may live outside it, in a memory store for instance; qargi project set PROJECT backlog.file PATH). "
                 "An item is a top-level list line written '- [ID] text' (or '* [ID] text'), ID a lowercase slug of letters, digits and hyphens, two characters or more "
                 "(so a task-list box '- [x] text' is no id), with the indented lines after it. Any other top-level list line is an item without an id and is listed as unnumbered; "
                 "headings, paragraphs and fenced code blocks are not items. feature finish and release finish print a plan line, 'backlog items named in these commits: ID, ...', "
                 "for the open items whose id the messages of the commits being merged contain; it is information only and nothing is done, and nothing is printed when backlog.file "
                 "is unset or its file is missing. backlog.section names a heading of the file (its text, with or without the #s): only the list under it holds items, up to the next "
                 "heading of the same or a higher level (a deeper heading belongs to it), also for that plan line; a heading the file lacks is an error for the verbs and names nothing in the plan line. "
                 "backlog.archive says where the archive goes: a directory (created when absent; a ~/ or relative path works as for the file) that receives NAME-archive-YYYY-MM.md, "
                 "or a path ending in .md for one archive file whatever the month; by default the archive is beside the backlog file."),
        "scripts": ["backlog.sh", "backlog_graph.py"],
        "verbs": {
            "graph": verb("Check, show or explain a manually edited read-only backlog graph v1", [("ACTION", ("check", "show", "why"))],
                          [PROJECT_OPT, opt("--graph", "the graph JSON file (required)", "FILE", "file"),
                           opt("--node", "a declared typed reference, required only for why", "REF"),
                           opt("--json", "print the native backlog-graph-report v1 object, including invalid input reports")],
                          desc=("Use check|show|why --graph FILE; why also needs --node backlog:ID or feature:NAME. Reads the configured backlog.file; "
                                "backlog.section affects display metadata only, and identities resolve across the whole backlog. "
                                "Reported evidence is pinned to the parser's full item lines; revised items supersede that evidence. "
                                "Confirmed requires point from dependent to prerequisite; contains is structural only. "
                                "Projections describe planning, never acceptance or execution permission. Features and archives are unobserved. "
                                "No state setup, audit writes, network or data changes. Lead only under the current member guard; future graph verbs get no member permission. "
                                "Exit 0 for a valid graph (warnings allowed), 1 for invalid/unreadable inputs or an undeclared why node, 2 for usage errors. "
                                "The normative schema, findings codes and limitations are in docs/reference/backlog-graph.md."),
                          examples=["qargi backlog graph check --graph graph.json --json",
                                    "qargi backlog graph why --graph graph.json --node backlog:fix-names"]),
            "list": verb("List the open items with their ids; an item without an id is shown as '-', a duplicated id is flagged", [],
                         [PROJECT_OPT, opt("--json", "print the file, the items (id, line, text, full text, duplicate) and the duplicated ids as one JSON object")],
                         desc="Read only, so a member may run it. Exit 1 when backlog.file is unset or its file is missing.",
                         examples=["qargi backlog list", "qargi backlog list --json"]),
            "add": verb("Add an item: '- [ID] TEXT' at the end of the list, of the section when backlog.section is set", [("ID", "none"), ("TEXT", "none")],
                        [PROJECT_OPT, opt("--detail", "more words for the item, written as indented lines under it (one line of the option per line of the item)", "TEXT")],
                        desc=("ID is a lowercase slug (letters, digits and hyphens, two characters or more); an id that is no slug, or is already an item anywhere in the file (also outside "
                              "the section), is refused (exit 1) and the file is not touched. TEXT is one line; --detail may span lines. The item is written at once (no plan: it adds a line and "
                              "removes nothing) and an audit line is kept. Lead only: a member's guard refuses every backlog verb but list; report the item in the task output instead."),
                        examples=["qargi backlog add fix-names \"Rename the two helpers that share a name\"", "qargi backlog add fix-names \"Rename the helpers\" --detail \"They differ in case only.\""]),
            "done": verb("Move items, with the evidence and the date, to the archive file beside the backlog and remove them from the backlog, with the token and an approval", [("ID", "none"), ("[ID...]", "none")],
                         [PROJECT_OPT, opt("--evidence", "the words that show the items are done (they are archived with each item and the date)", "TEXT"), PLAN, APPROVED],
                         desc=("Several ids make one batch: one plan listing every item, one token for the whole batch, and the same evidence archived with each id; the batch applies together "
                               "(the archive is written once, then the backlog), and an id that is not there, is used by more than one item, or is named twice refuses the whole batch with no plan. "
                               "The plan shows the items and the file they go to. Applied, each item (as written, with its indented lines), the date and the evidence are appended to "
                               "NAME-archive-YYYY-MM.md in the directory of the backlog file, or where backlog.archive says (NAME is the backlog file's name without .md; the archive is created when absent), "
                               "and then the items are removed from the backlog. Nothing is deleted without the plan. Refused when the id is not there, or is used by more than one item "
                               "(make the ids unique first). Not available in a member run."),
                         examples=["qargi backlog done fix-names --evidence \"merged, suite green\"", "qargi backlog done fix-names add-cache --evidence \"merged in feature/names, suite green\"",
                                   "qargi backlog done fix-names --evidence \"merged, suite green\" --plan TOKEN --approved \"yes\""]),
        },
    },
    "ref": {
        "summary": "Record in the lead's ref journal a branch move or a branch that no flow verb made",
        "desc": ("The ref journal ($QARGI_STATE/ref-journal.jsonl) is the lead's record of the branch and tag moves qargi's verbs make (feature, release, branch prune, "
                 "review apply, with their pushes); qargi local verify and local clean accept and name what it records. "
                 "A verb that deletes a branch (release finish, a hotfix too, feature finish, branch prune) first records the commits made with git on that branch that the journal has no line for, "
                 "in the repository and for the branch it deletes on origin: one line per commit, with the verb's own name and a why that says git made the step, "
                 "so a run prepared before those commits accepts the deletion, and verify names the verb. No such line is written for a branch that is kept, "
                 "that the journal never had, or whose tip is not within 500 first-parent commits of a commit the journal has it at (a branch rewritten by hand, for one). "
                 "qargi ref record adds the two moves a lead makes by hand "
                 "that verify must still accept: the rewrite of an agent branch, or of a release or hotfix branch not yet pushed, that keeps its content (--rewrite), and the deletion of a branch "
                 "that no verb deleted (--deleted). qargi ref note adds the branches the lead made by hand or pushed "
                 "(git branch, git push), so that verify does not blame the run for them; a branch deleted and made again is journaled with --deleted, then ref note, whose line starts at absent."),
        "scripts": ["ref.sh"],
        "verbs": {
            "record": verb("Rewrite a branch to a commit with the same tree, or record a branch deleted by hand, and journal the move with the reason", [("REF", "branch"), ("OLD", "none"), ("NEW", "none", True)],
                           [opt("--rewrite", "the kind of move: REF goes from OLD to NEW, whose trees must be identical (exclusive with --deleted)"),
                            opt("--deleted", "the kind of move: REF was deleted by hand and was at OLD; give no NEW (exclusive with --rewrite)"),
                            opt("--why", "the reason, journaled and named by local verify", "TEXT"), PROJECT_OPT],
                           desc=("--rewrite: REF is an agent/* branch (agent/NAME or refs/heads/agent/NAME), or a release/* or hotfix/* branch that origin does not have (asked live: a branch that was pushed, "
                                 "and an origin that cannot be asked, are refused); never a long-lived branch (master, develop, repo.long_lived, repo.detached, the parking branch) or a feature branch. "
                                 "It refuses NEW unless git rev-parse OLD^{tree} and NEW^{tree} are the same, "
                                 "and REF unless it is at OLD now; the move is then a compare-and-swap (git update-ref REF NEW OLD), so nothing moves when REF changed meanwhile. "
                                 "The journal line has verb ref:rewrite and the reason, and a run prepared before the move verifies and is cleaned with it named as a rewrite; "
                                 "local clean, local list, lead compact-check and feature finish follow the applied tip of a run to NEW (one test, lib/merged.py). No working tree, other ref or origin is touched. "
                                 "--deleted: REF is a branch NAME, or origin/NAME for a branch of origin (asked live); it must be absent now, must not be long-lived, and OLD must be a commit. "
                                 "It first journals the commits made with git on the branch since the journal last had it (as a verb that deletes a branch does), then the deletion from OLD to absent "
                                 "(verb ref:deleted, with the reason), so local verify and local clean of a run prepared before accept the deletion and name it as qargi ref deleted. "
                                 "Nothing is moved or deleted: the branch is gone already. A branch deleted and made again is journaled with --deleted, then ref note. Not available in a member run."),
                           examples=["qargi ref record --rewrite agent/fix-names 1a2b3c4 5d6e7f8 --why \"reworded two messages\"",
                                     "qargi ref record --deleted agent/fix-names 1a2b3c4 --why \"deleted by hand after the merge\""]),
            "note": verb("Journal a branch you made by hand, or pushed to origin, so that local verify accepts it", [("REF", "none")],
                         [opt("--why", "a reason, journaled with a local branch", "TEXT"), PROJECT_OPT],
                         desc=("REF (give several) is a branch NAME, or origin/NAME for the branch NAME of origin, whose live value is asked (git ls-remote); the branch must exist now. "
                               "The journal line (verb ref:note) goes from the ref being absent to the value it has now, or, when you noted that ref before, from where the earlier note left it "
                               "(pushing the same branch again), or from absent when the ref was deleted since (by ref record --deleted, or by a verb that deletes branches), so a branch made again with the same name is noted as created; "
                               "a second note is refused when the earlier note's value is not an ancestor of the current one (the ref was rewritten: inspect it; "
                               "qargi ref record --rewrite records a rewrite of an agent branch, or of a release or hotfix branch not yet pushed, that keeps its tree). The note prints the author and subject of the tip, and REF@SHA "
                               "(7 to 40 hex digits) notes REF only while it is at SHA, so the lead notes what it looked at. Nothing is created, moved or pushed. A run prepared before it then verifies with the branch named as one you noted. "
                               "Only a ref that did not exist when the run was prepared (or that you noted before) is accepted this way: a ref that existed then and has moved, "
                               "a deletion that no verb made and you did not record (ref record --deleted), and any ref you did not note stay offending, so a branch the run's agent made or moved is still found. Note only what you made. "
                               "Not available in a member run. The harness's own worktree branches (worktree-bridge-NAME, held by the locked worktree bridge-NAME of the harness) need no note: verify leaves them out."),
                         examples=["qargi ref note feature/search origin/feature/search", "qargi ref note feature/search@1a2b3c4d"]),
        },
    },
    "release": {
        "summary": "Releases and hotfixes by the git-flow rules",
        "desc": ("release/<version> is cut from develop (a hotfix/<version> from master); its first commit bumps VERSION and dates the changelog and the man page. "
                 "It is pushed and a pull request into master runs CI on the commit that will be released. Finishing merges it into master with --no-ff, "
                 "tags that merge commit, merges the tagged master commit (not the branch a second time) into develop (a hotfix: into the open release branch, if there is one) with --no-ff, "
                 "so master holds no merge commit that develop lacks, and deletes the branch. A release starts only from "
                 "a develop whose head passed the whole suite. Starting, pushing, merging, tagging and publishing need the plan token and an approval: release plan prints one plan for the cut (start, push, finish, site) and one token, "
                 "its approval is recorded once, and those steps then take --plan TOKEN alone; publishing is not in the cut and has its own plan and approval; signing needs your terminal. "
                 "The layout of what a release updates is the project's, set in its answers (all optional): release.version_file (the file that holds only the version; default VERSION; "
                 "none when there is no such file, and the version is then the changelog heading and the tag), release.changelog.unreleased (the heading of the changes to come, default "
                 "'## [Unreleased]'; it may carry the version, as in '## {version} (unreleased)', and is then renamed) and release.changelog.released (default '## [{version}] - {date}'), "
                 "release.version_files (other files that carry the version, a list of paths; default none: start, status and verify warn of the ones that do not contain the version, never bump them), "
                 "release.man_pages (a list of paths; default the man/*.1 files), release.test_command (what release verify runs, a command line or a list of words; default test_command) "
                 "and release.preflight (a command as a list of words, {version} replaced, run by start and push before they change anything; a non-zero exit refuses and shows the tail of its output; "
                 "a hotfix's start does not run it, because master lacks the content the hotfix brings, and its push does, in a copy of the branch). "
                 "release.hotfix_preflight (the same forms) is what a hotfix's push runs instead of release.preflight, in a copy of the branch before anything is pushed, when the stored preflight needs content only the fix has or does not suit a hotfix; default none, and release.preflight runs. "
                 "release.finish_check (a command line, or a command as a list of words, {version} replaced; default none) is run by finish in a copy of the branch once its plan is approved, before anything is merged, tagged or pushed; a non-zero exit refuses and shows the tail of its output, and nothing has moved. "
                 "The project answer gates (an ordered list of {name, command, tier}) replaces test_command and release.test_command when declared: release verify runs the feature-tier gates, then the release-tier gates. "
                 "The release files are the project's too: release.assets_command (the command that builds them, a command line or a list of words with {version} replaced), which "
                 "release assets runs in a clean worktree of the tag, and release.assets (files or globs to attach, {version} replaced), taken in that worktree by release publish. "
                 "release.after_steps is a list of steps ({version} replaced), each a one-line string (a command or a reminder: its text is its name) or an object "
                 "{name, command, who (lead or owner), evidence (what shows it was done)}; the names are distinct. release finish prints them as 'after the release:' lines and records them as pending; "
                 "release step marks one done; qargi never runs them. "
                 "release.notes_file (a file relative to the repository, {version} replaced; default none) is the text release publish uses for the notes, and release push warns when it leaves out an item of the version's changelog section. "
                 "release.changelog.fragments (a directory relative to the repository; default none; the lead's) is for a project that records its notes as files: a fragment is any file in it but README* and .gitkeep. "
                 "With it release start counts the fragments at the base as notes (so --allow-empty-notes is not needed; the plan says how many are to be folded on the branch), and release push and release finish "
                 "refuse, with release-fragments-unfolded, while the directory at the branch head holds a fragment or the released section of CHANGELOG.md has no notes, is missing, or CHANGELOG.md is missing: "
                 "fold them in the fix worktree, commit, then release fix VERSION --record. Without the answer nothing changes, and an empty unreleased section refuses with release-notes-empty, which names the option and the answer. "
                 "A member may not set them: the lead runs them. "
                 "A project with a documentation site on a detached branch sets site.enabled to true, and optionally site.branch (default gh-pages when repo.detached "
                 "lists it) and site.config (the site.json on that branch, default site/site.json, with the hand pages in the folder pages/ beside it): then "
                 "release finish ends with 'next: qargi release site VERSION' (the methodology's after_release step) and release status has a site line."),
        "scripts": ["release.sh"],
        "verbs": {
            "plan": verb("One plan and one approval for the whole cut: start, push, finish and site (publish has its own plan)", [("VERSION", "none")],
                         [PROJECT_OPT, HOTFIX_OPT, opt("--date", "the changelog and man page date (default today)", "YYYY-MM-DD"), opt("--keep", "keep the branch when the cut finishes"),
                          opt("--allow-empty-notes", "release although the unreleased section of CHANGELOG.md is empty"),
                          opt("--again", "discard the recorded cut of VERSION and plan anew"), PLAN, APPROVED],
                         desc=("Without --approved it changes nothing: it prints every step of the ceremony with what moves (1 start, 2 push when the repository has an origin, 3 finish, 4 site when "
                               "site.enabled is true) and ONE plan token; publish is named as outside the cut. The start step is planned by release start itself, so its refusals come before a token does. "
                               "The push step names fix_paths, kept in the cut record: the paths a fix may change and still go on under this approval, derived from the project's answers (the directory of release.changelog.fragments "
                               "when set, CHANGELOG.md, release.version_file and each of release.version_files; docs/ and the manual pages are outside); a fix that changes any other path is pushed with the push's own plan "
                               "(release fix VERSION --record says which applies), after which the cut goes on from the pushed head. "
                               "Approving it is release plan VERSION --plan TOKEN --approved \"<your go-ahead>\" (the same --date, --keep and --allow-empty-notes): the words are recorded once, with the plan, "
                               "under the state's release directory (PROJECT-VERSION.cut.json), and the audit log gets a release:cut line. Lead only. Then each step is its own verb with --plan TOKEN alone "
                               "(release start, push, finish, site VERSION --plan TOKEN): the words are the record's and appear on that step's audit line, the step runs only when what the plan fixed "
                               "still holds, and each prints the next one. start must find its own plan as it was frozen (the head of the base, the files bumped, the date); push the branch where start left it; "
                               "finish the branch where push left it (the head CI ran on), master and the second target as planned and --keep as planned; site the tag on the commit finish tagged. "
                               "release publish is not a step of the cut: what it creates (the notes and the release files, whose hashes exist only after the tag) is shown by its own plan, so it refuses the cut token (run publish with its own plan and approval). A step that no longer matches "
                               "is refused before anything moves and is run with its own plan and approval (a fix committed after start that changes a path outside fix_paths is pushed that way, release fix --push; one inside them rides the cut); the cut records it and goes on from "
                               "the new state. A step under the cut is the lead's, as approving is: it is refused (exit 2) in a member run and when QARGI_NESTED is set, and a --plan that is not the recorded cut's token (without --approved) is refused naming that a cut is recorded. "
                               "finish is still the push and tag gate: the cut's words are the owner's, and --ignore-checks WORDS at the call is recorded as before. "
                               "Run again, plan shows the recorded cut and which steps ran (release status does too); --again discards it. A cut cannot begin once the branch or the tag exists."),
                         examples=["qargi release plan 0.2.4", "qargi release plan 0.2.4 --date 2026-11-12 --plan TOKEN --approved \"cut 0.2.4\"", "qargi release start 0.2.4 --plan TOKEN"]),
            "start": verb("Cut release/VERSION from develop (hotfix/VERSION from master) and bump the version", [("VERSION", "none")], [PROJECT_OPT, HOTFIX_OPT, opt("--date", "the changelog and man page date (default today)", "YYYY-MM-DD"),
                                                                                                    opt("--allow-empty-notes", "release although the unreleased section of CHANGELOG.md ('## [Unreleased]' by default) is empty"), PLAN, APPROVED, DRY],
                          desc=("Without --approved it changes nothing: it prints the plan (the branch, the base it is cut from and that base's head, the one commit that bumps the version, the files "
                                "the commit changes, the date) and a plan token. Apply it with the same command and --plan TOKEN --approved \"<your go-ahead>\" (the token covers the head of the base "
                                "and the date, so a plan that went stale is refused); the apply creates the branch and writes a line of the audit log. Nothing is pushed. "
                                "The checks below run for the plan too, so a refusal comes before a token does. "
                                "Before anything changes it checks what a release must update and refuses, naming the file and the fix: a man page (man/*.1) needs a .TH line "
                                "with a date and a version field, which the first commit sets to the date and VERSION (the pages are release.man_pages, else man/*.1); a CHANGELOG.md needs content under "
                                "its unreleased heading ('## [Unreleased]', or release.changelog.unreleased). A hotfix does not need that heading when release.changelog.unreleased carries {version} (such a project renames it at a release, so master has none); with any other unreleased heading, the default one included, a master without it is refused for a hotfix as for a release. When it applies, "
                                "the plan says so and the hotfix branch gets the heading for VERSION, empty, above the first heading that follows the released template (else the first of that level, fenced code ignored; at the end when there is none) (the changes are recorded under it on the branch; release finish refuses, before anything is merged, tagged or pushed, while that section of the branch's CHANGELOG.md is missing or empty, and release push runs only the preflight the project set); a release is still refused. The version file is release.version_file (default VERSION; none: no file is bumped). "
                                "release.preflight runs before anything changes; for a hotfix it does not run at start (master does not have the fix, its changelog entry or whatever the check looks for), "
                                "the plan says so, and release push runs it in a copy of the branch before anything is pushed (release.hotfix_preflight, when set, runs there instead of it). A project without a man page or changelog is not checked for that part. A release (not a hotfix) ends by listing what it contains: "
                                "the features merged into develop since the previous tag, the --no-ff merges whose message is \"Merge branch 'feature/...'\", one per line with the short sha. "
                                "When master and the new branch share no history (no merge base: master is one snapshot commit, say) it says so and that release push joins them. "
                                "With the answer release.version_files (a list of paths relative to the repository) it checks, once VERSION is bumped, that each listed file on the new branch "
                                "contains the version (as a whole version: 0.2.1 is not found in 0.2.10) and prints a warning naming the ones that do not: bump these on the release branch "
                                "(release fix makes the worktree). It is a warning, not a refusal, because the files are bumped on the branch start creates; without the answer nothing is checked. "
                                + DRY_NOTE + " For start the temporary worktree in which the plan builds the bump commit is removed again, also when the dry run is interrupted."),
                          examples=["qargi release start 0.2.4 --dry-run", "qargi release start 0.2.4 --dry-run --plan TOKEN"]),
            "status": verb("Show the branch, its commits and whether the whole suite passed at its head", [("VERSION", "none")], [PROJECT_OPT, HOTFIX_OPT],
                         desc=("The full-suite verdict names the command that produced it, when it ran, how long it took and the mode the command names (-j N, shard I/K), from the suite record (a record made before the duration was kept shows the command and the time only). When release.test_command is set and is not that command, "
                               "a line of its own says so: the pass is then not the release gate (release verify runs release.test_command). With declared gates a 'gates:' line lists each with its result at the last run. " + REMOTE_NOTE + " " + TAG_NOTE + " Only when the optional answer release.sign is set (the default is not) and the tag has no GitHub release, it also says 'awaiting signature' "
                               "until qargi release sign recorded a signature that still holds (no signed file or signature changed), and then 'VERSION is ready for signing: "
                               "qargi release sign VERSION' when the repository is at the tag with the files built, or what stands in the way. "
                               "When site.enabled is true a site line says 'site: not built for VERSION', 'site: built at SHA, not pushed' or 'site: pushed' "
                               "(the commit of qargi release site on the site branch, and whether the live origin has it). "
                               "While the release branch exists and the repository has an origin it shows the checks of the branch's pull request (gh pr checks, through QARGI_GH): "
                               "a verdict and one line per check with its state, pass, fail or pending; a missing gh, no pull request or no checks is a warning. "
                               "With release.version_files set, a line says that every listed file contains VERSION on the branch, or warns of the ones that do not (bump these on the release branch). "
                               "A branch that shares no history with master (no merge base) gets a warning that release push joins it. "
                               "For a tag that exists it ends with a checklist of what is left after the release: whether origin has the tag, whether the GitHub release is published or missing, "
                               "for each entry of the answer release.assets ({version} replaced; a glob by its base name) whether the release has it, for each file of release.sign.files whether its .sig is attached (UNSIGNED when not), "
                               "and the project's own after-steps: the ones release finish recorded, else the optional answer release.after_steps ({version} replaced). Each is shown "
                               "as '[done] NAME (WHO, TIME, evidence: TEXT)' or '[pending] NAME (WHO): COMMAND', the done ones first and the pending ones last; a pending step of the owner reads "
                               "'waits for the owner: run COMMAND', and a step that needs evidence says so. qargi release step marks one done; the list is kept in a file under the state directory.")),
            "verify": verb("Run the project's whole test suite on the release branch (develop's head before it starts) and record the result", [("VERSION", "none")],
                           [PROJECT_OPT, HOTFIX_OPT, opt("--strict", "refuse, before anything runs, when a CI job matches no declared gate name"), WAIVE_ENV_OPT, PLAN, APPROVED],
                           desc=TAG_NOTE + " The exit status stays the suite's result. The command is release.test_command when the project sets one, else test_command. " + GATES_NOTE + " " + ENV_NOTE + " "
                                 "Before it runs, it reads the workflow files of the tree it verifies (.github/workflows/*.yml and *.yaml; standard library only, no YAML library: the job ids under jobs: and the name: line of each job) "
                                 "and warns on standard error, naming each job whose name and id match no declared gate name, is not listed in a gate's ci_jobs and is not listed in the optional answer ci.not_gates (the jobs that are aggregate or publish jobs and not gates). "
                                 "A job a gate lists in ci_jobs is reported as a note, covered by that gate. With no gate declared it prints one note naming the jobs instead of a warning each. "
                                 "A name listed in ci_jobs or ci.not_gates that no workflow has is a warning. A job whose name cannot be read (an expression, a block scalar, a flow mapping) "
                                 "is reported as unknown, a note and never a failure. --strict refuses (exit 1, nothing run) when any job matches no gate name (the listed ones match), also with no gate declared. Without a workflow it prints nothing new. "
                                 "On the release branch, with release.version_files set, it also shows whether every listed file contains VERSION (a warning for the ones that do not). " + OTHER_RUNS_NOTE + " " + SUITE_FAIL_NOTE),
            "fix": verb("Make a worktree on the release branch to commit a fix in, and push the fix again with --push", [("VERSION", "none")],
                        [PROJECT_OPT, HOTFIX_OPT, opt("--push", "push the committed fix: the same as release push (the plan token and approval below)"),
                         opt("--record", "journal the commits made with git on the branch, and say whether they are inside the cut: the lead's, no plan, no token, no approval; exclusive with --push, --plan and --approved"),
                         PLAN, APPROVED, DRY],
                        desc=("For the pull request whose checks failed, or a change review asked for. Without --push it creates the worktree of release/VERSION (hotfix/VERSION with --hotfix) "
                              "under the worktree root (worktrees.root, default <state>/worktrees/<project>/<branch>), prints 'worktree: PATH' and the next step, and changes nothing else; "
                              "run again it names the same worktree. Fix there, commit on the branch, then run it with --push (or release push), which asks for a plan token and an approval, "
                              "pushes the branch and updates the open pull request, whose checks run again. Refused when the branch does not exist or the tag VERSION does (then it is a hotfix). "
                              "release finish removes the worktree with the branch when it is clean. "
                              "--record is a record of fact, like ref note: the lead's (a member run, and a call nested in an approved apply, are refused, exit 2), with no plan, no token and no approval, "
                              "and exclusive with --push, --plan and --approved (a usage error, exit 2). It journals the commits made with git on release/VERSION (hotfix/VERSION with --hotfix) in the ref journal, "
                              "with or without a cut, so a run prepared before them verifies; the head of the branch must follow the cut's anchor (the latest of the heads recorded for fix, push and start) along first parents, "
                              "else it is refused with cut-branch-moved. Then it says where the commits stand. With a live cut it checks every commit since the anchor against the paths the cut plan names, "
                              "fix_paths (release plan prints them: the directory of release.changelog.fragments when set, CHANGELOG.md, release.version_file and each of release.version_files; "
                              "docs/ and the manual pages are outside, a manual page being generated from the code): when all are inside it records fix in the cut and says 'inside the cut: push goes on under its approval'; "
                              "otherwise it records nothing in the cut and prints the notice cut-fix-outside with the commits that leave the paths (three and +N), 'outside the cut: push will take its own plan'. "
                              "It exits 0 either way: the journal is written and nothing was asked. Release push and fix --push make the same catch-up and the same check, so a lead who never ran --record "
                              "gets the same answer: inside, the push passes under the cut's token and records fix and push; outside, the cut's token is refused with cut-fix-outside, and release push VERSION without it "
                              "has its own plan, which lists every commit since the anchor and takes the owner's approval. A push under its own approval records the push in the cut (head and own_plan) and leaves the cut live, "
                              "anchored at the pushed head: the commits before it are no longer counted, and a later fix inside the paths goes on under the cut again. "
                              + DRY_NOTE + " With fix it is for --push only (a usage error, exit 2, without it)."),
                        examples=["qargi release fix 0.2.4", "qargi release fix 0.2.4 --record", "qargi release fix 0.2.4 --push --dry-run"]),
            "push": verb("Push the branch and open the pull request into master", [("VERSION", "none")], [PROJECT_OPT, HOTFIX_OPT, PLAN, APPROVED, DRY],
                         desc=REMOTE_NOTE + " When release.notes_file is set the plan reads that file and the VERSION section of CHANGELOG.md at the head of the branch and warns of the items of the section that the file "
                              "does not mention (never a refusal; the plan still has its token). An item is a line at the margin that starts with -, *, + or a number and a dot; it is mentioned when its leading `backticked term`, "
                              "else its first three words, occurs in the file, ignoring case and spacing. A notes file that is not on the branch is a warning. When release.preflight is set it runs in a copy of the branch once the plan is approved, before anything is pushed; a non-zero exit refuses. "
                              "When a pull request for the branch is open already (found with gh pr list; a gh that cannot list it is caught by the refusal of gh pr create) the plan says so, "
                              "nothing is opened and the result reads 'updated PR #N'; a worktree of the branch with uncommitted changes is a warning, only what is committed is pushed. "
                              "When master and the branch share no history (no merge base: git would refuse to merge unrelated histories, as with a master that is one parentless snapshot commit) "
                              "the plan has the line 'join the history of master': once approved, master is merged into the branch with -s ours --allow-unrelated-histories, in a temporary worktree, "
                              "as a new commit after the version bump and before the push, so CI runs on the joined head and release finish is an ordinary --no-ff merge. The tree of the branch must be the same "
                              "before and after (checked, with the parents of the commit); otherwise nothing moves and nothing is pushed. The plan token covers the join and master's head. "
                              "A branch that is checked out in a worktree with uncommitted changes is refused for the join. "
                              "When the project's answer release.changelog.fragments is set and the directory at the head of the branch still holds a fragment, or the section of VERSION in CHANGELOG.md has no notes, is missing, "
                              "or CHANGELOG.md is missing, it refuses with release-fragments-unfolded: fold them in the fix worktree, commit, then qargi release fix VERSION --record. "
                              "Commits since the cut last stood that change a path outside the cut's fix_paths refuse the cut's token with cut-fix-outside (see release fix --record). " + DRY_NOTE,
                         examples=["qargi release push 0.2.4 --dry-run", "qargi release push 0.2.4 --dry-run --plan TOKEN"]),
            "finish": verb("After the checks pass: merge into master, tag, merge the tagged commit back, delete the branch, push", [("VERSION", "none")],
                           [PROJECT_OPT, HOTFIX_OPT, opt("--keep", "keep the branch"),
                            opt("--ignore-checks", "finish although the pull request's checks fail, are pending or cannot be read; WORDS are your reason, in your own words, recorded in the output and the audit log", "WORDS"),
                            PLAN, APPROVED, RESOLVED_OPT],
                           desc=("The plan lists the checks of the branch's pull request (gh pr checks: one line per check, pass, fail or pending) and refuses, without a token, while one fails or is pending, "
                                 "unless --ignore-checks WORDS is given; the plan token covers the words. A missing gh, no pull request or no checks is a warning in the plan, and the apply then refuses "
                                 "(the checks are read again) unless --ignore-checks is given. A clean worktree that release fix made is removed with the branch. "
                                 "The second merge is of the master merge commit that carries the tag (message \"Merge tag 'VERSION' into develop\"); it may conflict, usually over the version number (the model says so), "
                                 "and the message then names the tag and the short sha of that commit, which is kept in a .master file beside the worktree and used again only when it is a merge of the current master and the branch head. "
                                 "Nothing moves then: resolve in the worktree "
                                 "the message names, which holds a merge of that commit, commit, and run the same command with --resolved. It refuses a branch whose manual page has an empty .TH date or version, "
                                 "and, when release.version_file is none, one whose changelog has no section for VERSION. When release.finish_check is set the plan lists it, and once the plan is approved it runs in a copy of the branch before any merge, tag or push "
                                 "(a non-zero exit refuses with the tail of its output; nothing was merged, tagged or pushed). It also refuses, with the fix, a branch that shares no history with master (no merge base): "
                                 "run release push first, whose plan joins the history of master. " + REMOTE_NOTE + " "
                                 "When the answer release.after_steps lists steps (a string, or an object {name, command, who, evidence}; {version} replaced), it prints each as an 'after the release: [pending] NAME (WHO): COMMAND' line, never runs them, and "
                                 "records them as pending under the state's release directory (PROJECT-VERSION.after.json) for release status and release step. "
                                 "It ends with a 'next: ...' line for each after_release step of the methodology whose answer is true: with site.enabled, "
                                 "'next: qargi release site VERSION'.")),
            "step": verb("Mark an after-release step of VERSION done, with the evidence", [("VERSION", "none"), ("NAME", "none")],
                         [PROJECT_OPT, opt("--evidence", "what shows the step was done, one line (a line to quote); required when the step's answer has an evidence", "TEXT"),
                          opt("--again", "record a step that is marked done already once more")],
                         desc=("NAME is the name of a step of the answer release.after_steps as release finish recorded it for VERSION (a string step is named by its text; {version} replaced). "
                               "It records the time and the evidence text in the record under the state's release directory (PROJECT-VERSION.after.json), which release status shows as "
                               "'[done] NAME (WHO, TIME, evidence: TEXT)'. It changes only that record: it never runs the step's command, which is the lead's or the owner's to do first. "
                               "Refused: a step that needs evidence (its answer has an evidence) without --evidence; a NAME or VERSION the record does not have (the message lists the names); "
                               "a step already marked done, unless --again. A lead's verb: a member's guard refuses it."),
                         examples=["qargi release step 0.2.3 'announce 0.2.3 to the list'", "qargi release step 0.2.3 'post the notes' --evidence 'the address of the post'"]),
            "assets": verb("Build the release files of the tag VERSION in a clean worktree of it, with the project's release.assets_command", [("VERSION", "none")],
                           [PROJECT_OPT, opt("--recreate", "remove the existing asset worktree of VERSION and build again from the tag")],
                           desc=("Makes a clean detached worktree of the tag VERSION under the state directory (release-assets/PROJECT-VERSION), runs the answer release.assets_command in it "
                                 "(a command line, run by bash -c, or a list of words with {version} replaced and no shell; QARGI_RELEASE_VERSION is set) and records the worktree, so the "
                                 "repository's own checkout is never touched. It prints where the files are and the next command: qargi release sign VERSION when release.sign is set, "
                                 "else qargi release publish VERSION. release sign and release publish then take the files from the worktree: release.sign.files, release.assets "
                                 "and relative --asset or --asset-dir names are looked up there. Refused when release.assets_command is not set, when the tag is missing, when the "
                                 "worktree exists already (--recreate removes it and builds again; its files may be signed) and in a member run or when QARGI_NESTED is set (exit 2). "
                                 "A command that fails leaves the worktree for you to look at and records nothing. It changes no branch and needs no plan token: it runs the command "
                                 "the lead put in the answers."),
                           examples=["qargi release assets 0.2.3", "qargi release assets 0.2.3 --recreate"]),
            "sign": verb("Sign the release files from the tag with your own key, on your own terminal, and record that they verify", [("VERSION", "none")], [PROJECT_OPT],
                         desc=("Signing is optional and off by default: it applies only to a project whose answers hold release.sign (otherwise this exits 2 and nothing else changes). "
                               "Run it in your terminal, in the project's repository checked out at the tag (git checkout --detach VERSION, with the release files built from it), or after qargi release assets VERSION, "
                               "which builds them in a worktree of the tag that sign then uses in place of the repository (the files are signed, verified and recorded there): "
                               "after finish, before publish. For each file of the answer release.sign.files it runs ssh-keygen -Y sign -f KEY -n NAMESPACE FILE attached to "
                               "your terminal (stdin, stdout and stderr are yours; nothing is captured and no input is logged), so you type the key's passphrase there and it "
                               "never passes through qargi, a log or an agent; no ssh agent is asked. Then it runs release.sign.verify_command (a list of words, no shell) in the "
                               "repository and records the result, the tag's commit and the hash of every signed file and signature under the state's release directory. "
                               "Refused (exit 1) when stdin is no terminal, HEAD is not exactly the tag VERSION, on a branch other than master, or a tracked file is modified; "
                               "refused (exit 2) in a member run, when QARGI_NESTED is set or when release.sign is not set. A member run cannot sign. The answers: release.sign.key (an ssh private key), "
                               "release.sign.namespace, release.sign.files (relative to the repository) and optionally release.sign.verify_command.")),
            "publish": verb("Create the GitHub release of an existing tag, with its changelog section (or a notes file) as the notes and the assets attached", [("VERSION", "none")],
                            [PROJECT_OPT, PLAN, APPROVED,
                             opt("--asset", "attach this file to the release; repeat for several, on top of the answer release.assets. A relative name is taken in the release asset worktree (qargi release assets) when there is one, else in the repository; a full path must lie in a worktree of the repository", "FILE"),
                             opt("--asset-dir", "attach every regular file of this directory (not its subdirectories), named like --asset; repeat for several", "DIR"),
                             opt("--notes-file", "take the notes from this file (relative to the repository) instead of the changelog section; the answer release.notes_file does the same", "FILE")],
                            desc=("For a tag that has no GitHub release, for example one pushed before the release workflow existed. The plan shows the tag, its commit, "
                                  "the notes (the VERSION section of CHANGELOG.md at the tag, found by release.changelog.released, or the notes file), the sha256 of every asset and the command: gh release create VERSION "
                                  "--verify-tag --title \"PROJECT VERSION\" --notes-file FILE ASSET... (gh is run through QARGI_GH, default gh, and must be logged in); the token covers "
                                  "the notes and the assets. The assets are --asset, the files of --asset-dir and release.assets (names or globs, {version} replaced; a glob that matches nothing refuses), regular files inside the asset worktree "
                                  "of qargi release assets, the repository or another worktree of it (a symbolic link that leaves them, a path with a .git component and two files of one base name are refused), attached by the same call that creates the release. "
                                  "It refuses when GitHub has the release already, when the tag is missing, when the notes are empty, and, when the answer release.sign is set, until "
                                  "qargi release sign recorded an ok for VERSION and none of the signed files or signatures changed since (without release.sign, which is the default, there is no such wait); --verify-tag makes gh refuse a tag that is not on origin. "
                                  "Needs the plan token and an approval; a member run cannot publish. The token of a release plan (the cut) is refused for it: publish has its own plan.")),
            "site": verb("Build the documentation site of the tag VERSION and commit it on the detached site branch; never pushes", [("VERSION", "none")],
                         [PROJECT_OPT, PLAN, APPROVED],
                         desc=("Only when the answer site.enabled is true. The source is the tree of the tag VERSION (its CHANGELOG.md, VERSION, README.md and "
                               "lib/commands.py, from which the reference is generated); the hand pages and site.json are those of the site branch (site.branch, "
                               "default gh-pages when repo.detached lists it; site.config, default site/site.json, with the hand pages in pages/ beside it). "
                               "lib/site.py builds it in a temporary worktree of the site branch: the site.json records release VERSION. The build checks the site, "
                               "but its output (_site/) is not committed, because a Pages build of the branch needs _site/ empty; a _site/ that an earlier build "
                               "committed is removed by the commit. The plan shows the build's warnings and the size of the change, and the token covers the tag, the branch's tip and the tree to commit; "
                               "the apply commits it as 'Site: built from release VERSION' and moves the branch, touching no working tree, and prints the git push "
                               "command for you to run. With an origin it first asks origin live for the branch (git ls-remote, at most QARGI_REMOTE_TIMEOUT seconds; "
                               "the remote-tracking ref when origin does not answer, and it says so) and writes a release:site line to the ref journal for the push it prints, "
                               "from what origin had to the commit just made, so a run prepared before the push still verifies once you push exactly that commit; "
                               "without an origin nothing more is journaled. Nothing is committed when the build is already there. Refused when the branch is checked out somewhere, "
                               "when the tag is missing and when the build reports an error; refused (exit 2) in a member run and when QARGI_NESTED is set."),
                         examples=["qargi release site 0.2.3", "qargi release site 0.2.3 --plan TOKEN --approved \"yes, commit the site\""]),
        },
    },
    "doctor": {
        "summary": "Check this host for what makes qargi fail quietly: logind, the guard, /dev/shm, the tools, the install records, the window table",
        "desc": ("Read-only, and a member may run it. It prints one line per check, `ok|warn|unknown  name: detail`, and after a warning the indented lines that say what you can do; "
                 "it changes nothing and runs none of the fixes. It does not fail on a finding: the exit status is 0, or 1 with --strict when any check warns (2 for a usage error "
                 "or a project that is not stored). A check that cannot be made (no logind, a tool that is missing, no project) says unknown, never warn. The project is the one "
                 "named, else the one in effect; without one the checks that need it say unknown. The checks: "
                 "remove-ipc: the logind setting RemoveIPC (busctl; QARGI_BUSCTL names another program) with the user's linger (loginctl; QARGI_LOGINCTL); with RemoveIPC on and "
                 "no linger, logind removes the user's IPC objects, among them what lives in /dev/shm, when the last session ends, and the warning prints the drop-in "
                 "/etc/systemd/logind.conf.d/remove-ipc.conf (`[Login]`, `RemoveIPC=no`) with `sudo systemctl reload systemd-logind`, or `loginctl enable-linger USER`. "
                 "guard: `qargi` is found on PATH and `qargi __guard` answers as the guard does (it allows a harmless call and refuses git push), and with a project, no member is "
                 "missing, stale or edited (the states of qargi agent list). "
                 "shm: the free space under /dev/shm (QARGI_RUN_TMP moves it) and the orphaned qargi-run.* directories there, the listing of qargi local clean --orphans; it warns on "
                 "an orphan or on less than 10% free (QARGI_DOCTOR_MIN_FREE moves the limit, in percent). "
                 "window-source: where the context-window table of the project's local runtime comes from (its definition, or the answer lead.context_window, which overrides the "
                 "table: the table gives the API's window, which the product may cap lower on some plans) "
                 "and whether each model id its roles name is in the table, and the model of the lead's own session (the last turn of its transcript, read only) unless the answer is set; an id that is not there warns, since its window is only assumed, "
                 "while a lead model that cannot be determined (no transcript, no counted turn, no model id) is not a warning. "
                 "verify-environment: whether the project declares verify.environment, as 'off' or as 'on' with the version of systemd-run (read with systemd-run --version; nothing is started); "
                 "it warns on a systemd-run that is missing or older than 254 while the declaration is on with the cpu part on (cpu_quota not null), on a declaration that differs from the one accepted for the project or is invalid, "
                 "and on the file of accepted declarations (verify-env.json in the state directory) when it cannot be read. "
                 "tools: flock (the locks of the finishing verbs and the ref journal) and timeout (the bound on a question put to a remote) are on PATH; a missing one warns and names what it is for and "
                 "the package that has it (util-linux, coreutils; make bootstrap installs both). "
                 "install: the install records of install.sh (install.d, install.json), read only: the installed tool with its source and version and every runtime installed for the user and in a project; "
                 "it warns on a recorded link or copy that is missing, dangling or now points elsewhere, on a recorded version other than the tool's VERSION, on a record that cannot be read, on a record that lacks the tool "
                 "(install.json without a tool_root, or runtimes recorded with no install.json) or its runtimes (install.json names the tool but no user runtime is in install.d), and on a leftover "
                 "install.manifest or project-N.manifest from 0.3.1 or earlier, which is no longer read and can be removed by hand after checking install.d (unknown when nothing is installed). "
                 "project-env: the last qargi env check recorded for the project in state/env/PROJECT.json, as 'last env check VERDICT at TIME' (a warning when the verdict is not ENV OK; "
                 "unknown, 'never run', when none was recorded). It only reads that record and never runs the project's code: qargi env check is what runs the project's doctor and records the result. "
                 "--json prints {project, checks: [{name, status, detail, fix}], warnings, strict, exit}."),
        "scripts": ["doctor.py", "orphans.sh"],
        "usage": [("PROJECT", "project", True)],
        "opts": [PROJECT_OPT, opt("--strict", "exit 1 when any check warns (the default exit status is 0)"), opt("--json", "print the checks as JSON")],
        "examples": ["qargi doctor", "qargi doctor acme --strict", "QARGI_RUN_TMP=/dev/shm qargi doctor --json"],
    },
    "env": {
        "summary": "What a repository declares about its development environment",
        "desc": ("qargi defines no file for this. A project declares its environment with a section of AGENTS.md (or README.md) headed "
                 "Development environment, Environment or Setup, the version pins in the standard files, and two runnable targets: bootstrap "
                 "(install or update, idempotent) and doctor (check only). qargi reads them; see qargi help environment."),
        "scripts": ["env.py", "env_check.py"],
        "verbs": {
            "show": verb("Print what was found (section, pins, submodules, runner, targets) and the commands in effect", [],
                         [PROJECT_OPT, opt("--repo", "the repository directory (default: the project's repo.path, else the repository around here)", "DIR", "dir"),
                          opt("--json", "print the result as JSON")],
                         desc=("Read-only, and a member may run it. Nothing is executed: make, just, task and mise are never run, their files are read as text "
                               "(at most 1 MB each; a symbolic link that leaves the repository is refused). The commands are derived from the targets "
                               "(make bootstrap, make -n bootstrap, make doctor) and replaced by the project's answers env.doctor_command, "
                               "env.bootstrap_command and env.dry_run_command; env.known_failures lists doctor lines accepted on this host. Each line says where it came from."),
                         examples=["qargi env show", "qargi env show --project acme --json", "qargi project set acme env.doctor_command 'make doctor'"]),
            "check": verb("Run the project's doctor, add the qargi layer (links, members, packs, memory) and print ENV OK or ENV INCOMPLETE", [],
                          [PROJECT_OPT, opt("--repo", "the repository directory (default: the project's repo.path, else the repository around here)", "DIR", "dir"),
                           opt("--timeout", "seconds the doctor may run (default 300, at most 3600)", "SECONDS"), opt("--json", "print the result as JSON")],
                          desc=("A member may run it. It RUNS THE PROJECT'S CODE: the doctor command (env.doctor_command, else the doctor or check target) is run once, "
                                "without a shell, in the repository, with standard input closed and a minimal environment, so the repository is as trusted as it is for "
                                "test_command. Its lines are read: one that begins with missing, fail, error, not ok, stale, [x] or a cross mark, or ends with missing, "
                                "not found or not installed, is a missing item; one that begins with expected or contains an env.known_failures entry is expected "
                                "and not red; a non-zero exit with no such line is one missing item. With no doctor command a built-in minimum runs: submodules "
                                "initialised, tags present when the repository has a remote and releases, and every tool a pin file names found on PATH, answering "
                                "--version and matching the pin's major.minor (this runs TOOL --version). For a stored project it then checks the tools the roles declare (roles.ROLE.tools): "
                                "a go tool or a binary that is not installed, is another version (go version -m) or another file (sha256) or sits in a directory PATH lacks, and a declared "
                                "submodule that is not initialised or at another commit, are missing items. It adds, read-only, whether the checkout "
                                "loads the project's skills, agents and memory, whether the members are current (STALE, DRIFT), packs check and memory check. "
                                "The last line is ENV OK or ENV INCOMPLETE: N missing (...); exit status 0, 1 or 2 (usage, no such project, no repository). "
                                "The verdict, HEAD, time and commands are recorded under check in state/env/PROJECT.json (mode 600, the other keys are kept); no command output is. "
                                "qargi doctor PROJECT shows that record as its project-env line (it reads it and runs nothing of the project's)."),
                          examples=["qargi env check", "qargi env check --project acme --timeout 60", "qargi env check --repo ~/src/acme --json"]),
            "plan": verb("Run the dry run of the bootstrap, show it grouped by privilege, print a plan token (the lead's; runs project code)", [],
                         [PROJECT_OPT, opt("--repo", "the repository directory (default: the project's repo.path, else the repository around here)", "DIR", "dir"),
                          opt("--approve-exec", "the executable of the dry-run command (make for make -n bootstrap); without it nothing is run and the exit status is 2", "NAME")],
                         desc=("A dry run is not harmless: make -n still expands $(shell ...) and runs recipe lines marked + or holding $(MAKE), and the dry run "
                               "of the other runners evaluates project code too. So the plan itself runs project code, and needs --approve-exec naming the "
                               "executable; read the project's files first. The command runs without a shell, in the repository, with standard input from /dev/null, "
                               "a minimal environment (PATH with absolute entries, HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE, TERM, TZ, TMPDIR) and a limit of "
                               "QARGI_ENV_TIMEOUT seconds (default 120). Its output is shown line by line, the privileged lines (a command in the line is sudo, doas, "
                               "pkexec, su or run0) apart from the others, then the executables seen in the lines. Lines and executables are read from the text, "
                               "best effort: a recipe can run more than its dry run shows. Then the tools the roles declare (roles.ROLE.tools), each with its state here "
                               "(ok, missing, wrong, path: in a directory PATH lacks); apply installs the go tools and binaries that are missing or wrong, so the token line "
                               "names go in --approve-exec when a go tool is among them. The plan token is a hash over the output, the commands, the tools, the repository "
                               "and its HEAD, and the host name. A member's guard refuses it."),
                         examples=["qargi env plan --approve-exec make", "qargi env plan --project acme --approve-exec make"]),
            "apply": verb("Run the bootstrap command once, for a plan you showed (the lead's)", [],
                          [PROJECT_OPT, opt("--repo", "the repository directory (default: the project's repo.path, else the repository around here)", "DIR", "dir"),
                           PLAN, APPROVED,
                           opt("--approve-exec", "name the executables of the dry-run and the bootstrap commands, and go when the plan installs a go tool, separated by commas (others the plan listed may be added)", "NAMES"),
                           opt("--allow-root", "allow a plan that has privileged lines (sudo, doas, ...)")],
                          desc=("Runs the dry run again (project code, as plan does) and refuses when its token is not --plan, when --approve-exec does not name the two "
                                "executables, and when the plan has privileged lines and --allow-root is not given. Then the bootstrap command runs once, without a "
                                "shell, with the minimal environment of plan and with standard input, output and error inherited, so sudo can ask on your terminal: run "
                                "it in a terminal you are at. No password is read or kept. Apply writes two lines to the audit log (start and result, with your words), "
                                "then installs the declared tools the plan showed as missing or wrong: go install NAME@VERSION for a go tool, and for a binary the file at its URL, downloaded to a temporary name, "
                                "kept only when its sha256 is the declared one, made executable and moved to ~/.local/bin/NAME (a failed tool is named, the others still run, exit 1). "
                                "It records the run in ~/.qargi/state/env/NAME.json (mode 600) and then runs qargi env check (the project's doctor), whose verdict ends the output and whose exit status is the verb's. QARGI_DRY_RUN stops it "
                                "after the checks, before the bootstrap runs. A member's guard refuses it."),
                          examples=["qargi env apply --plan 0123456789ab --approved \"install the tools\" --approve-exec make,go",
                                    "qargi env apply --plan 0123456789ab --approved \"go\" --approve-exec make,pacman --allow-root"]),
        },
    },
    "provision": {
        "summary": "Create the cloud agent, deployment and environment of an instance",
        "desc": ("Renders the agent, the shared environment, the memory stores it attaches and a manual-run deployment, "
                 "shows the plan, and creates them only with your go-ahead. Names follow qargi help naming. Provision the "
                 "role agents first; the lead (PROJECT-lead) needs them to exist. When the project's repository is on this host and declares a bootstrap "
                 "command, plan also prints it as suggested text for the environment's setup script; it is only printed, never run."),
        "scripts": ["provision.sh"],
        "verbs": {
            "plan": verb("Render the files and print the plan (changes nothing)", [("NAME", "instance", True)],
                         [opt("--project", "the project, instead of NAME", "PROJECT", "project"), opt("--role", "the role, or a base (worker, reviewer); default build", "ROLE", ROLES + ("worker", "reviewer")),
                          opt("--model", "model id, overriding the project's answers", "MODEL", "model"), opt("--effort", "effort level", "LEVEL", EFFORTS),
                          opt("--apt", "extra packages for the shared environment, space separated", "PACKAGES"),
                          opt("--networking", "the sandbox's network access", "MODE", ("unrestricted", "limited")),
                          opt("--budget", "spend ceiling of the deployment, in cents", "CENTS", "cents"),
                          opt("--memory-store", "attach this memory store instead of the project's", "ID", "store"),
                          opt("--reference-store", "attach this reference store", "ID", "store"),
                          opt("--force", "overwrite what changed on the server outside this config since the last apply (ant apply --force); the plan token covers it, so give it to plan and to apply")],
                         examples=["qargi provision plan acme-write"]),
            "apply": verb("Create the resources of an approved plan", [("NAME", "instance", True)],
                          [ASKED, PLAN, APPROVED, opt("--project", "the project, instead of NAME", "PROJECT", "project"), opt("--role", "the role, or a base (worker, reviewer)", "ROLE", ROLES + ("worker", "reviewer")), opt("--force", "overwrite what changed on the server outside this config since the last apply (ant apply --force); the plan token covers it, so give it to plan and to apply")],
                          desc="Brings new memory stores to the canon, seeds the roles, records the ids and registers the instance."),
            "add-reference": verb("Create and attach a reference store to an existing instance", [("NAME", "instance")], [ASKED, APPROVED]),
        },
    },
    "instances": {
        "summary": "Register, inspect and manage agent instances",
        "desc": ("An instance is <project>-<role>, for example acme-build, or the lead acme-lead. The registry records where it "
                 "runs and which resources it uses. Cloud operations follow the request and approval requirements documented by each verb."),
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
                 "guard refuses the verbs new, import, seal, remove, link, unlink, accept, unaccept, enable and disable, and writes in the pack library, "
                 "and QARGI_NESTED does not stand in for the plan token of import and seal."),
        "scripts": ["packs.sh"],
        "verbs": "PACK",
    },
    "tool": {
        "summary": "Create or import tools (MCP servers with an allowlist) and attach them by scope",
        "desc": ("A tool is an MCP server with an explicit list of allowed tools and a permission policy for each: always_allow, always_ask or auto. "
                 "The tools are named as the server names them: letters, digits and _ . - / (platform.list_items, repo/push). A write-like tool "
                 "cannot run unattended (always_allow or auto) unless the pack is marked write_ok. A tool is write-like when a word of its name "
                 "starts with create, update, delete, remove, post, push, write, merge, send, set, add, edit, close or comment, however the name is "
                 "spelled: the words are cut at every character that is not a letter and at a camelCase boundary (delete_item, "
                 "platform.delete_knowledge, repo/push, issue-close, deleteItem). A write word inside a word does not count (offset), nor do the "
                 "words settings, setting, address, addresses, postal, postcode, postcodes, additional and closest. With the server's own tool "
                 "listing (tool import or tool seal with --tool-list FILE) a tool it does not mark readOnlyHint true cannot run unattended either. "
                 "A member is given the MCP tools of the tool packs that reach its roles (qargi agent refresh after a link, an unlink or a seal), "
                 "under the names the runtime gives them, and its guard judges every call of one: a tool of no pack linked to the role, a tool "
                 "of a pack that changed since its approval and an always_ask tool are refused, and a read-only run calls only declared reads "
                 "(always_allow, a name that is not write-like, and readOnlyHint true where a listing was recorded). "
                 "Everything else works as for skills (qargi help skill)."),
        "scripts": ["packs.sh"],
        "verbs": "PACK",
    },
    "packs": {
        "summary": "Render, load or apply the skills and tools a role gets",
        "scripts": ["packs.sh"],
        "verbs": {
            "member-skills": verb("Opt in to canonical role-specific member skill snapshots", [("PROJECT", "project")],
                                  [opt("--enable", "enable snapshots"), opt("--disable", "disable snapshots without loading new content"), PLAN, APPROVED],
                                  desc=("Absent packs.member_skills is off. With neither choice, show status read-only; --enable and --disable are mutually exclusive. Changes need the recomputed plan token and approval and refuse member callers. "
                                        "The enable plan inventories currently dispatchable known work roles, including library roles without project entries, with canonical names and approval hashes. Invalid or unavailable role metadata is distinguished. The recomputed plan binds that inventory, project, old/new booleans, runtime composition, links, exclusions and bounded file identities; future roles use ordinary authorized prepare and current qualification. "
                                        "Only composed command runtimes with dispatch.home.skills_dir qualify structurally; actual loading remains unqualified. Prepare freezes a private role-specific snapshot, including an empty one. "
                                        "Four canonical scopes reach matching roles; broad user/project links reach each role, role-specific lead links stay out. Raw installed/checkout skills and rendered unions never select snapshots. "
                                        "Before launch, content/approval, relevant selection, opt-in or runtime drift requires re-prepare. After native begin, delivery populates private staging through descriptors and publishes by identity-checked atomic no-replace rename; run and private state must share a filesystem. Cleanup requires recorded group quiescence and validates staged identity before one-filesystem deletion. Absent delivery under its matched original parent can retire state after begin; dry-run never recovers it. Replacements preserve data/evidence and refuse without adoption. Interrupted cleanup can resume on normal --again. This cooperative Linux/OS boundary trusts controller-only private state and excludes escaped groups, arbitrary hostile same-user/root mutation and inode reuse as an independent identity proof. Save/verify validate frozen manifest identity, bytes, modes and generation independently of current configuration/review, granting no launch permission. "
                                        "MCP authority stays unchanged. A client can independently discover committed checkout skills or read other files under its qualified contract; pack prose grants no permission. "
                                        "Validate linked names and skill count before body reads; accumulate cross-pack entry and byte limits during collection. Incompatible packs contribute bounded compatibility facts, no delivered bytes, and need no approval or body review until included. Bounds: 64 skills, 4096 entries, 2,000,000 bytes/file, 16 MiB total and 1 MiB manifest; canonical per-pack review limits also apply.")),
            "render": verb("Write what a role gets into a directory (used by provisioning)", [("PROJECT", "project"), ("ROLE", "role"), ("OUTDIR", "dir")]),
            "load": verb("Show what a role has enabled, or print one pack's text", [("[PACK]", "pack")], [opt("--role", "the role whose packs (required)", "ROLE", ROLES), opt("--project", "the project (default: inferred from here)", "PROJECT", "project")],
                         desc="Read-only, and evaluated from the links when called, so enabling or disabling a pack takes effect at once. Refuses a pack that fails its review or changed since it was approved."),
            "apply": verb("Update an existing cloud agent, or render for a local runtime", [("INSTANCE|PROJECT", "instance")], [TARGET, ASKED, PLAN, APPROVED],
                          desc=("Without --target (or with managed-agents) this updates the existing cloud agent INSTANCE with its skills and tools; "
                                "the lead's GitHub tool arrives this way when the project grants a cloud push. It needs --asked, and always needs --plan "
                                "(QARGI_NESTED does not skip it); a local member's guard refuses it.\n"
                                "With --target claude-code it takes PROJECT instead of INSTANCE and needs no --asked. Any eligible local target works the same way: TARGET is session.render_target in the existing provider registry. "
                                "The member runtime resolves its own target directly; a secondary target must identify exactly one local runtime with a valid sealed definition, "
                                "verified skills capability and project skills layout. Inapplicable project extensions refuse a secondary target. No member runtime or profile changes. "
                                "Without --approved it prints a plan token. With --plan and --approved it renders compatible enabled packs into $QARGI_STATE/render/PROJECT/RUNTIME (claude-code for this target), "
                                "replacing that runtime's render atomically. Renders live side by side; their skills, MCP and settings paths come from provider resources. "
                                "The plan names project, runtime, target, selected resources and included/skipped packs, and prints the definition's launch line when available. "
                                "For this example the launch line is `claude --add-dir ...` with MCP/settings flags when needed. "
                                "Skills render under .claude/skills in this example; the definition chooses all resource paths. "
                                "Role scoping is advisory: skills include the member-role union and lead-only instructions; MCP permissions retain the member-role union without lead. "
                                "Every included skill needs a present canonical library approval matching its content hash, including lead-only skills on every local target. Passing review or approving this render cannot replace that prior approval; refusal preserves the live render. "
                                "Rendered resources go to the selected runtime's state tree. Member write protections depend on the runtime's qualified sandbox and guard coverage.\n"
                                "The plan refuses, naming the pack and writing nothing, a skill whose SKILL.md name differs from the pack name, whose "
                                "front matter is not closed or has more than one name key; a skill and a tool with the same name; and a tool allowlist "
                                "name outside letters, digits, _, . and -. Each plan stages into its own hidden directory and a lock serializes "
                                "concurrent applies; the second refuses if the render changed meanwhile. The swap installs only the tree the token "
                                "approved; the manifest and token bind project, runtime, target, composed definition and file modes. A foreign manifest refuses replacement. "
                                "Metadata without runtime identity is supported conservatively only for the member runtime; a fresh plan upgrades that metadata.")),
            "seed": verb("Add or update the baseline packs shipped with qargi in your library", [],
                         [opt("--install", "only add the packs the library lacks, without a token (install.sh --user runs this)"), PLAN, APPROVED],
                         desc=("qargi ships a few packs (packs/ in its tree). Seeding stores them in your library. Without --approved it prints one line per pack "
                               "(add, update, current or kept) and a plan token. A pack you edited and sealed, or one of your own with the same name, is kept and "
                               "never overwritten; an untouched shipped copy is updated when qargi ships a newer text. Seeding never links a pack: nothing "
                               "reaches a project or an agent until you link it.")),
            "check": verb("Check a render for drift (read only)", [("PROJECT", "project")], [TARGET],
                          desc=("Needs --target claude-code for that runtime, or another eligible local target selected as for apply. Writes nothing and exits 1 on any finding: library drift (a pack changed or failed review since it "
                                "was rendered), rendered tampering (a file differs from the manifest, or an extra or missing file), enablement drift (a pack "
                                "enabled or disabled, or its roles changed, since the render), shadowing of a rendered skill by ~/.claude/skills or by the "
                                "checkout's .claude/skills (another runtime uses the corresponding paths of its resources), and a render directory that has no manifest (a broken render). A project with no render at all is not a failure: "
                                "the check prints a not applied line with the command that applies it and exits 0. The answer packs.none: true says the project uses no project packs; "
                                "the check then passes with no render, and fails if a pack is linked to a role of the project. It also reports a rendered file that differs from "
                                "the library copy (even when the manifest was edited with it), a changed file mode, a group- or world-writable "
                                "render, a malformed manifest, and a manifest that names another project or whose role scoping is not advisory.\n"
                                "It ends with a section, skills a session would load, that gives every skill a session opened in the checkout would load one state: "
                                "qargi (a library pack with approved content, or a skill shipped with qargi), accepted (skill accept), drifted (accepted, "
                                "but its content changed: this exits 1), excluded (switched off in the provider's settings; qargi only reads them) or unmanaged "
                                "(everything else, shown with what to do about it; this does not change the exit status). When the checkout's skills directory "
                                "is not linked to the render it adds a note naming packs link.")),
            "link": verb("Make the project's checkout load its packs by itself", [("PROJECT", "project")], [LOCAL_TARGET, PLAN, APPROVED],
                         desc=("--target selects an eligible local runtime by session.render_target; omitted uses the project's member runtime. A secondary target links only skills, "
                               "with link.project dir-symlink. It does not link agents or memory; project link/unlink retain their default behavior and syntax. "
                               "Distinct runtime paths can be linked side by side; a shared destination already owned by another runtime refuses. "
                               "The provider's project skills directory in the repository (for Claude Code .claude/skills) becomes a symbolic link to the render "
                               "made by packs apply --target. Without --approved it prints the plan, the skills a session would load, and a plan token; apply with "
                               "--plan TOKEN --approved. If the directory is absent it creates the link; if it is already that link it says so and exits 0. It refuses "
                               "a link to anywhere else, a symlinked parent, a checkout that is not the top of a git work tree, a missing render, and files "
                               "tracked by git. If it is a real directory the plan lists each skill in it as same, differs or new against the library and "
                               "offers skill import and skill link for the new ones; apply then moves the directory to the backup name (skills.qargi-backup "
                               "beside it) and links, so skills not imported stop loading until they are. Nothing is deleted. If git does not ignore the path "
                               "it prints the line to add to .git/info/exclude and never edits that file. A provider that has no such directory is "
                               "refused (exit 3). Every verb that takes --target (packs apply, packs check), packs link and unlink, skill accept and marshal handoff "
                               "exit 2 when the project has no provider (qargi project set P models.provider NAME). A local member's guard refuses it.")),
            "unlink": verb("Undo packs link", [("PROJECT", "project")], [LOCAL_TARGET, PLAN, APPROVED],
                           desc=("Use the same --target as link for a secondary runtime. Removes only the symbolic link that points to this project's selected runtime render and, if the backup exists, moves it back to the skills "
                                 "directory. Refuses a link to anywhere else, a real directory in its place, and a backup with no link of ours. Same plan token "
                                 "and approval as link; nothing else is deleted. Owned unlink and backup recovery remain available after composition drift or render manifest corruption. "
                                 "They also survive lost skills support or verification, including a harmless library-provider reseal, when sealed runtime identity and a safe skills path and link mode remain available. "
                                 "Cleanup preserves sealed extension composition and skips current pack reviews and capability-verification prerequisites. Missing, ambiguous, unsealed or drifted identity and unsafe layouts refuse. "
                                 "Default cleanup retains optional target and link-mode compatibility. Explicit targets retain their identity and mode checks. Combined project unlink follows the same rule. Fresh apply, check and link retain their loading eligibility and render validation checks.")),
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
                 "checked out detached; install.sh --user then runs as you (it refreshes every runtime installed, the default runtime when none is) and the members to refresh are listed. The git commands that write "
                 "into the checkout run through sudo (QARGI_SUDO names another command). When the members file (~/.qargi/config/agents.json) is not in "
                 "the current shape, which every agent verb refuses, the plan and the end of the upgrade say so and how to redo it; nothing is "
                 "changed for that. A member or agent cannot use it."),
        "scripts": ["upgrade.sh"],
        "opts": [opt("--branch", "the branch to move to (default: the installed checkout's current branch)", "BRANCH"),
                 opt("--tag", "a tag to check out instead", "TAG"), PLAN, APPROVED],
        "examples": ["qargi upgrade --branch develop", "qargi upgrade --branch develop --plan 1a2b3c4d5e6f --approved \"upgrade to develop\"", "qargi upgrade --tag v0.2.0"],
    },
    "methodology": {
        "summary": "List and inspect the development and release methodologies",
        "desc": ("A methodology is the way a project is developed and released, as data: its branches, versioning and changelog, test tiers, "
                 "CI, release steps and deployment options, and the generic files a new project starts with. Two ship with qargi: gitflow, and plain for a project whose output is documents (one long-lived branch, main, and no feature, release or hotfix branches, no tag and no version); "
                 "add your own under ~/.qargi/config/methodologies/NAME/ (methodology.json and a scaffold/ directory). Today a methodology sets "
                 "the files and parameters a project starts with and a few patterns; the feature, release and branch verbs name develop and master themselves. "
                 "A methodology whose flow is plain (the key flow in methodology.json: gitflow by default) has exactly one long-lived branch and none of the release patterns; qargi feature, release (hotfixes included), branch prune, upstream and changelog renumber refuse such a project with the refusal methodology-no-flow (exit 2, nothing changed), while qargi local prepare, run, verify, close and clean, qargi review check, save and apply, and qargi backlog work with --base set to its branch. A methodology whose flow is not a valid value (or whose methodology.json cannot be read) is refused by those verbs as a plain one is, never run as gitflow; one that is not found is not refused. "
                 "These verbs only read; qargi project new and adopt write, and only after a plan."),
        "scripts": ["methodology.py"],
        "verbs": {
            "list": verb("List the methodologies and where they live"),
            "show": verb("Print a methodology: flow, branches, tests, CI, release steps (or the work steps of a plain one), parameters, scaffold, deployment options", [("NAME", "methodology")]),
            "check": verb("Validate one methodology, or all of them", [("[NAME]", "methodology")], desc="Names each problem. A methodology with the flow plain must have exactly one long-lived branch and a task pattern, and none of branches.feature, release, hotfix and tag, after_release, release and versioning. The optional work is a list of steps, each a non-empty line of text."),
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
                 "the one surface it serves (local or cloud) and a capability matrix for it: model and effort overrides at dispatch, a fixed tool "
                 "list per agent, a read-only barrier, a session budget ceiling, memory stores, skills and MCP. A capability that is not "
                 "verified counts as not supported. Optional dispatch.home.skills_dir is a validated private-home destination for opt-in command member snapshots; this structural declaration does not qualify actual loading or change capability dates. A provider with no read-only barrier on its surface cannot serve the review role there "
                 "unless you accept that with qargi provider accept. The project's models.provider chooses the provider; there is no default, and a verb that needs one refuses a project with none (exit 2). "
                 "A family name (what several runtimes of one vendor share) stands for the runtime of a surface only in a project's models.provider and in provider of; "
                 "every verb that takes a NAME (show, check, model, addenda, adapter-run, effective, require-barrier, layout, launch, require-skills) takes a runtime name, and a family name is refused as an unknown provider."),
        "scripts": ["provider.py", "provider.sh", "conformance/library.py"],
        "verbs": {
            "list": verb("List the providers with the surface each serves and whether the descriptor is clean"),
            "show": verb("Print one provider: tiers and models, effort levels and its capability matrix", [("NAME", "none")],
                         [opt("--json", "machine-readable"), opt("--project", "show it as this project sees it, with its verified extensions composed in", "PROJECT", "project")]),
            "accept": verb("Record that you accept a provider surface that has no read-only barrier", [("NAME", "none")],
                           [opt("--surface", "the surface the acceptance covers", "SURFACE", ("local", "cloud")),
                            opt("--no-barrier", "accept running the review role without a read-only barrier on that surface"),
                            opt("--project", "the project whose answers record it (default: the project of the current directory)", "PROJECT", "project"),
                            opt("--asked", "your words asking for it", "WORDS"), opt("--approved", "your words approving the plan", "WORDS"),
                            opt("--plan", "the plan token printed without it", "TOKEN")],
                           desc="Without --plan and --approved it prints what would be recorded and a plan token. Applied, it writes models.accept_no_barrier.SURFACE "
                                "(who, when, why) to the project's answers and the audit log. It is the only way a provider surface whose read-only barrier "
                                "is not supported can serve the review role."),
            "check": verb("Validate a definition (a library name or a directory) and say what degrades", [("NAME|DIR", "none")],
                          [opt("--project", "check it as this project composes it with its enabled extensions", "PROJECT", "project")],
                          desc="Fails on a definition that breaks the schema, a name that differs from its file, a missing tier or an unknown capability. "
                               "Warns on a verified date that is missing and says which capabilities count as not supported because of it, and which roles "
                               "therefore cannot be served (for example review where the read-only barrier is not supported)."),
            "new": verb("Scaffold a provider, catalog or extension pack in the library", [("NAME", "none")],
                        [opt("--kind", "provider, catalog or extension", "KIND", ("provider", "catalog", "extension")), opt("--from", "start from this provider's definition", "NAME"), PLAN, APPROVED],
                        desc="Plan, token, approval, as for a skill. The pack is stored unsealed and counts for nothing until sealed."),
            "import": verb("Import a provider pack from a directory, a JSON file or an https git URL, after a review", [("SOURCE", "file")],
                           [opt("--name", "store it under this name", "NAME"), opt("--ref", "the git ref to pin", "REF"), opt("--path", "a subdirectory of the source", "SUB"), PLAN, APPROVED, EXEC],
                           desc=("The review lists files, executables (with hash and interpreter), URLs, network commands and secret findings. Binaries, archives, symlinks and secrets are refused; "
                                 "opaque blobs are flagged. A pack with executables also needs --approve-exec naming each. Stored sealed, never enabled; a shipped or existing name is refused.")),
            "seal": verb("Record the current content of a library provider pack as approved", [("NAME", "none")], [PLAN, APPROVED, EXEC]),
            "remove": verb("Remove a library provider pack", [("NAME", "none")], [PLAN, APPROVED]),
            "enable": verb("Let a project use a library extension pack, or start members on one more local runtime (--runtime)", [("PROJECT", "project"), ("EXTENSION", "none", True)], [RUNTIME_GATE, OPTION_GATE, ASKED_WORDS, PLAN, APPROVED, EXEC],
                           desc=("An extension adds resources or capabilities to a runtime for one project. It counts only once it is sealed and verified. "
                                 "With --runtime NAME (and no extension) it allows an extra runtime: the project may then start members on NAME beside its own local runtime (models.extra_runtimes.local), "
                                 "chosen by a profile (profiles.NAME.runtime) or by one task (qargi local prepare --runtime NAME). NAME is a command runtime of the local surface (a shipped one, or a library pack that is sealed and unchanged) that is not the project's own; "
                                 "else the refusal runtime-unusable names which of the three fails. Without --plan and --approved it prints the plan and a token and changes nothing: the runtime, its origin and the executable it would resolve; "
                                 "each link source of its home as FROM -> TO with the real path, present or missing, and that it is not inside ~/.codex (a source that would be refused refuses the plan too, with no token); that runs sharing a plain link's source run one at a time and that a private copy (COPY in place of LINK) lets its runs overlap; "
                                 "the whole barrier note; that a read-only role runs on it under the partial barrier (no provider accept is asked and none counts), and that a read-only member reads and reports and runs nothing that writes; "
                                 "that its model and effort are requested, not confirmed while the override claims are unverified; the reads warning when the runtime does not confine reads (dispatch.reads), with the words the approval must carry; "
                                 "the tool packs each role would get on it and that their MCP servers run outside the sandbox; the hidden paths and what the runtime lacks (a guard hook, managed member skills, pack renders). "
                                 "Applied with --plan TOKEN --approved WORDS it writes models.extra_runtimes.local and one audit line (provider:enable). For a runtime that does not confine reads the owner's words must contain reads are not confined "
                                 "(letter case and runs of blanks ignored, matched as words), else the refusal runtime-reads-unacknowledged and the token stays good: the lead passes the owner's words on and never writes the phrase itself. "
                                 "With --runtime NAME --option OPT, NAME being a runtime the project has enabled (its own or an extra one: else runtime-not-enabled), it enables a run option the definition of NAME declares (dispatch.run_config.options; an option that is not declared does not exist), "
                                 "for the profiles of the project that select it (profiles.NAME.options): a run of such a profile gets the run's configuration file with the option's settings over the baseline, and nothing else changed; every other run gets the baseline alone. "
                                 "The plan prints the settings the option adds to the run's file, in that file's format; that the tool it opens runs outside the sandbox, may spend, and that qargi does not measure that; where it may write; the reads warning of the runtime; "
                                 "whether the option is verified (verified_on of the definition: null is not yet); the profiles that could select it; and the phrase of the option, which the owner's approval words must contain (as words, letter case and runs of blanks ignored), "
                                 "else the refusal runtime-option-unacknowledged and the token stays good. It is for write runs only, and a read-only run whose profile selects one is refused at prepare (runtime-option-class). Applied it writes models.run_options.local.NAME, the digest of the option's declaration as the plan showed it (models.run_options.declared.NAME.OPT: a run of a profile that selects the option is refused at prepare when the definition has changed it since, until the owner disables and enables it again) and one audit line (provider:enable-option). "
                                 "A lead's verb: the guard refuses it to a member. The project's own runtime, one already enabled and a name that is not a runtime are refused; nothing is changed.")),
            "disable": verb("Stop a project using a library extension pack, one extra local runtime (--runtime), or one run option of a runtime (--runtime --option)", [("PROJECT", "project"), ("EXTENSION", "none", True)], [RUNTIME_GATE, OPTION_GATE, ASKED_WORDS, PLAN, APPROVED],
                            desc=("With --runtime NAME it takes NAME out of models.extra_runtimes.local, with a plan and a token as for enable and no phrase to say. It is refused, with no token, while a profile names the runtime "
                                  "(unset profiles.NAME.runtime first: qargi project unset PROJECT profiles.NAME.runtime). Runs prepared for it are refused when they start (runtime-drift: prepare again); "
                                  "finished runs are verified, reviewed, applied, closed and cleaned as before, because those verbs ask for no runtime. "
                                  "With --runtime NAME --option OPT it takes OPT out of models.run_options.local.NAME, with its own plan and token and no phrase to say; it is refused, with no token, while a profile selects the option "
                                  "(take it out of profiles.NAME.options first). Runs prepared with it are refused when they start (prepare again). Disabling the runtime itself is refused, with no token, while an option of it is enabled: disable the options first.")),
            "runtimes": verb("Print the runtimes the project's local surface runs members on", [("PROJECT", "project")],
                             desc=("The line primary NAME (the project's own local runtime, models.provider.local), then a line extra NAME for each runtime of models.extra_runtimes.local, each once. "
                                   "Read-only and open to a member. Exit 2 for a project with no local runtime or no such project.")),
            "reads-warning": verb("Print the line that says what a member on a local runtime can read, when its sandbox does not confine reads", [("NAME", "none")],
                                  desc=("The line the plans of provider enable --runtime, project new, project attach and project set models.provider.local print: members on NAME can read the real ~/.codex (the paths the definition names under dispatch.reads.exposes, "
                                        "and what they hold) and whatever else this account can read: reads are not confined. A definition with no dispatch.reads counts as not confining reads, with no path named. "
                                        "Nothing is printed for a runtime that confines reads or works in the session. Read-only and open to a member.")),
            "adapter-run": verb("Run one verb of a runtime's adapter (a library pack's adapter runs only as a sealed private copy, removed afterwards)", [("NAME", "none"), ("SURFACE", "none"), ("VERB", "none")],
                                [opt("--check", "check that the adapter and the verb exist and print nothing else")],
                                desc="NAME is a runtime name, not a family name. A verb the definition does not list exits 3."),
            "addenda": verb("Print the texts a runtime's definition adds to the member contract (a cloud agent's prompt, or the run's contract directory on the local surface)", [("NAME", "none"), ("SURFACE", "none")],
                            desc="NAME is a runtime name, not a family name. resources.contract_addenda of the definition: plain text files in its own directory, printed in the order it lists them; nothing when it lists none. "
                                 "A file that is missing, is not text or leaves the directory is refused."),
            "notes": verb("Print a note of the project's runtime (local unless --surface cloud), or list the topics it has", [("TOPIC", "none", True)],
                          [opt("--project", "the project whose runtime is asked (default: the one in effect)", "PROJECT", "project"),
                           opt("--surface", "the surface whose runtime is asked (default local); the cloud runtime's notes say where a hosted session keeps its outputs and clones (output-dir, clone-dir)", "SURFACE", ("local", "cloud")),
                           opt("--lead-runtime", "the runtime of the lead's own session, when it is not the project's: the notes about the lead's session are read from it "
                                                 "(default: QARGI_LEAD_RUNTIME when it is set and not empty; with neither, every note is the project's runtime's, as before)", "NAME"),
                           opt("--runtime", "answer the notes about the members from this runtime of the project (its own, or one of models.extra_runtimes.local) in place of the project's own; local surface only, and not with --run", "NAME"),
                           opt("--run", "answer them from the runtime the lead's registry records for this run directory (the project's own for a run prepared before the project had extra runtimes; nothing is read from the directory); local surface only, and not with --runtime", "RUN", "dir")],
                          desc="The notes of a runtime's definition say how it does what a skill asks of it (how a lead starts a member, where it keeps its skills). "
                               "With a TOPIC the text is printed; without, the names of the topics, one per line. The definition is the runtime's composed with the project's "
                               "enabled extensions. A topic the runtime does not have, or a runtime with no notes, is exit 1, naming both and listing the topics there are; a project with no runtime on the surface, or a runtime that cannot be used as it stands (a library pack not sealed or changed since it was sealed, an unreadable definition), is exit 2 (a refusal; there is no default). Read-only. "
                               "A lead whose session runs on another runtime than the project's members names its own with --lead-runtime NAME or QARGI_LEAD_RUNTIME (the option wins). "
                               "A definition lists the topics that are about the lead's own session (lead_notes: its identity, its own model, how it searches, where it loads its skills from); "
                               "those are then answered by the lead runtime, and every other topic (how a member is started, what a member returns) by the project's runtime as before. "
                               "The list of topics is both. A topic the lead runtime lists needs the project but not the project's runtime. "
                               "How a member is started and what it returns (spawn, member-out) are instructions for a lead on the project's runtime when that runtime starts a member inside the lead's own session (dispatch mode in-session): "
                               "for a lead on another runtime they are unsupported, exit 3, saying that the members of this project cannot be started from this lead, and the list of topics leaves the two out. "
                               "NAME is a runtime of the local surface that can be used as it stands, by its own name (not a family's), whatever --surface says; any other name is unsupported, exit 3, whatever is asked. "
                               "Both refusals say whether the option or the variable named the lead runtime. "
                               "A topic the project's runtime lists as about a lead's session and the lead runtime does not have is unsupported too, exit 3: it is never answered by the project's runtime. "
                               "The name selects which definition is read and nothing else: nothing is stored or changed, and no identity, approval or permission depends on it. "
                               "A project with extra runtimes starts members on more than one runtime, and the notes about members depend on the runtime a member runs on: --runtime NAME (one the project has enabled) or --run RUN (the runtime of that run) names it, "
                               "and spawn, member-out and message are then that runtime's (provider notes spawn --run RUN says qargi local run RUN for a run on a command runtime, and the session's tool for one on an in-session runtime); a runtime the project does not enable, "
                               "a run the registry does not name and a run of another project are refused, exit 2, naming the runtimes the project has. The topics about the lead's own session keep to the lead runtime. With neither option the notes are the project's own runtime's, as before, "
                               "and a project without extra runtimes gets the same text for every topic."),
            "model": verb("Print the model a runtime maps a tier to on a surface", [("NAME", "none"), ("SURFACE", "none"), ("TIER", "none")],
                          desc="NAME is a runtime name, not a family name."),
            "attest": verb("Record a capability you verified by hand or by a paid run (never runs or spends anything itself)", [("NAME", "none"), ("CAPABILITY", "none")],
                           [opt("--asked", "your words asking for this spend check", "WORDS"), opt("--did", "what was run, in your words", "TEXT"),
                            opt("--result", "the outcome", "RESULT", ("pass", "fail")), opt("--cost-cents", "what it cost, in cents", "N"),
                            opt("--cleanup", "what was cleaned up afterwards", "TEXT"), opt("--note", "anything else worth keeping", "TEXT"), PLAN, APPROVED],
                           desc="Asked each time: without the facts it prints what it needs and why. A failed result removes the earlier record."),
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
    "plan": {
        "summary": "The stored record of a plan, as a verb kept it when it printed its token",
        "desc": ("A verb that prints a plan token keeps the plan it hashed in STATE/plans/TOKEN.json (mode 600, seven days; nothing in a dry run), so that a stale token can name what moved "
                 "and a reader can show the plan again. The plans of the verbs docs/reference/plan-record.md lists keep it (plain lines or one line of words); the plans of a JSON document or a digest, some plans of plain lines (packs seed, provider enable and disable, local clean --orphans) and those of qargi upgrade and of the link verbs are not kept yet. The record never decides a token: a plan whose record cannot be kept still prints its token."),
        "scripts": ["plan.py"],
        "verbs": {
            "show": verb("Print the stored record of a plan token: the verb, what it acts on, the labelled lines that were hashed, when it was made and when its seven days end", [("TOKEN", "none")],
                         [opt("--json", "print the record as it was stored, with \"state\": \"valid\", as one JSON object")],
                         desc=("Read only, open to a member, and it changes nothing: no file is made or removed (an expired record stays; the store prunes), no audit line, no lock, and it works under QARGI_DRY=1. "
                               "The state directory's plans directory and the file are opened without following a link, and the file must be a regular file of one link and mode 600. Before it prints, it checks the "
                               "record: the schema (qargi.plan/0, a draft that may change without notice until a consumer publishes it), the form, the SHA-256 of the lines (input_sha256, from the lines and input_newline; it binds the lines only) and the token "
                               "against that hash and the name of the file. The text shows the verb, the target (the project and the one object the verb acts on), each line that was hashed with its label, "
                               "and the times created and expires (created plus seven days); a control character in a value is printed as \\xNN. The lines hold the values in clear, lead-chosen ones (a branch, a path, a name) included, each with a kind (ref, path, name, sha, label or count): "
                               "the file is the owner's, as the audit log is, and a card that showed a digest would ask for an approval blind. --json prints the record as stored (schema, verb, context, target, lines, "
                               "input_sha256, input_newline, token, created, expires and the basis qargi plan-stale reads) and adds \"state\": \"valid\". "
                               "Exit status: 0; 1 for a refusal: plan-unknown (the token is not 12 hex digits, no such file, or a file of before the schema), plan-expired (expires is past; QARGI_PLAN_NOW stands for the clock in tests) "
                               "or plan-record-invalid (a link, a file of the wrong kind or mode, one that cannot be read, bad JSON, an unknown schema, a record that is malformed or whose lines do not hash to the token); 2 for a usage error. "
                               "The token is the first 12 hex digits of input_sha256: a card is bound to input_sha256, not to the token. Expiry is not checked when a plan is applied."),
                         examples=["qargi plan show 1a2b3c4d5e6f", "qargi plan show 1a2b3c4d5e6f --json"]),
        },
    },
    "track": {
        "summary": "Track a session that was started elsewhere (for example in the console)",
        "scripts": ["session.sh"],
        "usage": [("NAME", "instance:cloud"), ("SID", "none")],
        "opts": [ASKED],
    },
    "local": {
        "summary": "Prepare, verify, close, list and clean a local run, its git without credentials",
        "desc": ("The agent works in a clone whose origin points to a bare copy. The bare copy has no remote, and the clone's origin push URL is disabled. "
                 "The agent runs git through a credential-less wrapper, and "
                 "verify compares snapshots of the real repository's local refs and origin's heads and tags, excluding refs/qargi/. "
                 "Filesystem and network protections depend on the selected runtime. "
                 "See docs/development/architecture.md for accepted differences and runtime protection boundaries."),
        "scripts": ["local.sh"],
        "verbs": {
            "run": verb("Run a task through a command runtime (a vendor CLI) in a prepared run; --dry-run prints what would run", [("RUN", "dir")],
                        [opt("--task", "the file with the task block (default RUN/task.md)", "FILE", "file"), opt("--model", "override the prepared model with a tier, catalog alias/id or pattern-matching id; a different model needs supported per_dispatch_model_override", "MODEL"),
                         opt("--effort", "override the prepared effort level; a changed native control needs supported per_dispatch_effort_override; a null control is omitted with a note", "LEVEL"), opt("--timeout", "seconds before the process group is killed (default from the definition)", "S"),
                         opt("--wait", "seconds to wait for the lane of a plain sign-in link held by another run, then refuse with lane-busy (nothing recorded, no --again needed); 0 does not wait at all; without it the wait has no bound", "SECONDS"),
                         opt("--again", "open a fresh strict attempt in the same prepared run; invalidate current verification before output changes"), opt("--dry-run", "print the argv, the working directory and the prompt, and run nothing")],
                        desc=("Command runs prepared now use the lead's private request when --model or --effort is omitted, independently for each option. The resolved profile, logical base, requested model/id and effort, role, class and runtime are private authority; RUN/request.json, RUN/profile, RUN/ability and RUN/class are mirrors. Changes to the runtime, dispatch mode, catalog, selected profile inputs, composition or effective capability/barrier policy refuse before launch with re-prepare guidance, even with explicit overrides. "
                              "Explicit model overrides follow the current catalog's id/alias policy; a pattern-matching id is accepted as syntax, without claiming vendor access. Changing the model or a non-null native effort control needs its capability verified yes or partial (unverified counts as unsupported). Repeating the prepared value needs no override capability; null effort controls are omitted with a note. Empty explicit model/effort values refuse. These are requests, never observed identity claims. "
                              "Existing lifecycle records without a prepared request retain their former balanced-model/no-effort defaults and override validation; no request is inferred or backfilled from RUN or saved files. Genuinely unmarked legacy runs still require re-prepare for runtime dispatch. "
                              "New prepared runs use private attempt authority. Dispatch, verify, apply, close and clean share one lifecycle lock and refuse active or unknown members, including discard. Applied, closed or cleaned runs cannot be retried. Dry-run and preflight refusal preserve previous output; setup or spawn failure after the attempt commit leaves it unverified and retains earlier saved evidence. Opted-in member snapshots validate content and selection drift read-only, print MEMBER_SKILLS_DIR and names/approval hashes on dry-run, and publish private staged bytes after lifecycle begin into dispatch.home.skills_dir. Foreign/replaced destinations or missing ownership refuse; cleanup requires recorded group quiescence and validates staged identity before deletion. Interrupted cleanup resumes through native --again; dry-run only inspects. Save/verify prove frozen evidence independently of current configuration/review. "
                              "Retry epochs precede ref collection. Lead-written report manifests use the private prepared base commit. TERM, HUP and INT before begin leave a not-started attempt; uncatchable death without a recorded child remains unknown and refuses recovery. Only a kernel report that the recorded process group is absent proves it gone. An addressable group with no live member in a process listing, including unreaped zombies, remains busy or unknown; inaccessible evidence remains unknown. "
                              "Only for a runtime whose dispatch mode is command; a runtime that works inside the session (dispatch mode in-session) is refused: dispatch it as its notes say (qargi provider notes spawn). "
                              "A run whose profile selects options gets the run's configuration file with their settings over the baseline (--dry-run prints RUN_CONFIG_OPTIONS=, the settings each applies; RUN_CONFIG_BASELINE= stays the definition's baseline), RUN/dispatch.json records run_config.options (names only) and the run prints RUN_OPTIONS=; the options bind the prepared request, so one enabled, selected or edited after prepare is refused with re-prepare guidance. "
                              "The command is built from the definition without a shell, runs in a scrubbed environment (only the names the pack's env_pass lists, which the review shows), and its output goes to OUT/transcript. "
                              "A read-only run needs the barrier the definition declares (or your acceptance). A library pack's executable runs only from its sealed copy. "
                              "The runtime may refuse a run whose paths its sandbox hides from the member (dispatch.hidden_paths, /dev for codex): a clone, contract, git wrapper, OUT or TMP there that the run's class does not show refuses it before it starts (exit 2), naming the path and the fix. "
                              "When the member can write the clone's .git (the argv grants it, or the class has no sandbox arguments), a change to what git there would run (.git/config, hooks/, info/) is named in a GITDIR=changed: line and git_dir of RUN/dispatch.json; never run git in that clone. "
                              "A runtime that refreshes the sign-in it is given in place declares its link private (dispatch.home.link[].private): the member gets a copy of its own in the run home (a regular file, mode 600, made exclusively and removed when the run ends) with a placeholder in place of the refresh token, so it cannot refresh and cannot race; the runs that share such a source take no lock and overlap (a plain link keeps its lock, one run at a time). A run whose bound (timeout_s, or --timeout) plus the margin (900 s unless the definition says) would outlive the access token in the copy is refused before anything is made or recorded (exit 1, runtime-signin-expiring: the seconds left, the bound, the margin and the login that makes a new sign-in), and again once the locks are held; a source that is not a JSON object or has no token with an expiry is refused (exit 2). Nothing is written to the source, and what the runtime writes to the copy goes with it (a note says it changed). The member still gets a live access token in its own home, as the link gave it: the read barrier is unchanged, but the refresh token no longer reaches the member. The real sign-in is refreshed by the run itself when the definition declares private.refresh (below), else by the lead with the runtime's own login. --dry-run prints HOME_COPIES=NAME<-PATH, and RUN/dispatch.json records home.private (the name, the paths set and the seconds left at the start, never a value). "
                              "A run that finds the lane of its plain sign-in link held says so on standard error, names the holder from the lane record beside the lock (lead, run and how long it has held it) and, when several runs wait, its place among them; the lock is held by the member too, so a runner killed with SIGKILL leaves the lane held until the member's process group ends, and a lock file that was removed or replaced while the run waited is noticed (the run takes the file that is there). --wait SECONDS bounds the wait: at the bound the run is refused as lane-busy (exit 1) before its attempt is recorded and before anything is made, so a plain run of it starts once the lane is free; --wait 0 refuses at once. Without --wait the wait has no bound, as it always had. qargi local list --lanes shows who holds each lane and who waits. "
                              "A private link that declares a refresh (dispatch.home.link[].private.refresh; codex does) has its real sign-in refreshed by the run when the token would not last the run's bound and margin: the runner takes the lock beside the source, reads the source again (another run may have refreshed it), and otherwise runs the declared command once (read-only, in a scratch directory, the home variable naming the source's directory, its output discarded and never printed), prints qargi: refreshing the sign-in of RUNTIME (expires in N s) and reads the source again; a command that fails, times out or leaves a token that does not last refuses the run (runtime-signin-expiring, cause refresh-failed), with no second try; dispatch.json records home.private[].refreshed (true or false); --dry-run prints HOME_REFRESH= and refreshes nothing, and local prepare never does. "
                              "The run starts on the runtime it was prepared for (the runtime of its registry line; a line without one means the project's own): it is refused with runtime-drift, nothing started, when that runtime is no longer enabled for the project, no longer sealed, local and started by a command, or when its definition, catalog, composition, profile or policy changed since prepare; prepare the run again. --runtime is not an option here. "
                              "Exit status: 0 the command succeeded, 1 it failed (or a usage error, such as no task block, or a private sign-in that ends inside the run's bound: runtime-signin-expiring), 2 refused (a barrier the run cannot have, a refused definition), 3 the runtime cannot be run this way (not a command runtime, its command is not on PATH), 4 transport (the definition maps the command's exit to it).")),
            "prepare": verb("Make the clone and the wrapper for a local agent", [],
                            [opt("--repo", "the local repository", "DIR", "dir"), opt("--repo-url", "clone a private repository from this https URL (no user name or password in it: that is --credential-file)", "URL"),
                             opt("--credential-file", "token file for --repo-url", "FILE", "file"), opt("--base", "the base branch", "BRANCH", "branch"),
                             opt("--slug", "the task slug (branch agent/<slug>)", "SLUG"), opt("--scratch", "where to put the run", "DIR", "dir"),
                             opt("--role", "the task's role, written to RUN/ability, with its class in RUN/class and in your registry (the registry's decides); a read-only role keeps the clone unchanged (default build)", "ROLE", "workrole"),
                             opt("--profile", "the profile to dispatch under (for example advisor or auditor for review); command runtimes also resolve omitted profiles by role, then class fallback, before making run artifacts; the class must fit the role", "NAME"),
                             opt("--runtime", "the local runtime this run is prepared for: the project's own or one it enabled (provider enable --runtime); default the runtime the profile names (profiles.NAME.runtime), else the project's own. A runtime not enabled is refused (runtime-not-enabled)", "NAME"),
                             opt("--task-file", "the file with the task: prepare then writes the whole task block to RUN/task.md for every runtime (refused when the file is empty, not a regular file, a link, over 1 MiB, or has a line that starts SCOPE:); needs --done", "FILE", "file"),
                             opt("--done", "the check that says the task is done, as one command line (with --task-file). Refused when it is empty, has several lines or bash -n cannot parse it, and when the word that starts any of its simple commands (at the start of the line and after ; & && || | ( or $(, past NAME=value words and redirections) is not an executable on PATH, a shell builtin or keyword, or a script, so prose that only contains an operator (coverage > 80%) is refused (a first word with a slash is a file of BASE, a file under a --scope path that the task may create, or an absolute one; with --repo-url a relative path is taken as given; a later word with a slash is not looked up, since a cd may precede it). Only command words are checked, never the arguments", "COMMAND"),
                             opt("--scope", "a path the task may change, relative, with no space, comma or .. in it (repeat for several; a directory, a file or a glob); written as the SCOPE: line, which qargi review check applies as the limit. Without it the line says none (with --task-file)", "PATH")],
                            desc=("The run is prepared for one runtime: --runtime, else the runtime the profile names, else the project's own, and that runtime is used where the project's own was: the contract addenda, the mode, the prepared request, the read-only barrier (the barrier of an extra runtime is its own: runtime-barrier-missing for one that has none, whatever the project accepted for its own runtime) and the hidden-paths check. "
                                  "A project with extra runtimes (models.extra_runtimes.local not empty) sees more: RUNTIME=NAME for every run, the project's own too; RUNTIME_OVERRIDE=profile P names R, resolved in NAME: MODEL EFFORT when --runtime differs from the runtime the profile names (also profile P names no runtime (OWN) when it names none and --runtime picks an extra one; nothing when --runtime equals the profile's runtime, or is the project's own for a profile that names none); "
                                  "and MEMBER_SKILLS=none (not delivered to an extra runtime) for a run on an extra runtime, which freezes no managed member skills. Its registry line carries runtime, model_confirmed (display only: whether the runtime's model override is verified) and model; a project without extra runtimes sees no new word, key or digest. "
                                  "Under a coordinator label (QARGI_ACTOR, qargi help coordinator) the base must be feature/ followed by the label's feature, and the run's registry line records the label (actor) and the feature (feature); a run prepared without a label has neither field. "
                                  "Command runtimes resolve the role's explicit or implicit profile before RUN, TMP or the clone is made, without member registration. The logical worker/reviewer base, requested model and effort, class and runtime are retained in lead-owned private lifecycle authority, bound to runtime/mode/catalog/profile/policy inputs. RUN/request.json and RUN/profile mirror that request for inspection; they cannot authorize selection or accept drift. MEMBER names the logical base, MODEL the requested id or alias, and EFFORT the requested level, including when the runtime has no native effort control. "
                                  "A run whose profile selects an option the project enabled for the runtime (profiles.NAME.options, qargi provider enable --runtime NAME --option OPT) prints RUN_OPTIONS=NAME (what it opens: hosted, outside the sandbox, may spend); a project and a profile with none print nothing new and bind nothing new. A read-only run whose profile selects an option is refused (runtime-option-class) before anything is made; a selection the project did not enable, or the definition does not declare, is refused (exit 2). "
                                  "Managed member snapshots default off; the owner gate packs member-skills freezes canonical role-specific skills in private lifecycle authority, including empty selections. Exact prepared-request hashes stay unchanged, so a changed shipped home declaration requires re-prepare. With --task-file, prepare writes RUN/task.md, the task block, for every runtime, and prints TASK_FILE=RUN/task.md; the lead hands the member that path unchanged. Its sections, in this order: "
                                  "ROLE (with the class), ABILITY (the role's text), TASK (the file), DONE, PROFILE (the text of the repository's profile, ~/.qargi/config/profiles/<repository>.md, when there is one), "
                                  "BASE, BASE_SHA, SCOPE (one line, the paths comma separated, or none), RUN_DIR, CLONE, OUT, TMP, GIT, CONTRACT, then SUBMODULES and MEMORY when there are any. "
                                  "Every input is checked before anything is made, and a refusal makes no run. Without the flag no task.md is written and nothing else changes.\n"
                                  "Prints KEY=value lines: RUN, ROLE, CLASS, PROFILE (the resolved command profile; in-session, the role's own unless --profile), MEMBER, MODEL and EFFORT (for a command request or explicit --profile), CLONE, OUT, TMP, GIT, "
                                  "BASE_SHA, CONTRACT (the run's own copy of the member contract, with the contract addenda of the project's local runtime as runtime-addenda.md) and, when the role declares "
                                  "submodules (roles.ROLE.tools, kind submodule) and the clone got them, SUBMODULES=path,... Each declared submodule is checked out in the clone from the lead's copy of its objects "
                                  "(the checkout at REPO/PATH, else the modules directory), offline: a mirror with no remote under RUN/sub and git submodule update from it, push URL disabled. A commit "
                                  "the lead's copy lacks, a submodule not initialised there, or a run made with --repo-url, is a note on stderr; nothing is fetched. "
                                  "Then a blank line and a TASK-BLOCK PATHS block (RUN_DIR, CLONE, OUT, TMP, GIT, BASE_SHA, CONTRACT) to copy into the task, and in a stored project a TASK-BLOCK MEMORY block. "
                                  "A caller that evals the output must stop at the blank line.\n"
                                  "When the project (found by matching the repository against the stored answers) has a render for its local runtime "
                                  "(packs apply --target RUNTIME) that has drifted, prepare also prints a WARNING block to stderr with the "
                                  "findings and the fix, packs apply --target RUNTIME PROJECT. The run goes on, and stdout and the "
                                  "TASK-BLOCK PATHS block are unchanged.\n"
                                  "A --scratch on a tmpfs (/dev/shm, often /tmp) is warned about on stderr: a reboot empties it and loses the run (its clone, commits "
                                  "and output); prefer a directory on disk, such as ~/.cache/qargi-runs.\n"
                                  "The runtime may refuse a run whose paths its sandbox hides from the member (dispatch.hidden_paths, /dev for codex): prepare refuses it "
                                  "before it makes anything (exit 2), naming the path and the fix (--scratch on another filesystem, or QARGI_RUN_TMP). "
                                  "The temporary parent is resolved once before directory creation: QARGI_RUN_TMP accepts aliases, relative paths and ..; TMP in the display, task, registry and private ownership record is the canonical path. Cleanup uses that recorded path even if an alias is later repointed.")),
            "verify": verb("Compare observed repository refs with the run's current authoritative snapshot", [("RUN_DIR", "dir", True)],
                           [opt("--saved", "verify the lead's saved copy of a passed run whose directory is gone (ID: the name of the run directory, qargi.XXXXXX)", "ID"),
                            opt("--mine", "a coordinator's own runs: verify every open run whose recorded label is this session's QARGI_ACTOR, each as local verify RUN would; one line per run, the worst exit status; takes no RUN")],
                           desc=("--mine (the coordinator label, qargi help coordinator): the open runs are those the registry records under exactly QARGI_ACTOR and that are neither cleaned nor closed and whose directory exists; "
                                 "each is verified as qargi local verify RUN does, and one line says RUN, its slug, pass or fail with the exit status and, for a failure, the first line of what verify said. "
                                 "The exit status is the worst of them (3, then 2, then 1, then 0); with no open run it says so and exits 0. Without a valid QARGI_ACTOR it is a usage error (exit 2): the lead lists runs with local list and verifies one with local verify RUN. "
                                 "--mine takes no RUN and no --saved.\n"
                                 "OUT without a report, for an uncollected run or a read-only run, is said with its likely cause: a runtime can refuse the member's write tool for a report file, so the file never reached OUT; "
                                 "the member is told to collect again or return its report as the final message (for a read-only run it is a note, and the exit status stays the refs verdict). "
                                 "Fails first, with exit 1 and \"OUT is empty: the member did not collect\", when the clone holds commits past BASE_SHA and RUN/out holds neither patches nor a report: "
                                 "the refs are compared all the same and their verdict is printed next to that message (exit 2 when the ref comparison fails), but nothing is recorded: the run is not verified, and the member must collect (its DONE needs ls OUT/patches to list the patches) before apply or close. "
                                 "Exits 2 when the ref comparison fails, 3 when the lead's registry does not vouch for the run: it is not in it, names no repository for it, or RUN/repo.path, repo.url or cred.path differ "
                                 "from it (the repository and the credential come from the registry; a member can write the run directory). "
                                 "It accepts the lead's own moves and names each one (\"develop moved by qargi feature finish\"): what the lead's ref journal records (the branches and tags "
                                 "that qargi's flow verbs move, push to origin or delete: feature finish and park, release and hotfix finish and push, branch prune, review apply, "
                                 "the parking branch following develop, a rewrite recorded with qargi ref record --rewrite, and the commits you made with git on a branch that "
                                 "release finish, hotfix finish, feature finish or branch prune then deleted, named as that verb's deletion; the commits you made with git on a release or hotfix branch "
                                 "and journaled with qargi release fix VERSION --record; a branch you deleted with git and recorded with qargi ref record --deleted, named as qargi ref deleted; "
                                 "a branch that still exists, or that you deleted or rewrote by hand and did not record, is not covered), a remote-tracking ref of origin that says what origin has "
                                 "(a fetch), the parking branch (repo.parking_branch, default scratch) fast-forwarded to develop's tip, by hand too, and the branches and branches of origin you noted "
                                 "(qargi ref note: a ref that did not exist when the run was prepared; one the run's agent could have made or moved and you did not note still fails). "
                                 "It also leaves out the harness's own bridge branches: a branch worktree-bridge-NAME while the locked worktree bridge-NAME of the harness (in its worktrees directory under the main checkout) holds it and its moves are fast-forwards (or once the worktree and the branch are gone). "
                                 "The refs a runtime or harness creates in the repository can be declared in the project answer runs.owned_refs, a list of glob patterns for full ref names "
                                 "(qargi project set PROJECT runs.owned_refs '[\"refs/heads/foo-*\"]'; only the lead sets it, and project validate checks it): a local ref that matches one is accepted in either phase and "
                                 "named (\"foo-x created; accepted: refs/heads/foo-* (owned by the runtime, per runs.owned_refs)\"). A pattern needs a literal prefix of at least 3 characters after refs/NAMESPACE/, "
                                 "may not match develop, master, a repo.long_lived branch, or be able to match anything inside the git-flow branches (agent/, feature/, release/, hotfix/) or the tags (rel*/0* is refused as release/ is), "
                                 "and a ref is never taken as owned when it is the base of a run that is not cleaned or closed, a worktree-bridge-* branch, a git-flow branch or a tag; a ref that matches no valid pattern is checked as before, in the strict phase too. "
                                 "The answers verify and clean read (runs.owned_refs, repo.long_lived, repo.parking_branch) are the copy prepare took into your registry, "
                                 "not the stored file of the day: a change of them takes effect on the runs prepared after it. "
                                 "New runs compare against private prepared and attempt snapshots, epoch and phase; RUN/verified, refs.before, started and dispatch.json are diagnostic mirrors. After a passing verify, later verify and clean also accept "
                                 "your fast-forwards of develop and master and of agent|feature|release|hotfix/* branches, and new branches there. Other observed, non-exempt ref differences fail. "
                                 "For --repo runs, snapshots cover local refs and available origin heads/tags, excluding refs/qargi/. --repo-url observes only the URL's heads/tags. When the remote is unavailable at both observations, verification may pass while remote refs remain unobserved. A change in availability fails the comparison. Transient activity and other destinations require separate evidence. "
                                 "Run it on every run before merging any of them. "
                                 "A passing verify saves OUT in <state>/runs/<run id>/ bound to the prepared identity, attempt and generation. Repeated live or --saved verification reuses that copy and advances the private ref snapshot; identical observations consume no history. --saved and review apply --from-saved require the current verified generation. Earlier copies and historical verifications are each bounded to 32 per attempt; a failed save requires re-verification from the run. Legacy inspection warns about its writable snapshots; missing new-schema authority fails closed.")),
            "close": verb("Close a verified run whose patches you applied by hand (git am): it is no longer open", [("RUN_DIR", "dir")],
                          [opt("--applied-by-am", "the way the run was taken in: you applied its patches by hand with git am (the only way close knows; required)")],
                          desc=("Marks the run in the lead's registry (closed: the time, closed_by: applied-by-am), never in the run directory, which a member can write; the files are kept. "
                                "A closed run is no longer listed as open or counted as applied and not merged by qargi lead compact-check and the compaction advice, no longer blocks "
                                "qargi feature finish and is listed by marshal status as closed; qargi local list shows closed in the APPLIED column. qargi local clean then removes it "
                                "without asking for an applied tip (its commits are taken as applied by hand); clean --applied removes it too. Refused for a run that has no passing "
                                "local verify (verify it first: close must not hide a failed comparison), a run whose ref comparison fails since that verify (close runs the refs check again), a read-only run, one applied with qargi review apply (merge that branch), "
                                "a run already closed or cleaned. When the applied branch was rewritten by hand (its tip is not the review:apply tip in your ref journal, the trees are the same and no rewrite is recorded), "
                                "the refusal for an applied run also names the fix: qargi ref record --rewrite BRANCH OLD NEW --why ..., with the branch and both tips filled in. Not available in a member run."),
                          examples=["qargi local close ./run --applied-by-am"]),
            "clean": verb("Remove a collected, verified run and its temporary directory", [("RUN_DIR", "dir", True)],
                          [opt("--discard", "drop the run on purpose: also a run whose output holds no manifest, whose commits were never merged or whose ref comparison fails (verify's outcome is printed as a warning)"),
                           opt("--applied", "clean every run under --scratch whose work is recorded applied (review apply) and merged into a branch other than agent/*; the others are kept and named, one line each (a legacy run whose refs changed says what is the matter and the one command to run), and the exit status is 1 when an applied run was kept"),
                           opt("--legacy", "with --applied: the bulk, planned removal of the legacy runs (made by a qargi before the lifecycle) whose work is applied and merged: a plan and a token, then with --plan and --approved each run's out/ is archived to <state>/runs-archive/NAME.tar.gz, read back, and the run removed; a run that is open (not applied, not merged), has a member alive or is not legacy is never touched"),
                           opt("--stale", "list the finished runs (RUN/verified or RUN/applied exists) under --scratch that are at least DAYS days old, from the run's start (a run with no start time is named as skipped); with --yes clean each of them by the rules below, and keep and name those clean refuses; a run still in progress is never listed", "DAYS"),
                           opt("--yes", "with --stale: clean the runs it lists (without it nothing changes)"),
                           opt("--orphans", "list the qargi-run.XXXXXX directories under /dev/shm (or QARGI_RUN_TMP) that no run of your registry names, each with its age and whether it is named; a plan and a token, nothing removed"),
                           opt("--days", "with --orphans: remove only the orphans older than DAYS days, and with nothing in them newer (default 2, at least 1)", "DAYS"),
                           opt("--plan", "with --orphans, or --applied --legacy: the plan token printed by the same command without --approved", "TOKEN"),
                           opt("--approved", "with --orphans or --applied --legacy, and --plan: your go-ahead for exactly that plan, in your words; recorded in the audit log", "WORDS"),
                           opt("--scratch", "with --applied or --stale: the directory the runs were prepared in; only the run directories directly under it are looked at", "DIR", "dir")],
                          desc=("Lifecycle clean records ownership and atomically renames saved output and attempt state before recording cleaned in the registry and deleting them. Rerun clean after interruption; recorded deletion is idempotent even after partial marker or state removal. Unknown or replaced tombstones refuse cleanup. Cleaned registry rows remain as recovery evidence. "
                                "Clean of a lifecycle run writes an outcome receipt below <state>/attempts/.receipts/ before it removes anything, and the receipt stays when the run is gone "
                                "(docs/members-and-providers/verification-lifecycle.md describes it). When the receipt cannot be written, clean refuses (exit 3) with nothing removed and the run still usable, "
                                "and the message names the receipt and the cause; --discard goes on and warns that no receipt was written. A legacy run gets no receipt. "
                                "Prepare makes a private temporary directory for the run (TMP, on /dev/shm when it exists) that the agent puts its test "
                                "sandboxes in; lifecycle clean removes it with the clone, the bare copy and the output only after private evidence and ownership authorization. Prepare records RUN and TMP directory identities (TMP must be a qargi-run.XXXXXX directory under /dev/shm or QARGI_RUN_TMP, or inside the run). Refused authorization preserves TMP, RUN and retained evidence. Interrupted cleanup uses owned tombstones and the lead registry, never RUN/tmpdir. A source replacement before staging, or missing prepare-time ownership evidence for a marked run, refuses. Once the original is proven staged or deleted, a replacement at its old pathname is preserved and reported while cleanup finishes the owned tombstone and exact registry row. An owned tombstone proves staging even before the phase commit. Internal TMP completion is recorded before RUN staging; recovery never traverses a replacement RUN to inspect TMP or tombstones beneath it. "
                                "Genuinely unmarked registered legacy runs without private lifecycle remnants retain warned ordinary clean and explicit --discard recovery. This weaker recovery proves no process quiescence or directory identity and creates no lifecycle authority: preserve wanted work and establish process safety first. Legacy TMP comes only from the registry and is removed on one file system only as a non-symlink qargi-run.XXXXXX directly under the real /dev/shm or configured QARGI_RUN_TMP parent, or RUN/tmp. Other TMP paths are left and named. Stripped markers with retained state, cleanup tombstones or saved lifecycle markers still refuse. "
                                "It refuses a run whose output has no manifest (collect first), except a read-only run (an advisor or a review: its product is a report, never patches) whose output holds a report.md (or NAME-report.md; a regular file, directly in OUT), "
                                "which can close with a plain clean when its ref comparison passes, its clone holds no commit and retained lifecycle evidence does not require explicit disposition. Retained attempt history may require --discard even for a read-only run. Preserve its evidence first. Clean also refuses a run whose ref comparison fails (that is evidence); the lead's own moves that verify accepts "
                                "(a feature finish since the run was prepared, for one) are no change and are named in its output. It also refuses a run whose clone holds commits that were "
                                "never applied (review apply) or whose applied tip is on no branch but agent/* in the repository (feature merge first), so "
                                "finished work is not deleted by mistake. --discard deliberately bypasses these product and inspection checks; it never bypasses a held lock, and for lifecycle runs never bypasses ownership or quiescence. "
                                "It also refuses, --discard or not, a run whose review apply is running (the apply holds a pid lock in the lead's state, apply/RUN-ID.json.run); a lock whose process is gone does not block, and clean removes it. "
                                "A run cleaned with --applied needs a RUN/applied record and a repository path in the registry (a run of a repository URL is kept); --applied takes no RUN_DIR and no --discard. "
                                "A cleaned run keeps its line in the registry, marked cleaned: marshal status and handoff list it as cleaned, never as an open task. "
                                "--applied and --stale --yes work through many runs at once and do the repeated work once: the registry is read once, the refs of the repository and of its origin are asked once for all the runs "
                                "(the answer is the one of the moment the verb began), and a legacy run whose ref comparison fails is decided without a clean of its own. "
                                "A legacy run (made by a qargi before the lifecycle: its registry line has no lifecycle marker) that --applied keeps because its refs changed since it was prepared, or could not be compared, "
                                "is named in one line with the one command to run: when its work is merged, qargi local clean RUN --discard once its out/ is archived; when it is not, qargi feature merge first. "
                                "--applied --legacy --scratch DIR is the bulk form of that command, a plan first: it lists the legacy runs under DIR that are applied and merged, with their sizes, and prints a token; nothing changes. "
                                "With --plan TOKEN --approved WORDS it archives the out/ of each run (with its records, its bundle, the saved copy in the state and its registry line) to <state>/runs-archive/NAME.tar.gz, "
                                "reads the archive back in full and checks its size and its list of files against the run's files, and only then removes the run as clean RUN --discard does; an archive that is there already is "
                                "reused when it matches and never replaced when it does not (that run is kept), and a run whose archive cannot be made is kept. A run that is not legacy, is not applied or not merged (open work), "
                                "is of a repository URL, or has a runner or a member alive (its dispatch.json, or a process that carries QARGI_MEMBER_RUN for it) is not in the plan and is never touched; each run is checked again "
                                "when the plan is applied, and the removal is in the audit log with your words. A member cannot run it (it is a lead verb, and a coordinator label refuses --legacy); --legacy is for --applied only. "
                                "--stale DAYS --scratch DIR is a plan first: it prints each finished run older than DAYS days and changes nothing; with --yes each is cleaned exactly as clean RUN would, "
                                "so a stale run whose commits were never applied or merged is kept and named (exit status 1), never dropped. It is refused without --scratch, "
                                "takes no RUN_DIR, no --applied, no --legacy and no --discard, and --yes is for --stale only. "
                                "A run whose directory is gone (a reboot, or removed by hand) is the registry's record and the saved copy alone: clean RUN drops both once "
                                "the saved work is applied and merged, and refuses otherwise; clean RUN --discard deliberately drops their evidence; lifecycle runs remain subject to ownership and quiescence, while legacy recovery proves neither. Missing legacy RUN recovery leaves TMP as an orphan. --stale counts such a run by "
                                "the start time of its record, and with --yes keeps unapplied saved work; retained lifecycle evidence without a current copy requires explicit discard. "
                                "When the applied branch is not merged because you rewrote it by hand (its tip is not the review:apply tip in your ref journal, the trees are the same and no rewrite is recorded), "
                                "the refusal also names the fix, with the branch and both tips filled in: git branch -f BRANCH OLD, then qargi ref record --rewrite BRANCH OLD NEW --why ...; clean then follows the rewrite. "
                                "When the refusal for an OUT with no manifest finds no report either, it names the likely cause too: a runtime can refuse the member's write tool for a report file, "
                                "so the files never reached OUT; follow the selected runtime's output rules, returning the report as the final message when writes are unavailable. "
                                "--orphans is for what no run owns: prepare makes a qargi-run.XXXXXX directory under /dev/shm (QARGI_RUN_TMP moves it) for each run, and clean RUN removes only the one your registry names for that run, "
                                "so a prepare that failed halfway, a dropped record or a replaced state directory leaves one behind. --orphans lists every such directory with its age (from its modification time) and says whether a run of "
                                "the registry names it, live or not; a link and a file are named and left. Only the registry of this state directory is consulted: the runs of another state directory "
                                "on the host (another QARGI_STATE or QARGI_HOME) are not, so their directories look orphaned once they are older than --days; check the age and the directory before you approve. Without --approved it prints the plan and its token and removes nothing. "
                                "With --plan TOKEN --approved WORDS it removes only the directories that no registry names, that are older than --days (default 2, at least 1) and have nothing in them newer; "
                                "each is checked again at the moment of removal, a directory that appeared or changed since the plan makes the token stale, and the removal is in the audit log with your words. "
                                "A named directory is never removed by it, whatever its age. It takes no RUN_DIR, --applied, --legacy, --discard, --stale, --yes or --scratch; --days is for it only, and --plan and --approved are for it and for --applied --legacy. "
                                "A clean marks the run's record cleaned and removes its saved copy."),
                          examples=["qargi local clean --applied --scratch /tmp/scratch", "qargi local clean --applied --legacy --scratch /tmp/scratch",
                                    "qargi local clean --applied --legacy --scratch /tmp/runs --plan TOKEN --approved \"go\"",
                                    "qargi local clean --stale 14 --scratch /tmp/scratch", "qargi local clean --stale 14 --scratch /tmp/scratch --yes",
                                    "qargi local clean --orphans --days 3", "qargi local clean --orphans --days 3 --plan TOKEN --approved \"remove them\""]),
            "report": verb("A read-only member's own way to write its report: standard input, or a file under OUT, as RUN/out/report.md with a minimal manifest.json", [("RUN", "dir", True)],
                           [opt("--findings", "write RUN/out/findings.md instead of report.md"), opt("--from", "read the report from this file under OUT (a relative name is relative to OUT) instead of standard input", "FILE", "file"),
                            opt("--force", "replace a report that is there already")],
                           desc=("For a read-only run whose member's file tool is refused for a report file: the member writes its text with its file tool under another name in OUT (draft.txt) and runs this verb itself, "
                                 "with the RUN_DIR of its task block, so the report reaches OUT without shell text (echo, heredoc). The report is read from a regular file under OUT (--from) or from standard input (qargi local report RUN < report.md); "
                                 "a link, a path that leaves OUT, a file over one megabyte and an empty report are refused. A report that is there already is kept unless --force. "
                                 "When OUT has no manifest.json one is written (status DONE, the run's base branch and commit, commits [] and the report in artifacts); a manifest the member wrote is kept. "
                                 "Prints what it wrote and the qargi review check command to run next; the check, not this verb, decides whether the report has the required form. "
                                 "It is not review save, which is the lead's and stores a member's final message: it works in a read-only run that the lead's registry names, only inside that run's OUT, "
                                 "and with the member mark set (qargi local run) only in the member's own run. A build run is refused (its product is patches). "
                                 "findings.md is not a report review check reads: it is for a member that writes its findings apart from the report.")),
            "list": verb("List the local runs: role, slug, age, whether applied and merged", [],
                         [opt("--scratch", "the directory the runs were prepared in (default: the runs of the registry that still exist)", "DIR", "dir"),
                          opt("--actor", "only the runs recorded under this coordinator label: the whole label, or a prefix that ends at a colon (<lead-id>:coord:<feature>: lists every coordinator of a feature; a lead identity may hold colons, so a prefix can also match the labels of a lead whose identity begins with it, and the whole label is exact); a run prepared without a label matches none", "ID"),
                          opt("--feature", "only the runs of this feature: the one a labeled prepare recorded, else the one the run's base feature/NAME names", "NAME"),
                          opt("--lanes", "instead of the runs: each lane (the lock file beside a sign-in that member runs of the stored projects share), whether it is held, by which lead and run and for how long, and the runs waiting for it; takes no other option")],
                         desc=("Read-only. With --lanes it lists the lanes instead of the runs, one line for each lock file the runtimes of the stored projects declare (a plain sign-in link, or a private one that declares a refresh): RUNTIME, LOCK, STATE (free; held; held, member alive, runner gone) and HOLDER (the lead, run, kind and age from the lane record beside the lock), then one line for each run waiting for it in the order it began to wait. The lane is held only when /proc/locks says so (no lock is taken, not even for a moment: a probe could refuse a run of --wait 0 that comes at the same time), so a record left by a run that was killed is not a holder; the record and the waiters' files are advisory, the lock is the authority. It takes no sign-in lock and no lifecycle lock, and does not wait for a run that is under way. "
                               "One row per run: ROLE, SLUG, AGE, APPLIED (RUN/applied exists: review apply ran; closed for a run closed with close --applied-by-am), MERGED (the applied tip is on a branch other than agent/*; ? for a run of a repository URL) and RUN. "
                               "A project with extra runtimes (models.extra_runtimes.local) has a RUNTIME column before RUN (- for a run prepared before it had any) and, after RUN, model=M (requested at prepare, not confirmed) or (requested at prepare, override verified) for a run that asked for a model: no runtime reports which model answered, so the wording says requested, and override verified only when the runtime's per-dispatch model override is verified; --json has runtime and model_confirmed. "
                               "A run prepared under a coordinator label (qargi help coordinator) carries two more fields after RUN, actor=LABEL and feature=NAME, and so does every row when --actor or --feature is given (- for none). "
                               "Both options together are an AND; both are lead-side filters on what the registry recorded, never on a file of the run directory. "
                               "It is the list that qargi local clean --applied --scratch DIR acts on. A directory is a run only when the lead's registry names it (a directory a member makes beside its own run is not one), "
                               "and the AGE is ? when the run's started file is not a number. A run of the registry whose directory is gone and that clean did not remove "
                               "is listed after the others as directory gone, with its saved copy and the review apply --from-saved command that applies it.")),
        },
    },
    "review": {
        "summary": "Check what an agent returned and put it on a task branch",
        "scripts": ["review_check.py", "review.sh"],
        "verbs": {
            "check": verb("Check what a run returned: numbered patches, messages, manifest, groups", [("OUT", "dir")],
                          [opt("--allow-empty", "accept a manifest with no commits (a team member that was blocked or had nothing to change)")],
                          desc=("Structural inspection of unsuccessful-attempt output is diagnostic, not acceptance; verify and apply refuse it. Verify, check and apply refuse OUT changed since acceptance; re-prepare for revised external output. "
                                "Save staging uses a private directory with recorded device, inode and prepared identity. Reconciliation recovers only that owned stage; unowned or replaced stages are preserved and refused, and historical .save.* paths are never adopted. Retention bounds count copies, not bytes. "
                                "An unfinished apply marked started refuses resume, clean and discard even after its shell dies: Git or a hook may still be alive. Preserve the worktree and record. An apply marked built can finish bookkeeping after its owner exits. Apply scrubs the private patch copy; a previous check cannot authorize replacement bytes. "
                                "Stale cleanup preserves retained generations without a current copy; only explicit discard drops that evidence. Historical lead-owned runs directories are tightened to mode 0700 on save. "
                                "OUT is the member's output directory (RUN_DIR/out); the patches are read from OUT/patches only, where review apply reads them. "
                                "Given a run directory instead (no patches or manifest.json in it, an out directory in it), it checks RUN_DIR/out and notes that it did. "
                                "Refuses a commit without a message body and a manifest that does not match the patches. "
                                "For a run of a project with extra runtimes (models.extra_runtimes.local) one line, runtime=R model=M (requested at prepare, not confirmed) or (requested at prepare, override verified), comes first, from the lead's registry and never from a file of the run directory; a report from a codex-style runtime says which model was requested, not which answered, and none is printed for a run prepared before the project had extra runtimes. "
                                "Area-count heuristics emit advisory warnings for a single wide patch or a dominant wide patch in a series. Reviewers must substantively assess commit cohesion, including supporting tests, docs and changelog. "
                                "Source acceptance requires independent review of concrete changes and dependencies. Reject semantically mixed work with concrete evidence. Keep one patch per actual commit and meaningful buildable commit boundaries. "
                                "A report-only run (a review) has no patches: it passes with a report.md (or PREFIXreport.md, as in a team run) that has a Findings section and whose last non-empty line is "
                                "`verdict: accept` or `verdict: revise`, and the manifest.json (PREFIXmanifest.json) beside it; a missing manifest or verdict line fails, a missing Checked section warns. "
                                "A patch, or a touched_paths entry of the manifest, outside SCOPE fails: SCOPE is the SCOPE line of RUN/task.md (beside OUT) when it records one, else the manifest's scope[]. "
                                "A manifest whose done.command is not the DONE line of RUN/task.md (the check the lead set) fails, with both commands named; a manifest with no done.command warns. "
                                "Commits dated within two minutes of each other (made in one batch at the end) warn: explain the warning in the report. "
                                "Prints OK, WARN or FAIL lines and a summary; exit 1 when any line is FAIL (warnings alone exit 0). "
                                "When the run is in the lead's registry and the project declared a take-in scrub, a series that passes is then scrubbed: the answer review.scrub (a command line or a list of words) "
                                "runs in a throw-away checkout of the applied series (the run's base commit, then every patch with git am), with the range in QARGI_SCRUB_BASE and QARGI_SCRUB_TIP, and the answer "
                                "review.trailer_policy reject fails any commit whose message has a Co-Authored-By or Generated-with trailer (none, the default, checks nothing). One more line says scrub: ok, or "
                                "scrub: FAIL and the first lines of the output (scrub: not run when the series check failed), and a failing scrub exits 1. The checkout is a shared clone, so no branch, tag or worktree entry "
                                "is made in the repository. Both answers are the run's own copy taken by local prepare; with neither set nothing changes. A member's guard refuses setting them, and a member's own check (the member mark that local run sets is in its environment) does not run the scrub: it says scrub: not run (a member's check; the lead's check runs it) and does not fail.")),
            "save": verb("Store the final message of a read-only run (standard input) as RUN/out/report.md, with a minimal manifest.json", [("RUN", "dir", True)],
                         [opt("--force", "replace a report.md that is there already")],
                         desc=("For a read-only run (review, advisor, auditor) whose member could not write its report with a file tool: the member puts the whole report in its final message and the lead "
                               "stores that message, so no shell text is involved. The message is read from standard input (qargi review save RUN < message.md) and written as RUN/out/report.md; "
                               "a report.md that is there already is kept unless --force. When OUT has no manifest.json one is written: status DONE, the run's base branch and commit, commits [] and the report "
                               "in artifacts (a manifest the member wrote is kept). Prints what it wrote and the qargi review check command to run next; the check, not this verb, decides whether the report has the "
                               "required form. Refused for a directory that is not a run in the lead's registry, for a run that is not read-only (a build run returns patches), for a run directory or OUT that is a "
                               "link, for an empty message, and from a member (the guard refuses the verb; so does the verb itself when the member mark is set).")),
            "apply": verb("Apply a collected, checked run to a task branch of the repository", [("RUN_DIR", "dir", True)],
                          [PROJECT_OPT, opt("--branch", "the branch to create (default agent/<slug> of the run)", "BRANCH", "branch"),
                           opt("--from-saved", "apply the copy local verify saved of a passed run whose directory is gone (ID: qargi.XXXXXX), with the same checks", "ID")],
                          desc=("Refuses a run applied already or closed (local close --applied-by-am), and unless review check passes for RUN_DIR/out (warnings allowed) and local verify accepts the run (a refs-changed result "
                                "prints the diff). Creates the branch at the commit the run's base branch had when the run was prepared and applies every patch "
                                "of out/patches in order with git am, in a temporary worktree of the project's repository: your checkout is never touched and no "
                                "other ref changes. The committer is the one the repository has configured, else the author of the patches. "
                                "The author of every applied commit is reset to the lead's: the answer git.author ('Name <email>'), else the repository's user.name and user.email "
                                "(with neither, the member's author stays and the output says so); the answer review.keep_author true keeps the member's author instead. The date "
                                "stays, history already applied is not rewritten, and the member's author is recorded in the ref journal and the audit log, not in the commit. It refuses a "
                                "branch that exists; a patch that does not apply removes the worktree and the branch and names the patch. On success it prints "
                                "the commits and the next commands, and records branch and tip in RUN_DIR/applied and the branch in the run's ref snapshot, so "
                                "local clean still accepts the run. --from-saved ID applies from <state>/runs/ID instead (refused while the run directory exists): review check "
                                "of the saved OUT, local verify --saved ID, the registry's repository, slug and base, and the record in the saved copy, so it is applied once. "
                                "When the run's project declared a take-in scrub (review.scrub, review.trailer_policy), apply runs it too, before anything is made, unless a passing review check recorded the same "
                                "series (the patches in order and the declared scrub): then it prints the one line scrub: skipped (review check passed it for this series). A series changed after the check is scrubbed "
                                "again; a failing scrub (scrub: FAIL and the first lines of the output) refuses the apply and nothing is applied. The record is the lead's, in its state directory. "
                                "A member's apply does not run the scrub (scrub: not run), as its check does not."),
                          examples=["qargi review apply ./run", "qargi feature merge search agent/fix-names", "qargi local clean ./run"]),
        },
    },
    "team": {
        "summary": "Run a task with a lead and role agents (opt-in)",
        "desc": ("For a change that affects usage: the build member changes the code, the write member updates the operational docs, the "
                 "review member judges both. The lead is the session you work in, a cloud lead, or a session started in the console; all follow "
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
                 "print the plan and its token and change nothing; a store whose notes changed since the plan is refused. "
                 "The two stores of a cloud project and how an agent reads them: qargi help memory-stores."),
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
                         [PROJECT_OPT, WORKTREE, PLAN, APPROVED],
                         desc=("Without --approved it shows what would be created and a plan token and changes nothing. It refuses a tier that holds files that are not "
                               "a standard store, one whose place overlaps another tier, a repo tier outside the checkout, and the cloud tier (provision creates that). "
                               "The repo tier is written inside your repository checkout: qargi never commits it, so review it and commit or ignore it yourself; the plan names the branch checked out "
                               "there, which is where the files must be committed. --worktree DIR writes the repo tier into another worktree of the repository instead (the same path inside it), "
                               "and the plan then names the branch of that worktree; it is refused for any other tier. "
                               "A tier that is already set up says so and exits 0.")),
            "move": verb("Move notes from one tier to another, with the original archived in the first", [("PATH", "none")],
                         [PROJECT_OPT, opt("--from", "the tier the notes are in", "TIER", ("repo", "cloud", "project", "shared", "system")),
                          opt("--to", "the tier they go to", "TIER", ("repo", "cloud", "project", "shared", "system")), WORKTREE, PLAN, APPROVED],
                         desc=("PATH is one note (ending in .md) or a folder prefix under shared/ or roles/ROLE/. Only notes move, never indexes. A note must live in one tier, "
                               "so it refuses a path that is also in another tier. Nothing is deleted: the original goes to /_archive/<date>/ of the first tier and each copy "
                               "records its origin. Without --approved it prints the plan and its token and changes nothing; a tier whose notes changed since the plan is refused. "
                               "A move that has the repo tier at one end warns where its files must be committed, and --worktree DIR (refused when neither end is the repo tier) uses the repo tier "
                               "of that worktree of the repository instead of the checkout's.")),
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
                 "index with a Load column). plan and apply set up an empty store and keep a current one current; a store of an older layout or canon version is reported as unknown and not changed. "
                 "A store that cannot be listed (the cloud tool missing, not logged in, no access) is reported as `unreachable: <reason>`, exits 1 and is never taken for an empty one: no plan is advised or made for it, and apply, seed-role and promote write nothing. A project with no store recorded checks clean."),
        "scripts": ["canon.sh"],
        "verbs": {
            "check": verb("Report conformance and the version of each store", [("PROJECT", "project")], [KIND]),
            "plan": verb("Print every step needed to reach the current canon (changes nothing)", [("PROJECT", "project")],
                         [KIND]),
            "apply": verb("Run the plan", [("PROJECT", "project")], [KIND, PLAN, APPROVED]),
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
                             opt("--dry-run", "print the plan and stop; changes nothing"),
                             opt("--compatible", "the providers the pack works with (default: the catalog entry's, else asked)", "LIST")],
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
                 "notes go to the stores named in the project's answers. An archive's project answers never add or change models.extensions, "
                 "models.extra_runtimes, models.run_options or models.accept_no_barrier (they take a plan token and an approval: qargi provider enable, disable, accept), nor the lead's answers ci.not_gates, "
                 "methodology_accepted, review.reject_trailers, backlog.archive and backlog.section (a member's project set is refused them too); an archive may keep or drop "
                 "entries of such a list but not add or change one: the stored value stays, "
                 "or the key is left out, and a note says so. It asks at a terminal; --dry-run shows the plan without one."),
        "scripts": ["transfer.py"],
        "usage": [("FILE", "file")],
        "opts": [opt("--only", "the parts to import (default: ask)", "PARTS", ("config", "definitions", "memories", "state", "credentials")),
                 opt("--project", "only these projects of the archive, comma separated", "NAMES", "project"),
                 opt("--mode", "merge, overwrite or replace for every part (default: ask for each)", "MODE", ("merge", "overwrite", "replace")),
                 opt("--password-file", "the password is the first line of this file", "FILE", "file"),
                 opt("--dry-run", "print the plan and stop; changes nothing")],
        "examples": ["qargi import acme.tar.gz.gpg", "qargi import acme.tar.gz --dry-run --only memories"],
    },
    "lead": {
        "summary": "The lead session: its context, and the cloud lead's right to push",
        "desc": ("usage and compact-check keep the lead's own context small: usage says how much of it is in use, compact-check says whether a "
                 "compact of the session is safe now and what to re-read after it. Only the lead ever pushes, never a member. With a grant it creates agent/* "
                 "branches and opens pull requests; every merge is asked of you, and it cannot publish releases. grant and revoke are interactive: "
                 "each step prints its plan and asks you at the terminal, and your answer is the recorded approval. Where the session cannot answer a prompt, the person runs them at their own terminal (qargi provider notes commands says how the lead's runtime does it)."),
        "scripts": ["lead.sh", "lead_usage.py"],
        "verbs": {
            "usage": verb("How much of this session's context is in use: tokens of the last turn, percent of a known window, transcript size", [],
                          [PROJECT_OPT, opt("--session", "read the transcript of this session id, looked for among the transcripts of the current directory, the top of its work tree and the repository, in that order (default: the session QARGI_LEAD names; only when QARGI_LEAD is unset or empty, the newest transcript of the first of those that has one; a set id with none gives context: unknown)", "ID"),
                           opt("--transcript", "read this transcript file", "FILE", "file"), opt("--json", "machine-readable")],
                          desc=("The runtime of the project says where its session transcripts are and how to read them (resources.transcripts of its definition): "
                                "the context in use is the input, cache-read and cache-creation tokens of the last assistant turn. The window is the project answer "
                                "lead.context_window (tokens), else the one the runtime's definition gives for the model id of that turn (resources.transcripts.windows), else the "
                                "definition's single window, which is only a guess. The table in the runtime's definition lists the model families, per the vendor's "
                                "models overview of 2026-11-17: 1,000,000 tokens for Fable and Mythos 5, 5.1 and 5.2, Opus 4.6, 4.7, 4.8, 5 and 5.5, Sonnet 4.6, 5 and 5.5, "
                                "Haiku 5.5 and ids that end in [1m] or -1m; 200,000 for Opus 4, 4.1 and 4.5, Sonnet 4 and 4.5 and Haiku 4.5. A dated id takes its family's "
                                "window, and any other id is assumed at 200,000. The table gives the API's window, which the product may cap lower on some plans, so "
                                "lead.context_window overrides it. While the window is only assumed the line shows the tokens in use and says window unknown; set "
                                "lead.context_window, with no percentage and no advice to compact; when the tokens exceed the guess it adds that they do, since the real window is larger. "
                                "A window that the model id gave counts as assumed too once the tokens exceed it (the table is wrong for that id, for example a [1m] id whose entry is smaller than the real window): "
                                "the same line, no percentage and no advice. "
                                "--json says window_source answer, model or assumed; while it is assumed (a model window the tokens exceed included) percent is null (window is the guess) and window_exceeded says whether the tokens "
                                "are beyond it. Read only; a transcript that cannot be found or read prints unknown and exits 0."),
                          examples=["qargi lead usage", "qargi project set acme lead.context_window 1000000"]),
            "compact-check": verb("Is a compact of the session safe now? Exit 0 safe, 1 not, with every reason and the block to re-read after it", [],
                                  [PROJECT_OPT, opt("--advise", "also say whether a compact is advised: from 50% of the window, strongly from 70%; no advice on an assumed window (unknown model window and no lead.context_window), nor when the tokens exceed the window the model id gave"), opt("--json", "machine-readable")],
                                  desc=("Not safe while a local run is prepared and not verified, verified and not applied, or applied and not merged; a merge waits for its "
                                        "resolution; a whole-suite run (feature verify, release verify) is running; the handoff note written by marshal handoff --write is older "
                                        "than the last merge; or a release or hotfix branch is open. An applied run counts as merged by the test local list and local clean use: its applied tip is on a branch other than agent/*, or the commit the tip was rewritten to (ref record --rewrite) is, wherever the run directory lies. It prints the restart block: the handoff note, qargi marshal status, "
                                        "qargi feature status and the open runs, so the lead resumes from stored state. Read only. qargi cannot compact the session itself: the "
                                        "lead (or the person) does, by the runtime's own means. feature finish, the last feature merge of a feature's runs, release finish and marshal handoff print "
                                        "one line when the context is at or above the project answer lead.compact_advice_pct (default 40; 0 turns it off): "
                                        "\"lead: 50%, 100k tokens of context; compact is safe now: compact the session\", or that a compact is not safe yet, with the first reason; while the window is only assumed that line names the "
                                        "tokens and says the window is unknown, with no word of compacting."),
                                  examples=["qargi lead compact-check --advise"]),
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
        "summary": "Hooks that a runtime's session calls",
        "desc": ("session-start loads the lead role's READMEs and indexes from both stores (about 4 KB) for the project whose repository the "
                 "session is in, and the push grant. Register it as a SessionStart hook; it prints nothing outside a registered project. "
                 "Whether the project's runtime has such a hook, and how a session gets its lead identity from it, is in the runtime's notes: qargi provider notes identity."),
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
    "version": {"summary": "Print the version and the tool's root directory",
                "desc": "qargi version, or qargi --version, prints the version on the first line and \"source: DIR\", the tool's root directory, on the second. It changes nothing.",
                "scripts": [], "usage": []},
}

# skill and tool share one set of verbs
PACK_VERBS = {
    "new": verb("Create a pack from a template", [("NAME", "none")], [opt("--compatible", "the providers the pack works with: runtime or family names, comma separated, or any", "LIST")]),
    "import": verb("Import a pack from a directory, file or pinned git URL, after a review (a top-level .pack.json in the source is qargi's own record: ignored, not copied)", [("SOURCE", "file")],
                   [opt("--compatible", "the providers the pack works with: runtime or family names, comma separated, or any", "LIST"), opt("--name", "store it under this name", "NAME"), opt("--ref", "the git ref to pin", "REF"), opt("--path", "a subdirectory of the source", "SUB"), PLAN, APPROVED]),
    "list": verb("List the library, or what a project and role get", [("PROJECT", "project", True), ("ROLE", "role", True)]),
    "show": verb("Show a pack", [("NAME", "pack")]),
    "seal": verb("Approve the current content of a pack (after you edited it)", [("NAME", "pack")], [opt("--compatible", "the providers the pack works with: runtime or family names, comma separated, or any", "LIST"), PLAN, APPROVED],
                 desc="A pack with no compatible_providers needs --compatible once; giving it again changes the declaration and the plan says so."),
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
USER_OPT = opt("--user", "record it for every project instead of this one")
SKILL_VERBS = dict(PACK_VERBS)
SKILL_VERBS["accept"] = verb("Accept a skill a session loads that qargi does not manage", [("PROJECT", "project"), ("NAME", "none")], [LOCAL_TARGET, USER_OPT, PLAN, APPROVED],
    desc=("Finds NAME among the skills a session opened in the project's checkout would load (the checkout, the render and the user's skills directory; "
          "see qargi packs check) and applies only to one that is unmanaged or drifted. Without --plan it prints the same review as skill import "
          "(files, scripts, URLs, network commands, secret findings) and a plan token that covers project, runtime, target, composed definition, scope, name and content hash. With "
          "--plan and --approved it records the name, the content hash, the path and your words in the acceptances file, for this project or, with "
          "--user, for every project, and writes an audit line. An accepted skill shows as accepted in packs check; if its content changes it shows "
          "as drifted and packs check exits 1. qargi skills, excluded skills and skills already accepted are refused with the reason. A local "
          "member's guard refuses it. --target selects an eligible local runtime; omitted uses the member runtime. Approvals belong to resource/provider/name, "
          "including --user approvals; another runtime's record and unowned records accept nothing for the selected runtime."))
SKILL_VERBS["unaccept"] = verb("Remove the acceptance of a skill", [("PROJECT", "project"), ("NAME", "none")], [LOCAL_TARGET, USER_OPT, PLAN, APPROVED],
    desc=("Gated like accept. Removes only the record: the skill itself is not touched and shows as unmanaged again. Refused when there is no such "
          "acceptance in that scope. The token binds the exact provider-owned record and scope, so replacement needs a fresh plan. Revocation remains available "
          "after skills capability, verification or project layout is lost, when runtime/target identity is valid and unambiguous. Removed or ambiguous definitions refuse."))
COMMANDS["skill"]["verbs"] = SKILL_VERBS
TOOL_LIST = opt("--tool-list", "the server's own tool listing, saved to a file (the JSON result of MCP tools/list): the review also judges the pack's tools by it", "FILE", "file")
TOOL_VERBS = dict(PACK_VERBS)
TOOL_VERBS["import"] = dict(PACK_VERBS["import"], opts=PACK_VERBS["import"]["opts"] + [TOOL_LIST],
    desc=("With --tool-list FILE a tool that the listing does not annotate readOnlyHint true, or does not name, may not be always_allow or auto unless "
          "the pack sets write_ok; a tool annotated destructiveHint true is reported. The sha256 of the listing and what it says of each tool of the "
          "pack are kept in the pack's record (tool_list) and are part of the content hash and of the plan token. qargi reads the file and never "
          "contacts a server."))
TOOL_VERBS["seal"] = dict(PACK_VERBS["seal"], opts=PACK_VERBS["seal"]["opts"] + [TOOL_LIST],
    desc=(PACK_VERBS["seal"]["desc"] + " --tool-list FILE judges the tools by the server's tool listing (see tool import) and replaces what the record "
          "keeps of it; without the option the record's stands, and a tool added since then counts as not listed."))
COMMANDS["tool"]["verbs"] = TOOL_VERBS

# The coordinator label (QARGI_ACTOR): a session that carries a valid one is of coordinator class. It may run the verbs listed here and no other: a
# verb that is not listed is the lead's, and so is every verb added later until it is listed (tests/test_gates.py, ActorVerbTable, checks that each name here is a
# verb, and lists what is allowed). The label is attribution, not an identity: it grants nothing, it only narrows (lib/help.py actor_gate decides, once, in
# the dispatcher's preamble, before any verb changes anything).
#   ACTOR_VERBS     (area, verb) -> what the verb names that the label narrows: "" nothing, "run" a run directory (its registry base must be
#                   feature/<the label's feature>), "feature" a feature name (it must be the label's feature), "base" the --base option
#                   (it must be feature/<the label's feature>). An area with no verbs (doctor, status) has the verb "".
#   ACTOR_OPTS      (area, verb) -> options that make an allowed verb the lead's (a verb that acts beyond one run, or removes without a check)
#   ACTOR_ANY_OPTS  options no coordinator's command line may carry, on any verb: --approved (a go-ahead is the lead's), --push (a push is the lead's)
ACTOR_VERBS = {}
for _area, _names, _words in (
    # only read
    ("project", "", "template show list validate profile"), ("agent", "", "list models for"), ("role", "", "list show prompt card check"),
    ("feature", "", "list"), ("marshal", "", "status check handoff"), ("upstream", "", "status review"), ("campaign", "", "show check log"),
    ("backlog", "", "graph list"), ("release", "", "plan status"), ("doctor", "", ""), ("env", "", "show check"),
    ("instances", "", "list show"), ("skill", "", "list show effective check"), ("tool", "", "list show effective check"), ("packs", "", "load check"),
    ("status", "", ""), ("report", "", ""), ("watch", "", ""), ("methodology", "", "list show check files deployment"),
    ("cloud", "", "list show check"), ("provider", "", "list show check addenda notes model"), ("noticed", "", "list"),
    ("team", "", "brief check contract"), ("memory", "", "lint get tiers check"), ("canon", "", "check plan audit"),
    ("credential", "", "check"), ("discover", "", "sources search recommend show"), ("lead", "", "usage compact-check status"),
    ("supervise", "", "status hooks"), ("local", "", "list"), ("plan", "", "show"),
    # a coordinator's own work, narrowed to its feature
    ("local", "base", "prepare"), ("local", "run", "run verify clean"), ("review", "run", "check"), ("feature", "feature", "status verify"),
):
    for _verb in (_words.split() or [""]):
        ACTOR_VERBS[(_area, _verb)] = _names
ACTOR_OPTS = {
    ("local", "clean"): ("--discard", "--applied", "--legacy", "--stale", "--orphans", "--yes"),   # only clean RUN: the other forms reach runs of other features
    ("marshal", "handoff"): ("--write",),                                                # a coordinator does not change who leads
    ("release", "plan"): ("--again",),                                                   # it discards a recorded cut
}
ACTOR_ANY_OPTS = ("--approved", "--push")

TOPICS = {
    "coordinator": ("The coordinator label", [
        "A lead may let a coordinator session run the dispatch work of one feature (prepare, run, verify, clean) while the lead keeps every gated act. The session says so with the "
        "environment variable QARGI_ACTOR, a label of the form <lead-id>:coord:<feature>:<n>: a lead identity of the form the marshal accepts (letters, digits and . _ @ : + -, never /), "
        "the word coord, a feature name, and a positive integer, at most 128 characters in all. A value that is set and not of that form is refused by every verb (exit 2, the form shown): "
        "it never counts as no label (help, version, completion, the guard and the run-event hooks are let through: they change nothing and must not fail). Unset or empty is no label, and nothing changes.",
        "The label narrows and grants nothing. A session that carries it runs as coordinator class: it may read, and it may run the verbs listed below, and every other verb is refused "
        "before it changes anything (exit 2, \"a coordinator does not ...; the lead runs it\"): feature start, sync, merge, park and finish; every release verb but plan and status; "
        "branch prune; every verb or option that pushes; any command line with --approved; marshal claim, set, renew, release, take, takeover, finish, enable, disable, key, signers, "
        "resign and forget, and handoff --write; upgrade, install, export and import; the verbs of project, provider, packs, skill, tool, memory, canon, agent, instances, "
        "cloud and env that change stored configuration; local close, report, clean --discard, --applied, --stale and --orphans; review save and apply.",
        "Allowed: the verbs that only read, local prepare, run, verify and clean RUN, local list, review check, feature status and verify, marshal check and status, role card, backlog list and graph, plan show, "
        "lead usage, provider notes and doctor. It is narrowed by feature: local prepare needs --base feature/<the label's feature>; a local or review verb that names a run is "
        "refused when the run's base is another feature; a feature verb that names a feature is refused for another one. A coordinator may clean any run of its own feature, "
        "also one a stopped predecessor prepared (the narrowing is by feature, not by label). Where a verb that is narrowed by feature or run is given an option it does not declare, "
        "it is refused (exit 2): the verb may read the words after such an option differently than the narrowing does, so what it names could not be told. "
        "The narrowing is checked where the target is resolved: the gate in front of the verb refuses early, and the script then checks the run, the feature or the base it is about "
        "to act on, once it has read its own command line (local prepare, run, verify and clean, review check, feature status and verify), before it changes anything or renews a lease. "
        "That check is the one that counts: a run word that starts with a dash (a link named --again in the working directory) is refused, and so is a path that reaches another "
        "feature's run by a link before a .., or an output that is a run of another feature.",
        "Some of the allowed verbs write something small, and are allowed for that: qargi credential check appends a line to the audit log and asks the remote with a push "
        "--dry-run that sends nothing; qargi review check renews the lead's lease of the feature the run belongs to; the verbs that fetch (marshal status and check, unless --no-fetch) "
        "update what this machine holds of the remote. None of them changes a branch, a run or a record of who leads.",
        "qargi local prepare under a label records the label and the feature with the run, in the lead's registry. qargi local list --actor ID (the whole label, or a prefix ending at "
        "a colon: a lead identity may hold colons, so a prefix such as lead-1: also matches the labels of a lead whose identity begins with it; give the whole label when that matters) "
        "and --feature NAME list the runs by them; qargi local verify --mine verifies every open run recorded under this session's label.",
        "The label is attribution, not an identity and not an authority: it is unauthenticated, a session can unset the variable, and it is never compared as an identity for a lease, an "
        "approval or a marshal record (QARGI_LEAD stays the lead identity). It stops a coordinator that follows its brief from doing a lead's act by mistake; it does not stop a hostile session. "
        "A member's guard is unchanged by it: a member that sets the variable can only narrow itself."]),
    "concepts": ("The model in one page", [
        "Task: you describe one task and an executable check that decides it is done. An agent works on it in its own clone and hands back "
        "numbered patches, one per commit, with a manifest. Members are instructed to return patches without pushing; lead grants are described in qargi help push.",
        "Roles are build, write, review, test and lead: build changes code, write writes the operational docs, review judges a change and changes no file, test writes and runs tests, lead coordinates a team. Each role is defined by its role text, which comes with the task block. The local workers are members you name and give roles (qargi agent add NAME --roles build,test); qargi agent for ROLE prints the member that serves it. "
        "A role has its own model, effort, skills and packages, stored in the project's answers.",
        "Local or cloud: local (a member on this machine) is the default. The cloud is used only when your request for that task names it, "
        "and start and send require and log your words with --asked. Other commands describe their gates in their own help.",
        "You decide: the coordinator re-verifies everything an agent returns (qargi review check), applies it as separate commits, and "
        "requests approval for pushes outside an existing scoped lead grant. Long-lived branch finishing and release commands retain their plan gates."]),
    "roles": ("Roles and members", [
        "Role build: changes the code with its tests, manual page, help and changelog.",
        "Role write: writes the operational documentation on its own branch.",
        "Role review: reads a change, runs its checks and reports a verdict, and changes no file.",
        "Role test: writes and repairs tests and proves them failing first and stable.",
        "Role lead: it does no work of its own; it coordinates a team of members on one task (qargi team, the skill qargi-team).",
        "A member is a local agent you name (qargi agent add forge --roles build,test), rendered from the one member definition "
        "qargi ships. The task block names the role and carries its role text; there is no role skill to load. qargi agent for ROLE prints the member "
        "dispatch spawns. A cloud agent serves one role, is named <project>-<role> and carries its role text in its prompt.",
        ]),
    "approvals": ("Plans, tokens and your go-ahead", [
        "A command that requires a plan token prints a plan first. The plan ends with a plan token, a hash of what would be done.",
        "To apply, run the same command with --plan TOKEN --approved \"your words\". If the plan changed in between, the token no longer "
        "matches and nothing happens.",
        "Add --json to any verb to get the plan as one JSON object instead of text: {verb, plan, token, apply, exit}, where apply is the command "
        "line to run once the person has agreed (the call as given, without --json, plus --plan TOKEN and --approved with a placeholder for the person's own words). "
        "A verb that printed no plan token (it ran, or refused) gives {verb, plan: null, token: null, output, exit}; the exit status is the verb's and its error "
        "messages stay on stderr. --json never supplies --plan or --approved, and a call that carries them runs as it would without --json, wrapped the same way "
        "with a null token. A verb that describes a --json option of its own keeps it.",
        "A plan that a verb printed is kept so that it can be shown again: qargi plan show TOKEN (--json for the record) prints the verb, what it acts on and the labelled lines that were hashed, "
        "with the values in clear and a kind for each (ref, path, name, sha, label or count), from STATE/plans/TOKEN.json (mode 600, seven days, nothing in a dry run). It changes nothing and works in a dry run. "
        "The plans of the verbs docs/reference/plan-record.md lists keep it (plain lines or one line of words; packs seed, provider enable and disable, local clean --orphans, qargi upgrade and the link verbs keep none yet); a token of a plan that keeps none is not known to it (plan-unknown), and a plan whose record could not be kept still prints its token. The record is a draft, schema qargi.plan/0, and "
        "the token stays the first 12 hex digits of its input_sha256: a record whose lines (or input_newline) were edited no longer hashes to its token and is not shown (plan-record-invalid), and one past its seven days is not shown either (plan-expired). The hash binds the lines only: the verb, the target, the context, the labels, the kinds and the times are not under it. They are checked for their form, and expires must be created plus seven days, but a hand edit that keeps them well formed (another verb, say) is shown as it stands: the file belongs to the owner, and the record is a reading aid, not a signature; "
        "applying a plan does not check its age.",
        "start and send require --asked \"your request\" naming the cloud instance. The gate records it in the state directory's "
        "append-only audit log. Consult each command's help for its request and approval requirements. "
        "Audit entries record supplied --asked and --approved words only where the command calls audit_log.",
        "qargi lead grant and revoke are interactive instead: you confirm each step at the terminal, and that is the approval.",
        "The rules. The token covers the plan the person saw, and an apply refuses when the plan is no longer that one. The --approved text is "
        "recorded, not verified: it is not proof that a person agreed. Never allow-list a gated verb in the runtime's settings: the permission "
        "prompt is the person's real control. A member never applies: it reports the plan and its token, and the lead shows them to the person "
        "(what the member's guard refuses: qargi help guard)."]),
    "guard": ("What a member's guard refuses", [
        "These best-effort checks apply when the runtime adapter installs qargi __guard (qargi provider show RUNTIME). Members run as your OS user. qargi local verify compares snapshots.",
        "It refuses verbs that change shared state: skill and tool new, import, seal, remove, unlink, link, enable, disable, accept and unaccept; "
        "discover install; import; packs apply, seed, link, unlink, member-skills; project set (models, release, test_command, gates, env, site, backlog, packs, runs, upstream, git, review, roles), init, new, remove, link and unlink; "
        "provider new, import, seal, remove, enable, disable, attest, accept, check and adapter-run (the rest "
        "read); release publish, sign, site, assets and fix; marshal claim, set, renew, release, take, "
        "takeover, finish, enable, disable, key, signers and resign (handoff only with --write); feature start, finish, verify and park; branch prune; changelog renumber without --check; "
        "upstream status, sync; backlog done; ref record; memory init, "
        "move, split, merge and copy; cloud set, unset and login; upgrade; local run, prepare, verify and clean; agent remove; review apply; env plan and apply; team run and task.",
        "It refuses writes in the pack library, credentials, the install record, the runtime's skills, agents and plugin directories, the installed copy, "
        "the state's render, providers, marshal, feature and saved-run directories, its ref journal, the memory tiers, ~/.config/anthropic, and the "
        "lead's git configuration and session files. "
        "It refuses the tool's own install.sh and lib/install_record.py (its engine) in any use. "
        "The install record is install.json, install.d and install.lock. "
        "Reading stays allowed except the lead's signing key. It refuses git push, send-email, imap-send, p4 submit, daemon, remote changes, -c or config of keys that run programs (alias.*, core.worktree), exporting GIT_DIR, rsync to a host. A git write is judged where -C, --work-tree or --git-dir name it. Text check, not a sandbox.",
        "A command is cut at every ; && || | and newline, inside quotes and heredocs, and a substitution is a command. A piece that starts with git push, git tag NAME, ssh, scp, sftp or gh "
        "is refused even in text (not mid-sentence); any other refused verb is text when every command is echo, cat, tee, grep or git commit, "
        "as is a heredoc body cat or tee gets, bar lines starting qargi. "
        "Shell programs piped in or here-strings are read; curl | sh and bash < f are refused. A cd it cannot read refuses relative writes.",
        "Wrapper options (sudo, env, timeout and the like) are read from a table; except for the read-only class's writes, an unknown one is judged with and without the next word as its value. "
        "bash's one-dash long options and source -p DIR NAME are read. A value the shell builds ($(, ${ or a backtick; not a plain $NAME) makes a shell's or python's options unreadable: any lead-only script the command names is refused.",
        "The read-only class (review) may write only OUT and TMP (the run's TMPDIR). Recognized clone mutations are refused. It runs build, vet and test commands with its given environment; assigning PATH, TMPDIR or GIT_* is refused, not the command.",
        "Setting QARGI_NESTED (skips a plan token), or setting or unsetting QARGI_LEAD, is refused.",
        "A refusal is a result: report it."]),
    "refusal": ("A refusal's code and the rule behind it", [
        "A command that a rule stops prints, on standard error, a line that starts qargi-refusal/1 and holds one JSON object (the code, the exit status, the verb, the project, the role and, in detail, qargi's own text: "
        "the typed fields as key=value, with dry=1 first in a dry run), then 'qargi: refused [CODE] message', a 'why:' line and a 'next:' line. The code names the rule once, in the catalogue lib/refusals.json. "
        "qargi help refusal lists the codes; qargi help refusal CODE prints the entry of one (an unknown code exits 2): the rule, why it exists, its class and exit status, its status, "
        "the fields its message fills, the message, and the next step for a lead and for the owner's own session.",
        "The object of the line is a document of the kind qargi-refusal (qargi help json qargi-refusal): it carries schema and kind beside the code, and the number after qargi-refusal/ is its schema. "
        "The exit status of the process is the exit of the code, and it is one of four: 1 (a refusal), 2 (a guard's deny, or a verb that does not apply to the project or a removal that something holds back), "
        "3 (a refusal that a retry may cure: the remote of the shared records could not be asked, class marshal-remote) and 77 (a refusal of the lead seat). A refusal of a verb that prints a JSON document leaves standard output empty.",
        "A code is live when a verb raises it, planned when it is written down before a verb raises it (so that it is reviewed early) and withdrawn when it is no longer raised; a code is never reused. "
        "The guard's refusals carry the code in front of their sentence. A note, 'qargi: note [CODE] ...', names a rule that will apply later and changes no exit status. "
        "docs/reference/refusals.md is the page of the catalogue, generated from it."]),
    "json": ("The JSON documents qargi prints for a program to read", [
        "A document that this tool prints for a program to read is one JSON object that names itself with two fields: kind, a string of the form qargi-NAME, and schema, an integer of 1 or more that belongs to the kind. "
        "A reader checks the kind, then the schema, stops on a kind or a schema it does not know, ignores a field it does not know and never parses a text field (detail, note, a warning). "
        "The integer of a kind rises when a field is removed, renamed, retyped or changes its meaning, and stays when a field is only added; a number in a document is a whole number within 2^53 - 1. "
        "Exit status 0 means one complete document on standard output. A rule that stops the verb prints a qargi-refusal line on standard error and no document, and exits 1, 2, 3 (a refusal that a retry may cure) or 77 (a refusal of the lead seat).",
        "qargi help json lists the kinds; qargi help json KIND prints the fields of one kind (an unknown kind exits 2); qargi help json KIND --json prints the registry file of the kind itself. "
        "The pinned kinds are qargi-marshal-status, qargi-marshal-check, qargi-handoff and qargi-refusal; every other --json output is unpinned and may change. "
        "docs/reference/json-output.md holds the rule, the table of kinds with what each verb writes, and how to qualify a reader with tests/fixtures/json/."]),
    "naming": ("How resources are named", [
        "Project and role are single lower-case tokens. An instance is <project>-<role>, for example acme-build. A session is "
        "<instance>-<task-slug>, and the agent's branch is agent/<task-slug>.",
        "Cloud resources follow <project>-<component>[-<role>]: the agent <project>-<role> (acme-build), the deployment "
        "<project>-deployment-<role>, the shared <project>-environment, and the stores <project>-memory and <project>-reference. "
        "The lead is <project>-lead, and so is its agent.",
        "qargi instances normalize renames existing resources to match."]),
    "memory-stores": ("The two memory stores", [
        "<project>-memory is where agents write verified how-to facts they learn, under their own role folder (shared/ is curated and reached by promotion). <project>-reference is read-only: rules, workflow and "
        "conventions you and the coordinator curate. Both have shared/ for every role and roles/<role>/ for one.",
        "An agent reads each store's README.md, then shared/INDEX.md and its role's index, then only the notes its task needs. "
        "The canon (qargi canon) fixes the layout and the note format. Read one note with qargi memory get.",
        "qargi memory split, merge and copy move notes between two stores (directories, .jsonl dumps or store ids). Nothing is deleted: "
        "what leaves a store is archived under /_archive/<date>/, a collision goes to /_conflicts/<date>/, and the origin of every "
        "note written is added to its Sources: line."]),
    "push": ("Who may push", [
        "Push policy reserves pushing to the lead. Without a scoped grant, ask before each push. Plan-gated flow commands retain their own approval requirements.",
        "The stored lead.push.local grant permits scoped agent/* branch pushes and pull requests without asking each time. Enforcement depends on the selected runtime and its tool permissions; inspect that adapter before relying on it.",
        "The cloud lead grant, lead.push.cloud = branches, supplies a GitHub tool with a fixed allowlist. It asks before merging when lead.push.merge is ask, and omits that tool when it is never. Set it up with qargi lead grant. Long-lived branch finishing and release/publication commands retain their command-specific approval gates.",
        "The scoped cloud GitHub tool excludes release creation. Release publication remains a lead operation under the release gates."]),
    "environment": ("Declaring a development environment", [
        "There is no file format of this tool for it. A project says how to set up a checkout in what it already has: a section of AGENTS.md (or README.md) headed "
        "Development environment, Environment or Setup; version pins in go.mod, .tool-versions, mise.toml, .python-version, .nvmrc or package.json; "
        ".gitmodules; and two targets of its task runner (Makefile, justfile, Taskfile.yml or mise.toml tasks): bootstrap, which installs "
        "everything idempotently, and doctor, which prints one line per item and exits non-zero on a missing one. setup and check are accepted names.",
        "Anyone, with or without qargi, runs the dry run (make -n bootstrap), reads it, runs bootstrap, then doctor. qargi env show prints what it "
        "found and the commands it would use; it runs nothing. qargi env check runs the doctor (the project's code, as trusted as test_command), "
        "adds the project's links, members, packs and memory and ends with ENV OK or ENV INCOMPLETE: N missing (...). A doctor line that "
        "begins with missing, fail or error, or ends with missing or not found, is a missing item; one that begins with expected is not red. "
        "qargi env plan runs the dry run (a dry run still runs project code: make -n expands $(shell ...)) "
        "and shows it with a plan token; qargi env apply runs bootstrap once for that plan. Both are the lead's.",
        "A tool a role needs that the bootstrap does not provide (a pinned linter from go install, a downloaded binary, a vendored test framework "
        "that is a submodule) is declared once in the project's answers, roles.ROLE.tools (qargi help project set): env plan shows each with its state, "
        "env apply installs the go tools and binaries (the binary's sha256 must match), env check reports one that is missing or wrong, and "
        "qargi local prepare checks the submodules out in every member clone from the lead's copy, offline. Plain apt packages stay in roles.ROLE.apt.",
        "For the author of a doctor target: print one line per item, for example the tool and its version. Start a line with missing, fail or error "
        "when the item is absent or wrong (such a line is a missing item); start it with expected for a known failure that is accepted (shown, not red); "
        "any other line is information. Exit non-zero when anything is missing, and change nothing.",
        "qargi project new writes an AGENTS.md section and stub bootstrap and doctor targets (the doctor fails until you fill it in); project attach "
        "lists what a repository lacks; project adopt drafts the missing files on a branch to review. qargi provision plan prints the bootstrap command as "
        "setup-script text, and marshal handoff gives the last check and apply.",
        "The project's answers can replace a command and list accepted failures: env.doctor_command, env.bootstrap_command, env.dry_run_command "
        "and env.known_failures (qargi project set acme env.known_failures '[\"line\"]'). They are overrides, never a second description."]),
    "files": ("Where things are", [
        "Configuration: ~/.qargi/config: projects/, instances.json, profiles/, packs/, credentials/, install.json, install.d/, install.lock.",
        "State: ~/.qargi/state: sessions.json, local-runs.jsonl, audit.log, runs/, backups/, provision/.",
        "Overrides: QARGI_HOME replaces ~/.qargi; QARGI_CONF and QARGI_STATE replace the two directories and win over it. XDG_CONFIG_HOME and XDG_STATE_HOME are not used. "
        "QARGI_PROJECT names the project when you are not inside its repository. QARGI_ROLES replaces the list of roles. "
        "QARGI_DRY_RUN prints a session request with secrets masked instead of sending it.",
        "These are user-installation defaults. In dev mode, configuration and state can live in checkout-local .qargi (qargi help dev). Project repo-tier memory can be committed, and shared marshal records can be commits on the project remote."]),
    "dev": ("Running a branch checkout", [
        "install.sh --user records the tool it installed in ~/.qargi/config/install.json (with whether it is linked or copied). A checkout run from any other place (its own bin/qargi, "
        "for example in a worktree) is then a dev run: it keeps its configuration and state in <checkout>/.qargi (ignored by version control), prints "
        "'qargi: dev run from ...' on stderr once per command, and never touches your live data. Without install.json every checkout is the installed one.",
        "QARGI_HOME, QARGI_CONF or QARGI_STATE, when set, win: QARGI_HOME=~/.qargi makes a dev run use live data on purpose.",
        "help, version, completion, the guard and the run-event hooks print no banner. Hook-enabled runtimes call qargi __guard from PATH, which normally resolves to the installed "
        "copy; put <checkout>/bin first on PATH to test the guard or the hooks of a branch."]),
}

ENVIRONMENT = [
    ("QARGI_HOME", "the directory that holds config/ and state/ (default ~/.qargi; a dev run: <checkout>/.qargi, see qargi help dev)"),
    ("QARGI_CONF", "the configuration directory (default $QARGI_HOME/config); wins over QARGI_HOME"),
    ("QARGI_STATE", "the state directory (default $QARGI_HOME/state); wins over QARGI_HOME"),
    ("QARGI_RUNS_ROOT", "a directory to scan for local run directories (qargi.*) in qargi report, besides the registry"),
    ("QARGI_PROJECT", "the project to use when the current directory is not inside its repository"),
    ("QARGI_ROLES", "the list of work roles (default: build review write test)"),
    ("QARGI_DRY", "set to 1 by --dry-run inside the verb that has it (release start, push and fix --push, feature finish, branch prune): a helper that writes (the audit log, the state files, the journal, a ref move, a commit) "
                  "stops the verb with exit 70, and git and gh pass only commands that read; unset, empty and 0 are a normal run. Do not set it yourself"),
    ("QARGI_VERB", "the verb a refusal's contract line names, as 'feature finish' (default: the verb the script was run as); the scripts that raise a refusal set it, you need not"),
    ("QARGI_PLAN_NOW", "a time (UTC, 2026-11-22T10:00:00Z) that stands for the clock of the plan records: when a plan is kept (created, expires) and when qargi plan show asks whether it is past its seven days; for tests, you need not set it"),
    ("QARGI_ROLE", "the role a refusal's contract line names (default: none); set by a member's run, you need not"),
    ("QARGI_DRY_RUN", "print a session request, with secrets masked, instead of sending it; qargi env apply stops before it runs the bootstrap"),
    ("QARGI_ENV_TIMEOUT", "seconds the dry run of qargi env plan and apply may take (default 120)"),
    ("QARGI_HOOK_MARSHAL_SECS", "seconds the session-start hook gives the read of the open features (qargi marshal status --all --brief --no-fetch) before it leaves the block out "
                                "(default 5; a whole number from 1 to 9999, anything else is ignored); a test on a loaded machine raises it"),
    ("QARGI_ACTOR", "the label of a coordinator session, <lead-id>:coord:<feature>:<n> (qargi help coordinator): a session that carries it may run only a coordinator's verbs, on its own feature (everything else is refused, exit 2), "
                    "qargi local prepare records it with the run, local list --actor and local verify --mine use it. A value that is set and not of that form is refused by every verb with exit 2; unset or empty is no label. "
                    "It is attribution only: unauthenticated, no identity and no authority (QARGI_LEAD stays the lead identity), and a session can unset it"),
    ("QARGI_LEAD_RUNTIME", "the runtime of the lead's own session for qargi provider notes, when it is not the project's (the option --lead-runtime wins; an empty value is none)"),
    ("QARGI_BUSCTL", "the program qargi doctor asks logind with (default busctl)"),
    ("QARGI_DOCTOR_MIN_FREE", "the percent of free space under /dev/shm below which qargi doctor warns (default 10)"),
    ("QARGI_LOGINCTL", "the program qargi doctor reads the user's linger with (default loginctl)"),
    ("NO_COLOR", "turn off bold in the terminal help"),
]

FILES = [
    ("~/.qargi/config/projects/NAME.json", "the answers about a project"),
    ("~/.qargi/config/instances.json", "the registry of instances"),
    ("~/.qargi/config/profiles/NAME.md", "a repository's gates and review rules, given to agents with a task"),
    ("~/.qargi/config/packs/", "the library of skills and tools, and their links"),
    ("~/.qargi/config/credentials/", "token files, mode 600"),
    ("~/.qargi/config/install.json", "the tool root install.sh recorded; a checkout run from elsewhere is a dev run"),
    ("~/.qargi/config/install.d/", "the install records: one manifest per runtime, a shared one, one per project and runtime; --uninstall removes exactly what they list"),
    ("~/.qargi/config/install.lock", "held by install.sh while it reads or changes the install records"),
    ("~/.qargi/state/sessions.json", "the tracker of cloud sessions"),
    ("~/.qargi/state/audit.log", "append-only entries from commands that call audit_log, with supplied --asked and --approved words"),
    ("~/.qargi/state/runs/", "collected outputs of runs"),
    ("~/.qargi/state/plans/TOKEN.json", "the plan a verb printed under that token (mode 600, kept seven days, none in a dry run): qargi plan show TOKEN"),
]

WORKFLOW = [
    ("Once per project", ["qargi project template acme > acme.json   # edit it", "qargi project init acme --answers acme.json",
                          "qargi provision plan acme-build    # then apply it with --plan and --approved"]),
    ("One task, cloud", ['qargi send acme-build "$BRIEF" --label rename-verb --asked "use the cloud builder"',
                         "qargi watch SID    # in the background", "qargi collect SID ./out", "qargi review check ./out"]),
    ("A team", ["qargi team brief acme code-docs --task \"rename the verb\" --done \"make test\" --base develop",
                "qargi lead status acme", "qargi team check ./run"]),
]
