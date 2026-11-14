# Backlog graph v1

This is the normative public contract for the bounded, read-only native graph
foundation. It describes manually declared relationships and reported evidence
against the configured open backlog. It grants no evaluation, approval,
acceptance, scheduler or execution authority.

## Commands and boundaries

```sh
qargi backlog graph check --graph graph.json [--project P] [--json]
qargi backlog graph show --graph graph.json [--project P] [--json]
qargi backlog graph why --graph graph.json --node backlog:some-id [--project P] [--json]
```

`--graph FILE` is required. Its path is relative to the caller's directory unless
absolute. `why` requires `--node REF`, a node declared in that graph. The other
actions reject `--node`. Project inference and `QARGI_PROJECT` work as for other
backlog commands. Malformed registry records, including JSON nesting beyond the
decoder's recursion limit, and non-string repository paths are skipped during
inference. A valid explicit project or `QARGI_PROJECT`
still wins, and valid repository matches use the longest containing path.
The graph replaces a leading `~` in `repo.path` and `backlog.file` literally
with the raw `HOME` value, including
forms such as `~name`, trailing slashes and an empty `HOME`. Relative backlog
paths are joined to `repo.path`. Remaining relative paths, including `--graph`,
are prefixed with the caller's directory. Paths retain symlink, `..`, `/./` and
terminal slash syntax so the kernel selects the file. A slash after a regular
file fails as unreadable rather than reading that file.

These are bounded prefix rules, not exact shell equivalence. With Bash's
`patsub_replacement` enabled, `backlog list` may replace `&` in `HOME` with the
matched tilde; the graph and shared project inference use raw literal `HOME`.
Shell command substitution of jq output also removes embedded NUL and trailing
newlines. The graph preserves those configured characters: NUL is unreadable,
and a trailing-newline filename is read literally or fails as `input-unreadable`
if absent. It does not silently select the shell's stripped filename.

Missing, null, empty-string and false `backlog.section` values mean no section
filter. Other values must be nonempty heading strings. Unlike `backlog list`,
`add` and `done`, which require a repository marker at `repo.path`, this reader
can observe an absolute configured backlog after the checkout has
gone. It requires a configured `repo.path` string but does not require a local
repository or create one. This narrow observation boundary grants no editing
authority.

`check` validates and reports findings. `show` also displays node projections.
`why` explains a selected node. JSON returns the native report below directly,
through the command's own `--json` metadata, without a plan/output envelope.
Exit 0 means valid inputs, including graphs with warnings or unknown states.
Exit 1 means invalid or unreadable data, missing configuration, or an undeclared
`why` node. Those failures also produce `valid:false` reports with `--json`.
Usage errors exit 2 and print usage on stderr.

An unavailable current directory prevents inference of a containing project.
With an explicit or environment project, absolute graph and backlog paths remain
usable with an accessible configuration. A relative graph path that needs the
missing directory produces an `input-unreadable` report. The public CLI's Bash
entrypoints can also print their own getcwd startup warnings in this situation;
the pure Python reader has no shell startup. This covers the graph and shared
inference boundaries, not every other command's cwd handling.

The graph branch sets `DA_NOSETUP` before shared initialization. It creates no
configuration or state directories, registry files, audit records, archives or
graph data. It uses no network and invokes no provider or forge. Existing
`backlog list`, `add` and `done` behavior is unchanged. Under the current guard,
**the public graph command remains lead-only**. Members may run `backlog list`,
and direct `backlog.sh graph` calls receive the same guard denial. The pure
`lib/backlog_graph.py` reader is permitted directly for members. Invoke it with
`python3 -B -I lib/backlog_graph.py` to suppress Python import-cache writes.
It performs no graph, configuration or state writes. Python may create bytecode
caches when invoked without `-B`. Public CLI compatibility and guard policy
do not grant access to future graph writes.

The input syntax below is supported independently of source observation. A valid
feature reference does not establish that a feature exists. Host support follows
qargi's Linux, bash and GNU tool requirements. The implementation uses only
Python 3.11+ standard-library APIs and syntax. Follow-up checks ran on Linux with
Python 3.14.8 and re-ran Python 3.11 AST grammar checks on the changed Python
source and tests. Grammar checks do not certify a Python 3.11 runtime, its date
parser behavior, or other operating systems.

## Closed input schema

The complete top-level object has exactly the following shape.

```json
{
  "format": "backlog-graph",
  "version": 1,
  "nodes": ["backlog:some-id", "backlog:other-id"],
  "relations": [
    {
      "id": "needs-other",
      "kind": "requires",
      "from": "backlog:some-id",
      "to": "backlog:other-id",
      "status": "confirmed",
      "provenance": {
        "by": "reviewer",
        "at": "2026-11-14",
        "basis": "manual review of the two items"
      }
    }
  ],
  "evidence": []
}
```

Every field shown is required. Empty arrays are valid, including `evidence:[]`.
Every object is closed. Unknown fields and duplicate JSON keys at any depth are
errors. Types are strict. Strings are strings, arrays are arrays, and `version`
is integer `1`, excluding booleans and floating-point `1.0`. Non-JSON numeric
constants are invalid. There is no accepted evidence input or runnable output.

Free-text `by`, `basis` and `ref` strings must contain only Unicode scalar
values. Escaped lone surrogates fail with a `provenance` finding; valid JSON
surrogate pairs decode to a scalar and are allowed, as is printable Unicode.
This field-level guarantee covers Unicode validity of provenance strings only.

| Field | Contract |
|---|---|
| `nodes[]` | Unique typed reference strings of the form `backlog:ID` or `feature:NAME`. |
| Backlog `ID` | The backlog parser's actual ID grammar is `[a-z0-9][a-z0-9-]*[a-z0-9]`, at least two characters. Repeated internal hyphens are allowed. Task-list boxes such as `[x]` are not IDs. |
| Feature `NAME` | The feature command's grammar is `[a-z0-9]+(-[a-z0-9]+)*`, at most 40 characters, excluding reserved `master` and `develop`. |
| Relation/evidence `id` | Stable lowercase slug matching `[a-z0-9]+(-[a-z0-9]+)*`. IDs must be unique across both arrays. |
| Relation `kind` | `requires` or `contains`. |
| Relation `from`, `to` | Declared typed nodes. Self edges are invalid. |
| Relation `status` | `confirmed` or `proposed`, both manual declarations. |
| Relation `provenance` | Exactly `by`, `at`, `basis`. All are strings, with nonempty words in `by` and `basis`. |
| `at` | A valid extended ISO8601 date `YYYY-MM-DD`, or timestamp with `T` and `HH:MM`, optional seconds (with optional fractional seconds), and optional `Z` or `±HH:MM` offset. Lowercase `t`/`z` and a decimal comma are also supported. Calendar dates, clock times and offsets are validated. Hours are restricted to 00 through 23 on every runtime. No current time is inferred. |

`requires` points from dependent to prerequisite. `contains` points from parent
to child. Duplicate relation semantics `(kind, from, to)` are invalid even if the
IDs or statuses differ. Confirmed requires cycles are invalid. Confirmed contains
cycles and multiple confirmed parents for one child are invalid. Proposed parents
do not count toward that restriction.

Cycles involving proposals generate `proposed-cycle` warnings per relation kind
and cyclic component, naming the proposed edge IDs participating in that cycle.
They never become confirmed dependencies. Traversals are iterative, so long
acyclic chains need no recursion adjustment or new arbitrary graph size limit.

Containment is structural only. It neither transfers evidence nor changes any
node's planning prerequisite or effective reported state. Requires and contains
cycles are checked separately. A path mixing the two is not a dependency path.

## Source identity and reported evidence

Every backlog node resolves against **all** items from the existing backlog
parser. Duplicate IDs anywhere in that file invalidate the report, including
duplicates outside `backlog.section` or IDs not declared in the graph.
`backlog.section` affects only each open node's `source.in_section` display
metadata. A missing configured heading remains an error, as with existing
backlog commands. No source identity is inferred from headings or containment.

An open node's `source` is `{digest, line, in_section}`, with the parser's
one-based line number. Its digest is the UTF-8 SHA-256 of
`"\n".join(item["full"])`. These are the parser's full item lines, including the first
line, continuation lines, internal blank lines and their literal whitespace,
without an added final newline. Source reading uses the parser's universal
newline normalization. The spelling is the literal `sha256:` prefix followed
by 64 lowercase hexadecimal digits.

Each evidence entry has exactly the following fields.

```json
{
  "id": "report-one",
  "node": "backlog:some-id",
  "level": "reported",
  "for_digest":
    "sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "ref": "test-log.txt",
  "by": "worker",
  "at": "2026-11-14T12:34:56Z"
}
```

Replace the example zero digest with the node's current `source.digest` from
`show --json`. `node` must be declared and must be a backlog node. Evidence for
feature nodes is unsupported. `level` must be `reported`. `ref` and `by` must
contain words, and `at` follows the provenance date rules. `ref` is a descriptive
reference. Qargi does not open it, run it, fetch it or verify its claim. Neither
the author nor the `confirmed` label supplies approval authority.

Matching reported evidence has report `state:"current"`. Every mismatched or
unresolvable evidence record remains in the report as `state:"superseded"`,
with an `evidence-superseded` warning. A later matching record can coexist with
superseded records. Nothing is deleted or accepted.

A missing or archived backlog node has `source:null`, an unknown state and a
`source-not-open` warning, without invalidating graph structure. Archives are
not read. Feature nodes are syntax-only. They have `source:null`, unknown state,
and `feature-not-observed`. No branch, local marshal record or remote is queried.
A missing or unreadable **backlog file**, in contrast, makes the input invalid.

The configured open backlog is the only source authority in this version.
Editing text under the same ID, changing its ID, or reflowing the parser's full
lines supersedes earlier evidence. Manual ID reuse is not protected. If exactly
the same full lines return, their digest matches again. This is revision
pinning, without enforced history or identity incarnation tracking.

## Conservative projections and explanations

Each node has the following descriptive fields.

| Field | Rule |
|---|---|
| `ref` | The node's typed reference string. |
| `source` | Null when unobserved, otherwise `digest`, `line` and `in_section` from the whole open backlog. |
| `own` | `reported` only with current matching reported evidence. Otherwise `unknown`. |
| `effective` | `reported` only if `own` is reported and every confirmed requires prerequisite is effectively reported. Otherwise `unknown`. |
| `prerequisites` | `unconstrained` with no requires edges. `proposed` with any proposed need. Otherwise `unknown` if any confirmed need is effectively unknown, or `reported` if every confirmed need is effectively reported. |
| `reasons` | All applicable own-evidence, stale-evidence, unobserved-source, unknown-prerequisite and proposed-need reasons, including relation IDs. |

Thus stale evidence propagates unknown through confirmed requires edges, even
when a dependent's own evidence still matches. Proposed edges never increase
effective reported state. They do not replace confirmed prerequisites. Any
proposed need makes planning prerequisite state proposed even when confirmed
needs are also unknown, and both kinds of reason remain visible. `unconstrained`
does not report completion. No state is permission to execute or accept work.

`why` follows requires edges, including proposals for diagnostics, and returns
one shortest path to each reachable node that has reasons. Ties use sorted
relation IDs. A visited set terminates proposed cycles. Each entry contains
`node`, `path` (typed nodes), `relations` (edge IDs along that path), and `reasons`.
The full relation records identify which path steps are proposed. Contains
edges are not traversed. This bounded explanation does not enumerate every
possible path. Superseded historical records remain diagnostics even when a
newer current record permits effective reported state.

`why` builds a complete path for every explained node, including the selected
node when it has reasons. For a requires chain of `n` nodes queried from its
dependent end, a reason at every node yields `n(n+1)/2` node entries across
those paths. Path construction and output can therefore grow quadratically.
Iterative traversal visits each reachable node once.

Each node reason and each `why` reason has one of these complete shapes.

| Reason | Fields |
|---|---|
| `source-not-open`, `feature-not-observed`, `no-current-reported` | `code` only. |
| `evidence-superseded` | `code` and `evidence`, a list of superseded evidence IDs. |
| `prerequisite-unknown`, `proposed-need` | `code`, singular `relation` containing one relation ID, and `node` containing the target typed reference. |

Reasons retain superseded evidence even when current evidence is also present.

## Report contract and stable codes

Every data report has `format:"backlog-graph-report"`, integer `version:1`,
`command` (`check`, `show` or `why`), boolean `valid`, `inputs`, `findings`,
`nodes`, `relations`, and `evidence`. Valid `why` reports also have `node` and
`why`. Nodes are sorted by typed reference. Relations and evidence are sorted by
ID. Findings use a stable sort over their contents. No current timestamps are added.
Array input order does not affect projections or explanations.

`inputs.graph` and `inputs.backlog` each contain `path` and `digest`. Paths are
absolute after successful resolution. When the caller's directory is unavailable,
an invalid report can retain the original relative graph argument. Digests cover
the complete bytes actually read,
including original line endings and JSON ordering, and use the same `sha256:`
spelling. Unconfigured paths are null. Digests are null for inputs not read
successfully or not reached before a configuration/read failure.
Paths containing NUL or characters that cannot be encoded for the filesystem
produce `input-unreadable` findings, just like ordinary filesystem read errors.
Text diagnostics escape all non-printable characters as explicit backslash
notation, including ESC, CR, newline, C1 and bidi controls. Printable Unicode is
preserved when the output encoding supports it. Other characters use escaped
notation rather than causing an encoding failure. Untrusted provenance text is
not displayed in text projections.
Byte digests intentionally change on graph reordering even when projections do
not. Invalid reports may have empty or partial result arrays. Consumers must
check `valid` before using projections. Invalid reports can contain escaped lone
surrogates in input paths and diagnostic messages. The Unicode scalar requirement
applies to provenance fields in valid reports. Validation stops at the first error.
Input order can determine which schema error is found first. This does not
promise a complete inventory of invalid declarations.

Findings have `code`, `severity` (`error` or `warning`) and a human `message`.
Details such as `node`, `evidence`, `kind`, `nodes` and `relations` appear where
applicable. Finding `evidence` is a single evidence ID, unlike the list in a
reason. Confirmed cycle errors include `kind`, sorted participant `nodes` and
sorted `relations` containing only confirmed edges inside cyclic components.
Text structure diagnostics also name their participant nodes and relations.
Multiple containment parent errors include `kind`, the child `node`, sorted
`nodes` containing that child and its confirmed parents, and sorted incoming
confirmed `relations`. If multiple children have multiple parents, the first
sorted child is reported. Messages can change. The following codes are the v1
contract.

| Codes | Meaning |
|---|---|
| `schema`, `version`, `typed-ref` | Closed schema, field/type/value or reference syntax failure. |
| `invalid-json`, `duplicate-json-key` | Invalid UTF-8/JSON, non-JSON constant, or repeated object key. |
| `duplicate-node`, `duplicate-id`, `duplicate-relation` | Repeated node, shared relation/evidence ID, or repeated relation semantics. |
| `endpoint`, `self-edge` | Undeclared endpoint/evidence node, or a self relation. |
| `provenance`, `feature-evidence` | Invalid provenance/evidence author/reference/date, or unsupported feature evidence. |
| `requires-cycle`, `contains-cycle`, `contains-multiple-parents` | Invalid confirmed structure. |
| `configuration`, `input-unreadable`, `source-unreadable` | Missing/invalid project backlog configuration, unreadable graph/backlog, or non-UTF-8 backlog. |
| `duplicate-backlog-id`, `source-section`, `unknown-node` | Duplicate source IDs, absent configured heading, or undeclared why node. |
| `proposed-cycle` | Warns that proposals participate in a cycle. |
| `source-not-open`, `feature-not-observed`, `evidence-superseded` | Warns of unobserved source or superseded reported evidence. These codes also occur in node reasons. |
| `no-current-reported`, `prerequisite-unknown`, `proposed-need` | Node/why reasons for absent current own evidence, unknown confirmed need, or proposed need. |

## Manual editing and compatibility

Create and edit graph JSON with an editor. Use `check` after edits and `show` to
obtain current source digests before recording evidence. Retain superseded
evidence when adding a new report if that history matters. The reader retains
what the input contains. It cannot enforce append-only editing or prevent an
editor from deleting or rewriting evidence, relations or provenance.

There is no lock, enforced history, compare-and-swap (CAS), atomic read of both
inputs, plan/apply command or acceptance record. Each digest identifies bytes
observed during that call, without guaranteeing they remain current afterward.
This foundation is independent of providers, settings, schedulers, forge APIs
and execution engines. It changes no backlog data or existing list/add/done
file formats. Unknown fields and versions fail closed rather than granting
future authority accidentally.

Future source observation for archives or features, and any atomic apply or
acceptance operation, require separate contracts and implementation. They must
not reinterpret this report's declarations or planning states as acceptance or
an execution guarantee.
