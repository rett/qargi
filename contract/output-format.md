# Output files (in OUT)
OUT is the output directory the task block gives. `qargi review check` and `qargi local clean` read OUT; write
nothing of your result anywhere else.

patches/NNNN-*.patch: one patch per commit, in order, from `git format-patch --binary
BASE_SHA..HEAD` (never a single combined patch), series.md (each patch in order: subject, the
change group it belongs to, why, which checks it passed), run.bundle
(git bundle create run.bundle BASE_SHA..agent/<slug>), manifest.json, log.txt
(every command with its exit status, in order). If OUT_PREFIX is given, start the name of every
file you write to OUT with it (build--manifest.json): outputs are collected by base name and the
members of a team share one directory.
manifest.json keys: status (DONE|BLOCKED), blocked_reason, task, commit_advice[] {sha, subject,
why_separate, depends_on[], builds_alone}, patch_groups[] {name, why, commits[]} (related commits
grouped under the one change they implement, so a change is reviewed with its context),
base {branch, sha}, branch, scope[], done {command, exit_code, output_tail},
gates[] {name, command, result pass|fail|not run, exit_code, verdict_line
verbatim}, commits[] {sha, subject}, touched_paths[] {path, reason},
deviations[], noticed_not_acted_on[], artifacts[] {path, kind: report|log|other} (deliverables
that are not patches), usage_impact[] {kind: command|flag|output|config|file, before, after, where}
(required when you change something a user sees or types), on_top_of {run, head_sha} and, per commit,
for_group (when your work builds on another member's series), environment {tool versions, test_user}.

## Two shapes
A role that changes the repository returns patches: everything above.

A read-only role (review) returns a report and no patches: `report.md` and `manifest.json` in OUT, with
`status`, `commits: []` and the report listed in `artifacts[]` (kind `report`). No `patches/`, no `series.md`,
no bundle. A suggested fix goes in the report as a fenced diff, never a patch file.
