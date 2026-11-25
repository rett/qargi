# Sending tasks to a second runtime

How a project whose own local runtime is `claude-code` sends chosen tasks to `codex`, by profile or by task, and takes the work back. The rules are in [More than one local runtime in a project](providers.md#more-than-one-local-runtime-in-a-project); this page is the order of the steps. The names are examples: any command runtime of the local surface that is sealed can be the second one.

- [Before you start](#before-you-start)
- [1. Enable the runtime](#1-enable-the-runtime)
- [2. Choose it by profile](#2-choose-it-by-profile)
- [3. Choose it for one task](#3-choose-it-for-one-task)
- [4. Run, take in, review](#4-run-take-in-review)
- [5. Stop using it](#5-stop-using-it)
- [6. Turn on an option of the runtime](#6-turn-on-an-option-of-the-runtime)
- [When something is refused](#when-something-is-refused)

## Before you start

- The project has its own local runtime (`qargi provider runtimes PROJECT` prints `primary NAME`), and the second runtime is a command runtime that is not that one. An in-session runtime cannot be the second one.
- The second runtime can start. For `codex` that is its executable on `PATH` and the members' sign-in, made once and kept apart from your own: `mkdir -p ~/.codex-members && chmod 700 ~/.codex-members && CODEX_HOME=~/.codex-members codex login` ([Codex as lead and as member](codex.md#what-a-member-can-reach)).
- You, the owner, decide the approval. The lead shows you the plan and passes your words on; it never writes the phrase for you.

## 1. Enable the runtime

`qargi provider enable PROJECT --runtime codex` prints the plan and a token and changes nothing. Read it: the executable it would resolve, the link source of the sign-in (`present`, not inside `~/.codex`), that runs sharing it run one at a time, the barrier note, that a read-only member there reads and reports and runs nothing that writes, that the model and effort are requested and not confirmed, the tool packs each role would get and that their MCP servers run outside the sandbox, and the reads warning:

```
reads: members on codex can read the real ~/.codex (sessions, history, sign-in) and whatever else this account can read: reads are not confined
the owner's approval words must contain: "reads are not confined"
```

Approve with your own words, which must carry that phrase: `qargi provider enable PROJECT --runtime codex --plan TOKEN --approved "yes, I know reads are not confined"`. Without the phrase it refuses with `runtime-reads-unacknowledged` and the token stays good, so you can say it again. A runtime whose definition confines reads asks for no phrase. `qargi provider runtimes PROJECT` now prints `extra codex` under the primary.

## 2. Choose it by profile

A profile names the runtime its members run on: `qargi project set PROJECT profiles.codex-build '{"base":"worker","tier":"balanced","effort":"high","runtime":"codex"}'`, and the same for a review profile with `"base":"reviewer"`. It is a plain `project set` (it selects among runtimes you already approved), with a hyphen allowed in the profile's name; a member cannot set it. The tier is read in the catalog of that runtime and the effort in its levels. `qargi agent for build --profile codex-build --project PROJECT` now prints a fifth word, `worker gpt-6.1-terra high codex-build codex`, and `qargi agent models --project PROJECT` shows each profile with its runtime. `qargi project validate PROJECT` refuses a profile whose runtime is not enabled or whose model does not fit it.

## 3. Choose it for one task

`qargi local prepare ... --runtime codex` sends one task to the runtime, whatever the profile says; it wins over `profiles.NAME.runtime`, which wins over the project's own. When the profile names another runtime, or none, prepare says what it did:

```
RUNTIME=codex
RUNTIME_OVERRIDE=profile build names no runtime (claude-code), resolved in codex: gpt-6.1-terra high
MEMBER_SKILLS=none (not delivered to an extra runtime)
```

`RUNTIME_OVERRIDE` is printed when `--runtime` differs from the runtime the profile names (for a profile that names none, from the project's own); `--runtime` equal to the profile's runtime, or the project's own for a profile that names none, prints no such line. `RUNTIME=` is printed for every run of a project with extras, its own runtime's too. Managed member skills are delivered to the project's own runtime only, so a run on an extra one freezes none. A profile whose own `model` the runtime does not offer is refused (`runtime-profile-model`); give the profile a tier.

## 4. Run, take in, review

Start the run as the run's runtime says: `qargi provider notes spawn --run RUN` prints it (`qargi local run RUN` for a command runtime). Runs that share the members' sign-in run one at a time, so a build and a review on `codex` queue. A run starts on the runtime it was prepared for.

A review on `codex` is a **reading review**: its sandbox refuses every write, so the member cannot run tests, a build or `git apply`, and always runs read-only. Put the diff or the patch series on disk before the run, where the member can read it (never under `/dev`), name the files in the task block, run the tests and gates yourself and put their output beside the diff. The report can cite that output and verify none of it.

Take both runs in as for any run: `qargi local verify RUN`, `qargi review check RUN/out`, `qargi review apply RUN` for a build, `qargi local close RUN` and `qargi local clean RUN`. `qargi local list` shows a `RUNTIME` column and a tail `model=gpt-6.1-terra (requested at prepare, not confirmed)`, and `review check` prints `runtime=codex model=gpt-6.1-terra (requested at prepare, not confirmed)` first. `(requested at prepare, override verified)` appears when the runtime's per-dispatch model override is verified. It is never "confirmed": no runtime reports which model answered, so a verified override is still a request.

The recommended practice: a review on `codex` is advisory and is never the sole review behind a merge. It ran nothing, its sandbox does not confine reads, and the model behind its verdict is unconfirmed, so a second review on the project's own runtime, or yours, stands behind the merge. No verb checks it; you decide whether to keep it.

## 5. Stop using it

`qargi provider disable PROJECT --runtime codex` is refused, with no token, while a profile names the runtime: `qargi project unset PROJECT profiles.codex-build.runtime` first (the unset is plain, hyphen included). Then disable with its own plan and token; it asks for no phrase. Runs prepared for it and not yet started are refused at `local run` (`runtime-drift`: prepare again). Finished runs are taken in as before, because verify, review, apply, close and clean ask for no runtime.

## 6. Turn on an option of the runtime

A runtime's definition may declare **options**: opt-in changes to the file every run of it gets (`dispatch.run_config.options`). `codex` declares one, `image_generation`, a hosted tool that runs outside its sandbox and may spend; the baseline keeps it off. Nothing here is on until you approve it, and then only for the profiles you choose ([the option and what is not verified](codex.md#image-generation-an-opt-in-off-by-default)).

1. Enable it for the project: `qargi provider enable PROJECT --runtime codex --option image_generation` prints the plan and a token. `codex` must be the project's own runtime or one you enabled in step 1 (else `runtime-not-enabled`). Approve with your own words, which must carry the phrase of the plan, `hosted image generation runs outside the sandbox`: `--plan TOKEN --approved "yes, hosted image generation runs outside the sandbox"`. Without it the refusal is `runtime-option-unacknowledged` and the token stays good.
2. Select it in a profile of a worker base: `qargi project set PROJECT profiles.codex-images '{"base":"worker","tier":"balanced","effort":"high","runtime":"codex","options":["image_generation"]}'`. It is a plain `project set` that only selects among what you enabled; `qargi project validate` refuses an option that is not enabled and a profile on the `reviewer` base.
3. To stop: take the option out of the profile (`qargi project set PROJECT profiles.codex-images.options '[]'`), then `qargi provider disable PROJECT --runtime codex --option image_generation` (its own plan and token, no phrase); disabling the runtime itself (step 5) is refused while an option of it is enabled. A run prepared with the option before a change of the project's list, the profile or the definition is refused at `local run` with a request to prepare again.

## When something is refused

| Code | Meaning | What to do |
|---|---|---|
| `runtime-not-enabled` | the runtime is not the project's own or an enabled one | `qargi provider runtimes PROJECT`, then the owner's `provider enable --runtime` |
| `runtime-unusable` | the runtime is not sealed, not local, not started by a command, or is the project's own | `qargi provider check NAME`, or choose a command runtime |
| `runtime-reads-unacknowledged` | the approval words lack the phrase | approve again with the same token and words that carry `reads are not confined` |
| `runtime-option-unacknowledged` | the approval words of an option lack its phrase | approve again with the same token and words that carry the phrase the plan printed |
| `runtime-profile-model` | a profile's `model` is not one the runtime offers | give the profile a tier |
| `runtime-barrier-missing` | a read-only role on a runtime that has no barrier (the acceptance of the own runtime does not count) | use a runtime with a barrier |
| `runtime-drift` | the run was prepared for a runtime that is no longer enabled, usable or unchanged | `qargi local prepare` again |
| `runtime-hidden-path` | the member would not see its clone, contract or OUT | `--scratch` on disk, not under `/dev/shm` |

[The catalogue of refusals](../reference/refusals.md) has the rule, the reason and the next step of each.

## Upgrading

A project that has no extra runtime and no profile `runtime` sees no new word, key or line, and no open run goes stale. The shipped `codex` definition changed (it says what its sandbox does not confine, and its barrier note names the reads): an open `codex` run prepared before the upgrade, in a project whose own runtime is `codex`, is refused at `qargi local run`; prepare it again.
