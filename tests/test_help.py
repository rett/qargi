#!/usr/bin/env python3
"""The command description (lib/commands.py) against the scripts, and the help, man page, completion and
project inference built from it. Offline. Run: python3 tests/test_help.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import glob, json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "lib")
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, LIB)
import commands as C  # noqa: E402
import help as H  # noqa: E402
import guard as G  # noqa: E402


def slurp(p):
    with open(p) as f:
        return f.read()


def verbs(cmd):
    v = C.COMMANDS[cmd].get("verbs")
    return v if isinstance(v, dict) else {}


def doc_flags(cmd):
    spec = C.COMMANDS[cmd]
    out = {o["flag"] for o in spec.get("opts", [])}
    for v in verbs(cmd).values():
        out |= {o["flag"] for o in v["opts"]}
    return out


# every kind of value the command data may name, and what completes it
TYPES = {"none": None, "project": 1, "instance": 1, "session": 1, "target": 1, "pack": 1, "team": 1, "role": 1, "workrole": 1, "methodology": 1, "member": 1, "store": 1, "deployment": 1,
         "model": 1, "branch": 1, "entry": 1, "key": 1, "value": 1, "seconds": 1, "cents": 1, "file": 1, "dir": 1, "help": 1}


class Sync(unittest.TestCase):
    def test_shared_help_introductions_describe_command_specific_requirements(self):
        guidance = "Request, plan and approval requirements are command-specific."
        self.assertIn(guidance, H.show_overview())
        introduction = H.man().split(".SH GLOBAL OPTIONS", 1)[0].replace("\\-", "-")
        self.assertIn(guidance, introduction)
        self.assertNotIn("A cloud verb needs", H.show_overview())
        self.assertNotIn("a cloud command needs", introduction)

    def test_standalone_verify_help_describes_observed_snapshot_scope(self):
        for arguments in (("help", "local", "verify"), ("local", "verify", "--help")):
            result = subprocess.run([BIN, *arguments], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = " ".join(result.stdout.split())
            for boundary in ("local refs", "available origin heads/tags", "excluding refs/qargi/",
                             "Transient activity", "other destinations"):
                self.assertIn(boundary, text)
            self.assertNotIn("Anything else (a push", text)

    def test_shared_policy_topics_and_exit_status_are_scoped(self):
        overview = H.show_overview()
        self.assertIn("Members are instructed", overview)
        self.assertIn("qargi help push", overview)
        self.assertIn("qargi help dev", overview)
        concepts = " ".join(C.TOPICS["concepts"][1])
        self.assertIn("scoped lead grant", concepts)
        self.assertNotIn("Nothing is pushed", concepts)
        self.assertNotIn("before anything is pushed", concepts)
        push = " ".join(C.TOPICS["push"][1])
        self.assertIn("selected runtime", push)
        self.assertIn("Long-lived branch", push)
        exit_status = H.man().split(".SH EXIT STATUS\n", 1)[1].split(".SH SEE ALSO", 1)[0]
        self.assertIn("command-specific", exit_status)

    def test_verify_help_describes_remote_observation_gaps(self):
        text = " ".join(C.COMMANDS["local"]["verbs"]["verify"]["desc"].split())
        self.assertIn("--repo-url observes only", text)
        self.assertIn("unavailable at both observations", text)
        self.assertIn("remote refs remain unobserved", text)

    def test_storage_and_guard_topics_disclose_runtime_scope(self):
        files = " ".join(C.TOPICS["files"][1])
        self.assertIn("dev mode", files)
        self.assertIn("repo-tier memory", files)
        self.assertNotIn("Nothing is stored in a repository", files)
        guard = " ".join(C.TOPICS["guard"][1])
        self.assertIn("adapter installs", guard)
        self.assertIn("qargi provider show", guard)
        self.assertIn("install.sh and lib/install_record.py (its engine) in any use", guard)
        dev = " ".join(C.TOPICS["dev"][1])
        self.assertIn("Hook-enabled runtimes", dev)

    def test_canonical_target_guidance_preserves_selection_and_explicit_checks(self):
        pack = " ".join(slurp(os.path.join(ROOT, "skills/qargi-packs/SKILL.md")).split())
        self.assertIn("match the selected runtime", pack)
        for name in ("skills/qargi-packs/apply.md", "docs/skills-tools-and-memory/local-session.md"):
            text = " ".join(slurp(os.path.join(ROOT, name)).split())
            self.assertIn("Explicit targets retain", text)
            self.assertNotIn("Explicit secondary targets retain", text)

    def test_campaign_metadata_help_and_completion(self):
        self.assertEqual(set(verbs("campaign")), {"commit", "show", "check", "log"})
        for spec in verbs("campaign").values():
            self.assertIn("--json", {o["flag"] for o in spec["opts"]})
        self.assertEqual(set(H.complete(["campaign", ""])), {"commit", "show", "check", "log"})
        self.assertEqual(H.complete(["campaign", "check", "--spec", ""]), ["@file"])
        for args in (["help", "campaign"], ["campaign", "--help"],
                     ["help", "campaign", "log"], ["campaign", "log", "--help"]):
            result = subprocess.run([BIN, *args], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("4096", result.stdout)
            self.assertNotIn("dev run", result.stderr)

    def test_every_dispatched_command_is_described_and_back(self):
        src = slurp(BIN)
        body = src[src.index("area=${1:-}"):]
        labels = set()
        for m in re.finditer(r"(?m)^  ([a-z_|-]+)\) ", body):
            labels |= set(m.group(1).split("|"))
        labels -= {"-h", "--help", "--version", "__complete", "__guard"}
        self.assertEqual(labels, set(C.COMMANDS), "bin/qargi and lib/commands.py disagree")

    def test_groups_cover_every_command_once(self):
        listed = [c for _, cs in C.GROUPS for c in cs]
        self.assertEqual(sorted(listed), sorted(C.COMMANDS))

    def test_documented_verbs_and_flags_exist_in_the_scripts(self):
        for cmd, spec in C.COMMANDS.items():
            src = "".join(slurp(os.path.join(LIB, s)) for s in spec.get("scripts", []))
            if not src:
                continue
            for v in verbs(cmd):
                self.assertRegex(src, r"\b%s\b" % re.escape(v), "%s %s is documented but not in %s" % (cmd, v, spec["scripts"]))
            for f in doc_flags(cmd):
                self.assertIn(f, src, "%s %s is documented but not in %s" % (cmd, f, spec["scripts"]))

    def test_every_flag_a_script_parses_is_documented(self):
        label = re.compile(r"(?m)^\s*(--[a-z][a-z-]*(?:\|--?[a-z][a-z-]*)*)\)")
        quoted = re.compile(r"\"(--[a-z][a-z-]+)\"")
        by_script = {}
        for cmd, spec in C.COMMANDS.items():
            for s in spec.get("scripts", []):
                by_script.setdefault(s, set()).update(doc_flags(cmd))
        ignore = {"--help"}
        # (script, flag) pairs that a script hands to another program and does not parse itself: doctor.py asks systemd-run `--version`, which is
        # an argument of systemd-run and no flag of `qargi doctor`; rolecard.py looks for the flag --plan in the command description to list the verbs that
        # take a plan on the lead's card, and parses none of it
        passed_on = {("doctor.py", "--version"), ("rolecard.py", "--plan")}
        for s, documented in by_script.items():
            src = slurp(os.path.join(LIB, s))
            found = set()
            for m in label.finditer(src):
                found |= set(m.group(1).split("|"))
            if s.endswith(".py"):
                found |= set(quoted.findall(src))
            missing = {f for f in found if f.startswith("--") and (s, f) not in passed_on} - documented - ignore
            self.assertFalse(missing, "%s parses %s, which lib/commands.py does not describe" % (s, sorted(missing)))

    def test_argument_types_are_known(self):
        known = set(TYPES)
        for cmd, spec in C.COMMANDS.items():
            arglists = [spec.get("usage", [])] + [v["args"] for v in verbs(cmd).values()]
            for al in arglists:
                for a in al:
                    self.assertTrue(isinstance(a[1], tuple) or H.kind(a[1]) in known, "%s: unknown argument type %r" % (cmd, a[1]))
            opts = list(spec.get("opts", [])) + [o for v in verbs(cmd).values() for o in v["opts"]]
            for o in opts:
                self.assertTrue(isinstance(o["type"], tuple) or H.kind(o["type"]) in known, "%s %s: unknown type" % (cmd, o["flag"]))


class Render(unittest.TestCase):
    def test_overview_names_everything(self):
        out = H.show_overview()
        self.assertIn(C.TAGLINE, out)
        for title, cmds in C.GROUPS:
            self.assertIn(title, out)
            for c in cmds:
                self.assertIn(c, out)
        for t in C.TOPICS:
            self.assertIn(t, out)
        self.assertNotIn("\033", out)

    def test_every_command_and_verb_renders_within_the_width(self):
        for cmd in C.COMMANDS:
            txt = H.show_command(cmd)
            self.assertTrue(txt and cmd in txt)
            for v in verbs(cmd):
                vt = H.show_command(cmd, v)
                self.assertTrue(vt and v in vt, "%s %s" % (cmd, v))
                for line in vt.splitlines():
                    self.assertLessEqual(len(line), 100, "%s %s: %r" % (cmd, v, line))
        for t in C.TOPICS:
            self.assertTrue(H.show_topic(t))

    def test_topics_name_only_commands_and_verbs_that_exist(self):
        for t, (_, paras) in C.TOPICS.items():
            for m in re.finditer(r"(?<![\w./~])qargi ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?", " ".join(paras)):
                cmd, verb = m.groups()
                if cmd == "ships":                      # prose: "the member definition qargi ships"
                    continue
                self.assertIn(cmd, C.COMMANDS, "topic %s names qargi %s" % (t, cmd))
                if verb and verbs(cmd) and verb not in verbs(cmd):
                    self.fail("topic %s names qargi %s %s, which is not a verb" % (t, cmd, verb))

    def test_no_help_topic_has_a_commands_name(self):
        """`qargi help NAME` shows the topic first when NAME is one, so a topic named like a command would hide that command's help."""
        self.assertEqual(sorted(set(C.TOPICS) & set(C.COMMANDS)), [])

    def test_the_guard_topic_is_listed_renders_and_is_in_the_man_page(self):
        self.assertIn("guard", C.TOPICS)
        title, paras = C.TOPICS["guard"]
        text = " ".join(paras)
        self.assertLessEqual(len(text.split()), 494)
        for needle in ("QARGI_NESTED", "plan token", "OUT", "local verify", "report", "push", "quotes", "heredoc", "substitution",
                       "Wrapper options", "except for the read-only class's writes, an unknown one is judged with and without the next word", "source -p DIR NAME",
                       "($(, ${ or a backtick; not a plain $NAME)", "The install record is install.json, install.d and install.lock.", "best-effort"):
            self.assertIn(needle, text)
        self.assertNotIn("install.manifest", text)
        self.assertIn("guard", H.show_overview())
        self.assertIn(title, H.show_topic("guard"))
        r = subprocess.run([BIN, "help", "guard"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=dict(os.environ, QARGI_HOME=tempfile.mkdtemp()))
        self.assertEqual(r.returncode, 0)
        self.assertIn("local verify", r.stdout)

    def test_doctor_and_handoff_help_say_what_the_install_check_warns_of_and_how_the_note_is_laid_out(self):
        doctor = " ".join(C.COMMANDS["doctor"]["desc"].split())
        for needle in ("install: the install records", "install.manifest or project-N.manifest from 0.3.1 or earlier", "no longer read", "removed by hand after checking install.d",
                       "on a record that lacks the tool (install.json without a tool_root, or runtimes recorded with no install.json) or its runtimes (install.json names the tool but no user runtime is in install.d)"):
            self.assertIn(needle, doctor)
        self.assertIn("the tools, the install records", C.COMMANDS["doctor"]["summary"])
        for needle in ("verify-environment: whether the project declares verify.environment, as 'off' or as 'on' with the version of systemd-run",
                       "a systemd-run that is missing or older than 254", "a declaration that differs from the one accepted for the project or is invalid",
                       "the file of accepted declarations (verify-env.json in the state directory) when it cannot be read"):
            self.assertIn(needle, doctor)
        self.assertIn("a lead model that cannot be determined (no transcript, no counted turn, no model id) is not a warning", doctor)
        for word in ("migrat", "moved into install.d"):
            self.assertNotIn(word, doctor)
        handoff = " ".join(C.COMMANDS["marshal"]["verbs"]["handoff"]["desc"].split())
        self.assertIn("The note starts with its where section, then an index of its features, lists live work first and lists a feature's own worktrees under it. "
                      "A note that fits the bound is printed whole, with every index line and no truncation line; "
                      "only a note over the bound has its index cut (3072 bytes of lines, then one line that counts the features without one) and ends with a line naming the features left out or cut short and saying how many have no index line.", handoff)
        self.assertIn("The features that have a branch and no marshal record are one note: how many, their first names, then the count of the rest.", handoff)
        self.assertIn("--json over the bound empties worktrees_unattributed and agent_unattributed as needed (each only while the output is still over the bound), then, one feature at a time from the last, trims its detail and drops it, and sets truncated; "
                      "when features are dropped it adds features_omitted (the count dropped) and features_left_out (their names, up to 3000 bytes), and features_left_out_more (the count of names not listed) when not all of them are.", handoff)
        self.assertIn("it cuts the lists from the end, the notes first, then deviations.accepted, gates, read_first.memory, read_first.repo_docs and read_first.successor, and lists_left_out says how many items each list lost.", handoff)
        self.assertIn("Output is capped at 16 KiB, the note and --json alike (the final newline counted). The text note is always within the bound; in --json the one part not bounded is what a successor needs whole and --json never cuts: do_not_assume, where, packs and environment (", handoff)
        for key in ("truncated", "features_omitted", "features_left_out", "features_left_out_more", "lists_left_out", "worktrees_unattributed", "agent_unattributed"):   # the keys of a cut note in --json (lib/marshal_handoff.py)
            self.assertIn(key, handoff)
        advise = [o for o in C.COMMANDS["lead"]["verbs"]["compact-check"]["opts"] if o["flag"] == "--advise"]
        self.assertIn("no advice on an assumed window (unknown model window and no lead.context_window)", str(advise))

    def test_lead_usage_session_help_says_where_the_transcript_is_looked_for_and_the_team_help_names_no_runtime(self):
        """lib/lead_usage.py: a named session id (--session, else the id in the lead's environment) is looked for among the transcripts of the
        current directory, the top of its work tree and the repository; only with no id at all is the newest transcript taken, and a set id
        with none reads as unknown. The help of `team` is for a lead of any runtime."""
        opts = [o for o in C.COMMANDS["lead"]["verbs"]["usage"]["opts"] if o["flag"] == "--session"]
        self.assertEqual(len(opts), 1)
        text = " ".join(opts[0]["help"].split())
        for needle in ("the current directory, the top of its work tree and the repository", "the session QARGI_LEAD names",
                       "only when QARGI_LEAD is unset or empty, the newest transcript", "a set id with none gives context: unknown"):
            self.assertIn(needle, text)
        self.assertNotIn("this directory", text)
        self.assertNotIn("Claude Code", C.COMMANDS["team"]["desc"])

    def test_the_guard_topic_and_the_read_only_card_say_what_a_read_only_member_runs_where_tmpdir_points_and_what_a_piece_after_a_cut_may_not_start_with(self):
        """What the guard refuses a read-only member, as the member needs to read it: the guard topic says it all (an assignment, not the command; the TMP that TMPDIR
        is; the words the guard reads after a separator) and the read-only card, which the task block carries in place of the review role's text, says what a reviewer
        acts on. The behaviour itself is tested in test_guard.py, the card against the guard in test_rolecard.py."""
        topic = " ".join(" ".join(C.TOPICS["guard"][1]).split())
        for needle in ("build, vet and test", "TMPDIR", "OUT and TMP", "git push", "git tag", "ssh", "scp", "sftp", "gh", "not mid-sentence"):
            self.assertIn(needle, topic, "the guard topic does not say %r" % needle)
        self.assertNotIn("is not set", topic)
        self.assertIn("is refused, not the command", topic)
        self.assertIn("the run's TMP", topic)
        card = subprocess.run([sys.executable, "-I", os.path.join(LIB, "rolecard.py"), "card", "review"], capture_output=True, text=True, check=True).stdout
        card = " ".join(card.split())
        for needle in ("TMPDIR is TMP, where Go tests write", "OUT and TMP", "PATH, HOME, TMPDIR, GIT_*, LD_*, BASH_*, PYTHONPATH, NODE_OPTIONS", "see `qargi help guard`",
                       "A target platform (GOOS, GOARCH)", "Do not run the whole suite",
                       "A line, even in a heredoc, a quoted string or a commit message, that starts with git push, ssh or gh is refused: write such text with your file tool."):
            self.assertIn(needle, card, "the read-only card does not say %r" % needle)
        role = " ".join(slurp(os.path.join(ROOT, "roles", "review", "ROLE.md")).split())
        self.assertNotIn("TMPDIR", role, "what the guard refuses of a read-only run is on the card, not in the role text")

    def test_review_check_help_and_the_review_role_state_the_report_only_rule(self):
        # what review_check.py requires of a report-only run: the manifest beside the report, a closing verdict line, SCOPE as a hard limit, a batch warning
        r = subprocess.run([BIN, "help", "review", "check"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=dict(os.environ, QARGI_HOME=tempfile.mkdtemp()))
        self.assertEqual(r.returncode, 0)
        text = " ".join(r.stdout.split())
        for needle in ("last non-empty line is `verdict: accept` or `verdict: revise`", "manifest.json", "outside SCOPE fails", "RUN/task.md", "warn"):
            self.assertIn(needle, text)
        self.assertNotIn("instead of patches", text)
        role = slurp(os.path.join(ROOT, "roles", "review", "ROLE.md"))
        self.assertIn("closing verdict line", role)
        self.assertNotIn("DONE checks that the report has a Findings section", role)

    def test_the_verify_skill_names_both_ways_a_read_only_report_reaches_the_lead(self):
        """A read-only run with no report in OUT either gave it in its final message (the lead stores it) or wrote it with local report."""
        skill = " ".join(slurp(os.path.join(ROOT, "skills", "qargi-verify", "SKILL.md")).split())
        self.assertIn("`qargi review save RUN_DIR` stores it", skill)
        self.assertIn("`qargi local report`", skill)
        self.assertIn("report", verbs("local"))

    # verbs the guard refuses that the topic need not name, each with the reason: none yet
    GUARD_TOPIC_EXEMPT = {}

    def test_the_guard_topic_names_every_verb_the_guard_refuses(self):
        text = " ".join(C.TOPICS["guard"][1])
        words = set(re.findall(r"[a-z][a-z-]*", text))
        refused = set(G.SKILL_VERBS) | set(G.PROJECT_VERBS) | set(G.MEMORY_VERBS) | {"claim", "set", "renew", "release", "take", "takeover", "finish", "enable", "disable"} | set(G.MARSHAL_SIGNING)
        src = slurp(os.path.join(LIB, "guard.py"))
        m = re.search(r"if \(area in \(\"skill\", \"tool\"\) and verb in SKILL_VERBS\) or \(area, verb\) in \((.*?)\)\s*\\", src, re.S)
        self.assertTrue(m, "the gated (area, verb) pairs of lib/guard.py moved: update this test")
        pairs = re.findall(r'\("([a-z]+)", "([a-z-]+)"\)', m.group(1))
        self.assertGreaterEqual(len(pairs), 6)
        refused |= {v for _, v in pairs}
        refused |= set(G.ENV_LEAD)                                         # env plan and apply
        refused |= {"publish", "login", "unset", "accept"}                # release publish, cloud set|unset|login, provider accept
        missing = sorted(v for v in refused if v not in words and v not in self.GUARD_TOPIC_EXEMPT)
        self.assertFalse(missing, "the guard topic does not name %s (add them to the topic, or to GUARD_TOPIC_EXEMPT with a reason)" % missing)
        for area in ("discover", "import", "upgrade", "release", "cloud", "local", "feature", "memory", "marshal", "provider"):
            self.assertIn(area, words, "the guard topic does not name the area %s" % area)
        for needle in ("QARGI_LEAD", "QARGI_NESTED", "journal", "plugin"):
            self.assertIn(needle, text)
        stale = sorted(v for v in self.GUARD_TOPIC_EXEMPT if v in words or v not in refused)
        self.assertFalse(stale, "stale exemptions: %s" % stale)

    def test_the_guard_topic_names_every_provider_verb_it_refuses_and_none_it_allows(self):
        """Each provider verb of commands.py is one of the guard's reading verbs (PROVIDER_READ) or is named in the topic's list of refused ones."""
        text = " ".join(C.TOPICS["guard"][1])
        m = re.search(r"provider ([a-z, -]+?) \(", text)
        self.assertTrue(m, "the guard topic has no 'provider new, ... and adapter-run (...)' list of refused verbs")
        named = set(re.findall(r"[a-z][a-z-]*", m.group(1))) - {"and"}
        verbs, read = set(C.COMMANDS["provider"]["verbs"]), set(G.PROVIDER_READ) - {""}
        missing = sorted(v for v in verbs if v not in read and v not in named)
        self.assertFalse(missing, "provider verbs the guard refuses and the topic does not name: %s" % missing)
        self.assertFalse(sorted(named & read), "the topic names as refused a verb the guard allows")
        self.assertFalse(sorted(named - verbs), "the topic names provider verbs that commands.py does not list")

    def test_the_man_page_holds_the_approvals_and_guard_topics_as_man_writes_them(self):
        page, shipped = H.man(), slurp(os.path.join(ROOT, "man", "qargi.1"))
        self.assertEqual(shipped, page)
        for t in ("approvals", "guard"):                 # the page says "See APPROVALS", and the guard is what the approvals topic points at
            self.assertIn("\n.SH %s\n" % t.upper(), shipped)
            for para in C.TOPICS[t][1]:
                self.assertIn(H.esc(para), shipped, "the %s topic is not in man/qargi.1 as man() writes it" % t)

    def test_project_set_help_names_every_answer_the_guard_refuses_a_member_and_import_help_every_gated_key(self):
        """The help of project set lists the answers a member's guard refuses (EXECUTED_ANSWERS, git and review, runs and packs have their own sentences), and the help of
        import names each key of GATED_KEYS in lib/transfer.py that an archive may not add or change."""
        text = C.COMMANDS["project"]["verbs"]["set"]["desc"]
        for a in G.EXECUTED_ANSWERS + G.IDENTITY_ANSWERS:
            self.assertRegex(text, r"(?<![a-z_.])%s(\.\*|,| and |\.)" % re.escape(a), "project set help does not name %s among what a member's guard refuses" % a)
        src = slurp(os.path.join(LIB, "transfer.py"))
        m = re.search(r"^GATED_KEYS = (.*?)^PROVIDER_KEYS", src, re.S | re.M)
        self.assertTrue(m, "GATED_KEYS of lib/transfer.py moved: update this test")
        keys = re.findall(r'"([a-z_.]+)"', re.sub(r"#[^\n]*", "", m.group(1)))
        self.assertGreaterEqual(len(keys), 7)
        imp = C.COMMANDS["import"]["desc"]
        for k in keys:
            self.assertIn(k, imp, "import help does not name the gated key %s" % k)

    def test_the_release_answers_are_listed_by_the_key_completion_and_the_error_text_of_the_release_check(self):
        """Every layout key of a release (lib/release_layout.py) can be typed as a project key (changelog by its three sub-keys), and the text of the release answers
        check names every key it accepts: it is built from RELEASE_KEYS, not copied."""
        import release_layout as RL, release_sign as RS
        for k in RL.LAYOUT_KEYS:
            want = ["release.changelog." + c for c in RL.CHANGELOG_KEYS] if k == "changelog" else ["release." + k]
            for w in want:
                self.assertIn(w, H.EXTRA_KEYS, "%s is not among the keys the completion offers" % w)
        for k in ("finish_check", "hotfix_preflight"):
            self.assertIn("release." + k, H.EXTRA_KEYS)
        msg = RS.problems("not an object")[0]
        for k in RS.RELEASE_KEYS:
            self.assertRegex(msg, r"[{ ]%s[,}]" % k, "the check's error text does not name release.%s" % k)
        self.assertIn("release.hotfix_preflight", slurp(os.path.join(LIB, "release_sign.py")).split('"""')[1], "the header of lib/release_sign.py does not list the layout answers")
        self.assertIn("release.finish_check", slurp(os.path.join(LIB, "release_sign.py")).split('"""')[1])

    def test_the_registry_comment_of_lib_sh_lists_the_review_answers_the_registry_copy_keeps(self):
        """lib/local.sh copies owns([...]) of the review answers into the registry line; the comment in lib/lib.sh names each of them."""
        m = re.search(r'review: \(at\(\.review\) \| owns\(\[([^\]]*)\]\)', slurp(os.path.join(LIB, "local.sh")))
        self.assertTrue(m, "the review answers kept in the registry line moved in lib/local.sh: update this test")
        kept = re.findall(r'"([a-z_]+)"', m.group(1))
        self.assertGreaterEqual(len(kept), 4)
        comment = " ".join(l for l in slurp(os.path.join(LIB, "lib.sh")).splitlines() if l.startswith("#"))
        for k in kept:
            self.assertIn("review." + k, comment, "the comment in lib/lib.sh does not name review.%s" % k)

    def test_the_approvals_topic_states_the_rules_the_skills_point_at(self):
        text = " ".join(C.TOPICS["approvals"][1])
        for needle in ("covers the plan", "recorded, not verified", "Never allow-list", "A member never applies"):
            self.assertIn(needle, text)

    def test_cli_help_forms(self):
        home = tempfile.mkdtemp()                       # never the real home: some commands look at it
        self.addCleanup(shutil.rmtree, home, True)
        def run(*a, env=None):
            return subprocess.run([BIN, *a], capture_output=True, text=True, env=dict(os.environ, QARGI_HOME=home, **(env or {})), stdin=subprocess.DEVNULL)
        self.assertEqual(run("help").returncode, 0)
        r = run("lead", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("grant", r.stdout)
        r = run("canon", "apply", "-h")
        self.assertIn("--plan", r.stdout)
        r = run("help", "approvals")
        self.assertIn("plan token", r.stdout)
        r = run("help", "nosuch")
        self.assertEqual(r.returncode, 2)
        r = run("nosuch")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown command", r.stderr)
        want = slurp(os.path.join(ROOT, "VERSION")).strip() + "\nsource: " + os.path.realpath(ROOT) + "\n"
        for form in ("version", "--version"):
            r = run(form)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, want, ""), form)
        self.assertIn("--version", C.COMMANDS["version"]["desc"])
        self.assertIn("source:", C.COMMANDS["version"]["desc"])

    def test_the_declared_gates_in_the_output_of_the_verbs_are_described(self):
        # declared gates appear in the handoff note (== gates, and gates in --json), on standard error of project show and in project attach: the help says so
        for cmd, verb, needles in (("marshal", "handoff", ("== gates", "`gates`")), ("project", "show", ("standard error", "gates")),
                                   ("project", "attach", ("declare gates", "replace the detected test command")), ("project", "new", ("gates=JSON", "stored"))):
            v = C.COMMANDS[cmd]["verbs"][verb]
            text = v["summary"] + " " + v["desc"] + " " + " ".join(o["help"] for o in v["opts"])
            for n in needles:
                self.assertIn(n, text, "%s %s" % (cmd, verb))

    def test_the_provider_notes_help_names_the_refusal_of_the_start_notes_and_the_help_of_a_lead_names_no_runtime(self):
        # a lead on another runtime than an in-session project's is refused spawn and member-out with exit 3, and the list leaves them out
        v = C.COMMANDS["provider"]["verbs"]["notes"]
        text = " ".join(v["desc"].split())
        for needle in ("spawn, member-out", "dispatch mode in-session", "unsupported, exit 3", "cannot be started from this lead", "the list of topics leaves the two out"):
            self.assertIn(needle, text)
        # the help of the lead and of the hooks says what a session's identity is without naming the runtime it was first built for
        marshal = " ".join(C.COMMANDS["marshal"]["desc"].split())
        self.assertIn("A lead is a session with an identity", marshal)
        self.assertNotIn("session id", marshal)
        self.assertNotIn("Claude Code", marshal)
        self.assertNotIn("Claude Code", C.COMMANDS["hook"]["summary"])
        self.assertNotIn("subagent_type", C.COMMANDS["agent"]["verbs"]["for"]["desc"])
        self.assertNotIn("Agent tool", C.COMMANDS["agent"]["verbs"]["for"]["desc"])

    def test_man_page_is_current_and_lints(self):
        page = H.man()
        self.assertEqual(slurp(os.path.join(ROOT, "man", "qargi.1")), page, "regenerate: python3 lib/help.py man > man/qargi.1")
        self.assertIn(".SH COMMANDS", page)
        for c in C.COMMANDS:
            self.assertIn("qargi %s" % c.replace("-", "\\-"), page)
        if shutil.which("groff"):
            r = subprocess.run(["groff", "-k", "-ww", "-man", "-Tutf8"], input=page, capture_output=True, text=True)
            self.assertEqual(r.stderr, "", "groff warnings")

    def test_man_page_is_written_by_a_copy_without_skills(self):
        # a copy of lib alone (a partial or packaged one) writes the whole page; SEE ALSO names the skills generically
        t = tempfile.mkdtemp()
        try:
            shutil.copytree(os.path.join(ROOT, "lib"), os.path.join(t, "lib"), ignore=shutil.ignore_patterns("__pycache__"))
            r = subprocess.run([sys.executable, os.path.join(t, "lib", "help.py"), "man"], capture_output=True, text=True, cwd=t, stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith(".TH QARGI 1 "), r.stdout[:80])
            self.assertIn("The qargi skills, loaded by the lead's session", r.stdout)
        finally:
            shutil.rmtree(t)


class Env(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.t, "c", "projects"))
        os.makedirs(os.path.join(self.t, "s"))
        self.repo = os.path.join(self.t, "repo")
        os.makedirs(os.path.join(self.repo, "sub"))
        def put(path, obj):
            with open(path, "w") as f:
                json.dump(obj, f)
        for n, path in (("alpha", self.repo), ("beta", os.path.join(self.t, "elsewhere"))):
            put(os.path.join(self.t, "c", "projects", n + ".json"), {"project": n, "repo": {"path": path}, "teams": {"code-docs": {}} if n == "alpha" else {}})
        put(os.path.join(self.t, "c", "instances.json"), {"alpha-build": {}, "alpha-write": {}})
        put(os.path.join(self.t, "s", "sessions.json"), {"sesn_1": {}})
        self.put = put
        self.old = {k: os.environ.get(k) for k in ("QARGI_CONF", "QARGI_STATE", "QARGI_PROJECT")}
        os.environ["QARGI_CONF"], os.environ["QARGI_STATE"] = os.path.join(self.t, "c"), os.path.join(self.t, "s")
        os.environ.pop("QARGI_PROJECT", None)
        self.cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self.cwd)
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.t, ignore_errors=True)


class Complete(Env):
    def test_commands_verbs_and_values(self):
        self.assertIn("lead", H.complete([""]))
        self.assertEqual(H.complete(["lead", ""]), ["usage", "compact-check", "grant", "status", "revoke"])
        self.assertEqual(H.complete(["lead", "grant", ""]), ["alpha"])   # only projects that define teams
        self.assertEqual(H.complete(["team", "brief", "alpha", ""]), ["code-docs"])
        self.assertEqual(H.complete(["instances", "show", ""]), ["alpha-build", "alpha-write"])
        self.assertEqual(H.complete(["close", ""]), ["sesn_1"])
        self.assertEqual(H.complete(["canon", "apply", "--kind", ""]), ["memory", "reference"])
        self.assertEqual(H.complete(["skill", "link", "x", "--scope", ""]), ["user", "user-role", "project", "project-role"])
        self.assertEqual(H.complete(["agent", "for", "build", "--surface", ""]), ["local", "cloud"])
        self.assertIn("--plan", H.complete(["canon", "apply", "alpha", "-"]))
        self.assertEqual(H.complete(["review", "check", ""]), ["@dir"])
        self.assertEqual(H.complete(["project", "init", "x", "--answers", ""]), ["@file"])
        self.assertIn("lead", H.complete(["help", ""]))
        self.assertEqual(H.complete(["nosuch", ""]), [])

    def test_bash_function(self):
        script = os.path.join(ROOT, "completions", "qargi.bash")
        env = dict(os.environ, PATH=os.path.join(ROOT, "bin") + os.pathsep + os.environ["PATH"])
        r = subprocess.run(["bash", "-c", 'source "%s"; COMP_WORDS=(qargi lead gr); COMP_CWORD=2; _qargi; echo "${COMPREPLY[*]}"' % script],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.stdout.strip(), "grant", r.stderr)
        r = subprocess.run(["bash", "-c", 'source "%s"; COMP_WORDS=(qargi instances show ""); COMP_CWORD=3; _qargi; echo "${COMPREPLY[*]}"' % script],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.stdout.split(), ["alpha-build", "alpha-write"], r.stderr)


class Shells(Env):
    def run_shell(self, argv, script):
        env = dict(os.environ, PATH=os.path.join(ROOT, "bin") + os.pathsep + os.environ["PATH"])
        return subprocess.run(argv + [script], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)

    def test_described_output(self):
        out = H.complete_described(["lead", ""])
        self.assertEqual([c for c, _ in out], ["usage", "compact-check", "grant", "status", "revoke"])
        self.assertTrue(all(d for _, d in out))
        r = subprocess.run([BIN, "__complete", "--described", "lead", ""], capture_output=True, text=True)
        self.assertIn("grant\tGuided", r.stdout)

    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed")
    def test_zsh(self):
        script = os.path.join(ROOT, "completions", "_qargi")
        stub = ('_describe() { shift 3; print -l -- "${(@P)1}"; }; _files() { print "FILES $*"; }; f() { source %s }; ' % script)
        r = self.run_shell(["zsh", "-f", "-c"], stub + 'words=(qargi lead ""); CURRENT=3; f')
        self.assertEqual([l.split(":")[0] for l in r.stdout.split("\n") if l], ["grant", "status", "revoke"], r.stderr)
        r = self.run_shell(["zsh", "-f", "-c"], stub + 'words=(qargi instances show ""); CURRENT=4; f')
        self.assertEqual([l.split(":")[0] for l in r.stdout.split("\n") if l], ["alpha-build", "alpha-write"], r.stderr)
        r = self.run_shell(["zsh", "-f", "-c"], stub + 'words=(qargi review check ""); CURRENT=4; f')
        self.assertEqual(r.stdout.strip(), "FILES -/")
        r = self.run_shell(["zsh", "-n"], script)
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless(shutil.which("fish"), "fish is not installed")
    def test_fish(self):
        script = os.path.join(ROOT, "completions", "qargi.fish")
        r = self.run_shell(["fish", "-c"], 'source %s; complete -C "qargi lead "' % script)
        self.assertEqual(sorted(l.split("\t")[0] for l in r.stdout.split("\n") if l), ["grant", "revoke", "status"], r.stderr)
        r = self.run_shell(["fish", "-c"], 'source %s; complete -C "qargi team brief alpha "' % script)
        self.assertEqual(r.stdout.strip(), "code-docs", r.stderr)
        r = self.run_shell(["fish", "-n"], script)
        self.assertEqual(r.returncode, 0, r.stderr)


class Rich(Env):
    """Values from the user's own state, narrowed by what the verb can act on, with a description each."""
    def setUp(self):
        super().setUp()
        res = [{"memory_store_id": "memstore_A", "access": "read_write"}, {"memory_store_id": "memstore_B", "access": "read_only"}]
        agent = {"version_pinned": 3, "model": "claude-sonnet-5-5", "effort": "high"}
        self.put(os.path.join(self.t, "c", "instances.json"), {
            "alpha-build": {"location": "cloud", "agent": agent, "deployment_id": "depl_1", "resources": res},
            "alpha-write": {"location": "cloud", "agent": dict(agent, model="claude-opus-5-5"), "deployment_id": "depl_2", "resources": res},
            "alpha-local": {"location": "local"}})
        self.put(os.path.join(self.t, "s", "sessions.json"), {
            "sesn_run": {"instance": "alpha-build", "status": "running", "label": "job", "list_cost": "9", "outputs_collected": False},
            "sesn_idle": {"instance": "alpha-build", "status": "idle", "outputs_collected": True},
            "sesn_old": {"instance": "alpha-build", "status": "archived", "closed_at": "2026-01-01T00:00:00Z", "outputs_collected": True}})
        self.put(os.path.join(self.t, "c", "projects", "alpha.json"), {
            "project": "alpha", "repo": {"path": self.repo, "url": "https://example.net/alpha"}, "budget_cents": 1500,
            "teams": {"code-docs": {"members": ["build", "write"]}}, "lead": {"push": {"local": True, "cloud": "none"}},
            "roles": {"build": {"model": "claude-sonnet-5-5", "effort": "high"}, "write": {"model": "claude-opus-5-5", "effort": "medium"}}})
        os.makedirs(os.path.join(self.t, "c", "packs", "skills", "pdf"))
        os.makedirs(os.path.join(self.t, "c", "packs", "tools"))
        self.put(os.path.join(self.t, "c", "packs", "tools", "github.json"), {})
        self.put(os.path.join(self.t, "c", "agents.json"), {"schema": 2, "projects": {"alpha": {"forge": {"roles": ["build", "test"], "seq": 1}, "scribe": {"roles": ["write"], "seq": 2}},
                                                                              "beta": {"forge": {"roles": ["test"], "seq": 3}, "lone": {"roles": ["write"], "seq": 4}}}})

    def test_members_complete_with_their_abilities(self):
        self.assertEqual(H.complete(["agent", "remove", ""]), ["forge", "lone", "scribe"])   # every project's members, a name once
        self.assertEqual(H.complete(["agent", "remove", "--project", "alpha", ""]), ["forge", "scribe"])
        self.assertEqual(dict(H.complete_described(["agent", "rename", "--project", "alpha", ""]))["forge"], "build,test")
        self.assertEqual(dict(H.complete_described(["agent", "rename", "--project", "beta", ""]))["forge"], "test")
        self.assertEqual(H.complete(["agent", "for", ""]), list(C.ABILITIES))

    def test_sessions_are_narrowed_by_what_the_verb_does(self):
        self.assertEqual(H.complete(["stop", ""]), ["sesn_run"])
        self.assertEqual(H.complete(["collect", ""]), ["sesn_run"])
        self.assertEqual(H.complete(["close", ""]), ["sesn_idle", "sesn_run"])
        self.assertEqual(H.complete(["watch", ""]), ["sesn_idle", "sesn_run"])
        self.assertEqual(H.complete(["send", "alpha-build", "x", "--session", ""]), ["sesn_idle"])
        self.assertEqual(H.complete(["status", ""]), ["sesn_idle", "sesn_old", "sesn_run", "alpha-build", "alpha-write"])   # sessions and cloud instances
        self.assertEqual(dict(H.complete_described(["stop", ""]))["sesn_run"], "alpha-build running job $0.09")

    def test_cloud_verbs_do_not_offer_a_local_instance(self):
        self.assertEqual(H.complete(["start", ""]), ["alpha-build", "alpha-write"])
        self.assertEqual(H.complete(["instances", "show", ""]), ["alpha-build", "alpha-local", "alpha-write"])
        self.assertEqual(dict(H.complete_described(["start", ""]))["alpha-build"], "cloud agent v3 claude-sonnet-5-5/high")

    def test_stores_deployments_models_and_numbers(self):
        self.assertEqual(dict(H.complete_described(["memory", "lint", ""])), {"memstore_A": "alpha, memory", "memstore_B": "alpha, reference"})
        self.assertEqual(H.complete(["memory", "get", "memstore_A", ""]), [])   # a note path needs the store itself
        self.assertEqual(H.complete(["instances", "init", "--deployment", ""]), ["depl_1", "depl_2"])
        self.assertEqual(H.complete(["provision", "plan", "--memory-store", ""]), ["memstore_A", "memstore_B"])
        self.assertIn("claude-opus-5-5", H.complete(["instances", "init", "--model", ""]))
        self.assertEqual(H.complete(["instances", "budget", "alpha-build", ""])[:2], ["500", "1000"])
        self.assertIn("3600", H.complete(["watch", "sesn_run", ""]))

    def test_branches_come_from_the_projects_repository(self):
        def git(*a):
            subprocess.run(["git", "-C", self.repo] + list(a), check=True, capture_output=True,
                           env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.net", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.net"))
        git("init", "-q", "-b", "develop"); git("commit", "-q", "--allow-empty", "-m", "x"); git("branch", "feature/one")
        self.assertEqual(sorted(H.complete(["team", "brief", "alpha", "code-docs", "--base", ""])), ["develop", "feature/one"])
        os.chdir(self.repo)
        self.assertEqual(sorted(H.complete(["local", "prepare", "--base", ""])), ["develop", "feature/one"])

    def test_project_answers_and_their_values(self):
        keys = H.complete(["project", "set", "alpha", ""])
        for k in ("budget_cents", "lead.push.local", "roles.build.effort", "roles.write.model", "teams.code-docs.members", "lead.push.merge",
                  "release.version_file", "release.changelog.unreleased", "release.changelog.released", "release.man_pages", "release.test_command", "release.preflight",
                  "ci.not_gates", "methodology_accepted", "review.reject_trailers", "backlog.file", "backlog.archive", "backlog.section", "verify.environment"):
            self.assertIn(k, keys)
        self.assertEqual(dict(H.complete_described(["project", "set", "alpha", ""]))["budget_cents"], "now 1500")
        self.assertEqual(H.complete(["project", "set", "alpha", "roles.build.effort", ""]), list(C.EFFORTS))
        self.assertEqual(H.complete(["project", "set", "alpha", "lead.push.cloud", ""]), ["none", "branches"])
        self.assertEqual(H.complete(["project", "set", "alpha", "lead.push.local", ""]), ["true", "false"])
        self.assertEqual(H.complete(["project", "set", "alpha", "budget_cents", ""]), [])
        os.chdir(os.path.join(self.repo, "sub"))   # the project implied by the directory also gives the keys
        self.assertIn("budget_cents", H.complete(["project", "set", "alpha", ""]))

    def test_packs_follow_the_command(self):
        self.assertEqual(H.complete(["skill", "show", ""]), ["pdf"])
        self.assertEqual(H.complete(["tool", "show", ""]), ["github"])

    def test_roles_follow_the_project_and_teams_get_their_members(self):
        self.assertEqual(H.complete(["packs", "render", "alpha", ""]), ["build", "write", "lead"])
        self.assertEqual(dict(H.complete_described(["packs", "render", "alpha", ""]))["write"], "claude-opus-5-5/medium")
        self.assertEqual(dict(H.complete_described(["team", "brief", "alpha", ""]))["code-docs"], "build, write")

    def test_option_equals_value_and_options_are_offered_once(self):
        self.assertEqual(H.complete(["instances", "init", "--effort="]), ["--effort=" + e for e in C.EFFORTS])
        self.assertEqual(H.complete(["canon", "apply", "alpha", "--kind=", ]), ["--kind=memory", "--kind=reference"])
        # an inline value counts as given: no option twice, the positional is still the next one
        out = H.complete(["canon", "apply", "--kind=memory", "alpha", "-"])
        self.assertNotIn("--kind", out)
        self.assertIn("--plan", out)
        self.assertIn("--help", out)
        self.assertEqual(H.complete(["start", "--label=x", ""]), ["alpha-build", "alpha-write"])

    def test_help_completes_the_verbs_of_a_command(self):
        self.assertIn("refresh-prompt", H.complete(["help", "instances", ""]))
        self.assertEqual(H.complete(["help", "start", ""]), [])
        self.assertEqual(H.complete(["help", "instances", "show", ""]), [])

    def test_bash_puts_option_equals_value_back_together(self):
        script = os.path.join(ROOT, "completions", "qargi.bash")
        env = dict(os.environ, PATH=os.path.join(ROOT, "bin") + os.pathsep + os.environ["PATH"])
        for words, cword, want in (("instances init --effort = hi", 5, "high"), ("instances init --effort =", 4, "low medium high xhigh max")):
            r = subprocess.run(["bash", "-c", 'source "%s"; COMP_WORDS=(qargi %s); COMP_CWORD=%d; _qargi; echo "${COMPREPLY[*]}"' % (script, words, cword)],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.stdout.strip(), want, r.stderr)

    def test_every_kind_of_value_has_a_completer(self):
        """A new type in the command data must come with candidates, so completion keeps up with the command data."""
        seen = set()
        for cmd, spec in C.COMMANDS.items():
            vs = spec.get("verbs") or {}
            lists = [(spec.get("usage", []), spec.get("opts", []))] + [(v["args"], v["opts"]) for v in vs.values()]
            for args, opts in lists:
                seen |= {H.kind(a[1]) for a in args if isinstance(a[1], str)} | {H.kind(o["type"]) for o in opts if isinstance(o["type"], str)}
        self.assertEqual(seen, set(TYPES), "the types in the command data and the list in this test")
        ctx = ["alpha", "build", "project"]
        for t in sorted(seen - {"none", "value", "branch"}):   # a branch needs a repository (its own test); a value needs a key
            self.assertTrue(H.by_type(t, ctx), "no candidates for the type %r" % t)
        self.assertTrue(H.by_type("value", ["alpha", "lead.push.cloud"]))


class Infer(Env):
    def test_deep_registry_is_skipped_inference_and_public_preamble(self):
        os.chdir(self.repo)
        target = os.path.join(self.t, "c", "projects", "deep.json")
        with open(target, "w") as stream:
            stream.write("[" * 100000)
        self.assertEqual(H.infer_project(), "alpha")
        result = subprocess.run([BIN, "project", "show"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("alpha", result.stdout)

    def test_removed_cwd_inference_preserves_environment_precedence(self):
        gone = os.path.join(self.t, "removed")
        os.mkdir(gone)
        os.chdir(gone)
        os.rmdir(gone)
        self.assertIsNone(H.infer_project())
        self.assertEqual(H.resolve(["lead", "status", "beta"]), ["lead", "status", "beta"])
        os.environ["QARGI_PROJECT"] = "alpha"
        self.assertEqual(H.infer_project(), "alpha")

    def test_malformed_registry_shapes_and_path_types_are_skipped(self):
        os.chdir(os.path.join(self.repo, "sub"))
        target = os.path.join(self.t, "c", "projects", "broken.json")
        for record in ([], None, "x", {"repo": "x"}, {"repo": []},
                       {"repo": {"path": [self.repo]}}, {"repo": {"path": 1}},
                       {"repo": {"path": "nul\0path"}}):
            with self.subTest(record=record):
                self.put(target, record)
                self.assertEqual(H.infer_project(), "alpha")
                self.assertEqual(H.resolve(["lead", "status", "beta"]), ["lead", "status", "beta"])
        self.put(os.path.join(self.t, "c", "projects", "nested.json"),
                 {"repo": {"path": os.path.join(self.repo, "sub")}})
        self.assertEqual(H.infer_project(), "nested")
        os.environ["QARGI_PROJECT"] = "beta"
        self.assertEqual(H.infer_project(), "beta")

    def test_literal_leading_tilde_repository_inference(self):
        previous = os.environ.get("HOME")
        self.addCleanup(lambda: os.environ.__setitem__("HOME", previous) if previous is not None
                        else os.environ.pop("HOME", None))
        for home, spelling, expected in ((self.t + "/home", "~repo", "tilde"),
                                        (self.t + "/home/", "~repo", "tilde"),
                                        ("", "~.", "tilde"), ("", "~", None)):
            with self.subTest(home=home):
                os.chdir(self.t)
                os.environ["HOME"] = home
                path = home + spelling[1:]
                if not os.path.isabs(path):
                    path = os.path.join(self.t, path)
                os.makedirs(path, exist_ok=True)
                self.put(os.path.join(self.t, "c", "projects", "tilde.json"), {"repo": {"path": spelling}})
                os.chdir(path)
                self.assertEqual(H.infer_project(), expected)

    def test_project_is_implied_inside_its_repository(self):
        os.chdir(os.path.join(self.repo, "sub"))
        self.assertEqual(H.infer_project(), "alpha")
        self.assertEqual(H.resolve(["lead", "status"]), ["lead", "status", "alpha"])
        self.assertEqual(H.resolve(["lead", "status", "beta"]), ["lead", "status", "beta"])     # an explicit project wins
        self.assertEqual(H.resolve(["team", "brief", "code-docs", "--task", "x"]), ["team", "brief", "alpha", "code-docs", "--task", "x"])
        self.assertEqual(H.resolve(["team", "brief", "alpha", "code-docs"]), ["team", "brief", "alpha", "code-docs"])
        self.assertEqual(H.resolve(["credential", "setup", "lead-push", "--from-file", "f"]), ["credential", "setup", "lead-push", "alpha", "--from-file", "f"])
        self.assertEqual(H.resolve(["canon", "apply", "--kind", "memory"]), ["canon", "apply", "alpha", "--kind", "memory"])
        self.assertEqual(H.resolve(["project", "set", "budget_cents", "600"]), ["project", "set", "alpha", "budget_cents", "600"])
        self.assertEqual(H.resolve(["skill", "check", "write"]), ["skill", "check", "alpha", "write"])

    def test_a_role_stands_for_the_instance(self):
        os.chdir(self.repo)
        self.assertEqual(H.resolve(["instances", "show", "build"]), ["instances", "show", "alpha-build"])
        self.assertEqual(H.resolve(["instances", "show", "alpha-write"]), ["instances", "show", "alpha-write"])
        self.assertEqual(H.resolve(["provision", "plan", "write"]), ["provision", "plan", "alpha-write"])
        self.assertEqual(H.resolve(["provision", "plan"]), ["provision", "plan", "--project", "alpha"])
        self.assertEqual(H.resolve(["send", "build", "the task text", "--label", "x"]), ["send", "alpha-build", "the task text", "--label", "x"])

    def test_free_text_and_unrelated_commands_are_left_alone(self):
        os.chdir(self.repo)
        for argv in (["send", "alpha-build", "build lead status", "--label", "x"], ["collect", "sesn_1", "dir"], ["review", "check", "dir"],
                     ["help", "lead"], ["version"], ["skill", "list"], ["memory", "get", "memstore_1", "/a.md"]):
            self.assertEqual(H.resolve(argv), argv, argv)

    def test_outside_a_repository_nothing_is_guessed(self):
        os.chdir(self.t)
        self.assertIsNone(H.infer_project())
        self.assertEqual(H.resolve(["instances", "show", "build"]), ["instances", "show", "build"])
        self.assertIsNone(H.resolve(["lead", "status"]))
        self.assertEqual(H.resolve(["lead", "status", "alpha"]), ["lead", "status", "alpha"])

    def test_environment_names_the_project(self):
        os.chdir(self.t)
        os.environ["QARGI_PROJECT"] = "beta"
        self.assertEqual(H.resolve(["lead", "status"]), ["lead", "status", "beta"])

    def test_the_command_line_uses_it(self):
        os.chdir(self.repo)
        r = subprocess.run([BIN, "project", "show"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alpha", r.stdout)
        os.chdir(self.t)
        r = subprocess.run([BIN, "project", "show"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)
        self.assertIn("which project?", r.stderr)


class Surface(Env):
    """What the rules-visible-early change declares (flags, forms, the card, the catalogue help), against what the command line does."""

    def cli(self, *args):
        return subprocess.run([BIN, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)

    def test_role_card_goes_to_the_card_generator_and_the_other_role_verbs_to_role_py(self):
        r = self.cli("role", "card", "build", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(sorted(doc), ["card", "chars", "class", "members_stale", "project", "role", "run", "words"])
        self.assertEqual((doc["role"], doc["class"], doc["project"], doc["run"], doc["members_stale"]), ("build", "write", None, None, None))
        self.assertEqual(doc["words"], len(doc["card"].split()))
        self.assertEqual(doc["chars"], len(doc["card"]))
        direct = subprocess.run([sys.executable, "-I", os.path.join(LIB, "rolecard.py"), "card", "build", "--json"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(json.loads(direct.stdout), doc)                         # the same object, by the command and by the module
        plain = self.cli("role", "card", "build")
        self.assertEqual((plain.returncode, plain.stdout), (0, doc["card"] + "\n"))
        listed = self.cli("role", "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("build", listed.stdout)
        self.assertNotIn("Class write", listed.stdout)                           # role list is still role.py's, not the card's

    def test_the_card_of_each_class_and_the_lead_card_with_the_stored_member_states(self):
        self.assertEqual(json.loads(self.cli("role", "card", "review", "--json").stdout)["class"], "read-only")
        lead = json.loads(self.cli("role", "card", "lead", "--json").stdout)
        self.assertEqual(lead["class"], "lead")
        self.assertIsNone(lead["members_stale"])
        with open(os.path.join(self.t, "s", "agent-states.json"), "w") as f:
            json.dump({"schema": 1, "projects": {"alpha": {"at": "2026-11-21T10:00:00Z", "members": {"forge": ["STALE"], "fine": []}}}}, f)
        os.chmod(os.path.join(self.t, "s", "agent-states.json"), 0o600)
        stale = json.loads(self.cli("role", "card", "lead", "--project", "alpha", "--json").stdout)
        self.assertEqual(stale["project"], "alpha")
        self.assertEqual(stale["members_stale"], {"as_of": "2026-11-21T10:00:00Z", "members": {"forge": ["STALE"]}})
        self.assertIn("forge (STALE)", stale["card"])

    def test_a_run_fills_in_its_paths(self):
        run = os.path.join(self.t, "run")
        for d in ("clone", "out", "tmp"):
            os.makedirs(os.path.join(run, d))
        with open(os.path.join(run, "tmpdir"), "w") as f:
            f.write(os.path.join(run, "tmp") + "\n")
        r = self.cli("role", "card", "review", "--run", run)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(os.path.join(run, "out"), r.stdout)
        self.assertEqual(json.loads(self.cli("role", "card", "review", "--run", run, "--json").stdout)["run"], run)

    def test_the_exit_statuses_of_the_card(self):
        for args, code, words in ((["role", "card", "nobody"], 1, "no role named nobody"),
                                  (["role", "card", "build", "--run", os.path.join(self.t, "none")], 1, "is not a run directory"),
                                  (["role", "card"], 2, "usage:"), (["role", "card", "build", "--nope"], 2, "unknown option"),
                                  (["role", "card", "build", "--project"], 2, "needs a value"), (["role", "card", "build", "extra"], 2, "unexpected argument")):
            r = self.cli(*args)
            self.assertEqual((r.returncode, r.stdout), (code, ""), args)
            self.assertIn(words, r.stderr, args)

    def test_the_card_is_declared_and_agent_list_says_where_it_stores_the_states(self):
        card = verbs("role")["card"]
        self.assertEqual({o["flag"] for o in card["opts"]}, {"--project", "--run", "--json"})
        self.assertEqual([a[0] for a in card["args"]], ["ROLE"])
        self.assertIn("rolecard.py", C.COMMANDS["role"]["scripts"])
        self.assertIn("STATE/agent-states.json", verbs("agent")["list"]["desc"])
        self.assertEqual(H.complete(["role", ""]), ["list", "show", "prompt", "check", "card"])
        self.assertIn("lead", H.complete(["role", "card", ""]))
        self.assertEqual(sorted(H.complete(["role", "card", "build", "--"])), ["--help", "--json", "--project", "--run"])
        text = " ".join(self.cli("help", "role", "card").stdout.split())
        self.assertIn("qargi role card lead", text)
        self.assertIn("open to a member", text)


class EarlyRulesHelp(Env):
    """The forms the rules-visible-early change put in the scripts are declared in lib/commands.py, with the usage errors the declaration promises."""

    def cli(self, *args):
        return subprocess.run([BIN, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)

    def test_the_dry_run_is_declared_on_the_five_verbs_and_on_no_other(self):
        has = {(c, v) for c in C.COMMANDS for v, spec in verbs(c).items() if "--dry-run" in {o["flag"] for o in spec["opts"]}}
        # `local run --dry-run` and the commands with a flag of their own (export, import) print what would run and are another change
        self.assertEqual({x for x in has if x[0] in ("release", "feature", "branch")},
                         {("release", "start"), ("release", "push"), ("release", "fix"), ("feature", "finish"), ("branch", "prune")})
        for c, v in (("release", "start"), ("release", "push"), ("release", "fix"), ("feature", "finish"), ("branch", "prune")):
            flat = " ".join(C.COMMANDS[c]["verbs"][v]["desc"].split())
            for want in ("dry-run: N would refuse; nothing was changed", "dry=1 first in the detail of the contract line", "git ls-remote", "the same token the plain plan has"):
                self.assertIn(want, flat, "%s %s" % (c, v))
        self.assertIn("for --push only (a usage error, exit 2, without it)", " ".join(C.COMMANDS["release"]["verbs"]["fix"]["desc"].split()))
        self.assertIn("QARGI_DRY", dict(C.ENVIRONMENT))
        man = H.man().replace("\\-", "-")
        self.assertIn("dry-run", man)
        self.assertIn("QARGI_DRY", man)

    def test_the_dry_run_flag_of_another_verb_is_a_usage_error_as_declared(self):
        for args, words in ((["release", "fix", "9.9.9", "--dry-run"], "--dry-run belongs to release start, release push and release fix --push"),
                            (["release", "finish", "9.9.9", "--dry-run"], "--dry-run belongs to release start, release push and release fix --push"),
                            (["feature", "start", "x", "--dry-run"], "--dry-run belongs to feature finish")):
            r = self.cli(*args)
            self.assertEqual((r.returncode, r.stdout), (2, ""), args)
            self.assertIn(words, r.stderr, args)

    def test_release_fix_record_is_declared_with_its_exclusions(self):
        fix = C.COMMANDS["release"]["verbs"]["fix"]
        self.assertIn("--record", {o["flag"] for o in fix["opts"]})
        flat = " ".join(fix["desc"].split())
        for want in ("no plan, no token and no approval", "exclusive with --push, --plan and --approved", "fix_paths", "inside the cut: push goes on under its approval",
                     "cut-fix-outside", "cut-branch-moved", "own_plan", "a later fix inside the paths goes on under the cut again"):
            self.assertIn(want, flat)
        self.assertIn("fix_paths", " ".join(C.COMMANDS["release"]["verbs"]["plan"]["desc"].split()))
        for flag in ("--record", "--dry-run", "--push"):
            self.assertIn(flag, H.complete(["release", "fix", "9.9.9", "--"]))                     # the completion offers each flag
        self.assertIn("--deleted", H.complete(["ref", "record", "--"]))
        self.assertIn("--agents", H.complete(["branch", "prune", "--"]))
        for args, words in ((["release", "fix", "9.9.9", "--record", "--push"], "--record and --push are two ways of taking a fix in"),
                            (["release", "fix", "9.9.9", "--record", "--plan", "abc"], "--record asks for no plan and no approval"),
                            (["release", "fix", "9.9.9", "--record", "--approved", "ok"], "--record asks for no plan and no approval"),
                            (["release", "start", "9.9.9", "--record"], "--record belongs to release fix")):
            r = self.cli(*args)
            self.assertEqual((r.returncode, r.stdout), (2, ""), args)
            self.assertIn(words, r.stderr, args)

    def test_the_answer_for_changelog_fragments_is_described_and_completes(self):
        self.assertIn("release.changelog.fragments", H.EXTRA_KEYS)
        desc = " ".join(C.COMMANDS["release"]["desc"].split())
        for want in ("release.changelog.fragments", "release-fragments-unfolded", "README* and .gitkeep", "release-notes-empty", "release fix VERSION --record"):
            self.assertIn(want, desc)
        flow = " ".join(slurp(os.path.join(ROOT, "docs", "flow", "git-flow.md")).split())
        for want in ("`release.changelog.fragments`", "`release-fragments-unfolded`", "`fix_paths`", "`own_plan`", "`release fix VERSION --record`", "`cut-fix-outside`"):
            self.assertIn(want, flow)
        self.assertIn("release.changelog.fragments", [k for k, _ in H.keys([])])

    def test_ref_record_declares_deleted_and_the_rewrite_of_a_release_branch(self):
        record = C.COMMANDS["ref"]["verbs"]["record"]
        self.assertEqual({o["flag"] for o in record["opts"]}, {"--rewrite", "--deleted", "--why", "--project"})
        self.assertEqual([(a[0], a[2] if len(a) > 2 else False) for a in record["args"]], [("REF", False), ("OLD", False), ("NEW", True)])
        flat = " ".join(record["desc"].split())
        for want in ("release/* or hotfix/* branch that origin does not have", "ref:deleted", "qargi ref deleted", "never a long-lived branch"):
            self.assertIn(want, flat)
        for stale in ("agent/* only", "the one move"):
            self.assertNotIn(stale, flat + " " + C.COMMANDS["ref"]["desc"])
        self.assertIn("starts at absent", " ".join(C.COMMANDS["ref"]["desc"].split()))
        self.assertIn("from absent when the ref was deleted since", " ".join(C.COMMANDS["ref"]["verbs"]["note"]["desc"].split()))
        self.assertNotIn("deleted or rewrote by hand, is not covered", " ".join(C.COMMANDS["local"]["verbs"]["verify"]["desc"].split()))
        r = self.cli("ref", "record", "--rewrite", "--deleted", "agent/x", "a", "--why", "x")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("takes --rewrite or --deleted, not both", r.stderr)

    def test_branch_prune_agents_is_declared_as_the_one_ungated_deletion(self):
        prune = C.COMMANDS["branch"]["verbs"]["prune"]
        self.assertEqual({o["flag"] for o in prune["opts"]}, {"--project", "--remote", "--agents", "--plan", "--approved", "--dry-run"})
        flat = " ".join(prune["desc"].split())
        for want in ("--agents is local only and the exception to the gate", "takes no --plan, --approved or --remote (a usage error, exit 2)", "never a feature branch", "(exit 2)"):
            self.assertIn(want, flat)
        self.assertIn("The one deletion that is not gated is prune --agents", " ".join(C.COMMANDS["branch"]["desc"].split()))
        for extra in ("--remote", "--plan x", "--approved y"):
            r = self.cli("branch", "prune", "--agents", *extra.split())
            self.assertEqual((r.returncode, r.stdout), (2, ""), extra)
            self.assertIn("--agents", r.stderr)
        flow = " ".join(slurp(os.path.join(ROOT, "docs", "flow", "git-flow.md")).split())
        self.assertIn("`qargi branch prune --agents [--dry-run]` is the exception to the gate", flow)
        self.assertIn("qargi branch prune --agents", slurp(os.path.join(ROOT, "skills", "qargi-flow", "SKILL.md")))


class WindowHelp(unittest.TestCase):
    def test_a_window_from_the_model_that_the_tokens_exceed_counts_as_assumed_in_the_help_the_man_page_and_the_flow_page(self):
        for name, text in (("help", C.COMMANDS["lead"]["verbs"]["usage"]["desc"]), ("man page", H.man().replace("\\-", "-")),
                           ("docs/flow/marshal.md", slurp(os.path.join(ROOT, "docs", "flow", "marshal.md")))):
            flat = " ".join(text.split())
            self.assertRegex(flat, r"window that the (model id|table) gave( for the model id)? counts as assumed too once the tokens exceed it", name)
            self.assertIn("no percentage and no advice", flat, name)
        self.assertIn("nor when the tokens exceed the window the model id gave", C.COMMANDS["lead"]["verbs"]["compact-check"]["opts"][1]["help"])


class RefusalHelp(Env):
    """qargi help refusal [CODE]: the catalogue entry of a code (lib/refusals.json, read through lib/refusal.py), the list of the codes, an unknown code."""

    def cli(self, *args):
        return subprocess.run([BIN, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)

    def entries(self):
        with open(os.path.join(LIB, "refusals.json")) as f:
            return json.load(f)["codes"]

    def test_the_list_names_every_code_with_its_class_exit_and_status(self):
        r = self.cli("help", "refusal")
        self.assertEqual(r.returncode, 0, r.stderr)
        flat = " ".join(r.stdout.split())
        for code, e in self.entries().items():
            self.assertIn(code, r.stdout)
            self.assertIn("(%s, exit %d, %s)" % (e["class"], e["exit"], e["status"]), flat)
        self.assertIn("qargi help refusal CODE", r.stdout)
        self.assertIn("refusal", self.cli("help").stdout)                        # the overview lists the topic

    def test_a_code_prints_its_rule_why_class_exit_fields_and_next(self):
        for code, e in self.entries().items():
            r = self.cli("help", "refusal", code)
            self.assertEqual(r.returncode, 0, (code, r.stderr))
            flat = "".join(r.stdout.split())                                     # the text is wrapped, also at a hyphen: compare without any white space
            self.assertTrue(flat.startswith("".join(("%s (%s)" % (code, e["status"])).split())), (code, flat[:60]))
            for want in ("Rule: " + e["rule"].rstrip("."), "Why: " + e["why"].rstrip("."), "Class: %s    Exit: %d" % (e["class"], e["exit"]),
                         "Message: " + e["message"], "Next, for a lead: " + e["next"]["lead"]):
                self.assertIn("".join(want.split()), flat, code)
            self.assertEqual("".join("Next, in the owner's own session (host):".split()) in flat, e["next"]["host"] != e["next"]["lead"], code)
            for k, v in e["fields"].items():
                self.assertIn("".join(("%s (%s)" % (k, v)).split()), flat, code)
        flat = " ".join(self.cli("help", "refusal", "plan-stale").stdout.split())
        self.assertIn("Fields: verb (verb), moved (label-list)", flat)
        self.assertIn("a token from a lead's plan never matches (R77)", flat)

    def test_an_unknown_code_or_two_words_exit_2_and_print_nothing_on_standard_output(self):
        for args in (["nosuch-code"], ["plan-stale", "plan-missing"], ["PLAN-STALE"]):
            r = self.cli("help", "refusal", *args)
            self.assertEqual((r.returncode, r.stdout), (2, ""), args)
            self.assertIn("no refusal code", r.stderr)
            self.assertIn("qargi help refusal lists the codes", r.stderr)

    def test_the_codes_are_completed_and_the_topic_is_in_the_man_page(self):
        self.assertIn("plan-stale", H.complete(["help", "refusal", ""]))
        self.assertIn("refusal", H.complete(["help", ""]))
        self.assertEqual(H.complete(["help", "refusal", "plan-stale", ""]), [])
        self.assertIn(".SH REFUSAL", H.man())
        self.assertIn("refusal", C.TOPICS)

    def test_the_reference_page_links_the_catalogue_and_the_environment_lists_the_refusal_variables(self):
        self.assertIn("(refusals.md)", slurp(os.path.join(ROOT, "docs", "reference", "README.md")))
        env = dict(C.ENVIRONMENT)
        for k in ("QARGI_DRY", "QARGI_VERB", "QARGI_ROLE"):
            self.assertIn(k, env)
        man = H.man().replace("\\-", "-")
        for k in ("QARGI_DRY", "QARGI_VERB", "QARGI_ROLE"):
            self.assertIn(k, man)


class ProviderNameHelp(unittest.TestCase):
    """The provider verbs take a runtime name, not a family name: the help says so, and the verbs agree."""

    def test_the_help_says_a_name_is_a_runtime_name(self):
        r = subprocess.run([BIN, "help", "provider"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = " ".join(r.stdout.split())
        self.assertIn("takes a runtime name, and a family name is refused as an unknown provider", text)

    def test_a_family_name_is_refused_as_the_help_says(self):
        r = subprocess.run([BIN, "provider", "layout", "claude"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown provider 'claude'", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
