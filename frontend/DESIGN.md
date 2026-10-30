# Frontend and generative UI (design draft 1)

Status: draft for review. Nothing here is implemented, and the frontend itself is for later. This document
exists so decisions made now do not force breaking changes then. Decisions the owner made are marked
**Decided**; the rest is a proposal from a design analysis whose sources (Expo, A2UI, json-render, MCP
Apps) are fast-moving and not all verified.

## Requirement

A frontend with a mobile focus (React or React Native, or something more appropriate), extremely simple,
very few pages, ideally an advanced chat interface with dynamically built controls, actions and widgets.

## Decided

- **Technology:** React Native with Expo. One TypeScript codebase for iOS, Android and web. The web build
  covers desktops and laptops. Nothing in the backend may assume a browser DOM: every payload must be
  renderable by native components.
- **Pages:** five screens. **Chat** (default; one thread per session, widgets inline, a deployment
  switcher in the header), **Inbox** (pending approvals, plan previews, failed unattended runs, quarantined
  memory notes; the badge count equals the push count), **Library** (packs and skills, the phase
  questionnaire, verdict status), **Connections** (connector types, accounts, bindings, OAuth start,
  token health), **Settings** (deployments, pairing, notifications, the audit viewer).
  Chat-native widgets, not pages: schedule card, session cost and budget, plan preview with approve, the
  pack phase questionnaire, memory-note review as a diff.
- **Widgets:** an own allowlisted catalogue, `qargi.ui/v1`, rendered on mobile with the json-render React
  Native renderer. A2UI conventions (catalogues as JSON Schema, advertised `supported_catalogs`, a
  fallback for unknown components) and AG-UI event names are borrowed, not adopted whole. MCP Apps HTML may
  later appear only as an untrusted inbound card.
- **Approvals:** a biometric confirmation for `external`, `destructive`, money, push or publish actions; a
  device passcode for the rest. The assertion level is logged.

## Widget model (Proposed)

- **Catalogue** (about 15 components, each with a JSON Schema; the catalogue file is the contract and ships
  in `conformance/ui/`): `text`, `markdown` (sanitised, no raw HTML, no images), `kv`, `table` (bounded),
  `list`, `badge`, `progress`, `diff`, `code`, `form`, `field` (string, number, boolean, enum, multi-enum,
  date), `button`, `link`, `image` (deployment-proxied only), and `approval` (special, below).
- **Descriptor:** `{widget_id, catalog, component, props, children[], data_bindings?, actions[], summary,
  size_hint}`. `summary` is mandatory plain text: the CLI prints it, a screen reader reads it, and an older
  app shows it. Limits: 16 KiB per descriptor, 50 table rows, depth 6, 200 nodes.
- **Life cycle:** a widget is the rendering of a tool part with states `streaming`, `ready`, `updated`,
  `expired`, `error`. Updates are JSON Patch deltas against `widget_id`; the client may request a snapshot.
  A widget is immutable once an action has been taken on it.
- **Actions:** `{action_id, kind: submit|approve|deny|open|navigate, payload_schema, target}`. An action is
  a `widget-action` event carrying `widget_id`, `action_id`, `descriptor_digest` and the user's payload,
  never a string the model wrote.
- **Forms from skills.** A skill's `arguments[]` (with a type and `ui` hints) derives a `form` widget;
  `result_schema` and `result_ui` derive result widgets. The form subset is flat primitives, as in MCP
  elicitation.
- **Degradation.** The client states `supported_catalogs[]` at session start. An unknown component renders
  its `summary` and a "newer app needed" chip. An invalid descriptor returns a validation error to the
  model once, then falls back to text.
- **Accessibility and size.** Every component has an accessible label from `summary` or `label`; touch
  targets at least 44 pt; no colour-only state. The model emits component names, not markup.

## Security (Proposed; follows the guardrails draft)

- A widget payload is **output** (`widget` channel, outbound): validated against the catalogue, scanned by
  the mandatory secret and PII pre-scan, with link and image targets limited to deployment-relative or
  allowlisted hosts, and assigned a `descriptor_digest`.
- A widget action is **input** (`widget-action`, inbound, origin `user`, correlated to the widget). It is
  trusted as the user's only if its digest matches a widget the engine emitted; otherwise it is blocked.
- **An approval is never a widget the model draws.** The `approval` component takes only a `plan_token`.
  The client fetches `GET /approvals/{plan_token}` and renders the server-generated `approval_summary`
  (effect class, audience, money, reversibility, data classes, the exact command or diff digest) in a fixed
  system style the model cannot imitate, outside the message bubble. Approve sends `{plan_token,
  descriptor_digest, biometric_assertion?}`; the server refuses if the plan changed, which is today's
  plan-token rule. The full digest and plan text are stored server-side; the 12-hex form stays as the
  display token only.
- **Clickjacking and spoofing.** A model widget may not carry a button whose label is a reserved word
  (approve, allow, confirm, localised). A `button` can only `submit` to the model or `open` an allowlisted
  link; only the client-drawn `approval` can carry `approve` or `deny`. `badge` and `text` cannot use the
  reserved style tokens.
- **Exfiltration and links.** The client never fetches a model-supplied URL directly. Link text and
  destination are shown together. Deep links (`qargi://`) open the app to `inbox/{plan_token}` or
  `session/{id}` only and perform no action.
- **Peers and MCP.** A federated peer's widget arrives with origin `peer:<ns>`, lowest trust, an origin
  banner, and actions disabled except opening its plan summary.
- **Reserved rule ids:** `ui.reserved-label`, `ui.unlisted-component`, `ui.link-not-allowlisted`, `ui.size`.

## Backend API (Proposed; protocol level)

- **Events:** server-sent events, `GET /v1/sessions/{id}/events/stream`. Every event has a monotonic `seq`
  and an `id`; clients resume with `Last-Event-ID`; widgets are rebuilt from the durable event log.
  All client writes are idempotent POSTs (`Idempotency-Key`); approvals are idempotent on the plan token.
  Cursor pagination, never offsets.
- **App to deployment auth:** device pairing first (a QR code carries a short-lived pairing code; the phone
  gets a device-bound refresh token and registers a device key that signs approvals). External IdP
  OAuth and passkeys are later upgrades.
- **Multi-deployment:** one credential per deployment, never shared; the Inbox merges the streams.
- **Push:** ids only, `{deployment_id, kind: approval|run_failed|budget_tight, ref}`, under the relay's
  payload cap, with no Approve action on the notification: approving requires opening the app and
  verifying. Whether qargi runs its own relay or uses Expo's is open.
- **CLI:** `qargi watch` and `qargi send` become clients of the same stream and POSTs; widget events print
  their `summary`.

## OAuth2 on mobile (Proposed; refines CONNECTORS.md)

The **deployment** is the OAuth client, never the phone. The phone opens the system browser (not an embedded
web view), the provider redirects to the deployment's HTTPS redirect URI, and the deployment exchanges the
code with PKCE and keeps the tokens. The deployment then returns to an app link carrying only a one-time
`binding_id`. Device-code is the headless path. On the phone live only the deployment refresh token and the
device key, in the platform keystore, locked to the device. Never on the phone: provider tokens, client
secrets, API keys, plan contents above `internal`, memory notes. This needs a deployment reachable at an
HTTPS redirect URI for a phone-started flow; the earlier decision that Managed Agents roles are consented on
the owner's machine still holds for that case.

## Approvals at scale (Proposed)

Approve plans, not actions; one plan token covers a run's tier-2 actions, and pending items group by plan.
Expiry to skip stays server-side and the push says when it expires. At most one push per plan; an hourly
digest mode for unattended runs per binding. "Asks per run" is shown on the schedule card, so the owner
narrows a binding instead of tapping.

## Decide now (applied in library/SPEC.md and guard/DESIGN.md)

Skill arguments get a `type`, constraints and a `ui` hint; `result_schema` and `result_ui`; an
`approval_summary` template; `i18n` hooks; a `ui_max_chars` policy limit. Guardrail channels `widget`,
`widget-action` and `approval`; `descriptor_digest` on widget events; `device_id` and `auth_level` on an
approval decision; `client_hello` with `supported_catalogs[]`, locale and app version. Memory notes default
to `renderable: false`, so memory text is never a widget source without promotion. The outcome record gains
an optional typed `result`.

## Risks and deferrals

Regrets to avoid: model-emitted HTML, approve buttons inside model-drawn widgets, provider tokens on a
phone, an API only a WebSocket client can speak. Risks: A2UI and json-render are young, so pin versions
and own the catalogue file; Expo's yearly SDK churn; the Apple developer account and a push relay.
Deferred: inbound MCP Apps rendering, passkeys, A2UI wire compatibility, localisation beyond a default
language, desktop native.

## Open questions

1. Is the phone a client of the owner's own deployments only, or also of shared team deployments (pairing
   versus an identity provider)?
2. Is a deployment reachable from the internet, or only on a LAN or VPN (push relay and OAuth redirect host)?
3. Will qargi run its own push relay or use Expo's?
4. Is English the only language in v1?
5. Must the CLI render widgets as text in v1, or only print summaries?
6. Is model-emitted Markdown allowed at all, or only `text` plus structured components?
