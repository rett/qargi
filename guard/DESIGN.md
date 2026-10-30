# Guardrails layer (design draft 2)

Status: draft for review, revised after an adversarial review. Nothing here is implemented. Decisions the
owner made are marked **Decided**; everything else is a proposal and is marked **Proposed**.

## Purpose

A governance layer between the harness and the model. It owns user gates and the detection or containment
of prompt injection, hallucination, off-topic drift, data leakage, toxic or biased output, brand damage,
unsafe actions, cost runaway and memory poisoning. "brad damage" in the request was read as brand damage.

## Decided

- **Five layers.** Input, prompt, output, action execution and memory write.
- **One engine, thin adapters.** A single policy engine (`qargi guard`) fed by platform adapters. No API
  proxy. Python first, Go later, one set of language-neutral fixtures.
- **Classifiers are pluggable.**
- **MCP, inbound and outbound, is a design constraint, not a deliverable.** Nothing MCP-specific is built
  now; the event model must take it without a redesign.
- **Domain neutrality.** qargi is not for code only; code is the first domain because the team builds it by
  using it. The core assumes no domain; domain specifics live in policy packs, code being the first.
- **Reads.** A read is "open" only if it changes no state, has no egress outside an allowlist and touches
  data below a sensitivity threshold. An action of unknown effect is risky. A read of a credential or PII
  path fails closed when its check is unavailable.
- **Contained writes (tier 1), unattended, check unavailable.** Allowed and the run is marked
  `unverified`, only where a human apply step follows; where an action takes effect with no human step it
  is denied. `qargi-verify` refuses to apply an unverified run without a person.
- **Skill modification.** Only core, built-in, qargi-sanctioned skills may modify a skill, only by invoking
  host verbs, and always with proof that a person is present (a typed confirmation at the terminal or a
  device-signed approval; never a flag, an environment variable or a string in a prompt). Agent tools and
  shells are denied writes under skill directories. Self-improvement may propose a change and never apply
  one. See `library/SPEC.md`, "Who may modify a skill".
- **Cloud memory.** The recipes store is mounted read-only on Managed Agents; agents write notes through a
  qargi-run `memory_note` tool, and unreviewed notes are quarantined.
- **Schema 1 now, implementations later.** Data classes, effect class, reversibility, audience, money,
  verification kind and an `external` consent level ship in skill schema 1 (see library/SPEC.md).
  Toxicity and hallucination classifiers stay deferred.

## Domain neutrality

The core is domain-free: layers, events, trust levels, classifiers, tiers, exceptions and the audit record.
A **policy pack** supplies a domain's specifics: command classes, secret and PII patterns, path globs,
publication surfaces, rubrics and regression sets. The code domain (git/gh/ssh command classes, gitleaks,
executable DONE checks) is the first pack. Consequences:
- Toxic, biased and brand-damaging output, PII and unsupported prose claims are first-class concerns.
- "Executable check" is one **verification kind** among `executable`, `rubric`, `source-resolves`,
  `second-reader` and `human`. The review ability already is a second reader; register it as a classifier of
  kind `agent-review` rather than building a judge.
- An action is classified by its effect on the world, not by being a shell command: `effect_class`
  (`send`, `post`, `publish`, `pay`, `delete-record`, `modify-record`, `commit`, `push`), `reversibility`
  (`reversible`, `compensable`, `irreversible`), `audience` (`private`, `internal`, `named-external`,
  `public`) and `money`. The old "publication boundary" is `audience` at or above `named-external`.
- False-positive regression sets are built per pack from that domain's own runs.

## Layers

| Layer | Subject | Typical checks | Outputs |
|---|---|---|---|
| L1 input | what a human, event or peer submits | structure, secret and PII patterns, forbidden-intent patterns, origin tag | allow, block, escalate (a hook can block here but not rewrite) |
| L2 prompt | everything assembled for the model: system prompt, skills, memory, reference, tool results, tool descriptions | provenance in the audit record (not in the prompt), tool-description digest pinning, secret scrub, size budget | allow, transform (tool results where the platform permits), block, warn |
| L3 output | model text and proposed tool calls, before they run | action vs TASK and SCOPE, secrets and PII in text, source check on deliverables | allow, block, escalate |
| L4 action | execution of an approved call | egress allowlist, effect and reversibility, budget counters, denial loops | allow, ask, deny |
| L5 memory | writes to memory, skills, packs, federated imports | provenance, instruction-like text, cross-role writes, stale digests, quarantine | allow, quarantine, block |

Text layers advise and tag; action layers decide. A text-layer verdict never widens what L4 or L5 permit.
**L5 is split in two:** (a) a real gate on curated writes (`shared/`, reference store, pack import,
federated import, plan-token gated, already mostly in `packs.sh` and `memory.sh`); (b) a post-session
reconcile that quarantines agent-written notes in a `quarantine/` folder that session-start does not load
until they are linted or promoted. Locally a `PreToolUse` matcher on `Write|Edit` over the store paths gives
(a); on Managed Agents the `memory_note` tool does.

## Event model (Proposed)

Adapters supply what they can see; the engine derives the layer, so adapters cannot disagree about it.

```
event = {
  id, correlates_to?                   # a later event refers to the one it answers
  phase:     proposed | pre-exec | post-exec | input-request | deferred-result
  channel:   user | operator | event | peer | skill | memory | reference
             | tool-call | tool-result | tool-description | session
             | widget | widget-action | approval        # see frontend/DESIGN.md
  direction: inbound | outbound        # relative to the agent session
  origin:    user | operator | skill:<ref> | tool:<name> | mcp:<server-id>@<principal> | peer:<ns> | system
  sources[]: [{origin, trust}]         # everything that contributed; trust = lowest of these
  payload:   text or structured arguments (digests, never secret values)
  descriptor_digest?                   # on tool-description events (rug-pull pinning) and on widget and
                                       # widget-action events (an action is trusted only if its digest
                                       # matches a widget the engine emitted)
  device_id?, auth_level?              # on approval events: which device, and none|passcode|biometric
  context:   {skill, binding, role, ability, unattended, task, scope, effect_class, reversibility,
              audience, money, data_classes[], risk_tier, session_taint}
  policy_version
}
session events: start | checkpoint | deliverable | end   # carry counters, task and scope
                                                          # start may be a client_hello: supported_catalogs[],
                                                          # locale, app version
layer = derived(channel, phase, direction)                # a view, pinned by fixtures
decision = {action: allow|warn|transform|ask|deny|quarantine, rule_id, classifier_ids[], reason,
            evaluated_permission, transform?}
```

Session events carry what per-call events cannot: drift against the task, cost counters, and a
deliverable boundary where source-resolution, audience and toxicity classifiers run once.

**MCP adaptability (design only; reflects the 2026-07-28 revision as Fable read it, to be re-checked
before an MCP adapter is built).** Outbound MCP: a call is a `tool-call` (phases `proposed`, `pre-exec`,
`post-exec`), descriptions and results are `tool-description` and `tool-result` with origin
`mcp:<server>@<principal>`. Server requests for more input arrive inside a result as `input-request` and
the client's retry that carries the user's answer is an outbound decision, so a server asking for a
credential is caught like any disclosure. Long-running calls produce a `deferred-result` after the
decision. Tool annotations (read-only, destructive hints) are classifier inputs, never the risk tier.
Inbound MCP (qargi serving tools): requests are inbound `tool-call` or `session` events from
`mcp:<client>`, responses outbound. No rule or classifier needs to know the protocol.

## Trust levels (Proposed)

`user > operator (profile, CLAUDE.md) > local accepted skill > reference store > memory store >
local tool result > mcp-server result > federated skill, peer task and mcp-client request`.
A skill that has been accepted locally takes its trust from the local verdict and digest, not from its
namespace, otherwise acceptance would mean nothing. An event's trust is the lowest across `sources[]`.

## Pluggable classifiers (Proposed shape; pluggability is Decided)

```
{id, kind: rule | local-model | llm-judge | http | mcp | agent-review,
 channels[], phases[], applies_to{pack, platform, ability, unattended}, timeout_ms, cost_class,
 egress: local | remote, data_classes_allowed[], pin: digest | version+schema+approval,
 on_error: {tier0: open-with-warning, tier1: per the tier-1 rule, tier2: closed}}
```

Interface: `classify(event) -> {verdict: allow|warn|block, score, label, reason}`.
- A **mandatory local, deterministic pre-scan** (secret and PII patterns) assigns `data_classes` first;
  `unknown` counts as the highest class present. No remote plugin sees a payload before that.
- Order is cheap first; a costlier classifier runs only on suspicion, on tier 2, or at a `deliverable`.
- Any `block` wins; `warn` verdicts aggregate toward `ask`. A plugin below its minimum measured precision
  has its `block` degraded to `warn`, so one bad plugin cannot stop the pipeline.
- A classifier failure on a text event yields `warn` plus an `unchecked` tag that any later tier 1 or 2
  action in the session inherits.
- A classifier's output is untrusted: never concatenated into a prompt, only mapped to a verdict. An
  `llm-judge` reads untrusted text, so it is itself an injection and exfiltration target and may be
  `remote` only for data classes at or below `internal`.
- Local plugins are pinned by content digest. An `http` plugin cannot be pinned, so it needs a URL,
  a declared version, a response schema and an approval record, and is refused for data above `internal`.
- A model-based classifier is a skill-shaped component: it earns acceptance through the trial machinery in
  library/SPEC.md (digest, recorded results, precision and recall, two selectors). Engine fixtures use stub
  classifiers whose verdicts the fixture supplies; model classifiers are tested by trial, not by fixture.

## Risk tiers and failure policy

Tier of an action, from effect, reversibility, audience, money and data class:
**0 read** (no state change, no egress beyond an allowlist, data below the threshold),
**1 contained write** (inside the clone or the role's own memory folder),
**2 risky** (external effect, `audience` at or above `named-external`, money, irreversible, out of scope,
credential use, publication, unknown effect). An arbitrary shell command or an MCP tool without a known
effect is tier 2, never 0. A GET to a host outside the allowlist is tier 2.

**Session taint.** Once a session has read data above `internal` and consumed untrusted input, every
outbound action is tier 2 regardless of verb. This applies the Rule of Two per session, which tiers per
action cannot.

Unattended, with a check or an approval unavailable: tier 0 proceeds with a warning, except a read of a
credential or PII path, which fails closed; tier 1 proceeds and the run is `unverified` where a human apply
step follows, and is denied otherwise; tier 2 is denied and the run ends with outcome `error`. An unanswered
approval expires into `skip`, never `allow`. Interactive sessions ask the person.

## Gates (Proposed)

Always ask, no exception possible: push or publish, external communication, credential use, destructive or
irreversible actions, money, budget raise, writes to `shared/` memory or a reference store, any
modification of a skill (create, edit, import, seal, remove, accept, overlap decision), creating or
widening a binding, changing peer trust. "Ask" means proof of a present person, as defined under Decided;
today's `--approved "<words>"` flag does not meet it (verified: any caller can supply the words, and the
`QARGI_NESTED` environment variable skips the plan-token check in `need_plan`). Pre-approved by a binding that only narrows:
reads, in-clone edits, notes under the role's own memory folder, scheduled runs within budget. Approve
plans and bindings, not each action. Measure asks per run as a tracked metric.

## Policy as data (Proposed)

`guard/policy.json`, schema 1: `rules[] {id, owasp, layer-view, channel, phase, applies_to{pack, ...},
match, action, severity, since}` with match kinds `regex`, `command_class`, `path_glob`, `trust_flow`,
`budget`, `effect`. Rule ids map to the OWASP agentic and MCP top-ten ids for audit. Exceptions are
records `{rule_id, scope, granted_by, asked, plan_token, expires, reason}`, never edits. Audit lines extend
the existing audit log with `event_digest, rule_id, classifier_ids, decision` rather than a second log.

## Testing

`conformance/guard/` fixtures `{name, event, policy_version, expect}`: each rule alone, the layer
derivation, session taint, tier assignment for unknown effects; a red-team set (injected tool results,
poisoned memory notes, a changed tool description, a server asking for a credential, exfiltration through
a commit message, a forged provenance trailer); and per-pack benign regression sets with a stated
false-positive budget. A policy change fails CI if the budget or a red-team case regresses.

## Platform reality (per current docs as Fable read them; to be re-checked before building each adapter)

- **Claude Code hooks:** `UserPromptSubmit` can block, not transform. `PreToolUse` can allow, deny, ask or
  rewrite arguments. `PostToolUse` can rewrite a tool result, MCP included. Skill bodies and memory reads
  have no hook. Model prose cannot be transformed. Hooks fail open on error or timeout unless a hook sets
  `onFailure: "block"`; `agents/member.md` sets none, so the existing guard hook should. In `-p` mode an
  `ask` with nobody present is denied.
- **Managed Agents:** nothing can alter a tool result or model text. `always_allow` cannot be intercepted;
  `auto` denials cannot be overridden by the client, and `auto` reads user messages as operator intent, so
  a peer task relayed verbatim in a user message inflates its trust (wrap it as data, or use `always_ask`).
  Memory stores are mounted filesystems with no hook. A scheduled run that pauses for approval waits
  indefinitely unless a webhook handler answers; the expire-to-skip rule lives in that handler.
- **Memory backend and pack import:** real, host-side gates. `packs.sh` review and drift check is already
  an L5 adapter; register it instead of duplicating it.

## What a guardrail cannot do

Detect every injection; verify the truth of prose; stop a covert channel inside an allowed output when
egress exists; judge taste. Honest coverage: real controls for unsafe actions locally, curated memory writes
and pack import, and data leakage where egress is structurally absent; tripwires for injection, drift,
toxic or biased output and brand damage (real control only via `audience` at or above `named-external`
forcing a human); no control for hallucination in prose beyond source-resolution and a second reader.

## Deferred

Toxicity classifiers, hallucination judges for prose, an API proxy, a policy language such as Cedar, the Go
port, and any MCP adapter. Their schema fields are not deferred.

## Open questions for the owner

1. Is any run allowed unrestricted networking while it reads data above `internal`? (Recommended: no.)
2. Which non-code effect class ships first: send, post, publish, pay or modify-record?
3. Is `verification_kind: human` enough for an unattended run that ends in an external deliverable, or must
   such a run be `unattended: never`?
4. Who or what answers a cloud approval, and is 15 minutes the right expiry before `skip`? (Recommended:
   a webhook handler denies after the lesser of the binding's `max_runtime` and 15 minutes.)
5. Which data classes will agents handle across the planned domains? (Default enumeration: public,
   internal, confidential, pii, phi, financial, credential, legal-privileged, unknown.)
