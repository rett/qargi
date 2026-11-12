Load when verifying, attesting or enabling a runtime or extension.

# Verification, attest, extensions

## What counts

The review of a pack with executables gives each one's path, sha256, interpreter, first lines, the URLs and network commands it mentions and the commands the argv would run. qargi runs an approved executable only from a private copy, after its hash and the pack's were checked against the sealed record.

- A shipped definition is verified by the `verified_on` date and `source` of each cell.
- A library definition is verified by `qargi provider check NAME` on the sealed pack, which records every capability whose hermetic cases all pass in `state/providers/NAME/verified.json`, bound to the content hash. An edit and a reseal, or a reseal of the runtime an extension extends, make the record stale until `check` is run again. The hermetic cases are the agent render twice and read back, the skills link planned, applied and undone in a temporary repository, the read-only corpus through the guard, an adapter's stub, and the read-only arguments of a `sandbox-args` barrier (that case can only hold the claim back).

## Attest

A fact no hermetic case can show (an OS sandbox that really holds, a real model id, a cost report) is `qargi provider attest NAME CAP`. It records a check that the person ran; it runs nothing and spends nothing itself. **Attest is asked each time.** Never run a live check, or suggest the person has pre-approved one, on your own initiative. Without the facts the verb prints what is needed. Before any run, tell the person: the runtime and the capability; the exact command or API calls and the scratch resources; the smallest model and effort; the hard ceiling in cents or tokens; the expected cost and how it is cleaned up. Only on their go-ahead, after the run: `qargi provider attest NAME CAP --asked "<their words>" --did "<what was run>" --result pass|fail --cost-cents N --cleanup "<state>" [--note TEXT]`, then the plan token as for any change. A failed result removes the earlier record. A free local check that makes no API call needs no spend ask but is recorded the same way (`--cost-cents 0`).

## A sandbox runtime

A runtime held by `sandbox-args` (the shipped `codex`) passes `bash tests/conformance.sh NAME`, which shows only what qargi passes. What the runtime does is checked live, in a scratch repository, each check asked first as above:

- **Barrier, free**: the sandbox alone with no model call (`codex sandbox`; its `--help` says how a mode is chosen): a write in the scratch directory is refused under read-only and allowed under workspace-write.
- **Smoke run**: one `qargi local run` on the fast tier at `low` effort: the run signs in through the run home's link, the last message lands in `OUT/report.md`, and `USAGE=` shows the tokens. A model or effort override is verified only when an event names what was used.
- **Before members rely on it**: a sign-in the runtime rewrites during a run reaches your file, through the link or written back; the MCP tool names have the form of `permission_rule`; `enabled_tools` hides a server's other tools; a write member can commit (the write class makes the clone's `.git` writable); the run's `baseline` holds (no approval asked, no network for commands, no hosted search, the features it turns off are gone) and a clone's own `.codex/` does not load. The offline checks of what loads, with a scratch `CODEX_HOME` and no sign-in, cost nothing: `codex debug prompt-input`, `codex mcp list --json`, `codex features list`.

A shipped runtime records each result as `verified_on` and `source` in its definition, a change to the repository; a library pack records it with `attest`. The shipped `codex` has headless dispatch, its barrier (partial) and its token report verified (codex-cli 0.167.1, 2026-11-11), so a review role runs on it without `provider accept`; its model and effort overrides (no event names them), skills and MCP are not verified.

A read-only role on a surface whose barrier is not supported is refused unless the person accepts that for the project: `qargi provider accept NAME --surface S --no-barrier --asked "..."` (plan token, then `--plan TOKEN --approved "..."`).

## Extensions

`qargi provider new NAME --kind extension` scaffolds one: `extends` (a runtime or family), `provides` (capabilities), `requires` and `adds.capabilities` (plus barrier, dispatch variants, renderers, resources). Seal it, then `qargi provider enable PROJECT NAME` (a plan and approval, with `--approve-exec` for executables); `disable PROJECT NAME` undoes it. Extensions are per project only (`models.extensions` in the answers). Nothing is overridden: two extensions that add the same thing, or one that adds what the runtime already has, are refused, naming both. What an extension provides counts only after `qargi provider check NAME [--project P]` passes for it, or an attest, and `provider show RUNTIME --project P` shows which pack provided each capability.
