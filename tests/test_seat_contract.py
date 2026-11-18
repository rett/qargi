#!/usr/bin/env python3
"""The contract of the lead seat (docs/reference/lead-seat.md) and the skeleton of its tests.

The seat is not built. `Seat` holds one test per rule of the contract, named after the rule (test_R7_...), with a docstring that
states the rule and the observable the test will check, and skipped with the reason "seat not built: R7": the builder of a slice
removes the skip of the rules the slice satisfies and writes the body.

`Contract` runs today and keeps the two in step: the rules are numbered from 1 without a gap and each once (a rule added in a
later revision takes the next number and stands in the section of its subject, so the numbers are not in page order; a rule that
is dropped keeps its number, marked withdrawn, and its test), each has exactly one test and every test names a rule, each rule
states its refusal, every reference to a rule or a point names one that exists, every point marked OPEN is listed at the end with
what is proposed and an alternative, every point that was decided is listed with the rule that states the decision and is open
nowhere, the contract names no path outside its roots (ROOTS, RECORDED, DECLARED and BELOW_DECLARED below say what a path may
start with), and what the design's first wave has not produced is listed, each thing with a wave, until it exists (NOT_PRODUCED).
It also holds the page to what it says it guarantees: the outside proof of `qargi host` states what it shows and against whom (a
guard rail, with the limits that make it one), and what a sandbox never holds, and what it can write, are conditions of the
supervising layer. The page's other statements that can be read from its text are held too: the projection has every field
the gate compares, a spool envelope names its transfer and S2 and S6 match it, and the archive of open runs opens regular
files only and has a limit for a transfer.
Offline. Run: python3 tests/test_seat_contract.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, unittest

ROOT =os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, "docs", "reference", "lead-seat.md")
NOT_BUILT = "seat not built: R%d"
WITHDRAWN = "withdrawn: R%d"

# A path the contract names starts at one of its three roots: the state root, the config root and the authority root. The authority
# store is a third root, outside the other two, for good: the lead decided the point that asked where it lives (O1 of the contract).
ROOTS = ("$STATE", "$CONF", "$AUTH")
# The two directories whose location the seat marker (below the config root) records: named by their field, not by a path.
RECORDED = ("<assignment_dir>", "<projection_dir>")
# The locations the assignment declares, named by their field too. A sandbox can write the first two, and the contract refuses every
# recorded path that overlaps them (R89): so the assignment has to name the state root of the role beside its clone.
DECLARED = ("<clone>", "<state_root>", "<mirror>")
# The one path the contract names below a declared location: the file in which the supervising layer records its placeholders (R99).
BELOW_DECLARED = ("<clone>/.git/info/exclude",)
# What the design's first wave was to produce and what does not exist yet. The contract names these files in one section only, the
# one that lists them as not yet produced and proposes the wave for each; a file that is produced leaves this list and that table.
RECONCILIATION = "## Reconciliation with the design's wave 0 (task F)"
NOT_PRODUCED = ("docs/reference/lead-seat-records.md", "docs/reference/lead-seat-projection.md", "docs/reference/lead-refusals.md",
                "docs/reference/handoff-note.md", "docs/reference/lead-readback.md", "docs/reference/lead-render-manifest.md",
                "lib/refusals.json", "lib/seat-records.json")
# The three things the design asks of that wave that are no file of their own.
NOT_PRODUCED_PARTS = ("the render manifest (3.9)", "the module interfaces (3.11)", "the full transition table (3.2)")

RULE = re.compile(r"^\*\*R(\d+)\*\*", re.M)
SCHEMA_ID = re.compile(r"^qargi[.-][a-z-]+/\d+$")
REPO_FILE = re.compile(r"^(lib|bin|tests|docs)/[\w./-]+$")
FENCE = re.compile(r"^```.*?^```[ \t]*$", re.M | re.S)
OPEN_HEADING = "## Open points"
DECIDED_HEADING = "## Decided points"


def contract():
    with open(CONTRACT, encoding="utf-8") as f:
        return f.read()


def rule_numbers(text):
    """The numbers of the rules, in the order they are defined (a rule is a paragraph that starts with **Rn**)."""
    return [int(n) for n in RULE.findall(text)]


def withdrawn_numbers(text):
    """The numbers of the rules that a later revision dropped: such a rule keeps its number in a paragraph that starts
    **Rn** (withdrawn), so no number is ever used for two rules."""
    return {int(n) for n in re.findall(r"^\*\*R(\d+)\*\* \(withdrawn\)", text, re.M)}


def rule_blocks(text):
    """{number: the text of the rule}: from its **Rn** to the next rule or the next heading."""
    starts = [(m.start(), int(m.group(1))) for m in RULE.finditer(text)]
    out = {}
    for i, (at, n) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        head = re.search(r"^#{1,6} ", text[at:end], re.M)
        out[n] = text[at:at + head.start()] if head else text[at:end]
    return out


def open_marks(text):
    """The open points marked in the body: [OPEN On] anywhere before the list at the end."""
    return set(re.findall(r"\[OPEN (O\d+)\]", text.partition(OPEN_HEADING)[0]))


def open_items(text):
    """{On: the text of its item} of the list under the heading at the end."""
    tail = text.partition(OPEN_HEADING)[2]
    parts = re.split(r"^- \*\*(O\d+)\*\*", tail, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def section(text, heading):
    """The text under a `## ` heading, up to the next one; empty when the page has no such heading."""
    _, found, tail = text.partition("\n" + heading + "\n")
    return tail.split("\n## ", 1)[0] if found else ""


def subsection(text, heading):
    """The text under a `### ` heading, up to the next heading of any level; empty when the page has no such heading."""
    _, found, tail = text.partition("\n" + heading + "\n")
    return re.split(r"\n#{1,6} ", tail, maxsplit=1)[0] if found else ""


def squash(text):
    """The text on one line with single spaces: a phrase of the page may run over a line break."""
    return " ".join(text.split())


def fenced_json(block):
    """The first fenced json example of a rule, parsed; None when the rule has none."""
    m = re.search(r"^```json\n(.*?)\n```", block, re.M | re.S)
    return json.loads(m.group(1)) if m else None


def decided_items(text):
    """{On: the text of its item} of the list of the points that were open in an earlier revision and are decided."""
    parts = re.split(r"^- \*\*(O\d+)\*\*", section(text, DECIDED_HEADING), flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def named_paths(text):
    """Every word with a slash that the contract writes as code: the words of its code spans (a span may run over a line break) and
    the quoted strings of its fenced blocks."""
    fences = FENCE.findall(text)
    prose = FENCE.sub("", text)
    words = []
    for span in re.findall(r"`([^`]+)`", prose):
        words += span.split()
    for block in fences:
        words += re.findall(r'"([^"\n]*)"', block)
    return sorted({w.lstrip("\"'([{").rstrip("\"',;:)]}.") for w in words if "/" in w})


def outside_the_roots(word, not_produced=()):
    """Why a named path is outside the roots, or None when it is inside (or is no path: a schema id, a file of this repository).
    NOT_PRODUCED names the files of this repository that the text may name although they do not exist."""
    if SCHEMA_ID.match(word):
        return None
    if REPO_FILE.match(word):
        return None if os.path.exists(os.path.join(ROOT, word)) or word in not_produced else "names a file this repository does not have"
    if word.startswith(tuple(r + "/" for r in ROOTS + RECORDED)) or word in BELOW_DECLARED:
        return None
    return "starts at no root of the contract"


def rule_tests():
    """{rule number: [names of the tests of Seat for it]} from the test names (test_R7_...)."""
    out = {}
    for name in dir(Seat):
        m = re.match(r"test_R(\d+)_\w+$", name)
        if m:
            out.setdefault(int(m.group(1)), []).append(name)
    return out


class Contract(unittest.TestCase):
    """What must hold today, before any rule is built."""

    @classmethod
    def setUpClass(cls):
        cls.text = contract()
        cls.numbers = rule_numbers(cls.text)

    def test_the_rules_are_numbered_from_one_without_a_gap_and_each_once(self):
        self.assertGreater(len(self.numbers), 0, "the contract defines no rule")
        # not in page order: a rule added in a later revision stands in the section of its subject, with the next number
        self.assertEqual(sorted(self.numbers), list(range(1, len(self.numbers) + 1)))
        said = re.search(r"\*\*R1\*\* to \*\*R(\d+)\*\*", self.text)      # the page says how far its rules go
        self.assertEqual(int(said.group(1)), max(self.numbers), "the first section names the last rule")

    def test_every_rule_has_exactly_one_test_and_every_test_names_a_rule(self):
        tests = rule_tests()
        self.assertEqual(sorted(set(self.numbers) - set(tests)), [], "rules without a test")
        self.assertEqual(sorted(set(tests) - set(self.numbers)), [], "tests that name a rule the contract does not have")
        self.assertEqual({n: t for n, t in tests.items() if len(t) != 1}, {}, "rules with more than one test")
        stray = [n for n in dir(Seat) if n.startswith("test_") and not re.match(r"test_R\d+_\w+$", n)]
        self.assertEqual(stray, [], "a test of Seat is named after its rule: test_R7_...")

    def test_every_rule_test_is_skipped_for_its_rule_and_states_the_rule_and_the_observable(self):
        gone = withdrawn_numbers(self.text)
        for n, names in sorted(rule_tests().items()):
            fn = getattr(Seat, names[0])
            with self.subTest(rule=n):
                doc = " ".join((fn.__doc__ or "").split())
                self.assertTrue(doc.startswith("R%d: " % n), "the docstring starts with the rule: R%d: ..." % n)
                self.assertIn(" Observable: ", doc)
                why = getattr(fn, "__unittest_skip_why__", None) if getattr(fn, "__unittest_skip__", False) else None
                if n in gone:                # a withdrawn rule keeps its test, skipped for good
                    self.assertEqual(why, WITHDRAWN % n)
                elif why is not None:        # a built rule has no skip; an unbuilt one names its rule
                    self.assertEqual(why, NOT_BUILT % n)

    def test_every_rule_states_its_refusal(self):
        gone = withdrawn_numbers(self.text)      # a withdrawn rule refuses nothing: its paragraph says what replaced it
        missing = [n for n, block in sorted(rule_blocks(self.text).items()) if n not in gone and "Refusal:" not in block]
        self.assertEqual(missing, [], "rules that do not say what a violation is refused with")

    def test_every_reference_names_a_rule_or_a_point_that_exists(self):
        known = set(self.numbers)
        cited = {int(n) for n in re.findall(r"\bR(\d+)\b", self.text)}
        self.assertEqual(sorted(cited - known), [], "the contract cites rules it does not define")
        points = set(open_items(self.text)) | set(decided_items(self.text))      # a point is listed as open or as decided
        cited_points = set(re.findall(r"\bO(\d+)\b", self.text))
        self.assertEqual(sorted(p for p in cited_points if "O" + p not in points), [], "the contract cites points it does not list")

    def test_a_decided_point_names_the_rule_that_states_it_and_is_open_nowhere(self):
        self.assertEqual(self.text.count(DECIDED_HEADING), 1, "the contract lists the points that were decided, once")
        decided, still_open = decided_items(self.text), open_items(self.text)
        self.assertGreater(len(decided), 0, "no decided point is listed")
        self.assertEqual(sorted(set(decided) & set(still_open)), [], "a point is decided or open, not both")
        for point, body in sorted(decided.items()):
            with self.subTest(point=point):
                self.assertRegex(body, r"\A \(R\d+(, R\d+)*\)\. Decided", "a decided point names the rules that state the decision")
        # a decided point keeps its number: over both lists the points are numbered from one without a gap, each once
        # (that none is still marked in a rule is the other test: a mark needs an item in the list at the end)
        numbers = sorted(int(p[1:]) for p in list(decided) + list(still_open))
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)), "the points are numbered from one without a gap")

    def test_no_open_point_is_left_unlisted_at_the_end(self):
        self.assertEqual(self.text.count(OPEN_HEADING), 1)
        last_heading = re.findall(r"^## .*$", self.text, re.M)[-1]
        self.assertEqual(last_heading, OPEN_HEADING, "the list of open points is the last section")
        marks, items = open_marks(self.text), open_items(self.text)
        self.assertEqual(sorted(marks - set(items)), [], "marked OPEN in a rule, not listed at the end")
        self.assertEqual(sorted(set(items) - marks), [], "listed at the end, marked nowhere in the contract")
        for point, body in sorted(items.items()):
            with self.subTest(point=point):
                self.assertIn("Proposed:", body, "an open point says what the contract proposes")
                self.assertRegex(body, r"Alternative|A cost either way", "an open point names an alternative or its cost")
        # every word OPEN in the body is a mark with a number: no point is open without a place in the list
        body = self.text.partition(OPEN_HEADING)[0]
        self.assertEqual(len(re.findall(r"\bOPEN\b", body)), len(re.findall(r"\[OPEN O\d+\]", body)))

    def test_the_contract_names_no_path_outside_its_roots(self):
        # a file of this repository exists, but for the files the reconciliation lists as not yet produced, and only in that section
        planned = section(self.text, RECONCILIATION)
        elsewhere = self.text.replace(planned, "") if planned else self.text
        bad = {w: why for w in named_paths(elsewhere) for why in [outside_the_roots(w)] if why}
        bad.update({w: why for w in named_paths(planned) for why in [outside_the_roots(w, NOT_PRODUCED)] if why})
        self.assertEqual(bad, {}, "paths named outside the roots")
        # a root is one of the three the contract has, and the point that asked whether the third may be one is decided, not open
        used = set(re.findall(r"\$[A-Z][A-Z_]*", self.text))
        self.assertEqual(sorted(used - set(ROOTS)), [], "roots the contract may not name")
        self.assertIn("O1", decided_items(self.text), "the authority root is a root since the point about it was decided")
        for field in RECORDED:
            self.assertIn('"%s"' % field.strip("<>"), self.text, "the seat marker records %s" % field)
        for field in DECLARED:
            self.assertIn('"%s": "%s"' % (field.strip("<>"), field), self.text, "the assignment declares %s" % field)
        for path in BELOW_DECLARED:      # an entry that the contract no longer names goes from the list
            self.assertIn(path, named_paths(self.text), "the contract names %s" % path)
        # no literal location: no absolute path, no home path
        self.assertEqual(re.findall(r"(?<![\w$<>./-])/[A-Za-z0-9_.][^\s`\"]*", self.text), [], "absolute paths")
        self.assertNotIn("~", self.text, "home paths")

    def test_what_the_first_wave_has_not_produced_is_listed_with_a_wave_until_it_exists(self):
        self.assertEqual(self.text.count(RECONCILIATION), 1, "the contract has the reconciliation with the design's wave 0, once")
        planned = section(self.text, RECONCILIATION)
        named = set(named_paths(planned))
        for path in NOT_PRODUCED:
            with self.subTest(path=path):
                self.assertIn(path, named, "the section lists %s as not yet produced" % path)
                self.assertFalse(os.path.exists(os.path.join(ROOT, path)), "%s exists now: it leaves the section and NOT_PRODUCED" % path)
        for part in NOT_PRODUCED_PARTS:
            self.assertIn("| %s |" % part, planned, "the section lists %s as not yet produced" % part)
        # one row for each, and every row proposes a wave
        rows = [line for line in planned.splitlines() if line.startswith("| ") and not line.startswith(("| ---", "| Not yet produced"))]
        self.assertEqual(len(rows), len(NOT_PRODUCED) + len(NOT_PRODUCED_PARTS), "one row for each thing that is not yet produced")
        for row in rows:
            with self.subTest(row=row.split("|")[1].strip()):
                self.assertRegex(row.split("|")[4], r"\bwave \d\b", "a row proposes the wave that produces it")
        # what the section proposes is the lead's to decide: it is an open point
        self.assertRegex(planned, r"\[OPEN O\d+\]")

    def test_the_projection_holds_every_field_that_the_gate_compares(self):
        blocks = rule_blocks(self.text)
        projection = fenced_json(blocks[21])
        self.assertIsNotNone(projection, "R21 writes the projection out")
        holder = projection["holder"]
        # R24 and R56 compare these with the assignment file; the projection has to have each of them to compare
        for field in ("project", "role_name", "unit", "runtime", "clone"):
            with self.subTest(field=field):
                self.assertTrue(field in holder or field in projection, "the projection of R21 has no %s to compare" % field)
                self.assertIn("`%s`" % field, blocks[24])
                self.assertIn("`%s`" % field, blocks[56])
        # the epoch is compared on its own (R57, R58), after R56: the holder does not repeat it, and no rule compares display ids
        self.assertIn("epoch", projection)
        self.assertIn("`epoch`", blocks[24])
        self.assertNotIn("epoch", holder)
        self.assertNotRegex(squash(blocks[56]) + squash(blocks[24]), r"compar\w* `?display_id")
        # the holder of the projection is the seat record's holder (R11) but for the epoch
        seat = re.search(r"\| `holder` \|[^|]*\| `\{([^}]*)\}`", blocks[11])
        self.assertIsNotNone(seat, "R11 lists the fields of the holder")
        self.assertEqual(set(holder), {f.strip() for f in seat.group(1).split(",")} - {"epoch"})

    def test_a_spool_envelope_names_its_transfer_and_the_steps_match_it(self):
        blocks = {n: squash(b) for n, b in rule_blocks(self.text).items()}
        envelope = re.search(r'\{"schema": "qargi\.spool/1"[^}]*\}', blocks[32])
        self.assertIsNotNone(envelope, "R32 writes the envelope out")
        self.assertEqual(re.findall(r'"(\w+)"', envelope.group(0)), ["schema", "project", "epoch", "tx", "kind", "sha256", "bytes"])
        self.assertIn("Every field is mandatory", blocks[32])
        # S2 and S6 take an envelope only when it names the open transfer: "the envelope of the open transfer only" is checkable
        for n in (35, 39, 96):
            with self.subTest(rule=n):
                self.assertRegex(blocks[n], r"`project`, `epoch` and `tx` are (those of|the seat record's)")
        # the one thing whose fields stay open is the content of a state envelope, and the form rule says so
        self.assertIn("content of a `state` envelope", blocks[18])
        self.assertIn("`tx`", squash(open_items(self.text)["O10"]))

    def test_the_ignore_line_of_the_dev_store_is_named_with_the_change_that_adds_it(self):
        r7 = squash(rule_blocks(self.text)[7])
        self.assertIn("`.gitignore` carries `.qargi-authority-dev`", r7)
        self.assertRegex(r7, r"This page adds no line to `\.gitignore`: the line comes with the change that makes `\$AUTH` resolve")

    def test_what_a_sandbox_can_write_is_a_condition_of_the_supervising_layer(self):
        blocks = rule_blocks(self.text)
        self.assertIn(102, blocks, "R102 states the condition that R89 rests on")
        self.assertIn("**R102**", section(self.text, "## Conditions of the supervising layer"))
        r102 = squash(blocks[102])
        for words in ("`clone`", "`state_root`", "temporary directory", "`TMPDIR`"):
            with self.subTest(words=words):
                self.assertIn(words, r102)
        # the rules that name the two declared places say that "no other" is the layer's condition, not a fact
        for n in (19, 89):
            with self.subTest(rule=n):
                self.assertIn("R102", blocks[n])
        self.assertNotIn("What a sandbox can write is what the assignment declares", squash(blocks[89]))
        self.assertIn("R102", squash(section(self.text, "## Limits of phase 1")))

    def test_the_archive_reads_regular_files_only_and_is_limited_for_a_transfer(self):
        blocks = {n: squash(b) for n, b in rule_blocks(self.text).items()}
        r91 = blocks[91]
        # what the broker opens and what it only records, in R91 and in the row of the walk in R88
        for words in ("no-follow and non-blocking flags", "regular file", "recorded by its path and its type"):
            with self.subTest(words=words):
                self.assertIn(words, r91)
        self.assertIn("non-blocking", blocks[88])
        # an unreadable file marks its run cut and kept: it no longer holds the step open
        self.assertIn("marks its run `cut`", r91)
        self.assertNotRegex(r91, r"cannot be read keeps the step open")
        # a limit for a transfer beside the one for a run: how many runs and how many bytes
        self.assertRegex(r91, r"\b\d+ runs\b")
        self.assertEqual(set(re.findall(r"(\d+) MiB", r91)), {"64", "256"})
        self.assertIn("`left_out`", r91)
        # the rules that follow the archive know what is left in place
        self.assertIn("left out", blocks[92])
        self.assertIn("cut", blocks[38])

    def test_the_outside_proof_says_what_it_shows_and_against_whom(self):
        blocks = {n: squash(b) for n, b in rule_blocks(self.text).items()}
        r33 = blocks[33]
        for name in ("QARGI_AUTH", "QARGI_CONF", "QARGI_HOME", "QARGI_STATE"):      # the first step refuses what moves a root
            self.assertIn(name, r33)
        self.assertIn("dev run", r33)
        # what it shows, and the cases in which it passes although the call is inside a sandbox
        self.assertIn("does not show that the call runs outside a sandbox", r33)
        for case in ("user namespace", "patched copy"):
            self.assertIn(case, r33)
        # signing: a private key file, never an agent
        self.assertIn("private key file", r33)
        self.assertIn("SSH_AUTH_SOCK", r33)
        # the payload has no nonce: the signature is made and checked in one call
        payload = re.search(r'\{"v":1,"ns":"qargi-host"[^}]*\}', r33)
        self.assertIsNotNone(payload, "the payload of the proof is written out")
        self.assertEqual(re.findall(r'"([\w-]+)"', payload.group(0)), ["v", "ns", "qargi-host", "project", "epoch", "tx", "rev"])
        # the rules that rest on the proof, and the gate, say that they are guard rails, and Limits says why
        for n in (33, 51, 76, 77):
            with self.subTest(rule=n):
                self.assertIn("guard rail", blocks[n])
        limits = squash(section(self.text, "## Limits of phase 1"))
        for words in ("user namespaces", "code of its own", "guard rails"):
            self.assertIn(words, limits)
        self.assertNotIn("which is what R33 proves", self.text, "the proof of R33 is no proof that the caller is outside")

    def test_what_a_sandbox_never_holds_is_a_condition_of_the_supervising_layer(self):
        blocks = rule_blocks(self.text)
        self.assertIn("**R101**", section(self.text, "## Conditions of the supervising layer"))
        r101 = squash(blocks[101])
        for words in ("`$AUTH`", "private key", "agent socket", "`--approved`", "credential"):
            with self.subTest(words=words):
                self.assertIn(words, r101)
        # the Roots table promotes "absent" to the rule
        row = [ln for ln in section(self.text, "## Roots").splitlines() if ln.startswith("| `$AUTH` |")]
        self.assertEqual(len(row), 1)
        self.assertIn("R101", row[0])

    def test_the_trace_has_a_row_for_each_change_that_the_review_of_revision_2_required(self):
        self.assertIn("This is revision 3 of the page", self.text)
        for heading in ("### The review of revision 1", "### The review of revision 2"):
            self.assertEqual(self.text.count("\n" + heading + "\n"), 1, "the trace has a part for each review: " + heading)
        rows = [ln for ln in subsection(self.text, "### The review of revision 2").splitlines() if re.match(r"\| \d+ \|", ln)]
        self.assertEqual([int(re.match(r"\| (\d+) \|", ln).group(1)) for ln in rows], list(range(1, 8)), "seven required changes")
        for row in rows:
            with self.subTest(row=row.split("|")[1].strip()):
                self.assertRegex(row, r"\bR\d+\b", "each row names the rules it changed")
        # the rules that revision 3 added are in the trace: each is named in a row
        traced = "".join(rows)
        for new_rule in ("R101", "R102"):
            self.assertIn(new_rule, traced)

    def test_the_path_reader_finds_what_it_must(self):
        # the check above is only as good as its reader: it must see a path in a code span, over a line break, and in a fenced block
        sample = "a `$STATE/x.json` b `/srv/a/b`, `$OTHER/y` and `marshal broker\nrun ../z/q` c\n```json\n{\"clone\": \"/srv/c\", \"s\": \"qargi.seat/1\"}\n```\n"
        self.assertEqual(named_paths(sample), ["$OTHER/y", "$STATE/x.json", "../z/q", "/srv/a/b", "/srv/c", "qargi.seat/1"])
        self.assertEqual([w for w in named_paths(sample) if outside_the_roots(w)], ["$OTHER/y", "../z/q", "/srv/a/b", "/srv/c"])
        self.assertIsNone(outside_the_roots("<projection_dir>/<project>/projection.json"))
        self.assertIsNone(outside_the_roots("tests/test_seat_contract.py"))
        self.assertIsNotNone(outside_the_roots("lib/no_such_module.py"))
        self.assertIsNone(outside_the_roots("lib/no_such_module.py", ("lib/no_such_module.py",)))      # listed as not yet produced
        # below a location the assignment declares, the one listed path and no other
        self.assertIsNone(outside_the_roots("<clone>/.git/info/exclude"))
        self.assertIsNotNone(outside_the_roots("<clone>/.git/config"))
        self.assertIsNotNone(outside_the_roots("<state_root>/runs"))

    def test_the_rule_reader_finds_what_it_must(self):
        # the same for the rules: a rule is a paragraph that starts with its number, wherever it stands; a withdrawn one says so
        sample = "**R2** (b). Text. Refusal: none.\n\n**R3** (withdrawn). R9 replaces it.\n\nsee **R7** and `**Rn** (withdrawn)`\n\n**R1** (a). Refusal: none.\n"
        self.assertEqual(rule_numbers(sample), [2, 3, 1])
        self.assertEqual(withdrawn_numbers(sample), {3})
        self.assertEqual(sorted(rule_blocks(sample)), [1, 2, 3])
        self.assertNotIn("Refusal:", rule_blocks(sample)[3])


def unbuilt(n):
    """The skip of a rule that is not built: the reason names the rule."""
    return unittest.skip(NOT_BUILT % n)


def withdrawn(n):
    """The skip of a rule that a later revision withdrew: its test stays, so the number is never used for another rule."""
    return unittest.skip(WITHDRAWN % n)


class Seat(unittest.TestCase):
    """One test per rule. Each is skipped until the slice that satisfies its rule is built."""

    # ---- the seat and its states

    @unbuilt(1)
    def test_R1_seated_and_unseated(self):
        """R1: a project is seated when its answers hold marshal.seat.mode = managed; with no marshal.seat it is unseated and no
        rule but R73 changes a verb; any other marshal.seat is an invalid marker, never read as unseated.
        Observable: with a marker the gate answers from the seat; without one every verb behaves as before; a marker with another
        mode or without a directory field makes a read verb exit 77 with seat-record-invalid."""

    @unbuilt(2)
    def test_R2_closed_list_of_states(self):
        """R2: a seat is in exactly one of held, accepted, collected, fenced, pending-readback, vacant.
        Observable: a projection with another state makes a gated verb exit 77 with seat-record-invalid; a seat record with
        another state makes the broker exit 1 with content-invalid and write nothing."""

    @unbuilt(3)
    def test_R3_at_most_one_holder(self):
        """R3: held, accepted and collected carry the current holder, pending-readback the incoming one, fenced and vacant none.
        Observable: after every step of a transfer the seat record and the projection have a holder exactly in those states, and
        never two."""

    @unbuilt(4)
    def test_R4_holder_kinds(self):
        """R4: holder.kind is lead or caretaker.
        Observable: an assignment with another seat_role exits 1 with assignment-invalid and the store is unchanged."""

    @unbuilt(5)
    def test_R5_epoch_is_never_reused(self):
        """R5: the first assignment names epoch 1, every later one the epoch above the highest an accepted assignment named; the
        seat's epoch changes at S5.
        Observable: an assignment with a lower, equal or skipping epoch exits 1 with assignment-invalid; the seat record's epoch
        is N after S1 to S4 and the new epoch after S5; after an abort the next accepted epoch is not the aborted one."""

    @unbuilt(6)
    def test_R6_no_lapse_with_time(self):
        """R6: no gate decision reads a clock, a lease length or the age of a record.
        Observable: with the clock moved forward by more than any lease the gate gives the same answer to every class in every
        state."""

    # ---- records and where they live

    @unbuilt(7)
    def test_R7_authority_root_resolution(self):
        """R7: the authority store is a third root, outside the state root and the config root; its path is resolved by the
        first case that holds, in this order: QARGI_AUTH; a dev run (the dev data root with -authority-dev); QARGI_HOME (with
        -authority); QARGI_STATE or QARGI_CONF set (no default); else the default data root with -authority. The dev run is
        tried before the case of no default; the repository's .gitignore carries .qargi-authority-dev (the line comes with the
        change that makes the authority root resolve, not with the contract); resolving creates nothing.
        Observable: the resolved path in each of the five cases, and the earlier case wins where two hold; with QARGI_STATE
        alone, in a run that is not a dev run, a broker verb exits 1 with authority-store-unsafe; .gitignore holds the line
        .qargi-authority-dev, git check-ignore accepts it in a checkout and git status shows nothing after a broker call of a
        dev run; no directory exists after resolving."""

    @unbuilt(8)
    def test_R8_authority_root_is_apart(self):
        """R8: the authority root is never at or below the state root, the config root or the data root, is mode 700 and the
        caller's, and qargi export never includes it; a store that passes may be opened, which does not show that the caller is
        outside a sandbox (nor does the outside proof of R33).
        Observable: a broker verb exits 1 with authority-store-unsafe for a root below either root, for mode 755 and for a
        file of mode 644 inside; nothing is read or written; an export archive holds no file of it."""

    @unbuilt(9)
    def test_R9_store_layout(self):
        """R9: the store of a project holds the seat, the history, the door copies by epoch and the files of each transfer, among
        them the archive of open runs where there were any; beside the projects the host audit, the broker key and the signers;
        the reserved names are not created.
        Observable: after a whole transfer the store holds exactly the named files (an orphans directory with manifest.json
        and one archive file for each run inside the state root only when runs were archived), the tx name has its form, the
        read-back and result files are numbered from 1 and never beyond 3, and no delegations directory or dormancy file
        exists."""

    @unbuilt(10)
    def test_R10_only_the_broker_writes_the_store(self):
        """R10: only the broker and qargi host write below the authority root; lead-side code never opens it.
        Observable: every lead-side verb gives the same output and exit status with the authority root absent; no lead-side
        verb changes a file of it."""

    @unbuilt(11)
    def test_R11_seat_record_fields(self):
        """R11: the seat record is one object with schema, project, rev, epoch, state, holder, tx, step, readback, updated_at and
        updated_by, of the stated types.
        Observable: the record after each step has exactly these fields and types; a projection of another shape makes a gated
        verb exit 77 with seat-record-invalid."""

    @unbuilt(12)
    def test_R12_seat_record_is_written_atomically(self):
        """R12: a write locks the store, re-reads, compares rev, writes a new mode-600 file beside the record and renames it.
        Observable: a reader that loops during many writes never sees a partial record; a writer whose rev moved exits 1 with
        seat-changed and writes nothing; the file is mode 600 and rev grows by one per write."""

    @unbuilt(13)
    def test_R13_order_of_writes(self):
        """R13: every step writes its own records, then the seat record, then the projection; at init S3 writes the marker before
        the seat record; S4 publishes the archive between its seat record and its projection, and S5 removes the archived run
        folders before its seat record.
        Observable: with a stop injected after each write of each step, the files written so far are those earlier in that
        order and none later."""

    @unbuilt(14)
    def test_R14_history_line_per_change(self):
        """R14: every change of state appends one line {at, epoch, tx, from_state, to_state, step, kind, by} to the history.
        Observable: after a transfer the history has one line per change in order, and the earlier lines are byte for byte
        unchanged."""

    @unbuilt(15)
    def test_R15_host_audit_line(self):
        """R15: every door call, every step and every qargi host call that passed the outside proof appends {ts, verb, project,
        tx, epoch, detail, by} to the host audit, refused door calls too; a qargi host call that R33 refuses, at its first step or
        by its proof, records nothing.
        Observable: the audit grows by one line per call, a refused assignment included, and by none for a qargi host call
        that exits 1 with host-in-sandbox."""

    @unbuilt(16)
    def test_R16_seat_marker(self):
        """R16: the marker is marshal.seat = {mode, assignment_dir, projection_dir} in the answers; only the broker writes it;
        project set refuses it and import never carries it.
        Observable: qargi project set PROJECT marshal.seat.mode managed is refused and changes nothing; an import of an
        export made from a seated project yields answers without marshal.seat."""

    @unbuilt(17)
    def test_R17_bound_directories_come_from_the_marker(self):
        """R17: the lead side takes the assignment and projection directories from the marker only; an environment variable
        naming either counts in a dev run only.
        Observable: outside a dev run, an environment that points both directories at records of another holder changes no
        gate answer."""

    @unbuilt(18)
    def test_R18_record_form_and_size_limits(self):
        """R18: a record is a UTF-8 JSON object without floats, control characters or unknown fields (the reserved fields and
        the content of a state envelope, whose fields O10 leaves open, excepted); closed lists accept only their values; limits
        8 KiB, 16 KiB, 64 KiB and 16 KiB.
        Observable: each violation at the door exits 1 with content-too-large, assignment-invalid or content-invalid as the
        rule says, and the store is unchanged; a state content with a field of its own is accepted."""

    @unbuilt(19)
    def test_R19_assignment_record(self):
        """R19: an assignment has the fields of qargi.assignment/1, among them the clone and the state root, the two places that
        the holder's sandbox can write and the authority side must not trust (R102 asks that there be no other), and the
        tracked paths that a read-only bind hides; init and transfer need all, vacate and unseat carry no to, clone,
        state_root or hidden_tracked; role_name is kebab-case, at most 64, without a colon.
        Observable: the valid example is accepted; each missing field (state_root among them), each field a kind may not carry
        and each bad role_name exits 1 with assignment-invalid."""

    @unbuilt(20)
    def test_R20_fence_record(self):
        """R20: a fence has the fields of qargi.fence/1; method is one of four; process-tree needs owner_confirmed; epoch_ended
        is 0 at init.
        Observable: the valid example is accepted; process-tree without owner_confirmed and an unknown method exit 1 with
        fence-unproven or content-invalid and change nothing."""

    @unbuilt(21)
    def test_R21_projection(self):
        """R21: the projection is one file with the fields of qargi.projection/1, among them the rev of the seat record it was
        written from and, in its holder, the role_name that R24 and R56 compare (not the display id, which holds the epoch),
        replaced by a rename inside its directory at every step.
        Observable: after each step the file has that shape, a new inode and the epoch, tx and rev of the seat record, a holder
        with the kind, role_name, display_id, runtime, unit and clone of the seat record's holder, no temporary file is left in
        the directory, and a projection of another shape makes a gated verb exit 77 with seat-record-invalid."""

    @unbuilt(22)
    def test_R22_reserved_fields_stay_empty(self):
        """R22: delegations and child_units accept only the empty list; an open run's actor is null or a label.
        Observable: a fence with a non-empty child_units exits 1 with content-invalid; every projection written has
        delegations equal to the empty list."""

    # ---- who holds a seat

    @unbuilt(23)
    def test_R23_who_may_hold(self):
        """R23: a seat is held only by the unit an accepted assignment names, from S5 of its transfer to the next fence; no
        verb run in a sandbox makes a unit the holder.
        Observable: the holder of the seat record always equals to.unit of the last committed assignment; no lead-side verb
        changes the holder."""

    @unbuilt(24)
    def test_R24_identity_is_bound_by_the_assignment_file(self):
        """R24: a session is the holder when its assignment file and the projection agree on project, role_name, unit, runtime,
        clone and epoch.
        Observable: with agreeing records a lead-write verb passes; changing any one of the six fields in the assignment file
        makes it exit 77 with records-disagree, previous-epoch or projection-stale."""

    @unbuilt(25)
    def test_R25_display_id_is_derived(self):
        """R25: the display id is <role_name>@e<epoch>, derived from the assignment file, never passed in.
        Observable: marshal status, marshal handoff and a run's record name that id; no option or variable changes it."""

    @unbuilt(26)
    def test_R26_labels_do_not_select_the_holder(self):
        """R26: on a seated project --as, QARGI_LEAD, QARGI_NESTED and the actor label change no gate answer and no display id.
        Observable: the gate's answer and the display id are the same with each of them set to another lead's name, for a
        holder and for a session that is refused."""

    @unbuilt(27)
    def test_R27_only_the_door_changes_the_holder(self):
        """R27: on a seated project marshal claim, take and release change nothing; takeover, forget, resign, key and signers
        are class owner.
        Observable: the first three exit 1 with seated-project and leave the per-feature record and the seat as they were; the
        others exit 77 with not-assigned for the holder and run only under qargi host."""

    @unbuilt(28)
    def test_R28_the_order_is_a_label(self):
        """R28: an assignment needs ordered_by, which the broker trusts as given.
        Observable: an assignment without ordered_by exits 1 with assignment-invalid; one with any non-empty value is accepted
        and the value is stored unchanged."""

    # ---- the door and the broker

    @unbuilt(29)
    def test_R29_the_door_checks_form_and_leaves_the_store(self):
        """R29: the door verbs read one record from standard input and check its form against the contract and the seat; a
        refused call leaves the store as it was apart from its audit line.
        Observable: a wrong project, an epoch gap, a fence for another epoch or unit, a fence that carries a field of the
        order: each exits 1 and every file of the store but the host audit is byte for byte unchanged."""

    @unbuilt(30)
    def test_R30_git_from_the_mirror_only(self):
        """R30: the broker reads git only from the mirror the assignment names, with the environment for an untrusted tree, and
        never runs git in a clone.
        Observable: with a hook, an alias and an fsmonitor command planted in the configuration of the clone and of the
        mirror, a canary file is untouched after a whole transfer."""

    @unbuilt(31)
    def test_R31_the_broker_leaves_the_role_state(self):
        """R31: the broker never writes below a role's state root, the location state_root of its assignment names, and reads
        nothing there by path, except the archive and removal of run folders while the seat is fenced.
        Observable: the role's state root is byte for byte the same before and after S1 to S6 with no open run; the broker
        works with that root unreadable."""

    @unbuilt(32)
    def test_R32_spool_envelope(self):
        """R32: lead content reaches the authority side as a spool envelope {schema, project, epoch, tx, kind, sha256, bytes},
        every field mandatory, followed by the content, written by one of the verbs of R96 (which take project, epoch and tx from
        the projection) and passed through broker intake, which takes it only when project, epoch and tx are the seat record's.
        Observable: a valid envelope of each kind is stored; one over its limit exits 1 with content-too-large; a malformed
        one, a missing or null field, a wrong digest or length, another project, another epoch and another tx (the envelope of
        an aborted transfer, for one) exit 1 with content-invalid; the store is unchanged."""

    @unbuilt(33)
    def test_R33_owner_verbs_go_through_host(self):
        """R33: before anything else qargi host refuses when QARGI_AUTH, QARGI_CONF, QARGI_HOME or QARGI_STATE is set or the run
        is a dev run (a test of qargi host sets one switch that lifts this step and no other), then makes the outside proof: the
        authority root passes R8, a payload (project, epoch, tx, rev: no nonce) that it signs with the broker's private key file,
        with no agent in reach, verifies against the signers line of the projection, and the seat record agrees with the
        projection in epoch, tx and rev; then it appends its audit line and runs the verb. The proof shows that the call reads a
        store, a projection and a key that agree, not that it runs outside a sandbox: it is a guard rail against a mistaken or
        stale lead. No variable, option or file stands for a proof that passed.
        Observable: with the true store the audit line exists before the verb's first effect; with each of the four variables
        set, and in a dev run, it exits 1 with host-in-sandbox before it reads a store; with the test switch set and a store the
        caller made (mode 700, its own key and a copied seat record) it exits 1 with host-in-sandbox, the verb did not run and
        no file changed; the same with the true store and its key file replaced by the public key while an agent that holds the
        private key is reachable through SSH_AUTH_SOCK, with the true key and a seat record whose rev is behind the projection,
        with the true store and an audit log that cannot be appended to, and for a verb that names an unseated project; a verb
        that names no project runs when the proof passes for one seated project and is refused when there is none; and, as the
        limit that Limits names, roots that the test made whole (marker, projection, signers line, key, seat record) pass the
        proof, which a test keeps so that nobody claims more of it."""

    # ---- the handoff protocol

    @unbuilt(34)
    def test_R34_S1_accept(self):
        """R34: S1 needs a transfer assignment and a held seat, writes the copy, the seat (accepted, new tx) and the projection;
        from then A's lead-write verbs are refused, all but marshal seat state --submit.
        Observable: after S1 the seat and projection say accepted and A's lead-write verb exits 77 with
        transfer-in-progress while its read verb and its marshal seat state --submit pass."""

    @unbuilt(35)
    def test_R35_S2_collect(self):
        """R35: S2 takes A's spool state, which A wrote with marshal seat state --submit and which may be empty, when its
        envelope's project, epoch and tx are the seat record's, and writes the copy, the seat (collected) and the projection;
        it may be skipped.
        Observable: with and without a state the seat reaches collected; a state envelope of another transfer is not taken
        (exit 1, content-invalid); S3 from accepted is accepted too."""

    @unbuilt(36)
    def test_R36_S3_fence(self):
        """R36: S3 needs an accepted fence for the ending epoch and writes the fence copy, the seat (fenced, no holder) and the
        projection; the fence comes before the note, S3 before S4, S5 and S6, and no later step runs without it.
        Observable: with the fence the seat is fenced with holder null; without one, asking for S3 or a later step exits 1
        with fence-required and changes nothing; no note file exists before the fence copy does."""

    @unbuilt(37)
    def test_R37_S4_note(self):
        """R37: after S3 and the archive of open runs the broker builds and signs the note and writes the note files, the seat,
        the published archive and the projection.
        Observable: after S4 the three note files exist, the seat names the note's version and the projection carries the
        note with its digests."""

    @unbuilt(38)
    def test_R38_S5_commit(self):
        """R38: S5 first removes the run folders that were archived whole, then writes the seat (pending-readback, B, the new
        epoch) and the projection; B reads but may not write, its marshal seat readback --submit excepted.
        Observable: after S5 B's read verb and its marshal seat readback --submit pass and its other lead-write verbs exit 77
        with readback-pending; the seat's epoch is the new one; the run folders archived whole were gone before the seat
        changed and the folder of a cut run is still there."""

    @unbuilt(39)
    def test_R39_S6_check(self):
        """R39: S6 checks B's read-back, taken when its envelope's project, epoch and tx are the seat record's; on a match the
        seat is held and B is the lead; without one the seat stays pending-readback and B may read back again, up to three
        compared read-backs for a transfer; one that is refused before the comparison is not counted.
        Observable: a matching read-back gives held with readback matched and B's lead-write verb passes; a failing one exits
        1 with readback-mismatch, stores the result with its attempt and leaves pending-readback; a second, matching one then
        succeeds; after three failed comparisons a fourth read-back exits 1 with readback-exhausted, stores nothing and
        leaves the seat as it was; a read-back refused for its form, for another transfer or for another note version leaves
        the count as it was."""

    @unbuilt(40)
    def test_R40_interruption_and_resume(self):
        """R40: a transfer may stop between any two writes; seat status names the open step, broker run completes it and a
        second broker run changes nothing.
        Observable: for a stop after each write of S1 to S6 and of S3 at init, the state is the one the table gives, seat
        status names the step, broker run reaches the completed state and a second run exits 0 with no file changed."""

    @unbuilt(41)
    def test_R41_re_note(self):
        """R41: when a tip or a stored record changes after S4 and before a match, the note is built again as the next version
        in the same tx.
        Observable: after a tip moves the note has version 2 under the same tx, and a read-back that names version 1 exits 1
        with note-digest-mismatch."""

    @unbuilt(42)
    def test_R42_abort(self):
        """R42: before S3 broker abort returns the seat to held with A; from S3 on it changes nothing.
        Observable: an abort after S1 or S2 gives held at epoch N and A's lead-write verb passes again; an abort after S3,
        S4 or S5 exits 1 with abort-after-fence and the seat is unchanged."""

    @unbuilt(43)
    def test_R43_one_transfer_at_a_time(self):
        """R43: while S1 or S2 is open a new assignment for the project is refused.
        Observable: a second assignment of any kind or role exits 1 with transfer-open and the store is unchanged."""

    @unbuilt(44)
    def test_R44_init(self):
        """R44: a project is seated by an init assignment and a process-tree fence confirmed by the owner with epoch_ended 0; S3
        writes the marker, the seat and the projection in that order; the first holder has epoch 1.
        Observable: after init the marker, the seat and the projection exist and the holder has epoch 1; another fence method
        or a missing confirmation exits 1 with fence-unproven and no marker is written."""

    @unbuilt(45)
    def test_R45_vacate(self):
        """R45: a vacate assignment runs S1 and S3 and leaves the seat vacant; a vacant seat takes a transfer with a no-unit fence.
        Observable: after a vacate the seat is vacant with holder null and a read verb exits 77 with seat-vacant; a transfer
        with a no-unit fence then completes."""

    @unbuilt(46)
    def test_R46_note_content(self):
        """R46: the note has schema qargi.handoff/2 and the listed fields, active features first, lead-written content below
        lead_stated or marked unverified, a text form of at most 16 KiB whose first line names the JSON's digest.
        Observable: a note built from a fixture has exactly those fields, the order, the digest line and the bound; text a
        lead wrote appears nowhere outside lead_stated and the unverified lists."""

    @unbuilt(47)
    def test_R47_note_signature(self):
        """R47: the broker signs the note's payload with its key, and the signers line it writes into the projection names that
        key for the namespaces qargi-handoff and qargi-host; note verify checks both digests, the signature against the
        projection's signers line, and the transfer id and version.
        Observable: note verify exits 0 on the note as written; a changed byte of either form exits 1 with
        note-digest-mismatch; another key, transfer id or version exits 1 with note-invalid; the signers line of every
        projection lists both namespaces."""

    @unbuilt(48)
    def test_R48_read_back_record(self):
        """R48: a read-back is {project, transfer_id, note_sha256, epoch, believes} of schema qargi.readback/1, its transfer_id
        the tx of the envelope that carries it; seat readback --template prints the empty one and seat readback --submit FILE
        writes the filled one into the spool.
        Observable: the template parses, has every field and is accepted when filled in and submitted; an unknown field, or a
        transfer_id that is not the envelope's tx, exits 1 with content-invalid and one over 64 KiB with content-too-large."""

    @unbuilt(49)
    def test_R49_check_of_the_read_back(self):
        """R49: the broker compares the fields of readback_fields with the note, the mirror's tips and the assignment; the
        projection carries the checks with id, ok and reason, never an expected value.
        Observable: a read-back with a wrong develop yields a check with ok false and a reason of the closed list; the
        projection's last_result holds no value of the note or the mirror; the full result is in the store."""

    @unbuilt(50)
    def test_R50_seat_status(self):
        """R50: marshal seat status --json prints one object of schema qargi.seat-status/1 and reads only, in every state.
        Observable: in each state the object has the listed fields and next_action; no file changes; the verb exits 0 for a
        session that every other verb refuses."""

    # ---- exclusivity

    @unbuilt(51)
    def test_R51_one_gate_four_classes(self):
        """R51: every verb has one of the classes always-open, read, lead-write, owner (the broker verbs and qargi host are
        host), the three verbs that write a spool envelope being lead-write and every verb that writes below the config root,
        the clone's runtime configuration or the clone's .git/info/exclude being owner, and one gate in the preamble decides
        before the verb runs; an unseated project costs no extra process. The gate is a guard rail: it refuses a session that
        runs qargi as it is and does not stop a lead that runs code of its own.
        Observable: every verb the commands table describes has a class; a refused verb has no effect at all; for an
        unseated project a command starts the same number of processes as before."""

    @unbuilt(52)
    def test_R52_order_of_the_conditions(self):
        """R52: the conditions are tried in the order of their rules and the first that holds decides; from the held state on,
        class owner is answered not-assigned.
        Observable: for each pair of conditions made to hold at once the earlier one's code is printed; an owner verb in a
        vacant seat gets not-assigned."""

    @unbuilt(53)
    def test_R53_condition_unseated(self):
        """R53: with no marker and readable answers every class passes.
        Observable: one verb of each class passes on an unseated project."""

    @unbuilt(54)
    def test_R54_condition_answers_unreadable_or_invalid(self):
        """R54: with unreadable answers or an invalid marker always-open passes and the other classes are refused.
        Observable: read, lead-write and owner verbs exit 77 with seat-record-invalid; seat status exits 0."""

    @unbuilt(55)
    def test_R55_condition_no_bound_record(self):
        """R55: with the marker set and the assignment file or the projection missing, always-open passes and the other classes
        are refused: what a session the supervising layer did not assign gets.
        Observable: with either file missing, read, lead-write and owner verbs exit 77 with seat-record-missing."""

    @unbuilt(56)
    def test_R56_condition_records_disagree(self):
        """R56: when the projection carries a holder and the assignment file and the projection differ in project, role_name,
        unit, runtime or clone, always-open passes and the other classes are refused; where the holder is null, in fenced and
        in vacant, the condition is skipped.
        Observable: for each of the five fields, read, lead-write and owner verbs exit 77 with records-disagree; in fenced
        and in vacant a session with an assignment file of the seat's epoch gets the answer of R60 or R62
        (transfer-in-progress, seat-vacant) and never records-disagree."""

    @unbuilt(57)
    def test_R57_condition_previous_epoch(self):
        """R57: when the assignment file's epoch is below the projection's, always-open passes and the other classes are
        refused: what a stale lead gets after the cutover.
        Observable: A's read, lead-write and owner verbs exit 77 with previous-epoch after S5."""

    @unbuilt(58)
    def test_R58_condition_projection_stale(self):
        """R58: when the assignment file's epoch is above the projection's, always-open and read pass.
        Observable: a read verb passes; lead-write and owner verbs exit 77 with projection-stale."""

    @unbuilt(59)
    def test_R59_condition_held_by_a_lead(self):
        """R59: in held with a lead holder of the same epoch, always-open, read and lead-write pass.
        Observable: those pass for the holder; an owner verb exits 77 with not-assigned."""

    @unbuilt(60)
    def test_R60_condition_transfer_open(self):
        """R60: in accepted, collected and fenced, always-open and read pass, and of the lead-write verbs only marshal seat
        state --submit, in accepted only.
        Observable: in each of the three states a lead-write verb exits 77 with transfer-in-progress and an owner verb with
        not-assigned; marshal seat state --submit passes in accepted and exits 77 with transfer-in-progress in collected
        and in fenced."""

    @unbuilt(61)
    def test_R61_condition_read_back_pending(self):
        """R61: in pending-readback, always-open and read pass, and of the lead-write verbs only marshal seat readback --submit.
        Observable: B's lead-write verb exits 77 with readback-pending and its owner verb with not-assigned; B's marshal seat
        readback --submit passes; marshal seat state --submit and marshal caretaker request exit 77 with readback-pending."""

    @unbuilt(62)
    def test_R62_condition_vacant(self):
        """R62: in vacant only always-open passes.
        Observable: read and lead-write verbs exit 77 with seat-vacant, an owner verb with not-assigned."""

    @unbuilt(63)
    def test_R63_condition_held_by_a_caretaker(self):
        """R63: in held with a caretaker, always-open and read pass and of the lead-write verbs only env check, doctor, packs
        check and marshal caretaker request, the exceptions of the caretaker's row among the derived classes (R98).
        Observable: the four exceptions pass; every other lead-write verb of the commands table exits 77 with
        caretaker-denied; an owner verb exits 77 with not-assigned, not caretaker-denied."""

    @unbuilt(64)
    def test_R64_condition_no_project_named(self):
        """R64: a verb that names no project is answered by this condition alone: where some project under the config root is
        seated (an answers file that cannot be read or holds an invalid marker counts as seated), it passes unless its class is
        owner, inside a sandbox and outside; the owner runs it through qargi host.
        Observable: with one seated project such an owner verb exits 77 with not-assigned whatever the authority root is
        (absent, the true store, a store the caller made); verbs of the other classes pass; under qargi host with the true
        store the owner verb runs; with no seated project every class passes."""

    @unbuilt(65)
    def test_R65_refusal_line(self):
        """R65: every lead refusal and door refusal prints one line qargi-refusal/1 plus a JSON object {code, exit, verb,
        project, role, epoch, state, tx, detail} of at most 4 KiB on standard error; detail never carries text a lead wrote.
        Observable: every refusal of this file has exactly one such line that parses and whose exit equals the exit status;
        with a marker string planted in every lead-written field the line never contains it."""

    @unbuilt(66)
    def test_R66_exit_statuses(self):
        """R66: 0 done, 1 refused, 2 usage, 3 remote not checked, 70 a defect, 77 a lead refusal; a verb that gets 77 from a
        verb it runs exits 77 and passes the line on.
        Observable: a flow verb whose inner marshal question is refused by the gate exits 77 and its standard error holds
        the inner refusal line once."""

    @unbuilt(67)
    def test_R67_the_preamble_decides(self):
        """R67: the preamble's first field is ok, refused or usage; refused exits 77, usage exits 2; no answer, another field
        or a gate that fails in any way is gate-error.
        Observable: with the preamble made to print each of ok, refused, usage, nothing and garbage, and the gate made to
        exit 1, 4, 70, 127, 137, be absent or hang, the command exits 0, 77, 2 and 77 with gate-error for all the rest."""

    @unbuilt(68)
    def test_R68_what_is_not_gated(self):
        """R68: the run-event hooks, help, completion, the guard's entry and campaign check --spec are not gated; the --json
        wrapper is gated by the run it wraps and the other campaign verbs before they start.
        Observable: in a vacant seat the ungated entries run; a --json run of a refused verb exits 77; a campaign state verb
        exits 77 before its program starts."""

    @unbuilt(69)
    def test_R69_the_store_checks_again(self):
        """R69: on a seated project a write of a per-feature record reads the projection again inside the feature's lock.
        Observable: with the projection changed to accepted between the preamble and the write, the write is refused with
        exit 77 and the record is unchanged."""

    @unbuilt(70)
    def test_R70_door_refusal_codes(self):
        """R70: the exit-1 codes are a closed list, each raised as the table says, each with the refusal line.
        Observable: each code of the table is produced by its trigger with exit 1; no refusal of the seat verbs prints a code
        outside the two lists."""

    @unbuilt(71)
    def test_R71_per_feature_questions_are_answered_by_the_seat(self):
        """R71: on a seated project marshal check and the flow verbs' question are answered from the projection; set and finish
        pass for the holder; status and handoff name the holder's display id.
        Observable: the holder gets yours and exit 0 on a feature whose record names another lead; a session that is not
        the holder gets exit 77; status and handoff show the display id."""

    @unbuilt(72)
    def test_R72_renewal_is_a_no_op(self):
        """R72: on a seated project marshal renew exits 0 and writes nothing, and local prepare records the holder's display
        id as the run's lead.
        Observable: the per-feature record is byte for byte unchanged after a renew and after a long verb's renewer ran; the
        registry line of a prepared run has the display id."""

    @unbuilt(73)
    def test_R73_unseated_projects_fail_closed(self):
        """R73: on an unseated project the marshal question lets a flow verb or local prepare go on only on exit 0, or on exit
        3 with the override for an unreachable remote.
        Observable: with the question made to exit 70 and 127 the verb stops, names the status and changes nothing; with 3
        and no override it stops; with 3 and the override it goes on."""

    @unbuilt(74)
    def test_R74_shared_backend_and_seat_exclude_each_other(self):
        """R74: on a seated project marshal enable is refused, and a project on the shared refs backend is not seated.
        Observable: both exit 1 with refs-backend-active; the switch file and the store are unchanged."""

    @unbuilt(75)
    def test_R75_caretaker_transitions(self):
        """R75: the rows C1 to C7 are the only caretaker transitions, each with its fence method, steps and read-back; marshal
        caretaker request writes a spool envelope and changes no seat.
        Observable: each of C1 to C4 and C7 completes with its fence and is refused with another method; C4 ends in held
        with readback waived; C5 exits 1 with caretaker-not-vacant, C6 with transfer-open."""

    # ---- what never transfers

    @unbuilt(76)
    def test_R76_no_approval_from_inside(self):
        """R76: on a seated project a verb given --approved is refused before it does anything, unless a qargi host call that
        passed the outside proof runs it; a guard rail against a mistaken or stale lead, not a hostile one (a lead that runs code
        of its own or presents roots of its own is not stopped by it, which R101, R102 and R89 bound instead).
        Observable: typed without qargi host, each verb that takes --approved exits 1 with approval-refused and leaves no file
        changed, with the true store present and with every variable of a qargi host call set by hand too; under qargi host
        with the true store it is accepted; under qargi host with a store the caller made the call exits 1 with
        host-in-sandbox."""

    @unbuilt(77)
    def test_R77_plan_tokens_do_not_cross(self):
        """R77: qargi host computes a plan token over the plan preceded by a line only it adds, so a lead's token never matches;
        the line is no secret, so this is a guard rail against a token that crosses by mistake and not against a forged one.
        Observable: the token a lead's plan prints is refused under qargi host for the same plan; the token qargi host
        prints is accepted."""

    @unbuilt(78)
    def test_R78_nothing_that_authorizes_is_carried(self):
        """R78: the note, the seat record, the projection, the spool copies and the results hold no approval text, plan token
        or owner's words; the note says authority none and lists what not to assume.
        Observable: with a marker string as the approval words and a known token in the outgoing lead's state, neither
        occurs in any file of the store or the projection; the note has authority none and a non-empty do_not_assume."""

    @unbuilt(79)
    def test_R79_the_owners_words_stay_with_the_owner(self):
        """R79: the record of a release cut is written below the owner's state root by qargi host, never below a role's state
        root or the authority root.
        Observable: after a cut through qargi host the record exists below the owner's state root and the words occur in no
        file of the role's state root or the authority root."""

    # ---- what is preserved

    @unbuilt(80)
    def test_R80_a_transfer_leaves_the_role_state_alone(self):
        """R80: S1 to S6 change nothing below the role's state root but the run folders R92 removes.
        Observable: the per-feature records, the registry of local runs, the suite records and the audit log have the same
        digests before and after a transfer."""

    @unbuilt(81)
    def test_R81_a_lease_does_not_block_the_successor(self):
        """R81: a per-feature record that names the previous holder with a live lease neither refuses the new holder nor needs
        a takeover.
        Observable: B's feature merge and local prepare pass on such a feature without --approved, and the record names B
        only after B's own verb wrote it."""

    @unbuilt(82)
    def test_R82_open_runs_are_carried_by_name(self):
        """R82: the note lists every open run as {run, feature, state, actor} and the read-back as {run, feature, actor};
        open_runs is a checked field.
        Observable: the note of a fixture with two open runs lists both; a read-back that omits one or adds one exits 1
        with readback-mismatch and a check named open_runs."""

    @unbuilt(83)
    def test_R83_the_evidence_of_a_transfer_is_kept(self):
        """R83: no step removes or rewrites an accepted assignment, a fence, a note version, a read-back or a result; after an
        unseat the store stays, read only.
        Observable: the digests of those files are unchanged by every later step and transfer; after an unseat they exist
        and no file or directory of the project's store has a write bit."""

    @unbuilt(84)
    def test_R84_the_clone_is_handed_over_in_place(self):
        """R84: the clone and the state root stay the role's across epochs; the note lists uncommitted work as lead-stated,
        unverified data and the hidden tracked files as the supervising layer's data, copied from the assignment and not
        lead-stated; a verb that writes below the config root, the clone's runtime configuration or the clone's
        .git/info/exclude is class owner.
        Observable: hidden_tracked of the note equals the assignment's and stands outside lead_stated; uncommitted work is
        marked unverified; each such verb exits 77 with not-assigned for the holder and runs under qargi host."""

    # ---- conditions of the supervising layer

    @unbuilt(85)
    def test_R85_managed_at_fence_time(self):
        """R85: the marker is written only by S3 of an init, after a fence that the owner confirmed; no other verb sets it.
        Observable: no marker exists after S1 of an init or after an init with no or an unconfirmed fence (exit 1,
        fence-required or fence-unproven); it exists after S3; from then a session without a bound assignment exits 77."""

    @unbuilt(86)
    def test_R86_the_undo_is_a_named_owner_step(self):
        """R86: a project is unseated only by an unseat assignment and a fence through broker unseat; the marker goes last,
        after its value is stored; output and audit say the refusals no longer apply.
        Observable: after unseat the answers hold no marker, the transfer's records hold its value, and the output and the
        audit line say so; without the fence it exits 1 with fence-required and the marker stays."""

    @unbuilt(87)
    def test_R87_never_half_managed(self):
        """R87: a project with the marker set is never treated as unseated, whatever is missing or unreadable.
        Observable: with the marker set and, in turn, no assignment file, an unreadable one, no projection and a partly valid
        marker, a lead-write verb exits 77 and no per-feature record changes."""

    @unbuilt(88)
    def test_R88_no_path_is_followed_through_a_link(self):
        """R88: every path a seat verb reads or writes is resolved one component at a time without following a symbolic link,
        at the time of use; the path of a root is resolved once and what it resolves to must pass an owner-only check as in
        R8 before anything below it is opened.
        Observable: for each row of the table, a symbolic link put in place of the file and of each directory component
        after it was recorded makes the authority side exit 1 with symlink-refused and the gate exit 77 with
        seat-record-invalid, and the link's target is neither read nor written (a link inside a run folder is no path
        component: R91 records it by type); a root that resolves to a directory of
        another owner, or one that group or others can enter, makes the authority side exit 1 with authority-store-unsafe
        and the gate exit 77 with seat-record-invalid, and nothing below it is opened."""

    @unbuilt(89)
    def test_R89_nothing_a_sandbox_can_write_is_trusted_by_path(self):
        """R89: authority-side code uses no path with a component a sandbox can write; qargi knows what a sandbox can write from
        the clone and the state root that the assignment declares, and that there is no other such place that the authority
        side reads is the supervising layer's condition (R102); the assignment directory, the projection directory, the mirror
        and the authority and config roots are refused when equal to, below or containing either; who owns a path is not the
        test.
        Observable: an assignment whose mirror lies below its clone, equals its state root or contains its clone exits 1 with
        assignment-invalid; a marker whose directory lies below the declared state root makes authority-side verbs exit 1
        with authority-store-unsafe; a path outside both declared locations is accepted whoever owns its components, which is
        the limit that R102 names: qargi does not see a place the assignment does not declare."""

    @unbuilt(90)
    def test_R90_archive_before_remove(self):
        """R90: nothing is removed before an archive of it exists and was read back and compared; the only removals are the
        open run folders after a fence and the marker at an unseat.
        Observable: with the archive write made to fail or the read-back made to differ, the run folder and the marker are
        still there and the step is open; no other file of the store or the role's state is ever removed."""

    @unbuilt(91)
    def test_R91_the_archive_of_open_runs(self):
        """R91: after S3 and before the note of S4 the broker archives the open run folders of the role whose epoch ended,
        walking only below the state_root of that epoch's assignment: one archive file for each run and manifest.json, owner
        only, verified by reading it back; it opens only regular files, with no-follow and non-blocking flags, and records
        every other entry by its path and type; a file it cannot read marks its run cut and kept, and the step goes on; the
        limits are 64 MiB of file content for each run and, for a transfer, 32 runs and 256 MiB, files stored whole in the
        byte order of their paths; an init archives nothing.
        Observable: after S4 the manifest names each of the first 32 open runs with its feature, whether it lies outside the
        state root, the count and size of its regular files and of those stored, the entries recorded by type only, the files
        it could not read, the digest of its archive file and cut, and counts the runs beyond the 32nd (left_out); the files
        are mode 600; a run of 64 MiB and one byte is marked cut and the files stored are the first of its paths in byte
        order; a transfer whose runs hold more than 256 MiB marks the run that finds no room cut with nothing stored; a
        named pipe in a run folder is recorded by type and the walk does not block on it, a symbolic link or a device node is
        recorded by type and never followed or opened; a file made unreadable marks its run cut, the folder stays and S4 and
        S5 complete; a run that the role's records place outside the state root is listed as outside and its folder is neither
        read nor changed."""

    @unbuilt(92)
    def test_R92_orphans_are_named_published_then_removed(self):
        """R92: the note lists every archived run as a lead-stated orphan with the digest of its archive file; S4 publishes the
        manifest and the archive files read only below the projection directory, where the successor reads them; a run folder
        is removed only when its archive holds it whole, is verified and published and the note that names it is written, as
        the first act of S5; a run that was cut stays, and so does a run that the transfer left out, of which the note carries
        the number.
        Observable: with a stop between archive, note, publication and removal the folder exists until all three are written;
        the published files have the digests the note names and no write bit; the note's orphans equal the manifest's runs;
        the folder of a cut run and of a left-out run is still there after S5; no run of the registry is absent from both the
        note and the role's state; no gate answer changes with a file below the published directory."""

    # ---- the coordinator's place

    @unbuilt(93)
    def test_R93_coordinator_values_are_reserved_and_refused(self):
        """R93: an assignment with seat_role coordinator or kind delegate or undelegate is refused, the gate raises no code in
        its reserved place, and the coordinator's row among the derived classes is reserved too.
        Observable: each of the three exits 1 with assignment-invalid and the store is unchanged."""

    @unbuilt(94)
    def test_R94_the_actor_label_is_attribution(self):
        """R94: the actor label is recorded on a run and never makes the gate pass a verb it refuses without the label.
        Observable: for every class and state the gate's answer with a label equals its answer without one; the label
        appears as actor on the run and in the note, and nowhere as a holder."""

    @unbuilt(95)
    def test_R95_a_coordinator_is_the_holder_to_the_gate(self):
        """R95: a helper inside the lead's session shares its assignment file and is answered as the holder.
        Observable: a verb run with the holder's records and a label gets the holder's answer, and the store holds no record
        of a delegation."""

    # ---- rules added in revision 2 of the contract (in the page each stands in the section of its subject)

    @unbuilt(96)
    def test_R96_the_spool_writing_verbs(self):
        """R96: marshal seat state --submit, marshal seat readback --submit and marshal caretaker request each write one spool
        envelope (state, readback, caretaker-request) and nothing else; they are lead-write verbs, and each passes in the state
        that asks for its envelope: accepted, pending-readback, held by a caretaker; each stamps its envelope with the project,
        epoch and tx of the projection, and S2 and S6 take an envelope of the open transfer only.
        Observable: in accepted A's state --submit passes while its other lead-write verbs exit 77 with transfer-in-progress,
        and in collected it exits 77 too; in pending-readback B's readback --submit passes while its other lead-write verbs
        exit 77 with readback-pending; after each passing call exactly one new file exists below the state root, its envelope
        has the projection's project, epoch and tx, and no record of the project, no run and nothing in the repository
        changed; an envelope left over from an earlier transfer is not taken by S2 or S6."""

    @unbuilt(97)
    def test_R97_no_unit_of_the_role_between_the_fence_and_S5(self):
        """R97: the supervising layer does not start B's unit before S5 is written; from the fence until then no unit of the
        role exists, and only then does the broker read or remove below the role's state root.
        Observable: the archive, the publication and the removal are complete before the seat write of S5; seat status
        names the start of B's unit as the next action only after S5; a session with B's assignment file before S5 gets
        exit 77 with projection-stale for a lead-write verb; after S5 no broker step opens a path below the role's state
        root."""

    @unbuilt(98)
    def test_R98_derived_classes(self):
        """R98: a derived class is answered as the lead is, less what its row takes away; the description of the commands
        carries one row (class, base rule, exceptions) for each: caretaker, with the exceptions env check, doctor, packs check
        and marshal caretaker request, and a reserved row for coordinator that nothing reads.
        Observable: the table has exactly these two rows; the verbs that pass for a caretaker in held (R63) are the
        exceptions of its row and no others; no assignment and no gate answer uses the coordinator's row."""

    @unbuilt(99)
    def test_R99_placeholders_are_the_supervising_layers(self):
        """R99: the supervising layer makes the placeholders of its read-only binds and records them in the clone's
        .git/info/exclude; qargi makes none, every qargi verb that writes that file is class owner, and the broker writes
        nothing below a clone.
        Observable: each verb of the commands description that writes the clone's .git/info/exclude exits 77 with
        not-assigned for the holder and changes nothing; after a whole transfer no file below the clone has changed, that
        file included."""

    @unbuilt(100)
    def test_R100_a_hidden_tracked_copy_is_an_intake_item(self):
        """R100: a tracked path that a read-only bind hides is listed in hidden_tracked of the assignment and carried
        unchanged by the note; a change to it is an intake item for the owner at the reviewed merge, which the text form of
        the note says for every listed path; no seat verb writes a listed path.
        Observable: hidden_tracked of the note equals the assignment's; the text form names each listed path as an intake
        item for the owner; after a whole transfer no listed path has changed in the clone or in the mirror."""

    # ---- rules added in revision 3 of the contract (in the page each stands in the section of its subject)

    @unbuilt(101)
    def test_R101_what_a_sandbox_never_holds(self):
        """R101: the supervising layer binds none of $AUTH, the broker's private key or a copy of it, an agent socket or other
        service that holds or signs with the key, or a credential with which an approved verb makes a remote act into the
        sandbox of a unit; qargi keeps every lead-side verb independent of all of it, reads the key on the authority side only
        and refuses a qargi host call that cannot read it.
        Observable: every lead-side verb gives the same output and exit status with $AUTH, the key, every agent socket and
        every remote credential absent as with them present, and opens no path below $AUTH; qargi host, called where none of
        them is readable, exits 1 with host-in-sandbox and the verb did not run. What the supervising layer binds is not
        observable by qargi: its own qualification of a sandbox shows it."""

    @unbuilt(102)
    def test_R102_a_sandbox_writes_the_two_declared_places_and_no_other(self):
        """R102: the places a unit's sandbox can write are the clone and the state root that its assignment declares, and the
        supervising layer sees to it that there is no other that the authority side reads or writes (every root and directory
        of the page, the qargi code and its tools, the temporary directory of authority-side code), the run folders of R91
        excepted while no unit of the role exists; authority-side code puts its scratch files below the directory that TMPDIR
        names.
        Observable: with TMPDIR set to a directory the test made, every scratch file of a broker step and of a qargi host call
        appears there and nowhere else (none below a clone, a state root, the projection directory or the shared temporary
        directory of the system); the door refuses every overlap with the declared places (R89). What a sandbox can write
        beyond them is not observable by qargi: the supervising layer's own qualification of a sandbox shows it."""


if __name__ == "__main__":
    unittest.main()
