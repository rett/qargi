# Skill spec, version 1 (draft 2)

Status: draft for review, revised after an adversarial review. Nothing here is implemented. The contract
is this document plus `conformance/skills/` (language-neutral fixtures); a Python reference and a later
Go port must both pass them. Federation is specified separately in `FEDERATION.md`.

A rule below is one of three kinds, and says which:
- **lint**: a validator decides it from the files alone;
- **record**: a validator checks that a recorded artifact exists, matches the current digest and meets
  policy, without being able to judge its truth;
- **approval**: a person decides, and the decision is recorded.

## Goals

1. Selection is unambiguous: a skill says when it applies, when it does not and what applies instead.
2. A skill exists only for a demonstrated need.
3. One source compiles to every platform that reads Agent Skills.
4. Automation is declared so a runtime can enforce it, and a binding can only narrow it.
5. Context cost is small, measured and budgeted per attached set.

## Layout

```
library/
  policy.json  domains.json  overlaps.json
  skills/<id>/skill.json  body.md  evals/cases.json  evals/value.json  evals/rubric.md
              evals/results/  verdicts/  references/  scripts/  assets/
  packs/<id>/pack.json
  roles/<id>.json            decomposition records
conformance/skills/          fixtures
```

Bindings (`automation.json`) live in the project or user scope, never in the catalog.

## References

Every reference to a skill (`instead`, `neighbours`, `delegation.to`, pack members, bindings) is
`namespace/id`. A bare `id` means `local/id`. `local` is reserved for this deployment's own skills.

## Digest (lint)

The digest identifies the exact content of a skill. It is computed, never authored, and lives in the
catalog listing and in verdicts, not in `skill.json`.

1. Take every regular file under the skill directory except `verdicts/` and `evals/results/` (outputs
   that depend on the digest). Symlinks are an error.
2. Path = relative path, `/` separators, UTF-8, no leading `./`. Sort by path bytes.
3. For each file, one line: lowercase hex `sha256(path)` + lowercase hex `sha256(file bytes)` + `\n`.
4. Digest = lowercase hex `sha256` of the concatenated lines. No newline, mode or encoding normalisation.

## skill.json

| Field | Meaning |
|---|---|
| `schema` | integer, `1`. |
| `id`, `version`, `domain`, `license` | `id` is lowercase letters, digits and single hyphens (no leading, trailing or doubled hyphen), at most 64 characters, equal to the directory name. `version` is semver. `domain` is in `domains.json`. `license` is an SPDX expression. |
| `summary` | what the skill does; one sentence, at most `summary_max_chars`. |
| `selection.intents[]` | 1 to `max_intents` imperative user goals. Linted against `intent_forbidden_patterns`. |
| `selection.excludes[]` | `min_excludes` to `max_excludes` entries `{topic, instead}`; `instead` is a reference or `none`. |
| `neighbours[]` | `{ref}`. Symmetric: if A lists B, B lists A. Must include every `instead` reference. The boundary itself is recorded in the overlap register (below), not as free text. |
| `provenance` | `{author, origin, sources[], borrowed}`. `origin` is `original`, `adapted` or `federated`. `adapted` requires each source with `url` (https), `commit` (hex, 7+ characters) and a note on what was borrowed. `federated` keeps the publisher's evidence under `remote_evidence` (record only; never counted locally). |
| `demand` | `{cases[], baseline, exception}`; see Demand. |
| `invocation` | `auto`, `manual` or `both`. Default `auto`. |
| `scope_paths[]` | optional file globs that gate auto activation where a platform supports it. |
| `arguments[]` | `{name, hint, required, type, enum?, format?, ui?}`. `type` is `string`, `number`, `integer`, `boolean`, `enum`, `multi-enum`, `date`, `date-time` or `secret-ref` (rendered as an account picker, never text). `ui` is `{widget?, label, help, placeholder, order, group, sensitive}`. Feeds `argument-hint` and a generated form (`frontend/DESIGN.md`). |
| `result_schema`, `result_ui` | `result_schema` is a JSON Schema in the flat-primitive subset plus arrays of flat objects; `result_ui` is `{component, summary_template}`. A run's outcome record may carry a typed `result` that conforms to it. |
| `approval_summary` | a template with named fields (`{effect_class} {audience} {money} {targets}`) rendered by the client for an approval. Lint: no free text over 240 characters and no URLs. |
| `i18n` | `summary`, `selection.intents` and `arguments[].ui.label` may be `{default, <bcp47>: ...}`; the compiled description uses `default`. |
| `requires` | `{runtimes[], network}`. Compiles to `compatibility`. |
| `scripts[]` | one entry per file under `scripts/`: `{path, consent, network}`. An unlisted script file is an error. |
| `tools[]` | `{server_ref, capability?, tool_names[], scopes[], mode, consent}`; see Tools. `server_ref` resolves through a connector type (`CONNECTORS.md`) and never to an account. |
| `data`, `effects[]`, `verification` | what the skill reads, where its results may go, what it does to the world, and how a run is checked; see Data, effects and verification. |
| `automation` | what the skill may do unattended; see Automation. |
| `events` | `{accepts[], emits[]}` with `accepts[]` entries `{type, data_schema}`. (Formerly `triggers`; renamed so it cannot be confused with selection.) |
| `delegation` | `{allowed, max_hops, to[]}`. `to[]` entries are references or `agent:<name>`. `deployment:<name>/agent:<role>` is reserved and not validated in v1. |
| `retired` | `{after, superseded_by}`; see Retirement. Absent unless retired. |
| `x-*` | platform extensions. Never validated. A compiler MUST NOT copy a permission-bearing key (`allowed-tools`, `hooks`, `agent`, `context`, `paths`) from an `x-*` field. |

There is no `status` field. Status is derived (below). A skill never contains secrets, tokens, client
ids, account identifiers or URLs with credentials (lint: secret patterns).

## Effective status (record)

`retired` if `skill.json` has `retired`. Otherwise the highest verdict (`trial`, `accepted`) in
`verdicts/` whose `digest` equals the current digest. Otherwise `draft`. A content change therefore
demotes a skill automatically; a change to a neighbour re-opens the pair in the overlap register.

A verdict is a file `verdicts/<digest>.json`: `{digest, status, results[], approved_by, approved_at,
note, exception?}`. Writing a verdict runs every rule below for that status first (an **approval** is
required for `accepted`; see Lifecycle). Verdicts are local: an imported skill arrives without them.

| Rule | draft | trial | accepted |
|---|---|---|---|
| Structure, ids, types, secrets, forbidden intent patterns | yes | yes | yes |
| Description fits and `Must` section present | | yes | yes |
| Demand: cases and baseline, or exception | | yes | yes |
| Evals present and well formed | | yes | yes |
| Neighbours symmetric, scripts and tools declared | | yes | yes |
| Trial results meet policy (below) | | | yes |
| Value result meets policy | | | yes |
| Overlap register clean for every flagged pair | | | yes |
| Human approval recorded | | | yes |

## Description (lint)

The compiled `description` is generated, never hand-written:

```
<summary> Use when: <intent1>; <intent2>. Not for: <topic1> (use <name1>); <topic2> (use <name2>).
```

`<name>` is the `id` of the `instead` skill if it is in the attached set, otherwise `out of scope here`.
`instead: none` also gives `out of scope`. Separators are exactly as shown; no newlines. Length is at
most `description_max_chars`. The sum of `len(name) + len(description)` over an attached set is at
most `attached_set_budget_chars` (the per-set budget is what platforms enforce). The conformance suite
pins the exact string for a given `skill.json`.

## Evals and trials

`evals/cases.json` is a list of `{id, prompt, expect, kind}`:
- `kind` is `positive` (`expect: self`), `near_miss` (`expect: <reference>` or `none`) or `negative`
  (`expect: none`).
- At least `min_eval_positive` positives and `min_eval_negative` negatives. Prompts are unique within a
  skill.
- **A near miss must be a copy of a positive prompt of one of the skill's neighbours** and its `expect`
  is that neighbour. At least `near_miss_share` of the negatives are near misses when the skill has
  neighbours. Authors cannot invent easy negatives to pass; the harness derives them (lint).

A **trial** runs the positives of every skill in the attached set, and each skill's near misses and
negatives, against one named selector (`{platform, model, version}`), `trial_runs_per_case` times each.
Its result is `evals/results/<digest>-<platform>-<model>.json`:
`{digest, selector, date, runs, cases[{id, selected, hits, cost_usd, turns, output_tokens}]}`. A case passes
at `case_pass_rate`. Cost and turns are recorded, not gated: a skill use costs extra turns (a pilot on
2026-10-30 measured roughly 70% more per run with a trivial skill body), so the approver sees the added cost
per run beside the value delta, and a skill whose delta does not repay it is flagged for the approver.
Precision, recall and cross-fire are **recomputed by the validator** from `cases[]`; stored aggregates
are ignored. Acceptance needs a result with precision and recall at least `min_trigger_precision` and
`min_trigger_recall` on **at least two selectors**: the cheapest and the strongest model in use
(record).

`evals/value.json`: `{digest, rubric, cases[{id, task, without, with}]}`, scores 0 to 1 against
`evals/rubric.md`. The metric is the mean of `with - without`; acceptance needs at least
`min_value_delta` (record). The `without` scores are the baseline failure.

## Overlap (record)

**Cross-fire** from skill A to skill B is the share of A's positive cases a trial assigned to B. A pair
is flagged when either cross-fire is at least `overlap_threshold`, or when either skill lists the other
as a neighbour. Each flagged pair needs an entry in `overlaps.json`:

`{a, b, basis{digest_a, digest_b}, rate_ab, rate_ba, decision, cases[], decided, by}`

`decision` is `boundary` (they stay separate), `split`, `merge` or `retire-one`. Only `boundary` can be
accepted: its `cases[]` name near-miss cases in each skill that pass in the latest trial. The other
decisions are pending actions; the pair stays unresolved until a skill changes. An entry is stale when
either digest differs from `basis`, and the pair must be re-evaluated.

## Demand (lint + record + approval)

`demand.cases[]` are `{date, what, evidence}` with `date` in the past and `evidence` a resolvable
reference: an audit-log id, a repository path, or an https URL. The validator checks the form and the
date; a person approves that the cases are real. At least `min_demand_cases`, all local. `baseline`
points to `evals/value.json` (the without-skill runs). `exception.justification` replaces cases and
baseline only for a `trial` verdict; an `accepted` verdict never carries an exception.

## Packs and role decomposition

`pack.json`: `{schema, id, title, domain, summary, skills[], phases[]}`. `domain` equals each member's
domain unless the pack sets `cross_domain: true`. A phase is `{id, question, select, options[]}` with
`select` of `one` or `many` and `options[]` entries `{id, label, adds[], then?}`; `then` names the next
phase, and a phase with no inbound `then` is a first phase. Selection narrows in three steps before any
skill is loaded: pick the pack, answer its phases, attach only the added skills at a scope (`user`,
`user-role`, `project`, `project-role`). Compilation is set-aware (see Description). An attach is refused
if it exceeds `attached_set_budget_chars`.

`roles/<id>.json` records a decomposition: `{goal, date, method, duties[{id, title, tasks[{id,
statement, skill, gap}]}]}`. A task statement names a trigger, an outcome and a boundary. Each task has
a `skill` reference or `gap: true`; a gap must acquire demand cases before a skill is drafted (lint).

## Tools and consent (lint)

`mode`: `user`, `service` or `either`. `consent`: `read` < `write` < `external` < `destructive`.
`external` is an effect that reaches people or systems outside the deployment (send, post, publish, pay);
a `write` tool must not be one. `external` and `destructive` can never be pre-approved by a binding.
`server_ref` is a logical name resolved by runtime config. Compilers pre-approve (emit `allowed-tools`)
only tools of consent `read`, never from `x-*`. `scripts[].consent` uses the same order.

## Data, effects and verification (lint; schema 1, enforced by the guardrails in `guard/DESIGN.md`)

- `data`: `{reads[], egress[], sensitivity}`. Data classes: `public`, `internal`, `confidential`, `pii`,
  `phi`, `financial`, `credential`, `legal-privileged`, `unknown` (the highest class present when a class
  cannot be determined). `egress[]` names sinks: `git-push`, `pr`, `comment`, `email`, `chat`, `publish`,
  `http:<host>`, `memory`, `peer`. `sensitivity` is `low`, `medium` or `high`. Lint: `reads` containing
  `credential` together with any `egress` is refused; non-empty `egress` with `unattended` other than
  `never` needs an approval record.
- `effects[]`: `{class, reversibility, audience, money}`. `class`: `none`, `send`, `post`, `publish`, `pay`,
  `delete-record`, `modify-record`, `commit`, `push`. `reversibility`: `reversible`, `compensable`,
  `irreversible`. `audience`: `private`, `internal`, `named-external`, `public`. `money`: boolean. A tool
  of consent `external` must be matched by an effect with `audience` of `named-external` or `public`, or
  with `money` true.
- `verification`: `{kind}` with `kind` one of `executable`, `rubric`, `source-resolves`, `second-reader`,
  `human`, naming how a run of the skill is checked before its result is relied on. The `rubric` kind
  points to `evals/rubric.md`. Whether `human` alone suffices for an unattended skill with an external
  effect is an open question (see `guard/DESIGN.md`).

## Automation (lint)

`automation`: `{unattended, idempotent, schedule_policy, budget, alert_after_errors}`.
- `unattended`: `never`, `allowed`, `required`. Any effect with `reversibility` `irreversible`, `money`
  true, or `audience` of `named-external` or `public`, in a skill whose `unattended` is not `never`,
  requires an approval record (approval). (`side_effects` is gone: `effects[]` replaces it.)
- `schedule_policy`: `{min_interval, max_interval, backoff, jitter, catch_up, concurrency}`. Intervals
  are durations (`30s`, `15m`, `6h`, `2d`); `backoff` ≥ 1; `jitter` in 0 to 0.5. `catch_up`: `skip`,
  `coalesce` (default), `replay` (idempotent skills only). `concurrency`: `forbid` (default), `queue`,
  `replace`, `allow`.
- `budget`: `{tokens_per_run, runs_per_day, max_runtime}`; required when `unattended` is not `never`.

**Outcome contract.** Every scheduled run ends with a record the spec defines:
`{outcome, detail, tokens, duration_ms, next_hint?, result?, accounts_used?}`, `outcome` in `changed`,
`unchanged`, `error`; `result` conforms to the skill's `result_schema` so a client can render it without
the model, and `accounts_used` lists the account ids a run used (see `CONNECTORS.md`).
Next interval from the previous interval `p`: `unchanged` → `min(max_interval, p × backoff)`;
`changed` → `min_interval`; `error` → `min(max_interval, p × backoff)`, with an alert after
`alert_after_errors` consecutive errors. `next_hint` may move the result but never outside
`[min_interval, max_interval]`. With `jitter` j, the delay is multiplied by a uniform value in
`[1 - j, 1]`. Fixtures use `jitter: 0`.

## Binding (`automation.json`) may only narrow (lint)

A binding names a skill, a `schedule` (`cron` + IANA timezone, `rrule`, `interval`, or `adaptive`),
`events`, `tools`, `accounts` and limits. It is valid only if all of these hold:

| Binding field | Must satisfy |
|---|---|
| Any schedule | `unattended` is not `never`. Over a 366-day window every gap between consecutive runs is at least `min_interval` (a cron whose gap is shorter is invalid). An adaptive range lies within `[min_interval, max_interval]`. |
| `events[]` | each `type` is in the skill's `events.accepts`. |
| `tools[]` | each `(server_ref, tool_name)` is in the skill's tools, and its scopes are a subset. `mode` is allowed by the skill (`either` permits `user` or `service`; otherwise equal). |
| Tool approval `allow` | permitted only when the skill's consent for it is `read` or `write` and `unattended` is not `never`; `external` and `destructive` are always `ask`. |
| `budget` | every figure is at most the skill's. |
| `accounts` | no counterpart in the skill; secrets never appear (lint). |
| Retired skill | refused. |

## Retirement (lint)

`retired: {after, superseded_by?}`. Before `after`, a reference to the skill is a warning. From `after`
on, it is an error unless the referrer is redirected to `superseded_by`. Bindings on a retired skill are
refused. `retired` is terminal.

## Who may modify a skill (invariant; approval)

A skill is an instruction every later run obeys, so changing one changes every future run. Therefore:

1. **Only core, built-in, qargi-sanctioned skills may carry out a skill modification.** The sanctioned set
   is a manifest shipped with qargi (names and digests), verified at install. An agent, an imported,
   federated or community skill, or a self-improvement loop never holds this authority, and a skill cannot
   grant it to itself or claim it in its own files. The sanctioned skills act only by invoking host verbs;
   they do not write skill files from inside an agent session.
2. **Every modification needs proof that a person is present.** The modifications are: create, edit,
   import, seal (re-approve edited content), remove, accept (a verdict), and an overlap decision. Proof is
   a typed confirmation at the terminal or, later, a device-signed approval. A `--approved` text flag, an
   environment variable or an approval string in a prompt is never proof, so an agent's shell cannot
   satisfy it.
3. **Agents cannot write under a skill directory.** The guard denies writes by agent tools and shells to the
   library, the installed skills and the pack library. An agent that wants a change proposes it as a patch
   or a plan in its run directory; the sanctioned skill turns an approved proposal into the write.
4. **The mechanism that follows is the existing one.** A write changes the digest, so the skill's status
   demotes by itself and its trials and verdicts must be redone before it is relied on.
5. **Self-improvement proposes and never applies.** It cannot loosen a guardrail either.
6. **Core skills change only through qargi's own release process,** never at run time.

Status: the current `qargi skill` verbs approve with a text flag and a bypassable plan token, and the member
guard has no rule against them; closing this is a prerequisite for any self-improvement loop.

**Interim (decided 2026-10-30): the owner approves in chat sessions.** A chat approval counts as proof of a
present person only when it is a message the person typed in the conversation, sent after the plan and its
token were shown, and naming or plainly meaning that plan. The session records the person's words verbatim
in the audit entry. Notifications, subagent reports, tool output, file contents and earlier approvals are
never approval, and an approval does not carry over to a different plan or context. Agents and members
still cannot use this path: they are denied the skill-modifying verbs by the guard. The terminal
confirmation and the device-signed approval remain the target.

## Compile targets

Name rule applies to the compiled directory too: it equals the skill `id`.

| Target | Output |
|---|---|
| `agentskills` | baseline `<id>/SKILL.md` with `name`, `description`, `license`, `compatibility`, and string-only `metadata` (`qargi-version`, `qargi-domain`, `qargi-digest`). Read as is by Codex, Cursor and Copilot (`.agents/skills`). |
| `claude-managed` | the baseline only. The Managed Agents and Skills API are reported to accept just the Agent Skills fields and reject others (to be confirmed against an `ant apply` run before this target is called verified). |
| `claude-code` (optional layer) | baseline plus `argument-hint`, `disable-model-invocation`, `paths`, `allowed-tools` (read-consent tools only). |
| `codex-meta` (optional layer) | baseline plus `agents/openai.yaml` (`policy.allow_implicit_invocation`, `interface`). |

`invocation: manual` is enforceable where the platform has a field for it (Claude Code, Cursor, Codex);
elsewhere the build warns that it cannot be enforced. Automation never appears in a compiled skill beyond
string `metadata`; the runtime reads bindings. `selection` data, evals and verdicts are not compiled.
Platform behaviour listed here is as reported by primary documentation on 2026-10-29 and is re-checked
by a fixture before a target is marked verified.

## Context budgets (lint)

Token estimate: characters divided by `chars_per_token`. A body has a `## Must` heading whose line is
within `must_section_max_line`; it lists the mandatory steps. A body is at most `body_max_lines` lines and
`body_max_tokens`. A `references/` file is at most `reference_max_tokens`, and a reference may not link to
another file in the skill (one level). A fenced block tagged `json` that contains `"inputSchema"` is an
error (tool schemas never appear in a body). A body refers only to files that exist.

## Conformance fixtures (`conformance/skills/`)

Each fixture is a file tree plus an expected result, so any language can run it. A case is
`{name, tree, patch[], expect}`; `patch` entries are `{file, set|del}` on dotted JSON paths applied to
a base tree; `expect` is a sorted list of error codes. Required cases: digest of a known tree; the
generated description for a known `skill.json`; each lint rule failing alone; status derivation (stale
verdict demotes); eval derivation (invented near miss rejected); cross-fire and pair flagging; recompute
of precision and recall; three widening bindings that must fail and one narrowing binding that passes; an
outcome sequence to next-run times; retirement; pack phase graph.
