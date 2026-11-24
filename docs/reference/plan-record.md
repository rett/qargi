# The stored plan record

A verb that prints a plan token can keep the plan it hashed, so that a reader (a person, or a card that asks the owner to approve) sees what the token covers and a stale token can say what moved. The record is `STATE/plans/TOKEN.json`, written by `plan_token --basis`, read by `qargi plan show TOKEN [--json]`.

**Draft.** The schema string is `qargi.plan/0`: it means "draft, may change without notice". It becomes `qargi.plan/1` only when the shape is published, once a consumer uses it. Nothing here changes a token, `need_plan` or any approval.

## Which verbs keep it

`branch prune`, `feature finish` (the plan, and the plan of a finish that was cut off), `release plan`, `release start` and `release push`. The other plans keep nothing yet: `qargi plan show` of their tokens is `plan-unknown`. Nothing is kept in a dry run (`QARGI_DRY=1`).

## The record

```json
{"schema": "qargi.plan/0", "verb": "release start", "context": "lead",
 "target": {"project": "acme", "object": "0.4.0"},
 "lines": [{"label": "project", "kind": "name", "value": "acme"}, {"label": "kind", "kind": "label", "value": "release"}],
 "input_sha256": "<64 hex>", "input_newline": true, "token": "1a2b3c4d5e6f",
 "created": "2026-11-22T10:00:00Z", "expires": "2026-11-29T10:00:00Z",
 "basis": [{"label": "project", "lines": ["acme"]}]}
```

- `verb` is the verb as `lib/commands.py` names it, never the command line; `context` is `lead` (the owner's own session is not built).
- `target` is the project and the one object the verb acts on (a feature, a version, the merged branches). The call site says it: `plan_token --basis LABELS --verb VERB --target PROJECT:OBJECT`; nothing is read off the command line.
- `lines` holds one entry for each line that was hashed, in order. A label covers one line: where a label took several (the branches of a prune, the files of a start) it is written out for each. The values are in clear, lead-chosen ones included, because a card that showed a digest would ask for an approval blind; the file is the owner's, mode 600, beside `audit.log`. `kind` says what a value is, in the types of the refusal catalogue: `ref`, `path` and `name` are text the lead chose, `sha`, `label` and `count` are qargi's own or of a fixed shape. A consumer that sends the plan off the host digests the lead-chosen kinds itself. A label given without a kind is `name`, the conservative one. Nothing of a plan goes into a refusal line, a seat note or a result.
- `input_sha256` and `input_newline` bind the record to the exact bytes that were hashed: `"\n".join(values)`, plus a final newline when `input_newline` is true, hashes to `input_sha256`, and its first 12 digits are `token`. A card is bound to `input_sha256`, not to the 48-bit token.
- `created` and `expires` are UTC; `expires` is `created` plus seven days. Expiry is not checked when a plan is applied.
- `basis` is the older key that `basis moved` and `plan-stale moved=` read: the lines grouped by label. It is not part of the canonical record.

## `qargi plan show TOKEN [--json]`

Read only, open to a member (class `read` of the seat). It changes nothing: no file is made or removed, no audit line, no lock; it works under `QARGI_DRY=1`. The plans directory and the file are opened without following a link, and the file must be a regular file of one link and mode 600. It recomputes `input_sha256` from the lines and `input_newline`, and checks the token against that hash and against the name of the file, before it prints anything.

The text gives the verb, the target, the labelled lines, `created` and `expires`. `--json` prints the record as stored and adds `"state": "valid"`.

| Refusal | When |
| --- | --- |
| [`plan-unknown`](refusals.md#plan-unknown) | the argument is not 12 hex digits, no such file, or a file of before the schema (no `schema` key) |
| [`plan-expired`](refusals.md#plan-expired) | `expires` is past; the file is left where it is, the store prunes it |
| [`plan-record-invalid`](refusals.md#plan-record-invalid) | a link, a file of the wrong kind, mode or link count, damaged JSON, an unknown schema, a malformed record, or lines that do not hash to the token |

`QARGI_PLAN_NOW` (a UTC time such as `2026-11-22T10:00:00Z`) stands for the clock of the records in tests.
