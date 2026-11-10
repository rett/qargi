#!/usr/bin/env python3
"""The time of `qargi marshal status --all --brief --no-fetch` on a project whose remote holds 14 signed records, integrity strict (a
signature verified for each), against its ceiling in tests/startup-budget.txt: the median of 20 runs. Like `role list` the ceiling only
warns (a machine under load is no failure; the count of git and key-tool processes is what tests/test_marshal_batch.sh gates). The records
are built in a hermetic home with the real key tool and git. Offline. Skips when ssh-keygen or git is not installed.
Run: python3 tests/test_marshal_startup.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, shutil, subprocess, sys, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'lib'))
import test_startup as S  # noqa: E402   (its Home, its budget reader and its median; no test of it runs from here)
import marshal_refs as MR  # noqa: E402
import marshal_sign as MS  # noqa: E402

COMMAND = "marshal status --all --brief --no-fetch"
RECORDS = 14


class Ceiling(unittest.TestCase):
    def test_marshal_status_of_14_signed_records_against_its_ceiling(self):
        if not shutil.which("ssh-keygen") or not shutil.which("git"):
            self.skipTest("the signing tests need ssh-keygen and git")
        with open(S.BUDGET) as f:
            ceiling = S.read_budget(f.read())[COMMAND][0]
        h = S.Home("project")
        try:
            def git(*a):
                return subprocess.run(["git", "-C", h.repo] + list(a), check=True, capture_output=True, env=h.env)
            git("init", "-q", ".")
            line = MS.keygen(os.path.join(h.conf, "credentials", "marshal_ed25519"), "lead@host")
            os.makedirs(os.path.join(h.state, "marshal"))
            MS.signers_add(os.path.join(h.state, "marshal", "alpha.signers"), line)
            with open(os.path.join(h.state, "marshal", "alpha.enabled"), "w") as f:
                json.dump({"backend": "refs", "remote": "origin", "enabled_at": "2026-01-01T00:00:00Z", "words": "w", "integrity": "strict"}, f)
            signer = MR.signer_for(h.conf, "alpha")
            self.assertIsNotNone(signer)
            when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            old_env = dict(os.environ)
            os.environ.update(h.env)                                           # marshal_refs.write starts git with the environment it has
            try:
                for i in range(1, RECORDS + 1):
                    name = "feat-%02d" % i
                    rec = {"feature": name, "project": "alpha", "status": "active", "goal": "goal %d" % i, "purpose": "", "plan": "", "note": "",
                           "started": when, "renewed_at": when, "updated_at": when, "finished_at": None, "updated_by": "alice", "rev": 1,
                           "lead": {"id": "alice", "user": "u", "host": "h", "since": when}}
                    git("update-ref", "refs/qargi/features/" + name, MR.write(h.repo, rec, None, "marshal: %s rev 1" % name, signer))
            finally:
                os.environ.clear()
                os.environ.update(old_env)
            argv = COMMAND.split()
            h.env["QARGI_PROJECT"] = "alpha"
            r = h.run(argv)
            self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
            self.assertEqual([l.split()[0] for l in r.stdout.splitlines() if l.endswith("[signed]")], ["feat-%02d" % i for i in range(1, RECORDS + 1)], r.stdout)
            times = []
            for _ in range(S.RUNS):
                t0 = time.perf_counter()
                h.run(argv)
                times.append((time.perf_counter() - t0) * 1000)
        finally:
            h.close()
        got = S.median_ms(times)
        print("startup: qargi %s median %.0f ms over %d runs (ceiling %d ms)%s" % (COMMAND, got, S.RUNS, ceiling, "" if got <= ceiling else
              "\nWARNING: over the ceiling of tests/startup-budget.txt (a loaded machine, or a read of the records got slower: measure it again alone)"),
              file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
