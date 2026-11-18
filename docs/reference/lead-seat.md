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

- A rule is a paragraph that starts with its number, **R1** to **R96**. The numbers are this page's
  own and they are stable: a rule added in a later revision takes the next number and stands in the
  section of its subject, so the numbers are not in page order, and a rule that is dropped keeps
  its number in a paragraph that starts `**Rn** (withdrawn)`. Each rule ends with its refusal: the
  code a violation is refused with and its exit status, or `none` where the rule binds qargi's own
  output and a violation is a defect.
- A rule marked as open (`[OPEN O1]`, for example) states what this page proposes where the design
  leaves a choice or two inputs disagree. [Open points](#open-points) lists every one with its
  alternatives and their cost, and says who decides it when that is not the lead. An open rule is
  not settled until then. [Decided points](#decided-points) lists the points that were open in an
  earlier revision and are decided, each with the rule that states the decision.
- A refusal has one of two classes. A **lead refusal** exits 77 and tells a session that it may not
  act as the lead now. A **door refusal** exits 1 and tells the caller of an authority-side verb that
  its input or the state does not allow the step. Both print the refusal line of R65.

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

## Roots

| Name | What it is | In a managed lead's sandbox | Written by |
| --- | --- | --- | --- |
| `$CONF` | the config root | read only, bound file by file; `$CONF/credentials/` never | owner, broker |
| `$STATE` | the state root of the caller: the role's own inside a sandbox, the owner's outside | read and write (the role's own) | the caller |
| `$AUTH` | the authority root (R7) | absent | broker |
| assignment directory | recorded in the seat marker (R16) | read only, bound as a directory | supervising layer |
| projection directory | recorded in the seat marker (R16) | read only, bound as a directory | broker |

The clone, the mirror and the state root of the role are locations that the assignment record
names in its fields `clone`, `mirror` and `state_root` (R19). Inside the role's sandbox `$STATE` is
the location that `state_root` names. This page names no path below them.

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

**R7** (authority root) `[OPEN O1]`. `$AUTH` is the value of `QARGI_AUTH` when it is set. Otherwise,
in a dev run, it is the dev data root's path with the suffix `-authority-dev`. Otherwise it is the
data root's path (the value of `QARGI_HOME`, else the default data root) with the suffix
`-authority`. When `QARGI_STATE` or `QARGI_CONF` is set and neither `QARGI_AUTH` nor `QARGI_HOME`
is, there is no default. Resolving a root creates nothing. Refusal: `authority-store-unsafe`,
exit 1, from every authority-side verb when there is no default.

**R8** (authority root is apart). `$AUTH` is never equal to or below `$STATE`, `$CONF` or the data
root, is a directory of mode 700 owned by the effective user, and holds directories of mode 700 and
regular files of mode 600 only. `qargi export` never includes it. A store that passes this check
may be opened; the check does not show that the caller is outside a sandbox, which is what R33
proves. Refusal: `authority-store-unsafe`, exit 1; nothing is read from or written to a store that
fails the check.

**R9** (store layout). The authority store of a project holds exactly: `$AUTH/<project>/seat.json`
(R11), `$AUTH/<project>/history.jsonl` (R14), `$AUTH/<project>/assign/<n>.json` and
`$AUTH/<project>/fence/<n>.json` (the accepted door records, numbered by epoch), and per transfer
`$AUTH/<project>/tx/<tx>/state.json`, `$AUTH/<project>/tx/<tx>/note.json`,
`$AUTH/<project>/tx/<tx>/note.txt`, `$AUTH/<project>/tx/<tx>/note.sig`,
`$AUTH/<project>/tx/<tx>/readback-<k>.json` and `$AUTH/<project>/tx/<tx>/result-<k>.json`. Beside
the projects it holds `$AUTH/audit-host.log` (R15), `$AUTH/credentials/broker_ed25519` and
`$AUTH/signers`. The names `$AUTH/<project>/delegations/` and `$AUTH/<project>/dormancy.json` are
reserved and not created. `<tx>` has the form `tx-<UTC time>-<four hex digits>`. Refusal: none.

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
note, the read-back and result, and `$AUTH/<project>/tx/<tx>/state.json`), then the seat record,
then the projection. At init, step S3 writes the seat marker before the seat record. Refusal: none.

**R14** (history). Every change of state appends one line to `$AUTH/<project>/history.jsonl`:
`{at, epoch, tx, from_state, to_state, step, kind, by}`. A line is never changed or removed.
Refusal: none.

**R15** (host audit). Every door call, every step and every `qargi host` call that has passed the
outside proof (R33) appends one line to `$AUTH/audit-host.log`: `{ts, verb, project, tx, epoch,
detail, by}`. A refused door call is recorded too. A `qargi host` call whose proof fails has no
store that it may write to, and records nothing. Refusal: none.

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
and the state root of its role (R89). `role_name` is kebab-case, at most 64 characters, without
`:`. Refusal: `assignment-invalid`, exit 1.

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
 "holder": {"kind": "lead", "display_id": "example-lead@e7", "runtime": "runtime-b",
            "unit": "lead-example.service", "clone": "<clone>"},
 "readback": "pending",
 "note": {"version": 1, "json": {}, "text": "...", "json_sha256": "...", "text_sha256": "..."},
 "signature": "...", "signers_line": "...", "last_result": null, "delegations": [],
 "written_at": "2026-11-20T10:00:05Z"}
```

`rev` is the `rev` of the seat record that the projection was written from (R11). Every write of
the seat record is followed by a write of the projection (R13), so the two agree in `epoch`, `tx`
and `rev` except while a step is open (R40). Refusal: `seat-record-invalid`, exit 77, for a
projection that does not have this shape.

**R22** (reserved fields). `delegations` of the projection and `child_units` of the fence are
reserved: phase 1 writes and accepts only the empty list. `actor` of an open run (R82) is reserved:
phase 1 accepts null or a label. Refusal: `content-invalid`, exit 1, for a non-empty reserved list.

## Who holds a seat

**R23** (who may hold). A seat is held only by the unit that an accepted assignment names in
`to.unit`, in the role `lead` or `caretaker`, from the commit of that assignment's transfer (S5)
until the next fence. No verb run in a sandbox makes a unit the holder. Refusal: none.

**R24** (binding). On the lead side a session is the holder when the assignment file bound into its
sandbox and the projection agree on `project`, `role_name`, `unit`, `runtime`, `clone` and `epoch`.
The supervising layer establishes the identity by deciding which unit gets that file; qargi does not
authenticate it (see [Limits](#limits-of-phase-1)). Refusal: `records-disagree`, `previous-epoch` or
`projection-stale`, exit 77 (R56 to R58).

**R25** (display id). The holder's display id is `<role_name>@e<epoch>`, derived from the assignment
file and never passed in. It is the lead named in `marshal status`, `marshal handoff` and a run's
record. It is a name, not a credential. Refusal: none.

**R26** (labels do not select the holder). On a seated project `--as`, `QARGI_LEAD`, `QARGI_NESTED`
and the actor label (R94) change no gate answer and no display id. Refusal: none; the gate's answer
without the label stands.

**R27** (only the door changes the holder). On a seated project `marshal claim`, `marshal take` and
`marshal release` change nothing. `marshal takeover`, `forget`, `resign`, `key` and `signers` are
class `owner` (R51). Refusal: `seated-project`, exit 1, for the first three; `not-assigned`,
exit 77, for the others inside a sandbox.

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

**R33** (owner's verbs go through `qargi host`; the outside proof). On a seated project the owner
runs a lead verb as `qargi host VERB ...`, outside every sandbox. A store that passes R8 does not
show that the call is outside: a sandboxed lead runs as the same user, can make a directory of
mode 700 and can name it in `QARGI_AUTH`. So before anything else `qargi host` makes the outside
proof, from what no sandbox holds:

1. `$AUTH` resolves (R7) and passes R8.
2. It makes a payload for this call, with `epoch`, `tx` and `rev` from
   `$AUTH/<project>/seat.json` and a random `nonce`:
   `{"v":1,"ns":"qargi-host","project","epoch","tx","rev","nonce"}`. It signs the payload with
   `$AUTH/credentials/broker_ed25519` in the namespace `qargi-host` and verifies the signature
   against the `signers_line` of the project's projection (R21).
3. `$AUTH/<project>/seat.json` and that projection agree in `epoch`, `tx` and `rev`.

A key that the caller made fails step 2: the signers line is the broker's (R47), the broker's key
is in no sandbox, and no sandbox can write the projection. A copy of the store that is behind the
projection fails step 3. The signature is made and checked in the same call. It is never stored,
and no variable, option or file stands for a proof that passed. Then `qargi host` appends its audit
line (R15), and it runs the verb only when the proof passed and the append succeeded. Between the
seat write and the projection write of a step the two records differ (R40): `qargi host` is
refused until `qargi marshal broker run` has completed the step. For a verb that names no project
(R64) the proof is made against the seated projects under `$CONF` and passes when it passes for
one of them. `qargi host` records what was run; it is not a fence. Refusal: `host-in-sandbox`,
exit 1, when a part of the proof fails or no seated project is there to prove against; the verb
did not run and nothing was written.

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

**R36** (S3 fence) `[OPEN O3]`. Needs an accepted fence for epoch N. Writes the fence copy, the
seat (`fenced`, `holder: null`) and the projection. No later step of the transfer runs without it.
Refusal: `fence-required`, exit 1, when S3 or a later step is asked for and no fence was accepted.

**R37** (S4 note). After S3 the broker builds the note (R46) from the store, the mirror's tips and
the spool copies, signs it (R47) and writes the note files, the seat (`fenced`, the note's version)
and the projection. Refusal: none.

**R38** (S5 commit). Needs the note. Writes the seat (`pending-readback`, B as holder, the new
epoch, `readback: pending`) and the projection. B's `read` verbs pass; its `lead-write` verbs are
refused until S6 matches, all but `marshal seat readback --submit` (R61, R96). Refusal:
`readback-pending`, exit 77, to B.

**R39** (S6 check). Takes B's read-back from the spool (R48), checks it (R49) and writes the copy
and the result. On a match it writes the seat (`held`, `readback: matched`) and the projection, and
B is the lead. Without a match the seat stays `pending-readback` and B may read back again.
Refusal: `readback-mismatch`, exit 1, to the broker's caller; B sees the result of R49.

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
| S5 | (no record of its own) | seat `pending-readback`, projection `fenced` at epoch N; B is refused `projection-stale` |
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
that write below `$CONF` or write the runtime configuration of the clone, and the marshal verbs
R27 names. The broker verbs and `qargi host` are class `host` and are not gated: R8 and R33 decide
them. One gate, in the preamble of every command (R67), applies R53 to R64 to the verb's class
before the verb runs. For an unseated project it starts no process of its own. Refusal: the code
of the condition that holds, exit 77.

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

**R56** (condition 4: the records disagree). The assignment file and the projection differ in
`project`, `role_name`, `unit`, `runtime` or `clone`: `always-open` passes. This is what a
competing session with another unit's file is refused with. Refusal: `records-disagree`, exit 77,
for `read`, `lead-write` and `owner`.

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
`marshal caretaker request` pass. Refusal: `not-assigned`, exit 77, for `owner`, tried first;
`caretaker-denied`, exit 77, for every other `lead-write` verb.

**R64** (condition 12: no project named) `[OPEN O17]`. R53 to R63 are about the project that a verb
names; a verb that names none is answered by this condition alone. Where some project under `$CONF`
is seated, `always-open`, `read` and `lead-write` pass and class `owner` is refused. The gate does
not ask whether it runs in a sandbox: nothing that a sandboxed session can set or make shows where
it runs, so whether a project is seated decides. The refusal therefore also meets the owner outside
every sandbox, who runs such a verb as `qargi host VERB ...` (R33); `qargi host` is not gated
(R51). An answers file under `$CONF` that cannot be read or holds an invalid marker counts as
seated here (R1, R87). Where no project under `$CONF` is seated, every class passes, as on an
unseated project (R53). Refusal: `not-assigned`, exit 77, for `owner`.

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
| `note-digest-mismatch` | a digest of the note differs from the recorded one, or a read-back names another note version (R41, R47) |
| `note-invalid` | the note's signature does not verify, or its `transfer_id` or `version` is not the projection's (R47) |
| `seat-changed` | `rev` moved under a write (R12) |
| `refs-backend-active` | `marshal enable` on a seated project; `init` on a project whose shared backend is on (R74) |
| `approval-refused` | `--approved` on a seated project in a verb that no `qargi host` call with a passed proof runs (R76) |
| `authority-store-unsafe` | `$AUTH` has no default or fails R8; a marker or a root is a path that R89 refuses |
| `content-too-large` | a record over its limit (R18) |
| `content-invalid` | a record other than an assignment breaks R18, R22 or R32 |
| `symlink-refused` | a symbolic link in a path of R88 |
| `caretaker-not-vacant` | a caretaker order while a lead holds the seat (R75) |
| `host-in-sandbox` | `qargi host` whose outside proof fails, or that has no seated project to prove against (R33) |
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

**R76** (no approval from inside). On a seated project a verb given `--approved` is refused before
it does anything, unless a `qargi host` call that has passed the outside proof runs it (R33). The
proof decides, not a guess about where the verb runs: typed without `qargi host`, the verb is
refused in the owner's own session too. Refusal: `approval-refused`, exit 1.

**R77** (plan tokens do not cross). `qargi host` computes a plan token over the plan preceded by a
line that only it adds, so a token a lead's plan printed never matches the plan the owner applies.
The owner plans again outside the sandbox. Refusal: the existing refusal of a plan token that does
not match the plan, exit 1.

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
epochs, and so does its `state_root`. The note lists uncommitted work and the tracked files a read-only bind hides
(`hidden_tracked`, from the assignment) as unverified, lead-stated data. A verb that writes below
`$CONF` or writes the clone's runtime configuration is class `owner`. Refusal: `not-assigned`,
exit 77, for such a verb in a sandbox.

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
only when the path was recorded. This table says how for each path.

| Path | Opened by | How no-follow is enforced |
| --- | --- | --- |
| `$CONF/projects/<project>.json` | both sides | each component below `$CONF` is opened no-follow; the file must be regular with one link; the broker writes a new file created exclusively in the same directory descriptor and renames it there |
| `<assignment_dir>/<project>.json` | lead side | the recorded directory is opened from the file system root with no-follow on every component, at every gate; the file is opened no-follow relative to it and must be regular |
| `<projection_dir>/<project>/projection.json` | lead side reads, broker writes | as the assignment directory; the broker creates the new file exclusively and renames it inside the directory descriptor |
| the spool below `$STATE` | lead side writes | created exclusively and no-follow below `$STATE`; the broker never opens it: it takes the content from standard input (R31) |
| the location in `mirror` | broker | opened from the file system root with no-follow on every component before every use; git then runs on the opened directory |
| `$AUTH/<project>/seat.json` and every other file of R9 | broker | `$AUTH` is checked by R8, then each component below it is opened no-follow; new files are created exclusively and renamed inside the directory descriptor |
| `$AUTH/audit-host.log` | broker, `qargi host` | opened for append with no-follow below `$AUTH` |
| the run folders that R91 archives | broker | the location in `state_root` is opened from the file system root with no-follow on every component, and the folders are walked no-follow below it; a link is stored as a link and never read through |

Refusal: `symlink-refused`, exit 1, on the authority side; `seat-record-invalid`, exit 77, at the
gate.

**R89** (G1: nothing a sandbox can write is trusted by path). Authority-side code never reads or
writes a path that has a component a sandbox can write. What a sandbox can write is what the
assignment declares: its `clone` and its `state_root` (R19). The broker refuses the assignment
directory, the projection directory, the mirror, `$AUTH` and `$CONF` when one of them overlaps a
declared location: when it is equal to the `clone` or the `state_root`, lies below one of them or
contains one of them. Who owns a path is not the test: a sandboxed lead runs as the owner's user,
so the owner of a file does not say who could write it. The one thing below a declared location
that authority-side code reads is the run folders of R91, and only while the seat is `fenced`
(R31). Refusal: `assignment-invalid`, exit 1, for an assignment that declares or names such a
path; `authority-store-unsafe`, exit 1, for a marker or a root that is such a path.

**R90** (archive before remove). Nothing a seat verb removes is removed before an archive of it
exists and was read back and compared. This page has exactly two removals: the open run folders of
a role after a fence (R91) and the marker at an unseat (R86). Every other record is kept (R83).
Refusal: none; a removal whose archive is absent or does not compare does not happen, and the step
stays open.

**R91** (the archive of open runs) `[OPEN O7]`. After S3 and before S4 the broker archives every
open run folder of the role: one archive file per run and one manifest, below
`$AUTH/<project>/tx/<tx>/orphans/`, owner only. The manifest lists per run its name, feature, the
number and total size of its files, the digest of the archive file and whether a size limit cut it
short. The archive is verified by reading it back against the manifest. Refusal: none; a run over
the size limit is archived up to the limit and marked, never skipped, and a run that cannot be read
keeps the step open.

**R92** (orphans are named, then removed). The note lists every archived run as a lead-stated
orphan (R46). A run folder is removed only after its archive is verified and the note that names it
is written. The successor reconciles its runs from the note and the archive: it adopts or discards
each orphan, and no run is dropped without a line in the note. Refusal: none.

## The coordinator's place

**R93** (reserved, refused). Phase 1 has no coordinator. An assignment with `seat_role`
`coordinator` or `kind` `delegate` or `undelegate` is refused. The gate keeps one place for later
codes between `caretaker-denied` and `gate-error` and raises none of them. Refusal:
`assignment-invalid`, exit 1.

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
  directories of its own sees what it put there: an unseated project, or a seat and a store of its
  own making that pass R33. Nothing below the real roots changes by that; what the session can
  change is still what its sandbox lets it write. The gate and the outside proof hold for the roots
  that the supervising layer bound.
- **An unseated project is as before.** Until a project is seated, any session can write its qargi
  records and push; R73 is the only change. Unseating reopens that.
- **Qargi does not stop git.** A lead that runs git itself is limited by what its sandbox mounts and
  by the mirror, not by this page. A lead can edit its own working records; they are lead-stated.
- **The fence is the supervising layer's proof.** Qargi checks its form.
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
mirror.

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
| 6 | no authority default with only the state or config root named | R7 |
| 7 | build plan | none (not a rule) |
| 8 | per-feature verbs on a seated project; the renewer; `local prepare` | R27, R71, R72 |
| 9 | owner hygiene on a role's state | replaced by R90 to R92 |
| 10 | open runs as objects; the display id | R25, R82 |
| 11 | placeholders, hidden tracked copies, `owner` class for the verbs that write them | R84 |
| 12 | the member sandbox rule | outside this page |
| 13 | a lead runtime's capability line | outside this page |
| 14 | citation of the requirements | none |
| 15 | coordinator reservations | R22, R93 |
| 16 | `detail` never carries lead text; 4 KiB | R65 |
| 17 | a caretaker restart's S5 goes to `held` | R75 |
| 18 | one abort rule | R42 |
| 19 | dormancy field added later | excluded |
| 20 | status of the decisions | none |
| 21 | the owner plans the cut again; a lead's token never matches | R77, R79 |
| 22 | three lines of the supervising layer in the joint list | O10 |
| 23 | the actor label is built outside the seat's waves | R94 |
| 24 | tests added | `tests/test_seat_contract.py` |

The twelve conditions the gate checks are R53 to R64, one rule each `[OPEN O2]`.

The two inputs that follow the check of revision 5 map to R90 to R92 (archive before remove) and
R88 and R89 (G1). The four conditions for "a seat only for managed projects" map to R85, R86, R87
and the third limit above.

## Trace to the review

The review of revision 1 required a numbered list of changes. Each row maps one of them to the
rules and points it changed.

| # | Required change | Rules and points |
| --- | --- | --- |
| 1 | the proof that `qargi host` is outside every sandbox cannot be made inside one; a verb with no project is judged by whether a project is seated | R33, R64 and R76 rewritten; R8, R15, R21, R47 and R70 follow; O9 decided; O17 new |
| 2 | a recorded path is refused by the clone and the state root that the assignment declares, not by who owns it | R89 rewritten; R19 gains `state_root`; R31, R70, R84 and R88 follow; O6 decided |
| 3 | the verbs that write the spool are named, and each passes in the state that asks for its envelope | R96 new; R32, R34, R35, R38, R40, R48, R51, R60 and R61 follow; O10 narrowed |

## Decided points

These points were open in an earlier revision and are decided. Each names the rule that states the
decision, and none is marked in a rule any more.

- **O6** (R19, R89). Decided as the alternative: the assignment names the state root of the role
  (`state_root`), and the broker refuses every recorded path that overlaps the clone or the state
  root that the assignment declares. Who owns a path is not used: it cannot tell a sandbox of the
  same user from the owner. It costs one field in a record that the supervising layer writes.
- **O9** (R33, R64). Decided: a verb that names no project is judged by whether some project under
  `$CONF` is seated, not by a test for a sandbox. Class `owner` is then refused wherever the verb
  runs, and the owner's way is `qargi host`, whose outside proof is the signature of R33. The cost
  is the owner's question O17.

## Open points

Every `[OPEN On]` above is listed here. The lead decides a point unless its item names the owner
or the supervising layer.

- **O1** (R7, R8). Where the authority store lives. Proposed: a third root outside the state and
  config roots, as the design's decision says. Alternative A: a directory below `$CONF` that is
  never bound into a sandbox; it costs the rule "never below the config root" and needs `export` and
  every `$CONF` bind list to leave it out, but then this page names no path outside the two roots.
  Alternative B: keep the third root and do not call it a deviation; it costs one more root to
  resolve, document and check in `doctor`. The test of this page allows `$AUTH` only while O1 is
  listed.
- **O2** (trace). The task names "the 12 check changes of revision 5". Proposed: the inputs hold no
  list of twelve changes, so this page maps all 24 changes of revision 5 and the two later inputs,
  and states the twelve gate conditions as R53 to R64. Alternative: another list of twelve was
  meant; it costs a second trace table once the list is supplied.
- **O3** (R36 to R39). Whether A is fenced before B reads back. Proposed: yes, as the design has it:
  the note is built after the fence, so it cannot go stale under A. Alternative: B reads back while
  A still holds; it costs a window with two live units and a note that A can outdate, and gains a
  failed read-back that leaves the project with its old lead.
- **O4** (R17). The marker records the two directories as the lead sees them, but the broker writes
  the projection outside the sandbox. Proposed: both sides use the same path. Alternative A: the
  marker records an inside and an outside path for each; it costs two more fields the lead can
  read. Alternative B: the broker is told the outside path on each call; it costs a value that is
  not recorded anywhere. The same question holds for `clone`, `state_root` and `mirror` of the
  assignment, which R89 compares as the broker reaches them; the proposal covers them.
- **O5** (R88). Where no-follow starts. Proposed: at the file system root for a path a record names
  (the two directories, the mirror), and below the root for `$CONF`, `$STATE` and `$AUTH`, whose
  own path is resolved once. Alternative: from the file system root for every path; it costs every
  host whose home directory is reached through a link.
- **O7** (R91, R92). The archive: who makes it, where, how large, and how the successor reads it.
  Proposed: the broker, below `$AUTH`, with a size limit per run that this page does not fix, and
  the successor reads the manifest in the note only. Alternative A: the supervising layer archives
  and hands qargi the manifest; it costs qargi the check that the archive exists. Alternative B: the
  archive is published below the projection directory so the successor can read the files; it costs
  lead-written files in a directory the lead side trusts. The inputs also conflict here: the walk
  reads lead-written folders, which R89 forbids by path; the proposal allows it only between S3 and
  S5, when no unit of the role exists.
- **O8** (R52, R60 to R63). The design's list of codes puts `not-assigned` after `seat-vacant`, but
  its matrix answers class `owner` with `not-assigned` in every state. Proposed: the matrix wins.
  Alternative: the list wins; it costs an owner verb in a vacant seat the answer `seat-vacant`. The
  matrix also names no answer for a `fenced` seat, which has no holder to compare; proposed: R60
  applies and R56 is skipped.
- **O10** (R32, R35, R39). The spool's file names, what triggers collection, and the fields of the
  content of a `state` envelope, which the design does not give. Proposed: left to the joint list
  with the supervising layer; this page fixes the envelope, the verbs that write it and where they
  pass (R96). Alternative: this page fixes one file name for each kind and says that the
  supervising layer collects when the file appears; it costs rules about the supervising layer's
  side that no test of qargi can show.
- **O11** (R70). The design names `fence-required`, `fence-unproven`, `note-invalid`,
  `note-digest-mismatch` and `seat-changed` without saying when each is raised. Proposed: the table
  of R70. Alternative: fewer codes (`fence-unproven` for both fence cases, `note-invalid` for both
  note cases); it costs the caller the difference between "send a fence" and "send a better one".
- **O12** (R5, R44). Which epoch `vacate` and `unseat` name, whether a number is reused after an
  abort before S3, and what S1 writes at init. Proposed: every accepted assignment takes the next
  number, none is reused, and S1 at init writes the copy only. Alternative: `vacate` and `unseat`
  keep the current epoch and an aborted number is reused; it costs the rule that a number names one
  assignment for good.
- **O13** (R74). Whether the door refuses to seat a project on the shared backend. Proposed: yes,
  with `refs-backend-active`. Alternative: a documented step only (`marshal disable` first); it
  costs a seated project with two sources for who leads.
- **O14** (R12, R19). Details the design does not state: the lock and the flush of R12, mode 600,
  what `managed` and `sandboxed` of the assignment mean, how many read-backs B may send, and how
  the store is made read only after an unseat. Proposed: as R12 says, no rule on the two booleans,
  no bound on attempts, and modes without the write bit. Alternative: leave each to the build; it
  costs a contract that the first reviewer has to complete.
- **O15** (R94). The label's name and carrier come from a review, and the label is built outside
  the seat's waves. Proposed: this page fixes what the label is not and leaves its name to that
  task. Alternative: fix `QARGI_ACTOR` and `--actor` here, with the narrowing checks; it costs the
  seat a dependency on work the plan keeps apart.
- **O16** (R65). The supervising layer's requirements say the refusal line is the first line of
  standard error. Proposed: any line, as the design says. Alternative: the first line; it costs
  every verb that prints a warning before it is refused.
- **O17** (R64; for the owner). What it costs to judge a verb with no project by whether a project
  is seated. On a host with one seated project every `owner` verb that names no project is refused
  when it is typed plainly, in the owner's own session too and also when the work is for an
  unseated project. It has to be typed as `qargi host VERB`, which then needs the authority store
  and the projection of a seated project. Proposed: the owner accepts that cost, because no test
  that a sandboxed session cannot defeat tells the two callers apart. Alternative A: a variable
  that the supervising layer sets inside a sandbox; it costs a check the lead can switch off.
  Alternative B: the gate makes the outside proof itself and passes such a verb when it holds; it
  costs lead-side code that opens `$AUTH`, against R10.
