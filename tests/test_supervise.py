#!/usr/bin/env python3
"""qargi supervise: hook handlers, the run registry, the tick's classes, the nudge caps. No model, no cloud, no real state:
every test uses temporary QARGI_STATE and QARGI_CONF directories, fixtures, and a fake `ant`. Hook events get their time from
QARGI_NOW so the scenarios are exact. Run: python3 tests/test_supervise.py"""
import inspect, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
T0 = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)
SECRET = "SECRET-COMMAND-TEXT-9f3"
FAKE_ANT = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE/ant.log"
case $1 in
  auth) exit 0;;
  beta:sessions:events) [ "$2" = send ] && printf '%s\\n' "$*" >> "$FAKE/sent.log"; echo '{}';;
  *) echo '{}';;
esac
"""


def at(minutes):
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state, self.conf, self.fake = (os.path.join(self.tmp, d) for d in ("s", "c", "fake"))
        for d in (self.state, self.conf, self.fake, os.path.join(self.tmp, "bin"), os.path.join(self.tmp, "home")):
            os.makedirs(d)
        ant = os.path.join(self.tmp, "bin", "ant")
        with open(ant, "w") as f:
            f.write(FAKE_ANT)
        os.chmod(ant, 0o755)
        self.env = dict(os.environ, QARGI_STATE=self.state, QARGI_CONF=self.conf, FAKE=self.fake, HOME=os.path.join(self.tmp, "home"),
                        PATH=os.path.join(self.tmp, "bin") + os.pathsep + os.environ["PATH"])
        self.env.pop("QARGI_NOW", None)
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- helpers
    def qargi(self, *args, stdin="", env=None):
        return subprocess.run([BIN, *args], input=stdin, capture_output=True, text=True, env=env or self.env, timeout=60)

    def run_dir(self, name, ability="build", manifest=False, register=True, started=-1):
        run = os.path.join(self.tmp, "runs", "qargi." + name)
        os.makedirs(os.path.join(run, "out"))
        for f, body in (("ability", ability + "\n"), ("refs.before", "")):
            with open(os.path.join(run, f), "w") as h:
                h.write(body)
        if manifest:
            with open(os.path.join(run, "out", "manifest.json"), "w") as h:
                json.dump({"status": "DONE"}, h)
        for d, _, files in os.walk(run):   # fixture files look as old as the start of the scenario
            for x in files + ["."]:
                os.utime(os.path.join(d, x), (T0.timestamp(), T0.timestamp()))
        if register:
            with open(os.path.join(self.state, "local-runs.jsonl"), "a") as h:
                h.write(json.dumps({"run": run, "slug": name, "ability": ability, "base": "main", "started": at(started)}) + "\n")
        return run

    def hook(self, verb, payload, minutes=0, raw=None):
        env = dict(self.env, QARGI_NOW=at(minutes))
        return self.qargi("hook", verb, stdin=raw if raw is not None else json.dumps(payload), env=env)

    def ev(self, verb, aid, run, minutes, **kw):
        p = {"agent_id": aid, "agent_type": "build", "session_id": "sess1", "cwd": run}
        p.update(kw)
        r = self.hook(verb, p, minutes)
        self.assertEqual(r.returncode, 0, r.stderr)

    def tool(self, aid, run, minutes, cmd="ls"):
        self.ev("tool-use", aid, run, minutes, tool_name="Bash", tool_input={"command": cmd}, tool_response={"x": 1})

    def tick(self, minutes):
        r = self.qargi("supervise", "tick", "--now", at(minutes))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    def runs(self):
        with open(os.path.join(self.state, "runs.json")) as f:
            return json.load(f)

    def row(self, key):
        return self.runs()["runs"][key]

    def lines(self, name):
        try:
            with open(os.path.join(self.state, name)) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def nudges(self):
        return [json.loads(x) for x in self.lines("nudges.jsonl")]

    def tracker(self, rows):
        with open(os.path.join(self.state, "sessions.json"), "w") as f:
            json.dump(rows, f)


def srow(status="running", why=None, seen=0, cost="120", budget="3000", review="pending", **kw):
    r = {"instance": "alpha-build", "label": "x", "created": at(-60), "status": status, "stop_reason": why, "last_seen": at(seen),
         "list_cost": cost, "budget": budget, "review_state": review, "closed_at": None, "outputs_collected": False, "interrupt_sent_at": None}
    r.update(kw)
    return r


# ---------------------------------------------------------------------------------------------------- hook handlers
class Hooks(Base):
    def test_each_handler_appends_one_small_line_and_stores_no_content(self):
        run = self.run_dir("a")
        self.ev("subagent-start", "agent-1", run, 0)
        self.ev("tool-use", "agent-1", run, 1, tool_name="Bash", tool_input={"command": SECRET}, tool_response={"stdout": SECRET})
        self.ev("tool-failure", "agent-1", run, 2, tool_name="Bash", tool_input={"command": SECRET}, error="boom " + SECRET, is_interrupt=False)
        self.ev("notification", "agent-1", run, 3, message="needs " + SECRET, title=SECRET, notification_type="permission_prompt")
        self.ev("stop-failure", "agent-1", run, 4, error="rate_limit", error_details=SECRET, last_assistant_message=SECRET)
        self.ev("pre-compact", "agent-1", run, 5, trigger="auto", custom_instructions=None)
        self.ev("subagent-stop", "agent-1", run, 6, last_assistant_message=SECRET, background_tasks=[{"id": "b"}], agent_transcript_path="/x/y.jsonl")
        path = os.path.join(self.state, "run-events", "agent-1.jsonl")
        body = open(path).read()
        self.assertNotIn(SECRET, body)
        events = [json.loads(x) for x in body.splitlines()]
        self.assertEqual([e["ev"] for e in events], ["start", "tool", "fail", "notify", "stopfail", "compact", "stop"])
        self.assertEqual(events[0]["t"], at(0))
        self.assertEqual(events[1]["tool"], "Bash")
        self.assertEqual(len(events[1]["dg"]), 12)
        self.assertEqual((events[3]["ntype"], events[4]["err"], events[5]["trigger"], events[6]["bg"]), ("permission_prompt", "rate_limit", "auto", 1))
        self.assertTrue(all(len(x) < 400 for x in body.splitlines()))
        self.assertEqual(events[1]["run"], run)

    def test_digest_depends_on_name_and_input(self):
        run = self.run_dir("a")
        for cmd in ("ls", "ls", "pwd"):
            self.tool("a1", run, 0, cmd)
        ev = [json.loads(x) for x in open(os.path.join(self.state, "run-events", "a1.jsonl"))]
        self.assertEqual(ev[0]["dg"], ev[1]["dg"])
        self.assertNotEqual(ev[0]["dg"], ev[2]["dg"])

    def test_malformed_input_never_blocks_and_exits_zero(self):
        for raw in ("", "not json", "[1,2]", "null", '{"agent_id":', "\x00\xff\xfe", "{" * 5000, '{"agent_id": 5, "tool_input": 7}',
                    json.dumps({"agent_id": "a", "tool_name": ["x"], "tool_input": {"k": [1] * 10000}}), json.dumps({"hook_event_name": "PostToolUse"})):
            for verb in ("subagent-start", "subagent-stop", "tool-use", "tool-failure", "notification", "stop-failure", "pre-compact"):
                t = time.time()
                r = self.hook(verb, None, raw=raw)
                self.assertEqual(r.returncode, 0, "%s %r: %s" % (verb, raw[:20], r.stderr))
                self.assertEqual(r.stdout, "", "a hook must print nothing the harness could read as a decision")
                self.assertLess(time.time() - t, 5)

    def test_every_layer_exits_zero_on_its_own(self):
        py = os.path.join(ROOT, "lib", "supervise.py")
        for raw in ("", "garbage", "[1]", '{"agent_id":'):
            r = subprocess.run([sys.executable, "-I", py, "hook-event", "tool-use"], input=raw, capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 0, "the Python handler itself must not fail on %r" % raw)
        fake = os.path.join(self.tmp, "badpy")
        os.makedirs(fake)
        with open(os.path.join(fake, "python3"), "w") as f:
            f.write("#!/bin/sh\nexit 3\n")
        os.chmod(os.path.join(fake, "python3"), 0o755)
        env = dict(self.env, PATH=fake + os.pathsep + self.env["PATH"])
        for cmd in ([os.path.join(ROOT, "lib", "hook.sh"), "tool-use"], [BIN, "hook", "tool-use"]):
            r = subprocess.run(cmd, input="{}", capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, "a failing interpreter must not make %s fail" % cmd[-2:])

    def test_exits_zero_even_when_the_state_cannot_be_written(self):
        with open(os.path.join(self.tmp, "blocker"), "w") as f:
            f.write("a file where the state directory should be")
        env = dict(self.env, QARGI_STATE=os.path.join(self.tmp, "blocker", "s"))
        r = self.qargi("hook", "tool-use", stdin=json.dumps({"agent_id": "a", "tool_name": "Bash"}), env=env)
        self.assertEqual(r.returncode, 0)

    def test_hostile_agent_id_cannot_leave_the_event_directory(self):
        self.hook("tool-use", {"agent_id": "../../escape", "tool_name": "Bash", "tool_input": {}})
        self.assertEqual(os.listdir(os.path.join(self.state, "run-events")), ["....escape.jsonl"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape.jsonl")))

    def test_events_of_the_coordinating_session_are_not_a_runs(self):
        self.hook("tool-use", {"session_id": "main", "tool_name": "Bash", "tool_input": {}, "cwd": "/"})
        self.hook("notification", {"session_id": "main", "notification_type": "permission_prompt", "cwd": "/"})
        self.assertFalse(os.path.isdir(os.path.join(self.state, "run-events")) and os.listdir(os.path.join(self.state, "run-events")))

    def test_hooks_never_touch_the_registry(self):
        run = self.run_dir("a")
        self.tool("a1", run, 0)
        self.assertFalse(os.path.exists(os.path.join(self.state, "runs.json")), "only the tick writes runs.json")
        self.tick(1)
        before = open(os.path.join(self.state, "runs.json")).read()
        for i in range(3):
            self.tool("a1", run, 2 + i)
        self.assertEqual(open(os.path.join(self.state, "runs.json")).read(), before)
        import supervise
        self.assertNotIn("runs", inspect.getsource(supervise.hook_event))

    def test_run_event_hook_is_dispatched_before_resolve_and_help_still_works(self):
        self.assertEqual(self.qargi("hook", "tool-use", "--help").returncode, 0)
        self.assertIn("tool-use", self.qargi("help", "hook").stdout)


# ---------------------------------------------------------------------------------------------------- classes
class Classify(Base):
    def test_finished_with_manifest_is_quiet(self):
        run = self.run_dir("fin", manifest=True)
        self.ev("subagent-start", "fin1", run, 0)
        self.tool("fin1", run, 1)
        self.ev("subagent-stop", "fin1", run, 2, background_tasks=[])
        self.assertEqual(self.tick(300), [])
        r = self.row("fin1")
        self.assertEqual((r["class"], r["manifest_present"], r["end_kind"], r["report_count"], r["tool_calls"]), ("finished", True, "final", 1, 1))
        self.assertEqual(r["ability"], "build")
        self.assertEqual(r["run_id"], "qargi.fin")

    def test_interim_then_final_is_two_reports_not_a_stall(self):
        run = self.run_dir("two")
        self.ev("subagent-start", "t1", run, 0)
        self.ev("subagent-stop", "t1", run, 5, background_tasks=[{"id": "bg"}])
        self.assertEqual(self.tick(10), [])
        self.assertEqual((self.row("t1")["class"], self.row("t1")["end_kind"]), ("interim", "interim"))
        with open(os.path.join(run, "out", "manifest.json"), "w") as h:
            json.dump({"status": "DONE"}, h)
        os.utime(os.path.join(run, "out", "manifest.json"), (T0.timestamp(), T0.timestamp()))
        self.ev("subagent-stop", "t1", run, 20, background_tasks=[])
        self.assertEqual(self.tick(21), [])
        r = self.row("t1")
        self.assertEqual((r["class"], r["end_kind"], r["report_count"]), ("finished", "final", 2))

    def test_interim_that_never_finishes_is_overdue_after_the_cap(self):
        run = self.run_dir("iv")
        self.ev("subagent-stop", "iv1", run, 0, background_tasks=[{"id": "bg"}])
        self.assertEqual(self.tick(34), [])                        # 34 minutes: still inside the 35 minute cap
        self.assertEqual(self.tick(36), ["QARGI SUPERVISE interim_overdue qargi.iv notify-then-nudge"])
        self.assertEqual(self.row("iv1")["report_count"], 1)

    def test_stop_without_background_tasks_and_without_manifest_is_reported(self):
        run = self.run_dir("nm")
        self.ev("subagent-stop", "nm1", run, 0, background_tasks=[])
        self.assertEqual(self.tick(1), ["QARGI SUPERVISE ended_no_manifest qargi.nm collect-or-rerun"])

    def test_permission_wait_is_not_a_stall_and_is_never_nudged(self):
        run = self.run_dir("pw")
        self.tool("pw1", run, 0)
        self.ev("notification", "pw1", run, 1, notification_type="permission_prompt", message=SECRET)
        self.assertEqual(self.tick(2), ["QARGI SUPERVISE waiting qargi.pw answer-the-pending-approval"])
        r = self.row("pw1")
        self.assertEqual((r["waiting_on"], r["waiting_since"]), ("permission_prompt", at(1)))
        for m in (60, 200, 400):                                  # hours later it is still a wait, never suspected dead, never nudged
            self.assertEqual(self.tick(m), [])
            self.assertEqual(self.row("pw1")["class"], "waiting")
        self.assertEqual(self.nudges(), [])
        self.tool("pw1", run, 410)                                # the approval was answered: the run went on
        self.tick(411)
        self.assertEqual((self.row("pw1")["class"], self.row("pw1")["waiting_on"]), ("working", None))

    def test_a_notification_of_another_type_is_not_a_wait(self):
        run = self.run_dir("nt")
        self.tool("nt1", run, 0)
        self.ev("notification", "nt1", run, 1, notification_type="auth_success")
        self.tick(2)
        self.assertEqual(self.row("nt1")["waiting_on"], None)

    def test_loop_of_identical_tool_digests(self):
        run = self.run_dir("lp")
        for i in range(4):
            self.tool("lp1", run, i)                              # the same call four times
        self.assertEqual(self.tick(5), ["QARGI SUPERVISE looping qargi.lp notify-then-nudge"])
        self.assertEqual(self.row("lp1")["repeat_count"], 4)
        run2 = self.run_dir("lp2")
        for i, c in enumerate(("a", "a", "b", "a", "a")):
            self.tool("lp2", run2, i, c)                          # never three in a row
        self.tick(6)
        self.assertEqual((self.row("lp2")["class"], self.row("lp2")["repeat_count"]), ("working", 2))

    def test_three_identical_in_a_row_is_a_loop_two_is_not(self):
        r2, r3 = self.run_dir("l2"), self.run_dir("l3")
        for i in range(2):
            self.tool("l2a", r2, i)
        for i in range(3):
            self.tool("l3a", r3, i)
        self.tick(5)
        self.assertEqual((self.row("l2a")["class"], self.row("l3a")["class"]), ("working", "looping"))

    def test_suspected_dead_when_activity_is_stale(self):
        run = self.run_dir("dd")
        self.tool("dd1", run, 0)
        self.tool("dd1", run, 1, "other")
        self.assertEqual(self.tick(30), [])                       # 29 minutes since the last call: below the 30 minute floor
        self.assertEqual(self.tick(32), ["QARGI SUPERVISE suspected_dead qargi.dd notify-then-nudge"])
        self.assertEqual(self.row("dd1")["last_activity_at"], at(1))

    def test_file_changes_count_as_activity(self):
        run = self.run_dir("fc")
        self.tool("fc1", run, 0)
        os.makedirs(os.path.join(run, "out"), exist_ok=True)
        with open(os.path.join(run, "out", "log.txt"), "w") as h:
            h.write("working")
        os.utime(os.path.join(run, "out", "log.txt"), ((T0 + timedelta(minutes=50)).timestamp(),) * 2)
        self.assertEqual(self.tick(60), [])                       # the log changed 10 minutes ago
        self.assertEqual(self.row("fc1")["last_activity_at"], at(50))

    def test_rate_limit_stop_failure(self):
        run = self.run_dir("rl")
        self.tool("rl1", run, 0)
        self.ev("stop-failure", "rl1", run, 1, error="rate_limit", error_details=SECRET)
        self.assertEqual(self.tick(2), ["QARGI SUPERVISE stop_failure qargi.rl wait-then-resume"])
        self.assertEqual(self.row("rl1")["stop_failure"], "rate_limit")
        self.ev("stop-failure", "rl2", run, 3, error="authentication_failed")
        self.assertIn("QARGI SUPERVISE stop_failure qargi.rl log-in-again", self.tick(4))

    def test_events_without_an_agent_id_are_applied_to_the_run_they_came_from(self):
        run = self.run_dir("rn")
        self.tool("rn1", run, 0)
        self.hook("notification", {"session_id": "s", "cwd": run, "notification_type": "permission_prompt"}, 1)
        self.assertEqual(self.tick(2), ["QARGI SUPERVISE waiting qargi.rn answer-the-pending-approval"])
        self.assertEqual(self.row("rn1")["waiting_on"], "permission_prompt")

    def test_per_ability_thresholds_come_from_the_data_file(self):
        d = json.load(open(os.path.join(ROOT, "lib", "supervise-defaults.json")))
        d["per_ability"] = {"test": {"local": {"stale_seconds": 7200}}}
        path = os.path.join(self.tmp, "d.json")
        json.dump(d, open(path, "w"))
        self.env["QARGI_SUPERVISE_DEFAULTS"] = path
        run, run2 = self.run_dir("pa", ability="test"), self.run_dir("pb", ability="build")
        self.tool("pa1", run, 0)
        self.tool("pb1", run2, 0)
        self.tick(100)
        self.assertEqual((self.row("pa1")["class"], self.row("pb1")["class"]), ("working", "suspected_dead"))

    def test_registered_run_without_hooks_is_still_seen_and_old_ones_are_ignored(self):
        self.run_dir("nohook", started=0)
        self.run_dir("ancient", started=-60 * 24 * 30)
        gone = self.run_dir("gone", started=0)
        shutil.rmtree(gone)
        self.assertEqual(self.tick(10), [])
        self.assertEqual(sorted(self.runs()["runs"]), ["local-qargi.nohook"])
        self.assertEqual(self.tick(40), ["QARGI SUPERVISE suspected_dead qargi.nohook notify-then-nudge"])
        run = os.path.join(self.tmp, "runs", "qargi.nohook")
        self.tool("real1", run, 41)                               # a real agent row replaces the placeholder
        self.tick(42)
        self.assertEqual(sorted(self.runs()["runs"]), ["real1"])
        self.assertEqual(self.row("real1")["slug"], "nohook")

    def test_cloud_rows(self):
        self.tracker({
            "sesn_ra": srow("idle", "requires_action"),
            "sesn_bud": srow("idle", "budget_reached"),
            "sesn_stale": srow("running", seen=0),
            "sesn_fresh": srow("running", seen=120),
            "sesn_rev": srow("idle", "end_turn", seen=0),
            "sesn_done": srow("idle", "end_turn", seen=0, review="applied"),
            "sesn_stopped": srow("idle", "end_turn", seen=0, interrupt_sent_at=at(1)),
            "sesn_closed": srow("archived", "end_turn", seen=0, closed_at=at(5), review="applied"),
        })
        out = self.tick(121)
        self.assertEqual(sorted(out), sorted([
            "QARGI SUPERVISE budget_reached sesn_bud raise-the-budget-or-collect",
            "QARGI SUPERVISE idle_awaiting_review sesn_rev collect-and-review",
            "QARGI SUPERVISE requires_action sesn_ra answer-the-pending-approval",
            "QARGI SUPERVISE stale_running sesn_stale refresh-then-nudge"]))
        self.assertEqual({k: v["class"] for k, v in self.runs()["runs"].items()}["sesn_fresh"], "working")
        self.assertEqual(self.row("sesn_stopped")["class"], "stopped_by_qargi")

    def test_cloud_stale_uses_last_processed_at_when_present(self):
        self.tracker({"sesn_a": srow("running", seen=0, last_processed_at=at(118))})
        self.assertEqual(self.tick(120), [])


# ---------------------------------------------------------------------------------------------------- idempotence, single writer
class Tick(Base):
    def scenario(self):
        run = self.run_dir("lp")
        for i in range(4):
            self.tool("lp1", run, i)
        run2 = self.run_dir("pw")
        self.ev("notification", "pw1", run2, 0, notification_type="permission_prompt")
        self.tracker({"sesn_ra": srow("idle", "requires_action")})

    def snapshot(self):
        r = self.runs()
        r.pop("last_tick_at")
        return json.dumps(r, sort_keys=True), [self.lines(n) for n in ("supervisor.log", "audit.log", "nudges.jsonl")]

    def test_running_the_tick_twice_changes_nothing_and_prints_nothing_new(self):
        self.scenario()
        first = self.tick(3)
        self.assertEqual(len(first), 3, first)
        snap = self.snapshot()
        self.assertEqual(self.tick(3), [])
        self.assertEqual(self.tick(3), [])
        self.assertEqual(self.snapshot(), snap)
        self.assertEqual(self.runs()["last_tick_at"], at(3))

    def test_log_and_audit_lines_carry_the_supervisor_origin(self):
        self.scenario()
        self.tick(3)
        audit = [json.loads(x) for x in self.lines("audit.log")]
        self.assertEqual(len(audit), 3)
        self.assertTrue(all(a["origin"] == "supervisor" and a["verb"].startswith("supervise:") for a in audit))
        self.assertEqual(len(self.lines("supervisor.log")), 3)
        self.assertTrue(all("QARGI SUPERVISE" in x for x in self.lines("supervisor.log")))

    def test_a_class_that_clears_and_returns_is_announced_again(self):
        run = self.run_dir("x")
        self.ev("notification", "x1", run, 0, notification_type="permission_prompt")
        self.assertEqual(len(self.tick(1)), 1)
        self.tool("x1", run, 2)
        self.assertEqual(self.tick(3), [])
        self.ev("notification", "x1", run, 4, notification_type="permission_prompt")
        self.assertEqual(len(self.tick(5)), 1)

    def test_events_are_folded_once_even_if_the_tick_is_repeated(self):
        run = self.run_dir("x")
        self.tool("x1", run, 0)
        self.tick(1)
        self.tick(1)
        self.assertEqual(self.row("x1")["tool_calls"], 1)
        self.tool("x1", run, 2)
        self.tick(3)
        self.assertEqual(self.row("x1")["tool_calls"], 2)

    def test_a_half_written_event_line_waits_for_its_newline(self):
        run = self.run_dir("x")
        self.tool("x1", run, 0)
        with open(os.path.join(self.state, "run-events", "x1.jsonl"), "a") as h:
            h.write('{"agent_id": "x1", "ev": "tool", "t": "' + at(1) + '", "dg"')
        self.tick(2)
        self.assertEqual(self.row("x1")["tool_calls"], 1)
        with open(os.path.join(self.state, "run-events", "x1.jsonl"), "a") as h:
            h.write(': "z"}\n')
        self.tick(3)
        self.assertEqual(self.row("x1")["tool_calls"], 2)

    def test_registry_rows_have_the_designed_fields(self):
        run = self.run_dir("x")
        self.tool("x1", run, 0)
        self.tick(1)
        import supervise
        self.assertFalse(set(supervise.FILE_FIELDS) - set(self.row("x1")))

    def test_single_writer_parallel_ticks_print_each_line_once_and_keep_the_file_valid(self):
        self.scenario()
        outs = []
        def go():
            outs.append(self.qargi("supervise", "tick", "--now", at(3)).stdout.splitlines())
        ts = [threading.Thread(target=go) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        flat = [x for o in outs for x in o]
        self.assertEqual(len(flat), 3, flat)
        self.assertEqual(len(set(flat)), 3)
        self.assertEqual(len(self.lines("audit.log")), 3)
        self.runs()

    def test_a_tick_waits_for_the_writer_lock(self):
        import fcntl
        self.scenario()
        with open(os.path.join(self.state, "runs.json.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            p = subprocess.Popen([BIN, "supervise", "tick", "--now", at(3)], stdout=subprocess.PIPE, text=True, env=self.env)
            time.sleep(1.0)
            self.assertIsNone(p.poll(), "the tick must wait while another writer holds the lock")
            self.assertFalse(os.path.exists(os.path.join(self.state, "runs.json")))
            fcntl.flock(lock, fcntl.LOCK_UN)
        out, _ = p.communicate(timeout=30)
        self.assertEqual(len(out.splitlines()), 3)

    def test_status_warns_when_the_tick_is_overdue(self):
        r = self.qargi("supervise", "status", "--now", at(0))
        self.assertIn("WARNING: no tick has run", r.stdout)
        self.tick(0)
        self.assertNotIn("WARNING", self.qargi("supervise", "status", "--now", at(9)).stdout)    # interval is 5 minutes: 10 is the limit
        self.assertNotIn("WARNING", self.qargi("supervise", "status", "--now", at(10)).stdout)
        self.assertIn("WARNING: the last tick was 11 minutes ago", self.qargi("supervise", "status", "--now", at(11)).stdout)
        j = json.loads(self.qargi("supervise", "status", "--json", "--now", at(11)).stdout)
        self.assertIn("warning", j)

    def test_status_does_not_write(self):
        self.scenario()
        self.tick(3)
        before = open(os.path.join(self.state, "runs.json")).read()
        self.qargi("supervise", "status", "--now", at(500))
        self.assertEqual(open(os.path.join(self.state, "runs.json")).read(), before)


# ---------------------------------------------------------------------------------------------------- nudges
class Nudges(Base):
    def looping(self, name="lp", aid="lp1"):
        run = self.run_dir(name)
        for i in range(4):
            self.tool(aid, run, i)
        return run

    def test_local_nudge_is_prepared_after_notice_and_never_sent(self):
        self.looping()
        self.assertEqual(self.tick(5), ["QARGI SUPERVISE looping qargi.lp notify-then-nudge"])      # notify first
        self.assertEqual(self.tick(10), [])                                                          # not yet: the notice is 5 minutes old
        out = self.tick(16)
        self.assertEqual(out[0], "QARGI SUPERVISE looping qargi.lp nudge-prepared")
        text = json.load(open(os.path.join(ROOT, "lib", "supervise-defaults.json")))["nudge"]["template"]
        self.assertTrue(any("agent lp1" in x and "nudge 1 of 2" in x and "1 left" in x for x in out), out)
        self.assertIn("    " + text, out)
        self.assertTrue(any("qargi supervise delivered lp1" in x for x in out))
        n = self.nudges()
        self.assertEqual([(e["type"], e["key"], e["target"], e["text"], e["number"]) for e in n], [("prepared", "lp1", "lp1", text, 1)])
        self.assertEqual(self.tick(17), [])
        self.assertEqual(len(self.nudges()), 1, "one outstanding nudge at a time")
        self.assertEqual(self.row("lp1")["nudges"], 0, "a prepared nudge is not counted")
        self.assertNotIn("sent.log", os.listdir(self.fake))

    def test_template_is_fixed_and_carries_nothing_from_the_agent(self):
        run = self.looping()
        self.ev("notification", "lp1", run, 6, notification_type="auth_success", message=SECRET)
        self.tick(5)
        self.tick(16)
        self.assertNotIn(SECRET, open(os.path.join(self.state, "nudges.jsonl")).read())
        self.assertIn("approves nothing", self.nudges()[0]["text"])

    def test_two_nudges_cooldown_and_cap(self):
        self.looping()
        self.tick(5)
        self.tick(16)
        r = self.qargi("supervise", "delivered", "lp1", "--now", at(17))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tick(18), [])
        self.assertEqual((self.row("lp1")["nudges"], self.row("lp1")["last_nudge_at"]), (1, at(17)))
        self.assertEqual(self.tick(26), [], "cooldown: only 9 minutes since the first nudge")
        out = self.tick(27)                                                                          # 10 minutes
        self.assertEqual(out[0], "QARGI SUPERVISE looping qargi.lp nudge-prepared")
        self.assertTrue(any("nudge 2 of 2" in x and "0 left" in x for x in out), out)
        self.assertEqual(self.qargi("supervise", "delivered", "lp1", "--now", at(29)).returncode, 0)
        self.assertEqual(self.tick(30), [])
        out = self.tick(60)                                                                          # still stalled after both nudges
        self.assertEqual(out, ["QARGI SUPERVISE looping qargi.lp salvage"])
        self.assertEqual(self.tick(90), [])
        self.assertEqual(len([e for e in self.nudges() if e["type"] == "prepared"]), 2, "a third is never prepared")
        r = self.qargi("supervise", "delivered", "lp1", "--now", at(95))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no prepared nudge", r.stderr)
        self.assertEqual(self.row("lp1")["nudges"], 2)
        self.assertEqual(len([e for e in self.nudges() if e["type"] == "delivered"]), 2)

    def test_delivery_is_refused_when_no_nudge_was_prepared(self):
        self.looping()
        self.tick(5)
        self.assertNotEqual(self.qargi("supervise", "delivered", "lp1").returncode, 0)
        self.assertNotEqual(self.qargi("supervise", "delivered", "nobody").returncode, 0)

    def test_nothing_is_prepared_while_the_run_waits_and_a_prepared_one_is_cancelled(self):
        run = self.looping()
        self.tick(5)
        self.tick(16)
        self.assertEqual(len(self.nudges()), 1)
        self.ev("notification", "lp1", run, 20, notification_type="permission_prompt")
        out = self.tick(21)
        self.assertEqual(out, ["QARGI SUPERVISE waiting qargi.lp answer-the-pending-approval"])
        self.assertEqual([e["type"] for e in self.nudges()], ["prepared", "cancelled"])
        r = self.qargi("supervise", "delivered", "lp1", "--now", at(22))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.row("lp1")["nudges"], 0)
        self.tick(200)
        self.assertEqual(len(self.nudges()), 2)

    def test_gate_rules_directly(self):
        import supervise as S
        d = S.load_defaults()
        now = T0
        fresh = {"delivered": 0, "last": None}
        self.assertIsNone(S.gate(fresh, now, d, "build", False))
        self.assertIn("waits", S.gate(fresh, now, d, "build", True))
        self.assertIn("budget", S.gate(fresh, now, d, "build", False, "the session's budget is nearly used"))
        self.assertIn("cap", S.gate({"delivered": 2, "last": at(-600)}, now, d, "build", False))
        self.assertIn("cooldown", S.gate({"delivered": 1, "last": at(-9)}, now, d, "build", False))
        self.assertIsNone(S.gate({"delivered": 1, "last": at(-10)}, now, d, "build", False))
        d["nudge"].update(max_per_run=9, cooldown_seconds=1)             # the data cannot loosen the caps
        self.assertIn("cap", S.gate({"delivered": 2, "last": at(-600)}, now, d, "build", False))
        self.assertIn("cooldown", S.gate({"delivered": 1, "last": at(-5)}, now, d, "build", False))
        d["nudge"].update(max_per_run=1)
        self.assertIn("cap", S.gate({"delivered": 1, "last": at(-600)}, now, d, "build", False))

    def test_standing_permission_is_off(self):
        import supervise as S
        self.assertFalse(S.standing_permission(S.load_defaults(), "x"))

    # ---- cloud
    def nudge(self, sid, minutes, asked="please nudge it, it is stuck"):
        args = ["supervise", "nudge", sid, "--now", at(minutes)]
        if asked is not None:
            args += ["--asked", asked]
        return self.qargi(*args)

    def sent(self):
        try:
            return ["beta:sessions:events send" + x for x in open(os.path.join(self.fake, "sent.log")).read().split("beta:sessions:events send")[1:]]
        except OSError:
            return []

    def test_cloud_nudge_is_prepared_not_sent_and_needs_asked(self):
        self.tracker({"sesn_s": srow("running", seen=0)})
        self.assertEqual(self.tick(130), ["QARGI SUPERVISE stale_running sesn_s refresh-then-nudge"])
        out = self.tick(141)
        self.assertEqual(out[0], "QARGI SUPERVISE stale_running sesn_s nudge-prepared")
        self.assertTrue(any('qargi supervise nudge sesn_s --asked "<your words>"' in x for x in out), out)
        self.assertEqual(self.sent(), [])
        r = self.nudge("sesn_s", 142, asked=None)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.sent(), [], "no --asked, no send")

    def test_cloud_nudge_send_counts_audits_and_respects_the_caps(self):
        self.tracker({"sesn_s": srow("running", seen=0)})
        r = self.nudge("sesn_s", 130)
        self.assertEqual(r.returncode, 0, r.stderr)
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        self.assertIn("beta:sessions:events send --session-id sesn_s", sent[0])
        self.assertIn("user.message", sent[0])
        self.assertIn("not from the user", sent[0])
        r = self.nudge("sesn_s", 135)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cooldown", r.stderr)
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.nudge("sesn_s", 141).returncode, 0)
        r = self.nudge("sesn_s", 300)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cap of 2", r.stderr)
        self.assertEqual(len(self.sent()), 2, "the third nudge is refused")
        audit = [json.loads(x) for x in self.lines("audit.log")]
        verbs = [a["verb"] for a in audit]
        self.assertEqual(verbs.count("supervise:nudge-sent"), 2)
        self.assertEqual(verbs.count("supervise:nudge-refused"), 2)
        self.assertTrue(all(a.get("origin") == "supervisor" for a in audit if a["verb"].startswith("supervise:")))
        self.assertTrue(any(a["asked"] == "please nudge it, it is stuck" for a in audit))
        self.tick(301)
        self.assertEqual(self.row("sesn_s")["nudges"], 2)

    def test_cloud_nudge_is_refused_while_the_session_waits_or_the_budget_is_tight(self):
        self.tracker({"sesn_ra": srow("idle", "requires_action"), "sesn_bud": srow("idle", "budget_reached"),
                      "sesn_tight": srow("running", seen=0, cost="2600"), "sesn_closed": srow("archived", closed_at=at(1)),
                      "sesn_edge": srow("running", seen=0, cost="2549"), "sesn_line": srow("running", seen=0, cost="2550")})
        for sid, word in (("sesn_line", "budget"),("sesn_ra", "approval"), ("sesn_bud", "budget"), ("sesn_tight", "budget"), ("sesn_closed", "not active"), ("sesn_none", "not tracked")):
            r = self.nudge(sid, 130)
            self.assertNotEqual(r.returncode, 0, sid)
            self.assertIn(word, r.stderr, sid)
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.nudge("sesn_edge", 130).returncode, 0)     # 85 percent is the line: 2549 of 3000 is below it

    def test_tick_prepares_no_cloud_nudge_when_the_budget_is_tight(self):
        self.tracker({"sesn_t": srow("running", seen=0, cost="2700")})
        self.tick(130)
        self.assertEqual(self.tick(200), [])
        self.assertEqual(self.nudges(), [])

    def test_a_cloud_run_waiting_on_an_approval_gets_no_prepared_nudge(self):
        self.tracker({"sesn_ra": srow("idle", "requires_action", seen=0)})
        self.tick(130)
        self.assertEqual(self.tick(400), [])
        self.assertEqual(self.nudges(), [])


# ---------------------------------------------------------------------------------------------------- snippet
class Snippet(Base):
    def test_hooks_prints_the_snippet_and_writes_nothing(self):
        r = self.qargi("supervise", "hooks")
        self.assertEqual(r.returncode, 0)
        j = json.loads(r.stdout)["hooks"]
        self.assertEqual(sorted(j), sorted(["SubagentStart", "SubagentStop", "PostToolUse", "PostToolUseFailure", "Notification", "StopFailure", "PreCompact"]))
        want = {"SubagentStart": "subagent-start", "SubagentStop": "subagent-stop", "PostToolUse": "tool-use", "PostToolUseFailure": "tool-failure",
                "Notification": "notification", "StopFailure": "stop-failure", "PreCompact": "pre-compact"}
        for ev, verb in want.items():
            h = j[ev][0]["hooks"][0]
            self.assertEqual((h["type"], h["command"]), ("command", "qargi hook " + verb))
            self.assertLessEqual(h["timeout"], 10)
            self.assertEqual(self.qargi("hook", verb, stdin="{}").returncode, 0)
        self.assertEqual(json.loads(self.qargi("supervise", "hooks", "--qargi", "/opt/q/qargi").stdout)["hooks"]["PreCompact"][0]["hooks"][0]["command"], "/opt/q/qargi hook pre-compact")
        self.assertEqual(os.listdir(os.path.join(self.tmp, "home")), [], "nothing is written to the home directory")


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    os.environ.setdefault("QARGI_STATE", tempfile.mkdtemp())
    unittest.main(warnings="ignore")
