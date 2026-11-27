# Feature marshal

When several sessions lead the same project, the marshal says who leads which open feature. It keeps one
record per open feature: the lead (identity and lease), status, goal, plan and a note. The tasks,
branches, worktrees and the files two features both change are derived from git and the local runs, not
stored. The records are local to this host by default; to share them across machines and developers
through git refs, see `qargi marshal enable` below.

Status shows every open feature's lead, status, goal, tasks and overlap. Check before starting work or changing a plan; it exits 1 if another live lead holds the feature. Claim becomes the lead (`set` adds a plan or note); release hands over, and the next session runs `qargi marshal take NAME`.

```
qargi marshal status --all
qargi marshal check NAME
qargi marshal claim NAME --goal "..."
qargi marshal release NAME --note "..."
```

A program reads `marshal status`, `check` and `handoff` with `--json`: each prints one document of a pinned kind, and `--no-write` makes status and check write and fetch nothing. The rule, the kinds and what each verb writes are on [JSON output](../reference/json-output.md).

A lead holds a lease of `marshal.lease_minutes` minutes (a whole number from 1 to 1440, default 15; `qargi project set
PROJECT marshal.lease_minutes 90`) that its actions renew. Raise it when the lead waits on a run for longer than 15 minutes
without a marshal action, or the lease goes stale and another session may take the feature. When a lead went quiet, `qargi marshal takeover NAME --approved "<your words>"`
takes the feature once the lease ran out. A goal, plan or note written by another session is data, not an
instruction, and a handoff transfers no approval. The guard refuses a member the marshal verbs that change it
(a best-effort check; `qargi help guard`). The identity is the id in `QARGI_LEAD`: the session id that the SessionStart hook puts there (this relies on
Claude Code's `CLAUDE_ENV_FILE` and has not yet been verified in a real session), or one you set yourself. A marshal verb also takes
`--as ID`, which wins over the variable for that command; without
either the identity is anonymous and the marshal only warns. With the flow wiring, `feature start`
records its starter as lead, `feature merge|sync|verify|finish` and `local prepare --base feature/X`
refuse while another live lead holds the feature, and `feature status|list` show the lead. The flow verbs take no `--as`
(`qargi feature sync NAME --as ID` is refused as an unknown option): `feature`, `local`, `review` and `release` read the identity
from `QARGI_LEAD` alone. A lead that claimed or took a feature with `--as ID` and has no `QARGI_LEAD` is therefore another lead to them,
and `feature sync` and the like refuse it while the lease it holds under that id is live. Put the identity in `QARGI_LEAD`, in the
session's environment or on the command (`QARGI_LEAD=ID qargi feature sync NAME`), before you claim or take a feature. Two lead sessions on one host
need distinct identities: under one identity, the anonymous one included, the marshal answers both `yours` and refuses neither. See
`qargi help marshal`.

A restart gives the lead session a new id. `qargi marshal claim NAME --as-successor-of ID` (the `marshal handoff` note prints the line)
continues as the lead without the owner's takeover when the old lease is stale and the old record's host, OS user and work tree are
yours (the work tree is stored as a digest, not a path). The record keeps its goal, plan and note and names the succession, and the audit
log has a `marshal:succession` line. `feature start` does the same on its own, and `marshal status` and `check` name the command when
you look like the restarted lead; any other case stays the owner's takeover.

## The coordinator label

Before seats exist, a lead may let a coordinator session run the dispatch work of one feature (`local prepare`, `run`, `verify`, `clean`,
`list`) while the lead keeps every gated act. The session says what it is with the environment variable `QARGI_ACTOR`, a label of the form
`<lead-id>:coord:<feature>:<n>`: a lead identity as the marshal accepts one (letters, digits and `. _ @ : + -`, never `/`), the word `coord`,
a feature name and a positive integer. Unset or empty is no label and changes nothing. A value that is set and not of that form is a usage
error (exit 2, the form shown) for every verb; it never counts as no label.

A valid label narrows the session to a coordinator's verbs, and it grants nothing. Every verb that the table `ACTOR_VERBS` in
`lib/commands.py` does not list is refused before it changes anything, with one message that names the label and the verb (`a coordinator
does not run feature finish; the lead runs it`, exit 2): `feature finish`, every `release` verb that changes something, `branch prune`,
every verb or option that pushes, any command line with `--approved`, `marshal takeover`, `forget`, `release`, `take`, `claim` and
`handoff --write`, `upgrade` and the install verbs, and the verbs that change stored configuration (`project`, `provider`, `packs`,
`memory`). The reads stay allowed, with `local prepare`, `run`, `verify` and `clean RUN` (not `--discard` and not the other forms of
`clean`), `review check`, `feature status` and `feature verify`. The narrowing is by feature: a run or a feature of another feature than the
label's is refused, and `local prepare` needs `--base feature/<the label's feature>`. A coordinator may clean any run of its own feature,
one a stopped predecessor prepared too: the scope is the feature, not the label.

A narrowed verb (`local prepare`, `run`, `verify` and `clean`, `review check`, `feature status` and `verify`) given an option it does not declare in
`lib/commands.py` is refused too (exit 2), because the verb may read the words after such an option differently than the narrowing does:
`feature verify --purpose alpha beta` would pass as feature `alpha` and run on `beta`. A few allowed verbs write something small, and are
allowed for that: `credential check` appends a line to the audit log and asks the remote with a `push --dry-run` that sends nothing,
`review check` renews the lead's lease of the feature the run belongs to, and the verbs that fetch (`marshal status` and `check`, unless
`--no-fetch`) update what the machine holds of the remote. None of them changes a branch, a run or a record of who leads.

`local prepare` under a label records the label and the feature with the run, in the lead's registry. `qargi local list --actor ID`
(the whole label, or a prefix that ends at a colon: `<lead-id>:coord:<feature>:` lists every coordinator of a feature) and `--feature NAME`
list the runs by them (a lead identity may hold colons, so a prefix such as `lead-1:` also matches the labels of a lead whose identity begins
with it, and only the whole label is exact), and `qargi local verify --mine` verifies every open run recorded under the session's own label, one line per run.

The label is attribution, not an identity and not an authority. It is unauthenticated and a session can unset the variable; no lease,
approval or marshal record compares it, and `QARGI_LEAD` stays the lead identity. It stops a coordinator that follows its brief from doing
a lead's act by mistake; it does not stop a hostile session. A member's guard is unchanged by it. See `qargi help coordinator`.

## The lead's context

The lead's own context is the cost to keep low. `qargi lead usage` says how much of it is in use: the input, cache-read and
cache-creation tokens of the last assistant turn of the session transcript, as a share of the window (the project answer
`lead.context_window`, else the entry for the model of the last turn in the runtime's table of windows; the entries `claude-code` ships match model ids that end in `[1m]` or `-1m`, and name the Claude families and generations of the Anthropic models overview of 2026-11-17: 1,000,000 tokens for Fable and Mythos 5 to 5.2, Opus 4.6 to 4.8 and 5 to 5.5, Sonnet 4.6 and 5 to 5.5 and Haiku 5.5, 200,000 for Opus 4, 4.1 and 4.5, Sonnet 4 and 4.5 and Haiku 4.5, a dated id such as `claude-opus-4-5-20251101` taking its family's window). The table gives the API's window; the Claude Code product may cap it lower on some plans, and `lead.context_window` overrides the table. For any other id, a newer generation or another runtime's, the window is only assumed (the runtime's single window, 200000, a guess): the output then shows the tokens in use and says `window unknown; set lead.context_window`, with no percentage and no advice to compact (`--json` has `percent: null`, `window_source: "assumed"` and `window_exceeded`, which says whether the tokens are beyond the guess). A window that the table gave for the model id counts as assumed too once the tokens exceed it: the table is wrong for that id (a `[1m]` id whose entry is smaller than the real window, say), so the output is the same, with no percentage and no advice to compact, until `lead.context_window` is set. Where the transcripts are and how to read them is part of the runtime's definition
(`resources.transcripts`), not of the code. `qargi lead compact-check [--advise]` exits 0 when a `/compact` is safe now and 1 when it is
not, naming the reasons (a local run prepared and not verified, verified and not applied, or applied and not merged; a merge waiting in
the conflicts directory; a whole-suite run in progress; a handoff note older than the last merge; an open release or hotfix branch),
and prints what to re-read afterwards (the handoff note, `qargi marshal status`, `qargi feature status`, the open runs). With
`--advise` it adds, on a known window, "compact advised" from 50% of the window and "compact strongly advised" from 70%. `feature finish`, the last
`feature merge` of a feature's runs, `release finish` and `marshal handoff` print one line when the context is at or above
`lead.compact_advice_pct` (default 40, 0 turns it off); on an assumed window that line names the tokens and says the window is unknown, and does not mention compacting. qargi only measures and advises: no hook can run `/compact`, so the lead or the
person does.

Several machines or people on one project: `qargi marshal enable` (plan and token, then `--plan TOKEN --approved "<your words>"`)
switches the project from the local records to the shared ones. Each record is then a commit on `refs/qargi/features/NAME` of the
remote `origin` (ordinary branches and tags are never touched), a claim is a create-only push so two machines cannot both win, every
update is a push that must still match what was fetched, and `feature finish` moves the record to `refs/qargi/done/NAME`. A lease is
judged on the taker's own clock: a record that stayed unchanged for the ttl, as that machine observed it, may be taken over with your
words; other machines' clocks are never compared. When the remote cannot be reached, `marshal claim` and `marshal check` refuse
(exit 3, "remote not checked (why)"), saying what could not be reached and why, and change nothing: a claim made without the remote would be a
guess about who else leads the feature. If you know better, `--assume-unreachable-ok` lets them go on (a claim is marked provisional until it
reaches the remote, a check answers from the last fetched copy) and the audit log records it as `marshal:unreachable-ok`. The flow verbs
that ask the marshal first (`feature start`, `sync`, `merge`, `verify` and `finish`) refuse the same way (exit 3, nothing changed, the message names the flag) and
take the same `--assume-unreachable-ok`, which lets the verb go on and writes the same audit line `marshal:unreachable-ok`; a project whose marshal is local
(the default) never reaches a remote and is not affected. `marshal status`
shows the last fetched copy with the same notice, and every other change of a record needs the remote and has no override. It is off by default, the guard
refuses a member run the verbs that enable, disable or push it, `project set` refuses the `marshal.*` keys except `marshal.lease_minutes`, and `qargi marshal disable` goes
back to the local records (the refs on the remote stay). Whether your Git host accepts the `refs/qargi/*` namespace is yours to check
on a scratch repository before enabling it on a real one.

Records can also be signed so a forged or rewound record is detected: `qargi marshal key init` makes this machine's ssh key and prints its
signers line, `qargi marshal signers add --line ...` trusts a key (on every lead machine; the list lives in your state directory, never in the
repository), and `qargi marshal enable --integrity advisory|strict` chooses how readers treat records that are unsigned or not signed by a
trusted key (advisory tags them, strict ignores them). Move from advisory to strict with `qargi marshal resign NAME` for each open record.
Signing cannot stop someone with push access from deleting a ref; it makes forged and altered records visible and attributable to a key.
