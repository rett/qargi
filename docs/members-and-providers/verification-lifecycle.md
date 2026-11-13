# Verification and retries

Every newly prepared run has private, lead-owned attempt state under `<state>/attempts/ID`. Preparation records the original refs, epoch, base branch and base commit before publishing `lifecycle: 1` in the lead's registry. Those prepared values remain immutable. The initial attempt can accept an external read-only report without any runtime dispatch: store the message with `qargi review save RUN`, then run `qargi local verify RUN`.

`qargi local run RUN --again` opens another strict attempt after a completed dispatch or a verified result. The pre-dispatch comparison can accept legitimate lead moves since verification; the accepted refs become the new attempt's baseline. During that attempt, an unjournaled local fast-forward is refused again. Qargi's journaled moves, permitted tracking-ref updates and the project's declared owned refs retain their existing rules. Remote changes still require the existing journal rules.

Dry-run, invalid configuration and other preflight refusals preserve earlier output and verification. Once dispatch crosses the mutation boundary, it first commits the new attempt and clears verification mirrors, then writes dispatch metadata, truncates transcripts, rotates reports or starts the runtime. A setup or spawn failure after that boundary leaves a new, unverified `not-started` attempt. The previous saved generation remains private evidence; it is never replaced by the failed attempt's output. An applied, closed or cleaned run cannot be dispatched again; prepare another run.

## Accepting and recovering output

Verification reads the private attempt's baseline, epoch and phase and compares refs in a private temporary directory. `RUN/verified`, `refs.before`, `started` and `dispatch.json` are compatibility and diagnostic files; changing them cannot grant verification or change the prepared base. Apply and the declared scrub use the original prepared base commit.

A successful verification saves output under `<state>/runs/ID`. Each save has a fresh lead-created nonce in its `attempt` marker, bound to the prepared identity and attempt number. The previous copy is retained before a replacement is published. The new copy is built privately, renamed into place, then committed as verified without an intervening recovery step. An interrupted save cannot make an older verification accept the replacement. Its failed copy is retained by recovery, and verification from the original run is required again, even if the ref-comparison phase still says `after-verify`.

Repeated live or `--saved` verification of a current generation reuses that accepted output and advances the private comparison snapshot when refs change. An identical observation consumes no verification history; a changed snapshot consumes one historical record but no retained-copy slot. Changes to mutable OUT after acceptance do not replace that product. A new runtime attempt produces a new generation. Apply reads the accepted copy, so the checked and scrubbed patches are the ones applied.

`qargi local verify --saved ID` and `qargi review apply --from-saved ID` require the current verified prepared identity, attempt and generation. A missing copy, wrong marker or interrupted save refuses; a preserved previous attempt is evidence, not a selectable accepted result. Apply from saved output still requires the original run directory to be gone. Keep the original run until verification and collection have succeeded.

Retention is bounded: at most 32 retained copies and 32 historical verification records per attempt, and 256 attempts per prepared run, subject also to the private record size limit. Reaching a limit refuses further transitions instead of deleting evidence. Preserve wanted evidence separately before cleaning and preparing another run. Clean removes the run's current and retained copies and private attempt state; the lifecycle lock inode remains stable.

## Execution, termination and acceptance

Actual dispatch, public verify, apply, close and clean share one nonblocking lifecycle lock. A busy lock refuses promptly, including `clean --discard`. Internal apply/verify and close/clean checks share only the actual held descriptor. Lock order is lifecycle, apply PID lock, then short registry or journal locks. Members, Git helpers, scrub commands and background lease renewers receive no lifecycle descriptor.

The runtime owner records begin, member identity and end itself. Execution completion, termination of the recorded member process group, and verification of returned output are separate decisions. An active or unknown attempt cannot be verified, applied, closed or cleaned. After an owner dies, recovery can mark the attempt `lost` only when the recorded member group is proven gone.

There is an intentional unknown-spawn window: if the owner dies after begin and no member identity was committed, qargi cannot prove whether a child was launched. Retry, verification and discard refuse with an unknown-liveness diagnostic. Do not edit the record to fabricate an ended member or rely on `dispatch.json` to recover it. Preserve the evidence and investigate outside these lifecycle verbs. This implementation provides no automatic recovery protocol for that window.

Process evidence is Linux-specific and covers the recorded process group. Descendants can escape it by starting another session; this is not containment of escaped processes. An unavailable or unsupported host process probe is unknown, never proof of termination. Filesystem operations that committed but could not fsync their directory warn; persistence across power loss is not guaranteed.

## Legacy preparation

The current production format is the foundation's schema 1, selected by the exact registry marker `lifecycle: 1`; this wiring does not change that schema. A registry entry without the marker is explicitly legacy. Inspection and recovery remain available with a warning about their writable snapshots, but actual runtime dispatch requires a newly prepared run. No snapshots are automatically adopted into authority. A marked run whose state is missing, corrupt or unsupported fails closed and is never treated as legacy. Legacy recovery has no private attempt-identity or process-liveness guarantee.
