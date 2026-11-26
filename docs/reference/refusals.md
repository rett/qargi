# Refusals

Generated from `lib/refusals.json` by `python3 lib/refusal.py page`; edit the catalogue, not this page. A refusal is a rule that
stopped a verb. The catalogue names each rule once, with the reason it exists, so that a lead or a member can read the rule before a
verb refuses it.

## What a refusal prints

On standard error, the contract line first, then the human lines:

```
qargi-refusal/1 {"code":"plan-stale","exit":1,"verb":"release push","project":"acme","role":null,"epoch":null,"state":null,"tx":null,"detail":"moved=head"}
qargi: refused [plan-stale] ...
  why: ...
  next: ...
```

`detail` is qargi's own text: the typed fields as `key=value`. A value that a lead chose (a ref, a path or a name) appears in the human
lines only; in `detail` it is a digest of 12 hex digits. A list prints three items and `+N`. The line stays under 4 KiB. `notice`
prints `qargi: note [code] ...` and a `next:` line, with no contract line, and exits 0: the verb did its work and names a rule that
will apply later.

## What moved: the basis of a plan

`plan_token --basis "LABELS" --verb VERB --target PROJECT:OBJECT` in a plan hashes its input as `plan_token` always has (a token is the same with or without the basis) and
keeps the plan in `STATE/plans/TOKEN.json` (mode 600, seven days) as the record `qargi.plan/0`, which `qargi plan show TOKEN` prints. LABELS are words separated by spaces,
each `label` or `label:kind` (`ref`, `path`, `name`, `sha`, `label` or `count`; a label with no kind is `name`): line N of the plan is
labelled with word N, and the lines after the last word belong to it. When `--plan` names a token that is no longer the plan's,
`plan-stale` says which labels differ between the plan that was shown and the plan now (`moved`), or `unrecorded` when either plan was
planned without a basis. Nothing is kept in a dry run.

## Statuses

- `live`: a verb of this build raises the code (or, for the `verify.environment` codes and the guard's, prints it at the sites the catalogue lists).
- `planned`: written down so that it is reviewed early; no verb raises it yet.
- `withdrawn`: no longer raised; the code is never reused.

No code of this catalogue starts with `pack-`: the lint refuses it, because the codes a provider pack prints are `[pack-...]` and stay apart from qargi's own.

The codes of the classes `seat-gate` and `seat-door` are the lists of R52 and R70 of the [lead seat contract](lead-seat.md); the lint
compares them with that page.

## Codes

| Code | Class | Exit | Status | Rule |
| --- | --- | --- | --- | --- |
| [`approval-missing`](#approval-missing) | approval | 1 | planned | An apply that the owner must approve is given the owner's own words with --approved |
| [`approval-inside-run`](#approval-inside-run) | approval | 1 | planned | A member run, or a verb called inside an approved apply, never gives --approved |
| [`cut-not-covering`](#cut-not-covering) | cut | 1 | live | The approval of a release cut covers only the steps its plan listed, while what the cut fixed still holds |
| [`cut-lead-changed`](#cut-lead-changed) | cut | 1 | live | A release cut belongs to the lead that approved it |
| [`cut-branch-moved`](#cut-branch-moved) | cut | 1 | live | A release cut stands only while its branch is where the cut left it |
| [`cut-fix-outside`](#cut-fix-outside) | cut | 1 | live | A fix recorded on a release branch goes on under the cut's approval only when it stays inside the paths the cut named |
| [`feature-runs-open`](#feature-runs-open) | feature | 1 | live | A feature is finished when none of its runs is open |
| [`ro-write-outside`](#ro-write-outside) | guard | 2 | live | A read-only run writes only OUT and TMP |
| [`ro-second-tree`](#ro-second-tree) | guard | 2 | live | A read-only run makes no second tree of the clone inside the clone |
| [`ro-env-restricted`](#ro-env-restricted) | guard | 2 | live | A read-only run does not assign the variables that decide what runs |
| [`member-push`](#member-push) | guard | 2 | live | A member never pushes |
| [`member-lead-verb`](#member-lead-verb) | guard | 2 | live | A member does not run the lead's verbs |
| [`member-run-record`](#member-run-record) | guard | 2 | live | A member does not write the lead's run records |
| [`methodology-no-flow`](#methodology-no-flow) | methodology | 2 | live | A verb of the git-flow shape runs only on a project whose methodology has that flow |
| [`plan-missing`](#plan-missing) | plan | 1 | live | A token covers the plan the person saw |
| [`plan-stale`](#plan-stale) | plan | 1 | live | A token covers the plan the person saw |
| [`plan-unknown`](#plan-unknown) | plan | 1 | live | qargi plan show answers for a plan that this build kept a record of |
| [`plan-expired`](#plan-expired) | plan | 1 | live | A stored plan is shown for the seven days it is kept |
| [`plan-record-invalid`](#plan-record-invalid) | plan | 1 | live | A stored plan is shown only when its file is whole |
| [`project-remove-unknown`](#project-remove-unknown) | project-remove | 2 | live | qargi project remove names a project with stored answers |
| [`project-remove-feature`](#project-remove-feature) | project-remove | 2 | live | A project with an open feature is not removed |
| [`project-remove-run`](#project-remove-run) | project-remove | 2 | live | A project with an open run is not removed |
| [`project-remove-lease`](#project-remove-lease) | project-remove | 2 | live | A project with a live marshal lease is not removed |
| [`project-remove-release`](#project-remove-release) | project-remove | 2 | live | A project with an open release cut is not removed |
| [`project-remove-linked`](#project-remove-linked) | project-remove | 2 | live | A project whose work tree is linked is not removed |
| [`project-remove-cloud`](#project-remove-cloud) | project-remove | 2 | live | A project bound to a cloud workspace is not removed |
| [`project-remove-instances`](#project-remove-instances) | project-remove | 2 | live | A project with registered instances is not removed |
| [`project-remove-unreadable`](#project-remove-unreadable) | project-remove | 2 | live | A project is not removed while something that could hold it back cannot be read |
| [`runtime-unusable`](#runtime-unusable) | project-rule | 1 | live | An extra runtime is sealed, local, started by a command, and not the project's own |
| [`runtime-reads-unacknowledged`](#runtime-reads-unacknowledged) | project-rule | 1 | live | The owner's approval of a runtime that does not confine reads says so |
| [`runtime-option-unacknowledged`](#runtime-option-unacknowledged) | project-rule | 1 | live | The owner's approval of a run option says what it opens |
| [`runtime-option-class`](#runtime-option-class) | project-rule | 1 | live | A run option is for the run classes its definition names |
| [`runtime-barrier-missing`](#runtime-barrier-missing) | project-rule | 1 | live | A read-only role needs the barrier of its own runtime; the acceptance of the project's own runtime does not count |
| [`runtime-not-enabled`](#runtime-not-enabled) | project-rule | 1 | live | A run uses a runtime the project enabled |
| [`runtime-profile-model`](#runtime-profile-model) | project-rule | 1 | live | A profile's model belongs to the runtime the profile is resolved in |
| [`runtime-hidden-path`](#runtime-hidden-path) | project-rule | 1 | planned | A member sees its clone, contract and OUT |
| [`release-notes-empty`](#release-notes-empty) | release | 1 | live | A release has notes |
| [`release-fragments-unfolded`](#release-fragments-unfolded) | release | 1 | live | A release branch holds no unfolded changelog fragment when it is pushed or finished |
| [`seated-project`](#seated-project) | seat-door | 1 | planned | A marshal claim, take or release is not run on a seated project (R27) |
| [`assignment-invalid`](#assignment-invalid) | seat-door | 1 | planned | An assignment is well formed and names nothing reserved or unsafe (R4, R5, R18, R19, R28, R89) |
| [`transfer-open`](#transfer-open) | seat-door | 1 | planned | A new assignment waits while a transfer is open (R43) |
| [`abort-after-fence`](#abort-after-fence) | seat-door | 1 | planned | A transfer cannot be aborted once the old lead is fenced (R42) |
| [`fence-required`](#fence-required) | seat-door | 1 | planned | A transfer goes past the fence only with an accepted fence (R36) |
| [`fence-unproven`](#fence-unproven) | seat-door | 1 | planned | A fence proves the end of this epoch (R20, R29) |
| [`readback-mismatch`](#readback-mismatch) | seat-door | 1 | planned | The read-back matches what the project says (R49) |
| [`readback-exhausted`](#readback-exhausted) | seat-door | 1 | planned | A transfer allows three failed read-backs (R39) |
| [`note-digest-mismatch`](#note-digest-mismatch) | seat-door | 1 | planned | The handoff note is the one recorded (R41, R47) |
| [`note-invalid`](#note-invalid) | seat-door | 1 | planned | The handoff note verifies and belongs to this transfer (R47) |
| [`seat-changed`](#seat-changed) | seat-door | 1 | planned | A seat write sees the seat it read (R12) |
| [`refs-backend-active`](#refs-backend-active) | seat-door | 1 | planned | The shared refs backend and a seat exclude each other (R74) |
| [`approval-refused`](#approval-refused) | seat-door | 1 | planned | A verb given --approved on a seated project is refused unless qargi host runs it (R76) |
| [`authority-store-unsafe`](#authority-store-unsafe) | seat-door | 1 | planned | The authority store and the roots are safe paths (R8, R88, R89) |
| [`content-too-large`](#content-too-large) | seat-door | 1 | planned | A record is within its limit (R18) |
| [`content-invalid`](#content-invalid) | seat-door | 1 | planned | A record other than an assignment keeps to its shape (R18, R22, R32) |
| [`symlink-refused`](#symlink-refused) | seat-door | 1 | planned | No path of the seat's stores is a symbolic link (R88) |
| [`caretaker-not-vacant`](#caretaker-not-vacant) | seat-door | 1 | planned | A caretaker order waits for a vacant seat (R75) |
| [`host-in-sandbox`](#host-in-sandbox) | seat-door | 1 | planned | qargi host runs only outside every sandbox, with a passed proof (R33, R103) |
| [`member-sandbox-off`](#member-sandbox-off) | seat-door | 1 | planned | A member is dispatched only into a sandbox (dispatch) |
| [`seat-record-invalid`](#seat-record-invalid) | seat-gate | 77 | planned | The answers file of a seated project is readable and its marker valid (R54) |
| [`seat-record-missing`](#seat-record-missing) | seat-gate | 77 | planned | A seated project has its assignment file and its projection (R55) |
| [`records-disagree`](#records-disagree) | seat-gate | 77 | planned | The assignment file and the projection agree on the holder (R56) |
| [`previous-epoch`](#previous-epoch) | seat-gate | 77 | planned | The assignment file is not of an earlier epoch than the projection (R57) |
| [`projection-stale`](#projection-stale) | seat-gate | 77 | planned | The projection is as new as the assignment file (R58) |
| [`transfer-in-progress`](#transfer-in-progress) | seat-gate | 77 | planned | No lead verb changes the project while a transfer is open (R60) |
| [`readback-pending`](#readback-pending) | seat-gate | 77 | planned | No lead verb changes the project while a read-back is pending (R61) |
| [`seat-vacant`](#seat-vacant) | seat-gate | 77 | planned | A vacant seat is held by nobody who may write (R62) |
| [`not-assigned`](#not-assigned) | seat-gate | 77 | planned | A verb of class owner is not run by an assigned lead (R59) |
| [`caretaker-denied`](#caretaker-denied) | seat-gate | 77 | planned | A caretaker runs no lead verb that writes (R63) |
| [`gate-error`](#gate-error) | seat-gate | 77 | planned | A gate that cannot answer refuses (R67) |
| [`runtime-drift`](#runtime-drift) | state | 1 | live | A run starts on the runtime it was prepared for |
| [`verify-env-invalid`](#verify-env-invalid) | verify-environment | 1 | live | The verify.environment answer is a valid declaration |
| [`verify-env-change-unapproved`](#verify-env-change-unapproved) | verify-environment | 1 | live | A change of verify.environment that loosens it takes the owner's approval, and the suite runs only under the declaration qargi last accepted |
| [`verify-env-cpu-no-systemd-run`](#verify-env-cpu-no-systemd-run) | verify-environment | 1 | live | With the cpu part on, the suite runs in a scope made by systemd-run |
| [`verify-env-cpu-systemd-too-old`](#verify-env-cpu-systemd-too-old) | verify-environment | 1 | live | With the cpu part on, systemd-run is systemd 254 or newer |
| [`verify-env-cpu-no-user-manager`](#verify-env-cpu-no-user-manager) | verify-environment | 1 | live | With the cpu part on, the scope is made and the launcher reports |
| [`verify-env-cpu-readback`](#verify-env-cpu-readback) | verify-environment | 1 | live | With the cpu part on, the launcher reads back that it is alone in a new scope below qargi-verify.slice with the declared cpu.max |
| [`verify-env-signals`](#verify-env-signals) | verify-environment | 1 | live | The suite starts with default signal dispositions and an empty mask |
| [`verify-env-fds`](#verify-env-fds) | verify-environment | 1 | live | The suite starts with only the descriptors the declaration allows |
| [`verify-env-tty`](#verify-env-tty) | verify-environment | 1 | live | The suite runs in a session of its own with no terminal |
| [`verify-env-no-log`](#verify-env-no-log) | verify-environment | 1 | live | With verify.environment on, the suite's output goes to a log and never to a terminal, and the launcher's reports have a directory |
| [`verify-env-waive-unapproved`](#verify-env-waive-unapproved) | verify-environment | 1 | live | A waiver of a part stands on the plan token of a refusal of exactly those parts at this head and on the owner's words |
| [`verify-env-waive-unknown`](#verify-env-waive-unknown) | verify-environment | 1 | live | --waive-environment names parts of verify.environment that are on and can fail |
| [`verify-env-waive-used`](#verify-env-waive-used) | verify-environment | 1 | live | A waiver token is good for one run at its head |
| [`verify-env-waiver-dir`](#verify-env-waiver-dir) | verify-environment | 1 | live | A waiver is claimed in a directory of the state, with a count of the tokens used at the head, before the run starts |

## Class approval

### approval-missing

- Rule: An apply that the owner must approve is given the owner's own words with --approved.
- Why: the owner's words are the approval: a verb that needs them cannot be told they were given.
- Exit 1, planned.
- Fields: `verb` (verb), `token` (token).
- Message: `{verb} needs --approved with the owner's own words`
- Next, for a lead: show the plan to the owner, wait for the answer, then apply with --plan {token} --approved and the owner's words

### approval-inside-run

- Rule: A member run, or a verb called inside an approved apply, never gives --approved.
- Why: an approval is the owner's, given in the lead's session for the plan the owner saw; qargi can detect a run or a nested call, not relayed words.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} was given --approved inside a member run or a nested call`
- Next, for a lead: report the refusal and the plan token in your report; the lead applies the plan after the owner approves it

## Class cut

### cut-not-covering

- Rule: The approval of a release cut covers only the steps its plan listed, while what the cut fixed still holds.
- Why: a cut approves one plan; a step that no longer matches it is a different plan.
- Exit 1, live.
- Fields: `verb` (verb), `step` (label).
- Message: `the approval of the release cut does not cover the step {step} of {verb}`
- Next, for a lead: run {verb} without the cut's token, show its own plan, and apply that with its token and the owner's words

### cut-lead-changed

- Rule: A release cut belongs to the lead that approved it.
- Why: the approval was given to that lead's plan.
- Exit 1, live.
- Fields: `verb` (verb).
- Message: `the release cut of {verb} was approved by another lead, or by a lead that cannot be told`
- Next, for a lead: plan {verb} again with its own token and take the owner's approval for it

### cut-branch-moved

- Rule: A release cut stands only while its branch is where the cut left it.
- Why: the owner approved the plan for that head.
- Exit 1, live.
- Fields: `verb` (verb), `ref` (ref).
- Message: `{ref} is not where the release cut left it`
- Next, for a lead: journal commits made on the branch with qargi release fix VER --record (push goes on under the cut while they stay inside the paths its plan named), or run {verb} with its own plan: shown, and approved anew

### cut-fix-outside

- Rule: A fix recorded on a release branch goes on under the cut's approval only when it stays inside the paths the cut named.
- Why: the cut approved a release, not a change of the code.
- Exit 1, live.
- Fields: `verb` (verb), `commits` (sha-list).
- Message: `the commits {commits} leave the paths the cut covers`
- Next, for a lead: run qargi release push VER without the cut's token: its own plan lists every commit and takes the owner's approval

## Class feature

### feature-runs-open

- Rule: A feature is finished when none of its runs is open.
- Why: an open run holds patches that are not taken in.
- Exit 1, live.
- Fields: `verb` (verb), `count` (count), `runs` (name-list).
- Message: `{count} run(s) of this feature are still open: {runs}`
- Next, for a lead: take each run in (qargi local verify, then merge it), or close it: qargi local clean RUN once its work is merged (--discard drops it on purpose), qargi local close RUN --applied-by-am when its patches were applied by hand; then run {verb} again

## Class guard

### ro-write-outside

- Rule: A read-only run writes only OUT and TMP.
- Why: a review that changes the code it reviews is no longer a review.
- Exit 2, live.
- Fields: none.
- Message: `a read-only run may not write outside OUT and TMP`
- Next, for a lead: write the report in OUT; to test patches make a copy in TMP and work there
- Printed at 4 sites; `qargi help guard` says what a member's guard refuses.

### ro-second-tree

- Rule: A read-only run makes no second tree of the clone inside the clone.
- Why: a clone or an init made inside the clone, or a worktree added from it, changes the clone a review is held to; the tree is made in TMP.
- Exit 2, live.
- Fields: none.
- Message: `a read-only run may not make a second tree (clone, init or worktree) inside the clone`
- Next, for a lead: clone into TMP with git -C TMP clone CLONE x, then work in TMP/x
- Printed at 1 site; `qargi help guard` says what a member's guard refuses.

### ro-env-restricted

- Rule: A read-only run does not assign the variables that decide what runs.
- Why: PATH, HOME, TMPDIR and the git and loader variables decide which program a command is.
- Exit 2, live.
- Fields: none.
- Message: `a read-only run may not assign this variable`
- Next, for a lead: pass the path as an argument instead of assigning the variable
- Printed at 1 site; `qargi help guard` says what a member's guard refuses.

### member-push

- Rule: A member never pushes.
- Why: the lead's branches are the lead's; a member hands patches back.
- Exit 2, live.
- Fields: none.
- Message: `a member may not push`
- Next, for a lead: return patches in OUT; the lead takes them in
- Printed at 1 site; `qargi help guard` says what a member's guard refuses.

### member-lead-verb

- Rule: A member does not run the lead's verbs.
- Why: the lead's verbs change the project's records, runs and branches.
- Exit 2, live.
- Fields: none.
- Message: `a member may not run this verb`
- Next, for a lead: report what you need in your task output; the lead, or the owner for a skill, runs the verb
- Printed at 48 sites; `qargi help guard` says what a member's guard refuses.

### member-run-record

- Rule: A member does not write the lead's run records.
- Why: the run directory is the member's to write, and the lead's registry is the lead's.
- Exit 2, live.
- Fields: none.
- Message: `a member may not write this run record`
- Next, for a lead: write your outputs in OUT and report; the lead's registry records the run
- Printed at 4 sites; `qargi help guard` says what a member's guard refuses.

## Class methodology

### methodology-no-flow

- Rule: A verb of the git-flow shape runs only on a project whose methodology has that flow.
- Why: the feature, release and hotfix verbs, and the others that need develop and master, cut and merge branches a plain methodology does not have, so on such a project they would act on branches that are not there; a methodology whose flow cannot be read is not run as git-flow either, because that would be a guess.
- Exit 2, live.
- Fields: `verb` (verb), `methodology` (label).
- Message: `{verb} is refused: the project follows the {methodology} methodology, which has no feature, release or hotfix flow (its flow is plain, or cannot be read: qargi methodology check)`
- Next, for a lead: work goes on a branch cut from the project's one long-lived branch: qargi local prepare, run and verify with --base BRANCH, qargi review check, save and apply, qargi local close and clean, and qargi backlog; the feature, release and hotfix verbs belong to a methodology of the git-flow shape

## Class plan

### plan-missing

- Rule: A token covers the plan the person saw.
- Why: an apply with no token has no plan that anybody was shown.
- Exit 1, live.
- Fields: `verb` (verb), `token` (token), `context` (enum:lead,host).
- Message: `the plan changed or --plan is missing: {verb} was given no --plan`
- Next, for a lead: run {verb} without --plan, show the plan to the user, then apply exactly that with --plan {token}
- Next, in the owner's own session (`host`): plan again with qargi host {verb}, show it, then apply exactly that with --plan {token}: a token from a lead's plan never matches (R77)

### plan-stale

- Rule: A token covers the plan the person saw.
- Why: what the plan hashed changed after it was shown.
- Exit 1, live.
- Fields: `verb` (verb), `moved` (label-list), `token` (token), `context` (enum:lead,host).
- Message: `the plan changed or --plan is missing: the plan of {verb} is no longer the one shown (moved: {moved})`
- Next, for a lead: run {verb} without --plan, show the new plan, then apply exactly that with --plan {token}
- Next, in the owner's own session (`host`): plan again with qargi host {verb}, show the new plan, then apply exactly that with --plan {token}: a token from a lead's plan never matches (R77)

### plan-unknown

- Rule: qargi plan show answers for a plan that this build kept a record of.
- Why: a plan that was never kept, was pruned after seven days, was made before the records had a schema, or belongs to a verb that keeps none has nothing to show, and a guess would put words in front of an approver that nobody hashed.
- Exit 1, live.
- Fields: `given` (name), `context` (enum:lead,host).
- Message: `no stored plan has the token {given}`
- Next, for a lead: plan again with the verb, which keeps its plan, then show it with qargi plan show TOKEN
- Next, in the owner's own session (`host`): plan again with qargi host and the verb, which keeps its plan, then show it with qargi host plan show TOKEN

### plan-expired

- Rule: A stored plan is shown for the seven days it is kept.
- Why: a plan shown long after it was made may no longer say what the verb would do, so show says that it is past its days instead of presenting it as current.
- Exit 1, live.
- Fields: `token` (token), `context` (enum:lead,host).
- Message: `the stored plan {token} is past its seven days`
- Next, for a lead: plan again with the verb: a plan that has not changed has the same token and is kept again for seven days
- Next, in the owner's own session (`host`): plan again with qargi host and the verb: a plan that has not changed has the same token and is kept again for seven days

### plan-record-invalid

- Rule: A stored plan is shown only when its file is whole.
- Why: the file lies in the state of the owner, and a plan that is shown must have the lines that were hashed (the hash binds the lines only, not the verb, the target, the labels or the times, which are checked for their form): a link, a file of the wrong kind or mode, one that cannot be read, damaged JSON, a schema this build does not know or lines that no longer hash to the token are not shown.
- Exit 1, live.
- Fields: `token` (token), `problem` (label), `context` (enum:lead,host).
- Message: `the stored plan {token} cannot be trusted ({problem}) and is not shown`
- Next, for a lead: plan again with the verb, which writes the record anew, and check who changed the plans directory of the state if it happens again
- Next, in the owner's own session (`host`): plan again with qargi host and the verb, which writes the record anew, and check who changed the plans directory of the state if it happens again

## Class project-remove

### project-remove-unknown

- Rule: qargi project remove names a project with stored answers.
- Why: there is nothing to remove for a name that has no answers, and a misspelt name must not look like a removal.
- Exit 2, live.
- Fields: `name` (name).
- Message: `project remove is refused: no project named {name} has stored answers`
- Next, for a lead: see the stored projects with qargi project list

### project-remove-feature

- Rule: A project with an open feature is not removed.
- Why: an open feature is work the project's answers are still needed to finish, verify and merge.
- Exit 2, live.
- Fields: `name` (label), `features` (name-list).
- Message: `project remove is refused: {name} has open feature(s): {features}`
- Next, for a lead: finish each open feature with qargi feature finish FEATURE (qargi feature list shows them), then run project remove again

### project-remove-run

- Rule: A project with an open run is not removed.
- Why: an open run holds patches that are not taken in, and verifying, applying or cleaning it reads the project's answers.
- Exit 2, live.
- Fields: `name` (label), `runs` (path-list).
- Message: `project remove is refused: {name} has open run(s): {runs}`
- Next, for a lead: close each run: qargi local clean RUN once its work is merged (qargi local list shows the runs), then run project remove again

### project-remove-lease

- Rule: A project with a live marshal lease is not removed.
- Why: another session may be leading the feature; removing the project's answers under it would strand that lead.
- Exit 2, live.
- Fields: `name` (label), `features` (name-list).
- Message: `project remove is refused: {name} has a live marshal lease on {features}`
- Next, for a lead: give the lease up with qargi marshal release FEATURE --project NAME (or wait for it to lapse), then run project remove again

### project-remove-release

- Rule: A project with an open release cut is not removed.
- Why: an open cut is an approved release that has not finished; its steps read the project's answers.
- Exit 2, live.
- Fields: `name` (label), `versions` (name-list).
- Message: `project remove is refused: {name} has an open release cut: {versions}`
- Next, for a lead: finish the release with qargi release finish VERSION --project NAME, then run project remove again

### project-remove-linked

- Rule: A project whose work tree is linked is not removed.
- Why: the links in a work tree point into qargi's render, and qargi project unlink needs the project's answers to take them away.
- Exit 2, live.
- Fields: `name` (label), `trees` (path-list).
- Message: `project remove is refused: {name} is linked in {trees}`
- Next, for a lead: run qargi project unlink NAME inside each linked work tree, then run project remove again

### project-remove-cloud

- Rule: A project bound to a cloud workspace is not removed.
- Why: the binding is how every cloud call of the project reaches its workspace; it is removed on purpose, not with the answers.
- Exit 2, live.
- Fields: `name` (label).
- Message: `project remove is refused: {name} is bound to a cloud workspace`
- Next, for a lead: remove the binding with qargi cloud unset NAME, then run project remove again

### project-remove-instances

- Rule: A project with registered instances is not removed.
- Why: an instance is a cloud agent or a local agent file that is named after the project and that dispatch looks up through it.
- Exit 2, live.
- Fields: `name` (label), `instances` (name-list).
- Message: `project remove is refused: {name} has registered instance(s): {instances}`
- Next, for a lead: remove each registry entry with qargi instances remove INSTANCE (qargi instances list shows them), then run project remove again

### project-remove-unreadable

- Rule: A project is not removed while something that could hold it back cannot be read.
- Why: a source that exists and cannot be read may name a feature, run, lease, cut, work tree or instance of the project, so a removal over it would be a guess.
- Exit 2, live.
- Fields: `name` (label), `what` (name-list), `fix` (name-list).
- Message: `project remove is refused: {name} cannot be checked, because it could not be read: {what}`
- Next, for a lead: fix it, one item at a time: {fix}; then run project remove again

## Class project-rule

### runtime-unusable

- Rule: An extra runtime is sealed, local, started by a command, and not the project's own.
- Why: qargi local run starts a member of an extra runtime itself, so it must be a definition qargi has reviewed that it can start.
- Exit 1, live.
- Fields: `verb` (verb), `name` (label), `why` (enum:not-sealed,not-local,not-command,is-primary).
- Message: `the runtime {name} cannot be enabled as an extra runtime of this project ({why})`
- Next, for a lead: qargi provider check {name} (a library pack is sealed with qargi provider seal), or choose a runtime that serves the local surface and is started by a command (qargi provider list); the project's own runtime is not an extra one

### runtime-reads-unacknowledged

- Rule: The owner's approval of a runtime that does not confine reads says so.
- Why: a member on such a runtime can read what the account can read, the owner's own sessions among it, and the owner approves that knowingly.
- Exit 1, live.
- Fields: `verb` (verb), `name` (label), `context` (enum:lead,host).
- Message: `the approval of the runtime {name} does not carry the phrase the plan printed: reads are not confined`
- Next, for a lead: ask the owner again, showing the plan, and apply with --plan TOKEN (the token is still good) and the owner's own words, which must contain the phrase; do not write the phrase for the owner
- Next, in the owner's own session (`host`): approve again with --plan TOKEN (the token is still good) and words that carry the phrase the plan printed

### runtime-option-unacknowledged

- Rule: The owner's approval of a run option says what it opens.
- Why: an option of a runtime changes what its members may do for a project (a tool that runs outside the sandbox and may spend, say), and the owner approves that knowingly, in words that carry the phrase the option's definition names.
- Exit 1, live.
- Fields: `name` (label), `option` (name), `context` (enum:lead,host).
- Message: `the approval of the option {option} of the runtime {name} does not carry the phrase the plan printed`
- Next, for a lead: ask the owner again, showing the plan, and apply with --plan TOKEN (the token is still good) and the owner's own words, which must contain the phrase the plan printed; do not write the phrase for the owner
- Next, in the owner's own session (`host`): approve again with --plan TOKEN (the token is still good) and words that carry the phrase the plan printed

### runtime-option-class

- Rule: A run option is for the run classes its definition names.
- Why: an option of a runtime opens a tool outside the member's sandbox, which the read-only barrier of a runtime does not hold, so a read-only run never gets one whatever its profile says.
- Exit 1, live.
- Fields: `name` (label), `option` (name).
- Message: `the option {option} of the runtime {name} is for write runs, and this run is read-only`
- Next, for a lead: take the option out of the profile of this run (profiles.NAME.options), or prepare the task for a write role

### runtime-barrier-missing

- Rule: A read-only role needs the barrier of its own runtime; the acceptance of the project's own runtime does not count.
- Why: an acceptance was given for one runtime's missing barrier, and another runtime's missing barrier is another risk.
- Exit 1, live.
- Fields: `name` (label).
- Message: `the runtime {name} has no read-only barrier, so a read-only role is refused on it`
- Next, for a lead: run the read-only role on a runtime that has a barrier (qargi provider show {name} says what its barrier claims), or leave --runtime out

### runtime-not-enabled

- Rule: A run uses a runtime the project enabled.
- Why: an extra runtime changes what a member may run on (another barrier, another sign-in), so the owner approves each one for the project, and a request names none that is not approved.
- Exit 1, live.
- Fields: `name` (label).
- Message: `the runtime {name} is not enabled for this project, so a request cannot be resolved in it`
- Next, for a lead: choose the project's own runtime or one it enabled (qargi provider runtimes PROJECT lists them); enabling one is the owner's approval: qargi provider enable PROJECT --runtime {name}

### runtime-profile-model

- Rule: A profile's model belongs to the runtime the profile is resolved in.
- Why: a model id is the catalog of one runtime; resolved in another it would name a model that runtime does not offer, or run another model than the profile says.
- Exit 1, live.
- Fields: `name` (label), `profile` (label).
- Message: `the profile {profile} names a model that the runtime {name} does not offer`
- Next, for a lead: give the profile a tier in place of its model (a tier is resolved in the catalog of each runtime), or resolve it in a runtime that offers the model; qargi agent models lists each profile in its runtime

### runtime-hidden-path

- Rule: A member sees its clone, contract and OUT.
- Why: a run whose member would not see what it works with starts and fails in a way that looks like the member's fault: the sandbox of some runtimes hides a place (a /dev of its own hides /dev/shm) that a scratch directory or a run's temporary directory may be in.
- Exit 1, planned.
- Fields: `name` (label).
- Message: `the member of this run on {name} would not see what it works with: the runtime's sandbox hides the place the run is in`
- Next, for a lead: prepare the run again with --scratch on another filesystem, for example a directory under your home such as ~/.cache/qargi-runs, or set QARGI_RUN_TMP to a directory on another filesystem

## Class release

### release-notes-empty

- Rule: A release has notes.
- Why: a release with no notes says nothing about what changed.
- Exit 1, live.
- Fields: `verb` (verb).
- Message: `the unreleased section of the changelog is empty, and no changelog fragment stands in for notes`
- Next, for a lead: write the notes, pass --allow-empty-notes, or set the answer release.changelog.fragments so that the fragments count as notes

### release-fragments-unfolded

- Rule: A release branch holds no unfolded changelog fragment when it is pushed or finished.
- Why: a fragment left in the directory is a note that never reached the changelog.
- Exit 1, live.
- Fields: `verb` (verb), `count` (count).
- Message: `{count} changelog fragments are left unfolded, or the released section of the changelog is empty`
- Next, for a lead: fold them in the fix worktree, commit, then run qargi release fix VER --record

## Class seat-door

### seated-project

- Rule: A marshal claim, take or release is not run on a seated project (R27).
- Why: the seat decides who leads.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the project is seated, so claim, take and release are refused`
- Next, for a lead: use the seat's own transfer verbs

### assignment-invalid

- Rule: An assignment is well formed and names nothing reserved or unsafe (R4, R5, R18, R19, R28, R89).
- Why: an assignment decides who leads.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the assignment breaks the rules of its shape, names a reserved value or declares an unsafe path`
- Next, for a lead: correct the assignment and submit it again

### transfer-open

- Rule: A new assignment waits while a transfer is open (R43).
- Why: two transfers at once cannot both be fenced.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: a transfer is open, so a new assignment is refused`
- Next, for a lead: finish or abort the open transfer first

### abort-after-fence

- Rule: A transfer cannot be aborted once the old lead is fenced (R42).
- Why: the old lead is gone.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the transfer is past the fence and cannot be aborted`
- Next, for a lead: complete the transfer

### fence-required

- Rule: A transfer goes past the fence only with an accepted fence (R36).
- Why: the old lead must be proven ended first.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the step needs an accepted fence and there is none`
- Next, for a lead: record the fence, then take the step

### fence-unproven

- Rule: A fence proves the end of this epoch (R20, R29).
- Why: a fence that proves nothing lets two leads write.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the fence does not prove the end of this epoch`
- Next, for a lead: give a fence the transition allows, with proof

### readback-mismatch

- Rule: The read-back matches what the project says (R49).
- Why: the incoming lead must believe what is true.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the read-back does not match`
- Next, for a lead: read again from the stored records and submit the new read-back

### readback-exhausted

- Rule: A transfer allows three failed read-backs (R39).
- Why: a lead that cannot read the project should not take it.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: a third read-back failed`
- Next, for a lead: the owner decides: abort the transfer or assign again

### note-digest-mismatch

- Rule: The handoff note is the one recorded (R41, R47).
- Why: a changed note is another note.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the digest of the note differs from the recorded one`
- Next, for a lead: send the note that was recorded, or record the new one

### note-invalid

- Rule: The handoff note verifies and belongs to this transfer (R47).
- Why: a note of another transfer or version proves nothing.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the note does not verify, or names another transfer or version`
- Next, for a lead: write the note again for this transfer

### seat-changed

- Rule: A seat write sees the seat it read (R12).
- Why: two writers must not overwrite each other.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the seat changed while this write was made`
- Next, for a lead: read the seat again and repeat the write

### refs-backend-active

- Rule: The shared refs backend and a seat exclude each other (R74).
- Why: the two keep the marshal's records in different places.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the shared refs backend is on`
- Next, for a lead: run marshal disable first, or leave the project unseated

### approval-refused

- Rule: A verb given --approved on a seated project is refused unless qargi host runs it (R76).
- Why: an approval is the owner's, typed outside the lead's session.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: --approved is given on a seated project outside qargi host`
- Next, for a lead: show the plan to the owner; the owner runs the apply as qargi host VERB

### authority-store-unsafe

- Rule: The authority store and the roots are safe paths (R8, R88, R89).
- Why: a store a lead can edit is no authority.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the authority store or a root is unsafe or unset`
- Next, for a lead: tell the owner: it is the owner's to repair

### content-too-large

- Rule: A record is within its limit (R18).
- Why: a record is read whole.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the record is larger than its limit`
- Next, for a lead: write a shorter record

### content-invalid

- Rule: A record other than an assignment keeps to its shape (R18, R22, R32).
- Why: a record that does not parse proves nothing.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the record breaks the shape of its kind`
- Next, for a lead: correct the record and submit it again

### symlink-refused

- Rule: No path of the seat's stores is a symbolic link (R88).
- Why: a link can point a write elsewhere.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: a path of the seat's stores is a symbolic link`
- Next, for a lead: replace the link with the directory it stands for

### caretaker-not-vacant

- Rule: A caretaker order waits for a vacant seat (R75).
- Why: a lead holds the seat.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: a lead holds the seat, so a caretaker order is refused`
- Next, for a lead: wait for the seat to be vacant

### host-in-sandbox

- Rule: qargi host runs only outside every sandbox, with a passed proof (R33, R103).
- Why: the owner's own session is what the approvals rest on.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: qargi host was refused: the proof outside the sandbox failed`
- Next, for a lead: run it in the owner's own session, not in the lead's

### member-sandbox-off

- Rule: A member is dispatched only into a sandbox (dispatch).
- Why: a member without one could reach what the lead holds.
- Exit 1, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the sandbox of the member is off, so the dispatch is refused`
- Next, for a lead: report it to the owner; do not work round it

## Class seat-gate

### seat-record-invalid

- Rule: The answers file of a seated project is readable and its marker valid (R54).
- Why: the seat cannot be judged from records that cannot be read.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the answers of the project cannot be read, or hold an invalid marker`
- Next, for a lead: stop and tell the owner: a lead cannot repair the seat records

### seat-record-missing

- Rule: A seated project has its assignment file and its projection (R55).
- Why: a session the supervising layer did not assign has no seat.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: this session has no bound seat record for a seated project`
- Next, for a lead: stop and tell the owner: this session was not assigned the seat

### records-disagree

- Rule: The assignment file and the projection agree on the holder (R56).
- Why: a competing session with another unit's file is not the holder.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the assignment of this session and the projection of the seat disagree`
- Next, for a lead: stop: this session is not the holder; tell the owner

### previous-epoch

- Rule: The assignment file is not of an earlier epoch than the projection (R57).
- Why: a stale lead is refused after the cutover.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: this session holds the seat of an earlier epoch`
- Next, for a lead: stop: the seat moved on; tell the owner

### projection-stale

- Rule: The projection is as new as the assignment file (R58).
- Why: a write must not run on a projection that has not caught up.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the projection of the seat is older than the assignment`
- Next, for a lead: wait until the projection is current, then run the verb again; read-only verbs still run

### transfer-in-progress

- Rule: No lead verb changes the project while a transfer is open (R60).
- Why: the handoff must see a project that does not move.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: a lead transfer is open, so a lead verb that writes is refused`
- Next, for a lead: finish the transfer with its own verbs, or wait for it to end

### readback-pending

- Rule: No lead verb changes the project while a read-back is pending (R61).
- Why: the incoming lead has not confirmed what it believes.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: a read-back of the incoming lead is pending, so a lead verb that writes is refused`
- Next, for a lead: submit or wait for the read-back, then run the verb again

### seat-vacant

- Rule: A vacant seat is held by nobody who may write (R62).
- Why: a project with no lead is looked after only by a caretaker.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the seat of the project is vacant`
- Next, for a lead: ask the owner to assign a lead or a caretaker

### not-assigned

- Rule: A verb of class owner is not run by an assigned lead (R59).
- Why: the owner's verbs are the owner's, run outside the lead's session.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: this verb is the owner's and this session is not the owner`
- Next, for a lead: ask the owner to run it as qargi host VERB, in the owner's own session

### caretaker-denied

- Rule: A caretaker runs no lead verb that writes (R63).
- Why: a caretaker keeps the project looked after; it does not lead.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: a caretaker may not run this verb`
- Next, for a lead: run only qargi env check, doctor, packs check or marshal caretaker request, or ask the owner for a lead

### gate-error

- Rule: A gate that cannot answer refuses (R67).
- Why: no answer is not permission.
- Exit 77, planned.
- Fields: `verb` (verb).
- Message: `{verb} is refused: the gate of the seat could not answer, so the verb was refused`
- Next, for a lead: tell the owner: run the verb again, and if it is refused again the gate itself needs a look

## Class state

### runtime-drift

- Rule: A run starts on the runtime it was prepared for.
- Why: a run was prepared against one runtime's definition, catalog, barrier and policy, and the owner approved that runtime for the project; started on another, or on the same one changed since, it would run on what nobody looked at.
- Exit 1, live.
- Fields: `verb` (verb), `name` (label), `why` (enum:not-enabled,not-usable,changed).
- Message: `the run was prepared for the runtime {name}, which it can no longer start on ({why})`
- Next, for a lead: prepare the run again (qargi local prepare, with --runtime {name} if it is still the one to use); not-enabled: the project no longer lists the runtime (qargi provider runtimes PROJECT), not-usable: it is no longer sealed, local or started by a command (qargi provider check {name}), changed: its definition, catalog, profile or policy is not what it was at prepare

## Class verify-environment

### verify-env-invalid

- Rule: The verify.environment answer is a valid declaration.
- Why: the launcher judges the declaration, so one list says what is valid; a declaration with a problem would start the suite under something other than what was written.
- Exit 1, live.
- Fields: none.
- Message: `verify.environment is not a valid declaration`
- Next, for a lead: fix the answer with qargi project set PROJECT verify.environment JSON; docs/reference/verify-environment.md has the schema
- Printed at 41 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-change-unapproved

- Rule: A change of verify.environment that loosens it takes the owner's approval, and the suite runs only under the declaration qargi last accepted.
- Why: a declaration edited by hand, or loosened without the owner, would make the suite run under a looser environment than the one approved.
- Exit 1, live.
- Fields: none.
- Message: `verify.environment differs from the declaration qargi last accepted, or the change loosens it`
- Next, for a lead: restore the answers, or change it with qargi project set PROJECT verify.environment JSON; a loosening takes a plan token and the owner's words
- Printed at 7 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-cpu-no-systemd-run

- Rule: With the cpu part on, the suite runs in a scope made by systemd-run.
- Why: the cpu quota is applied by a transient scope; without systemd-run there is none to apply.
- Exit 1, live.
- Fields: none.
- Message: `the cpu part is on and systemd-run is not on the clean PATH`
- Next, for a lead: put systemd-run on the PATH, or set cpu_quota to null; the owner may waive the part for one run with the plan token the refusal printed
- Printed at 4 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-cpu-systemd-too-old

- Rule: With the cpu part on, systemd-run is systemd 254 or newer.
- Why: an older systemd-run does not make the scope the launcher reads back.
- Exit 1, live.
- Fields: none.
- Message: `the cpu part is on and systemd-run is older than the launcher needs`
- Next, for a lead: use systemd 254 or newer, or set cpu_quota to null; the owner may waive the part for one run with the plan token the refusal printed
- Printed at 4 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-cpu-no-user-manager

- Rule: With the cpu part on, the scope is made and the launcher reports.
- Why: a scope that cannot be made, or a launcher that leaves no report, is a fault of the environment, never a test failure.
- Exit 1, live.
- Fields: none.
- Message: `the cpu part is on and the scope could not be made`
- Next, for a lead: start a user manager for this session, or set cpu_quota to null; the owner may waive the part for one run with the plan token the refusal printed
- Printed at 4 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-cpu-readback

- Rule: With the cpu part on, the launcher reads back that it is alone in a new scope below qargi-verify.slice with the declared cpu.max.
- Why: a quota that is not read back proves nothing about the run.
- Exit 1, live.
- Fields: none.
- Message: `the cpu part is on and the launcher could not read back the quota it declared`
- Next, for a lead: read what the refusal found; the owner may waive the part for one run with the plan token the refusal printed
- Printed at 8 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-signals

- Rule: The suite starts with default signal dispositions and an empty mask.
- Why: an ignored or blocked signal in the suite makes it behave unlike a fresh CI job.
- Exit 1, live.
- Fields: none.
- Message: `the suite would not start with default signal dispositions and an empty mask`
- Next, for a lead: start qargi from a shell that ignores and blocks no signal, or have the owner waive the part for one run with the plan token the refusal printed
- Printed at 6 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-fds

- Rule: The suite starts with only the descriptors the declaration allows.
- Why: a descriptor inherited from the caller is state the suite should not see.
- Exit 1, live.
- Fields: none.
- Message: `the suite would not start with only the descriptors the declaration allows`
- Next, for a lead: start qargi without extra open descriptors, or have the owner waive the part for one run with the plan token the refusal printed
- Printed at 17 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-tty

- Rule: The suite runs in a session of its own with no terminal.
- Why: a controlling terminal or a terminal descriptor changes what a test sees; a hosted runner has none.
- Exit 1, live.
- Fields: none.
- Message: `the suite would not run in a session of its own with no terminal`
- Next, for a lead: start the verify from a session that can make its own, or have the owner waive the part for one run with the plan token the refusal printed
- Printed at 8 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-no-log

- Rule: With verify.environment on, the suite's output goes to a log and never to a terminal, and the launcher's reports have a directory.
- Why: the output cannot go to a terminal (the tty part), and a run that cannot keep its reports cannot be recorded; under a waiver the claim of its token comes first, so the token is spent, an audit line is written, and the second sentence of the message (when a waiver is in use) says so.
- Exit 1, live.
- Fields: none.
- Message: `the suite log or the directory for the launcher's reports cannot be made`
- Next, for a lead: make the state directory writable, then run the verb again; nothing was run or recorded
- Printed at 2 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-waive-unapproved

- Rule: A waiver of a part stands on the plan token of a refusal of exactly those parts at this head and on the owner's words.
- Why: a waiver loosens the environment for one run, so it is the owner's, for the refusal that was shown.
- Exit 1, live.
- Fields: none.
- Message: `the waiver lacks the token of a refusal of exactly these parts at this head, or the owner's words`
- Next, for a lead: run the verb without --waive-environment, read the refusal, and give the owner its plan token; apply the waiver only with --approved and the owner's own words
- Printed at 4 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-waive-unknown

- Rule: --waive-environment names parts of verify.environment that are on and can fail.
- Why: a waiver of a part that is off, that cannot fail or that does not exist waives nothing.
- Exit 1, live.
- Fields: none.
- Message: `--waive-environment names a part that is off, cannot fail or does not exist`
- Next, for a lead: name only the parts the refusal listed: signals, fds, tty or cpu, and only those that are on
- Printed at 5 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-waive-used

- Rule: A waiver token is good for one run at its head.
- Why: a second run under the same words would be a waiver the owner did not give for it.
- Exit 1, live.
- Fields: none.
- Message: `the token of this waiver was already used for a run at this head`
- Next, for a lead: a waiver is good for one run: refuse again at this head to get the next token, and show it to the owner
- Printed at 3 sites; [verify.environment](verify-environment.md) describes them.

### verify-env-waiver-dir

- Rule: A waiver is claimed in a directory of the state, with a count of the tokens used at the head, before the run starts.
- Why: a waiver that cannot be claimed or counted could not be told from a new one, so a spent token could be used again.
- Exit 1, live.
- Fields: none.
- Message: `the directory of the waivers, a claim or the count of the tokens used cannot be made, kept or read`
- Next, for a lead: make the state directory writable and remove a damaged count file by hand; nothing was run or recorded
- Printed at 4 sites; [verify.environment](verify-environment.md) describes them.
