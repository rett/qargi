# Lead seat v1 (Wave 0 contract)

This page is the normative contract of the lead seat, phase 1 of the lead handoff. It is written
before the code. **Nothing on this page is built**: no seat verb, record, refusal code or exit
status 77 exists in qargi yet. `tests/test_seat_contract.py` holds one skipped test per rule, so the
seat can be built against the rules one at a time. What exists today (the per-feature lease,
release and take, the owner's takeover, the handoff note and `marshal claim --as-successor-of`) is
described in [Feature marshal](../flow/marshal.md) and stays as it is for a project without a seat.

This is revision 2 of the page. It takes in the changes that the review of revision 1 required;
[Trace to the review](#trace-to-the-review) maps each of them to its rules.

How to read it:

- A rule is a paragraph that starts with its number, **R1** to **R101**. The numbers are this page's
  own and they are stable: a rule added in a later revision takes the next number and stands in the
  section of its subject, so the numbers are not in page order, and a rule that is dropped keeps
  its number in a paragraph that starts `**Rn** (withdrawn)`. Each rule ends with its refusal: the
  code a violation is refused with and its exit status, or `none` where the rule binds qargi's own
  output and a violation is a defect.
- A rule marked as open (`[OPEN O4]`, for example) states what this page proposes where the design
  leaves a choice or two inputs disagree. [Open points](#open-points) lists every one with its
  alternatives and their cost, and says who decides it when that is not the lead. An open rule is
  not settled until then. [Decided points](#decided-points) lists the points that were open in an
  earlier revision and are decided, each with the rule that states the decision.
- A refusal has one of two classes. A **lead refusal** exits 77 and tells a session that it may not
  act as the lead now. A **door refusal** exits 1 and tells the caller of an authority-side verb that
  its input or the state does not allow the step. Both print the refusal line of R65.
- A rule says what it guarantees and against whom where that is not plain. Qargi's code on the lead
  side runs in the lead's own process, so a check it makes is a guard rail: it stops a lead that does
  what it should not by habit, by an old instruction or by confusion, and it does not stop a lead
  that works round it. The gate (R51 to R64, R67 to R69), the outside proof of `qargi host` (R33), R76
  and R77 are guard rails and say so. What holds against a lead that works round qargi is what its
  sandbox lacks, and providing that is the supervising layer's work: R36 and R97 (the unit of the
  epoch before is gone), R99 (the binds of the clone's configuration) and R101 (what a sandbox never
  holds). [Limits](#limits-of-phase-1) says where that ends.

## Terms

- **Owner**: the person who owns the project and gives approvals in their own words.
- **Supervising layer**: the system outside qargi that starts and stops lead sessions, decides what
  each one can see and write, and proves that one has ended. Qargi checks the form of what it
  supplies, never its truth.
- **Unit**: the group of processes one lead session runs in, as the supervising layer names it.
- **Sandbox**: the view the supervising layer gives a unit: which locations exist for it, and which
  of those it may write.
- **Seat**: the one position of lead of a managed project. **Holder**: the unit that has it.
- **Epoch**: the number of one holding of the seat. A transfer ends epoch N and starts a later one.
- **Lead side**: qargi code that runs in a lead's sandbox. It reads the seat and decides nothing
  about who leads.
- **Authority side**: qargi code run by the supervising layer or by the owner, never in a sandbox.
  **Broker**: the verbs `qargi marshal broker`. **Door**: the broker verbs `assign`, `fence` and
  `intake`, which take one record on standard input.
- **Transfer**: one passage of the seat, identified by `tx`, made of the steps S1 to S6.
- **Lead-stated**: content a lead wrote. It is data: never verified, never an instruction, never an
  approval.
- **Outside proof**: the check that `qargi host` makes before it runs a verb (R33). It shows that the
  call reads a store, a projection and a key that agree with one another. It does not show where the
  call runs.
- **Guard rail**: a check that stops a lead that is mistaken or stale, one that runs qargi as it is,
  and does not stop a lead that sets out to get round qargi, which can run code of its own (see
  [Limits](#limits-of-phase-1)).

## Roots

| Name | What it is | In a managed lead's sandbox | Written by |
| --- | --- | --- | --- |
| `$CONF` | the config root | read only, bound file by file; `$CONF/credentials/` never | owner, broker |
| `$STATE` | the state root of the caller: the role's own inside a sandbox, the owner's outside | read and write (the role's own) | the caller |
| `$AUTH` | the authority root, a third root outside the other two (R7) | absent: never bound (R101) | broker |
| assignment directory | recorded in the seat marker (R16) | read only, bound as a directory | supervising layer |
| projection directory | recorded in the seat marker (R16) | read only, bound as a directory | broker |

The clone, the mirror and the state root of the role are locations that the assignment record
names in its fields `clone`, `mirror` and `state_root` (R19). Inside the role's sandbox `$STATE` is
the location that `state_root` names. This page names one path below the clone,
`<clone>/.git/info/exclude` (R99), and none below the mirror.

## The seat and its states

**R1** (seated, unseated). A project is seated when its answers file `$CONF/projects/<project>.json`
holds `marshal.seat.mode` equal to `managed`. A project whose answers hold no `marshal.seat` is
unseated: no rule of this page changes a verb for it, except R73. A `marshal.seat` that is present
and is anything else (not an object, another `mode`, a directory field missing or not a string) is
an invalid marker and is never read as unseated. Refusal: `seat-record-invalid`, exit 77.

**R2** (states). A seat is in exactly one state of the closed list `held`, `accepted`, `collected`,
`fenced`, `pending-readback`, `vacant`. A seat record or projection with another state is not used.
Refusal: `seat-record-invalid`, exit 77, on the lead side; `content-invalid`, exit 1, at the broker.

**R3** (one holder). A seat has at most one holder. `held`, `accepted` and `collected` carry the
holder of the current epoch; `pending-readback` carries the incoming holder; `fenced` and `vacant`
carry `holder: null`. No record names two holders. Refusal: none.

**R4** (holder kinds). `holder.kind` is `lead` or `caretaker`, a closed list. Refusal:
`assignment-invalid`, exit 1, for an assignment that asks for another kind.

**R5** (epoch) `[OPEN O12]`. `epoch` is a positive integer. The first assignment of a project names
epoch 1. Every later assignment names the epoch one above the highest epoch that an accepted
assignment of the project has named, so an epoch number is never used twice. The seat's `epoch` is
N from S1 to S4 of a transfer and becomes the new epoch at S5. Refusal: `assignment-invalid`,
exit 1, for an assignment that names another epoch.

**R6** (no lapse). A seat does not lapse with time. No gate decision of this page reads a clock, a
lease length or the age of a record; only a step of a transfer changes who holds the seat. Refusal:
none.

## Records and where they live

**R7** (authority root). The authority store is a third root, outside the state root and the config
root, and `$AUTH` is its path. `$AUTH` is resolved by the first of these cases that holds, tried in
this order:

1. `QARGI_AUTH` is set: its value.
2. The run is a dev run: the dev data root's path with the suffix `-authority-dev`.
3. `QARGI_HOME` is set: its value with the suffix `-authority`.
4. `QARGI_STATE` or `QARGI_CONF` is set: there is no default.
5. Otherwise: the default data root's path with the suffix `-authority`.

The dev run is tried before case 4: when `QARGI_STATE` is set, the run is first asked whether it is
a dev run, and only a run that is not one is left without a default.
[Running a branch checkout](../install-and-upgrade/README.md#running-a-branch-checkout) says what a
dev run is today: a checkout other than the installed one, run with none of `QARGI_HOME`,
`QARGI_CONF` and `QARGI_STATE` set. As long as that holds, case 2 and case 4 never hold together,
and the order decides only where that definition changes. The store of a dev run lies in the
checkout, beside the dev data root, so the repository's `.gitignore` lists `.qargi-authority-dev`
and git never offers that store for a commit. Resolving a root creates nothing. Refusal:
`authority-store-unsafe`, exit 1, from every authority-side verb when there is no default.

**R8** (authority root is apart). `$AUTH` is never equal to or below `$STATE`, `$CONF` or the data
root, is a directory of mode 700 owned by the effective user, and holds directories of mode 700 and
regular files of mode 600 only. `qargi export` never includes it. A store that passes this check
may be opened; the check does not show that the caller is outside a sandbox, and nor does the outside
proof (R33 says what that proof shows). Refusal: `authority-store-unsafe`, exit 1; nothing is read
from or written to a store that fails the check.

**R9** (store layout). The authority store of a project holds exactly: `$AUTH/<project>/seat.json`
(R11), `$AUTH/<project>/history.jsonl` (R14), `$AUTH/<project>/assign/<n>.json` and
`$AUTH/<project>/fence/<n>.json` (the accepted door records, numbered by epoch), and per transfer
`$AUTH/<project>/tx/<tx>/state.json`, `$AUTH/<project>/tx/<tx>/note.json`,
`$AUTH/<project>/tx/<tx>/note.txt`, `$AUTH/<project>/tx/<tx>/note.sig`,
`$AUTH/<project>/tx/<tx>/readback-<k>.json` and `$AUTH/<project>/tx/<tx>/result-<k>.json`, and
where runs were archived `$AUTH/<project>/tx/<tx>/orphans/` with `manifest.json` and one archive
file for each run (R91). Beside the projects it holds `$AUTH/audit-host.log` (R15),
`$AUTH/credentials/broker_ed25519` and `$AUTH/signers`. The names `$AUTH/<project>/delegations/`
and `$AUTH/<project>/dormancy.json` are reserved and not created. `<tx>` has the form
`tx-<UTC time>-<four hex digits>`, and `<k>` is the number of a compared read-back, 1 to 3 (R39).
Refusal: none.

**R10** (who writes the store). Only the broker and `qargi host` write below `$AUTH`. Lead-side code
never opens `$AUTH`: every lead-side verb gives the same result with `$AUTH` absent. Refusal: none.

**R11** (seat record). `$AUTH/<project>/seat.json` is one JSON object with exactly these fields.
The broker is the only writer of every one of them. The file is a regular file of mode 600 in a
directory of mode 700 (R8) and is written as R12 says.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | string | `qargi.lead-seat/1` |
| `project` | string | the project's name |
| `rev` | integer | 1 at the first write, one more at every write |
| `epoch` | integer | the current epoch (R5) |
| `state` | string | one of R2 |
| `holder` | object or null | `{kind, role_name, epoch, runtime, unit, clone, display_id}`, all strings but `epoch` (R3, R4, R25) |
| `tx` | string or null | the open transfer, or the last completed one |
| `step` | string or null | the last step written, `S1` to `S6` |
| `readback` | string | `pending`, `matched` or `waived` |
| `updated_at` | string | UTC time of the write |
| `updated_by` | string | `broker:<run>`, a label of the broker call |

Refusal: `seat-record-invalid`, exit 77, for a seat or projection that does not have this shape.

**R12** (atomic write) `[OPEN O14]`. Every write of the seat record holds an exclusive lock on the
project's store, re-reads the record under it, compares `rev` with the one it decided on, writes a
new file of mode 600 beside the record, flushes it to disk and renames it over the record. A reader
therefore sees the old record or the new one, never a part. Refusal: `seat-changed`, exit 1, when
`rev` moved; nothing is written.

**R13** (order of writes). Every step writes, in this order: its own records (the door copy, the
archive of open runs, the note, the read-back and result, and
`$AUTH/<project>/tx/<tx>/state.json`), then the seat record, then the projection. At init, step S3
writes the seat marker before the seat record. S4 publishes the archive between its seat record and
its projection (R92), and S5 removes the archived run folders before its seat record (R38).
Refusal: none.

**R14** (history). Every change of state appends one line to `$AUTH/<project>/history.jsonl`:
`{at, epoch, tx, from_state, to_state, step, kind, by}`. A line is never changed or removed.
Refusal: none.

**R15** (host audit). Every door call, every step and every `qargi host` call that has passed the
outside proof (R33) appends one line to `$AUTH/audit-host.log`: `{ts, verb, project, tx, epoch,
detail, by}`. A refused door call is recorded too. A `qargi host` call that R33 refuses, at its first
step or by its proof, has no store that it may write to, and records nothing. Refusal: none.

**R16** (seat marker). The marker is the object `marshal.seat` of `$CONF/projects/<project>.json`:
`{"mode": "managed", "assignment_dir": "...", "projection_dir": "..."}`. Only the broker writes it.
`qargi project set` refuses it as it refuses every `marshal.*` key but `marshal.lease_minutes`
today, and `qargi import` never carries it. Refusal: the existing refusal of `project set`, exit 1.

**R17** (the two bound directories) `[OPEN O4]`. Lead-side code takes the assignment directory and
the projection directory from the marker and from nowhere else. An environment variable that names
either is honoured in a dev run only; in any other run it changes nothing. Each is bound at the
same path inside and outside the sandbox, so the marker's value is also where the broker writes.
Refusal: none.

**R18** (record form). Every record of this page is a UTF-8 JSON object with no float, no control
character in a string and no field this page does not name, reserved fields excepted (R22). A
closed list accepts only its values. Size limits: assignment and fence 8 KiB, spool state 16 KiB,
read-back 64 KiB, note text 16 KiB. Refusal: `content-too-large` for a record over its limit,
`assignment-invalid` for an assignment and `content-invalid` for any other record that breaks the
form; all exit 1, and the store is unchanged.

**R19** (assignment). The supervising layer writes `<assignment_dir>/<project>.json` and passes the
same record through the door:

```json
{"schema": "qargi.assignment/1", "project": "example", "role_name": "example-lead",
 "seat_role": "lead", "kind": "transfer", "epoch": 7,
 "to": {"runtime": "runtime-b", "unit": "lead-example.service"},
 "clone": "<clone>", "state_root": "<state_root>", "mirror": "<mirror>", "hidden_tracked": [],
 "managed": true, "sandboxed": true,
 "ordered_by": "owner", "order_ref": "...", "at": "2026-11-20T10:00:00Z"}
```

`seat_role` is `lead` or `caretaker`. `kind` is `init`, `transfer`, `vacate` or `unseat`. `init` and
`transfer` need every field; `vacate` and `unseat` carry no `to`, `clone`, `state_root` or
`hidden_tracked`. `clone` and `state_root` declare what the holder's sandbox can write: its clone
and the state root of its role (R89). `hidden_tracked` lists the tracked paths that a read-only
bind of the supervising layer hides in the clone (R100). `role_name` is kebab-case, at most 64
characters, without `:`. Refusal: `assignment-invalid`, exit 1.

**R20** (fence). A fence is the supervising layer's statement that the unit of an epoch is gone:

```json
{"schema": "qargi.fence/1", "project": "example", "epoch_ended": 6,
 "method": "unit-empty", "unit": "lead-example.service", "pids": [], "child_units": [],
 "proven_at": "2026-11-20T09:59:00Z", "owner_confirmed": false, "evidence_ref": "..."}
```

`method` is `unit-empty`, `process-tree`, `unbound-empty` or `no-unit`. `process-tree` needs
`owner_confirmed: true`. `epoch_ended` is 0 at init. Refusal: `fence-unproven`, exit 1 (R70).

**R21** (projection). The projection is what the lead side reads of the seat: one file,
`<projection_dir>/<project>/projection.json`, replaced by a rename inside that directory at every
step:

```json
{"schema": "qargi.projection/1", "project": "example", "rev": 12, "epoch": 7,
 "state": "pending-readback", "tx": "tx-20261120T095800Z-4b1c",
 "holder": {"kind": "lead", "role_name": "example-lead", "display_id": "example-lead@e7",
            "runtime": "runtime-b", "unit": "lead-example.service", "clone": "<clone>"},
 "readback": "pending",
 "note": {"version": 1, "json": {}, "text": "...", "json_sha256": "...", "text_sha256": "..."},
 "signature": "...", "signers_line": "...", "last_result": null, "delegations": [],
 "written_at": "2026-11-20T10:00:05Z"}
```

`rev` is the `rev` of the seat record that the projection was written from (R11). Every write of
the seat record is followed by a write of the projection (R13), so the two agree in `epoch`, `tx`
and `rev` except while a step is open (R40). The holder has the fields of the seat record's holder
(R11) but `epoch`, which the projection holds once, at its top. It carries `role_name` as well as
`display_id`, because R24 and R56 compare `role_name` field by field. They do not compare
`display_id`: it is `<role_name>@e<epoch>` (R25), so it holds the epoch, which R57 and R58 compare on
their own and which R52 tries after R56. A comparison of display ids would answer `records-disagree`
to a lead of an earlier or a later epoch, and never `previous-epoch` or `projection-stale`.
Refusal: `seat-record-invalid`, exit 77, for a projection that does not have this shape.

**R22** (reserved fields). `delegations` of the projection and `child_units` of the fence are
reserved: phase 1 writes and accepts only the empty list. `actor` of an open run (R82) is reserved:
phase 1 accepts null or a label. Refusal: `content-invalid`, exit 1, for a non-empty reserved list.

## Who holds a seat

**R23** (who may hold). A seat is held only by the unit that an accepted assignment names in
`to.unit`, in the role `lead` or `caretaker`, from the commit of that assignment's transfer (S5)
until the next fence. No verb run in a sandbox makes a unit the holder. Refusal: none.

**R24** (binding). On the lead side a session is the holder when the assignment file bound into its
sandbox and the projection agree on `project`, `role_name`, `unit`, `runtime`, `clone` and `epoch`;
the projection holds each of the six, `project` and `epoch` at its top and the other four in its
holder (R21). The supervising layer establishes the identity by deciding which unit gets that file;
qargi does not authenticate it (see [Limits](#limits-of-phase-1)). Refusal: `records-disagree`,
`previous-epoch` or `projection-stale`, exit 77 (R56 to R58).

**R25** (display id). The holder's display id is `<role_name>@e<epoch>`, derived from the assignment
file and never passed in. It is the lead named in `marshal status`, `marshal handoff` and a run's
record. It is a name, not a credential. Refusal: none.

**R26** (labels do not select the holder). On a seated project `--as`, `QARGI_LEAD`, `QARGI_NESTED`
and the actor label (R94) change no gate answer and no display id. Refusal: none; the gate's answer
without the label stands.

**R27** (only the door changes the holder). On a seated project `marshal claim`, `marshal take` and
`marshal release` change nothing. `marshal takeover`, `forget`, `resign`, `key` and `signers` are
class `owner` (R51). Refusal: `seated-project`, exit 1, for the first three; `not-assigned`,
exit 77, from the gate for the others (R59 to R63).

**R28** (the order is a label). An assignment needs `ordered_by`. The broker trusts its value as
given and does not check who the caller is. Refusal: `assignment-invalid`, exit 1, without it.

## The door and the broker

**R29** (the door). `qargi marshal broker assign`, `fence` and `intake` read one record from
standard input and check its form against this page and against the seat: the project, the epoch
(R5), the closed lists, the fields each kind needs, a fence that names another unit or epoch than
the one that ends, a fence that carries a field of the order. A refused call leaves the store as it
was, apart from its audit line. Refusal: the code of the rule that is broken, exit 1.

**R30** (git from the mirror only). The broker reads git only from the location the assignment
names in `mirror`, with the environment qargi uses for a tree it does not trust, and never runs git
in a clone. Configuration planted in the clone or the mirror runs nothing. Refusal: none.

**R31** (the role's state is the lead's). The broker never writes below a role's state root, the
location that `state_root` of its assignment names, and reads nothing there by path; the one
exception is the archive and removal of run folders while the seat is `fenced` (R91, R92).
Lead-written content reaches it only as a spool envelope through `broker intake`. Refusal: none.

**R32** (spool envelope) `[OPEN O10]`. A lead hands content to the authority side by writing it to a
spool below its `$STATE`, with one of the verbs of R96. The content is preceded by one line
`{"schema": "qargi.spool/1", "project", "epoch", "kind", "sha256", "bytes"}`, with `kind` one of
`state`, `readback`, `caretaker-request`. The supervising layer collects it and passes it to
`broker intake`. Refusal: `content-too-large` over the limit of its kind (R18), `content-invalid`
for a malformed envelope, a digest or length that does not match, or another epoch than the
transfer's; exit 1.

**R96** (the spool-writing verbs). Three lead-side verbs write a spool envelope (R32), each of one
kind, and change nothing else: no record of the project, no run, nothing in the repository.

| Verb | Kind | Run by | Passes |
| --- | --- | --- | --- |
| `marshal seat state --submit FILE` | `state` | the outgoing holder A | where `lead-write` passes, and in `accepted` (R60) |
| `marshal seat readback --submit FILE` | `readback` | the incoming holder B | where `lead-write` passes, and in `pending-readback` (R61) |
| `marshal caretaker request` | `caretaker-request` | a caretaker | where `lead-write` passes, and under a caretaker in `held` (R63) |

Their class is `lead-write`, and each is an exception that passes in the state that asks for its
envelope. So no step waits for an envelope that its writer is refused: S2 takes A's state while
A's other `lead-write` verbs are refused (R34), and S6 takes B's read-back while B's are (R38).
`marshal seat readback --template` stays `always-open` (R51). A verb of this rule creates the
envelope exclusively and without following a link (R88). An envelope written while no step asks
for it is not taken: S2 and S6 take the envelope of the open transfer only (R35, R39). Refusal: the
gate's answer to a `lead-write` verb in every other state, exit 77: among them
`transfer-in-progress` for `marshal seat state --submit` in `collected` and `fenced`, and
`readback-pending` for the two other verbs in `pending-readback`.

**R33** (owner's verbs go through `qargi host`; what the outside proof shows). On a seated project
the owner runs a lead verb as `qargi host VERB ...`, outside every sandbox. A store that passes R8
does not show that the call is outside: a sandboxed lead runs as the same user, can make a
directory of mode 700 and can name it in `QARGI_AUTH`. So before anything else `qargi host` takes
these steps, and it runs the verb only when all of them pass:

1. It refuses when `QARGI_AUTH`, `QARGI_CONF`, `QARGI_HOME` or `QARGI_STATE` is set, or when the
   run is a dev run (R7): it works with the default roots only. The one exception is a test of
   `qargi host` in this repository's own suite, which sets one switch for it (the build names the
   switch). The switch lifts this step and no other, and any caller can set it, so it is no part of
   what the proof shows.
2. `$AUTH` resolves (R7) and passes R8.
3. It makes a payload for this call, with `epoch`, `tx` and `rev` from
   `$AUTH/<project>/seat.json`: `{"v":1,"ns":"qargi-host","project","epoch","tx","rev"}`. It signs
   the payload with the private key file `$AUTH/credentials/broker_ed25519` in the namespace
   `qargi-host` and verifies the signature against the `signers_line` of the project's projection
   (R21). The key tool is given the path of that file and an environment with no `SSH_AUTH_SOCK`,
   and a file that does not hold a private key fails this step: `ssh-keygen -Y sign` answers a
   public key from an agent that holds the private half, and an agent that reaches the caller must
   not stand in for the key file.
4. `$AUTH/<project>/seat.json` and that projection agree in `epoch`, `tx` and `rev`.

A passed proof shows this and no more: the call reads a seat record, a projection and a private key
that agree with one another, and the key matches the signers line of the projection. It does not
show that the call runs outside a sandbox, and no check made by code that the caller runs could.
Step 1 closes the variables and the dev run that qargi itself reads, and nothing else. A caller that
moves the roots by other means gets a proof that passes: `HOME` moves the default roots, and a mount
of its own in a user namespace puts a config, a projection, a key and a store of its own making
where `$CONF` and the default `$AUTH` stand. A caller that runs a patched copy of this code is not
refused at all, by step 1 or by the proof (Limits). So the proof is a guard rail: it refuses a lead
that is mistaken or stale, one that holds no key and made no roots of its own, and it is no fence
against a lead that works round qargi. What holds against that lead is R101: no sandbox holds the
broker's key, an agent that signs with it or a credential that makes an approval effective.

A key that the caller made fails step 3 unless the caller made the projection too, which it can do
only in roots of its own: the signers line is the broker's (R47), R101 keeps the broker's key out of
every sandbox, and no sandbox can write the projection that is bound. A copy of the store that is
behind the projection fails step 4. The signature is made and checked in the same call, by the one
process that holds the payload, and it is never stored; the payload carries no nonce, because
nothing is sent to a second party that a nonce could keep from being replayed. No variable, option
or file stands for a proof that passed. Then `qargi host` appends its audit line (R15), and it runs
the verb only when the proof passed and the append succeeded. Between the seat write and the
projection write of a step the two records differ (R40): `qargi host` is refused until `qargi
marshal broker run` has completed the step. For a verb that names no project (R64) the proof is made
against the seated projects under `$CONF` and passes when it passes for one of them. A verb that
names an unseated project needs no `qargi host` (R53), and `qargi host` does not run it: there is
no projection to prove against. `qargi host` records what was run; it is not a fence. Refusal:
`host-in-sandbox`, exit 1, when step 1 refuses, when a part of the proof fails, when no seated
project is there to prove against or when the audit line cannot be appended; the verb did not run
and nothing was written.

## The handoff protocol

A transfer moves the seat from holder A (epoch N) to holder B (a later epoch). The names this page's
readers may know map to the steps as follows.

| Plain name | Step | What happens |
| --- | --- | --- |
| offer | S1 accept | the order for B is accepted; A may read and may no longer write, its last state for the spool excepted |
| | S2 collect | A's last state is taken from its spool |
| relinquish | S3 fence | A's unit is proven gone; the seat has no holder |
| | S4 note | the note is built from stored facts and signed |
| acquire, new epoch | S5 commit | B is named; B may read and must read back |
| read-back and its check | S6 check | B's read-back is compared; on a match B holds the seat |

**R34** (S1 accept). Needs an accepted assignment of kind `transfer` and a seat in `held`. Writes
the assignment copy, the seat (`accepted`, a new `tx`) and the projection. From the moment the
projection says `accepted`, A's `lead-write` verbs are refused, all but
`marshal seat state --submit` (R60, R96). Refusal: `transfer-in-progress`, exit 77, to A;
`assignment-invalid`, exit 1, to the door.

**R35** (S2 collect). Takes A's spool content of kind `state`, which A wrote with
`marshal seat state --submit` (R96) and which may be empty. Writes the copy, the seat (`collected`)
and the projection. S2 may be skipped: S3 is allowed from `accepted`. Refusal: the refusals of R32.

**R36** (S3 fence). Needs an accepted fence for epoch N. Writes the fence copy, the seat (`fenced`,
`holder: null`) and the projection. The fence comes before the note: S3 runs before S4, S5 and S6,
so A's unit is proven gone before the note is built and before B reads back, and the note cannot go
stale under A. No later step of the transfer runs without it. Refusal: `fence-required`, exit 1,
when S3 or a later step is asked for and no fence was accepted.

**R37** (S4 note). After S3, and after the archive of open runs where there are any (R91), the
broker builds the note (R46) from the store, the mirror's tips and the spool copies, signs it (R47)
and writes the note files, the seat (`fenced`, the note's version), the published archive (R92)
and the projection. Refusal: none.

**R38** (S5 commit). Needs the note. Where runs were archived, its first act is their removal
(R92). Then it writes the seat (`pending-readback`, B as holder, the new epoch,
`readback: pending`) and the projection. B's `read` verbs pass; its `lead-write` verbs are
refused until S6 matches, all but `marshal seat readback --submit` (R61, R96). Refusal:
`readback-pending`, exit 77, to B.

**R39** (S6 check) `[OPEN O14]`. Takes B's read-back from the spool (R48), checks it (R49) and
writes the copy and the result. On a match it writes the seat (`held`, `readback: matched`) and
the projection, and B is the lead. Without a match the seat stays `pending-readback` and B may read
back again, up to three compared read-backs for a transfer: `attempt` of the result counts them,
and a read-back that is refused before the comparison (for its form, its size or another note
version) is not counted. After the third failed comparison the broker takes no further read-back
for the transfer: the seat stays `pending-readback`, and the only way on is a new assignment, as
R42 says for an abort after S5. Refusal: `readback-mismatch`, exit 1, to the broker's caller for a
failed comparison; `readback-exhausted`, exit 1, for a read-back after the third; B sees the
result of R49.

**R40** (interruption and resume). A transfer may stop between any two writes. Each stop leaves the
state of this table, `marshal seat status` names the step that is open, and `qargi marshal broker
run` completes the open step from the records already written. A second `broker run` changes
nothing and exits 0.

| Stopped in | After the step's records, before the seat | After the seat, before the projection |
| --- | --- | --- |
| S1 | seat `held`; A works on | seat `accepted`, projection `held`; A still passes until the projection is written |
| S2 | seat `accepted`; A is refused `transfer-in-progress` (R60) | seat `collected`, projection `accepted`; the same |
| S3 | seat `accepted` or `collected`; A's unit is gone | seat `fenced`, projection one step behind; no session passes `lead-write` |
| S3 at init | marker set, no seat: every gated verb is refused `seat-record-missing` | seat written, no projection: the same |
| S4 | note files written, seat names no note | seat names the note, projection lacks it; `note show` has nothing |
| S5 | no record of its own; run folders partly removed, and the removal is done again (R92) | seat `pending-readback`, projection `fenced` at epoch N; B is refused `projection-stale` |
| S6 | result stored, seat `pending-readback`; B is refused `readback-pending` (R61) | seat `held`, projection `pending-readback`; the same |

Refusal: none for the resume; a stop never lets a session pass that the completed step would refuse,
except in the first row.

**R41** (re-note). When a tip of the mirror or a stored record changes after S4 and before a match,
the broker builds the note again as the next version in the same `tx`. A read-back that names an
earlier version does not match. Refusal: `note-digest-mismatch`, exit 1 (R70).

**R42** (abort). Before S3, `qargi marshal broker abort` returns the seat to `held` with A as the
holder of epoch N. From S3 on it changes nothing: the only way on is a new assignment, with a new
`tx`, the next epoch (R5) and, when S5 ran, a fence for B's unit. Refusal: `abort-after-fence`,
exit 1.

**R43** (one transfer at a time). While S1 or S2 of a transfer is open, a new assignment for the
project is refused, whatever its kind or role. Refusal: `transfer-open`, exit 1.

**R44** (init) `[OPEN O12]`. A project becomes seated by an assignment of kind `init` and a fence
with method `process-tree`, `owner_confirmed: true` and `epoch_ended: 0`. S1 stores the assignment
copy only. S3 writes the marker, then the first seat record, then the first projection. S4, S5 and
S6 follow as in a transfer, and the first holder has epoch 1. Refusal: `fence-unproven`, exit 1,
for another method or without the owner's confirmation.

**R45** (vacate). An assignment of kind `vacate` runs S1 and S3 and leaves the seat `vacant`, with
no holder. A `vacant` seat takes a transfer whose fence has the method `no-unit`. Refusal:
`seat-vacant`, exit 77, to any session that asks the gate of a vacant seat (R62).

**R46** (the note). The note has the schema `qargi.handoff/2` and these fields: `kind`, `project`,
`transfer_id`, `version`, `from` and `to` (`epoch`, `runtime`, `display_id`), `generated_at`,
`where` (`host`, `user`, `clone`, `mirror`), `features` (name, tip read from the mirror, the suite
record's state, `active`), `omitted_features`, `runs` (R82), `uncommitted`, `hidden_tracked`,
`capabilities`, `packs`, `readback_fields`, `lead_stated`, `authority`, `do_not_assume` and
`truncated` (`value`, `dropped_fields`). Active features come first. Everything a lead wrote is
below `lead_stated` or marked unverified. The text form is rendered from the JSON, its first line
names the JSON's digest, and it is at most 16 KiB. Refusal: none.

**R47** (the note is signed). The broker signs `{"v":1,"ns":"qargi-handoff","project",
"transfer_id","version","json_sha256","text_sha256"}` with `$AUTH/credentials/broker_ed25519`. A
signers line may list several namespaces; the broker's own are in `$AUTH/signers`, kept with
`qargi marshal broker signers add|list`. The signers line that the broker writes into the
projection names its key for the namespaces `qargi-handoff` and `qargi-host` (R33).
`marshal note verify` checks the digest of both forms, the signature against the signers line of
the projection, and that `transfer_id` and `version` are the projection's. Refusal:
`note-digest-mismatch` or `note-invalid`, exit 1 (R70).

**R48** (read-back). B states what it believes in a record of schema `qargi.readback/1`:
`{project, transfer_id, note_sha256, epoch, believes}`, where `believes` holds `host`, `user`,
`clone`, `head`, `develop`, `features` (name, tip, status, suite), `open_runs` (R82),
`capabilities_acknowledged`, `skills_seen` and `unresolved`. `marshal seat readback --template`
prints the empty record, and `marshal seat readback --submit FILE` writes the filled one into the
spool (R96). Refusal: `content-invalid` or `content-too-large`, exit 1.

**R49** (check of the read-back). The broker compares the fields the note lists in
`readback_fields` with the note, the mirror's tips and the assignment, and stores a result of
schema `qargi.readback-result/1`: `{transfer_id, attempt, match, checks, stored_unchecked,
checked_at, checked_by}`. A check is `{id, ok, reason}` with `reason` one of `moved-since-note`,
`not-in-note`, `differs-from-mirror`. The projection's `last_result` carries exactly that form: the
lead sees which checks failed and why, never an expected value. The full result stays in the store.
Refusal: `readback-mismatch`, exit 1.

**R50** (seat status). `marshal seat status --json` prints one object of schema
`qargi.seat-status/1`: `{project, seated, epoch, state, step, tx, holder, readback, next_action,
run_by}`, with `holder` as `{kind, display_id, runtime}`. It reads only and is available in every
state. Refusal: none.

## Exclusivity: what a stale or competing lead is refused

**R51** (one gate, four classes). Every verb has one class. `always-open`: `marshal seat status`,
`marshal note show`, `marshal note verify`, `marshal seat readback --template`, help and
completion. `read`: verbs that change nothing. `lead-write`: verbs that change the project's
records, runs or repository, and the three verbs that write a spool envelope (R96). `owner`: verbs
that write below `$CONF`, write the runtime configuration of the clone or write
`<clone>/.git/info/exclude` (R99), and the marshal verbs R27 names. The broker verbs and
`qargi host` are class `host` and are not gated: R8 and R33 decide them. One gate, in the preamble
of every command (R67), applies R53 to R64 to the verb's class before the verb runs. For an
unseated project it starts no process of its own. Refusal: the code of the condition that holds,
exit 77.

**R52** (order of the conditions) `[OPEN O8]`. The conditions R53 to R64 are tried in the order of
their numbers and the first that holds decides. Within a condition the verb's class picks the
answer; from R59 on, class `owner` is always answered `not-assigned`. The codes in order:
`seat-record-invalid`, `seat-record-missing`, `records-disagree`, `previous-epoch`,
`projection-stale`, `transfer-in-progress`, `readback-pending`, `seat-vacant`, `not-assigned`,
`caretaker-denied`, one reserved place (R93), `gate-error`. Refusal: as each condition says.

**R53** (condition 1: unseated). No marker and the answers are readable: every class passes.
Refusal: none.

**R54** (condition 2: answers unreadable or invalid). The answers file cannot be read, is not a
JSON object or holds an invalid marker (R1): `always-open` passes. Refusal:
`seat-record-invalid`, exit 77, for `read`, `lead-write` and `owner`.

**R55** (condition 3: no bound record). The marker is set and the assignment file or the projection
is missing: `always-open` passes. This is what a session left over from before the project was
seated, or any session the supervising layer did not assign, is refused with. Refusal:
`seat-record-missing`, exit 77, for `read`, `lead-write` and `owner`.

**R56** (condition 4: the records disagree) `[OPEN O8]`. The projection carries a holder, and the
assignment file and the projection differ in `project`, `role_name`, `unit`, `runtime` or `clone`
(the last four are fields of the projection's holder, R21): `always-open` passes. This is what a
competing session with another unit's file is refused with.
Where the projection's `holder` is null, in `fenced` and in `vacant`, there is no holder to compare
with: this condition is skipped and a later one answers, R60 in `fenced` and R62 in `vacant`
unless R57 or R58 holds first. Refusal: `records-disagree`, exit 77, for `read`, `lead-write` and
`owner`.

**R57** (condition 5: previous epoch). The assignment file's epoch is below the projection's:
`always-open` passes. This is what a stale lead is refused with after the cutover. Refusal:
`previous-epoch`, exit 77, for `read`, `lead-write` and `owner`.

**R58** (condition 6: projection stale). The assignment file's epoch is above the projection's:
`always-open` and `read` pass. Refusal: `projection-stale`, exit 77, for `lead-write` and `owner`.

**R59** (condition 7: held by a lead). State `held`, holder kind `lead`, same epoch: `always-open`,
`read` and `lead-write` pass. Refusal: `not-assigned`, exit 77, for `owner`.

**R60** (condition 8: transfer open). State `accepted`, `collected` or `fenced`: `always-open` and
`read` pass; of the `lead-write` verbs only `marshal seat state --submit` passes, and only in
`accepted` (R96). Refusal: `transfer-in-progress`, exit 77, for every other `lead-write` verb;
`not-assigned` for `owner`.

**R61** (condition 9: read-back pending). State `pending-readback`: `always-open` and `read` pass;
of the `lead-write` verbs only `marshal seat readback --submit` passes (R96). Refusal:
`readback-pending`, exit 77, for every other `lead-write` verb; `not-assigned` for `owner`.

**R62** (condition 10: vacant). State `vacant`: `always-open` passes. Refusal: `seat-vacant`,
exit 77, for `read` and `lead-write`; `not-assigned` for `owner`.

**R63** (condition 11: held by a caretaker). State `held`, holder kind `caretaker`: `always-open`
and `read` pass; of the `lead-write` verbs only `env check`, `doctor`, `packs check` and
`marshal caretaker request` pass, the exceptions of the caretaker's row in R98. Refusal:
`not-assigned`, exit 77, for `owner`, tried first; `caretaker-denied`, exit 77, for every other
`lead-write` verb.

**R64** (condition 12: no project named) `[OPEN O17]`. R53 to R63 are about the project that a verb
names; a verb that names none is answered by this condition alone. Where some project under `$CONF`
is seated, `always-open`, `read` and `lead-write` pass and class `owner` is refused. The gate does
not ask whether it runs in a sandbox: nothing that a sandboxed session can set or make shows where
it runs, so whether a project is seated decides. The refusal therefore also meets the owner outside
every sandbox, who runs such a verb as `qargi host VERB ...` (R33); `qargi host` is not gated
(R51). An answers file under `$CONF` that cannot be read or holds an invalid marker counts as
seated here (R1, R87). Where no project under `$CONF` is seated, every class passes, as on an
unseated project (R53). Refusal: `not-assigned`, exit 77, for `owner`.

**R98** (derived classes). A derived class is a kind of session that is answered as the lead is,
less what its row takes away. The description of the commands (`lib/commands.py`) carries one row
for each derived class, `(class, base rule, exceptions)`, and the gate takes what a derived class
may run from that row and from nowhere else.

| Derived class | Base rule | Exceptions |
| --- | --- | --- |
| `caretaker` | `always-open` and `read` as for a lead; every `lead-write` verb is refused `caretaker-denied` | `env check`, `doctor`, `packs check`, `marshal caretaker request` |
| `coordinator` | reserved: phase 1 has no such session and reads no such row | none |

R63 is the caretaker's row applied. The coordinator's row is reserved, as its codes and its
assignment values are (R93): no assignment selects it and the gate raises nothing from it.
Refusal: `caretaker-denied`, exit 77, as R63 says; none for the reserved row.

**R65** (refusal line) `[OPEN O16]`. Every lead refusal and every door refusal prints, on standard error, one
line that starts with `qargi-refusal/1 ` followed by one JSON object on the same line, at most
4 KiB: `{code, exit, verb, project, role, epoch, state, tx, detail}`, null where unknown. `detail`
is qargi's own text: text a lead wrote never enters it, only a digest or a field name. The line may
be any line of standard error. Refusal: none.

**R66** (exit statuses). 0 done, 1 refused, 2 usage, 3 remote not checked, 70 a defect, 77 a lead
refusal. A verb that runs another verb and gets 77 exits 77 and passes the refusal line on.
Refusal: none.

**R67** (the preamble decides). The first field that `lib/help.py` prints for the preamble of
`bin/qargi` is `ok`, `refused` or `usage`. On `refused` the refusal line is already on standard
error and `bin/qargi` exits 77; on `usage` it exits 2. No answer, another first field, or a gate
that fails in any way (it exits 1, 4, 70, 127 or 137, is absent or runs out of time) is a refusal
too. Refusal: `gate-error`, exit 77.

**R68** (what is not gated). The run-event hooks, help, completion, the guard's own entry and
`campaign check --spec` are not gated. The `--json` wrapper is gated by the run it wraps; every
other `campaign` verb is gated before it starts. Refusal: none.

**R69** (the store checks again). On a seated project a write of a per-feature record reads the
projection again inside the feature's lock and applies the gate's answer to it, so a transfer that
began after the preamble is not written past. Refusal: the gate's code, exit 77.

**R70** (door refusals) `[OPEN O11]`. The exit-1 codes are a closed list. Each is raised as this
table says and prints the line of R65.

| Code | Raised when |
| --- | --- |
| `seated-project` | `marshal claim`, `take` or `release` on a seated project (R27) |
| `assignment-invalid` | an assignment breaks R4, R5, R18, R19 or R28, names a reserved value (R93), or declares or names a path that R89 refuses |
| `transfer-open` | a new assignment while S1 or S2 is open (R43) |
| `abort-after-fence` | `broker abort` from S3 on (R42) |
| `fence-required` | S3 or a later step without an accepted fence (R36) |
| `fence-unproven` | a fence that does not prove the end of this epoch: another unit or `epoch_ended`, a method the transition does not allow, `process-tree` without `owner_confirmed`, a non-empty `pids` (R20, R29) |
| `readback-mismatch` | S6 with a failed check (R49) |
| `readback-exhausted` | a read-back after the third failed comparison of a transfer (R39) |
| `note-digest-mismatch` | a digest of the note differs from the recorded one, or a read-back names another note version (R41, R47) |
| `note-invalid` | the note's signature does not verify, or its `transfer_id` or `version` is not the projection's (R47) |
| `seat-changed` | `rev` moved under a write (R12) |
| `refs-backend-active` | `marshal enable` on a seated project; `init` on a project whose shared backend is on (R74) |
| `approval-refused` | `--approved` on a seated project in a verb that no `qargi host` call with a passed proof runs (R76) |
| `authority-store-unsafe` | `$AUTH` has no default or fails R8; a marker or a root is a path that R89 refuses; a root fails the owner-only check of R88 |
| `content-too-large` | a record over its limit (R18) |
| `content-invalid` | a record other than an assignment breaks R18, R22 or R32 |
| `symlink-refused` | a symbolic link in a path of R88 |
| `caretaker-not-vacant` | a caretaker order while a lead holds the seat (R75) |
| `host-in-sandbox` | `qargi host` that R33 refuses: a variable that names a root is set or the run is a dev run, the outside proof fails, no seated project is there to prove against, or the audit line cannot be appended |
| `member-sandbox-off` | raised by member dispatch; its rule is not part of this page |

Refusal: as the table says, exit 1.

**R71** (per-feature questions are answered by the seat). On a seated project `marshal check` and
the question the flow verbs ask before `feature merge|sync|verify|finish` and `local prepare` are
answered from the projection: `yours` and exit 0 for the holder. `marshal set` and `marshal finish`
pass for the holder. `marshal status` and `marshal handoff` are class `read` and name the holder's
display id. Refusal: the gate's code, exit 77, for anyone else.

**R72** (renewal is a no-op). On a seated project `marshal renew` exits 0 and writes nothing, so
the background renewer of a long verb keeps running and changes no record. `local prepare` records
the holder's display id as the run's lead. Refusal: none.

**R73** (unseated projects fail closed). On an unseated project the marshal question of the flow
verbs and of `local prepare` lets the verb go on only when it exits 0, or exits 3 and the caller
gave the existing override for an unreachable remote (`--assume-unreachable-ok`). Every other
status, among them 70 and 127, stops the verb. Refusal: the verb names the status it got, changes
nothing and exits with a status other than 0.

**R74** (shared backend and seat exclude each other) `[OPEN O13]`. On a seated project
`marshal enable` is refused. A project whose marshal records are on the shared refs backend is not
seated: its `init` is refused until `marshal disable` ran. Refusal: `refs-backend-active`, exit 1.

**R75** (caretaker transitions). A caretaker holds a vacant seat so that the project is looked
after while it has no lead. It asks for the next assignment with `marshal caretaker request
--runtime R [--note FILE]`, which writes a spool envelope of kind `caretaker-request` and changes
no seat. These rows are the only ones; the fence method is the one the supervising layer must
supply.

| Row | From | To | Fence | Steps | Read-back |
| --- | --- | --- | --- | --- | --- |
| C1 | vacant | caretaker | `no-unit` | S1, S3 to S6 | checked |
| C2 | caretaker | lead | `unbound-empty` | S1 to S6 | checked |
| C3 | caretaker | vacant | `unbound-empty` | S1, S3 | none |
| C4 | caretaker | caretaker (restart) | `unit-empty` | S1, S3 to S5 | `waived`: S5 goes to `held` |
| C5 | held by a lead | caretaker | | none | |
| C6 | transfer open | caretaker | | none | |
| C7 | caretaker | unseated | as R86 | as R86 | none |

Refusal: `caretaker-not-vacant`, exit 1, for C5; `transfer-open`, exit 1, for C6, which wins when
both hold.

## What never transfers

**R76** (no approval from inside; a guard rail). On a seated project a verb given `--approved` is
refused before it does anything, unless a `qargi host` call that has passed the outside proof runs
it (R33). The proof decides, not a guess about where the verb runs: typed without `qargi host`, the
verb is refused in the owner's own session too. This guards against a mistake: a lead that types
`--approved` out of habit, on an old instruction or with words it was handed is refused. It does
not guard against a lead that works round qargi. Such a lead can run code of its own, in which this
check is not made, or present roots of its own, in which the proof of R33 passes (Limits), and
then it can give itself an approval. What keeps that lead from acting on the approval is not this
rule but R101 and R89: it holds no key and no credential with which a remote would act, and it can
write only the places that its assignment declares. Refusal: `approval-refused`, exit 1.

**R77** (plan tokens do not cross; a guard rail). `qargi host` computes a plan token over the plan
preceded by a line that only it adds, so a token a lead's plan printed never matches the plan the
owner applies. The owner plans again outside the sandbox. The line is in qargi's code and is no
secret: a lead that computes the token itself, with code of its own, makes one that matches. So
this stops a token that crosses by mistake and not one that is forged; R76 and R101 say what a lead
that works round qargi can reach. Refusal: the existing refusal of a plan token that does not match
the plan, exit 1.

**R78** (nothing that authorizes is carried). The note, the seat record, the projection, the spool
copies and the results hold no approval text, no plan token and no words of the owner. The note
carries `"authority": "none"` and the list of things a successor must not assume. Refusal: none.

**R79** (the owner's words stay with the owner). The record of a release cut, which holds the
owner's words, is written below the owner's `$STATE` by `qargi host`, never below a role's `$STATE`
and never below `$AUTH`. Refusal: none.

## What is preserved

**R80** (a transfer leaves the role's state alone). S1 to S6 change nothing below the role's
`$STATE` but the run folders that R92 removes: the per-feature records with their leases, the
registry of local runs, the suite records and the audit log are byte for byte what they were.
Refusal: none.

**R81** (a lease does not block the successor). A per-feature record that names the previous
holder with a live lease neither refuses the new holder nor has to be taken over: the seat
answers (R71) and the record is rewritten only by the new holder's own verbs. Refusal: none.

**R82** (open runs are carried by name). The note lists every open run of the role as
`{run, feature, state, actor}` and the read-back lists them as `{run, feature, actor}`; `open_runs`
is one of the checked fields (R49). Refusal: `readback-mismatch`, exit 1, for a read-back that
leaves an open run out or names one the note does not have.

**R83** (the evidence of a transfer is kept). No step removes or rewrites an accepted assignment, a
fence, a note version, a read-back or a result. After an unseat the project's store stays, read
only. Refusal: none.

**R84** (the clone is handed over in place). The assignment's `clone` stays the role's across
epochs, and so does its `state_root`. The note lists uncommitted work as lead-stated data, never
verified. It lists the tracked files that a read-only bind hides (`hidden_tracked`) as the
supervising layer's data, copied from the assignment: that list is not lead-stated, and qargi
checks its form, not its truth (R100). A verb that writes below `$CONF`, writes the clone's runtime
configuration or writes `<clone>/.git/info/exclude` (R99) is class `owner`. Refusal:
`not-assigned`, exit 77, from the gate for such a verb (R59 to R63); the owner runs it through
`qargi host`.

**R99** (placeholders are the supervising layer's). The supervising layer binds the clone's runtime
configuration read only, for every epoch. Where the clone lacks a target of such a bind, it makes
an empty placeholder when it creates the clone, outside every sandbox, and it records each
placeholder in `<clone>/.git/info/exclude`, which is bound read only too. Qargi makes no
placeholder and edits that file for no lead: every qargi verb that writes
`<clone>/.git/info/exclude` is class `owner` (R51), and the broker writes nothing below a clone.
Refusal: `not-assigned`, exit 77, from the gate for such a verb (R59 to R63).

**R100** (a hidden tracked copy is an intake item). Where the repository tracks a path that such a
bind covers, the lead sees the bound file and not the tracked copy. The supervising layer lists
every such path in `hidden_tracked` of the assignment, and the note carries the list unchanged
(R84). A change to a hidden tracked copy is neither the lead's to make nor qargi's: it is an intake
item for the owner at the reviewed merge, the step outside this page in which the owner takes the
lead's work in from the mirror. The text form of the note says so for every listed path, and no
seat verb writes a listed path. Refusal: none.

## Conditions of the supervising layer

**R85** (managed at fence time). The marker is written only by S3 of an `init`, after a fence that
states the session from before is stopped and that the owner confirmed it (R44). No other verb sets
it. From that write on, a lead verb without a bound assignment is refused (R55). Refusal:
`fence-required` or `fence-unproven`, exit 1, for an `init` without that fence.

**R86** (the undo is a named owner step). A project is unseated only by an assignment of kind
`unseat` and a fence, through `qargi marshal broker unseat`. The marker is removed last, after its
value is stored in the transfer's records (R90). The verb's output and its audit line say that the
project is unseated and that the refusals of this page no longer apply to it. Nothing else removes
the marker. Refusal: `fence-required`, exit 1, without the fence.

**R87** (never half managed). A project with the marker set is never treated as unseated. A missing
or unreadable assignment file, a missing projection or a partly valid marker never falls back to
the per-feature rules. Refusal: `seat-record-missing` or `seat-record-invalid`, exit 77 (R54, R55).

**R88** (G1: no path is followed through a link) `[OPEN O5]`. No path that a seat verb reads or
writes is followed through a symbolic link. Every open resolves the path one component at a time
relative to a directory descriptor, with no-follow on each component, at the time of use and not
only when the path was recorded. The path of `$CONF`, `$STATE` and `$AUTH` itself is resolved
once, and before anything below it is opened, what it resolves to must pass an owner-only check
as in R8: a directory that the effective user owns and that gives group and others no access. This
table says how for each path.

| Path | Opened by | How no-follow is enforced |
| --- | --- | --- |
| `$CONF/projects/<project>.json` | both sides | each component below `$CONF` is opened no-follow; the file must be regular with one link; the broker writes a new file created exclusively in the same directory descriptor and renames it there |
| `<assignment_dir>/<project>.json` | lead side | the recorded directory is opened from the file system root with no-follow on every component, at every gate; the file is opened no-follow relative to it and must be regular |
| `<projection_dir>/<project>/projection.json` | lead side reads, broker writes | as the assignment directory; the broker creates the new file exclusively and renames it inside the directory descriptor |
| the files below `<projection_dir>/<project>/orphans/<tx>/` (R92) | lead side reads, broker writes | as the projection |
| the spool below `$STATE` | lead side writes | created exclusively and no-follow below `$STATE`; the broker never opens it: it takes the content from standard input (R31) |
| the location in `mirror` | broker | opened from the file system root with no-follow on every component before every use; git then runs on the opened directory |
| `$AUTH/<project>/seat.json` and every other file of R9 | broker | `$AUTH` is checked by R8, then each component below it is opened no-follow; new files are created exclusively and renamed inside the directory descriptor |
| `$AUTH/audit-host.log` | broker, `qargi host` | opened for append with no-follow below `$AUTH` |
| the run folders that R91 archives | broker | the location in `state_root` is opened from the file system root with no-follow on every component, and the folders are walked no-follow below it; a link is stored as a link and never read through |

Refusal: `symlink-refused`, exit 1, on the authority side for a link; `authority-store-unsafe`,
exit 1, on the authority side for a root that fails the owner-only check; `seat-record-invalid`,
exit 77, at the gate for either.

**R89** (G1: nothing a sandbox can write is trusted by path). Authority-side code never reads or
writes a path that has a component a sandbox can write. What a sandbox can write is what the
assignment declares: its `clone` and its `state_root` (R19). The broker refuses the assignment
directory, the projection directory, the mirror, `$AUTH` and `$CONF` when one of them overlaps a
declared location: when it is equal to the `clone` or the `state_root`, lies below one of them or
contains one of them. Who owns a path is not the test: a sandboxed lead runs as the owner's user,
so the owner of a file does not say who could write it. The one thing below a declared location
that authority-side code reads is the run folders of R91, and only while no unit of the role
exists (R31, R97). Refusal: `assignment-invalid`, exit 1, for an assignment that declares or names
such a path; `authority-store-unsafe`, exit 1, for a marker or a root that is such a path.

**R90** (archive before remove). Nothing a seat verb removes is removed before an archive of it
exists and was read back and compared. This page has exactly two removals: the open run folders of
a role after a fence (R91, R92) and the marker at an unseat (R86). Every other record is kept
(R83). Refusal: none; a removal whose archive is absent or does not compare does not happen, and
the step stays open.

**R91** (the archive of open runs) `[OPEN O7]`. After S3 and before the note of S4 the broker
archives every open run folder of the role whose epoch the fence ended: one archive file for each
run, named after the run, and `manifest.json`, below `$AUTH/<project>/tx/<tx>/orphans/`, owner
only. It walks only below the `state_root` of that epoch's assignment, without following a link
(R88): a run that the role's records place anywhere else is listed in the manifest as outside the
state root, and its folder is neither read nor removed. An init ends no epoch and archives nothing.
The size limit is 64 MiB of file content for each run: its files are stored whole, in the byte
order of their paths, as long as their sizes together stay within the limit. The manifest lists
for each run its name, its feature, the number and total size of its files, the number and total
size of the files stored, the digest of the archive file and `cut`, which is true when the limit
left files out. The archive is verified by reading it back against the manifest; after a stop,
`qargi marshal broker run` verifies what is there and writes again what does not verify. Refusal:
none; a run over the limit is archived up to the limit and marked, never skipped, and a run that
cannot be read keeps the step open.

**R92** (orphans are named, published, then removed) `[OPEN O7]`. The note lists every archived run
as a lead-stated orphan, below `lead_stated` (R46), with the digest of its archive file. S4 then
publishes the manifest and the archive files, read only, below
`<projection_dir>/<project>/orphans/<tx>/`, before it writes its projection: each file is created
exclusively and renamed there as the projection is (R88), and is compared with its digest. That is
how the successor reads the archive. Its sandbox has the projection directory; it checks a
published file against the digest in the signed note; and what the file holds is lead-stated data,
which qargi neither runs nor trusts. The gate reads nothing below that directory, and no seat verb
removes a published copy. A run folder is removed only when its archive holds it whole (`cut` is
false), is verified and published, and the note that names it is written. The removal is the first
act of S5, before its seat write (R38). A run that was cut stays where it is, and the note says so.
The successor reconciles its runs from the note and the archive: it adopts or discards each orphan,
and no run is dropped without a line in the note. Refusal: none.

**R97** (no unit of the role between the fence and S5) `[OPEN O7]`. The supervising layer does not
start B's unit before S5 is written. From the fence of S3 until then no unit of the role exists, so
no sandbox can write below the role's state root, and that is the only time in which the broker
reads there (R91) and removes there (R92): the exception that R89 leaves lasts no longer. Qargi
cannot see a unit, so this binds the supervising layer. What qargi does is to finish the archive,
the publication and the removal before the seat write of S5, to name the start of B's unit as the
next action of `marshal seat status` only once S5 is written, and to answer a session that has B's
assignment file before S5 from a projection of the earlier epoch. This rule stands while the
broker makes the archive: if the supervising layer makes it, the broker reads nothing below a
state root and the rule goes (O7). Refusal: `projection-stale`, exit 77 (R58), to a `lead-write`
verb of a unit that was started in that time; none on the authority side.

**R101** (what a sandbox never holds). The supervising layer binds none of these into the sandbox of
a unit, in any epoch: `$AUTH`, with the broker's private key and the signers file below it, and
every copy of that key; an agent socket, or any other service, that holds the broker's key or signs
with it, and any variable or file that names one; and a credential with which a verb that takes
`--approved` makes a remote act: the push credential of the project's remote, the token of a hosting
service, the login of a cloud service. `$CONF/credentials/` is where qargi keeps such files, and it
is never bound (Roots). Qargi cannot see what a sandbox holds, so this binds the supervising layer.
What qargi does is to keep every lead-side verb independent of all of it (R10), to read the key on
the authority side only, and to refuse a `qargi host` call that cannot read the key (R33). This is
the rule that holds against a lead that works round qargi, where R33, R76 and R77 do not (Limits):
a lead that gives itself an approval can then change only what its sandbox can write (R89), cannot
sign as the broker, cannot read the store, and has no credential with which a remote would act on
the approval. Refusal: none; qargi cannot see what a sandbox holds, and a sandbox that holds the key
passes the proof of R33.

## The coordinator's place

**R93** (reserved, refused). Phase 1 has no coordinator. An assignment with `seat_role`
`coordinator` or `kind` `delegate` or `undelegate` is refused. The gate keeps one place for later
codes between `caretaker-denied` and `gate-error` and raises none of them, and the coordinator's
row among the derived classes is reserved in the same way (R98). Refusal: `assignment-invalid`,
exit 1.

**R94** (the actor label is attribution) `[OPEN O15]`. A lead may set an actor label, a string of
the form a lead identity has, to say which of its helpers started a run. It is recorded as `actor`
on the run and in R82. It is lead-stated: it is never an identity, is never compared with the
assignment file, and never makes the gate pass a verb that it refuses without the label. Refusal:
none; the gate's answer without the label stands.

**R95** (a coordinator is the holder to the gate). A helper that coordinates one feature from
inside the lead's session shares its sandbox and its assignment file. The gate answers it as it
answers the holder: phase 1 has no fence against it, no record of what it may do and nothing that
ends with its work. Refusal: none.

## Limits of phase 1

Phase 1 covers one host and one operating-system user. These are limits, not rules: no test can
show them.

- **No authentication of identity.** The holder is whoever the supervising layer gave the
  assignment file. `ordered_by`, the display id, `role_name`, `runtime` and the actor label are
  labels.
- **Fences hold against sandboxed processes only.** A process of the owner's user outside every
  sandbox can write the store, the mirror and the bound records, and can call `qargi host`.
- **The roots are taken as bound.** A session that points the config, state or authority root at
  directories of its own sees what it put there: an unseated project, or a seat, a projection, a key
  and a store of its own making that pass R33. `qargi host` refuses the variables that name a root
  and a dev run (R33), and that closes those variables and nothing else: `HOME` moves the default
  roots too, and the next two limits open the rest. Nothing below the real roots changes by this;
  what the session can change is still what its sandbox lets it write. The gate and the outside
  proof hold for the roots that the supervising layer bound.
- **A sandbox that allows user namespaces lets a process present roots of its own.** A member of a
  runtime that brings a sandbox of its own starts it inside the lead's (the end of this section),
  which needs a lead sandbox that allows user namespaces. A process in such a sandbox can make a
  mount namespace, mount a directory of its own where `$CONF`, the projection directory or the
  default `$AUTH` stands, and run `qargi host` in it. What the call reads is then what the process
  made, its own key included, and the proof of R33 passes. Qargi cannot tell that mount from the
  real one.
- **A lead can run code of its own.** Qargi's code on the lead side, `qargi host` with it, runs in
  the lead's own process. A lead can run a patched copy of it or call a module directly, and so skip
  any check that code makes: the refusal of the variables, the signature of the proof, the gate. No
  rule of this page stops that. This and the limit above are why R33, R76 and R77 are guard rails
  against a mistaken or a stale lead and not against a hostile one; against a hostile lead only what
  its sandbox lacks holds (R101).
- **An unseated project is as before.** Until a project is seated, any session can write its qargi
  records and push; R73 is the only change. Unseating reopens that.
- **Qargi does not stop git.** A lead that runs git itself is limited by what its sandbox mounts and
  by the mirror, not by this page. A lead can edit its own working records; they are lead-stated.
- **The fence is the supervising layer's proof.** Qargi checks its form.
- **The binds are the supervising layer's.** Qargi cannot see what a sandbox holds. R99 and R101
  bind the layer, and a bind that is wrong shows nowhere in qargi: a sandbox that holds the broker's
  key passes the proof of R33 and can sign a note.
- **The conversation does not transfer.** A successor starts from the note.

Excluded from phase 1, plainly:

- another host or another operating-system user for the authority side;
- any authentication of a lead, an order or an approval;
- delegation to a coordinator: the delegation record, a coordinator's own assignment, its gate
  class, `child_units` in a fence;
- dormant projects, and the projection field and door kinds they need;
- message records between leads;
- an outside dispatch broker for members.

Part of the same release but not of this page: the render of a lead's skills, hooks and settings
and its manifest; the capability list of a lead runtime; the choice of the lead runtime from the
seat; `schema` fields on other outputs; a configurable run and temporary root; the rule for a
member's sandbox (`member-sandbox-off`); the split of `release` and `feature finish` around the
mirror, with the owner's reviewed merge and its intake list (R100).

Three lines that the supervising layer's side has in the joint list are not rules of this page.
Where the refusal line stands on standard error is O16. The supervising layer's requirements still
refuse a member of a runtime that brings a sandbox of its own; a later decision lets such a member
start that sandbox inside the lead's, and the rule for it is `member-sandbox-off`, named above.
The outside dispatch broker for members stays the target and is excluded, as the list above says.

## Trace to the design

Revision 5 of the design lists 24 changes. Each maps to the rules it changes, or is outside this
page.

| # | Change | Rules |
| --- | --- | --- |
| 1 | one write order; the epoch is checked against the projection; marker before seat at init | R13, R57, R58, R44 |
| 2 | the bound directories come from the marker; `qargi host` proves it is outside by its audit append | R16, R17, R33: the append stays, and the proof is a signature, since an append also succeeds in a store that the caller made |
| 3 | record shapes written out | R11, R18 to R22, R46 to R50 |
| 4 | gate matrix by class and condition; always-open verbs; `owner` verbs with no project in a sandbox | R51 to R64; R64 asks whether a project is seated, not whether the verb runs in a sandbox |
| 5 | preamble protocol | R67, R68 |
| 6 | no authority default with only the state or config root named; the dev store ignored by git | R7 |
| 7 | build plan | none (not a rule); what its wave 0 has not produced is in [the reconciliation](#reconciliation-with-the-designs-wave-0-task-f) |
| 8 | per-feature verbs on a seated project; the renewer; `local prepare` | R27, R71, R72 |
| 9 | owner hygiene on a role's state | replaced by R90 to R92 and R97 |
| 10 | open runs as objects; the display id | R25, R82 |
| 11 | placeholders, hidden tracked copies, `owner` class for the verbs that write them | R84, R99, R100 |
| 12 | the member sandbox rule | outside this page |
| 13 | a lead runtime's capability line | outside this page |
| 14 | citation of the requirements | none |
| 15 | coordinator reservations, among them the table of derived classes | R22, R93, R98 |
| 16 | `detail` never carries lead text; 4 KiB | R65 |
| 17 | a caretaker restart's S5 goes to `held` | R75 |
| 18 | one abort rule | R42 |
| 19 | dormancy field added later | excluded |
| 20 | status of the decisions | none |
| 21 | the owner plans the cut again; a lead's token never matches | R77, R79 |
| 22 | three lines of the supervising layer in the joint list | O16 and [Limits](#limits-of-phase-1) |
| 23 | the actor label is built outside the seat's waves | R94 |
| 24 | tests added | `tests/test_seat_contract.py` |

The twelve conditions the gate checks are R53 to R64, one rule each `[OPEN O2]`.

The two inputs that follow the check of revision 5 map to R90 to R92 and R97 (archive before
remove) and R88 and R89 (G1). The four conditions for "a seat only for managed projects" map to
R85, R86, R87 and the limit that an unseated project is as before. The three additions to the rule
for the clone in place map to R99 (placeholders), R100 (hidden tracked copies) and R84 (uncommitted
work is lead-stated).

## Trace to the review

The review of revision 1 required a numbered list of changes. Each row maps one of them to the
rules and points it changed.

| # | Required change | Rules and points |
| --- | --- | --- |
| 1 | the proof that `qargi host` is outside every sandbox cannot be made inside one; a verb with no project is judged by whether a project is seated | R33, R64 and R76 rewritten; R8, R15, R21, R27, R47 and R70 follow; O9 decided; O17 new |
| 2 | a recorded path is refused by the clone and the state root that the assignment declares, not by who owns it | R89 rewritten; R19 gains `state_root`; R31, R70, R84 and R88 follow; O6 decided |
| 3 | the verbs that write the spool are named, and each passes in the state that asks for its envelope | R96 new; R32, R34, R35, R38, R40, R48, R51, R60 and R61 follow; O10 narrowed |
| 4 | the archive of open runs stays an open question, the owner's and the supervising layer's; meanwhile no unit of the role runs before S5, the size limit is fixed and the successor has a way to read the archive | R97 new; R91 and R92 rewritten; R9, R13, R37, R38, R40, R88, R89 and R90 follow; O7 kept |
| 5 | rules that the design has and revision 1 lacked: the placeholders and the file that records them, hidden tracked copies, the derived classes, the dev store in `.gitignore` and the order of the cases of R7; change 22 of the design is traced to O16 and Limits | R98, R99 and R100 new; R7, R19, R51, R63, R84 and R93 follow |
| 6 | the authority store is a third root for good, and the fence comes before the note | R7 and R36 state the decisions; O1 and O3 decided |
| 7 | three proposals amended: R56 is skipped for a vacant seat as for a fenced one; the path of a root, resolved once, passes an owner-only check; a small cap on read-backs | R56 (O8), R88 (O5), R39 (O14); R9 and R70 follow; O5, O8 and O14 kept, O11 names the new code |
| 8 | what the design's wave 0 was to produce and has not, with the wave proposed for each | the section that follows; O18 new |

## Reconciliation with the design's wave 0 (task F)

The design's wave 0 is one task, F: it turns the draft contracts of the design's section 3 into
files, and the tasks that build the seat start only when those files are merged. What exists of it
is this page and its test. The rest is not yet produced. The table lists it, says what this page
already fixes of it, and proposes the wave that produces it `[OPEN O18]`.

| Not yet produced | Design | Fixed here by | Proposed wave | Why then |
| --- | --- | --- | --- | --- |
| `docs/reference/lead-seat-records.md` | 3.1, 3.2 | R9, R11, R14 to R16, R19, R20 | wave 0, a second task | it is where the transition table and the module interfaces go, and wave 1 builds against both |
| `docs/reference/lead-seat-projection.md` | 3.8 | R21 | wave 5, with the documentation | a reference page of what the store then writes; until then R21 and the schema file are the contract |
| `docs/reference/lead-refusals.md` | 3.3 to 3.5 | R51 to R70 | wave 5, with the documentation | as above: the lists are in `lib/refusals.json` and the rules are here |
| `docs/reference/handoff-note.md` | 3.6 | R46, R47 | wave 5, with the documentation | as above |
| `docs/reference/lead-readback.md` | 3.7 | R32, R48, R49 | wave 5, with the documentation | as above |
| `docs/reference/lead-render-manifest.md` | 3.9 | nothing: the render is not part of this page | wave 1, with the render | the task that builds the render describes what it prints |
| `lib/refusals.json` | 3.3 | R52, R65, R70 | wave 0, a second task | the reader and the store of wave 1 both take the codes, their exit and their order from it |
| `lib/seat-records.json` | 3.11 | R11, R18 to R22, R32, R46, R48 to R50 | wave 0, a second task | the intake, the read-back check and the store of wave 1 validate records against it |
| the render manifest (3.9) | 3.9 | nothing | wave 0 for its schema, in `lib/seat-records.json`; wave 1 for its page | the render prints it and the read-back check reads it, in two tasks of wave 1 that run side by side |
| the module interfaces (3.11) | 3.11 | nothing: this page names no module | wave 0, a second task | the modules of wave 1 are built side by side against them |
| the full transition table (3.2) | 3.2 | R34 to R45 and R75 state its rows as rules, not as one table | wave 0, a second task | the store of wave 1 implements it, and the review of that store reads it |

The second task of wave 0 comes after the lead has decided the open points that change a list or
a shape (O4, O7, O8, O10, O11, O12 and O14), so that the two files freeze what is settled. The
four pages proposed for wave 5 would say again what rules of this page say. Written with the
documentation, they describe what is built, and nobody has to keep them in step with this page
through the revisions before that.

## Decided points

These points were open in an earlier revision and are decided. Each names the rule that states the
decision, and none is marked in a rule any more.

- **O1** (R7, R8). Decided as alternative B: the authority store is a third root, outside the state
  root and the config root, and a permanent one. This page and its test name `$AUTH` beside
  `$STATE` and `$CONF` as a root. It costs one more root to resolve, to document and to check.
- **O3** (R36). Decided as proposed: the fence comes before the note, and S3 before S4, S5 and S6.
  It costs this: while a read-back fails the project has no lead that may write, until B matches or
  a new assignment is made. It never has two live units.
- **O6** (R19, R89). Decided as the alternative: the assignment names the state root of the role
  (`state_root`), and the broker refuses every recorded path that overlaps the clone or the state
  root that the assignment declares. Who owns a path is not used: it cannot tell a sandbox of the
  same user from the owner. It costs one field in a record that the supervising layer writes.
- **O9** (R33, R64). Decided: a verb that names no project is judged by whether some project under
  `$CONF` is seated, not by a test for a sandbox. Class `owner` is then refused wherever the verb
  runs, and the owner's way is `qargi host`, whose outside proof is the signature of R33. The cost
  is the owner's question O17.

## Open points

Every `[OPEN On]` above is listed here. The lead decides a point alone unless the heading of its
item says who else does.

- **O2** (trace). The task names "the 12 check changes of revision 5". Proposed: the inputs hold no
  list of twelve changes, so this page maps all 24 changes of revision 5 and the two later inputs,
  and states the twelve gate conditions as R53 to R64. Alternative: another list of twelve was
  meant; it costs a second trace table once the list is supplied.
- **O4** (R17). The marker records the two directories as the lead sees them, but the broker writes
  the projection outside the sandbox. Proposed: both sides use the same path. Alternative A: the
  marker records an inside and an outside path for each; it costs two more fields the lead can
  read. Alternative B: the broker is told the outside path on each call; it costs a value that is
  not recorded anywhere. The same question holds for `clone`, `state_root` and `mirror` of the
  assignment, which R89 compares as the broker reaches them; the proposal covers them.
- **O5** (R88). Where no-follow starts. Proposed: at the file system root for a path a record names
  (the two directories, the mirror, the state root), and below the root for `$CONF`, `$STATE` and
  `$AUTH`, whose own path is resolved once and must then pass an owner-only check as in R8.
  Alternative: from the file system root for every path; it costs every host whose home directory
  is reached through a link.
- **O7** (R91, R92, R97; for the owner and the supervising layer, jointly). The archive of open
  runs: who makes it, where, how large, how the successor reads it and how long a published copy
  stays. Proposed: the broker makes it below `$AUTH`, with a limit of 64 MiB for each run;
  publishes it read only below the projection directory, where the successor reads it; removes a
  run folder only when the archive holds it whole; and removes no published copy. R97 then keeps
  every unit of the role away while the broker reads the role's state root, which R89 otherwise
  forbids. Alternative A: the supervising layer archives and hands qargi the manifest; it costs
  qargi the check that the archive exists, and it ends R97 and the exception to R89. Alternative B:
  the successor reads the manifest in the note only, and the owner reads the archive; it costs
  what the supervising layer's input asks for, a successor that reconciles from the archive.
  Alternative C: the supervising layer binds the archive of the transfer read only into the
  successor's sandbox; it costs a bind for each transfer and a path that the lead side has to be
  told, and it saves the copy below the projection directory. Alternative D: a run that was cut is
  removed like the others; it costs the files beyond the limit, against R90. A cost of the
  proposal: lead-written files stand in a directory that the lead side trusts for the projection,
  and they take space there until the owner removes them.
- **O8** (R52, R56, R60 to R63). The design's list of codes puts `not-assigned` after
  `seat-vacant`, but its matrix answers class `owner` with `not-assigned` in every state. Proposed:
  the matrix wins. Alternative: the list wins; it costs an owner verb in a vacant seat the answer
  `seat-vacant`. The matrix also names no answer for a seat without a holder, where R56 has nothing
  to compare; proposed: R56 is skipped in `fenced` and in `vacant` alike, and R60 or R62 answers.
- **O10** (R32, R35, R39, R96; for the lead and the supervising layer). The spool's file names,
  what triggers collection, and the fields of the content of a `state` envelope, which the design
  does not give. Proposed: left to the joint list with the supervising layer; this page fixes the
  envelope, the verbs that write it and where they pass (R96). Alternative: this page fixes one
  file name for each kind and says that the supervising layer collects when the file appears; it
  costs rules about the supervising layer's side that no test of qargi can show.
- **O11** (R70). The design names `fence-required`, `fence-unproven`, `note-invalid`,
  `note-digest-mismatch` and `seat-changed` without saying when each is raised. Proposed: the table
  of R70. Alternative: fewer codes (`fence-unproven` for both fence cases, `note-invalid` for both
  note cases); it costs the caller the difference between "send a fence" and "send a better one".
  The table also has one code that the design lacks, `readback-exhausted` (R39).
- **O12** (R5, R44). Which epoch `vacate` and `unseat` name, whether a number is reused after an
  abort before S3, and what S1 writes at init. Proposed: every accepted assignment takes the next
  number, none is reused, and S1 at init writes the copy only. Alternative: `vacate` and `unseat`
  keep the current epoch and an aborted number is reused; it costs the rule that a number names one
  assignment for good.
- **O13** (R74). Whether the door refuses to seat a project on the shared backend. Proposed: yes,
  with `refs-backend-active`. Alternative: a documented step only (`marshal disable` first); it
  costs a seated project with two sources for who leads.
- **O14** (R12, R19, R39). Details the design does not state: the lock and the flush of R12, mode
  600, what `managed` and `sandboxed` of the assignment mean, how many read-backs B may send, and
  how the store is made read only after an unseat. Proposed: as R12 says, no rule on the two
  booleans, at most three compared read-backs for a transfer (R39), and modes without the write
  bit. Alternative: leave each to the build; it costs a contract that the first reviewer has to
  complete. For the cap alone: a larger number costs B more tries at values it is never shown
  (R49), and no cap costs a transfer that never ends by itself.
- **O15** (R94). The label's name and carrier come from a review, and the label is built outside
  the seat's waves. Proposed: this page fixes what the label is not and leaves its name to that
  task. Alternative: fix `QARGI_ACTOR` and `--actor` here, with the narrowing checks; it costs the
  seat a dependency on work the plan keeps apart.
- **O16** (R65; for the lead and the supervising layer). The supervising layer's requirements say
  the refusal line is the first line of standard error. Proposed: any line, as the design says.
  Alternative: the first line; it costs every verb that prints a warning before it is refused.
- **O17** (R64; for the owner). What it costs to judge a verb with no project by whether a project
  is seated. On a host with one seated project every `owner` verb that names no project is refused
  when it is typed plainly, in the owner's own session too and also when the work is for an
  unseated project. It has to be typed as `qargi host VERB`, which then needs the authority store
  and the projection of a seated project. Proposed: the owner accepts that cost, because no test
  that a sandboxed session cannot defeat tells the two callers apart. Alternative A: a variable
  that the supervising layer sets inside a sandbox; it costs a check the lead can switch off.
  Alternative B: the gate makes the outside proof itself and passes such a verb when it holds; it
  costs lead-side code that opens `$AUTH`, against R10.
- **O18** (the reconciliation with wave 0). Which wave produces what the design's wave 0 was to
  produce and this page does not. Proposed: the table of that section. A second task of wave 0,
  after the lead's decisions on the points that change a list or a shape, produces the two schema
  files and the records page with the transition table and the module interfaces; the page of the
  render manifest comes with the render in wave 1; the four pages that restate rules of this page
  come with the documentation in wave 5. Alternative: the second task of wave 0 produces all eight
  files, as the design planned for its one task; it costs four pages that say again what R21, R46
  to R49 and R51 to R70 say, to be kept in step with this page through every later revision.
