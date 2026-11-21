# verify.environment: whole-suite runs that look like CI

`verify.environment` is an optional project answer. When it is set, every whole-suite command of `qargi feature verify` and `qargi release verify` (the test command, or each gate) starts through one launcher, `lib/suite_env.py`, that puts the process into a declared state before the command runs and reads that state back. Unset, or `null`, means off: the verbs behave and record exactly as they did before.

**It is stricter than CI, and stricter than your own shell.** The launcher does not copy a runner. Where a runner leaks something into a job (an ignored signal, a spare descriptor, a variable you never asked for) the launcher starts from nothing and adds back only what you declare. A suite that passes under it has not leaned on a trait of your shell or of one CI image; a suite that fails under it has relied on one. The [table below](#settings-against-the-hosted-runner) says, setting by setting, how the launcher differs from the hosted Linux runner that was measured.

The answer is stored with the project answers (`qargi project set NAME verify.environment JSON`), never in the repository.

## The five parts

| part | what the launcher does | how it is read back |
|---|---|---|
| `signals` | every signal at its default disposition (KILL and STOP cannot be changed), an empty signal mask | `SigBlk` is zero; `SigIgn` is zero, apart from signals 32 and 33, which belong to the C library and cannot be set from Python (a bit of them is noted, not refused) |
| `fds` | only descriptors 0 to 2; with `ci-like` also the two pipes of the runner | the descriptor set is exactly what was declared; with `ci-like` each of the two is a pipe with the flags that were placed |
| `tty` | a new session (`setsid`), no controlling terminal, stdin from `/dev/null`; the output goes to the suite log | `setsid` succeeded, descriptors 0 to 2 are not terminals, `/dev/tty` fails to open |
| `cpu` | a transient cgroup scope below `qargi-verify.slice` with the cpu controller on, started with `systemd-run --user --scope` | the process is in a scope below that slice and its `cpu.max` is what was declared |
| `env` | an environment built from nothing: `PATH`, `HOME`, the names in `env_pass` that are set, and `env_set` | cannot fail; the names (never the values) are recorded |

A part that cannot be applied refuses the run with a code (below). Nothing is skipped silently.

## The schema

```json
"verify": {"environment": {
  "fds": "ci-like", "ci_fds": [142, 145],
  "cpu_quota": "200%",
  "env_pass": ["LANG"], "env_set": {"EXAMPLE_OFFLINE": "1"}
}}
```

| key | values | default when the object is present |
|---|---|---|
| `fds` | `"close"`, `"ci-like"` | `"close"` |
| `ci_fds` | exactly two different integers from 3 to 1023, `[READ, WRITE]`; only with `ci-like` | `[142, 145]` |
| `cpu_quota` | `"N%"` (N from 10 to 12800), `"max"`, `null` | `"max"` |
| `env_pass` | variable names (`[A-Za-z_][A-Za-z0-9_]*`), each once | `[]` |
| `env_set` | variable name to string, no NUL or line break | `{}` |

- `{}` is a valid declaration: `fds` `close`, `cpu_quota` `"max"`, nothing passed or set.
- `fds: "close"` keeps descriptors 0 to 2. `fds: "ci-like"` is `close` plus the runner's two pipes: `READ` gets the non-blocking read end of one pipe, `WRITE` the write end of another, neither close-on-exec. The launcher's parent holds the other end of each for the life of the suite, so a read of `READ` gives `EAGAIN` and never end-of-file, and a write to `WRITE` gets no `EPIPE` and no `SIGPIPE`; the parent reads and discards what is written, so a suite that writes more than a pipe buffer does not block. The default numbers are the runner's. Descriptor 255 and a `make -j` jobserver pair are not reproduced: each appears by itself when the suite's command is a shell script or runs `make -j`.
- `cpu_quota: "max"` turns the cpu controller on with no quota (`cpu.max` `max 100000`, `CPUWeight=100`), which is what the runner has. `"N%"` is a quota: `"200%"` gives `cpu.max` `200000 100000`, which is two CPUs of time, not two CPUs. `null` means no scope, so no cpu part and the weaker cleanup described below.
- There is no core-count key: `AllowedCPUs` is silently ignored for user scopes, so `nproc` reports the host's count.
- `PATH` and `HOME` always pass and cannot be named. `env_set` is plain text, not for secrets. A project that wants `CI=true` or a locale declares it: nothing is added by default.
- Refused with `verify-env-invalid`, at `project set`, `project validate` and at load: an unknown key (so `signals` and `tty` are not keys), a wrong type or value, a name in both `env_pass` and `env_set`, `PATH` or `HOME` in either, `ci_fds` without `ci-like` or not two different numbers, a name that the cloud binding rules out (the variables a suite never inherits), and any `QARGI_*` name.

## Changing it

`qargi project set NAME verify.environment JSON` compares the new declaration with the one qargi last accepted, which is kept apart from the answers in the state directory (`verify-env.json`, mode 600), never in the answers file.

- **Plain** (a tightening): no declaration was stored before, or only `cpu_quota` changed and became stricter (`null` to a value, `"max"` to `N%`, or `N%` to a lower `N%`).
- **A loosening** is everything else: removal (`null`, `project unset`), a higher quota, any change of `fds` or `ci_fds`, any change of `env_pass` or `env_set`. It is refused with `verify-env-change-unapproved` and a plan token; the same command with `--plan TOKEN --approved "<the owner's words>"` applies it and writes the audit line `project:verify-environment-loosened`.

The same rule covers `project set` and `project unset` of `verify` and of `verify.environment.KEY`: the comparison is always of the whole declaration before and after. In a member run these commands are refused (exit 2): the owner's words are the only approval, and an agent's relay of them is not.

A hand edit of the answers file cannot turn the setting off or change it. `qargi feature verify`, `feature finish`, `release start`, `release verify` and `release finish` compare the declaration in the answers with the accepted one and refuse with `verify-env-change-unapproved` when they differ, in either direction; `feature status` and `release status` print the same finding and go on. The two ways out are to restore the answers or to change the setting with `project set`. `project init`, `new` and `attach` refuse, and store nothing, an answers file whose declaration is not the accepted one; when none was accepted before, a declaration in the file is a first declaration, and it is stored and recorded as accepted. A state file that cannot be read (it holds the accepted declaration of every project) makes these verbs refuse for every project, one that never set the option too: it fails closed on purpose, because a project whose answers were edited to off cannot then be told from one that was always off. `qargi doctor` names the file; fix it or remove it by hand. Limit: this guards an edit of the answers file; someone who also edits the state file is not stopped, but the audit log then lacks the line a real change writes.

## Refusal codes

Every refusal names its code, the part, what was found and, for a part that can be waived, the waiver command. It exits 1 and records nothing.

| code | part | when |
|---|---|---|
| `verify-env-invalid` | none | the declaration is not valid (`project set`, `project validate`, load) |
| `verify-env-change-unapproved` | none | a loosening without token and words; an answers file that differs from the accepted declaration; a state file that cannot be read |
| `verify-env-cpu-no-systemd-run` | cpu | `systemd-run` is not on the clean `PATH` |
| `verify-env-cpu-systemd-too-old` | cpu | `systemd-run` reports a version below 254 |
| `verify-env-cpu-no-user-manager` | cpu | the scope cannot be made (no user manager), or the scope route left no report |
| `verify-env-cpu-readback` | cpu | no `cpu.max`, the wrong slice, or a value other than declared (the message gives what was found) |
| `verify-env-signals` | signals | the read-back of the signal state failed |
| `verify-env-fds` | fds | the read-back of the descriptors failed |
| `verify-env-tty` | tty | the session or terminal read-back failed |
| `verify-env-no-log` | tty | a suite log, or the directory for the launcher's reports, cannot be created: with the setting on the output goes to a log, never to a terminal. The suite log is made after the waiver is claimed, so under a waiver this refusal has spent the token and written its audit line, and the message says so |
| `verify-env-waive-unapproved` | none | a waiver without the token and the owner's words, or with a token for other parts or another head (a token holds the branch, the head and the declaration); a `--waive-environment` that does not name every refused part; a waiver when nothing was refused, so no token matches |
| `verify-env-waive-used` | none | the token of a waiver was already used for a run at this head |
| `verify-env-waive-unknown` | none | `--waive-environment` names something that is not `signals`, `fds`, `tty` or `cpu` (so not `env`), a part that is off, or the setting is off |
| `verify-env-waiver-dir` | none | the directory for the waivers (`<state>/verify-env-waivers`), the claim file of a waiver or the count of the tokens used at the head cannot be made, kept or read (a count that is not a number); nothing was run |

The verb makes the launcher's attempt before it makes the worktree, so a refusal costs no worktree. The attempt runs the launcher on a no-op command in a throwaway scope. A second verify of the same name (the same feature, or the same release version) while the first is still running is refused before the attempt, the waiver and the worktree, with a message naming the pid of the first: the two would share one directory for the launcher's reports, and the second would delete the first's. The check reads the busy mark the first verify writes once its attempt and worktree are made, so a second verify started while the first is still preparing (seconds, not an instant) is not refused. The message names the busy mark: if its pid is alive but is no qargi verify (the first one died without removing the mark and the pid was reused), remove the file. Other names, and the setting off, are not affected.

## The waiver

A waiver is per run: it is not kept as a setting, and the next run starts without it. Only a count of the tokens used at a head is kept in the state (`<state>/verify-env-waivers/KEY.count`, one file per branch, head and declaration, with one claim file for each use), so that a used token is never good again; the audit log holds the words. The command is `qargi feature verify NAME --waive-environment cpu --plan TOKEN --approved "<the owner's words>"` (the same on `release verify`).

- Only a refusal yields a token. The token covers the project, the branch, its head, the declaration and exactly the refused parts, and `--waive-environment` must name exactly those parts. With the setting off, with `cpu_quota` `null` (the cpu part is off), or for `env` (which cannot fail) the waiver is `verify-env-waive-unknown`. A token is good for one run at its head; the next refusal prints the next token.
- A waiver skips nothing. A waived part is still attempted, and when it fails it is a warning, printed before the run and again with the verdict, and recorded as `waived-failed` with its code. A waived `cpu` whose attempt failed runs without a scope and with the weaker cleanup; when the attempt passed, the scope is used and the part is recorded `applied`. A waived part that succeeds is recorded `applied`.
- A part that fails outside the waiver refuses again with a new token.
- The token is spent when the run is about to start: after the attempt and after the verb's own checks (a `--strict` refusal of `release verify` comes first and spends nothing, writes no claim and no audit line), and before the suite log is made. Of two verifies that hold the same token the later one is refused with `verify-env-waive-used` and nothing run.
- The run is audited as `verify:environment-waived` with the words. In a member run `--waive-environment` with `--approved` is refused (exit 2): the words are the owner's.
- A waived run counts for `feature finish` and `release start`. The verdict line ends with `(verify.environment: cpu waived-failed)`, and `feature status`, `release status` and the plan of `feature finish` show the waiver again.

## The record

With the setting on, the suite record of a run has an `environment` member:

```json
"environment": {"id": "b3efcece7ae9", "launcher": 1,
  "declared": {"ci_fds": [142, 145], "cpu_quota": "200%", "env_pass": ["LANG"], "env_set": {}, "fds": "ci-like"},
  "parts": {"signals": "applied", "fds": "applied", "tty": "applied", "cpu": "applied", "env": "applied"},
  "codes": [],
  "readback": {"sig_ign": "0", "sig_blk": "0", "fds": [0, 1, 2, 3, 142, 145], "sid": 4711, "dev_tty_errno": "ENXIO",
               "ci_fds": [{"fd": 142, "kind": "pipe", "end": "read", "flags": "04000", "cloexec": false, "read": "EAGAIN"},
                          {"fd": 145, "kind": "pipe", "end": "write", "flags": "01", "cloexec": false}],
               "cgroup": ".../qargi-verify.slice/run-u123.scope", "cpu_max": "200000 100000", "cpu_weight": "100",
               "systemd": 262, "env_names": ["HOME", "LANG", "PATH"], "env_pass_unset": []},
  "cleanup": "cgroup", "leftovers": [{"pid": 4790, "comm": "sleep"}]}
```

- `declared` is the normalised declaration: every default is filled in, so it is never empty (a declaration of `{}` is recorded as `{"cpu_quota": "max", "env_pass": [], "env_set": {}, "fds": "close"}`). `readback` holds the values found: environment names only, never values. `ci_fds` is there only with `ci-like` and says, per number, the kind, the end, the octal status flags as `/proc/self/fdinfo` prints them, and close-on-exec.
- `readback.fds` lists every descriptor the launcher had open when it read them back, including its own report descriptor (3, close-on-exec, so the command never has it). With a waived `cpu` whose attempt failed, `parts.cpu` is `waived-failed`, `codes` names the code, the readback has no `cgroup`, `cpu_max`, `cpu_weight` or `systemd`, and `cleanup` is `pgroup`.
- `id` is the first 12 hex digits of the sha256 of the launcher version and the normalised declaration. The launcher version is an integer in `lib/suite_env.py`, raised whenever what the launcher applies changes.
- A run counts for `feature finish`, `release start` and the status verbs only under the declaration and launcher version it was made with. A declaration that is set, changed or removed, or a new launcher, makes an earlier run stale, and `feature status` and `release status` say why. The accepted-declaration hash in the state is of the declaration alone, so an upgrade of qargi makes earlier runs stale without making the answers refuse.
- A run is recorded only with the report of the launcher behind it, and only when every launcher report of the run has the same id and launcher version (a launcher replaced while the run was going leaves no record). A scope that cannot be made, or a launcher that leaves no report, is `verify-env-cpu-no-user-manager` or a launcher fault, and never a test failure: the verdict is read from the report, not from the exit status.

## What a suite sees

- **Environment.** Nothing passes undeclared: `PATH`, `HOME`, the `env_pass` names that are set and `env_set`. An `env_pass` name that is not set in the caller's environment stays absent, and is recorded.
- **Signals.** All default, empty mask. A suite that writes to a closed pipe dies of `SIGPIPE` here; in a runner's shell step `SIGPIPE` is ignored and it gets `EPIPE`. There is no option in 0.3.5 to reproduce the runner's signal state.
- **Descriptors.** Only 0 to 2, plus the two pipes with `ci-like`.
- **Terminal.** A new session and no controlling terminal. Standard input is `/dev/null`; standard output and error are the suite log.
- **CPU.** The scope's controller state as declared. The host's CPU count is unchanged.
- **Cleanup.** When the command ends, whatever is left in the scope (found through the scope's `cgroup.procs`, so `setsid` children are reached) is listed, killed and recorded, up to five rounds over two seconds. Leftovers do not change the verdict. With `cpu_quota` `null` or a waived cpu whose attempt failed the process group is used instead and the record says `"cleanup": "pgroup"`. A forwarded interrupt, terminate, hangup or quit reaches every process in the scope; a signal that was ignored on entry (so `nohup qargi feature verify` keeps working) is not forwarded.

## Settings against the hosted runner

Measured on 2026-11-18 UTC on the hosted Linux runner of the CI service: image `ubuntu-24.04` version 20261111.370.1, runner 2.338.2, systemd 255 (255.4-1ubuntu8.18), a private scratch repository, Go 1.27.4. Four probes each inspected their parent process: a shell step (`step`, bash under the runner's worker), `make` and `make -j2` (under bash), and a Go test binary (`gotest`, under `go`). The values hold for that image; a later image may differ.

| part | local effect | hosted runner (measured) | relation |
|---|---|---|---|
| signals | all default (`SigIgn` 0), empty mask (`SigBlk` 0) | `step`: `SigIgn` 0x1004 (SIGQUIT and SIGPIPE), `SigBlk` 0x10000 (SIGCHLD). `make` and `make -j2`: `SigIgn` 0x1000 (SIGPIPE), `SigBlk` 0x10000. `gotest`: both 0. Nothing pending anywhere | local is stricter than the shell step and make, and equal to a Go test binary |
| `fds: close` (default) | only 0 to 2 | 0 to 2, 142 and 145 in all four probes; also 255 in `step` (bash's own handle on its script, close-on-exec), 3 and 4 in `make -j2` (the jobserver pipe, close-on-exec), 3, 5, 6 and 9 in `gotest` (opened by the Go runtime: `cpu.max`, epoll, eventfd, pidfd) | local is stricter |
| `fds: ci-like` | 0 to 2, `READ` (142): a pipe, flags `04000` (`O_RDONLY\|O_NONBLOCK`); `WRITE` (145): another pipe, flags `01` (`O_WRONLY`); neither close-on-exec; the other ends are held by the launcher's parent | 142: `pipe:[13056]`, flags `04000`; 145: `pipe:[13057]`, flags `01`; neither close-on-exec; the same two pipes in all four probes. Who holds the other ends, and what is done with them, is not observable from inside a job | same kind and flags; descriptor 255 and the jobserver pair are not reproduced |
| standard input, output, error | stdin `/dev/null`; 1 and 2 as the verb gives them (the suite log) | stdin is a pipe in `step`, `make` and `make -j2`, and `/dev/null` in `gotest` (set by `go test`); 1 and 2 are pipes. Whether the stdin pipe ever delivers data or end-of-file is not observable | local matches what a Go test binary gets; a shell step has a pipe |
| tty, session | a new session (`setsid`), no controlling terminal, `/dev/tty` fails to open | no terminal (`ps` shows `?`) and `/dev/tty` does not open, in all four; the job has its own session and process group (session 1854 = group 1854 in all four) | agrees |
| `cpu_quota: "max"` (default) | its own scope, cpu controller on, `cpu.max` `max 100000`, `CPUWeight=100` | cgroup `/system.slice/hosted-compute-agent.service` (cgroup v2, no scope per job); controllers `cpuset cpu io memory pids`; `cpu.max` `max 100000`; `cpu.weight` 100; the same in `system.slice`; the root has neither file | agrees |
| `cpu_quota: "N%"` | `cpu.max` N times 1000 over 100000, so `"200%"` is `200000 100000` | no quota | local is stricter |
| CPU count | the host's (no core-count key) | `nproc` and `getconf _NPROCESSORS_ONLN` give 2 in all four: two vCPUs, not a quota | not reproduced |
| env | `PATH`, `HOME`, the declared names | 111 names in `step`, 114 under make, 115 in `gotest`: `CI`, `LANG`, `HOME`, `PATH`, `USER`, `LOGNAME`, `SHELL`, 39 names that start `GITHUB_`, 8 that start `RUNNER_`, tool locations and others. Only names were printed, so the value of `CI` and of `LANG` is not measured | local is stricter; a project declares `CI=true` and its locale itself |
| limits | the caller's | `ulimit -n` 65536, stack 16384 kB, core size 0, locked memory 8192 kB | not part of the setting |

Two rows are not reproduced on purpose: the core count, because nothing in a user scope can set it, and the runner's signal state, because the stricter default is the better test. Nothing in the table says what the runner does with its ends of the two pipes, or what is in the values of its variables; the page claims nothing beyond what was measured.

## Doctor

`make doctor` reports `systemd-run` with its version, as `ok:`, or as `expected:` when it is absent or older than 254: it is optional, only the cpu part needs it, and the bootstrap does not install it. `qargi doctor` has a check `verify-environment`: off, or on with what the host needs, and a warning when the answers differ from the accepted declaration, when the declaration is invalid, when the file of accepted declarations cannot be read, or when the cpu part is on and `systemd-run` is missing or too old. It reads only and makes no scope; `qargi feature verify` makes the attempt.
