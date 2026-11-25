# The stored plan record

A verb that prints a plan token can keep the plan it hashed, so that a reader (a person, or a card that asks the owner to approve) sees what the token covers and a stale token can say what moved. The record is `STATE/plans/TOKEN.json`, written by `plan_token --basis`, read by `qargi plan show TOKEN [--json]`.

**Draft.** The schema string is `qargi.plan/0`: it means "draft, may change without notice". It becomes `qargi.plan/1` only when the shape is published, once a consumer uses it. Nothing here changes a token, `need_plan` or any approval.

## Which verbs keep it

The plans listed here keep it: the ones whose hashed input is plain lines or one line of words, and that a slice has reached (some plans of plain lines keep none yet: see [Plans that keep no record yet](#plans-that-keep-no-record-yet)). Each is listed with its verb, its target (`PROJECT:OBJECT`) and its labels in order; a label written once for several lines is `label*`.

| Verb | Target object | Labels, in the order of the lines |
| --- | --- | --- |
| `branch prune` | `merged-branches` (`+origin` with `--remote`) | `project remote branches*` |
| `feature finish` | the feature | `project branch head develop keep delete-merged origin-branch push`; a finish that was cut off: `record` |
| `feature merge` (into a detached branch) | the detached branch | `project detached head task task-head` |
| `upstream sync` | the branch that carries the upstream line | `project into head upstream` |
| `release plan` | the version | `project kind version date keep allow-empty branch base head master second steps start-plan fix-paths*` |
| `release start` | the version | `project kind branch base head version date files*` |
| `release push` | the version | `project branch head join master` |
| `release finish` | the version | `project branch head second master second-head keep ignore-checks`; a finish that was cut off: `record` |
| `release publish` | the version | `project version tag notes title asset* signature` |
| `release site` | the version | `project version tag site-branch site-head tree` |
| `feature verify`, `release verify` (the waiver of a `verify.environment` part, `--waive-environment`) | the feature or the version | `project branch head environment part* waiver` |
| `project new` | the directory, as given (a control character is shown as `?`; at most 200 characters) | `directory methodology url deployment provider provider-local provider-cloud files` |
| `project remove` | `answers` (under the project being removed) | `project answers approved member*`: the name, the sha256 of the answers file, the id of the approved `verify.environment` declaration (`none` when the state has no entry, `off` when the entry declares none), then one line `name\|roles\|file\|copy` for each member |
| `project set`, `project unset` (a loosening of `verify.environment`) | the path as given to the verb: `verify`, `verify.environment` or a path below it | `project old-declaration new-declaration` |
| `provider accept` | the runtime and the surface | `runtime surface project reason` |
| `instances init` (a change of the agent's model), `instances normalize`, `instances refresh-prompt` | the agent, or the instance | `agent`, `renames`, `prompt` |
| `credential setup` | the repository (`owner/name`) | `grant` |
| `skill accept`, `skill unaccept` | the skill | `accept`, `unaccept` |
| `marshal key`, `marshal enable`, `marshal signers`, `marshal resign`, `marshal forget`, `marshal disable` | `marshal key`: the principal (control characters removed, at most 200 characters), under the project `machine`; the others: the remote, the signer, the feature, the feature, `shared-refs` | `words` |

The plans not listed keep nothing yet (see [Plans that keep no record yet](#plans-that-keep-no-record-yet)): `qargi plan show` of their tokens is `plan-unknown`. Nothing is kept in a dry run (`QARGI_DRY=1`).

**Two names that are not projects.** A target is `PROJECT:OBJECT`, and two plans have no project to name. `machine` is the project of `marshal key init`: the signing key belongs to this machine, not to a project, so the target is `machine:PRINCIPAL`. `cloud` is the project of `instances init` when the name of the deployment gives no valid project name (the plan is made before the instance is named, so the target is `cloud:AGENT-ID`). No project of either name is made by these verbs.

**The record never decides a token.** The token is the first 12 digits of the sha256 of the hashed text, whatever happens to its record. When the record cannot be kept (no temporary file can be made, the target or the clock is refused by `lib/refusal.py`, the state cannot be written), the plan still prints its token, with a note on standard error, and the record is simply not there (`plan show` says `plan-unknown`). No gate accepts an empty token: `need_plan` stops with an internal error when the verb gives it none, so an apply that was given no `--plan` is never taken for the plan of a record that failed. The text a user chose for a target (a directory of `project new`, a principal of `marshal key init`) is cleaned for the target only (control characters removed or shown as `?`, cut to 200 characters); the hashed text keeps it as given.

**One line of words.** The record's lines are the hashed text split on a newline, so a plan that is one `printf` of words, or of fields joined by `|` (the marshal verbs, `instances init` and `normalize`, `credential setup`, `skill accept` and `unaccept`) is one line with one label (`words`, `agent`, `renames`, `grant`, `accept`, `unaccept`): the words cannot be split into a label each without changing the bytes, so the token. `instances refresh-prompt` hashes `VERSION|PROMPT|MEMBERS`: its lines are the rendered system prompt, one entry for each line, with `VERSION|` in front of the first and `|MEMBERS` after the last, all under the label `prompt`; the record holds the prompt in clear, as the cloud agent will hold it. The `project new` record holds the files it would create as one line of JSON (`jq -S -c`), as the plan hashed it. A label that covers a variable number of lines, in the middle of a plan (the assets of `release publish`, the parts of a waiver), is given once for each line by the call site; the basis (`basis moved`) groups them.

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
- `input_sha256` and `input_newline` bind the record to the exact bytes that were hashed: `"\n".join(values)`, plus a final newline when `input_newline` is true, hashes to `input_sha256`, and its first 12 digits are `token`. A card is bound to `input_sha256`, not to the 48-bit token. **The hash covers the lines and `input_newline` only.** The verb, target, context, labels, kinds and times are not under it: `plan show` checks them for their form (the types of the refusal catalogue; `expires` must be exactly `created` plus seven days), but a hand edit that keeps them well formed, another verb or target for instance, is shown as it stands. The record is a reading aid in the file of the owner, not a signature.
- `created` and `expires` are UTC; `expires` is `created` plus seven days. Expiry is not checked when a plan is applied.
- `basis` is the older key that `basis moved` and `plan-stale moved=` read: the lines grouped by label. It is not part of the canonical record.

## `qargi plan show TOKEN [--json]`

Read only, open to a member (class `read` of the seat). It changes nothing: no file is made or removed, no audit line, no lock; it works under `QARGI_DRY=1`. The plans directory and the file are opened without following a link, and the file must be a regular file of one link and mode 600. It recomputes `input_sha256` from the lines and `input_newline`, and checks the token against that hash and against the name of the file, before it prints anything.

The text gives the verb, the target, the labelled lines, `created` and `expires`; a control character in a value (the lead chose it) is printed as `\xNN`, so that a terminal does not act on it. `--json` prints the record as stored and adds `"state": "valid"`.

| Refusal | When |
| --- | --- |
| [`plan-unknown`](refusals.md#plan-unknown) | the argument is not 12 hex digits, no such file, or a file of before the schema (no `schema` key) |
| [`plan-expired`](refusals.md#plan-expired) | `expires` is past; the file is left where it is, the store prunes it |
| [`plan-record-invalid`](refusals.md#plan-record-invalid) | a link, a file of the wrong kind, mode or link count, one that cannot be read, damaged JSON, an unknown schema, a malformed record, or lines that do not hash to the token |

The `problem` of a `plan-record-invalid` is one of these words:

| `problem` | The record |
| --- | --- |
| `bad-directory` | the `plans` directory is a link or not a directory |
| `link` | the file is a link (it is not followed) |
| `unreadable` | the directory or the file cannot be opened or read for another reason (its mode 000, say) |
| `not-a-file` | the file is a directory, a pipe or another thing that is not a regular file |
| `links` | the file has more than one link |
| `wrong-mode` | the mode is not 600 |
| `too-large` | the file is larger than 1 MiB |
| `bad-json` | the text is not JSON, not UTF-8, or nested too deeply to parse |
| `unknown-schema` | the `schema` is not `qargi.plan/0` |
| `bad-form` | a key is missing or extra, a value is of the wrong type or form (the verb, target, context, label or kind among them), `expires` is not exactly `created` plus seven days, or the token is not the file's and the hash's |
| `hash-mismatch` | the lines and `input_newline` do not hash to `input_sha256` |

`QARGI_PLAN_NOW` (a UTC time such as `2026-11-22T10:00:00Z`) stands for the clock of the records in tests.

## Plans that keep no record yet

These plans call `plan_token` with no `--basis`, so `qargi plan show` of their tokens is `plan-unknown`. Most are left on purpose: what they hash is a JSON document, the content of files, or a text that the verb builds for itself, not the plan a person reads, so a record of its lines would show nothing to approve. The plans of plain lines (`packs seed`, `provider enable` and `disable`, `local clean --orphans`) are left only because no slice has reached them. A decision for each is open (slice 3).

| Where | Verb | What is hashed | Why it keeps nothing |
| --- | --- | --- | --- |
| `lib/canon.sh` | `canon plan`, `canon apply` | `jq -S -c .ops` of the plan of each kind of store, one JSON line per kind | a JSON document, not the plan text |
| `lib/memory.sh`, `lib/tierwrite.sh` | `memory copy`, `memory move`, `memory init`, and the like | `jq -S -c .` of the planner's `plan.json` | a JSON document |
| `lib/packs.sh` (`member-skills`) | `packs member-skills` | the member-skills plan, as the planner prints it | a JSON document |
| `lib/packs.sh` (cloud `apply`) | `packs apply` for a cloud agent | the bytes of every rendered file, then `AGENT\|VERSION\|SKILLS\|TOOLS-OFF` | the content of files, a digest of what would be sent |
| `lib/project.sh` | `project attach`, `project adopt` | `jq -S -c` of the answers, or of the plan's `basis` | a JSON document |
| `lib/provision.sh` | `provision plan`, `provision apply` | the bytes of every rendered file, then one line of store ids, budget, name and environment | the content of files |
| `lib/env_apply.py`, `lib/backlog.py` | `env plan`, `env apply`, `backlog done` | a JSON document (the dry run's output, its command, the host), and the parts of a backlog item joined by newlines | Python's own `plan_token`, over a JSON document or the item's text |
| `lib/packs.sh` (`seed`) | `packs seed` | the sorted plan lines, as printed | plain lines that no slice has reached yet: a record would be one label for every line |
| `lib/provider.sh` | `provider enable`, `provider disable` | the plan's own lines, as printed | plain lines that no slice has reached yet |
| `lib/local.sh` | `local clean --orphans` | the directories it would remove, one to a line | plain lines that no slice has reached yet |
| `lib/upgrade.sh` | `qargi upgrade` | the installed root and the two commits, hashed with `sha256sum`, not with `plan_token` | no lines: a hash of three values |
| `lib/project_link.py` | `project link`, `project unlink` | the verb and the facts of each link, as JSON, hashed in Python | a token of JSON facts, made in Python |
| `lib/linker.py`, `lib/packs_link.py` | `packs link`, `packs unlink` | the facts of the link, as JSON, hashed in Python | a token of JSON facts, made in Python |
| `lib/gitflow.sh` (`SE_KEY`) | none | the project, the branch, the head and the declaration | no plan: it names the files that count the waivers of a head and is never shown to an owner (the waiver token, `suite_env_token`, keeps a record) |
