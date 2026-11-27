# Queue of the whole-suite runs

Two whole-suite runs of one user never overlap on a host. `qargi feature verify` and `qargi release verify` take the one **slot** of a queue just before their suite starts and give it back when the suite has ended and the verb has read what the suite left, its log, its gate list and the reports of the launcher (a moment; not at the end of the verb), and a run that comes while the slot is taken waits its turn. `qargi suite run -- COMMAND` puts any command in the same queue, for a suite that is run by hand or by a supervisor to verify a run, and `qargi suite status` shows who holds the slot and who waits.

Two suites at once slow each other and fail on timeouts they would not meet alone; the warning of the verify verbs said so but did nothing about it. The queue does.

It is the owner's ruling that this is a lock of the user, in the kernel, for whole-suite runs only. The checks a member runs in its own clone stay out of it: a member's guard refuses `qargi suite` (see [Lead side only](#lead-side-only)).

## Where it is

| What | Where | Mode |
| --- | --- | --- |
| the queue directory | `$QARGI_STATE/suite-queue/` | 700 |
| the lock the slot is a `flock` on | `suite-queue/lock` | 600 |
| the record of the holder | `suite-queue/holder.json` | 600 |
| one file for each run that waits | `suite-queue/wait.PID.START` | 600 |

The state directory is `~/.qargi/state` unless `QARGI_STATE` says otherwise, so the queue is one for each user and each state directory. The records are advisory: **the `flock` is the authority**, and a record that is missing or wrong never lets two runs hold the slot.

## How the slot is taken

- **A kernel lock.** The shell of the run opens `lock` and keeps the descriptor only while the suite runs and the verb reads what it left; `lib/suite_queue.py` takes the `flock` on that descriptor and exits, and the lock stays with the shell's open file description. A lock held by the kernel cannot be left behind: it is freed when the last process that has the descriptor ends, however it ends.
- **Who has the descriptor.** The shell of the verb and the subshell that waits for the suite. What the suite starts never has it (it is closed for the suite, and a program that is started with `exec` keeps no copy), so a daemon that a test leaves behind cannot keep the slot. A verb that is killed while its suite runs therefore leaves the slot taken until that suite has ended, and not a moment longer: the suite is still on the machine. Nothing is ever held for the whole verb (the lease, the busy mark and the worktree are, the slot is not), and the lease renewer of a feature verify, which is started first, never has the descriptor.
- **First in, first out.** A run that wants the slot writes a waiter file (its pid, the start token of that process, the project, the verb, the name, the commit and the time it came, in nanoseconds) and only the first of the live waiters tries the lock; the others look again. So the order is the order of arrival and not whoever polls first. A waiter file of a process that is gone (or of a pid that was given to another process: the start token, field 22 of `/proc/PID/stat`, differs) is ignored and removed by the next waiter. This is the shape of the lane of a sign-in (`qargi local list --lanes`), which `lib/suite_queue.py` reuses for the start token, the atomic write and the reading of `/proc/locks`; the lane has no order, this queue has.
- **The record of the holder** is written, atomically (a new file renamed over the name), once the lock is held, and removed before it is let go: `pid` (the shell of the verb) and its start token, `project`, `verb`, `name`, `head` and `started`. A record whose process is gone names nobody: `status` reads the lock from `/proc/locks`, so the record of a killed holder is not shown. Where `/proc/locks` cannot say (the device it names cannot be compared with `stat`'s, as on btrfs, or it cannot be read), the lock file is probed with a non-blocking exclusive `flock` on a descriptor of its own, which is let go and closed at once; a refusal of it means held. Where the device can be compared (ext4, tmpfs) `/proc/locks` decides, also when it has no entry (it lists a lock of a process outside the pid namespace too), and no lock is taken. The probe is never kept, does not follow a link and does not block on a FIFO put in the place of the lock file (anything but a regular file is refused). A run that takes the slot uses a descriptor of its own and, when the probe was there at that moment, tries again three times, 20 milliseconds apart, also at the end of its `--queue-wait` (also `0`), before it is refused as `suite-queue-busy`; the refusal is therefore never the probe's. `qargi local run --wait N` (N above 0) makes the same tries at the end of its bound before it refuses as `lane-busy` (`--wait 0` tries once). The state is `unknown` only when the lock file cannot be opened. Every field read from these files is cut to plain characters before it is printed.

## What a waiting run prints

One line on standard error, again only when the holder or the place changes (no spinner):

```
qargi: suite queue: position 2, holder is app feature verify dots (running 4m)
```

`position 1` is the run that is served next. When the verb of the holder has been killed but its suite still runs, the line says so (`whose verb is gone (its suite still holds the slot)`). The verify verbs keep the lease of the feature and their busy mark while they wait (so with `verify.environment` on, a second verify of the same name is refused while the first waits, as while it runs), and they let the slot go only after they have read the log, the gate list and the reports of the launcher of the run, which are named by the feature or the version: the next run of that name rewrites them as soon as it has the slot. A busy mark, a `tests/run.sh` below the shell of a run in the queue, is no longer warned about as an unexplained busy run: the queue names it.

**A run started from inside the suite that holds the slot is refused, not waited for.** A test command that itself runs `qargi suite run -- ...` or `qargi feature verify` would wait for the slot of its own parent for ever. When the holder is a parent of the run that waits (the parents of the shell of the run, read from `/proc`), the run stops at once with a plain error (exit 1, nothing run or recorded, nothing left in the queue) that names the holder. It is not a refusal of the catalogue and has no bound option; the check sees a holder whose verb is alive, not a suite that a killed verb left running.

The wait is **not** part of the seconds of the suite. `feature verify` and `release verify` start the clock of their record when the slot is taken, and the entry they add to the [history](history.md) has the whole seconds waited, rounded up, as `queue_wait_s` (0 for a run that did not wait).

## `--queue-wait SECONDS`

`qargi feature verify NAME` and `qargi release verify VERSION` take `--queue-wait SECONDS`, a whole number. Without it the wait has no bound. At the bound the run is **refused** as the catalogue code `suite-queue-busy` ([refusals](refusals.md#suite-queue-busy); exit 1), which names the holder and the seconds waited. The refusal comes before anything is run, claimed or written: no history entry, no record of the branch, no log, no attempt counted, no waiver of `verify.environment` spent, and no file of the run left in the queue. `--queue-wait 0` refuses at once when the slot is not free, and also when it is free and another run is ahead of this one.

## `qargi suite run -- COMMAND [ARGS...]`

Takes a slot (waiting its turn, with no bound), runs COMMAND with its standard input, output and error as they are, lets the slot go and exits with the status of COMMAND (127 or 126 when it cannot be run). What follows `--` is the command's own, a `--json` or a `--help` of it included; `suite run` takes no option of its own. It records **nothing in the history**: that is for `feature verify` and `release verify`, which say what was verified, and a command that qargi does not know is not evidence of anything. The queue shows it as the verb `suite run`, named by the command and, when it is a word and not an option, its first argument (`bash run.sh`), never the rest of the line.

## `qargi suite status [--json]`

```
suite queue: held
POSITION  PROJECT  VERB            NAME    HEAD      AGE  PID
holder    app      feature verify  dots    9f3c1a07  4m   20311
1         app      release verify  0.3.10  4be2d6c0  2m   20418
```

The holder first, then the waiters in the order they will be served. It only reads: no lock is kept (the probe above is the one moment a lock is taken), nothing is removed, no process is signalled. With `--json` it prints one document of the draft kind `qargi-suite-queue` (`qargi help json qargi-suite-queue`): `state` (`free`, `held` or `unknown`), `holder` (null when nobody holds the slot, or when the lock is held and its record is missing or names a process that is gone) and `waiting` (each with its `position`, `pid`, `project`, `verb`, `name`, `head` and `waiting_seconds`). The document is checked against its registry file before it is printed; exit 0 after a complete document, 1 for a queue that cannot be read, 2 for a wrong call, 70 for a document that fails its registry file (nothing is printed). [JSON output](json-output.md#draft-kinds) says what a draft is.

## Lead side only

`qargi suite` is the lead's under the current member guard, as `qargi backlog graph` and `qargi history` are: a member is refused the verb, `lib/suite.sh` and `lib/suite_queue.py` of the tool in any use, and a write into the `suite-queue/` directory of the state (reading stays allowed). A coordinator (a session with a label) may run `suite status`; `suite run` takes a slot and is not in its list.

## What it does not do

- **Moving a run forward is not offered.** The order is the order of arrival; there is no priority, no jumping the line and no `--first`. A run that should not wait is stopped and run later.
- It is not a gate and decides nothing about a verdict: the record of the branch and the history say what ran, never the queue.
- It is one queue for each user and state directory on one host. It does not span hosts or users (another user's suite, and a `tests/run.sh` that is run by hand outside the queue, are still only warned about), and it does not queue the checks a member runs in its clone.
- It does not stop a suite that is running, and it does not time one out.
