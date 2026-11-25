#!/usr/bin/env python3
"""Run options of a command runtime (dispatch.run_config.options): what binds the prepared request, and that a project with none is untouched.

A project and a profile with no option keep the prepared request they always had: the request of the fake runtime of tests/prepared_request_cases.py is
compared with tests/golden/run-options-request.json, recorded from the head before run options existed (RUN_OPTIONS_RECORD=FILE records it again). With
options the request moves in the bindings the design names and nowhere else: the project's enabled list and the profile's key bind the policy (the
profile's whole entry also binds the selection), an edit of the definition's option binds the runtime and the composition, and taking everything away
gives the first request back, byte for byte. Hermetic and offline: the runtimes are fakes.
Run: python3 tests/test_run_options.py"""
import hermetic  # noqa: F401
import copy
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepared_request_cases as C  # noqa: E402

ROOT = C.ROOT
GOLDEN = ROOT / "tests" / "golden" / "run-options-request.json"
OPTION = {"set": {"features": {"img": True}}, "classes": ["write"], "outside_sandbox": True, "spends": "unknown", "writes": "the files the member saves",
          "phrase": "hosted images run outside the sandbox", "verified_on": None, "source": "a fixture", "note": "a hosted tool"}
BASELINE = {"ask": "never", "features": {"img": False, "other": False}}


def dumps(request):
    return json.dumps(request, sort_keys=True, indent=1) + "\n"


class RunOptions(unittest.TestCase):
    setUp = C.PreparedRequests.setUp
    git = C.PreparedRequests.git
    save_answers = C.PreparedRequests.save_answers
    install = C.PreparedRequests.install
    cmd = C.PreparedRequests.cmd
    prepare = C.PreparedRequests.prepare
    request = C.PreparedRequests.request
    argv = C.PreparedRequests.argv

    def option_runtime(self, option=OPTION):
        """cmdone with a run file (the tool pack's place, a baseline) and an option; the stub gets the file's path."""
        doc = copy.deepcopy(self.definitions["cmdone"])
        doc["resources"] = {"mcp": {"file": "conf.toml", "format": "toml", "root_pointer": "/mcp_servers", "entry": {"url": "{url}"}, "name_key": "nonword-underscore",
                                    "permission_rule": "mcp__{server}__{tool}", "tool_lists": {"allow": "/enabled_tools"}}}
        doc["dispatch"]["argv"] = doc["dispatch"]["argv"] + [{"if": "run_config", "then": ["--cfg", "{run_config}"]}]
        doc["dispatch"]["run_config"] = {"in": "run", "file": "conf.toml", "baseline": copy.deepcopy(BASELINE)}
        if option is not None:
            doc["dispatch"]["run_config"]["options"] = {"img": copy.deepcopy(option)}
        self.install("cmdone", doc)
        return doc

    def enable(self, names=("img",)):
        """The project enabling options for its runtime, as `qargi provider enable --option` stores them (models.run_options.local.RUNTIME)."""
        self.answers["models"]["run_options"] = {"local": {"cmdone": list(names)}} if names else {}
        self.save_answers()

    def profiles(self, **entries):
        self.answers["profiles"] = {k: dict({"base": "worker", "tier": "fast"}, **v) for k, v in entries.items()}
        self.save_answers()

    def binding(self, *args):
        self.prepare(*args)
        return self.request()["binding"]

    def moved(self, old, new):
        return sorted(k for k in old if old[k] != new[k])

    def test_a_project_without_options_has_the_request_it_always_had(self):
        self.prepare()
        text = dumps(self.request())
        if os.environ.get("RUN_OPTIONS_RECORD"):
            Path(os.environ["RUN_OPTIONS_RECORD"]).write_text(text)
            return
        self.assertEqual(text, GOLDEN.read_text(), "the prepared request of a project with no run options moved: a project without them keeps its request byte for byte")

    def test_the_options_bind_the_request_in_the_policy_and_the_selection_and_the_definition(self):
        self.option_runtime(option=None)
        self.profiles(imgs={})
        first = self.binding("--profile", "imgs")
        self.assertEqual(first, self.binding("--profile", "imgs"))
        # the definition declaring an option moves the definition and what is composed of it, and nothing the project said
        self.option_runtime()
        declared = self.binding("--profile", "imgs")
        self.assertEqual(self.moved(first, declared), ["composition", "runtime"])
        # the project enabling it, with no profile selecting it: the policy alone
        self.enable()
        enabled = self.binding("--profile", "imgs")
        self.assertEqual(self.moved(declared, enabled), ["policy"])
        # the profile selecting it: the profile's entry (the selection) and the policy
        self.profiles(imgs={"options": ["img"]})
        selected = self.binding("--profile", "imgs")
        self.assertEqual(self.moved(enabled, selected), ["policy", "selection"])
        self.assertEqual(self.request()["profile"], "imgs")
        # an edit of the option itself: the definition, whatever the project says
        edited = copy.deepcopy(OPTION)
        edited["note"] = "another note"
        self.option_runtime(edited)
        self.assertEqual(self.moved(selected, self.binding("--profile", "imgs")), ["composition", "runtime"])
        # and taking everything away gives the first request back, byte for byte
        self.option_runtime(option=None)
        self.enable(())
        self.profiles(imgs={})
        again = self.binding("--profile", "imgs")
        self.assertEqual(again, first)

    def test_the_request_of_a_profile_that_selects_nothing_does_not_know_the_options_of_the_project(self):
        self.option_runtime()
        self.profiles(imgs={"options": ["img"]}, plain={})
        self.enable()
        self.prepare("--profile", "plain")
        plain = self.request()
        self.assertEqual(plain["profile"], "plain")
        out = self.prepare("--profile", "imgs")
        self.assertIn("RUN_OPTIONS=img (hosted, outside the sandbox, may spend)\n", out)
        self.assertNotIn("RUN_OPTIONS", self.prepare("--profile", "plain"))

    def test_a_run_gets_the_baseline_with_the_options_of_its_profile_applied(self):
        import tomllib
        self.option_runtime()
        self.profiles(imgs={"options": ["img"]}, plain={})
        self.enable()
        self.prepare("--profile", "imgs")
        self.assertIn("RUN_CONFIG_OPTIONS=" + json.dumps({"img": {"features": {"img": True}}}, separators=(",", ":")), self.cmd("local", "run", self.run, "--dry-run"))
        self.argv()
        self.assertEqual(tomllib.loads((self.run / "config/conf.toml").read_text()), {"ask": "never", "features": {"img": True, "other": False}})
        rec = json.loads((self.run / "dispatch.json").read_text())
        self.assertEqual(rec["run_config"]["options"], ["img"])
        self.assertEqual(rec["run_config"]["baseline"], BASELINE)                     # the definition's baseline, as it is
        self.prepare("--profile", "plain")
        self.argv()
        self.assertEqual(tomllib.loads((self.run / "config/conf.toml").read_text()), BASELINE)
        self.assertNotIn("options", json.loads((self.run / "dispatch.json").read_text())["run_config"])

    def test_a_read_only_run_with_an_option_is_refused_before_anything_is_made(self):
        self.option_runtime()
        self.profiles(imgs={"options": ["img"]}, spy={"base": "reviewer", "options": ["img"]})
        self.enable()
        before = sorted(p.name for p in self.root.iterdir())
        out = self.cmd("local", "prepare", "--repo", self.repo, "--base", "main", "--slug", "ro", "--scratch", self.root, "--role", "review", "--profile", "spy", code=1)
        self.assertIn('"code":"runtime-option-class"', out)
        self.assertIn("the option img of the runtime cmdone is for write runs, and this run is read-only", out)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_a_profile_may_only_select_what_the_project_enabled_and_the_definition_declares(self):
        self.option_runtime()
        self.profiles(imgs={"options": ["img"]})
        out = self.cmd("local", "prepare", "--repo", self.repo, "--base", "main", "--slug", "ne", "--scratch", self.root, "--profile", "imgs", code=2)
        self.assertIn("the profile imgs selects the option img, which project demo has not enabled for the runtime cmdone", out)
        self.option_runtime(option=None)
        self.enable()
        out = self.cmd("local", "prepare", "--repo", self.repo, "--base", "main", "--slug", "nd", "--scratch", self.root, "--profile", "imgs", code=2)
        self.assertIn("the definition of the runtime cmdone declares no option img", out)


if __name__ == "__main__":
    unittest.main()
