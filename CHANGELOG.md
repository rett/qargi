# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `qargi help guard`: one place that says what a local member's guard refuses (verbs that change shared state, writes in the pack library, credentials, skills directories and the state's render directories, git push and remote changes, the signing key), that the read-only class writes only to OUT, that `QARGI_NESTED` does not stand in for a plan token, that a refusal is a result to report and `qargi local verify` the backstop. `qargi help approvals` now states in one place that a token covers the plan seen, that `--approved` is recorded and not verified, that gated verbs are never allow-listed in the runtime's settings and that a member never applies.
- The shipped `claude-code` definition has notes for the topics `spawn` (the Agent tool, with `subagent_type`, `model` and `effort`), `session-model`, `exploration`, `skills-dir` (where it loads skills from and how a skill is hidden), `identity` (the SessionStart hook and `QARGI_LEAD`, saying what is checked and what is assumed) and `commands` (the `!` prefix). `claude-platform` has none: no skill names its cloud tools. The skills point at these topics instead of naming them (see Changed).
- `qargi provider notes [TOPIC] [--project P]` prints a note of the project's local runtime (its definition composed with the project's enabled extensions), or the topic names when it is given none. The project is `--project`, else the one in effect. A topic the runtime does not have, or a runtime with no notes, is exit 1 and the message names both and lists the topics there are; a project with no local runtime, or a runtime that cannot be used as it stands (a library pack not sealed or changed since it was sealed, an unreadable definition), is exit 2, a refusal (there is no default provider). It changes nothing.
- A provider definition can hold `notes`: an object of topic name to text (at most 16 topics; a name is lower case letters, digits and `-`, starting with a letter, at most 32 characters; a text is one line of plain text, not empty, at most 2000 characters, with no control, format, private-use or unassigned character). They are how a runtime says what the skills would otherwise have to say about it. The provider check fails on a note that breaks these rules; an extension cannot add notes; a library pack's notes are part of the definition, so the seal hash covers them.
- A provider definition can list `resources.contract_addenda`: plain text files in its own directory (relative names, UTF-8, at most 16 KB each) that are added to the member contract in a cloud agent's prompt, so the neutral contract never has to name a hosted surface. The provider check (and the review of an import, a seal or a check of a library pack) fails on a file that is missing, is not text or leaves the directory (a link pointing out of it included); an extension cannot add them. `qargi provider addenda NAME SURFACE` prints them.
- Release publishing is automatic: pushing a release tag (`X.Y.Z`) runs `.github/workflows/release.yml`, which creates the GitHub release with that version's `CHANGELOG.md` section as its notes and the source archive of the tag and its SHA-256 as files. It refuses a tag that is not on `master`'s history and leaves an existing release alone; it can also be run by hand with a tag name for one pushed earlier. `lib/changelog_section.sh VERSION` prints a version's section.
- `qargi release publish TAG`: a plan and token that create the GitHub release of a tag from its changelog section (`gh release create --verify-tag`); refused when the release exists, the tag is missing or the section is empty. The guard refuses it to a member. `release status` and `release verify` now warn about a tag with no GitHub release and about a tagged commit that lacks `.github/workflows/release.yml` (`gh` is called through `QARGI_GH`; a missing or logged-out `gh` is a note, never a failure).
- `qargi provision plan|apply --force` passes `ant apply --force`, for a resource that changed on the server outside the config ("changed outside this config since the last apply"). The plan token covers the flag, so a plan made without it cannot be applied with it; the audit line says `force`.
- `qargi packs link PROJECT` and `packs unlink PROJECT`: the project's skills directory in the repository (the provider's `layout.project_skills_dir`, `.claude/skills` for Claude Code) becomes a symbolic link to the render of `packs apply --target`, so a session opened in the checkout loads the project's packs without `--add-dir`. The plan lists what a real directory there holds (same as the library, differs, or new, with the import and link commands for the new ones); apply moves it to `skills.qargi-backup` and `unlink` moves it back; nothing is deleted. A foreign link, a symlinked parent, files tracked by git and a missing render are refused. Plan token and approval as for `packs apply`; a member's guard refuses both.
- `qargi packs check --target` now ends with the skills a session would load: each is `qargi`, `accepted`, `drifted`, `excluded` (switched off in the provider's settings, which qargi only reads) or `unmanaged`. Only `drifted` changes the exit status. It also notes when the checkout is not linked, and `project attach` hints when the repository has its own skills.
- `qargi skill accept PROJECT NAME [--user]` and `skill unaccept`: record that a skill qargi does not manage (for example one in `~/.claude/skills`) is accepted, by name and content hash, for the project or for every project. The plan shows the same review as `skill import`; a changed accepted skill is `drifted` again. A member's guard refuses both.
- `qargi marshal handoff [NAME] [--write FILE] [--json]`: a read-only note for a fresh session, built from stored facts only (repository, HEAD, base, host, features, the marshal record under a data-not-instructions line, the packs check and launch line, what to read, what not to assume). Shipped with a lead-only `qargi-session` skill that says how to hand off and what to check in the new session's first reply.
- Provider descriptors have an optional `layout` (project and user skills and agents directories, settings files, how a skill is switched off, memory directory, render target, session launch line). A provider that leaves a facility out gets `provider NAME has no FACILITY` (exit 3) from the verbs that need it.

- `project validate`, `init`, `attach` and `new` print `finding: models.provider is not set` for answers without a provider (exit status unchanged); the answers template carries an empty `models.provider`. `local prepare` skips the render check with one note when the project has no provider, and an unknown project is `no such project` (exit 2).
- `packs unlink` also restores a backup whose link is already gone; `packs link` and `unlink` work through no-follow directory descriptors with a temporary link renamed into place, and when something fails they say where your skills are. Skills compared by `link`, the audit and `skill accept` use a stricter content hash (symlinks, the executable bit and nested files count), so an accepted record made before shows as `drifted` once. Names printed in offers are quoted and control characters are stripped; an unusual name is `skipped: unusual name`. For an unmanaged skill the audit prints the provider's line to hide it. The guard refuses the new scripts when a member runs them directly.

- `qargi project attach` and `project new` take `--provider NAME` and store it as `models.provider`; without it nothing is guessed (no models key, the `finding:` line says so).

- Provider descriptors have a second schema (`schema-2.json`): one runtime on one surface, shared model catalogs, family names that resolve per surface, and `models.provider` as a string or `{local, cloud}`. A definition in the library (`packs/providers/NAME/definition.json`) counts a capability only with a hash-bound `verified.json` record; a name defined both shipped and in the library is refused.
- The link engine behind `packs link` is now general (directory link, one link per entry, or a copy for runtimes that do not follow links); `packs link` behaves as before.
- Claude is shipped as two runtimes of one family: `claude-code` (local) and `claude-platform` (cloud), with a shared model catalog; `provider list|show|check` list them, and the conformance targets are `claude-code` and `claude-platform`. The family name `claude` resolves per surface (a notice says so); there is no runtime named `claude`.
- `models.provider` can name a runtime per surface: `qargi project set P models.provider.local|cloud NAME`, and `project new|attach` take `--provider-local` and `--provider-cloud` (or `--provider` for one name). `project validate` prints a `finding:` for an unset surface; a verb that needs a surface the answers leave out exits 2 and says which.
- Every skill and tool pack declares `compatible_providers` (runtime names, family names or `any`): `skill|tool new|import` need `--compatible LIST`, `seal --compatible` sets it on a pack, and it is part of the content hash. A project's provider skips a pack it is not on, with a note in `effective`, `check`, `packs apply|check|link` (`discover install [--compatible]` too). Existing library packs need `seal --compatible` (the baseline packs declare `any`: `packs seed`).
- The skill audit reads the exclusion from the provider's `resources` in every form (settings key at any depth, JSON or TOML, config list, deny list); accepted-skill records gain `resource` and `provider` fields.
- The member guard takes its hook protocol and its protected directories from the provider definitions (`qargi __guard --provider NAME`); a member is also refused the provider verbs that change a definition, writes under `state/render`, and the link and render scripts of the tool itself. Refusal texts for Claude are unchanged.
- Provider packs in the library: `qargi provider new|import|seal|remove|enable|disable|attest` for provider, catalog and extension packs. Each is a plan, a token and your approval; a pack with executables also needs `--approve-exec` naming every one. A pack may hold text only: binaries, archives, symlinks and secrets are refused, opaque blobs flagged. A pack counts only while it is what you sealed, and a capability counts only with a `verified.json` record bound to the definition's hash, written by `provider check` (hermetic cases) or `provider attest` (asked each time; it never runs or spends anything itself). The conformance harness moved to `lib/conformance/`; `tests/conformance.sh` still runs it.
- Members are rendered from one neutral definition (`agents/member.json`, `member.body.md`) through the runtime's renderer data. `agent list` and `agent models` show `STALE` (definition or catalog changed) and `DRIFT` (file edited by hand). The Claude member file is quoted slightly differently, so a member rendered before shows `STALE` until it is refreshed or added again.
- The packs render is neutral: `lib/packs_render.py` takes the skills directory, MCP file and settings from the runtime's definition, and the render directory is `~/.qargi/state/render/PROJECT/RUNTIME/` (it was `state/claude/PROJECT`). `qargi packs migrate-render` moves the existing ones (plan, token, approval).
- `qargi project set P models.provider.SURFACE X` refuses a runtime that does not serve that surface (exit 2).
- `qargi project link|unlink PROJECT [--resource skills,agents,memory]`: one plan and token links the project's skills, agents and memory into the work tree you run it in, each the way the runtime's definition says (a directory link, one link per entry, or a copy); for Claude Code the memory directory becomes a link into `~/.qargi/memory/projects/PROJECT`. A real directory in the way moves to `NAME.qargi-backup`; nothing records which work trees exist. A member's guard refuses both.
- `qargi local run RUN [--dry-run]` runs a task through a runtime whose dispatch is a command (a vendor CLI): the argv comes from the definition, without a shell, in a scrubbed environment (only the names the pack's `env_pass` lists, which the review shows), output in `OUT/transcript`; `--dry-run` prints what would run. A runtime that works inside the session is refused. A member's guard refuses it.
- Extensions: a project's `models.extensions` compose onto its runtime, with the pack that provided each capability recorded; two extensions that provide the same thing, or one that collides with the runtime, are refused. An extension's capability counts only after `provider check` (or `attest`) of that extension passes, bound to its hash and its runtime's. `provider show NAME --project P` and `provider effective ... --project P` show the composed view.
- The `qargi-providers` skill ships with the others (`install.sh` installs and removes it), and `install.sh` refuses a python3 older than 3.11.
- `qargi provider adapter-run NAME SURFACE VERB [--check]` runs a verb of a runtime's adapter (a library pack's adapter runs only as a sealed private copy that is removed afterwards; a verb the definition does not list exits 3), and `qargi provider model NAME SURFACE TIER` prints the model a tier maps to.
- `--project P` on `provider show|check|layout|require-skills|launch` reads the definition as the project sees it, with its verified extensions composed in. `agent for` and `provider accept` honour those extensions too, and `session` and `provision` go through the same loader.
- A member whose rendered text depends on an extension is shown STALE after the extension is enabled, disabled or changed, until `qargi agent refresh`.
- `tests/test_skill_budget.sh`: a word ceiling per text a member or lead loads (`tests/skill-budget.txt`; a ceiling is exact: a text over it or under it fails, so a raise and a leftover slack both show in a review; `--report` shows the slack), no sentence of 12 words or more in two texts (`tests/skill-dup-allowlist.txt`, a line per sentence naming exactly the texts it may stand in), and the three lists sorted, and every `qargi X Y` example in them must name a command and verb of `lib/commands.py` (`tests/skill-verbs-allowlist.txt`). Every reference file under `skills/*/` (a `.md` other than `SKILL.md`) must start with a `Load when ...` line and be named in its skill's `SKILL.md`.
- Four more baseline packs in `packs/`, each declared `compatible_providers: ["any"]` and seeded with the others: `review-findings` (how a reviewer writes findings), `secrets-scan` (run a secret scanner over your commits before the report and quote its verdict line), `docs-site-member` (work on a documentation branch that shares no history with the main branches) and `qargi-contributing` (habits for a member who changes qargi itself). Their `propose` values in `baseline.json` are descriptive: nothing evaluates `propose` yet.
- The provider check (and the review of an import or a seal) warns, and does not fail, when a local runtime that works in the session (`dispatch.mode` `in-session`) has no `spawn` note: the lead skills tell the lead to read that note to start a member, so without it the lead has no instructions. The `qargi-providers` definition guide names the topics the skills depend on (`spawn`, `session-model`, `exploration`, `skills-dir`, `identity`, `commands`).
- `tests/test_neutral.sh` has a second section: the files of `skills/`, `roles/`, `agents/`, `contract/` and `packs/skills/` must not name a vendor, a model family or the vendor's cloud CLI (case-insensitive: claude, anthropic, managed agents, haiku, sonnet, opus, `ant` as a word, the Agent tool). `tests/vendor-words-allowlist.txt` lists what may stay as `FILE:COUNT` (lines with a hit); a file over its count, a file not listed, or an entry above the real count fails, so the list can only shrink. It holds six files: the lines that define or choose the two shipped runtimes, the render directory `packs migrate-render` moves, the member template of the Claude member file and the file name CLAUDE.md.

### Changed
- The `qargi-instances` skill (898 words, from 1020) now also holds the models and dispatch rules that `qargi-flow` carried (the two bases, profiles, tiers, `qargi agent for ROLE [--profile P]`), and its description names the members (add, refresh, list; `STALE`, `DRIFT`), profiles, `agent for` and the cloud verbs (register, list, inspect). The sentence about migrating a members file of an earlier shape is gone. `qargi-project` leaves the `agent add` placement and refusal rules to `qargi-instances` (the member question keeps naming the members), and both skills point at `qargi help approvals` and `qargi help guard` for the plan-token and guard rules.
- The `qargi-flow` skill is lean (944 words, from 1723) and loads on demand: the marshal moves to `skills/qargi-flow/marshal.md` ("Load when you claim, take over, or hand off work"), leaving a four-line routine in the loop; the Models section moves to `qargi-instances` and the loop says only `qargi agent for ROLE [--profile P]`; taking a task in points at `/qargi-verify`; the plan-token and guard rules are one pointer each to `qargi help approvals` and `qargi help guard`. Its description no longer says "or a merge conflicts" and names the commands that should trigger it.
- The `qargi-flow`, `qargi-task`, `qargi-session`, `qargi-packs` and `qargi-team` skills no longer name Claude Code's tools, directories and settings: where they did, one sentence points at `qargi provider notes spawn`, `session-model`, `exploration`, `skills-dir`, `identity` or `commands`, and the launch line and the user directory are described without a vendor's names. The word ceilings of the five are lowered to match. The descriptions and texts of the lead skills (`qargi-flow`, `qargi-instances`, `qargi-memory`, `qargi-packs`, `qargi-project`, `qargi-provision`, `qargi-providers`, `qargi-session`, `qargi-team`) say "lead session", "cloud agents", "the cloud CLI" and a `RUNTIME` placeholder where they named Claude Code, Managed Agents, `ant` or `claude-code`; what is left (the two shipped runtimes where a skill defines or chooses a runtime, the file name CLAUDE.md) is listed in `tests/vendor-words-allowlist.txt`.
- The `qargi-task` skill loads in parts: its `SKILL.md` keeps the roles, the quick form, the hard rules, the task block, profiles and the local flow, and the cloud verbs, the cloud flow, the budget contingency and private repositories moved to `skills/qargi-task/cloud.md`, which starts "Load when the user's request names a cloud instance.", and the steps for a command runtime (`dispatch.mode` command) moved to `skills/qargi-task/local-run.md` ("Load when dispatch.mode is command.") (the skill directory is linked or copied whole by `install.sh`, so the reference file comes with it). `SKILL.md` is 834 words, from 2444: it no longer lists the related skills, carries the plan-token rules (`qargi help approvals`) or the guard's rules (`qargi help guard`) in its own words, has no "Features and releases" section (one sentence says to dispatch with `--base feature/NAME` after `qargi marshal check`; `/qargi-flow` owns the rest), and no longer repeats the `local verify` and `local clean` rules of `/qargi-verify`. `tests/test_prompt.sh` now lists `cloud.md` as the file that names the hosted output directory. The `qargi-verify` skill is the one take-in sequence (556 words, from 585): verify every open run with `local verify` before applying any, take the branch to apply and merge from the run's slug, `local clean` only after the merge is confirmed, no `feature finish`, `feature merge` or commit while a run is still open, and a loop over runs stops at the first failure before any `local clean`. Both descriptions now say what the skill does and when to use it; neither names a vendor product.
- A cloud member's prompt says each thing once: the cloud preamble no longer tells the agent to start long commands detached (the `claude-platform` addendum owns the recipe) or not to push (the contract's rule stands alone; the addendum keeps "use no ssh or gh"). The `qargi-contributing` pack names no tool of one runtime ("your runtime's file-writing tool", "background facility") and stays `compatible_providers: ["any"]`.
- The member contract carries again the rules that no pack or profile is certain to repeat (it is 718 words, from 678; the ceiling is exact): the profile's "always" gates before the report, and without a lint gate in the profile the repository's own lint step and a secret scanner over `BASE_SHA..HEAD`; temporary directories with `mktemp -d -p "$TMP"` and `TMPDIR="$TMP"`, nowhere else; the identity configured in the clone and `git interpret-trailers --parse` on each message; the profile's rules for examples and the files it says not to read. Its commit rule agrees with `qargi review check` (docs and changelog in the same commit, or in the next when one commit would span three top-level directories), `agent/<slug>`, commit advice and the clone's branch apply to roles that commit, and a read-only role runs `review check` until it reports no failure (`OK report-only run`). Background commands are "your runtime's background facility" with no trailing `&`, never `pgrep -f`, stopped or waited for before the report; the Bash tool and `Monitor` wording moved to the `claude-code` addendum, and the cloud addendum says its detached start is the one allowed form of a trailing `&`.
- A read-only role puts a suggested fix in its report as a fenced diff, never as a patch file (`local verify` and `review check` refuse patches of a read-only run); the manifest's artifact kind `suggestion` is gone. `CONFIRMED` (demonstrated by running it or by a traced line-level argument you quote) and `PLAUSIBLE` (reasoned, not demonstrated) mean the same in the review role and the `review-findings` pack. The write role again says to leave out what it cannot verify, the test role says "for example" and "at least ten runs" for flake checks, and the rule to read code facts with `git show` and never rebase or cherry-pick across is in the `docs-site-member` pack. Each role text is at most 170 words.
- `qargi local prepare` gives the run its own copy of the member contract and prints its directory as `CONTRACT=` (it printed the `contract/` directory of the checkout or the installed copy). For a repository of a stored project, the copy also holds the contract addenda of the project's runtime on the local surface (`resources.contract_addenda` of its definition) as `runtime-addenda.md`; a repository in no project, or a project with no local runtime, gets the contract alone. The `claude-code` definition lists one (`lib/providers/claude-code/local-run.md`): start a long command with the Bash tool's `run_in_background`, tail a log with `Monitor` only, and a foreground `sleep` is blocked. `provider addenda NAME local` prints them.
- The tests that run a modified copy of the tool copy it through one helper (`copy_tool` and `TOOL_DIRS` in `tests/hermetic.sh`, read by `tests/hermetic.py`), not a list of directories each spells out; `tests/test_tool_copy.sh` fails until a new top-level directory is in the list or named there as not needed, and fails on a `cp`, `rsync` or `copytree` line of a test that names three or more of the tool's directories by hand (`test_marshal_flow.sh` had one, with a list that left the others out).
- The cloud-only part of the member contract is no longer appended by the core: it is a resource of the `claude-platform` definition. A cloud agent's prompt is the contract, the output format and the contract addenda of the runtime the project uses on its cloud surface; a project with no cloud runtime (or none that resolves) gets no addendum, and no runtime is ever assumed. The prompt hash covers the composed text, so a changed addendum makes an agent's prompt stale. The cloud runtime's addendum states the cloud output directory (`/mnt/session/outputs`); the neutral contract, the cloud preamble and the role seeds do not name it, but `qargi team brief`, `qargi collect` and the `qargi-task` skill still do (`tests/test_prompt.sh` lists them, so the list can only shrink).
- The four role texts are at most 170 words each (from 253 to 314) and the member text is 118 words (from 180): the review role's product is stated as "a report in OUT, not patches", and the member text names OUT, not RUN_DIR, as the place for outputs.
- The member contract (`contract/contract.md`) is about half its length: one commit rule, checks and gates merged, "run the lint and secret-scan gates your packs and profile name" in place of the shellcheck and gitleaks instructions, and "write outputs only to OUT" (RUN_DIR is no longer an output location a member is told about). The detached-gate recipe, the no-wrapper git case and `/workspace/<repo>` moved to a text of the `claude-platform` definition (`lib/providers/claude-platform/cloud-run.md`, listed in its `resources.contract_addenda`), which a cloud agent's prompt carries after the output format when the project's cloud runtime is `claude-platform`. The only memory-write rule a member sees is the task block's MEMORY packet: members propose notes in their report and the lead files them (`qargi-memory` says the same).
- `qargi local prepare` also prints `CONTRACT=<directory>` in the TASK-BLOCK PATHS block (the `contract/` directory of the checkout or of the installed copy), and the member text tells the member to read the contract files there.
- The member contract moved from `skills/qargi-task/agent-contract.md` to `contract/contract.md`, and its "Output files" section to `contract/output-format.md`, which also states the two shapes (patches, or a report and manifest for a read-only role). The cloud agent prompt, its stamp and `install.sh --copy` read the `contract/` directory; the skill-budget test counts both files.
- There is no implicit Claude anywhere: `agent`, `provision`, `local prepare` (the read-only barrier), session starts and `project validate` take the provider from the project's `models.provider` and, when it is unset, stop with exit 2 and `project P has no provider: set one with qargi project set P models.provider NAME`. `agent add|refresh|rename` without `--project` use the project in effect (`QARGI_PROJECT`, else the checkout); `agent for --surface cloud --project UNKNOWN` is exit 2. `project validate` still exits 0 and prints the `finding:`.
- A project's provider is `models.provider`; every verb that takes `--target` (`packs apply`, `packs check`), `packs link` and `unlink`, `skill accept` and `marshal handoff` exit 2 when the project has no provider (`set one with qargi project set P models.provider NAME`) instead of assuming Claude; a name that is not a project says `no such project`. `--target` must be the provider's `layout.render_target` (`claude-code` for Claude).
- `provider check` is no longer on the member guard's read-only list, because it records the result in `verified.json`.
- `qargi agent add NAME` requires `--project P`; `--user` is gone from `agent add`, `refresh` and `rename`, and nothing is written to a runtime's user-level directory.

- `python3 lib/help.py man` keeps the .TH date of `man/qargi.1` (new `--keep-date FILE`), so regenerating the page after `release start` no longer undoes the date.
- `qargi project set P deployment VALUE` says only what was set for a methodology deployment option; the "applies to the next provision" note stays for other values.
- The `qargi-packs`, `qargi-providers`, `qargi-provision` and `qargi-memory` skills are shorter. `qargi-packs` loads in 765 words, from 1784, and `qargi-providers` in 767, from 1957: what you do on every use stays in `SKILL.md`, and the rest is read when needed, in `apply.md` and `seed.md` (render, apply, link, unmanaged skills, the baseline packs) and in `definition.md` and `verify.md` (the fields of a runtime definition, `notes` and `contract_addenda` included; verification, attest and extensions). Their sections on who may change a skill or a runtime are gone: `qargi help guard` and `qargi help approvals` say it once. `qargi-memory` is 947 words, from 1493 (the verbs `seed-role`, `import`, `promote` and `audit`, the seeding of a new project's stores and `memory split|copy|merge` are in `skills/qargi-memory/curate.md`, which loads on demand), with a description that names what it is for; it no longer tells a member where it may write, because members propose notes in their report and the lead files them. `qargi-provision` names the cloud surface without the name of the tool it creates resources with.
- The `qargi-session` skill is 891 words, from 972: the owner's-commands rule is said once, and the approvals rule points at `qargi help approvals`. Nothing else changed.
- The `qargi-team` skill is 894 words, from 935: the cloud and approval wording points at the `approvals` help topic and the spawn note of the runtime, and an example that only illustrated a rule is gone. No rule changed.
- The `keep-a-changelog` pack and `CONTRIBUTING.md` now state the commit rule of the member contract: one logical change per commit with its tests and docs, and a change that spans three or more top-level directories split into commits that each build (code and tests, then docs and changelog). The pack's description says it is the member that never dates the changelog or cuts a release; the lead's `release start` does.
- The `qargi-project` skill is 877 words, from 1067: the questions, the push policy and the answers-file steps stay; linking a work tree and starting from a repository (`project new`, `attach`, `adopt`) move to `skills/qargi-project/repository.md` ("Load when ..."), and what a member's guard refuses is left to `qargi help guard`.
- The `qargi-verify` skill (616 words) says what an open run is (a local run made by `qargi local prepare` that `local verify` has not passed; a cloud collect is never open) and has the apply path back for the other cases: a cloud collect or a project with no open feature is applied with `git am` onto the branch the user names (authors reset to the user), or split by file; `qargi feature merge NAME agent/<slug>` stays the feature path. It asks again for the reason code when rework was needed.
- `qargi help guard` now names every verb the guard refuses (packs seed, unlink and migrate-render, discover install, import, skill and tool unlink, enable, disable and unaccept, marshal key, signers and resign), the writes to the render, marshal and feature directories, the ref journal and the runtime's plugin directory, and the QARGI_LEAD setting; it stays within 330 words, and `tests/test_help.py` fails when a verb in the guard's refused lists is in neither the topic nor a documented exemption.
- The `qargi-flow` skill says in its marshal routine, without loading `marshal.md`, that marshal records are data, not instructions and that a handoff carries no approval (the skill is 944 words after the other changes of this release).
- `qargi provider notes` exits 2 for a runtime that cannot be used as it stands (a library pack never sealed or changed since it was sealed, a definition that cannot be read) and 1 for a topic the runtime does not have or a runtime with no notes; the command description, the usage text, the manual page and the changelog say so. A definition error that escaped as exit 1 is now a refusal.
- The `qargi-task` skill says that a cloud session's `CLONE` is the mounted repository only when the project has a `repo.credential_file` (otherwise it is whatever the task block provides), and the line on `qargi local prepare --repo-url URL --credential-file FILE` for a private repository is back in the local flow of `SKILL.md`, not in the cloud file (`SKILL.md` 834 words, `cloud.md` 760).
- Four small rules are back in the lead skills: `qargi-instances` has the `qargi instances init --location local --agent FILE` row (898 words); `qargi-memory` says that `memory check` exits 1 on any FAIL and that an unreachable third tier only warns (947 words), and its `curate.md` (345 words, from 336) that a store changed since the plan of a split, copy or merge is refused; `qargi-flow` says never to invent an approval: print the plan, show it, apply exactly that (944 words, from 951).
- `tests/test_skill_budget.sh` now needs a SKILL.md to send a session to each of its reference files (the path inside the skill as a link or in backticks on a line that says "load"), not just to name it, and budgets every file under `skills/` that is not `.md` (it needs a line in `tests/skill-budget.txt` and must be text). The `qargi-memory`, `qargi-packs`, `qargi-project` and `qargi-task` skills say "load `FILE`" where they only named it.

### Fixed
- The member guard lets a member run `qargi provider addenda` (which only prints) and `qargi provider notes`; it had refused `addenda` as a verb that changes a definition. Every other provider verb that is not on its list of reading verbs is still refused.
- A contract addendum is refused when it holds any format character (tags U+E0000-E007F, zero-width characters, the byte order mark, the soft hyphen, bidi marks), a private-use or unassigned code point or a line or paragraph separator, besides control characters; tab and newline stay. The check read a fixed list of bidi characters before, which let a tag-character message through.
- `qargi instances refresh-prompt` renders the prompt before any cloud call and stops with `could not render the system prompt` when a contract addendum of the cloud runtime cannot be read (it planned a refresh to a prompt without the addendum, and with the rest of the prompt missing); the stored prompt hash is likewise not recorded for a prompt that failed to render, so `instances show` says `unknown` rather than comparing the hash of a partial prompt. The hashes of a prompt that renders are unchanged.
- `qargi review check` accepts a read-only run's report under an `OUT_PREFIX` (`review--report.md`, as `qargi team brief` makes the review member write it), not only `report.md`; the guard's refusals to a read-only member say the report goes to `OUT` (they said `RUN_DIR`, which the contract no longer names as a place), and the refusal of a skill change says to propose it in the report.
- Texts that told an agent something the member contract does not: the cloud preamble and the lead's contract let members write the memory store under `roles/<role>/` (members propose notes in their report and the lead files them; a store is written only as the task block's MEMORY packet says) and named `RUN_DIR` as the output place (it is `OUT`; the `qargi team brief` entry for a cloud member now says `OUT: /mnt/session/outputs`, and the task block in `qargi-task` says the same). The lead session's memory-tier line says the same. The cloud output directory is stated in the `claude-platform` addendum (see Changed for the other places that name it).
- The member guard no longer refuses every file write because one provider definition in the library is broken; it skips it with one note and keeps the other roots. Hook data that would let a call through unjudged is refused, and `compatible_providers` names with a trailing newline are rejected.
- `qargi local clean` refuses a run whose commits were never applied, or whose applied branch is not merged into a branch other than `agent/*`; `--discard` drops them on purpose and says how many. A failed apply or merge in a loop can no longer delete finished work.
- `packs check --target claude-code` no longer reports "shadowing" for every rendered skill once the checkout's `.claude/skills` is the link made by `packs link`.
- A library provider pack with no record (placed by hand) is no longer loaded, run, checked or attested: seal it or import it. Skill packs are held to the same text-only policy as provider packs (no binaries, archives, links or special files; scripts stay allowed and are listed), the review of a provider, skill or tool pack refuses control and bidi characters, also when written as JSON escapes, and prints everything escaped, and `dispatch.env_pass` refuses names such as HOME, PATH, `LD_*`, `GH_*` and `SSH_*`, shows what it passes in the review, and `provider check` runs adapters with a fixed environment.
- `qargi local run` builds from the project's composed definition. A read-only run is refused when the barrier comes from an extension, or an extension only claims one, unless the project records `provider accept`. The prompt file lives in `RUN/prompt/` and can no longer overwrite the run's control files.
- `models.extensions` and `models.accept_no_barrier` can be changed only by `provider enable|disable` and `provider accept`: `project set` refuses them for everyone, and `project init`, `attach` and `new` refuse a file that adds or changes an entry (dropping one is allowed; restore a project from a file by `project init`, then `provider enable`), the private store has no environment switch, and the member guard refuses a member `project set|init|link|unlink` whenever it cannot read the words statically (variables, substitutions, xargs, braces, globs).
- A runtime that claims `read_only_barrier` with barrier kind `none` and no read-only arguments fails `provider check` and import, and reads as no barrier (`provider effective`, `require-barrier`, `agent add` of a review member); `local run` of a read-only member is refused for it, and for a runtime whose own barrier is a hook or adapter, unless the project ran `provider accept`. Only arguments for the read-only class count as a barrier.
- `provider check` fails a barrier hook whose refusal can never be told from an allow (equal exit codes, or an empty stdout object), so such a barrier is never verified.

- An interrupted set-up of an empty memory or reference store, or of a directory tier, can be finished by running it again: a store with no marker whose files are the first files of the set-up counts as empty and the rerun creates the rest, the marker last.
- `agent refresh|rename|remove NAME` inside a project's checkout acts only on that project's member: if the project lacks NAME the verb exits 2 and asks for `--project` (it no longer reaches another project's member). A members file with a record that lacks `roles` or `file` is refused by every agent verb with one line naming the member. `qargi upgrade` warns, in the plan and after applying, when `agents.json` is in an earlier shape. `agent models` needs a project (`--project`, else the one in effect).
- The manual page has a GUARD section (the `guard` help topic), so the "See APPROVALS" pointer and the approvals topic's reference to what a member's guard refuses resolve in `man qargi`; `tests/test_help.py` compares the APPROVALS and GUARD sections of `man/qargi.1` with what `man()` writes from the topics, instead of looking for the word "guard" anywhere in the page.

### Removed
- From the role texts: the opening paragraph that described the role and the contract, the "Before DONE" tail that repeated the contract, the build role's "Return numbered patches" line, the review role's enforcement note, and, from the write role, the paragraph on a documentation branch with no shared history, the PDF-skill sentence and the bullet that logged work in the memory store (a member proposes notes in its report).
- The contract's "Before you report DONE" section and its final-report Memory paragraph, and the build role's sentence that sent durable facts to a memory store under `roles/build/`.
- Schema 1 provider definitions: `lib/providers/claude.json`, `schema.json`, the `claude/adapter` router, `provider migrate` and all schema-1 code. The bare name `claude` is no longer a runtime (`unknown provider 'claude'`); `models.provider: "claude"` still resolves as the family of `claude-code` and `claude-platform`. `project template` no longer reads a Claude file: roles carry `model: null` until a provider is set.
- `qargi migrate` (both `roles` and `home`), the refusal that told you to run it when only the earlier XDG directories exist, the import of archives made with the old role names (`qargi import` takes an archive as it is), and `lib/roles.py`. The guard no longer protects `~/.config/qargi`.
- `install.sh` no longer removes the retired ability skills (`qargi-build`, `-write`, `-review`, `-test`), old agent links or the old `qargi` and `dev` skill links: remove any left over by hand.
- Canon chains older than version 2: such a store is `unknown` (plan nothing, apply refuses; bring it in by hand or with `canon import`), `canon plan|apply --default-role` is gone, and so are `provision/canon-seed/v1/` and `tests/canon_sim.py`. Setting up an empty store has its own step ("from empty").
- `agent add --abilities` (use `--roles`) and `local prepare --ability` (use `--role`) are unknown options.
- The one-per-ability fallback: `agent for ROLE` resolves only the project's `worker` or `reviewer` and exits 1 with the `agent add` command when the base is missing; `agent for --json` loses `legacy`; `agent models` flags `not a base` instead of `legacy`.
- Members with no project: `agents.json` is `{schema: 2, projects: {P: {NAME: record}}}` and any other shape makes every `agent` verb exit 2 without touching the file (move it aside and add the members again with `agent add NAME --project P`). Two projects can each have a `worker`; `agent list` shows PROJECT, NAME, ROLES, MODEL/EFFORT, FILE; `agent remove NAME --project P` is new, and `rename`, `refresh` and `remove` take `--project` (else the project in effect, else the only project holding the name). In `agent models --json` the member field `abilities` is `roles`.

## [0.2.0] - 2026-11-02

### Added
- `qargi marshal forget NAME`: drops this machine's accepted marshal mark of one feature, so a stale mark (left after the feature was
  deleted or re-created on the remote) stops reporting `rollback detected`. It needs integrity advisory or strict and a mark for NAME,
  prints the mark's revision and commit in a plan whose token covers both, applies with `--plan` and your words (audited as
  `marshal:forget`), touches no other feature and nothing on the remote, and is refused in a member run.
- `qargi project adopt PROJECT`: closes the safe gaps of an attached repository. With a plan token and your words it creates the missing
  long-lived branches locally (at the default branch tip; none is moved) and writes the methodology files that do not exist as one commit
  on `agent/adopt-<methodology>` cut from develop, for you to review. It never overwrites a file, never pushes, leaves the working tree
  alone, refuses a dirty tree, a detached HEAD and a member run, and lists the changelog format, tag format and CI content as left for you.
- Signed marshal records. With the shared marshal, each lead machine can have its own ssh key (`marshal key init`), a per-project
  signers file lists the trusted keys (`marshal signers add|remove|list`, never in the repository or the refs), and
  `marshal enable --integrity off|advisory|strict` sets the mode. Records are signed with `ssh-keygen -Y` (namespace `qargi-marshal`) over
  a canonical payload that names project, feature, kind, revision, parent and lead, so a record cannot be altered or moved to another
  feature. Advisory tags records signed, unsigned or INVALID; strict ignores unsigned and invalid ones and falls back to the last
  accepted record. A local high-water mark detects a rewound ref (`rollback detected`), and junk or replayed pushes neither renew a lease
  nor block a feature. `marshal resign NAME` signs an existing record when moving from advisory to strict. Keys, signers and the mode
  are yours to set; nothing is signed until you choose a mode. Members cannot read the signing key or change the signers.
  Review hardening: a lagging machine builds on the newest signed record rather than overwriting it; advisory builds on an unsigned head
  instead of dropping it; a signed finish records the last features commit so a reused name keeps its rollback mark; records are
  identified by what the signature covers, so a re-committed head is the same record; `resign` shows the head, lead and goal in a plan
  whose token covers that head and refuses a lead other than the accepted one; `disable` needs the plan token and your words while
  integrity is on; the guard follows `pushd`/`popd`, refuses links and moves of the key, and normalises `/./` in scanned text.
  Member definitions now also hook the guard on the Read and Grep tools (to keep the key unread); members created earlier keep the old
  matcher until they are refreshed (`qargi agent refresh NAME`).
- Shared marshal. `qargi marshal enable|disable` switch a project between the local records and a shared backend that keeps each
  feature record as a commit on `refs/qargi/features/NAME` of the remote origin: create-only claims, leased updates, an atomic move
  to `refs/qargi/done/NAME` on finish, a fetch that never brings other refs, and takeover judged on the taker's own monotonic clock.
  It is off by default, needs the plan token and your typed words, is audited, cannot be used from a member run, and `project set`
  refuses `marshal.*` except `marshal.ttl`. Offline verbs use the cache and say `remote not checked`; an offline claim is
  `provisional`. `local verify` ignores `refs/qargi/`; `marshal status|check` take `--no-fetch` (the session hook uses it).
  Hardening from review: an offline claim is dropped, not pushed, when another machine finished the feature meanwhile; remote records with
  wrong field types are ignored instead of crashing readers; `takeover` of a provisional claim is refused; the lease renewer survives an
  unreachable remote (exit status 3, `remote not checked`) and stops only on a lost lease; the fetch leaves `FETCH_HEAD` alone (git 2.29+);
  `marshal` ignores `APPROVED` and `PLAN_ARG` from the environment; and `qargi feature start|finish|verify` are refused to a member.
- Cloud profiles. A project can provision two cloud base agents, `<project>-worker` (write class) and `<project>-reviewer` (read-only),
  and start a session of a role and profile on one: `qargi start|send <project>-worker --role build --profile build`. The model and
  effort are overridden per session with a full model object and the role's prompt is rendered fresh, so the base needs no prompt
  refresh; its tools stay fixed on the agent. `agent for ROLE --surface cloud` resolves the instance and uses a base only when it is
  registered and the provider's cloud override capabilities are verified (they now are for `claude`, from a scratch run on
  2026-11-01); otherwise the four role agents keep serving, and a profile with a different model than the role agent refuses.
  A reviewer base needs the project's `provider accept` for the missing cloud read-only barrier before it is provisioned or started.
  The claude adapter gained a `start-session` request builder, with a conformance check that a body never carries tools, skills or
  MCP servers.
- Providers. Each model provider is a descriptor (`lib/providers/NAME.json`, one schema) with its tier-to-model map and verification
  dates, effort levels, surfaces and a per-surface capability matrix; `qargi provider list|show|check` prints and validates them,
  and `check` says what degrades (an unverified capability counts as unsupported). The `claude` provider has a local adapter
  (`lib/providers/claude/adapter`: resolve, dispatch-local, barrier-check) behind which members are rendered, and the Claude model ids
  and id pattern that were spread through the code now come from its descriptor. A surface with no read-only barrier cannot serve
  the review role unless the project records `models.accept_no_barrier` with `qargi provider accept` (plan and token, audit-logged);
  for `claude` that means a cloud review role needs your acceptance, while the local guard counts as a partial barrier. A provider with
  no effort control has the effort dropped and `agent models` says so, `agent for` refuses a profile on a provider that cannot override
  the model per dispatch, and `local verify` and `review apply` never apply patches from a read-only run. `bash tests/conformance.sh NAME`
  runs a conformance suite (verb shapes, unsupported verbs, secrets out of argv, a barrier corpus, the read-only definition) against an
  adapter, with a deliberately broken adapter proving the suite catches faults. A member cannot run `provider accept`.
- Base members and profiles. Two base members, one per guard class: `worker` (build, write, test) and `reviewer` (review, read-only);
  `qargi agent add worker|reviewer` defaults to the base's own abilities and refuses abilities of the other class. Specializations
  are profiles {base, tier, effort, purpose}, resolved at dispatch: shipped `build`, `write`, `test`, `review`, `auditor` (Haiku),
  `advisor` (Opus) and the opt-in `researcher` (frontier tier), plus your own under `profiles.NAME` in a project's answers (validated;
  a profile whose abilities do not fit its base's class is refused). `qargi agent for ROLE [--profile NAME] [--json]` now prints one
  line, `MEMBER MODEL EFFORT PROFILE`, and the lead passes the model and the effort to the Agent tool, which override the member
  definition. `qargi local prepare --profile NAME` resolves the profile before any clone, records it in `RUN/profile` (a file the guard
  keeps from the member) and prints `PROFILE`, `MEMBER`, `MODEL` and `EFFORT`. The tier-to-model table lives in the provider file
  (`lib/providers/claude.json`, with an alias per tier for local dispatch). `qargi agent models` flags legacy per-ability members,
  a missing base, refused profiles and mixed-class members. The earlier model-table entry is superseded: `roles` and `suggested`
  became `profiles`, and `auditor`, `advisor` and `researcher` are profiles, not members.
- Model selection. One table (`lib/model-defaults.json`) names a tier and an effort for the lead and each role (Sonnet 5.5 for the
  lead, build, write and test, Opus 5.5 for review), and `lib/providers/claude.json` maps the tiers (fast, balanced, deep,
  frontier) to models; a project chooses the provider with `models.provider`. `qargi agent add` takes its model and effort from
  the project's answers, else the table, and writes the effort into the member definition (so does `agent refresh`); the project
  template does the same, and its write role is now Sonnet rather than Opus. `qargi agent models [--project P] [--json]` shows
  the table, the project's overrides, the shipped profiles (`auditor` on Haiku, `advisor` on Opus, `researcher` on the opt-in
  frontier tier, Fable 5.1) and each member, marking an alias as unpinned and a frontier member as opt-in. The flow skill has an
  advisor sign-off before `feature finish` and says search is a read-only exploration on a small model, not a role.
- `qargi marshal status --all` (and `--brief`, `--json`, and the session-start hook that uses them) lists only the open features;
  `--history` adds the finished and abandoned records after them. `qargi marshal check NAME` for a name that has no branch and no
  record now exits 1 with `no feature NAME`, and so do the flow verbs and `local prepare --base feature/NAME` for such a name.
  The error for a branch that is checked out elsewhere says how to free it (`git -C DIR checkout --detach`).
- Memory tiers (writing, second slice). The session-start hook now lists the notes of the tiers, highest first, as data after the
  marshal block (at most 4000 characters per note and 16000 in all; a tier that is missing or unreadable is skipped and named).
  `qargi memory init TIER` creates a tier from the standard layout and `qargi memory move PATH --from TIER --to TIER` moves a
  note, or a folder of notes, between tiers; both print a plan and a token and apply only with your approval, and nothing is
  synced or deleted without it. A repo tier with notes that are not committed warns with the count. `local prepare` prints a
  TASK-BLOCK MEMORY packet for the member, and the guard refuses a member every verb and script that writes a tier. The memory,
  task and canon documents describe the tiers.
- Baseline packs. qargi ships three packs under `packs/`: `shellcheck-gate` (lint every shell file you touch and quote the verdict),
  `keep-a-changelog` (one Unreleased entry per user-visible change, in the same commit) and `gitflow-member` (a member's part of
  a git-flow project). `qargi packs seed` stores them in your library: it prints one line per pack (add, update, current or
  kept) and a plan token, and applies with your approval; an untouched shipped copy is updated when qargi ships newer text, a
  copy you edited and sealed or a pack of your own with the same name is kept and never overwritten, and seeding never links a
  pack. `install.sh` (and so `qargi upgrade`) adds the packs your library lacks with `packs seed --install`, which needs no token
  and never updates. Link a pack to a project with `qargi skill link`; proposing links when a project is created or attached is
  not built yet. A member cannot run `packs seed`.
- Memory tiers (read-only, first slice). A project's memory is five ranked tiers, highest first: repo, cloud, project, shared,
  system. A tier is a memory store of the standard layout in a directory (defaults under the qargi root; `memory.tiers` in the
  project answers moves any of them) or, for cloud, the project's memory store. `qargi memory tiers [--json]` lists them with
  their state and note counts; `qargi memory check` runs the canon check on each tier that exists and fails when a note path
  is present in two tiers (README, INDEX and the like repeat per tier by design). The reference store is not a tier. Nothing is
  written to a tier; creating and moving notes between tiers, and the session hook composing them, come later.
- Agents write verified facts only under their own role folder of the memory store; `shared/` is curated and reached by
  promotion (`qargi canon promote --approved`) or by the person, and an agent proposes a shared note in its report. The cloud
  preamble, the store README, the lead contract, the build role and skill and the canon say so. `canon audit` still reports
  only cross-role writes, so an agent writing under `shared/` is not yet detected. The cloud prompts change: refresh them.
- A lead-only ref journal (`ref-journal.jsonl` in the state directory) records every local branch that qargi's own verbs create,
  move or delete (`feature start|merge|sync|finish`, `release`, `review apply|prune`). `local verify` now accepts a branch
  change since the run was prepared when the journal leads from the snapshot to the branch's current value, so several runs
  prepared in parallel all verify after the lead merged the first one. Remote refs, tags and any unjournaled move are still
  refused, and the refusal says so. The guard keeps members from writing the journal; it is trusted only as far as the state
  directory is (signed records come later). `local prepare` records `RUN/started`.
- `qargi marshal` keeps one record per open feature: its lead (a Claude Code session, identified by the session id the SessionStart
  hook exports as `QARGI_LEAD`, or `--as`), a lease, status, goal, plan and note. `claim`, `status [--all] [--brief|--json]`,
  `set`, `check`, `renew`, `release --note`, `take`, `takeover --approved` and `finish`. Tasks, agent branches, worktrees and
  files that two features both change are derived from git and the local runs, not declared. Query it before starting work:
  `qargi marshal check NAME` refuses when another live lead holds the feature and warns about a stale lead, an anonymous
  identity and overlap. The lease is `marshal.ttl` minutes per project (default 15; `qargi project set PROJECT marshal.ttl N`),
  renewed by the lead's actions and for the whole run of `feature verify` and `feature finish`, so a suite of any length is
  safe. A feature whose lead stopped is taken over only after the lease ran out and with your words, which are audited.
  Records are local to the host unless the project switches to the shared backend (`marshal enable`).
- `feature start|merge|sync|verify|finish` and `local prepare --base feature/X` ask the marshal first and refuse when another
  live lead holds the feature; `feature start` records the starter as lead, `finish` marks the record finished, `feature
  status` ends with the marshal's view and `feature list` shows each lead. A marshal that is absent or fails never blocks.
  `local-runs.jsonl` lines gain `lead`.
- The session-start hook lists the open features as data for the lead session. The guard keeps members from the mutating
  marshal verbs, from the state `features/` directory and from setting `QARGI_LEAD`.
- `qargi release start` has a preflight. Before it creates the branch it checks what a release must update and refuses,
  changing nothing, with a message naming the file and the fix: a man page (`man/*.1`) needs a `.TH` line with a date and a
  version field, and the first commit now sets them to the release's date and `VERSION`; a `CHANGELOG.md` needs a
  `## [Unreleased]` section with content (`--allow-empty-notes` waives that). Projects without a man page or changelog are
  not checked for that part.
- Roles. A role is a directory with `role.json` (its class, `write` or `read-only`, and a description) and `ROLE.md` (its
  instructions). `build`, `write`, `review` and `test` ship in `roles/`; add your own under `~/.qargi/config/roles/NAME/`
  (one lower-case token, never `lead`, never a built-in's name). `qargi role list|show|prompt|check`. A local task names its
  role (`qargi local prepare --role R`, which records the class in `RUN/class`; `--ability` still works), the task block
  carries the role's text, `qargi agent add --abilities` and `qargi agent for` take any role (a role of yours without a member
  falls back to a member of the built-in role of the same class), and a cloud agent of a role gets its text in its system
  prompt. The class, not the name `review`, decides what the guard allows and which cloud tools are off.

- `qargi local clean RUN` removes a collected, verified local run (clone, bare copy, output) and its private temporary
  directory. `qargi local prepare` makes that directory (`TMP`, on `/dev/shm` when it exists, `QARGI_RUN_TMP` moves it) for
  the agent's test sandboxes, so parallel runs never share files and a run leaves nothing behind. The agent contract asks for
  targeted checks per task (the full suite belongs to the coordinator after a collection), and the task skill describes
  dispatching non-overlapping tasks in parallel.

- Methodologies. A methodology is the way a project is developed and released, as data: branches (long-lived, release
  `feature/<version>`, task `agent/<slug>`), versioning and changelog, test tiers (targeted per task, the whole suite once per
  collection), CI, release steps, deployment options with instructions, and the generic files a new project starts with
  (README, VERSION, CHANGELOG, CONTRIBUTING, CLAUDE.md, .gitignore, a GitHub Actions test workflow). `gitflow` ships in
  `methodologies/`; add your own under `~/.qargi/config/methodologies/NAME/`. `qargi methodology list|show|check|files|deployment`
  only read; the scaffold carries no reference to qargi.

- `qargi project attach [DIR]` attaches qargi to an existing repository without changing it. It reads the remote, branches, tags,
  version and changelog files, test command and CI, prints the answers it would store, the gaps against the methodology and
  what it could not determine, and a plan token; with `--plan` and `--approved` it stores the answers outside the repository.
  The safe gaps are closed by `qargi project adopt`, the rest by hand.

- `qargi project new NAME` starts a project from a methodology: it prints a plan (directory, branches, files, deployment
  options with instructions) and a token; with `--plan` and `--approved` it creates the directory, runs `git init`, writes the
  generic files in a first commit and creates the long-lived branches, leaving you on `develop`. With `--url` the qargi answers are
  stored too. Nothing is pushed and no remote is created. `--deployment ID` records a deployment option and prints how to do it.
  The generated `.gitignore` excludes `.claude/worktrees/` and `.claude/settings.local.json`.

- Git-flow, as its author described it. `qargi feature start|list|sync|merge|status|verify|finish`: a feature is a broad, related branch
  cut from `develop`; verified task branches are merged into it with `--no-ff`; the whole suite runs once when it is complete, and
  only then is it merged into `develop` (one merge per feature). Several features can be open at once; `feature list` shows their
  purposes and the files two of them both change. `qargi release start|status|verify|push|finish VERSION [--hotfix]`:
  `release/<version>` from `develop` (a hotfix from `master`), the version bump as its first commit, a pull request into `master`
  so CI runs on the commit that will be released, then merge into `master` with `--no-ff`, an annotated tag, merge into
  `develop` (a hotfix: into the open release branch), delete, push. Merges are made in temporary worktrees and a branch moves only
  after every merge succeeded; a conflict changes nothing, keeps the merge in progress in a worktree it names (exit 3), and
  `--resolved` applies the merge you resolved. Merging and pushing need a plan token and an approval; a release starts only from
  a `develop` whose head passed the whole suite. A finished feature's whole-suite run carries over to `develop`'s new head, and
  a feature must contain `develop` to finish, so a release needs no extra run. A release or hotfix finishes only on the commit that is
  on origin with passing checks, and pushes master, develop and the tag together or not at all.

- The `feature finish` and `release finish` plans list the commits and files being merged, so the approval is informed.
- The `qargi-flow` skill: the lead's git-flow process with the qargi commands (features and tasks, the one whole-suite run per feature,
  releases, hotfixes, resolving conflicts). A session that leads is pointed at it when it starts.

- `qargi review apply RUN_DIR` puts a collected run on a task branch of the project's repository: it needs `review check` and
  `local verify` to pass, creates `agent/<slug>` (or `--branch`) at the commit the base had when the run was prepared and applies
  the patches with `git am` in a temporary worktree, so your checkout is never touched. A patch that does not apply removes the
  branch again; a run is applied once. `qargi review prune [--yes]` lists, or deletes, the `agent/*` branches already merged into
  `develop` or a `feature/*` branch.

- `qargi packs apply --target claude-code PROJECT` renders the skills and tools a project has enabled into a managed state
  directory, `$QARGI_STATE/claude/PROJECT`, replacing the previous render atomically, and prints the exact
  `claude --add-dir ...` line that loads it. It needs no `--asked`; without `--approved` it prints a plan token. Skills render
  under `.claude/skills`, tool packs as `mcp.json` and `settings.json`, with a manifest. Claude Code cannot enforce role scoping,
  so the render is the union of the project's roles and role scoping is advisory there. Nothing is written into a repository or
  into `~/.claude`. `qargi packs check --target claude-code PROJECT` (read only) exits 1 on drift: a changed or unreviewed pack,
  a tampered, extra or missing rendered file, an enablement change, a rendered skill shadowed by `~/.claude/skills` or the
  checkout's `.claude/skills`, or a missing manifest. `--target managed-agents` is the existing cloud update of an instance.
- `qargi packs apply --target claude-code` refuses at plan time, naming the pack and writing nothing: a `SKILL.md` whose name
  differs from the pack name or whose front matter is not closed or has two `name` keys, a skill and a tool with the same name,
  and a tool allowlist name outside letters, digits, `_`, `.` and `-`. Each plan stages into its own hidden directory under a
  lock, so concurrent applies serialize and the second refuses if the render changed meanwhile.
- `qargi packs check --target claude-code` also reports a rendered file that differs from the library copy, a changed file mode,
  a group- or world-writable render, a malformed manifest, and a manifest naming another project or with role scoping other
  than advisory.
- `qargi local prepare` prints a WARNING block to stderr when the project's Claude Code render has drifted (the project is found
  by matching the repository against the stored answers), with the findings and the fix, `qargi packs apply --target claude-code
  PROJECT`. The run goes on; stdout and the TASK-BLOCK PATHS block are unchanged.
- The guard protects that directory: members can no longer write under the state's `claude/` directory, and the operands of
  `packs render` are judged as write destinations.
- A GitHub Actions workflow runs the whole test suite on pull requests and on pushes to `develop`.
- `qargi packs load [PACK] --role R [--project P]`: read-only. Without a pack it lists what the role has enabled, with each
  description; with one it prints its approved text and the library path of its other files. It reads the links when called,
  so linking, unlinking, enabling and disabling take effect at once, and it refuses a pack that fails its review or changed
  since it was approved. Members may run it.
- `qargi upgrade [--branch B | --tag T]`: plan, then apply with `--plan TOKEN --approved "..."`: moves the installed tool (the root-owned checkout
  `install.sh` recorded) to a newer branch (fast-forward only on its current branch) or tag of its origin, re-runs
  `install.sh --user` and lists the members to refresh. The writing git commands run through `sudo`; members cannot use the verb.
- `qargi cloud list|show|set|unset|check|login`: bind a project to an `ant` profile and the workspace it must reach
  (the project's optional `cloud` answer). Every command about that project then runs `ant` under that profile,
  and a cloud call is refused if the profile no longer reaches the workspace; a conflicting `ANTHROPIC_PROFILE` is
  refused. Projects without a binding are unchanged. qargi never reads or writes a token: `login` runs
  `ant auth login` on your own terminal, and members cannot use `set`, `unset` or `login`; the guard also protects
  `~/.config/anthropic`.
- `qargi mark SID applied|rejected --why CODE` records a reason (codes in `lib/reasons.json`); `qargi report` counts them.
  `mark` now refuses a session the tracker does not know.
- `qargi noticed list|resolve`: collecting a session records the `noticed_not_acted_on` notes of its manifest
  (short, secret-looking strings redacted, once each) in the append-only `events.jsonl` beside the audit log;
  each stays open until given a disposition (followup, dismissed with `--why`, accepted, superseded);
  `qargi report` shows how many are open and how old the oldest is, never the text.
- `qargi agent refresh NAME`: re-render a member from the member definition qargi ships now, keeping its
  name, abilities and model, so members created before a change (such as the hardened hook) can catch up
  without being removed and re-added.
- `qargi memory split|merge|copy FROM TO`: move memory between two stores, each a directory of
  notes, a `.jsonl` dump or a `memstore_` id. Nothing is deleted: what a split archives goes to
  `/_archive/<date>/` and a collision to `/_conflicts/<date>/`, with the origin of every note
  written added to its `Sources:` line, so each change can be undone (merging a split's target
  restores the archived originals byte for byte). Without `--approved` they print the plan and its
  token and change nothing; a store whose notes changed since the plan is refused and left as it
  was. On a directory store qargi's own writers are serialised by an exclusive lock, and each write
  re-reads the note immediately before replacing it or releasing its name, so a change made by an
  editor in that instant is refused and kept, not overwritten; an editor that writes in the last
  instant after that read is still not prevented (the lock is advisory), which is why the digest
  check exists. `lib/membackend.py` is the backend interface (directory, fixture dump and Managed Agents
  store through `ant`) with one ops executor, `lib/memplan.py` the pure planning;
  `lib/canon.py` gains `make_plan`, the migration plan `canon plan` prints, for reuse.
  A `.jsonl` dump is read-only (a source, never a target of split, merge or copy). A note named
  with a leading dot or trailing white space is not a note, and a note the target cannot hold
  (too many path segments or too large for a Managed Agents store) makes the plan refuse and name
  it. The plan token is always required: `QARGI_NESTED` does not stand in for it, and the audit log
  records the token, the selector and every step, with a second line once the apply succeeded.
  `merge` and `copy` without a selector leave the source's `/_archive/` behind. A
  provenance segment counts only when its digest matches the note it was added to. `/_archive/`
  is a tolerated folder of canon 2 (`canon check` warns about a note there without our segment).
  Known limit: `canon apply` is not run through the new executor; `memplan.migrate` exists for it.
- `qargi report [--since DATE] [--instance NAME] [--stale-after D] [--local-stale-after D] [--runs-root DIR] [--json]`: a read-only report from the session tracker (spend and spend per applied session, sessions pending review oldest first, sessions that look stale, idle sessions by why they stopped, time from creation to close) and from local run directories (finished DONE or BLOCKED, no manifest and still changing, no manifest and quiet: possibly stalled). It states what it cannot tell and never prints a session's note or request.
- `qargi local prepare` appends one JSON line per run (run directory, slug, ability, base, start time) to `local-runs.jsonl` in the state directory, so `report` can list local runs.
- `instances refresh-prompt --if-stale`: does nothing, with no cloud call, when the prompt rendered now has the hash recorded at the last provision or refresh. The registry entry of a cloud instance gets a `prompt` object (`sha`, `skill`, `at`); `instances list` marks a changed prompt `prompt STALE`, and `instances show` says which part changed. An entry without a hash (older release, or `instances init`) is unknown, not stale.
- `qargi supervise tick|status|nudge|delivered|hooks`: the first version of the stalled-agent supervisor. Hooks only record; one idempotent tick (the only writer of `runs.json`, under a lock) folds the per-run event files, the local-run registry and the session tracker, classifies every unfinished run in a fixed order (waiting on an approval, API stop failure, interim with a cap, looping on three identical tool digests, suspected dead on stale activity; cloud: `requires_action`, `budget_reached`, stale while running, idle awaiting review) and acts only by printing `QARGI SUPERVISE <class> <run> <next-action>` lines, appending to `supervisor.log` and the audit log (origin `supervisor`), and preparing a nudge in `nudges.jsonl`. A nudge is a fixed template, at most 2 per run with at least 10 minutes between them, never while the run waits or has little budget left, and never an approval; a local one is delivered by the coordinating session and counts once `qargi supervise delivered KEY` records it, a cloud one is sent only by `qargi supervise nudge SID --asked ...`. Nothing is sent automatically (a standing permission is a documented extension point, off). Thresholds are data in `lib/supervise-defaults.json`: conservative floors until `qargi report` shows real run lengths. `status` warns when the last tick is older than twice the interval.
- `qargi hook subagent-start|subagent-stop|tool-use|tool-failure|notification|stop-failure|pre-compact`: handlers for the Claude Code hooks that append one small line (ids, times, the tool name and a hash of its input; never a command, message or error text) to `run-events/<agent_id>.jsonl` in the state directory. They exit 0 at once, even on malformed input. `qargi supervise hooks` prints the settings snippet; it never writes `settings.json`.
- `qargi report` has a short Supervisor section (suspected stalls by class, what waits on you, prepared nudges awaiting action) once a tick has run.
- The audit log may carry an `origin` field (`supervisor`); the tracker row records `last_processed_at` (the session's `updated_at`) on refresh.
- Sessions record `interrupt_sent_at` when `qargi stop` sends the interrupt (an interrupted turn also ends with `end_turn`) and `stop_event_ids` for `requires_action`.
- `QARGI_HOME` replaces the root `~/.qargi` that holds `config/` and `state/`; `QARGI_CONF` and `QARGI_STATE` still win over it.
- `qargi migrate home`: copies the data from the earlier XDG directories to `~/.qargi/config` and `~/.qargi/state`. Without `--approved` it prints the plan (every directory, file and link with mode and digest, the `*.lock` files it skips, the files in which it rewrites old absolute paths: a project's credential file, `local-runs.jsonl`, anything else naming the old directories; the records `audit.log`, `supervisor.log` and `run-events/` are copied byte for byte and the plan lists them on a "Copied verbatim (records)" line) and a plan token covering it, and changes nothing. With `--plan TOKEN --approved "<words>"` it copies (the old directories stay as a backup), keeps modes (credentials 0700, files 0600), checks every file by digest, removes what it made if a step fails, refuses when the new root exists and is not empty, and logs an `audit.log` line. Run again it says there is nothing to do.
- Dev runs: `install.sh --user` records the tool it installed in `<config>/install.json` (`--uninstall` removes it; `--project` writes nothing). A checkout run from any other place, with none of `QARGI_HOME`, `QARGI_CONF` and `QARGI_STATE` set, keeps its data in `<checkout>/.qargi` (git-ignored), prints one `qargi: dev run from ...` line on stderr per command (none for `help`, `version`, completion, the guard and the run-event hooks), and never touches live data; with no `install.json` a checkout behaves as the installed one. `qargi migrate home` refuses in a dev run unless a location is named. See `qargi help dev`.
- `lib/paths.py` and the top of `lib/lib.sh` are the one place each language resolves these locations; the nine copies of the XDG logic are gone.

### Changed
- The plan token of `packs apply --target claude-code` also covers file modes, the manifest records them, and the swap installs
  only the tree the token approved.
- `qargi local verify` and `qargi local clean` accept the lead's own work. After a passing verify the run records `RUN/verified`,
  and later checks compare with it: fast-forwards of `develop`, `master` and `agent|feature|release|hotfix/*` branches and new
  branches there are accepted, while remote refs, tags, deletions and rewrites still fail. A change now exits 2 (it was 1). Run
  `qargi local verify` on every run before merging any of them.
- `qargi local prepare` ends its output with a blank line and a `TASK-BLOCK PATHS` block (`RUN_DIR`, `CLONE`, `OUT`, `TMP`, `GIT`,
  `BASE_SHA`); a caller that evals the output must stop at the blank line.
- `qargi project attach` reads the tree of the integration branch (`develop`, else the default branch, else `HEAD`) and says which,
  not the working tree. It prints origin as read and the normalised url. When answers are already stored it shows stored against
  detected and the fields the stored file lacks, stays read-only and gives no plan token; with `--force` the plan keeps what it
  cannot detect (the roles' models and effort, cloud, memory, budget).
- `qargi feature start` refuses a name origin already has, asked live with `git ls-remote`.
- `qargi feature status|finish` and `qargi release status|push|finish` ask the live origin with `git ls-remote` where the branches
  are (`QARGI_REMOTE_TIMEOUT` seconds, default 10) instead of the last fetch, and print `remote not checked` when origin cannot
  be reached.
- `tests/run.sh` runs without the caller's cloud binding or any `QARGI_*` or `ANTHROPIC_*` variable and with a fresh `HOME`, and
  every test is hermetic (`tests/hermetic.sh`, `tests/hermetic.py`): fresh qargi config and state, and failing `ant` and `claude`
  stubs first on `PATH`.
- The role and contract text lists the rules to follow before DONE. Every cloud agent's prompt changes: run
  `qargi instances refresh-prompt NAME --if-stale` for each.
- `qargi feature verify` and `qargi release verify` run the project's test command without the project's cloud binding
  (`ANTHROPIC_PROFILE`, `QARGI_CLOUD_WORKSPACE`, `QARGI_CLOUD_PROJECT`), and `tests/run.sh` unsets them, so a project with
  a cloud binding can get a passing whole-suite record.
- The cloud agent contract, the member definition and the task skill speak of a role and its text instead of loading an
  ability skill. Every cloud agent's prompt changes: run `qargi instances refresh-prompt NAME --if-stale` for each. The
- Breaking before 1.0: the default locations are `~/.qargi/config` and `~/.qargi/state`, not `$XDG_CONFIG_HOME/qargi` and `$XDG_STATE_HOME/qargi`; the XDG variables no longer move qargi's data. While only the earlier directories exist, every command except `help`, `version`, completion, `__guard`, the run-event hooks and `migrate home` stops and asks you to run `qargi migrate home`; qargi never creates an empty `~/.qargi` next to old data, and `install.sh --user` does not record the install until then.
- The member guard protects the pack library, `<config>/credentials/` and `<config>/install.json` at the new location (the resolved configuration directory, `$QARGI_HOME/config`, the live one and `~/.qargi/config`) and keeps the earlier XDG paths protected as a backup. The rest of the configuration directory stays writable (the guard decides by path, not by qargi verb), and reading a protected path is still allowed.
- The member guard refuses a member every skill-modifying verb: `qargi skill|tool new|import|seal|remove|unlink|link|enable|disable`, `qargi discover install`, `qargi packs apply` and `qargi import` (found after wrappers, in `sh -c`, `eval` and `$(...)`, and when `packs.sh` or `discover.py` is run directly), setting `QARGI_NESTED`, and writes under the pack library (`$QARGI_CONF/packs`, honouring the XDG defaults), `~/.claude/skills`, `~/.claude/agents`, `~/.claude/plugins` and any `.claude/skills` directory outside the run's clone (inside the clone it is the work product, reviewed as a patch; paths are resolved first, so a link in the clone to a protected location is still refused). Edit, Write and NotebookEdit are decided by the resolved path; Bash by a documented conservative heuristic (redirections, tee, cp, mv, rm, ln, install, rsync, `sed -i`, `dd of=`, find, tar and so on). The repository's own `skills/` directory in a member's clone and its run directories stay writable. Read-only verbs (`list`, `show`, `check`, `effective`, `search`, `render`) are unchanged. A barrier, not proof; code that writes a file itself (`python -c`) is not covered.
- The guard fails closed: an unexpected exception inside it is exit 2 with the reason on stderr, not a silent pass. `agents/member.md` sets `onFailure: "block"` and a `timeout` on the hook, so a hook that cannot start, crashes, times out or exits other than 0 or 2 blocks the call (needs Claude Code 2.1.295 or later; an older one runs the call, per the hooks documentation). Frontmatter hooks of a project-level agent file run only once the workspace is trusted.
- `QARGI_NESTED` no longer stands in for the plan token of `skill|tool new|import|seal|remove|link|unlink|enable|disable` and `packs apply`; `import`, `seal` and `packs apply` always need `--plan`, and an empty expected token is an error. Nothing nested them (`discover install` already cleared it, provisioning only renders). `--approved` remains recorded text: proof that a person approved is still the owner's chat approval.

### Removed
- The four ability skills `qargi-build`, `qargi-write`, `qargi-review` and `qargi-test` are gone: nothing loaded them. A member
  follows the role text that comes with the task block (`roles/<role>/ROLE.md`), and `qargi help roles`, `qargi help agent`
  and the manual page no longer name them. `install.sh --user` removes the leftover links to them.

### Fixed
- `qargi canon audit` now attributes a session of a cloud base (`<project>-worker`, `<project>-reviewer`) to the role recorded in the local
  session tracker, so its cross-role writes are reported; a session it cannot attribute is counted once in a NOTE line, not guessed.
- `qargi cloud show|check|login|unset` now refuse `--profile` and `--workspace-id` (only `set` takes them) instead of ignoring them;
  `qargi agent for --surface` completes `local` and `cloud`; the test that keeps the help in step with the scripts now also covers
  `lib/provider.sh`.
- Read-only cloud roles now have the `write` built-in tool off as well as `edit` (a reviewer could still create files through
  `write`); an unknown class now counts as read-only instead of write, and `worker` and `reviewer` are reserved role names.
- `qargi provision apply` no longer fails on the second and later roles of a project: an empty package list became `[""]`, which the shared environment update rejected, before the stores were attached and the instance registered.
- `qargi memory split|merge|copy`: a note whose own `Sources:` line is exactly `origin not recorded (qargi memory)` (written by an earlier copy or by hand) is no longer mistaken for the line qargi inserts into a note that has none. Undoing a copy or an archive (merging a split's target) now returns both kinds of note byte for byte; which one it was is read from the digest already in the origin segment, so the segment format is unchanged and notes written by earlier versions restore as before.
- The tracker's `stop_reason` was empty for every session: the session object has no such field. `status`, `watch`, `send`, `close` and `track` now read it from the last `session.status_idle` event of an idle session. `watch` can now print `budget_reached`.

### Security
- A review member could lift its own read-only limit: the guard took the ability from `RUN/ability`, a file the member could
  write. The guard now refuses any write to a run's `ability` and `refs.before`, and a member that only reviews names its
  class in the hook command of its definition (under the protected agents directory), which holds on every task whatever the
  run file says. Run `qargi agent refresh NAME` for existing members to get the new hook; a guard given an unknown class
  refuses every call.
- A member could rewrite the installed tool through the links in `~/.claude/skills` (they resolve into the installed copy,
  which was not a protected location) and a project's `.claude/agents` definitions (which carry the hook that guards a
  member). The guard now protects the installed tool root recorded in `install.json` and `.claude/agents` outside the run's
  clone, as it already did `.claude/skills`. Reading stays allowed.

## [0.1.0] - 2026-10-28

### Added
- Six skills behind one `qargi` command: `/qargi-task` (dispatch and session
  lifecycle), `/qargi-project` (the one-time questionnaire), `/qargi-instances`,
  `/qargi-provision`, `/qargi-memory` and `/qargi-verify`. `install.sh` installs them at
  user level (skills, command, manual page, completion) or per project (skills,
  hidden from git through `.git/info/exclude`), as symlinks or copies.
- Named instances, local or cloud (a
  Managed Agents deployment), registered outside every repository with model and
  effort chosen at `init`. Cloud verbs need `--asked`, the user's request naming
  the cloud instance; sessions are tracked, watched by a bounded poller,
  collected into a fresh directory and archived, never deleted. A session budget
  can only be set at creation, so the spend ceiling lives on the deployment
  (`instances budget` changes it).
- The agent contract (one task, own clone, patches back, never push, no backlog)
  and per-repository profiles for gates and rules, kept under the user's config
  directory and inlined into the task block, so nothing qargi related is
  added to a project's committed files.
- Project initialisation (`project template|init|show|list|validate|set`): the
  preliminary questions asked once per project (repository, long-lived branches,
  roles, per-role base branch, push policy, model, effort, packages, Anthropic
  skills, budget, stores), validated and stored. Never push is the default for
  every role; a role that pushes is an explicit answer with a branch pattern that
  cannot match a long-lived branch and, for the agent itself, a credential.
- Provisioning with `ant apply` (`provision plan|apply|add-reference`): plan
  first, create only with the user's go-ahead; model, effort, packages, skills,
  budget and stores come from the stored answers.
- A naming convention: `<project>-<role>-<component>` for agent, environment and
  deployment (roles `build`, `review`, `write`, `test`), project-level
  `<project>-memory` and `<project>-reference` stores that are attached rather than
  duplicated, and sessions named `<instance>-<task-slug>`. `instances normalize`
  renames to match and `instances show` reports deviations.
- The canon (`canon/CANON.md`, `canon/layout.json`, version 1, still a draft): the
  standard layout of the two memory stores. Both hold a `/CANON.md` marker, a README,
  `shared/` for every role and `roles/<role>/` with an `INDEX.md` per role; folders
  are named for their scope, with no numbered prefixes. Agents load the README,
  `shared/INDEX.md` and their own role's index, never another role's folder.
- `qargi canon check|plan|apply|import|seed-role|promote|audit`: the reconciler
  brings a store to the current version without losing content (renames keep
  identity and history, conflicts go to `/_conflicts/`, the marker is written last,
  re-runs resume; the legacy layouts and earlier drafts are recognised), imports a
  foreign store such as the old documentation store into a role folder with
  relevant names, writes a role's skeleton, moves a file to `shared/`, and reports
  cross-role writes from the memory version history. `tests/canon_sim.py` proves a
  migration is idempotent and conformant.
- Provisioning creates the project's stores in the canon layout and seeds each
  enabled role's skeleton (`provision/role-seeds/<role>/`); the cloud agent prompt
  names the agent's role and the folders it may load.
- A generic `write` role skeleton (`provision/role-seeds/write/`): the write ability (accuracy first, profile-defined checks and formats, conflict resolution, history logging), reference files for rules, workflow with the definition of done, per-release sync and review, writing conventions, styling, facts and preferences, and memory files for history and open items, distilled from a working documentation methodology. A role's ability skill is appended to its cloud agent's prompt; `tests/role_seed_sim.py ROLE` proves a role seed conforms to the canon.
- Cross-role content of a project's reference store lives in `shared/` (rules every role follows, the approved example values, architecture, source map, checked facts); a role's folder holds only that role's own.
- Approvals bind to the plan: plans print a token, the matching apply needs `--plan TOKEN` and refuses if the plan changed; every gated verb is appended to an audit log. Sessions without a spend budget are refused.
- Local dispatch has a technical barrier (`qargi local prepare|verify`): a clone of a remote-less bare copy, a credential-less git wrapper, and a comparison of every ref of the real repository and its remote before and after.
- The push policies `coordinator` and `agent` are designed but not built; the project validator refuses them instead of accepting an answer nothing honours. The unused `vault_ids`, `profile` and credential answers were removed.
- Gates have one source of truth, the repository profile; the reference store explains them.
- Canon version 2: both stores use one note format (`Kind`, `Applies to`, `Sources`, and `Check`/`Verified` for the runnable kinds), one index form (`| Path | Purpose | Load |`), a kind vocabulary per store, freshness, size and hygiene rules; `canon check` verifies all of it and `memory lint` is the same check. A version 1 store migrates by adding what a note lacks and never editing a body; imports get the header too; both stores carry a `_template.md`. Reconciler fixes: interrupted migrations resume, maintenance creates missing role indexes, an unrecognised layout is an error. `tests/run.sh` runs the whole suite.
- Private repositories: an optional `repo.credential_file` in the project answers (a token file only you can read, outside every repository). `qargi credential check` proves the token reads and warns if it can also push; a cloud session is created with the repository mounted when a credential is set; `local prepare --repo-url --credential-file` clones a private repository. The token goes to `ant` on stdin or to git through an askpass helper and is in no argument, tracker, audit log or repository; `tests/test_cred.sh` proves it with a fake `ant`.
- The secret rule flags an assignment of a long mixed value, not prose about tokens; the `/home/user/` placeholder is allowed.
- Skills and tools (`/qargi-packs`, `qargi skill|tool ...`): one library with globally unique names, attached by links at four scopes (user, user-role, project, project-role) and opted out per role with `packs_off`. A skill is a directory with `SKILL.md`; a tool is an MCP server with an explicit allowlist and a permission policy per tool (write-like tools cannot run unattended unless marked on purpose). Import takes a local path or a pinned git URL and shows a review (files, scripts, URLs, secret findings) that must be approved with the plan token; any later change is drift and fails `check` and provisioning until `seal`ed. Provisioning attaches a role's packs, and `packs apply INSTANCE` updates an existing cloud agent behind a plan token. `tests/test_packs.sh` covers it offline.
- Commit rules: agents commit change-specific units (a change with its tests, docs and changelog entry), never squash or rewrite, and advise in the manifest and report how the work should be committed (`commit_advice`); the coordinator reviews every patch and applies the commits separately, never squashed, checking that each one builds.
- `qargi instances refresh-prompt NAME`: rebuilds a cloud agent's system prompt from the current preamble, contract and role addendum (shared with provisioning), prints what changes, and applies behind a plan token, so an agent can always be brought back in line after the contract changes.
- Patches travel with their context: agents commit as they go, put the reasoning in each commit message, and return one numbered patch per commit plus `series.md` and `patch_groups` in the manifest (related commits grouped under the change they implement), never one combined patch. `qargi review check RUN_DIR` refuses a monolithic patch, a commit without a message body and a manifest that does not match the patches, and notes commits made in one batch. `tests/test_review.sh` covers it.
- `qargi review check` accepts a review run that returns a report instead of patches: a non-empty `report.md` with a Findings section passes, an empty run or a report without findings is refused. `tests/test_review.sh` covers it.
- Baseline seeds for every role (`provision/role-seeds/<role>/`). `build` gets real generic guidance (rules, workflow and definition of done by kind of change, gates, conventions for code, tests, user-visible changes and commits, a self-review checklist); `review` and `test` are new, each with its ability (a review returns a report and never edits the project; a test must be seen failing for the right reason, run three times, and never skipped or weakened), reference files, and a memory note (recurring findings, known flaky tests). Every file keeps a marked "Project specifics" slot for what only the repository can say. `tests/role_seed_sim.py` runs for all four roles in the suite.
- The manifest has an `artifacts[]` key for deliverables that are not patches. The review ability states that a review has no patches (`commits: []`, the report as an artifact, a scratch CLONE) and the test ability says where its evidence lives (`fail-first`, `pass` and `stability-N` entries in `gates[]`, ten runs as the floor). The cloud preamble no longer repeats the stores' own load rules.
- Seeds are leaner and have one home per fact: gates, source map and test conventions are `shared/` seeds (`canon seed-role --role shared`, run first by provisioning); a role's rules are not repeated from the contract; placeholder-only files are no longer shipped (the skill lists what to author); the per-file source line and the store-maintenance boilerplate are gone from indexes; the review checklist gains design and readability, the test conventions the test pyramid and assertion messages, the dev conventions secure-coding habits. A project statement replaces the baseline bullet it covers.
- Canon token rules: a note over 10000 characters warns (an agent loads a note whole), an index over 2500 characters warns, what a role loads before it knows its task (README, indexes, notes marked `always`) is at most 8000 characters per store, and an index Load cell must be `always` or a task, never "when unsure", "if needed" or "working on <project>". `canon check` reports each.
- The README seeds are about 40% smaller (the layout diagram the indexes already cover is gone), so a role's up-front load fits the budget with room for its rules.
- The project is named qargi: the command is `qargi`, the skills are `qargi-task`, `qargi-project`, `qargi-instances`, `qargi-provision`, `qargi-memory`, `qargi-packs`, `qargi-verify` and `qargi-team`, the ability skills `qargi-build`, `qargi-write`, `qargi-review` and `qargi-test`, the environment variables are `QARGI_*`, and the configuration, state and data directories are named `qargi`.
- Resource names follow `<project>-<component>[-<role>]`: the agent `<project>-<role>`, `<project>-deployment-<role>`, the project-wide `<project>-environment` (shared by the roles, holding the packages of all enabled roles), and the existing `<project>-memory` and `<project>-reference`. Provisioning, `instances normalize` and `show` use the new names; an instance is still `<project>-<role>` and a session `<instance>-<task-slug>`.
- The reconciler keeps the README's list of roles in step with the project's roles when one is added.
- Teams (opt-in, `/qargi-team`): a `lead` and named `teams` in the project answers; a lead role of its own (`PROJECT-lead`, a platform coordinator whose members are the role agents, pinned to their versions, with the team definitions in its prompt); `qargi team brief|check|contract`; a team's outputs are role-prefixed and `collect` splits them per member; the build member owns what ships with the code (manual page, help, completion, `docs/`), the write member owns the operational docs on its branch. The lead can be this Claude Code session, a cloud lead, or a session started in the console. `qargi hook session-start` loads the lead's READMEs and indexes at the start of a Claude Code session inside a registered project; `qargi memory get` reads a note. The shared environment is reused when a second role is provisioned. `tests/test_team.sh` covers it offline.
- Push grant for the lead (`lead.push` in the project answers; default none). Only the lead ever pushes, members never do. `local`: the Claude Code session leading may push `agent/*` branches and open pull requests without asking each time (the autoload says so, or says to ask before every push); `cloud: branches`: a cloud or console lead may do the same with a fine-grained token file kept outside every repository and different from the read-only repository token. Merges and releases are `ask` (the person confirms each one) or `never`; there is no automatic merge or release, and a branch pattern outside `agent/` is refused. The lead's prompt carries a Push section that grants exactly this, or says it never pushes.
- `review check --allow-empty`: a team member that returns no commits (blocked, or nothing to change) passes `team check`; a single run that claims DONE with no commits still fails.
- `qargi credential setup lead-push PROJECT`: one command for the cloud lead's write token. It reads a fine-grained token from a file or stdin (never an argument), checks against GitHub that it reaches only this repository and cannot administer it (classic tokens are refused), stores it mode 600 outside every repository, creates a vault of its own with a bearer credential for the GitHub tool, attaches the vault to the lead's deployment and records the grant in the project answers. It prints a plan first and applies behind a plan token. The lead then gets a fixed GitHub allowlist (`packs render`, `packs apply`): read tools and branch, file and pull-request writes unattended, `merge_pull_request` asked of the person, no delete tools and no release tool. `tests/test_leadcred.sh` covers it offline.
- `credential setup lead-push` tests the token itself: a push dry-run over https for Contents write, and a branch-protection read that only a token with Administration can make. The repository answer shows your own role, so it is no longer used to judge the token.
- `credential setup lead-push` no longer counts the repositories a token can see (a fine-grained token reads every public repository). It probes each repository the account can see with a push dry-run and refuses a token that can write anywhere but the project repository, unless `--allow-more-repos`.
- `qargi lead grant|status|revoke PROJECT`: the cloud lead's push grant as one guided flow. `grant` explains how to create the fine-grained token, reads it hidden, and walks through three steps (token and vault, the GitHub tool, the Push rules), printing each plan and asking at the terminal; your answer is the recorded approval, and it never runs without a terminal. Steps already in place are skipped, so running it again is safe. `status` shows what is in place and what is missing, including members pinned at old versions; `revoke` removes the tool and the Push rules, archives the credential, detaches the vault and deletes the token file, and reminds you to revoke the token on GitHub. `tests/test_lead.sh` covers it offline. `collect` also accepts a lead-only run.
- Help, a manual page and bash completion, all generated from one description of the commands (`lib/commands.py`): `qargi help [COMMAND [VERB]|TOPIC]`, `--help` on every command and verb, topics (`concepts`, `approvals`, `naming`, `memory`, `push`, `files`), `man/qargi.1` (`qargi help --man`), and `completions/qargi.bash`, which also completes your projects, instances, a project's teams, sessions and packs. `install.sh --user` installs the page and the completion and `--uninstall` removes them. Inside a project's repository a missing PROJECT is filled in from the current directory (`QARGI_PROJECT` overrides, an argument you give wins) and a role stands for the instance (`dev` for `PROJECT-dev`); outside one, a missing project says which projects exist. `tests/test_help.py` checks the description against the scripts, the page against the generator, and the completion and the inference.
- Tab completion for zsh (`completions/_qargi`) and fish (`completions/qargi.fish`) beside bash, from the same description, with a one-line description for each command, verb and option in the menu. `install.sh --user` installs and `--uninstall` removes them. `tests/test_help.py` runs both shells when they are installed.
- Tab completion is comprehensive: values come from your own state, each with a description in zsh and fish, and are narrowed to what the verb can act on (sessions by state, cloud instances for cloud verbs, projects with teams for `lead` and `team`, a project's roles, skills or tools by command). New: memory store, deployment and model ids; the branches of the project's repository for `--base`; the keys of a project's answers for `project set` and the values each takes; spend ceilings and wait times; the verbs of a command after `help COMMAND`; `--option=value` in all three shells (bash puts the word back together); options already given are not offered again, and `--help` is offered with them. A test fails when a new kind of value in `lib/commands.py` has no completer.
- `qargi export` and `qargi import`: save and restore selected components (config, definitions, memories, state, credentials) as one archive, optionally encrypted with a password (gpg, AES-256; never in argv). Import verifies the archive (names, entry kinds, checksums, format), asks which parts and projects and how to treat what exists (merge, overwrite, replace), prints the plan, writes nothing before you confirm, backs up what it replaces, and treats the audit log as append-only. Credentials only in an encrypted archive; definitions are restored as files; memory notes are written to the project's stores.
- `qargi discover sources|search|recommend|show|install`: tool discovery for the roles of a project. Searches a reviewed catalog and your library, and with `--online` the official MCP registry and Anthropic's skills; recommends by role and by the stack seen in the repository; installs through the existing pack gates (review, your approval of the exact content, scope choice, link, optional apply to cloud agents), or edits the role's apt list or the local agent's tools line after a confirmation. Entry IDs tab-complete.
- `qargi watch SID [MAX_SECONDS] [--warn PCT]` ends early with `budget_tight <cost>/<ceiling>` when a cloud session's cost reaches PCT percent of its ceiling (default 85, 0 turns it off), so the coordinator can offer the user a raise (`qargi instances budget NAME CENTS --session SID`) before the session stops at `budget_reached`.
- A `PreToolUse` guard (`qargi __guard`) on the members' Bash, Edit, Write and NotebookEdit calls refuses `git push`, `gh`, `ssh`, `scp`, `sftp` and changes to a git remote; `qargi discover install` edits the tools line of the members that serve a role (or of all). The agent contract now separates how to wait for a long command locally (`run_in_background`) and in the cloud (detach and poll) and asks for a `gitleaks` pass before the report, which the coordinator repeats.
- Cloud agents get a per-role list of built-in tools to switch off (`roles.<role>.tools_off` in the project answers; default `web_search` and `web_fetch` for every role, plus `edit` for review and the lead), rendered by provisioning as toolset `configs` and carried to existing agents by `qargi packs apply`, whose plan lists them. The shared environment can also hold `roles.<role>.pip` and `roles.<role>.go` (merged like `apt`), and `--networking limited` now renders `allow_package_managers` and `allow_mcp_servers` so the platform accepts it. The built-in GitHub tool for the lead no longer lists four pull-request read tools the server does not expose, and states `write_ok` for its unattended writes.
- Roles are named by their activity: the abilities `build`, `write`, `review` and `test`, plus `lead`. Each ability is defined by a skill (`qargi-build`, `qargi-write`, `qargi-review`, `qargi-test`), which a member loads when the task block names it (`ABILITY: build — load skill qargi-build`) and a cloud agent of that role carries in its prompt. The memory folders are `roles/<role>/`, the project answers `roles.<role>`, the instances `<project>-<role>`, a team's output prefixes `<role>--`, and `team brief` takes `--write-done` and `--review-done`. `qargi help roles` has the table.
- Members: the local workers are agents you name. qargi ships one member definition (`agents/member.md`, with `Skill` among its tools) and installs none; `qargi agent add NAME [--abilities LIST] [--model M] [--effort E] [--project P]` renders it (all four abilities by default; a name that exists, is not kebab-case or is a built-in Claude Code agent type is refused), `qargi agent for ABILITY` prints the member dispatch spawns, and `list`, `rename` and `remove` manage them. `/qargi-project` asks for the members once.
- Review is read-only as a rule: `qargi local prepare --ability A` records the task's ability in the run directory, and under review the guard refuses an edit outside the run's output directory and a Bash command that writes into the clone (a redirection, a file command, a git command that changes the work tree or history).
- The coordinator's procedure for verifying and applying returned patches is the skill `qargi-verify`.
- `qargi migrate roles [--member-names build=NAME,...] [--apply --plan TOKEN --asked "..."]`: existing installations made with the earlier names (roles `dev` and `docs`, the agents `qargi-dev`, `qargi-docs`, `qargi-review`, `qargi-test`, cloud agents `<project>-agent-<role>`) move to the current ones: registry, tracker, answers, pack links and saved definitions; the notes of both memory stores; the cloud agents and deployments (renamed by update, nothing archived) and their prompts; the old agent symlinks, replaced by members. It prints a plan with every cloud call and a token, applies exactly that plan, stops at the first failure and is re-runnable. `qargi import` maps an archive made with the earlier role names to the current ones.
