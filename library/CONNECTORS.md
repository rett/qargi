# Connectors, accounts and bindings (design draft 1)

Status: draft for review. Nothing here is implemented. Decisions the owner made are marked **Decided**;
the rest is a proposal taken from a design analysis whose provider-specific facts are not all verified.

## Requirement

MCP and OAuth2 support for any number of account connectors, and each platform or product has its own set
of skills.

## Decided

- **Three objects.** A **connector type**, an **account** and a **binding**. The scopes an account has
  consented to are a field of the account, not a fourth object.
- **Shared accounts.** A user-owned account is never used by more than one role. Only `service` or `org`
  accounts can be shared, and then only for `read` consent tools unless the owner approves.
- **Tool changes.** A changed description of a pinned tool needs re-approval but does not demote
  dependent skills. A changed input schema demotes them to `draft`. A removed tool fails their lint.
- **OAuth consent for Managed Agents roles.** The human consent runs on the owner's machine (authorization
  code with PKCE), and the resulting credential is stored in the platform vault. No hosted callback for now
  (revisit with the mobile frontend).
- **Money.** There is no separate `financial` consent level. `external` consent together with
  `effects.money = true` always asks. (A judgment call; the analysis proposed a level above `destructive`.)

## The three objects

| Object | Lifetime | Where it lives | Shared across deployments |
|---|---|---|---|
| connector type | follows the provider's releases | `library/connectors/<id>/connector.json` and `tools.pinned.json` | yes, as a signed catalog item |
| account | follows a person's consent | outside every repository: `<config>/qargi/accounts/<account_id>.json`, one file per account | never |
| binding | per project, schedule or run | `automation.json` (`accounts`) | no; an imported binding is invalid until re-bound |

Skills reference a connector by `tools[].server_ref`, which resolves through the type to a server, plus an
optional `capability` name (for example `calendar.read`) as the portable name, so a skill survives a
provider swapping its server. A skill never names an account.

### Connector type (`connector.json`, schema 1)

`{schema, id, version, provider, servers[{server_ref, transport: http|stdio|gateway, url|command,
auth{methods[], registration: preregistered|cimd|dcr, client_id?}, tool_catalogue_digest}],
scopes{<scope>: {description, consent}}, data_classes[], rate_limits{rpm, daily, concurrency}, quirks{},
testing{cassettes, fake_server, sandbox}, modes[user|service|org], federation{publish}}`.
`tools.pinned.json` holds a sha256 per tool over its name, description, input schema and annotations.
A public `client_id` belongs in the type; a `client_secret`, where a provider insists, is a secret
reference and never appears in a catalog file.

### Account

`{id, type, owner: user|service|org, label, platform_secret_ref{local, managed}, granted_scopes[],
expires_hint, status, created, last_verified}`. It never contains a token. `platform_secret_ref` has two
slots: an OS keychain item (encrypted file fallback) for local use, and a vault id plus credential id for
Managed Agents.

### Binding

`automation.json.accounts` maps `server_ref` to an `account_id` or to `{select: prompt|default|by_label}`.
An interactive run with no binding and more than one account for a type asks; it never picks silently.
A binding fails at bind time if the platform adapter lacks interactive OAuth and the account has no managed
slot.

## Connector skill packs

One connector type has one pack (`pack.json` with `connector` and `connector_version_range`). The pack's
phases are the anti-bloat tool: which part of the product, then read or act, then the task. A lint requires
that every path through the phases yields an attached set within `attached_set_budget_chars`. Connector
packs are `cross_domain: true`; domain packs refer to connector skills by `namespace/id` and never copy
them. Provider-supplied skill text is only `adapted` evidence, rewritten under the normal rules; federated
packs arrive as drafts. The pack version is independent of the type's.

In a skill, `tools[]` entries are `{server_ref, capability?, tool_names[], scopes[], mode, consent}`.
Lint: each tool name exists in the type's pinned catalogue; each scope exists in the type's scope table;
the skill's consent is at least the type's consent for that scope.

## Tracking upstream

MCP has no tool version or hash, so qargi pins. `qargi connector refresh <id>` diffs the live tool list
against the pin: description change goes to re-approval (a `tool-description` event in the guardrails);
schema change demotes dependent skills to `draft`; removal fails their lint with a deprecated-tool code.
Tool annotations (read-only or destructive hints) are untrusted input to the consent class, never the
decision.

## OAuth2

Supported now: authorization code with PKCE, `client_credentials` for service identities, refresh.
Designed in, deferred: enterprise-managed authorization, token exchange, DPoP, gateways. Device code is not
in the MCP specification and is used only for a provider's native API through a provider adapter.
Registration priority: pre-registered, then client-metadata document if the authorization server supports
it, then dynamic registration, then prompt. Each deployment may host one client-metadata document
(`deployment.json.cimd_url`); a deployment that cannot (air-gapped) uses pre-registered clients.

- Scopes requested are the union of the scopes of the skills attached to the role for that connector,
  recorded in `granted_scopes` and recomputed when the attached set changes.
- Unattended runs never step up scope. They end with outcome `error` and an alert.
- Revocation: `qargi account revoke` calls the provider's revocation endpoint where one exists, archives
  the vault credential, deletes the keychain item and writes an audit line. An account bound to a binding
  cannot be removed.
- Never present in a skill, binding or log: access or refresh tokens, client secrets, authorization codes,
  PKCE verifiers, `Authorization` headers, vault credential bodies. Logs carry `account_id`, `type`, scope
  names and token digests.
- Provider quirks go in `connector.json.quirks` and are fixtures (for example a short refresh-token
  lifetime in a test-mode app, or single-use rotating refresh tokens).

## MCP integration

Direct connection per platform for v1; a gateway is deferred, and `transport` allows `gateway` later. stdio
servers take credentials from the environment, are local-only, and cannot run on Managed Agents. A role's
tool allowlist is the union of the `tools[]` of its attached set, emitted as an allowlist on every
platform. This is the invariant, because Managed Agents has no tool search and quality degrades beyond
roughly 30 to 50 loaded tools; platform deferral is a bonus. `policy.json` gains `role_tool_budget`
(proposed: 40 enabled tools, 12 non-deferred). A platform adapter's `describe()` reports
`{oauth_interactive, vaults, stdio, tool_search, allowlist}`.

## Guardrails interaction

Data classes come from the connector type; a tool result inherits them and the skill's `data.reads` must
cover them. A connector result is trust `mcp-server result`. Every write tool is an egress sink with the
audience the type declares. A bind-time lint refuses a role that holds, in one attached set, a user-owned
account with a write egress tool, a connector whose results are `mcp-server` trust, and data above the
egress audience; a flagged pair needs an exception record. Account-changing actions (grant, revoke, scope
step-up, sharing) always ask. Audit records carry `account_id`, `type`, scopes used and the tool digest; an
outcome record gains `accounts_used[]`.

## Operations

Rate limits are type defaults with account overrides, counted per account across bindings. `qargi account
check` does a read-only probe and records `last_verified`; a scheduled health skill alerts on an
expiring token or two consecutive authentication errors. A Managed Agents vault is per owner, not global
(a per-vault credential cap is reported but unverified). A listing shows `id, type, owner, label, status`
and never reads a secret.

## Testing without accounts

Acceptance needs recorded MCP traffic (cassettes, kept as language-neutral fixtures and scrubbed by the
secret lint) and a fake server for write paths. Real sandbox accounts are a scheduled health check, not a
gate.

## Reuse and avoid

Reuse the MCP SDKs for the auth flows, an MCP recording tool for cassettes, OS keychain libraries and
Managed Agents vaults. Do not adopt hosted credential brokers yet: a service holding tokens for many
accounts is the single point the federation design refuses.

## Fixtures needed

Pin diff classification, phase-path budget, cross-account write refusal, account resolution per platform,
cassette replay, and a binding that fails when the platform has no managed slot.

## Open questions

1. Which providers are the first three connector types?
2. May a deployment host a public HTTPS document at all, or is pre-registration the baseline?
3. Is enterprise-managed authorization a requirement for the first customers or only a design constraint?
4. Which actions count as money-moving, and do quota-consuming actions (bulk mail, paid API calls) count?
