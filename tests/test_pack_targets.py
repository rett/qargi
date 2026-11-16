#!/usr/bin/env python3
"""Explicit local render targets, with two fake eligible runtimes and isolated source/config/checkout fixtures."""
import hermetic  # noqa: F401
import contextlib
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import packs_check as C
import packs_audit as A
import provider as P


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class Targets(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="targets."))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.tool = self.tmp / "tool"
        self.tool.mkdir()
        for name in hermetic.TOOL_DIRS:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, self.tool / name, ignore=shutil.ignore_patterns("__pycache__"))
            elif src.exists():
                shutil.copy2(src, self.tool / name)
        self.conf, self.state, self.repo = (self.tmp / x for x in ("conf", "state", "repo"))
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.env = dict(os.environ, QARGI_CONF=str(self.conf), QARGI_STATE=str(self.state))
        self.providers = self.tool / "lib" / "providers"
        self.base = json.loads((self.providers / "claude-code.json").read_text())
        self.base["resources"].pop("contract_addenda", None)
        self.runtime("first", ".first")
        self.runtime("second", ".second")
        self.answers = {"schema": 1, "project": "alpha", "repo": {"path": str(self.repo)},
                        "models": {"provider": {"local": "first", "cloud": "claude-platform"}},
                        "roles": {"build": {}, "review": {}, "lead": {}}}
        self.save_answers()
        self.links = []
        self.pack("shared", ["any"])
        self.pack("first-only", ["first"])
        self.pack("second-only", ["second"])
        self.pack("operator", ["any"], role="lead")
        self.pack("remote", ["second"], kind="tool", role="review")
        self.pack("lead-tool", ["any"], kind="tool", role="lead")

    def runtime(self, name, directory, target=None):
        doc = copy.deepcopy(self.base)
        doc["provider"] = name
        doc["session"] = {"render_target": target or name + "-view"}
        doc["resources"]["skills"]["project_dir"] = directory + "/skills"
        doc["resources"]["skills"]["user_dir"] = "~/" + directory + "/skills"
        doc["resources"]["settings"]["files"] = [{"scope": "project", "path": directory + "/settings.json"},
                                                  {"scope": "project-local", "path": directory + "/settings.local.json"},
                                                  {"scope": "user", "path": "~/" + directory + "/settings.json"}]
        # Exercise the existing per-role MCP policy as well as target-specific pack compatibility.
        doc["resources"]["mcp"]["tool_lists"] = {"allow": "/enabled_tools"}
        put(self.providers / (name + ".json"), doc)
        return doc

    def save_answers(self, project="alpha"):
        put(self.conf / "projects" / (project + ".json"), self.answers | {"project": project})

    def pack(self, name, compatible, kind="skill", role=None):
        path = self.conf / "packs" / ("skills" if kind == "skill" else "tools") / (name if kind == "skill" else name + ".json")
        if kind == "skill":
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Guidance for {name}.\n---\nRead the source.\n")
            record = path / ".pack.json"
        else:
            put(path, {"name": name, "url": "https://mcp.example.net/", "write_ok": True,
                       "tools": {"lookup": "always_allow", "deleteItem": "auto", "ask": "always_ask"}})
            record = path.with_suffix(".pack.json")
        put(record, {"compatible_providers": compatible})
        put(record, {"compatible_providers": compatible, "sha256": C.content_hash(str(path))})
        self.links.append({"pack": kind + ":" + name, "scope": "project-role" if role else "project", "project": "alpha", **({"role": role} if role else {})})
        put(self.conf / "packs" / "links.json", {"links": self.links})

    def cli(self, *args, ok=True):
        p = subprocess.run([str(self.tool / "bin" / "qargi"), *args], env=self.env, cwd=self.repo,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout)
            self.assertNotIn("plan token:", p.stdout)
        return p.stdout

    def token(self, *args):
        text = self.cli(*args)
        match = re.search(r"^plan token: ([0-9a-f]+)", text, re.M)
        self.assertIsNotNone(match, text)
        return match[1]

    def apply(self, *args):
        return self.cli(*args, "--plan", self.token(*args), "--approved", "fixture approval")

    def render(self, runtime="second", project="alpha"):
        return ("packs", "apply", project, "--target", runtime + "-view")

    def live(self, runtime="second", project="alpha"):
        return self.state / "render" / project / runtime

    def manifest(self, runtime="second", project="alpha"):
        return json.loads((self.live(runtime, project) / "MANIFEST.json").read_text())

    def outside(self, rt="second", user=False):
        base = Path(self.env["HOME"]) if user else self.repo
        path = base / ("." + rt) / "skills" / "outside"
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text("---\nname: outside\ndescription: Outside guidance.\n---\nRead carefully.\n")
        return path

    def test_owned_teardown_after_drift_and_corruption(self):
        for rt in ("first", "second"):
            with self.subTest(runtime=rt):
                dest = self.repo / ("." + rt) / "skills"
                dest.mkdir(parents=True)
                (dest / "keep.txt").write_text("owner content")
                if rt == "first":
                    doc = json.loads((self.providers / "first.json").read_text())
                    doc["resources"]["agents"]["link"]["project"] = "dir-symlink"
                    put(self.providers / "first.json", doc)
                self.apply(*self.render(rt))
                self.apply("packs", "link", "alpha", "--target", rt + "-view")
                if rt == "first":
                    members = Path(str(self.live(rt)) + ".agents")
                    members.mkdir()
                    (members / "fixture.md").write_text("Fixture member")
                    self.apply("project", "link", "alpha", "--resource", "agents")
                doc = json.loads((self.providers / (rt + ".json")).read_text())
                doc["description"] += " changed"
                put(self.providers / (rt + ".json"), doc)
                self.cli("packs", "link", "alpha", "--target", rt + "-view", ok=False)
                if rt == "second":
                    (self.live(rt) / "MANIFEST.json").write_text("{")
                    self.cli(*self.render(rt), ok=False)
                    self.cli("packs", "check", "alpha", "--target", rt + "-view", ok=False)
                args = (("project", "unlink", "alpha", "--resource", "skills,agents") if rt == "first" else
                        ("packs", "unlink", "alpha", "--target", rt + "-view"))
                self.apply(*args)
                if rt == "first":
                    self.assertFalse((self.repo / ".claude" / "agents" / "fixture.md").exists())
                    args = ("project", "unlink", "alpha", "--resource", "skills")
                self.assertEqual((dest / "keep.txt").read_text(), "owner content")
                self.assertFalse(dest.is_symlink())
                # Backup-only crash recovery uses the same engine guards even with an unusable render.
                backup = dest.with_name("skills.qargi-backup")
                dest.rename(backup)
                self.apply(*args)
                self.assertEqual((dest / "keep.txt").read_text(), "owner content")
                shutil.rmtree(dest)
                dest.symlink_to(self.repo)
                self.cli(*args, ok=False)
                self.assertEqual(dest.resolve(), self.repo)

    def test_default_packs_unlink_after_composition_change(self):
        self.apply(*self.render("first"))
        self.apply("packs", "link", "alpha")
        doc = json.loads((self.providers / "first.json").read_text())
        doc["description"] += " changed"
        put(self.providers / "first.json", doc)
        self.apply("packs", "unlink", "alpha")
        self.assertFalse((self.repo / ".first" / "skills").exists())

    def test_default_corrupt_manifest_refuses_loading_but_allows_owned_unlink(self):
        self.apply(*self.render("first"))
        self.apply("packs", "link", "alpha")
        (self.live("first") / "MANIFEST.json").write_text("{")
        self.cli("packs", "link", "alpha", ok=False)
        self.cli("packs", "check", "alpha", "--target", "first-view", ok=False)
        self.apply("packs", "unlink", "alpha")
        # A fresh render repairs by rebuilding from vetted source, rather than loading corrupt render content.
        self.apply(*self.render("first"))
        self.apply("packs", "link", "alpha")

    def test_revoke_after_capability_and_layout_loss(self):
        original = json.loads((self.providers / "second.json").read_text())
        for user in (False, True):
            for loss in ("verification", "support", "layout"):
                with self.subTest(user=user, loss=loss):
                    doc = copy.deepcopy(original)
                    put(self.providers / "second.json", doc)
                    put(self.conf / "packs" / "accepted.json", {"schema": 1, "user": {}, "projects": {}})
                    for rt in ("first", "second"):
                        self.outside(rt, user)
                        self.apply("skill", "accept", "alpha", "outside", "--target", rt + "-view", *(["--user"] if user else []))
                    accepted = self.conf / "packs" / "accepted.json"
                    before = json.loads(accepted.read_text())
                    bad = copy.deepcopy(doc)
                    if loss == "layout":
                        bad["resources"]["skills"].pop("project_dir")
                    else:
                        bad["capabilities"]["skills"].update({"verified_on": None} if loss == "verification" else {"value": "no"})
                    put(self.providers / "second.json", bad)
                    flags = ["--target", "second-view", *(["--user"] if user else [])]
                    self.cli("skill", "accept", "alpha", "outside", *flags, ok=False)
                    self.apply("skill", "unaccept", "alpha", "outside", *flags)
                    after = json.loads(accepted.read_text())
                    old = before["user"] if user else before["projects"]["alpha"]
                    new = after["user"] if user else after["projects"]["alpha"]
                    self.assertEqual(new, {k: v for k, v in old.items() if v["provider"] != "second"})
                    put(self.providers / "second.json", doc)
                    self.apply("skill", "unaccept", "alpha", "outside", "--target", "first-view", *(["--user"] if user else []))

    def test_accept_token_binds_same_provider_composition(self):
        self.outside()
        args = ("skill", "accept", "alpha", "outside", "--target", "second-view")
        token = self.token(*args)
        doc = json.loads((self.providers / "second.json").read_text())
        doc["description"] += " changed"
        put(self.providers / "second.json", doc)
        self.cli(*args, "--plan", token, "--approved", "fixture", ok=False)

    def test_accept_token_binds_same_provider_target(self):
        self.outside()
        args = ("skill", "accept", "alpha", "outside", "--target", "second-view")
        token = self.token(*args)
        doc = json.loads((self.providers / "second.json").read_text())
        doc["session"]["render_target"] = "renamed-view"
        put(self.providers / "second.json", doc)
        self.cli(*args[:-1], "renamed-view", "--plan", token, "--approved", "fixture", ok=False)

    def test_revoke_token_binds_exact_record_and_scope(self):
        self.outside()
        self.apply("skill", "accept", "alpha", "outside", "--target", "second-view")
        args = ("skill", "unaccept", "alpha", "outside", "--target", "second-view")
        token = self.token(*args)
        accepted = self.conf / "packs" / "accepted.json"
        data = json.loads(accepted.read_text())
        data["projects"]["alpha"]["outside"]["approved"] = "replacement authorization"
        put(accepted, data)
        self.cli(*args, "--plan", token, "--approved", "fixture", ok=False)
        self.assertEqual(json.loads(accepted.read_text()), data)
        self.apply(*args)

    def test_revoke_refuses_removed_ambiguous_identity_and_foreign_slot(self):
        self.outside()
        self.apply("skill", "accept", "alpha", "outside", "--target", "second-view")
        args = ("skill", "unaccept", "alpha", "outside", "--target", "second-view")
        accepted = self.conf / "packs" / "accepted.json"
        before = accepted.read_bytes()
        self.runtime("duplicate", ".duplicate", "second-view")
        self.cli(*args, ok=False)
        (self.providers / "duplicate.json").unlink()
        doc = (self.providers / "second.json").read_text()
        (self.providers / "second.json").unlink()
        self.cli(*args, ok=False)
        self.assertEqual(accepted.read_bytes(), before)
        (self.providers / "second.json").write_text(doc)
        data = json.loads(before)
        record = data["projects"]["alpha"].pop("outside")
        data["projects"]["alpha"]["skills/second/outside"] = record | {"provider": "first"}
        put(accepted, data)
        self.cli(*args, ok=False)
        self.assertEqual(json.loads(accepted.read_text()), data)

    def test_missing_approval_never_grants_tools(self):
        # Exercise rendering itself, beyond the member selector: either role can receive this pack on either runtime.
        for rt in ("first", "second"):
            for role in ("build", "review"):
                for approval in (None, ""):
                    with self.subTest(runtime=rt, role=role, approval=approval):
                        links = [{"pack": "tool:remote", "scope": "project-role", "project": "alpha", "role": role}]
                        put(self.conf / "packs" / "links.json", {"links": links})
                        record = {"compatible_providers": ["any"]}
                        if approval is not None:
                            record["sha256"] = approval
                        put(self.conf / "packs" / "tools" / "remote.pack.json", record)
                        self.apply(*self.render(rt))
                        path = self.live(rt) / "mcp.json"
                        servers = json.loads(path.read_text())["mcpServers"] if path.exists() else {}
                        self.assertNotIn("remote", servers)  # an empty allow list can mean unrestricted access to a runtime

    def test_skill_render_requires_prior_library_approval(self):
        for rt in ("first", "second"):
            for role in ("lead", "build"):
                with self.subTest(runtime=rt, role=role):
                    name = "operator" if role == "lead" else "shared"
                    path = self.conf / "packs" / "skills" / name
                    record = path / ".pack.json"
                    original = record.read_bytes()
                    put(self.conf / "packs" / "links.json", {"links": [
                        {"pack": "skill:" + name, "scope": "project-role", "project": "alpha", "role": role}]})
                    approved_token = self.token(*self.render(rt))
                    self.cli(*self.render(rt), "--plan", approved_token, "--approved", "fixture approval")
                    before = {str(p.relative_to(self.live(rt))): p.read_bytes()
                              for p in self.live(rt).rglob("*") if p.is_file()}
                    # Retain valid front matter and compatibility: review still passes after this content change.
                    skill = path / "SKILL.md"
                    content = skill.read_text()
                    for changed in (False, True):
                        skill.write_text(content + ("More valid guidance.\n" if changed else ""))
                        for approval in (None, ""):
                            rec = {"compatible_providers": ["any"]}
                            if approval is not None:
                                rec["sha256"] = approval
                            put(record, rec)
                            self.assertEqual(C.review("skill", str(path), C.compat_of(str(path)))[1], 0)
                            args = self.render(rt)
                            refused = self.cli(*args, ok=False)
                            self.assertIn("no content approval", refused)
                            # Render authorization cannot serve as the missing prior library approval.
                            self.assertIn("no content approval", self.cli(*args, "--plan", approved_token,
                                "--approved", "fixture render approval", ok=False))
                            self.assertEqual(before, {str(p.relative_to(self.live(rt))): p.read_bytes()
                                                     for p in self.live(rt).rglob("*") if p.is_file()})
                    record.write_bytes(original)
                    self.assertIn("library drift", self.cli(*self.render(rt), ok=False))
                    self.assertEqual(before, {str(p.relative_to(self.live(rt))): p.read_bytes()
                                             for p in self.live(rt).rglob("*") if p.is_file()})
                    put(record, {"compatible_providers": ["any"], "sha256": C.content_hash(str(path))})
                    self.apply(*self.render(rt))
                    self.assertEqual((self.live(rt) / ("." + rt) / "skills" / name / "SKILL.md").read_text(),
                                     skill.read_text())
                    skill.write_text(content)
                    record.write_bytes(original)

    @contextlib.contextmanager
    def cleanup_fixture(self, rt, rel=None):
        """Restore each scenario even when a subtest fails, so refusals cannot cascade into fixture errors."""
        record = self.conf / "packs" / "skills" / "shared" / ".pack.json"
        approved = record.read_bytes()
        try:
            yield
        finally:
            record.write_bytes(approved)
            directory = self.conf / "packs" / "providers" / rt
            if directory.exists():
                shutil.rmtree(directory)
            self.runtime(rt, "." + rt)
            dest = self.repo / (rel or ("." + rt + "/skills"))
            for path in (dest, dest.with_name("skills.qargi-backup")):
                if path.is_symlink():
                    path.unlink()
                elif path.exists():
                    shutil.rmtree(path)

    def test_cleanup_after_skills_verification_or_support_loss(self):
        for route in ("default", "secondary", "combined"):
            for loss in ("verification", "support", "reseal"):
                rt = "second" if route == "secondary" else "first"
                with self.subTest(route=route, loss=loss), self.cleanup_fixture(rt):
                    shipped = self.providers / (rt + ".json")
                    doc = json.loads(shipped.read_text())
                    shipped.unlink()
                    directory = self.conf / "packs" / "providers" / rt
                    definition = directory / "definition.json"
                    put(definition, doc)
                    seal = directory / ".pack.json"
                    put(seal, {"sealed": True, "sha256": P.tree_hash(str(directory))})
                    verified = self.state / "providers" / rt / "verified.json"
                    put(verified, {"skills": {"hash": P.definition_hash(rt, root=str(self.providers),
                        library=str(self.conf / "packs" / "providers")), "by": "conformance", "at": "fixture"}})
                    dest = self.repo / ("." + rt) / "skills"
                    dest.mkdir(parents=True)
                    (dest / "keep.txt").write_text("owner content")
                    target = ("--target", rt + "-view") if route == "secondary" else ()
                    link = ("project" if route == "combined" else "packs", "link", "alpha", *target)
                    unlink = (link[0], "unlink", "alpha", *target)
                    self.apply(*self.render(rt))
                    self.apply(*link)
                    if loss == "verification":
                        verified.unlink()
                    else:
                        if loss == "support":
                            doc["capabilities"]["skills"]["value"] = "no"
                        else:
                            doc["description"] += " harmless reseal"
                        put(definition, doc)
                        put(seal, {"sealed": True, "sha256": P.tree_hash(str(directory))})
                    self.assertIn("no skills support", self.cli(*self.render(rt), ok=False))
                    self.cli("packs", "check", "alpha", "--target", rt + "-view", ok=False)
                    self.cli(*link, ok=False)
                    # Corrupt linked pack records must not become cleanup authorization gates either.
                    library_record = self.conf / "packs" / "skills" / "shared" / ".pack.json"
                    old_record = library_record.read_bytes()
                    library_record.write_text("{")
                    self.apply(*unlink)
                    self.assertFalse(dest.is_symlink())
                    self.assertEqual((dest / "keep.txt").read_text(), "owner content")
                    backup = dest.with_name("skills.qargi-backup")
                    dest.rename(backup)
                    self.apply(*unlink)
                    self.assertEqual((dest / "keep.txt").read_text(), "owner content")
                    shutil.rmtree(dest)
                    dest.symlink_to(self.repo)
                    # Explicit selection requires a refusal; combined selection must leave foreign links alone.
                    foreign_args = (*unlink, "--resource", "skills") if route == "combined" else unlink
                    self.cli(*foreign_args, ok=False)
                    self.assertEqual(dest.resolve(), self.repo)
                    dest.unlink()
                    library_record.write_bytes(old_record)

    def test_cleanup_refuses_unresolved_identity_and_unsafe_layout(self):
        rt = "second"
        shipped = self.providers / "second.json"
        doc = json.loads(shipped.read_text())
        shipped.unlink()
        directory = self.conf / "packs" / "providers" / rt
        definition = directory / "definition.json"
        seal = directory / ".pack.json"
        put(definition, doc)
        put(seal, {"sealed": True, "sha256": P.tree_hash(str(directory))})
        put(self.state / "providers" / rt / "verified.json", {"skills": {
            "hash": P.definition_hash(rt, root=str(self.providers), library=str(self.conf / "packs" / "providers")),
            "by": "conformance", "at": "fixture"}})
        self.apply(*self.render(rt))
        self.apply("packs", "link", "alpha", "--target", "second-view")
        dest = self.repo / ".second" / "skills"
        source = dest.readlink()
        args = ("packs", "unlink", "alpha", "--target", "second-view")
        for case in ("missing", "unsealed", "drifted", "ambiguous", "path", "mode"):
            with self.subTest(case=case):
                bad = copy.deepcopy(doc)
                if case == "missing":
                    definition.unlink()
                elif case == "unsealed":
                    seal.unlink()
                elif case == "drifted":
                    (directory / "extra").write_text("unapproved change")
                elif case == "ambiguous":
                    self.runtime("duplicate", ".duplicate", "second-view")
                else:
                    if case == "path":
                        bad["resources"]["skills"]["project_dir"] = "../unsafe/skills"
                    else:
                        bad["resources"]["skills"]["link"]["project"] = "none"
                    put(definition, bad)
                    put(seal, {"sealed": True, "sha256": P.tree_hash(str(directory))})
                self.cli(*args, ok=False)
                self.assertEqual(dest.readlink(), source)
                for extra in (directory / "extra", self.providers / "duplicate.json"):
                    if extra.exists():
                        extra.unlink()
                put(definition, doc)
                put(seal, {"sealed": True, "sha256": P.tree_hash(str(directory))})
        self.apply(*args)

    def test_cleanup_keeps_sealed_extension_layout_without_verification(self):
        for rt in ("first", "second"):
            doc = json.loads((self.providers / (rt + ".json")).read_text())
            doc["capabilities"].pop("skills")
            doc["resources"].pop("skills")
            doc["resources"].pop("settings")
            put(self.providers / (rt + ".json"), doc)
        self.extension()
        self.answers["models"]["extensions"] = ["addon"]
        self.save_answers()
        for rt in ("first", "second"):
            with self.subTest(runtime=rt):
                verified = self.state / "providers" / "addon" / "verified.json"
                h = P.extension_hash("addon", rt, "local", root=str(self.providers), library=str(self.conf / "packs" / "providers"))
                put(verified, {"skills": {"hash": h, "by": "conformance", "at": "fixture"}})
                dest = self.repo / ".extended" / "skills"
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "keep.txt").write_text("extension owner content")
                self.apply(*self.render(rt))
                link = ("packs", "link", "alpha", "--target", rt + "-view")
                self.apply(*link)
                verified.unlink()
                self.cli(*self.render(rt), ok=False)
                self.cli(*link, ok=False)
                # The default combined route and explicit secondary route must resolve the same extension path.
                args = (("project", "unlink", "alpha", "--resource", "skills") if rt == "first" else
                        ("packs", "unlink", "alpha", "--target", rt + "-view"))
                self.apply(*args)
                self.assertEqual((dest / "keep.txt").read_text(), "extension owner content")

    def test_cleanup_skips_skills_verification_in_extension_requirements(self):
        for rt in ("first", "second"):
            doc = json.loads((self.providers / (rt + ".json")).read_text())
            doc["resources"].pop("skills")
            doc["resources"].pop("settings")
            put(self.providers / (rt + ".json"), doc)
        # This extension owns the safe layout but requires the base's verified skills capability for fresh loading.
        adds = {"resources": {k: copy.deepcopy(self.base["resources"][k]) for k in ("skills", "settings")}}
        adds["resources"]["skills"]["project_dir"] = ".required/skills"
        self.extension(provides=[], adds=adds, requires={"capabilities": ["skills"]})
        self.answers["models"]["extensions"] = ["addon"]
        self.save_answers()
        for rt in ("first", "second"):
            with self.subTest(runtime=rt), self.cleanup_fixture(rt, ".required/skills"):
                self.apply(*self.render(rt))
                link = ("packs", "link", "alpha", "--target", rt + "-view")
                self.apply(*link)
                doc = json.loads((self.providers / (rt + ".json")).read_text())
                doc["capabilities"]["skills"]["value"] = "no"
                put(self.providers / (rt + ".json"), doc)
                self.cli(*self.render(rt), ok=False)
                self.cli(*link, ok=False)
                args = (("project", "unlink", "alpha", "--resource", "skills") if rt == "first" else
                        ("packs", "unlink", "alpha", "--target", rt + "-view"))
                self.apply(*args)
                self.assertFalse((self.repo / ".required" / "skills").exists())

    def test_default_unlink_preserves_legacy_optional_link_mode(self):
        for mode in (None, "copy"):
            with self.subTest(mode=mode), self.cleanup_fixture("first"):
                path = self.providers / "first.json"
                doc = json.loads(path.read_text())
                if mode is None:
                    doc["resources"]["skills"]["link"].pop("project")
                else:
                    doc["resources"]["skills"]["link"]["project"] = mode
                put(path, doc)
                dest = self.repo / ".first" / "skills"
                dest.mkdir(parents=True)
                (dest / "keep.txt").write_text("legacy owner content")
                self.apply(*self.render("first"))
                self.apply("packs", "link", "alpha")
                self.assertTrue(dest.is_symlink())
                self.apply("packs", "unlink", "alpha")
                self.assertFalse(dest.is_symlink())
                self.assertEqual((dest / "keep.txt").read_text(), "legacy owner content")

    def test_default_unlink_after_optional_render_target_is_removed(self):
        dest = self.repo / ".first" / "skills"
        dest.mkdir(parents=True)
        (dest / "keep.txt").write_text("owner content")
        self.apply(*self.render("first"))
        self.apply("packs", "link", "alpha")
        path = self.providers / "first.json"
        doc = json.loads(path.read_text())
        doc["session"].pop("render_target")
        put(path, doc)
        self.apply("packs", "unlink", "alpha")
        self.assertFalse(dest.is_symlink())
        self.assertEqual((dest / "keep.txt").read_text(), "owner content")

    def test_combined_unlink_without_render_target_still_removes_agents(self):
        path = self.providers / "first.json"
        doc = json.loads(path.read_text())
        doc["session"].pop("render_target")
        doc["resources"]["agents"]["link"]["project"] = "dir-symlink"
        put(path, doc)
        members = Path(str(self.live("first")) + ".agents")
        members.mkdir(parents=True)
        (members / "fixture.md").write_text("Fixture member")
        dest = self.repo / doc["resources"]["agents"]["project_dir"]
        self.apply("project", "link", "alpha", "--resource", "agents")
        self.assertTrue(dest.is_symlink())
        self.apply("project", "unlink", "alpha")
        self.assertFalse(dest.exists())
        self.assertTrue((members / "fixture.md").is_file())

    def test_cleanup_after_reseal_with_non_skills_capability_requirement(self):
        for rt in ("first", "second"):
            with self.subTest(runtime=rt), self.cleanup_fixture(rt, ".required/skills"):
                path = self.providers / (rt + ".json")
                doc = json.loads(path.read_text())
                path.unlink()
                doc["resources"].pop("skills")
                doc["resources"].pop("settings")
                directory = self.conf / "packs" / "providers" / rt
                definition = directory / "definition.json"
                seal = directory / ".pack.json"
                put(definition, doc)
                put(seal, {"sealed": True, "sha256": P.tree_hash(str(directory))})
                digest = P.definition_hash(rt, root=str(self.providers),
                                           library=str(self.conf / "packs" / "providers"))
                put(self.state / "providers" / rt / "verified.json", {
                    capability: {"hash": digest, "by": "conformance", "at": "fixture"}
                    for capability in ("skills", "mcp")})
                adds = {"resources": {
                    key: copy.deepcopy(self.base["resources"][key]) for key in ("skills", "settings")}}
                adds["resources"]["skills"]["project_dir"] = ".required/skills"
                self.extension(provides=[], adds=adds, requires={"capabilities": ["mcp"]})
                self.answers["models"]["extensions"] = ["addon"]
                self.save_answers()
                dest = self.repo / ".required" / "skills"
                dest.mkdir(parents=True)
                (dest / "keep.txt").write_text("extension owner content")
                self.apply(*self.render(rt))
                self.apply("packs", "link", "alpha", "--target", rt + "-view")
                doc["description"] += " harmless reseal"
                put(definition, doc)
                put(seal, {"sealed": True, "sha256": P.tree_hash(str(directory))})
                refusal = self.cli(*self.render(rt), ok=False)
                self.assertIn("no skills support" if rt == "first" else "needs mcp", refusal)
                args = (("project", "unlink", "alpha", "--resource", "skills") if rt == "first" else
                        ("packs", "unlink", "alpha", "--target", rt + "-view"))
                self.apply(*args)
                self.assertFalse(dest.is_symlink())
                self.assertEqual((dest / "keep.txt").read_text(), "extension owner content")

    def extension(self, name="addon", **updates):
        doc = {"schema": 2, "kind": "extension", "extension": name, "description": "Shared skills extension",
               "extends": self.base["family"], "surface": "local", "provides": ["skills"],
               "adds": {"capabilities": {"skills": {"value": "yes", "note": "fixture"}},
                        "resources": {"skills": copy.deepcopy(self.base["resources"]["skills"]),
                                      "settings": copy.deepcopy(self.base["resources"]["settings"])}}}
        doc["adds"]["resources"]["skills"].update(project_dir=".extended/skills", user_dir="~/.extended/skills")
        doc["adds"]["resources"]["settings"]["files"] = [{"scope": s, "path": p} for s, p in
              (("project", ".extended/settings.json"), ("project-local", ".extended/settings.local.json"),
               ("user", "~/.extended/settings.json"))]
        doc.update(updates)
        directory = self.conf / "packs" / "providers" / name
        put(directory / "definition.json", doc)
        put(directory / ".pack.json", {"sealed": True, "sha256": P.tree_hash(str(directory))})
        return directory

    def test_secondary_extension_context_and_qualification(self):
        for rt in ("first", "second"):
            doc = json.loads((self.providers / (rt + ".json")).read_text())
            doc["capabilities"].pop("skills")
            doc["resources"].pop("skills")
            doc["resources"].pop("settings")
            put(self.providers / (rt + ".json"), doc)
        directory = self.extension()
        self.answers["models"]["extensions"] = ["addon"]
        self.save_answers()
        # Records are bound to each fake base in turn; no qualification calls or claims about a real runtime.
        for rt in ("first", "second"):
            with self.subTest(runtime=rt):
                h = P.extension_hash("addon", rt, "local", root=str(self.providers), library=str(self.conf / "packs" / "providers"))
                put(self.state / "providers" / "addon" / "verified.json", {"skills": {"hash": h, "by": "conformance", "at": "fixture"}})
                self.outside("extended")
                put(self.repo / ".extended" / "settings.json", {"skillOverrides": {"outside": "off"}})
                self.assertIn("skills=.extended/skills", self.cli(*self.render(rt)))
                self.apply(*self.render(rt))
                files = next(p["files"] for p in self.manifest(rt)["packs"] if p["name"] == "shared")
                self.assertIn(".extended/skills/shared/SKILL.md", files)
                self.assertRegex(self.cli("packs", "check", "alpha", "--target", rt + "-view"), r"excluded\s+outside")
                args = ("packs", "link", "alpha", "--target", rt + "-view")
                self.apply(*args)
                self.assertEqual((self.repo / ".extended" / "skills").resolve(), self.live(rt) / ".extended" / "skills")
                self.apply("packs", "unlink", "alpha", "--target", rt + "-view")
        (self.state / "providers" / "addon" / "verified.json").unlink()
        self.cli(*self.render(), ok=False)
        (directory / ".pack.json").unlink()
        self.cli(*self.render(), ok=False)
        put(directory / ".pack.json", {"sealed": True, "sha256": P.tree_hash(str(directory))})
        (directory / "extra").write_text("drift")
        self.cli(*self.render(), ok=False)
        (directory / "extra").unlink()
        self.extension(extends="first")
        self.assertIn("extensions do not apply", self.cli(*self.render(), ok=False))
        self.extension(requires={"resources": ["transcripts"]})
        # Remove a genuinely known required resource, so refusal exercises unmet requirements rather than schema validation.
        doc = json.loads((self.providers / "second.json").read_text())
        doc["resources"].pop("transcripts", None)
        put(self.providers / "second.json", doc)
        self.assertIn("needs the transcripts resource", self.cli(*self.render(), ok=False))
        self.extension()
        self.extension("collision")
        self.answers["models"]["extensions"] = ["addon", "collision"]
        self.save_answers()
        self.assertIn("both add", self.cli(*self.render(), ok=False))

    def test_side_by_side_render_check_link_unlink_and_member_defaults(self):
        original = (self.conf / "projects" / "alpha.json").read_bytes()
        for rt in ("first", "second"):
            plan = self.cli(*self.render(rt))
            self.assertIn(f"runtime: {rt}; project: alpha; target: {rt}-view", plan)
            self.assertIn(f"resources: skills=.{rt}/skills", plan)
            self.assertIn(f"skipped skill {'second' if rt == 'first' else 'first'}-only", plan)
            self.apply(*self.render(rt))
            m = self.manifest(rt)
            self.assertEqual((m["runtime"], m["target"]), (rt, rt + "-view"))
            self.assertEqual({p["name"] for p in m["packs"]}, {"shared", rt + "-only", "operator"} | ({"remote"} if rt == "second" else set()))
            self.cli("packs", "check", "alpha", "--target", rt + "-view")
            self.apply("packs", "link", "alpha", "--target", rt + "-view")
            self.assertEqual((self.repo / ("." + rt) / "skills").resolve(), self.live(rt) / ("." + rt) / "skills")
        data = json.loads((self.live() / "mcp.json").read_text())
        self.assertEqual(data["mcpServers"]["remote"]["enabled_tools"], ["lookup"])
        self.assertNotIn("lead-tool", data["mcpServers"])
        # The default routes still use the member runtime, including the combined project linker.
        self.assertIn("already linked", self.cli("packs", "link", "alpha"))
        self.assertIn("already linked", self.cli("project", "link", "alpha", "--resource", "skills"))
        self.cli("packs", "check", "alpha", ok=False)
        self.cli("packs", "apply", "alpha", ok=False)  # omitted target still selects the cloud verb
        self.apply("packs", "unlink", "alpha", "--target", "second-view")
        self.assertFalse((self.repo / ".second" / "skills").exists())
        self.assertTrue((self.repo / ".first" / "skills").is_symlink())
        self.apply("packs", "unlink", "alpha")
        self.assertEqual((self.conf / "projects" / "alpha.json").read_bytes(), original)

    def test_secondary_render_does_not_require_member_runtime_equality(self):
        self.apply(*self.render())
        self.assertEqual(self.manifest()["runtime"], "second")
        self.assertEqual(json.loads((self.conf / "projects" / "alpha.json").read_text())["models"]["provider"]["local"], "first")

    def test_target_specific_acceptance_and_unowned_legacy_records(self):
        for rt in ("first", "second"):
            path = self.repo / ("." + rt) / "skills" / "outside"
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text("---\nname: outside\ndescription: Outside guidance.\n---\nRead carefully.\n")
        accepted = self.conf / "packs" / "accepted.json"
        unowned_hash = A.strict_hash(str(self.repo / ".first" / "skills" / "outside"))
        put(accepted, {"schema": 1, "user": {"outside": {"sha256": unowned_hash}}, "projects": {}})
        self.assertRegex(self.cli("packs", "check", "alpha", "--target", "first-view"), r"unmanaged\s+outside")
        self.assertIn("unmanaged", self.cli("packs", "check", "alpha", "--target", "second-view"))
        first_token = self.token("skill", "accept", "alpha", "outside", "--target", "first-view")
        self.cli("skill", "accept", "alpha", "outside", "--target", "second-view", "--plan", first_token, "--approved", "fixture", ok=False)
        for rt in ("first", "second"):
            self.apply("skill", "accept", "alpha", "outside", "--target", rt + "-view")
        records = json.loads(accepted.read_text())["projects"]["alpha"]
        self.assertEqual({r["provider"] for r in records.values()}, {"first", "second"})
        self.assertTrue(all(r["resource"] == "skills" for r in records.values()))
        self.apply("skill", "unaccept", "alpha", "outside", "--target", "second-view")
        self.assertIn("accepted", self.cli("packs", "check", "alpha", "--target", "first-view"))
        self.assertIn("unmanaged", self.cli("packs", "check", "alpha", "--target", "second-view"))
        self.assertEqual(json.loads(accepted.read_text())["user"]["outside"]["sha256"], unowned_hash)

    def test_exclusion_settings_follow_selected_runtime(self):
        for rt in ("first", "second"):
            skill = self.repo / ("." + rt) / "skills" / "outside"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: outside\ndescription: Outside guidance.\n---\nRead carefully.\n")
        put(self.repo / ".first" / "settings.json", {"skillOverrides": {"outside": "off"}})
        first = self.cli("packs", "check", "alpha", "--target", "first-view")
        second = self.cli("packs", "check", "alpha", "--target", "second-view")
        self.assertRegex(first, r"excluded\s+outside")
        self.assertRegex(second, r"unmanaged\s+outside")
        self.assertIn("skill accept alpha outside --target second-view", second)
        self.cli("skill", "accept", "alpha", "outside", "--target", "first-view", ok=False)

    def test_ambiguity_unverified_layout_surface_and_extension_refuse(self):
        self.runtime("duplicate", ".dup", "second-view")
        self.assertIn("exactly one", self.cli(*self.render(), ok=False))
        (self.providers / "duplicate.json").unlink()
        doc = json.loads((self.providers / "second.json").read_text())
        for change, expected in ((lambda d: d["capabilities"]["skills"].update(verified_on=None), "no skills support"),
                                 (lambda d: d["resources"]["skills"].update(project_dir=None), "resources.skills.project_dir"),
                                 (lambda d: d.update(surface="cloud"), "exactly one"),
                                 (lambda d: d.update(schema=999), "exactly one")):
            bad = copy.deepcopy(doc)
            change(bad)
            put(self.providers / "second.json", bad)
            self.assertIn(expected, self.cli(*self.render(), ok=False))
        put(self.providers / "second.json", doc)
        self.answers["models"]["extensions"] = ["only-first"]
        self.save_answers()
        self.assertIn("no such extension", self.cli(*self.render(), ok=False))
        self.assertFalse(self.live().exists())

    def test_unsealed_drifted_invalid_secondary_library_and_unrelated_malformed_default(self):
        doc = json.loads((self.providers / "second.json").read_text())
        (self.providers / "second.json").unlink()
        directory = self.conf / "packs" / "providers" / "second"
        put(directory / "definition.json", doc)
        self.assertIn("never reviewed", self.cli(*self.render(), ok=False))
        put(directory / ".pack.json", {"sealed": True, "sha256": P.tree_hash(str(directory))})
        # A library capability needs bound verification evidence, not a date copied into its definition.
        self.assertIn("no skills support", self.cli(*self.render(), ok=False))
        (directory / "extra").write_text("drift")
        self.assertIn("changed since", self.cli(*self.render(), ok=False))
        invalid = copy.deepcopy(doc)
        invalid["models"] = {"pattern": "["}
        put(directory / "definition.json", invalid)
        put(directory / ".pack.json", {"sealed": True, "sha256": P.tree_hash(str(directory))})
        self.assertIn("invalid", self.cli(*self.render(), ok=False))
        (self.conf / "packs" / "providers" / "broken").mkdir()
        (self.conf / "packs" / "providers" / "broken" / "definition.json").write_text("{")
        self.token(*self.render("first"))
        self.assertFalse(self.live().exists())

    def test_stale_cross_target_project_tokens_and_foreign_manifests(self):
        # Equal payloads and layouts must still have different plan identities.
        first = json.loads((self.providers / "first.json").read_text())
        second = json.loads((self.providers / "second.json").read_text())
        second["resources"] = copy.deepcopy(first["resources"])
        put(self.providers / "second.json", second)
        put(self.conf / "packs" / "links.json", {"links": [self.links[0]]})
        token = self.token(*self.render("first"))
        self.assertNotEqual(token, self.token(*self.render()))
        self.cli(*self.render(), "--plan", token, "--approved", "fixture", ok=False)
        token = self.token(*self.render())
        doc = json.loads((self.providers / "second.json").read_text())
        doc["description"] += " changed"
        put(self.providers / "second.json", doc)
        self.cli(*self.render(), "--plan", token, "--approved", "fixture", ok=False)
        self.save_answers("beta")
        self.cli(*self.render(project="beta"), "--plan", self.token(*self.render()), "--approved", "fixture", ok=False)
        self.apply(*self.render())
        self.apply(*self.render("first"))
        self.assertEqual(self.manifest()["packs"], self.manifest("first")["packs"])
        self.assertEqual(self.manifest()["files"], self.manifest("first")["files"])
        path = self.live() / "MANIFEST.json"
        original = self.manifest()
        for field, value in (("runtime", "first"), ("target", "first-view"), ("project", "beta")):
            put(path, original | {field: value})
            before = path.read_bytes()
            self.cli(*self.render(), ok=False)
            self.cli("packs", "check", "alpha", "--target", "second-view", ok=False)
            self.cli("packs", "link", "alpha", "--target", "second-view", ok=False)
            self.assertEqual(path.read_bytes(), before)

    def test_default_metadata_compatibility_and_secondary_metadata_refusal(self):
        for rt in ("first", "second"):
            self.apply(*self.render(rt))
            m = self.manifest(rt)
            for k in ("runtime", "target", "composition"):
                del m[k]
            put(self.live(rt) / "MANIFEST.json", m)
        self.cli("packs", "check", "alpha", "--target", "first-view")
        self.apply("project", "link", "alpha", "--resource", "skills")
        self.apply(*self.render("first"))
        self.assertEqual(self.manifest("first")["runtime"], "first")
        self.cli(*self.render(), ok=False)
        self.cli("packs", "link", "alpha", "--target", "second-view", ok=False)

    def test_foreign_and_tracked_link_collisions_and_backup_restore(self):
        self.apply(*self.render())
        self.apply(*self.render("first"))
        dest = self.repo / ".second" / "skills"
        self.save_answers("beta")
        self.apply(*self.render(project="beta"))
        self.apply("packs", "link", "beta", "--target", "second-view")
        self.cli("packs", "link", "alpha", "--target", "second-view", ok=False)
        self.assertEqual(dest.resolve(), self.live(project="beta") / ".second" / "skills")
        self.apply("packs", "unlink", "beta", "--target", "second-view")
        self.assertTrue((self.live() / "MANIFEST.json").exists())
        dest.symlink_to(self.repo)
        self.cli("packs", "link", "alpha", "--target", "second-view", ok=False)
        dest.unlink()
        dest.mkdir()
        (dest / "keep.txt").write_text("mine")
        subprocess.run(["git", "-C", str(self.repo), "add", ".second/skills/keep.txt"], check=True)
        self.cli("packs", "link", "alpha", "--target", "second-view", ok=False)
        subprocess.run(["git", "-C", str(self.repo), "rm", "--cached", ".second/skills/keep.txt"], check=True, stdout=subprocess.PIPE)
        args = ("packs", "link", "alpha", "--target", "second-view")
        token = self.token(*args)
        doc = json.loads((self.providers / "second.json").read_text())
        doc["description"] += " changed"
        put(self.providers / "second.json", doc)
        self.apply(*self.render())
        self.cli(*args, "--plan", token, "--approved", "fixture", ok=False)
        self.assertEqual((dest / "keep.txt").read_text(), "mine")
        self.cli("packs", "link", "alpha", "--target", "first-view", "--plan", token, "--approved", "fixture", ok=False)
        self.apply(*args)
        self.apply("packs", "unlink", "alpha", "--target", "second-view")
        self.assertEqual((dest / "keep.txt").read_text(), "mine")


if __name__ == "__main__":
    unittest.main()
