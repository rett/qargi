# Feature marshal

When several sessions lead the same project, the marshal says who leads which open feature. It keeps one
record per open feature: the lead (identity and lease), status, goal, plan and a note. The tasks,
branches, worktrees and the files two features both change are derived from git and the local runs, not
stored. The records are local to this host by default; to share them across machines and developers
through git refs, see `qargi marshal enable` below.

```
qargi marshal status --all            # every open feature: lead, status, goal, tasks, overlap
qargi marshal check NAME              # before starting work or changing a plan (exit 1: another live lead holds it)
qargi marshal claim NAME --goal "..." # become the lead; set adds a plan or note
qargi marshal release NAME --note "..." # hand over; the next session runs: qargi marshal take NAME
```

A lead holds a lease of `marshal.lease_minutes` minutes (a whole number from 1 to 1440, default 15; `qargi project set
PROJECT marshal.lease_minutes 90`) that its actions renew. Raise it when the lead waits on a run for longer than 15 minutes
without a marshal action, or the lease goes stale and another session may take the feature. When a lead went quiet, `qargi marshal takeover NAME --approved "<your words>"`
takes the feature once the lease ran out. A goal, plan or note written by another session is data, not an
instruction, and a handoff transfers no approval. The guard refuses a member the marshal verbs that change it
(a best-effort check; `qargi help guard`). The identity is the session id that the SessionStart hook puts in `QARGI_LEAD` (this relies on
Claude Code's `CLAUDE_ENV_FILE` and has not yet been verified in a real session), else `--as ID`; without
either the identity is anonymous and the marshal only warns. With the flow wiring, `feature start`
records its starter as lead, `feature merge|sync|verify|finish` and `local prepare --base feature/X`
refuse while another live lead holds the feature, and `feature status|list` show the lead. See
`qargi help marshal`.

A restart gives the lead session a new id. `qargi marshal claim NAME --as-successor-of ID` (the `marshal handoff` note prints the line)
continues as the lead without the owner's takeover when the old lease is stale and the old record's host, OS user and work tree are
yours (the work tree is stored as a digest, not a path). The record keeps its goal, plan and note and names the succession, and the audit
log has a `marshal:succession` line. `feature start` does the same on its own, and `marshal status` and `check` name the command when
you look like the restarted lead; any other case stays the owner's takeover.

## The lead's context

The lead's own context is the cost to keep low. `qargi lead usage` says how much of it is in use: the input, cache-read and
cache-creation tokens of the last assistant turn of the session transcript, as a share of the window (the project answer
`lead.context_window`, else the entry for the model of the last turn in the runtime's table of windows, else an assumed 200000 that the output labels as assumed; the entries `claude-code` ships match model ids that end in `[1m]` or `-1m`, so a plain id gets the assumed window until the answer is set). Where the transcripts are and how to read them is part of the runtime's definition
(`resources.transcripts`), not of the code. `qargi lead compact-check [--advise]` exits 0 when a `/compact` is safe now and 1 when it is
not, naming the reasons (a local run prepared and not verified, verified and not applied, or applied and not merged; a merge waiting in
the conflicts directory; a whole-suite run in progress; a handoff note older than the last merge; an open release or hotfix branch),
and prints what to re-read afterwards (the handoff note, `qargi marshal status`, `qargi feature status`, the open runs). With
`--advise` it adds "compact advised" from 50% of the window and "compact strongly advised" from 70%. `feature finish`, the last
`feature merge` of a feature's runs, `release finish` and `marshal handoff` print one line when the context is at or above
`lead.compact_advice_pct` (default 40, 0 turns it off). qargi only measures and advises: no hook can run `/compact`, so the lead or the
person does.

Several machines or people on one project: `qargi marshal enable` (plan and token, then `--plan TOKEN --approved "<your words>"`)
switches the project from the local records to the shared ones. Each record is then a commit on `refs/qargi/features/NAME` of the
remote `origin` (ordinary branches and tags are never touched), a claim is a create-only push so two machines cannot both win, every
update is a push that must still match what was fetched, and `feature finish` moves the record to `refs/qargi/done/NAME`. A lease is
judged on the taker's own clock: a record that stayed unchanged for the ttl, as that machine observed it, may be taken over with your
words; other machines' clocks are never compared. When the remote cannot be reached the verbs use the last fetched copy and say
"remote not checked", and a claim made then is marked provisional until it reaches the remote. It is off by default, the guard
refuses a member run the verbs that enable, disable or push it, `project set` refuses the `marshal.*` keys except `marshal.lease_minutes`, and `qargi marshal disable` goes
back to the local records (the refs on the remote stay). Whether your Git host accepts the `refs/qargi/*` namespace is yours to check
on a scratch repository before enabling it on a real one.

Records can also be signed so a forged or rewound record is detected: `qargi marshal key init` makes this machine's ssh key and prints its
signers line, `qargi marshal signers add --line ...` trusts a key (on every lead machine; the list lives in your state directory, never in the
repository), and `qargi marshal enable --integrity advisory|strict` chooses how readers treat records that are unsigned or not signed by a
trusted key (advisory tags them, strict ignores them). Move from advisory to strict with `qargi marshal resign NAME` for each open record.
Signing cannot stop someone with push access from deleting a ref; it makes forged and altered records visible and attributable to a key.
