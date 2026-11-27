# JSON output

A program that reads what qargi prints needs two things: to know which document it has, and to know what may change under it. This page is that contract. `qargi help json` prints the short form and `qargi help json KIND` the fields of one kind; the shapes themselves are data, one registry file for each kind in `lib/kinds/`.

A **document** is one JSON object that a verb prints for a program to read. A **kind** is the name of a document's shape (`qargi-marshal-status`). The **schema** is the integer version of one kind. A kind is **pinned** when its registry file, its fixtures and the lint that compares them exist together and the changelog of a release names it. Every other `--json` output of qargi is unpinned and may change without notice.

## The rule

- **Two fields name a document.** `schema` is an integer of 1 or more, `kind` is a string of the form `qargi-NAME` (lower case, digits, hyphens). The number belongs to the kind: `qargi-marshal-status` at 2 says nothing about `qargi-handoff`. A nested field may also be called `kind` (an item of a plan's `lines`, for one); only the top-level field names the document. A `kind` without the prefix `qargi-` (`provider`, `catalog`, `extension`) names a definition file that a person writes, not an output document.
- **What raises the integer.** A field is removed or renamed; a field's type changes (also: it may now be null where it could not, or the type of an array's items changes); a field's meaning or unit changes; an enum loses a word or a word changes meaning; a field that was required becomes optional or absent in some case; the order of an array changes where the registry says the order has meaning (`x-ordered`); a bound is loosened that a reader may rely on. At any depth of the document.
- **What does not.** A new field (always optional for a reader for good: the registry records the version of qargi that added it, and never lists it as required); a new kind; a bound made tighter. A new word of an enum is not additive unless the registry declares the field open (`x-open`: a reader treats an unknown word as `unknown`).
- **A reader** checks `kind`, then `schema`. On a kind it does not expect or a schema it does not know, it stops. It ignores fields it does not know. It never parses a text field (`detail`, `note`, a warning, a task's `state`: the registry marks them `x-text`).
- **Integers.** Every number in a pinned document is a JSON integer: digits with an optional leading minus, no fraction, no exponent. `1.0`, `1e3`, `"1"`, `NaN` and `Infinity` are invalid. The value lies within plus or minus 9007199254740991 (2^53 - 1), so a reader that holds numbers as 64-bit floats loses nothing. A fraction or a quantity that can exceed the bound is not a number in a pinned document: it is an integer in a named unit. An identifier that looks like a number (a hash, a token) is a string. This is a duty of qargi's writers, which refuse to print a document that breaks it; a reader whose parser turns every number into a float cannot tell `3.0` from `3` and need not.
- **Other values.** `generated_at` of a handoff is a string in UTC, `YYYY-MM-DDTHH:MM:SSZ`, and its registry file enforces that pattern; every other time field (`renewed_at`, `finished_at`, a lead's `since`, the `at` of a run) is text as the record holds it, which the registry does not check and a reader does not parse. An absent value is `null` in a field the registry marks nullable. No key is written twice. Output is UTF-8, one document, ended by one newline. The order of keys has no meaning.
- **A consumer's own counters** may be decimal strings, as an event format of a program that counts past 2^53 may choose. qargi's are JSON integers, and none of them comes near the bound. The two never need to be the same type: a reader of a qargi document reads integers, a program that writes its own events writes what its format says.

## The exit rule

- **Exit 0 means a document.** A verb of a pinned kind exits 0 only after it wrote one complete, valid document to standard output. The writer checks the document against its registry file before it prints it: a document that fails the check (a hand-edited local record that holds a float where an integer is declared, say) is exit 70 with one line that names the rule and the path, never exit 0. Nothing but the document goes to standard output; warnings and advice go to standard error. A write that fails (a closed pipe, a full disk) is exit 1 with one plain line and no traceback. So is the file of the handoff verb's `--json --write FILE` when it cannot be made after the document was printed: exit 1, one plain line on standard error, no refusal line (a file that is refused before anything is printed, because it exists, its directory is missing or not writable, or it is inside a git work tree, is a refusal with an empty standard output).
- **A rule that stops the verb is a refusal.** Standard output stays empty, standard error carries the `qargi-refusal` line (the kind below) and its block, then the sentence the verb printed before, and the exit status is the refusal's, never 0. A reader acts on the `code` and the `exit` of the line and never on a sentence.
- **Other non-zero exits carry no document and no promise of a line**: exit 2 (a wrong call), exit 70 (a defect), and the stops of the layers in front of the verb (the gate of a coordinator label, the check that a profile matches). A reader that gets a non-zero exit and no refusal line reports "failed, cause unknown" and does not read standard output.
- **The exit classes of a refusal** are 1 (a refusal), 2 (a guard's deny, or a verb that does not apply to the project), 3 (a refusal that a retry may cure: the remote of the shared records could not be asked, code `marshal-remote-unreachable`, class `marshal-remote`; nothing was changed) and 77 (a refusal of the lead seat, which is not built). The `exit` of the line is the exit status of the process.

## The pinned kinds

| Kind | Schema | Verbs | Stream |
| --- | --- | --- | --- |
| `qargi-marshal-status` | 1 | `marshal status [NAME] [--all] --json` | standard output |
| `qargi-marshal-check` | 1 | `marshal check [NAME] --json` | standard output |
| `qargi-handoff` | 1 | `marshal handoff [NAME] --json` | standard output |
| `qargi-refusal` | 1 | every verb that stops on a rule of the catalogue | standard error, one line |

What each verb writes. This is the `writes` field of the registry file, and a program that decides whether it may call a verb (a freeze allow-list, say) reads that field, not the word "read only" in a help text. `--no-write` is an option of `marshal status` and `marshal check`: with it the call writes nothing (no record, no audit line, no cache, and not even the directories that the first load of qargi makes) and fetches nothing, it answers as the call that writes would (a record whose branch is gone is shown abandoned, with no lead, and is not stored), and `remote` says `not-asked` on the shared refs backend.

| Verb | Writes |
| --- | --- |
| `marshal status --json` | Unless `--no-write` is given: on the local backend a record whose branch is gone is marked abandoned; on the shared refs backend the call fetches the shared records into this machine's cache and updates this machine's own observation cache, with `--no-fetch` too (a lock file with it) and, with integrity on, its acceptance marks. With `--no-write` nothing is written and nothing is fetched. The shared records are never changed. |
| `marshal check --json` | Unless `--no-write` is given: on the local backend a record whose branch is gone is marked abandoned; on the shared refs backend the call fetches the shared records into this machine's cache and updates this machine's own observation cache, with `--no-fetch` too (a lock file with it) and, with integrity on, its acceptance marks; with `--assume-unreachable-ok` it appends one audit line. With `--no-write` nothing is written and nothing is fetched. The shared records are never changed. |
| `marshal handoff --json` | Nothing, unless `--write FILE` is given: then the document is written to standard output first, the file is created with mode 600 (never overwritten), and the time and place of the note are recorded under the state directory. |
| the refusal line | Nothing by itself: the line only says that a verb stopped, and what that verb changed before it stopped is the verb's own. |

The text form of each verb is not changed by any of this. `qargi marshal handoff --json --write FILE` prints the document first and flushes it, then creates the file, then says on standard error that it wrote the file: a standard output that cannot take the document leaves no file, and a failure after the document was written is a non-zero exit, which a reader answers by not reading standard output.

Four fields tell a reader how far to trust an answer, and a program that builds on a status or a check (a lease it shows, a lock it takes) reads them first:

- `backend` is `local` or `refs`: where the records are.
- `remote` is `none` (the local backend has no remote), `checked` (the fetch ran and worked), `unchecked` (the fetch was tried and failed: the answer is from the cache this machine fetched last, and exit 0) or `not-asked` (nothing was fetched: `--no-fetch`, `--no-write` or a member run). A handoff never fetches, so it says `not-asked` on the shared refs backend and `none` on the local one.
- `lease_clock` is `wall` (local records: the wall clock, whole minutes since `renewed_at`) or `observed-here` (shared records: how long this machine saw the record's commit unchanged on its own monotonic clock; two hosts can give different answers for one record, and a first read on a machine says 0). `lease` and `minutes_since_renewal` mean what it says. `minutes_since_renewal` is a whole number of minutes on both backends.
- `backend_fallback` of a handoff is true when the shared records could not be read and the note was made from the local records of the host; `backend` then says `local`.

## Draft kinds

A kind whose registry file says `status: draft` is registered, so that `qargi help json` shows its fields, but it is not pinned: it has no fixtures yet, its integer may be raised without a release naming it, and the exit rule above is not promised for it. `qargi flow plan check` is the only verb of draft kinds so far. It exits 0 for a valid plan and 1 for an invalid one, and in both cases it prints the document of the kind `qargi-run-plan-check` (`valid` says which); a file that cannot be read is exit 2 with one line on standard error and no document, and a document that fails the check of its own registry file is exit 70, also with no document. A draft kind that a verb only reads (the plan file) has `stream` `none`: `qargi help json KIND` then says "Read by:" instead of "Printed by:", and a pinned kind never has it. [The run plan reference](run-plan.md) describes both kinds.

| Kind | Schema | Verbs | Stream |
| --- | --- | --- | --- |
| `qargi-run-plan` | 1 | `flow plan check FILE` reads it; nothing prints it | none (read, never printed) |
| `qargi-run-plan-check` | 1 | `flow plan check FILE --json` | standard output |

| Verb | Writes |
| --- | --- |
| `flow plan check FILE` | Nothing: the file is written by its author, and the checker only reads it. |
| `flow plan check FILE --json` | Nothing: no state, no token, no network, no file; the plan, the roles qargi knows and the files a done command names are only read. |

## The refusal codes of the three verbs

| Code | Class, exit | When |
| --- | --- | --- |
| `marshal-feature-unknown` | `marshal`, 1 | the feature has no branch and no record |
| `marshal-feature-held` | `marshal`, 1 | another live lead holds the feature (`marshal check`) |
| `marshal-handoff-file` | `marshal`, 1 | the file of `--write` is refused, or cannot be written in a call that has printed no document |
| `marshal-remote-unreachable` | `marshal-remote`, 3 | the remote of the shared records cannot be asked (`marshal check` without `--assume-unreachable-ok`) |
| `marshal-refused` | `marshal`, 1 | every other rule of the marshal that stops one of the three verbs; the sentence that follows says which |

The catalogue is [Refusals](refusals.md); `qargi help refusal CODE` prints one entry. An exit status of 1 from a marshal verb with no refusal line is not a refusal of the marshal: it is one of the stops in front of it.

### The seven words

A consumer may group failures into a few words. Where a pinned verb has a code for the word, the code is the stable form; no second field repeats it.

| Word | Code of the catalogue |
| --- | --- |
| `conflict` | `marshal-feature-held` |
| `not-found` | `marshal-feature-unknown` |
| `unauthorized`, `stale`, `incomplete`, `unknown-outcome`, `unsupported-schema` | none yet: no pinned verb raises one. A word gets a row here, with a code of the catalogue, when a verb needs it |

`marshal-remote-unreachable` is none of the seven: it says that the question could not be asked and that nothing was changed, and its exit status 3 says that asking again may work.

## Qualifying a reader

`tests/fixtures/json/` is a plain tree that a consumer copies and needs nothing else of this repository for. For each kind it holds a directory for each integer (`qargi-handoff/v1/`) with the registry file as it was at the pin (`registry.json`, never changed afterwards), real output of qargi (`valid.json`, `valid-minimal.json` with the required fields only, and more), a file with a field the registry does not name (`valid-unknown-field.json`), one file for each way to break a document (`broken/RULE.json`) and `cases.json`, which lists every file as `{file, expect, rule, applies}`. `rules.json` gives each rule id a sentence.

- A **reader** qualifies when it accepts every file whose `expect` is `valid` and rejects every file whose `expect` is `invalid` and whose `applies` is `reader` or `both`.
- A **writer** qualifies when it prints no file whose `expect` is `invalid`. The files whose `applies` is `writer` (a number written `1.0` or `3.0`, an integer beyond 2^53 - 1, `NaN`, a key written twice) are the ones most parsers take without a word, so a reader may accept them and qargi never prints them.
- The files of `qargi-refusal` are the whole line with its prefix (`qargi-refusal/1 {...}`); two broken files break the prefix.
- When a kind changes in a way that raises its integer, the old directory stays and a new one is made, so that a reader of the old integer keeps qualifying.

qargi's own checks are `python3 tests/test_json_registry.py` (the registry files are well formed, every fixture is what `cases.json` says, the live registry is the frozen copy plus additions that keep the integer, every field is in a fixture, the frozen copies equal the ones at the last release tag) and `bash tests/test_json_live.sh`, which runs every pinned verb on both backends of the marshal and validates its real output against the registry.
