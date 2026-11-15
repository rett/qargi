# Campaign records v1

`qargi campaign` records bounded, editable coordination declarations in a
private local store for projects managed inside or outside Qargi. Ataniq is
the related, separately developed orchestration project; its orchestration
remains separately owned. Role transfer, scheduling, ingestion, notifications,
automated feedback or adoption, release/deploy and federation are future
campaign work.

These records are supplied claims. They establish neither observed project or
source state, acceptance, message delivery nor computed measurements. Every
evidence/outcome link remains an unresolved pointer, even with a digest.
The evidence invalidation policy is undecided. Fresh review against the actual
dependency is required before merge acceptance; this command does not enforce
that standard. Authorized preparation against provisional designs does not
establish merge readiness.

The interface and identities are provider neutral. This does not qualify a
runtime, adapter or cross-provider operation. Qargi's supported host boundary
remains Linux with GNU tools; the store boundary is cooperating local writers
on a trusted local filesystem with local flock, atomic same-directory rename
and directory fsync. Network filesystems and hostile same-user/root mutation
are outside that qualification.

## Public commands

All forms start with `qargi campaign`:

- `check --spec FILE [--json]`: validate only the supplied declaration and
  report warnings. Available to members, without configuration or state probes.
  It does not check a parent transition, project registration or source state.
- `commit UUID --spec FILE --create [--json]`: create revision 1, or settle
  an exact-current retry of that creation.
- `commit UUID --spec FILE --expected-head DIGEST [--json]`: compare and swap
  a changed declaration against that exact parent, or settle its exact retry.
- `show UUID [--revision DIGEST] [--json]`: return the current declaration,
  or a historical declaration after proving selected-head ancestry.
- `check UUID [--json]`: validate the current declaration and transition from
  its immediate parent (or creation). It does not verify the entire history.
- `log UUID [--cursor CURSOR] [--limit N] [--json]`: newest-first revision
  summaries, default 50, maximum 200, with bounded ancestry verification.

Every state form, including reads, is lead-only through cooperative
member-context refusal and a best-effort guard. Unknown caller context fails
closed. These checks do not authenticate a hostile same-user process or
establish OS isolation. There is no project or cloud setup requirement. The
selected UUID must equal the document's campaign UUID.

Options have exact spellings; valued options also accept `--option=value`.
A separated valued option cannot consume a word beginning `--`; use
`--spec=--filename` for such a filename. `--` ends option parsing: subsequent
words are positional, not options or spec values. Limits use unpadded ASCII
decimal integers from 1 through 200.

The spec is a bounded regular file; a user-selected symlink is followed.
Directories, FIFOs and other special files are refused. Declared locators,
references, pins and links are never opened, executed, fetched or ingested.

Exit 0 means a valid report (warnings may remain). CLI syntax usage errors
exit 2 with a diagnostic on stderr and no native report, including with
`--json`: malformed or nil positional UUIDs, bad `--expected-head` or
`--revision` digests, invalid or out-of-range log limits, empty/missing values,
duplicate options, abbreviations, mixed check forms and incompatible
creation/parent options. A malformed nonempty cursor instead exits 1 with a
native `cursor` failure report when reached in a lead context. Document/schema identity
failures also exit 1 with native reports, including `identity` for an invalid
document UUID and `identity-mismatch` for a document differing from the selected
UUID. These are distinct from malformed positional UUID usage errors.

Ordinary validation, store or output failure exits 1. A failed stdout write
cannot roll back a published commit and grants no additional credit. Native
`--json` routes a campaign report directly, rather than wrapping text in the
global plan format. Any development-run banner is on stderr.

## Closed declaration schema

Every object below requires exactly the named fields, including nullable
fields. Extra fields are rejected. Arrays may be empty. Integers exclude
booleans. Version 1 supports no floats. Text is preserved exactly, with no
Unicode, whitespace or date normalization; JSON integer `-0` becomes `0`.

Common grammar and limits:

- UUID: lowercase hexadecimal `8-4-4-4-12` groups, non-nil. No UUID version
  bits are required. Campaign and participant project identities are neutral
  UUIDs, independent of Qargi registration or adoption.
- Digest: `sha256:` followed by exactly 64 lowercase hexadecimal digits.
- Birth ID: `rN:slug`, N from 1 through 999999999, no leading zeros; slug is
  at most 48 characters matching `[a-z0-9]+(?:-[a-z0-9]+)*`.
- Text contains non-whitespace words and Unicode scalar values. Control
  characters are refused except LF, which is allowed only in objective and
  requirement text. All field lengths below count UTF-8 bytes.
- `by` and `at` are at most 128 bytes. `at` is a valid graph ISO8601 date
  `YYYY-MM-DD` or timestamp: date, `T`/`t`, `HH:MM`, optional `:SS`
  and fractional seconds, optional `Z`/`z` or signed `HH:MM` offset.
  Time and offset colons are required by the implemented grammar.
  Hours are 00..23; calendar/time validity is checked. Fractions use dot or
  comma and require seconds. Timezone omission is allowed.
- A typed reference is `backlog:ID` or `feature:NAME`. Backlog IDs match
  `[a-z0-9][a-z0-9-]*[a-z0-9]` (at least two characters). Feature names use
  the slug grammar, at most 40 characters, excluding `master` and `develop`.
  Typed references are at most 1024 bytes and do not prove a source exists.

The root fields are `format`, `version`, `campaign`, `label`, `objective`,
`continues`, `participants`, `requirements`, `work`, `coordination`,
`provenance`. `format` is `campaign`, `version` is integer 1, `campaign` is
a UUID, `label` is text up to 128 bytes, and `objective` is text up to 4096
bytes. `continues` is null or `{campaign, revision}` containing a UUID and
digest; this is an immutable supplied predecessor pointer, not verified lineage
between campaigns. `provenance` is `{by, at, basis}` with text `basis` up to
1024 bytes and the common attribution fields.

`participants` has at most 32 objects `{id, label, locator, qargi_project}`.
`id` is a unique participant UUID; `label` is text up to 128 bytes; `locator`
is null or text up to 1024 bytes. `qargi_project` is null or a declared name
matching `[a-z][a-z0-9-]{0,63}`. That optional mapping is not checked against
registration. An external participant needs neither registration nor adoption.

`requirements` has at most 128 objects `{id, text, state}`. `id` is a birth
ID; `text` is multiline text up to 2048 bytes; `state` is `active` or
`withdrawn`.

`work` has at most 128 objects with fields `id`, `participant`, `state`,
`requirements`, `source`, `design`, `links`:

- `id` is a birth ID; `participant` is a declared participant UUID; `state`
  is `active` or `withdrawn`.
- `requirements` holds at most 128 distinct declared requirement birth IDs.
- `source` is null or `{kind, ref, pin}`. `kind` is `backlog`, `feature`
  or `external`. External `ref` is text up to 1024 bytes; the other kinds
  require a matching typed reference and a non-null participant Qargi mapping.
- `pin` is null or `{type, value}`. `item-digest` permits only backlog;
  `file-digest` permits backlog/external; both values are digests. `commit`
  permits all source kinds and requires 40 or 64 lowercase hex digits.
  `opaque` permits only external, with text value up to 128 bytes.
- `design` is null or `{rev, state, ref, by, at}`. `rev` is 1..999999999;
  `state` is `provisional` or `settled`; `ref` is text up to 1024 bytes.
  Attribution uses the common fields. A settled declaration is still a claim.
- `links` holds at most 32 link objects. Duplicate complete canonical objects
  are refused; different digests or attribution make distinct declarations.

A link is `{purpose, target, digest, status, by, at}`. `purpose` is one of
`prepared-request`, `service-receipt`, `delivered-output`, `verified-snapshot`,
`source-review`, `evaluation`, `outcome`, `release-plan`, `prior-declaration`.
`digest` is null or a digest; `status` must be `unresolved`. Attribution uses
the common fields. `target` has exactly one of these shapes:

- `{kind, ref}`: `kind` is `ref`, with text `ref` up to 1024 bytes.
- `{kind, run, prepared_identity, prepared_epoch, attempt}`: `kind` is
  `qargi-attempt`; `run` matches `qargi.[A-Za-z0-9]{6}` with a literal dot;
  `prepared_identity` is null or 32 lowercase hex digits; `prepared_epoch`
  is null or integer 0..253402300799; `attempt` is null or integer 1..256.

`coordination` has at most 256 objects
`{id, dependent, upstream, briefed, graph_pin}`. `id` is a birth ID;
`dependent` and `upstream` are distinct declared work IDs. Ordered pairs
must be unique. Cycles are not prohibited. Upstream work must have a design.
`briefed` is null or `{design_rev, ref, by, at}`: `design_rev` is an integer
from 1 through the upstream's declared design revision, `ref` is text up to
1024 bytes and attribution uses the common fields. It records a briefing
claim, not delivery or acknowledgment.

`graph_pin` is null or `{graph, relation, kind, from, to, status, verification}`.
`graph` is `{locator, digest}`, with text locator up to 1024 bytes and a
digest. `relation` uses the slug grammar, up to 1024 bytes. `kind` is
`requires` or `contains`; `status` is `proposed` or `confirmed`;
`verification` must be `unverified`. `from` and `to` are distinct typed
references matching the dependent and upstream work sources respectively.
Both sources must be backlog/feature sources of the same participant. This
does not read the graph or verify the relationship.

## Input budgets and canonical storage

Strict UTF-8 JSON input is at most 524288 bytes (512 KiB). Duplicate keys at
any depth and non-JSON numeric constants are refused. The document tree is
bounded to 32768 values, including object keys, and depth 16 counting the
root as 1 (keys and values descend one level). Every string also has a global
4096-byte limit. Integer tokens have at most 12 digits excluding minus and
absolute values at most 253402300799, before narrower field checks.

Canonical revision bytes are at most 262144 (256 KiB), including the envelope.
Snapshot validation reserves the maximum v1 envelope overhead: 155 bytes,
leaving 261989 canonical document bytes including its newline. The store
checks the final envelope separately; its header adds ten values and one
depth level outside the document's independent budgets.

Normalization sorts participants by UUID; requirements, work and coordination
by numeric birth revision then slug; work requirement IDs by that same order;
and links by canonical bytes. Object keys sort lexically. Encoding is compact
ASCII JSON with Unicode escaped and exactly one final newline.

An immutable object has exactly `{format, version, rev, previous, document}`:
`format` is `campaign-revision`, `version` is 1, `rev` is 1..999999999,
`previous` is null at revision 1 or the immediate parent digest thereafter,
and `document` is the normalized declaration. Its digest hashes the complete
canonical envelope bytes, not the bare document. The canonical head has exactly
`{format, version, rev, revision}`, with `format` `campaign-head`, version 1,
matching revision number and object digest, bounded to 512 bytes.

Under the selected state root the layout is `campaigns/UUID/objects/HEX.json`,
`campaigns/UUID/head.json` and `campaigns/UUID/.lock`. Here `UUID` and `HEX`
are syntax placeholders, not runnable fixtures; HEX is the digest without its
prefix. Only head replacement publishes an object. Existing identical object
bytes may be reused; an orphan object is not committed history. Temporary
files are ignored. Readers validate canonical bytes, hashes, identity and
lineage headers; historical walks verify edges, not every declaration transition.

## Identity and edits

Creation requires revision 1, all campaign-owned entities born as `r1:slug`,
and each initial non-null design at revision 1. Campaign-owned IDs are unique
across requirements, work and coordination. A new entity must have its birth
revision equal to the new campaign revision. Retained IDs must stay in the
same array. Once omitted, an old birth ID cannot return in a later revision;
use a new birth ID. Omission changes the current planning window, without
deleting historical snapshots.

Participant UUIDs do not carry birth revisions: a participant may be removed
and reintroduced using the same UUID, subject to all current references being
valid. Participant labels, locators and optional Qargi mappings are editable.
Changing a participant mapping does not move retained work to another UUID.

`campaign` and `continues` are immutable. Retained work keeps `participant`;
retained coordination keeps `dependent` and `upstream`. Labels, objective,
provenance, requirement text/states, work state, requirement links, source,
evidence links, briefing claims and graph pins are otherwise editable within
the schema. No monotonic claim rule is imposed on briefings or states.

An absent design may stay null or start at revision 1. An unchanged design
retains its revision. Any change to a non-null design object, including its
attribution, must advance exactly one design revision; it cannot become null.
Canonical equality with the actual parent is `no-change`, not a new revision.
Pure `check --spec` validates a snapshot only, so past birth or design revisions
can be structurally valid without being valid creation requests.

## Requests, publication and durability

An exact retry repeats the same original spec and original request: `--create`
for creation, or the same original `--expected-head` parent for an update.
If its deterministic candidate is exactly current, the writer settles that
head and returns `result: already-current`. New publication returns
`result: committed`. Both successful results report `publication: visible`
and `durability: fsync-acknowledged`.

A fresh unchanged-spec request using the current head as expected parent is
`no-change`. It is not an exact retry. A stale request whose candidate is no
longer current conflicts, even if that candidate occurs deeper in history.
There is no implicit rebase or automatic retry. Conflicts can report
`current_head`, `candidate` (possibly null), and
`candidate_in_history: not-checked`.

Candidate publication and durability are independent:

- `not-assessed`: candidate selection has not been classified under the lock.
- `none`: the candidate was established as unselected.
- `visible`: the candidate was selected or observed as the selected head.
- `unknown`: a head replacement was attempted and its outcome could not be
  reconciled under the held lock.

Visible or unknown failed commits have candidate `durability: unknown`.
Unselected or unassessed candidates have `durability: not-assessed`.
An unpublished child may separately report `parent_durability: unknown` if
settling the current parent failed. That does not imply child publication.
Replacement errors are reconciled by observation, without repeating the effect
or changing the selected head. `durability-unknown` and `publication-unknown`
are ordinary failures. No visible outcome alone proves durability, and no
uncertain outcome grants acceptance. `fsync-acknowledged` reports successful
syscalls, not physical power-loss or kernel-EIO qualification.

Readers never repair, create, lock or fsync state and report durability as
`not-assessed`. Configured root aliases and trusted ancestors resolve once;
all operations require readable and searchable ancestors through that root.
The root must be effective-user-owned with no group/other write permission.
Descendants use descriptor-relative no-follow access, exact 0700 directories
and effective-user-owned, single-link 0600 regular files. Existing metadata is
unchanged. Missing directories created explicitly are linked durably before
head publication. Writers require directory fsync through ancestors to slash,
including settling earlier uncertain directory links. Traverse-only ancestors
and filesystems lacking directory fsync are unsupported. Failure stages can
include `ancestor-access` and `ancestor-fsync`.

The permanent `.lock` uses nonblocking exclusive flock, with named-versus-held
identity checks. Busy or replaced locks fail; do not remove or replace this
lock as a retry strategy. Cooperating writers are the qualified boundary.

## Bounded history

Each successful historical show or log page independently proves ancestry
from one authoritative selected head snapshot. A cursor carries no proof
credit. Its syntax is `v1:START_HEX:NEXT_HEX` (syntax placeholders only).
The next request verifies head-to-start, start-to-next and page entries under
one total budget of 4096 predecessor edges, charging each traversed edge once.
A concurrent advance selects a new head on the next request and uses budget
to establish the older start's ancestry from it.

Log returns at most 200 small summaries. `complete` means this page reached
revision 1; a cursor's presence does not certify the next object exists or
authenticate page consumption. Exhaustion returns `history-walk-limit`,
`entries: []`, `complete: false`, with no successful partial result.
An existing orphan yields `not-in-history` when the bounded ancestry proof can
establish exclusion; sufficiently distant orphan selection can instead exhaust
that proof and return `history-walk-limit`. Missing requested objects can yield
`not-found`. Current show/check and new commits remain available beyond this
history limit, using at most two distinct objects without a full-history walk.

A conservative historical request bound is 4097 chain objects plus two
candidate lookups: 4099 objects at 262144 bytes each, plus a 512-byte head,
or 1074528768 bytes. Memory retains a constant number of documents and at most
200 summaries. The traced sixteen-large-object fixture and the small
full-depth fixture do not establish ordinary worst-case latency or physical
power-loss/kernel-EIO qualification.

## Reports and diagnostics

Machine reports have `format: campaign-report`, `version: 1`, `command`,
`valid`, `campaign`, `revision`, `findings`, `constants`, and `durability`.
`revision` is null or `{digest, rev, previous}`. Successful show adds `document`,
`selected_head`, `selected_start`, and
`verified_scope: selected-head-ancestry`. Successful log includes `selected_head`
and the same `verified_scope`; its revision and findings describe the selected
head, while `entries`, `selected_start`, `cursor` and `complete` describe its
historical page. Check adds `transition: not-checked` for pure input. Successful
stored check adds `selected_head` and `transition: checked-create` at revision 1
or `checked-current-parent` otherwise. Commit adds the result/publication fields
described above. Failure reports have `valid: false`, null revision and an error
finding; additional fields such as stage, conflict or parent durability appear
only when applicable.

Findings have `code`, `severity`, `message` and, when applicable, `path` or
warning `entity`. When an error supplies a path, the failure report also has
that optional top-level `path`. Validation is first-error, with child paths
rooted at `$` and invalid-parent paths at `$parent`. Warnings are deterministic
and do not invalidate a report: `requirement-uncovered`, `brief-claim-missing`,
`brief-claim-behind`, `coordination-target-withdrawn`.

Declaration error codes are `invalid-json`, `duplicate-json-key`, `schema`,
`version`, `bounds`, `identity`, `reference`, `graph-pin`, `transition`,
`no-change`. State/input failures additionally include `identity-mismatch`,
`lead-only`, `not-found`, `conflict`, `lock-busy`, `lock-replaced`,
`private-state`, `corrupt-store`, `storage-error`, `durability-unknown`,
`publication-unknown`, `history-walk-limit`, `not-in-history`, `cursor`.
Diagnostics use fixed safe text and never interpolate supplied free text.

Authority constants are `authority: declarations-only`,
`source_observation: not-performed`, `acceptance: not-recorded`,
`invalidation_policy: undecided`, `measurements: not-computed`, and
`merge_review: fresh review against the actual dependency required; not enforced here`.
`coordination_scope` is `supplied-document` for pure checks, otherwise
`local-store`. Text output is a safe ASCII summary of identifiers, outcomes,
finding codes/paths, log entries and selected authority constants. It omits
the declaration, finding messages, warning entities, measurements and merge
review constant; use native JSON for the full machine fields.

## Executable external-only example

Save this complete declaration as `campaign.json`. These UUIDs and references
are concrete fictional fixture values, not syntax placeholders. It requires
no registered Qargi project or adoption. Every schema field is present, with
an initial design revision of 1:

```json
{
  "format": "campaign",
  "version": 1,
  "campaign": "11111111-1111-4111-8111-111111111111",
  "label": "External interface preparation",
  "objective": "Prepare against a provisional external interface.",
  "continues": null,
  "participants": [
    {
      "id": "22222222-2222-4222-8222-222222222222",
      "label": "External project",
      "locator": "external-project",
      "qargi_project": null
    }
  ],
  "requirements": [
    {
      "id": "r1:interface",
      "text": "Review the actual interface before acceptance.",
      "state": "active"
    }
  ],
  "work": [
    {
      "id": "r1:prepare",
      "participant": "22222222-2222-4222-8222-222222222222",
      "state": "active",
      "requirements": [
        "r1:interface"
      ],
      "source": {
        "kind": "external",
        "ref": "external-project/interface",
        "pin": null
      },
      "design": {
        "rev": 1,
        "state": "provisional",
        "ref": "design/interface-v1",
        "by": "Example lead",
        "at": "2026-11-15"
      },
      "links": []
    }
  ],
  "coordination": [],
  "provenance": {
    "by": "Example lead",
    "at": "2026-11-15",
    "basis": "Supplied external planning brief"
  }
}
```

Run from a writable example directory as a lead, using Qargi's selected private
state root on a qualified filesystem. The member-safe pure check comes first.
Keep the captured original parent for the update retry:

```sh
campaign=11111111-1111-4111-8111-111111111111
qargi campaign check --spec campaign.json --json
qargi campaign commit "$campaign" --spec campaign.json \
  --create --json > created.json
qargi campaign commit "$campaign" --spec campaign.json \
  --create --json > create-retry.json
qargi campaign show "$campaign" --json > shown.json
parent=$(jq -r '.revision.digest' created.json)
jq '.work[0].design.rev = 2 |
    .work[0].design.ref = "design/interface-v2"' \
  campaign.json > changed.json
qargi campaign commit "$campaign" --spec changed.json \
  --expected-head "$parent" --json > updated.json
qargi campaign commit "$campaign" --spec changed.json \
  --expected-head "$parent" --json > update-retry.json
```

Both retry files report `already-current`; the update is revision 2. None of
these declarations proves the external interface or its delivery was observed.
