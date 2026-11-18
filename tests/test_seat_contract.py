#!/usr/bin/env python3
"""The contract of the lead seat (docs/reference/lead-seat.md) and the skeleton of its tests.

The seat is not built. `Seat` holds one test per rule of the contract, named after the rule (test_R7_...), with a docstring that
states the rule and the observable the test will check, and skipped with the reason "seat not built: R7": the builder of a slice
removes the skip of the rules the slice satisfies and writes the body.

`Contract` runs today and keeps the two in step: the rules are numbered from 1 without a gap, each has exactly one test and every
test names a rule, each rule states its refusal, every reference to a rule or a point names one that exists, every point
marked OPEN is listed at the end with what is proposed and an alternative, every point that was decided is listed with the rule
that states the decision and is open nowhere, and the contract names no path outside the state and config roots (see ROOTS below
for the two exceptions that the contract itself declares).
Offline. Run: python3 tests/test_seat_contract.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, "docs", "reference", "lead-seat.md")
NOT_BUILT = "seat not built: R%d"

# A path the contract names starts at the state root or the config root.
ROOTS = ("$STATE", "$CONF")
# The design puts the authority store outside both roots on purpose. The contract may name it only while the open point that asks the
# lead where it lives is still listed; when that point is decided this entry moves into ROOTS or goes.
OPEN_ROOTS = {"$AUTH": "O1"}
# The two directories whose location the seat marker (below the config root) records: named by their field, not by a path.
RECORDED = ("<assignment_dir>", "<projection_dir>")
# The locations the assignment declares, named by their field too. A sandbox can write the first two, and the contract refuses every
# recorded path that overlaps them (R89): so the assignment has to name the state root of the role beside its clone.
DECLARED = ("<clone>", "<state_root>", "<mirror>")

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


def outside_the_roots(word):
    """Why a named path is outside the roots, or None when it is inside (or is no path: a schema id, a file of this repository)."""
    if SCHEMA_ID.match(word):
        return None
    if REPO_FILE.match(word):
        return None if os.path.exists(os.path.join(ROOT, word)) else "names a file this repository does not have"
    if word.startswith(tuple(r + "/" for r in ROOTS + tuple(OPEN_ROOTS) + RECORDED)):
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
        self.assertEqual(self.numbers, list(range(1, len(self.numbers) + 1)))
        said = re.search(r"\*\*R1\*\* to \*\*R(\d+)\*\*", self.text)      # the page says how far its rules go
        self.assertEqual(int(said.group(1)), self.numbers[-1], "the first section names the last rule")

    def test_every_rule_has_exactly_one_test_and_every_test_names_a_rule(self):
        tests = rule_tests()
        self.assertEqual(sorted(set(self.numbers) - set(tests)), [], "rules without a test")
        self.assertEqual(sorted(set(tests) - set(self.numbers)), [], "tests that name a rule the contract does not have")
        self.assertEqual({n: t for n, t in tests.items() if len(t) != 1}, {}, "rules with more than one test")
        stray = [n for n in dir(Seat) if n.startswith("test_") and not re.match(r"test_R\d+_\w+$", n)]
        self.assertEqual(stray, [], "a test of Seat is named after its rule: test_R7_...")

    def test_every_rule_test_is_skipped_for_its_rule_and_states_the_rule_and_the_observable(self):
        for n, names in sorted(rule_tests().items()):
            fn = getattr(Seat, names[0])
            with self.subTest(rule=n):
                doc = " ".join((fn.__doc__ or "").split())
                self.assertTrue(doc.startswith("R%d: " % n), "the docstring starts with the rule: R%d: ..." % n)
                self.assertIn(" Observable: ", doc)
                if getattr(fn, "__unittest_skip__", False):      # a built rule has no skip; an unbuilt one names its rule
                    self.assertEqual(fn.__unittest_skip_why__, NOT_BUILT % n)

    def test_every_rule_states_its_refusal(self):
        missing = [n for n, block in sorted(rule_blocks(self.text).items()) if "Refusal:" not in block]
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

    def test_the_contract_names_no_path_outside_the_state_and_config_roots(self):
        bad = {w: why for w in named_paths(self.text) for why in [outside_the_roots(w)] if why}
        self.assertEqual(bad, {}, "paths named outside the roots")
        # a root is one the contract may use: the two roots, and one more only while its open point is listed
        used = set(re.findall(r"\$[A-Z][A-Z_]*", self.text))
        self.assertEqual(sorted(used - set(ROOTS) - set(OPEN_ROOTS)), [], "roots the contract may not name")
        listed = open_items(self.text)
        for root, point in OPEN_ROOTS.items():
            if root in used:
                self.assertIn(point, listed, "%s is outside the state and config roots: allowed only while %s is open" % (root, point))
        for field in RECORDED:
            self.assertIn('"%s"' % field.strip("<>"), self.text, "the seat marker records %s" % field)
        for field in DECLARED:
            self.assertIn('"%s": "%s"' % (field.strip("<>"), field), self.text, "the assignment declares %s" % field)
        # no literal location: no absolute path, no home path
        self.assertEqual(re.findall(r"(?<![\w$<>./-])/[A-Za-z0-9_.][^\s`\"]*", self.text), [], "absolute paths")
        self.assertNotIn("~", self.text, "home paths")

    def test_the_path_reader_finds_what_it_must(self):
        # the check above is only as good as its reader: it must see a path in a code span, over a line break, and in a fenced block
        sample = "a `$STATE/x.json` b `/srv/a/b`, `$OTHER/y` and `marshal broker\nrun ../z/q` c\n```json\n{\"clone\": \"/srv/c\", \"s\": \"qargi.seat/1\"}\n```\n"
        self.assertEqual(named_paths(sample), ["$OTHER/y", "$STATE/x.json", "../z/q", "/srv/a/b", "/srv/c", "qargi.seat/1"])
        self.assertEqual([w for w in named_paths(sample) if outside_the_roots(w)], ["$OTHER/y", "../z/q", "/srv/a/b", "/srv/c"])
        self.assertIsNone(outside_the_roots("<projection_dir>/<project>/projection.json"))
        self.assertIsNone(outside_the_roots("tests/test_seat_contract.py"))
        self.assertIsNotNone(outside_the_roots("lib/no_such_module.py"))


def unbuilt(n):
    """The skip of a rule that is not built: the reason names the rule."""
    return unittest.skip(NOT_BUILT % n)


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
        """R7: the authority root is QARGI_AUTH, else the dev data root with -authority-dev, else the data root with -authority;
        with only QARGI_STATE or QARGI_CONF set there is no default; resolving creates nothing.
        Observable: the resolved path in each of the four cases; with QARGI_STATE alone a broker verb exits 1 with
        authority-store-unsafe; no directory exists after resolving."""

    @unbuilt(8)
    def test_R8_authority_root_is_apart(self):
        """R8: the authority root is never at or below the state root, the config root or the data root, is mode 700 and the
        caller's, and qargi export never includes it; a store that passes may be opened, which does not show that the caller is
        outside a sandbox (R33 proves that).
        Observable: a broker verb exits 1 with authority-store-unsafe for a root below either root, for mode 755 and for a
        file of mode 644 inside; nothing is read or written; an export archive holds no file of it."""

    @unbuilt(9)
    def test_R9_store_layout(self):
        """R9: the store of a project holds the seat, the history, the door copies by epoch and the files of each transfer; beside
        the projects the host audit, the broker key and the signers; the reserved names are not created.
        Observable: after a whole transfer the store holds exactly the named files, the tx name has its form, and no
        delegations directory or dormancy file exists."""

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
        the seat record.
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
        tx, epoch, detail, by} to the host audit, refused door calls too; a qargi host call whose proof fails records nothing.
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
        """R18: a record is a UTF-8 JSON object without floats, control characters or unknown fields; closed lists accept only
        their values; limits 8 KiB, 16 KiB, 64 KiB and 16 KiB.
        Observable: each violation at the door exits 1 with content-too-large, assignment-invalid or content-invalid as the
        rule says, and the store is unchanged."""

    @unbuilt(19)
    def test_R19_assignment_record(self):
        """R19: an assignment has the fields of qargi.assignment/1, among them the clone and the state root that the holder's
        sandbox can write; init and transfer need all, vacate and unseat carry no to, clone, state_root or hidden_tracked;
        role_name is kebab-case, at most 64, without a colon.
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
        written from, replaced by a rename inside its directory at every step.
        Observable: after each step the file has that shape, a new inode and the epoch, tx and rev of the seat record, no
        temporary file is left in the directory, and a projection of another shape makes a gated verb exit 77 with
        seat-record-invalid."""

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
        others exit 77 with not-assigned in a sandbox."""

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
        """R32: lead content reaches the authority side as a spool envelope {schema, project, epoch, kind, sha256, bytes}
        followed by the content, through broker intake.
        Observable: a valid envelope of each kind is stored; one over its limit exits 1 with content-too-large; a malformed
        one, a wrong digest or length and another epoch exit 1 with content-invalid; the store is unchanged."""

    @unbuilt(33)
    def test_R33_owner_verbs_go_through_host(self):
        """R33: before anything else qargi host proves that it is outside every sandbox: the authority root passes R8, a payload
        it signs with the broker's key verifies against the signers line of the projection, and the seat record agrees with the
        projection in epoch, tx and rev; then it appends its audit line and runs the verb. No variable, option or file stands
        for a proof that passed.
        Observable: with the true store the audit line exists before the verb's first effect; with a store the caller made
        (mode 700, named in QARGI_AUTH, its own key and a copied seat record) it exits 1 with host-in-sandbox, the verb did not
        run and no file changed; the same with the true key and a seat record whose rev is behind the projection; a verb that
        names no project runs when the proof passes for one seated project and is refused when there is none."""

    # ---- the handoff protocol

    @unbuilt(34)
    def test_R34_S1_accept(self):
        """R34: S1 needs a transfer assignment and a held seat, writes the copy, the seat (accepted, new tx) and the projection;
        from then A's lead-write verbs are refused.
        Observable: after S1 the seat and projection say accepted and A's lead-write verb exits 77 with
        transfer-in-progress while its read verb passes."""

    @unbuilt(35)
    def test_R35_S2_collect(self):
        """R35: S2 takes A's spool state, which may be empty, and writes the copy, the seat (collected) and the projection; it
        may be skipped.
        Observable: with and without a state the seat reaches collected; S3 from accepted is accepted too."""

    @unbuilt(36)
    def test_R36_S3_fence(self):
        """R36: S3 needs an accepted fence for the ending epoch and writes the fence copy, the seat (fenced, no holder) and the
        projection; no later step runs without it.
        Observable: with the fence the seat is fenced with holder null; without one, asking for S3 or a later step exits 1
        with fence-required and changes nothing."""

    @unbuilt(37)
    def test_R37_S4_note(self):
        """R37: after S3 the broker builds and signs the note and writes the note files, the seat and the projection.
        Observable: after S4 the three note files exist, the seat names the note's version and the projection carries the
        note with its digests."""

    @unbuilt(38)
    def test_R38_S5_commit(self):
        """R38: S5 writes the seat (pending-readback, B, the new epoch) and the projection; B reads but may not write.
        Observable: after S5 B's read verb passes and its lead-write verb exits 77 with readback-pending; the seat's epoch
        is the new one."""

    @unbuilt(39)
    def test_R39_S6_check(self):
        """R39: S6 checks B's read-back; on a match the seat is held and B is the lead; without one the seat stays
        pending-readback and B may read back again.
        Observable: a matching read-back gives held with readback matched and B's lead-write verb passes; a failing one exits
        1 with readback-mismatch, stores the result and leaves pending-readback; a second, matching one then succeeds."""

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
        """R48: a read-back is {project, transfer_id, note_sha256, epoch, believes} of schema qargi.readback/1, and seat
        readback --template prints the empty one.
        Observable: the template parses, has every field and is accepted when filled in; an unknown field exits 1 with
        content-invalid and one over 64 KiB with content-too-large."""

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
        host), and one gate in the preamble decides before the verb runs; an unseated project costs no extra process.
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
        """R56: when the assignment file and the projection differ in project, role_name, unit, runtime or clone, always-open
        passes and the other classes are refused.
        Observable: for each of the five fields, read, lead-write and owner verbs exit 77 with records-disagree."""

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
        """R60: in accepted, collected and fenced, always-open and read pass.
        Observable: in each of the three states a lead-write verb exits 77 with transfer-in-progress and an owner verb with
        not-assigned."""

    @unbuilt(61)
    def test_R61_condition_read_back_pending(self):
        """R61: in pending-readback, always-open and read pass.
        Observable: B's lead-write verb exits 77 with readback-pending and its owner verb with not-assigned."""

    @unbuilt(62)
    def test_R62_condition_vacant(self):
        """R62: in vacant only always-open passes.
        Observable: read and lead-write verbs exit 77 with seat-vacant, an owner verb with not-assigned."""

    @unbuilt(63)
    def test_R63_condition_held_by_a_caretaker(self):
        """R63: in held with a caretaker, always-open and read pass and of the lead-write verbs only env check, doctor, packs
        check and marshal caretaker request.
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
        passed the outside proof runs it.
        Observable: typed without qargi host, each verb that takes --approved exits 1 with approval-refused and leaves no file
        changed, with the true store present and with every variable of a qargi host call set by hand too; under qargi host
        with the true store it is accepted; under qargi host with a store the caller made the call exits 1 with
        host-in-sandbox."""

    @unbuilt(77)
    def test_R77_plan_tokens_do_not_cross(self):
        """R77: qargi host computes a plan token over the plan preceded by a line only it adds, so a lead's token never matches.
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
        """R84: the note lists uncommitted work and the hidden tracked files of the assignment as unverified lead-stated data,
        and a verb that writes below the config root or the clone's runtime configuration is class owner.
        Observable: hidden_tracked of the note equals the assignment's; each such verb exits 77 with not-assigned in a
        sandbox."""

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
        at the time of use.
        Observable: for each row of the table, a symbolic link put in place of the file and of each directory component
        after it was recorded makes the authority side exit 1 with symlink-refused and the gate exit 77 with
        seat-record-invalid, and the link's target is neither read nor written."""

    @unbuilt(89)
    def test_R89_nothing_a_sandbox_can_write_is_trusted_by_path(self):
        """R89: authority-side code uses no path with a component a sandbox can write; what a sandbox can write is the clone and
        the state root that the assignment declares; the assignment directory, the projection directory, the mirror and the
        authority and config roots are refused when equal to, below or containing either; who owns a path is not the test.
        Observable: an assignment whose mirror lies below its clone, equals its state root or contains its clone exits 1 with
        assignment-invalid; a marker whose directory lies below the declared state root makes authority-side verbs exit 1
        with authority-store-unsafe; a path outside both declared locations is accepted whoever owns its components."""

    @unbuilt(90)
    def test_R90_archive_before_remove(self):
        """R90: nothing is removed before an archive of it exists and was read back and compared; the only removals are the
        open run folders after a fence and the marker at an unseat.
        Observable: with the archive write made to fail or the read-back made to differ, the run folder and the marker are
        still there and the step is open; no other file of the store or the role's state is ever removed."""

    @unbuilt(91)
    def test_R91_the_archive_of_open_runs(self):
        """R91: after S3 and before S4 the broker archives every open run folder: one archive file per run and a manifest with
        name, feature, file count, size, digest and the cut mark, owner only, verified by reading it back.
        Observable: after S4 the manifest lists each open run with the digest of its archive file, the files are mode 600, a
        run over the limit is marked cut, and a symbolic link in a run folder is stored as a link."""

    @unbuilt(92)
    def test_R92_orphans_are_named_then_removed(self):
        """R92: the note lists every archived run as a lead-stated orphan, and a run folder is removed only after its archive
        is verified and the note that names it is written.
        Observable: with a stop between archive, note and removal the folder exists until both are written; the note's
        orphans equal the manifest's runs; no run of the registry is absent from both the note and the role's state."""

    # ---- the coordinator's place

    @unbuilt(93)
    def test_R93_coordinator_values_are_reserved_and_refused(self):
        """R93: an assignment with seat_role coordinator or kind delegate or undelegate is refused, and the gate raises no code
        in its reserved place.
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


if __name__ == "__main__":
    unittest.main()
