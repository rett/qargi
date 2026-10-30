# Federation of qargi deployments (draft)

Status: draft. Moved out of the skill spec so that spec stays testable. Decisions already made are marked.

"Seamless" means a skill, pack, task or verdict from one deployment is recognisable, verifiable and
usable on another without renaming, re-authoring or blind trust. It does not mean shared mutable state or
implicit trust. A peer is a source of artifacts and a target for tasks, never a principal that can change
local configuration. Every cross-boundary effect stays behind plan, show, approve.

## Decided

- **Name collisions**: an import is refused until the incoming skill is renamed. There is no aliasing, so
  "names are unique, no precedence" stays true and a compiled directory always equals the skill id.
- **Federated demand**: a publisher's demand cases are kept as evidence (`provenance.remote_evidence`) and
  never count toward the local minimum. A federated skill can be tried, but it cannot be accepted without
  a local baseline.
- **Acceptance**: a person approves `trial → accepted` over mechanical evidence, as `packs import` does.
- **Trust**: a federated skill is never auto-attached. It arrives as a draft with no verdicts and must pass
  every local gate.

## Recommended, not yet decided

- **Topology**: hybrid. Layer 1, mandatory: each deployment publishes a signed catalog (a git repository
  or an export archive), which works air-gapped. Layer 2, optional: live task exchange. Layer 3, optional:
  a hub registry as a cache.
- **Identity**: `deployment.json` (`id`, `name`, `public_keys[]`, `endpoints`, `capabilities[]`) and a
  `peers.json` registry, outside any repository. Audit lines and export items carry `origin`.
- **Namespace**: the `namespace` of a published skill is the `id` recorded in `peers.json` for the key that
  signed the catalog. A catalog whose namespace differs from its peer entry is refused. `local` and the
  names of well-known vendors are reserved. This blocks squatting.
- **Signing**: a detached signature envelope over the digest, ed25519 first, other schemes later. Per-peer
  trust policy `{keys[], auto_import: false}`.
- **Listing form**: `namespace/id`, `summary`, `digest` and nothing else; bodies are fetched on attach.
- **Secrets**: `vault_ids` and other workspace-scoped references are stripped from a published catalog; the
  receiving deployment binds its own.
- **Task exchange**: A2A as the wire model with a qargi extension carrying the task block; tokens are never
  forwarded between hops; the requester attributes cost, the executor enforces its own budget. Deferred
  until a second deployment exists.
- **Platforms**: an adapter per platform whose `describe()` reports capabilities (skills, MCP tools,
  memory, schedules, events, agents, vaults). A binding that needs a missing capability fails at bind time.
- **Versions**: three independent axes: `skill.json.schema`, the catalog format and the task-extension URI.
- **Memory**: federated memory is import-only and read-only, with origin recorded in `Sources:`.

## Open

- The exact signing envelope, and whether Sigstore-style identity is accepted next to local keys.
- How a deployment proves its identity to a peer for live task exchange.
- The catalog archive format, and how it relates to `qargi export`.

## Fixtures needed

Catalog digest verification, signature verification, namespace/peer-key binding, a platform `describe()`
document, collision refusal, and a stub task round trip.
