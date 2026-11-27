# Fixtures of the JSON kinds

One directory for each kind that qargi prints for a program to read (`lib/kinds/KIND.json` is its registry file), one subdirectory for each integer of the kind (`v1`). The tree is made of plain files: a consumer copies `tests/fixtures/json/` and needs nothing else of this repository to qualify its own reader or writer.

```
rules.json                       the rule ids of the broken files, with a sentence, who must reject the file and what a kind needs for it
KIND/v1/registry.json            the registry file of the kind as it was at the pin; never changed after it
KIND/v1/valid.json               a complete document: the real output of the scenario of scenario.sh
KIND/v1/valid-NAME.json          more real output: another backend, another call of the verb
KIND/v1/valid-minimal.json       the required fields only; a nullable required field is null
KIND/v1/valid-unknown-field.json valid.json with a field the registry does not name: a reader accepts it
KIND/v1/broken/RULE.json         valid.json with exactly one rule broken
KIND/v1/cases.json               every file above: {file, expect: valid | invalid, rule, applies}
scenario.sh                      how valid.json was made (qargi's own; a consumer does not need it)
```

## Qualifying a reader or a writer

`cases.json` is the contract of the copy.

- A **reader** qualifies when it accepts every file whose `expect` is `valid` and rejects every file whose `expect` is `invalid` and whose `applies` is `reader` or `both`. A reader stops on a `kind` it does not expect and on a `schema` it does not know, ignores fields it does not know, and never parses a text field.
- A **writer** qualifies when it prints no file whose `expect` is `invalid`: `applies` `writer` names the files a reader's parser may not see (a number written `1.0` or `3.0`, an integer beyond 9007199254740991, `NaN`, a key written twice), because most parsers take them in silence.
- `broken/enum-unknown.json` puts a word outside a closed enum; a word outside an `x-open` enum is not a break (a reader reads it as `unknown`), so no file of the tree closes one.
- Every number of a document is a JSON integer within plus or minus 2^53 - 1. A kind whose `stream` is `stderr` (the refusal) is one line: the prefix `qargi-refusal/N `, then the object on the same line, where N is the `schema` of the object. The files of that kind hold that whole line; the files `prefix-missing` and `prefix-number-differs` break the prefix.

## What the files are made from

`valid*.json` (not the minimal and the unknown-field file) are real output of the verbs of one fixed scenario (`scenario.sh`: a scratch project on the local backend, a second one with many features, a third on the shared refs backend, the clocks held), with only the values of the machine replaced by fixed ones: the scratch directory (`/work`), the host (`host`), the user (`user`) and the digest of a work tree. Everything else is made from them by `tests/test_json_registry.py`, which compares each file with what it makes and fails on a file that was edited by hand.

- `python3 tests/test_json_registry.py` is the static lint (six points: the registry files are well formed, every fixture is what `cases.json` says, every kind has its directory and its broken file for each rule that applies, the live registry is the frozen one plus additions that keep the integer, every field is in some valid fixture, the frozen files equal the ones at the last release tag).
- `python3 tests/test_json_registry.py --self-test` breaks a scratch copy of the tree in turn and expects the lint to fail by the right point.
- `python3 tests/test_json_registry.py --regen --tool CHECKOUT` runs the scenario in a checkout outside any run directory (in a scratch directory whose path has a fixed length, because the size cut of the handoff counts bytes) and writes the files; with `--check` it writes nothing and says whether the files are what the scenario makes now. `--freeze` copies the live registry files over the frozen ones, once, at the pin.

When a kind changes in a way that raises its integer, the old `vN` directory stays (a consumer keeps qualifying its old reader against it) and a new `vN+1` directory is made.
