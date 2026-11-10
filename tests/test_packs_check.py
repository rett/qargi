#!/usr/bin/env python3
"""lib/packs_check.py: the per-pack work of `skill check`, `tool check`, `packs check` and `skill|tool list` in one process.

The expected values were produced by the shell code this script replaced (content_hash, compat_of, review and the loops of lib/packs.sh at
version 0.2.8, run in the locale of the hermetic environment, C.UTF-8): the approval hash of a library pack is stored with it, so it may not
change by a bit, and the lines of the verbs are what people and scripts read. The packs are the awkward ones: names with a newline, a
backslash or a tab, a link, a hard link, a pipe, an empty directory, a nested record, a case and punctuation mix whose order depends on the
locale, a tool pack whose JSON is not what the review expects. The last test counts processes: a check of 3 packs and of 12 start the
same number of jq, find, sort, xargs, sha256sum and python3 (the shell started about 70 per pack).
Run: python3 tests/test_packs_check.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, locale, os, shutil, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import packs_check as C  # noqa: E402

GOOD = "---\nname: x\ndescription: Use for x.\n---\nbody\n"
TOOL = {"name": "t-ok", "url": "https://example.net/mcp", "tools": {"read_x": "always_allow", "create_y": "always_ask"}}
WRONG = "0123456789abcdef"


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def put(path, content, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content if isinstance(content, bytes) else content.encode("utf-8"))
    if mode is not None:
        os.chmod(path, mode)


def skill(lib, name, files=None, compat='["any"]', approved=WRONG, md=GOOD, record=True):
    d = os.path.join(lib, "skills", name)
    os.makedirs(d, exist_ok=True)
    if md is not None:
        put(os.path.join(d, "SKILL.md"), md)
    for f, c in (files or {}).items():
        put(os.path.join(d, f), c)
    if record:
        rec = {"kind": "skill", "source": "created", "sha256": approved, "stored": "2026-01-01T00:00:00Z"}
        if compat is not None:
            rec["compatible_providers"] = json.loads(compat)
        put(os.path.join(d, ".pack.json"), json.dumps(rec))
    return d


def tool(lib, name, doc=None, raw=None, compat='["any"]', approved=WRONG):
    put(os.path.join(lib, "tools", name + ".json"), raw if raw is not None else json.dumps(doc))
    rec = {"kind": "tool", "source": "created", "sha256": approved, "stored": "2026-01-01T00:00:00Z", "compatible_providers": json.loads(compat)}
    put(os.path.join(lib, "tools", name + ".pack.json"), json.dumps(rec))


def awkward(lib):
    """The awkward packs. Returns the names in the order of the library."""
    skill(lib, "plain")
    skill(lib, "nested", {"b/c.md": "c", "A/d.md": "d", "z.txt": "z", "a_b": "1", "a-b": "2", "a.b": "3", "Ab": "4", "ab": "5"})
    skill(lib, "oddnames", {"new\nline": "n", "back\\slash": "b", "tab\tname": "t", "é.md": "e", "日本.md": "j"})
    d = skill(lib, "special")
    os.symlink("SKILL.md", os.path.join(d, "link.md"))
    os.link(os.path.join(d, "SKILL.md"), os.path.join(d, "hard.md"))
    os.mkfifo(os.path.join(d, "pipe"))
    os.makedirs(os.path.join(d, "empty", "inner"))
    skill(lib, "recnest", {"x/.pack.json": "{}", "x/y/.pack.json": "{}"})
    skill(lib, "secret", {"n.txt": "sk-ant-0123456789"})
    skill(lib, "binary", {"b.bin": b"\x7fELF\x00\x01", "t.txt": b"\xff\xfe"})
    skill(lib, "controls", {"c.md": "a\x01b", "r.md": "a\rb", "bidi.md": "a‮b"})
    skill(lib, "frontmatter", md="name: x\ndescription: y\n")
    skill(lib, "nodesc", md="---\nname: x\ndescription: <b>\n---\n")
    skill(lib, "nomd", md=None)
    skill(lib, "scripts", {"run.sh": "#!/bin/sh\necho hi\n", "t.py": "x", "bin/tool": "x"})
    os.chmod(os.path.join(lib, "skills", "scripts", "bin", "tool"), 0o755)
    skill(lib, "norecord", record=False)
    skill(lib, "nocompat", compat=None)
    skill(lib, "badcompat", compat='["a","a"]')
    skill(lib, "multi", compat='["z-b","a-b","claude-code"]')
    skill(lib, "other", compat='["other-provider"]')
    tool(lib, "t-ok", TOOL)
    tool(lib, "t-write", dict(TOOL, name="t-write", tools={"create_y": "always_allow", "post_z": "auto"}))
    tool(lib, "t-badurl", dict(TOOL, name="t-badurl", url="http://x"))
    tool(lib, "t-vault", dict(TOOL, name="t-vault", vault_ids=["abc", 1]))
    tool(lib, "t-secret", dict(TOOL, name="t-secret", token="sk-ant-xx"))
    tool(lib, "t-array", raw="[1,2]")
    tool(lib, "t-badjson", raw="{nope")
    tool(lib, "t-toolsarr", dict(TOOL, name="t-toolsarr", tools=["always_allow"]))
    tool(lib, "t-keynl", dict(TOOL, name="t-keynl", tools={"a\nFAIL: forged": "always_allow"}))


def project(conf, name, repo):
    os.makedirs(os.path.join(conf, "projects"), exist_ok=True)
    doc = {"schema": 1, "project": name, "repo": {"url": "https://github.com/example/x", "path": repo, "long_lived": ["main"]},
           "roles": {"build": {"base": "@dispatcher", "push": {"mode": "none"}, "model": "claude-sonnet-5-5", "effort": "high", "apt": [], "skills": []}},
           "models": {"provider": {"local": "claude-code", "cloud": "claude-platform"}}, "memory": {"memory_store": "", "reference_store": ""},
           "budget_cents": 500}
    put(os.path.join(conf, "projects", name + ".json"), json.dumps(doc))


def link_all(conf, lib, scope_project="alpha"):
    names = [("skill", n) for n in sorted(os.listdir(os.path.join(lib, "skills")))] + \
            [("tool", n[:-5]) for n in sorted(os.listdir(os.path.join(lib, "tools"))) if n.endswith(".json") and not n.endswith(".pack.json")]
    links = [{"pack": "%s:%s" % (k, n), "scope": "project", "project": scope_project} for k, n in names]
    put(os.path.join(conf, "packs", "links.json"), json.dumps({"links": links}))


def qargi(env, *args):
    p = subprocess.run([os.path.join(ROOT, "bin", "qargi")] + list(args), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.stdout.decode("utf-8", "surrogateescape"), p.returncode


class Fixture:
    def __init__(self, extra=None):
        self.dir = tempfile.mkdtemp(prefix="pc.")
        self.conf = os.path.join(self.dir, "conf")
        self.lib = os.path.join(self.conf, "packs")
        os.makedirs(os.path.join(self.lib, "skills"))
        os.makedirs(os.path.join(self.lib, "tools"))
        (extra or awkward)(self.lib)
        project(self.conf, "alpha", os.path.join(self.dir, "repo"))
        link_all(self.conf, self.lib)
        self.env = dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=os.path.join(self.dir, "state"), HOME=os.path.join(self.dir, "home"))
        os.makedirs(self.env["HOME"], exist_ok=True)

    def close(self):
        for dp, dns, fns in os.walk(self.dir):
            for n in dns + fns:
                try:
                    os.chmod(os.path.join(dp, n), 0o700) if not os.path.islink(os.path.join(dp, n)) and os.path.isdir(os.path.join(dp, n)) else None
                except OSError:
                    pass
        shutil.rmtree(self.dir, ignore_errors=True)


# the content hash the shell function made of each awkward pack (hermetic locale C.UTF-8)
GOLD_HASH = {
    "skill:badcompat": "aea1a26d3f964d4d",
    "skill:binary": "54a2008e4ddfc11b",
    "skill:controls": "d6483fdcddd4399c",
    "skill:frontmatter": "5ea95dfa8342d6ff",
    "skill:multi": "e9abf036c82ae8ff",
    "skill:nested": "9ba512edc289ebf1",
    "skill:nocompat": "284e4e69c32da452",
    "skill:nodesc": "9f75c6379afdb438",
    "skill:nomd": "0a80fbe11e22e9ef",
    "skill:norecord": "284e4e69c32da452",
    "skill:oddnames": "927c2c75d34f976c",
    "skill:other": "968497e227a942b8",
    "skill:plain": "fabe665d3e1f8d3d",
    "skill:recnest": "879634e150c10c1e",
    "skill:scripts": "0371435cf8d405fc",
    "skill:secret": "10a58ef6e464b491",
    "skill:special": "70a2764f16d49211",
    "tool:t-array.json": "6e126a66211f443e",
    "tool:t-badjson.json": "894a475ee8c4e3da",
    "tool:t-badurl.json": "f2e7abcc3b1034e3",
    "tool:t-keynl.json": "eaf8affe081cf201",
    "tool:t-ok.json": "b12c12cd1d0f9bf8",
    "tool:t-secret.json": "3ee974959780679c",
    "tool:t-toolsarr.json": "19a1d8494482c997",
    "tool:t-vault.json": "0c0d0e8787765544",
    "tool:t-write.json": "3de85985a8c5e279"
}
# what the verbs printed, and their exit status
GOLD_SKILL_CHECK = ((
    'skip skill badcompat: not compatible with claude-code, claude-platform (it declares a)\n'
    'skip skill other: not compatible with claude-code, claude-platform (it declares other-provider)\n'
    'skill:binary: FAIL: b.bin is an ELF executable: a pack holds only text files (scripts you can read)\n'
    'skill:binary: FAIL: t.txt is not UTF-8 text: a pack holds only text files (scripts you can read)\n'
    'FAIL skill:controls: content changed since it was approved (drift: 0123456789abcdef -> d6483fdcddd4399c); review it and re-import\n'
    'skill:controls: FAIL: bidi.md:1 has a control or bidi character (U+202E), which can change what a reader sees; a pack holds plain text\n'
    'skill:controls: FAIL: c.md:1 has a control or bidi character (U+0001), which can change what a reader sees; a pack holds plain text\n'
    'skill:controls: FAIL: r.md:1 has a control or bidi character (U+000D), which can change what a reader sees; a pack holds plain text\n'
    'skill:frontmatter: FAIL: SKILL.md has no front matter\n'
    'ok   skill:multi\n'
    'ok   skill:nested\n'
    'skill:nocompat: FAIL: compatible_providers: not declared; every pack declares the providers that can use it (a list of runtime or family names, or ["any"])\n'
    'skill:nodesc: FAIL: SKILL.md front matter has no real description\n'
    'skill:nomd: FAIL: no SKILL.md\n'
    'skill:norecord: FAIL: compatible_providers: not declared; every pack declares the providers that can use it (a list of runtime or family names, or ["any"])\n'
    'skill:oddnames: FAIL: new\n'
    'skill:oddnames: FAIL: tab\tname: the file name has a control or bidi character, which can change what a reader sees\n'
    'ok   skill:plain\n'
    'FAIL skill:recnest: content changed since it was approved (drift: 0123456789abcdef -> 879634e150c10c1e); review it and re-import\n'
    "skill:recnest: FAIL: .pack.json is qargi's own record and only the top level of a library pack holds it; remove or rename these:\n"
    'ok   skill:scripts\n'
    'FAIL skill:secret: content changed since it was approved (drift: 0123456789abcdef -> 10a58ef6e464b491); review it and re-import\n'
    'skill:secret: FAIL: looks like a secret\n'
    'skill:special: FAIL: empty/inner is an empty directory, which a pack may not hold\n'
    'skill:special: FAIL: SKILL.md has 2 names (a hard link), which a pack may not hold\n'
    'skill:special: FAIL: hard.md has 2 names (a hard link), which a pack may not hold\n'
    'skill:special: FAIL: link.md is a symbolic link, which a pack may not hold\n'
    'skill:special: FAIL: pipe is not a regular file\n'), 1)
GOLD_TOOL_CHECK = ((
    'tool:t-array: FAIL: vault_ids must be vault ids (vlt_...), never secrets\n'
    'tool:t-badjson: FAIL: not valid JSON\n'
    'tool:t-badurl: FAIL: url: a real https URL\n'
    'tool:t-keynl: FAIL: tools.a\n'
    'tool:t-keynl: FAIL: forged: the key has a control or bidi character (U+000A), which can change what a reader sees; a definition holds plain one-line text\n'
    'tool:t-keynl: FAIL: forged=always_allow\n'
    'ok   tool:t-ok\n'
    'tool:t-secret: FAIL: looks like a secret (credentials belong in a vault)\n'
    'ok   tool:t-toolsarr\n'
    'tool:t-vault: FAIL: vault_ids must be vault ids (vlt_...), never secrets\n'
    'tool:t-write: FAIL: tools.create_y: a write-like tool may not run unattended (use always_ask) unless write_ok is true on the pack, on purpose\n'
    'tool:t-write: FAIL: tools.post_z: a write-like tool may not run unattended (use always_ask) unless write_ok is true on the pack, on purpose\n'), 1)
GOLD_LIST = (
    'badcompat   links: project:alpha   compatible: a\n'
    'binary   links: project:alpha   compatible: any\n'
    'controls   links: project:alpha   compatible: any\n'
    'frontmatter   links: project:alpha   compatible: any\n'
    'multi   links: project:alpha   compatible: a-b, claude-code, z-b\n'
    'nested   links: project:alpha   compatible: any\n'
    'nocompat   links: project:alpha   compatible: NOT DECLARED\n'
    'nodesc   links: project:alpha   compatible: any\n'
    'nomd   links: project:alpha   compatible: any\n'
    'norecord   links: project:alpha   compatible: NOT DECLARED\n'
    'oddnames   links: project:alpha   compatible: any\n'
    'other   links: project:alpha   compatible: other-provider\n'
    'plain   links: project:alpha   compatible: any\n'
    'recnest   links: project:alpha   compatible: any\n'
    'scripts   links: project:alpha   compatible: any\n'
    'secret   links: project:alpha   compatible: any\n'
    'special   links: project:alpha   compatible: any\n'
    't-array   links: project:alpha   compatible: any\n'
    't-badjson   links: project:alpha   compatible: any\n'
    't-badurl   links: project:alpha   compatible: any\n'
    't-keynl   links: project:alpha   compatible: any\n'
    't-ok   links: project:alpha   compatible: any\n'
    't-secret   links: project:alpha   compatible: any\n'
    't-toolsarr   links: project:alpha   compatible: any\n'
    't-vault   links: project:alpha   compatible: any\n'
    't-write   links: project:alpha   compatible: any\n')
GOLD_LIST_ROLE = (
    'badcompat   links: project:alpha   compatible: a  [attached to alpha/build]\n'
    'binary   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'controls   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'frontmatter   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'multi   links: project:alpha   compatible: a-b, claude-code, z-b  [attached to alpha/build]\n'
    'nested   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'nocompat   links: project:alpha   compatible: NOT DECLARED  [attached to alpha/build]\n'
    'nodesc   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'nomd   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'norecord   links: project:alpha   compatible: NOT DECLARED  [attached to alpha/build]\n'
    'oddnames   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'other   links: project:alpha   compatible: other-provider  [attached to alpha/build]\n'
    'plain   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'recnest   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'scripts   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'secret   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    'special   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    't-array   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    't-badjson   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    't-badurl   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    't-keynl   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    't-ok   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    't-secret   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    't-toolsarr   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    't-vault   links: project:alpha   compatible: any  [attached to alpha/build]\n'
    't-write   links: project:alpha   compatible: any  [attached to alpha/build]\n')


class Hashes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture()

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def test_the_hash_of_every_pack_is_the_one_the_shell_made(self):
        got = {}
        for kind, sub in (("skills", ""), ("tools", ".json")):
            for n in sorted(os.listdir(os.path.join(self.fx.lib, kind))):
                if n.endswith(".pack.json"):
                    continue
                got[kind[:-1] + ":" + n] = C.content_hash(os.path.join(self.fx.lib, kind, n))
        self.assertEqual(got, GOLD_HASH)

    def test_the_declaration_is_part_of_the_hash(self):
        fx = Fixture(extra=lambda lib: skill(lib, "plain"))
        try:
            d = os.path.join(fx.lib, "skills", "plain")
            before = C.content_hash(d)
            rec = os.path.join(d, ".pack.json")
            put(rec, json.dumps({"kind": "skill", "compatible_providers": ["claude-code"]}))
            one = C.content_hash(d)
            self.assertNotEqual(one, before)
            put(rec, json.dumps({"kind": "skill", "compatible_providers": ["claude-code", "claude-code"]}))   # unique: the same declaration
            self.assertEqual(C.content_hash(d), one)
        finally:
            fx.close()

    def test_the_order_is_the_order_of_sort_in_the_locale(self):
        """The names are put in the order `sort -z` puts them in: the approval hash depends on it."""
        names = [b"./a_b", b"./a-b", b"./a.b", b"./Ab", b"./ab", b"./A/d", b"./b/c", b"./z", b"./Z", b"./\xc3\xa9", b"./e", b"./E", b"./a b"]
        tried = 0
        saved = locale.setlocale(locale.LC_ALL)
        try:
            for name in ("en_US.UTF-8", "en_US.utf8", "de_DE.UTF-8", "C.UTF-8", "C"):
                try:
                    locale.setlocale(locale.LC_ALL, name)
                except locale.Error:
                    continue
                tried += 1
                want = subprocess.run(["sort", "-z"], input=b"\0".join(names) + b"\0", stdout=subprocess.PIPE,
                                      env=dict(os.environ, LC_ALL=name)).stdout.split(b"\0")[:-1]
                self.assertEqual(sorted(names, key=C.coll), want, "order in " + name)
        finally:
            locale.setlocale(locale.LC_ALL, saved)
        self.assertGreater(tried, 0, "no locale to try")


class Verbs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture()
        # approve what the shell approved: the hash of the library (the shell's), except for the packs that drift on purpose
        for key, h in GOLD_HASH.items():
            kind, n = key.split(":", 1)
            if n in ("secret", "t-secret", "controls", "recnest"):
                continue                                   # these keep the wrong approval: drift lines
            p = os.path.join(cls.fx.lib, "skills" if kind == "skill" else "tools", n)
            rec = os.path.join(p, ".pack.json") if kind == "skill" else p[:-5] + ".pack.json"
            try:
                d = jload(rec)
            except OSError:
                continue
            d["sha256"] = h
            put(rec, json.dumps(d))

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def test_skill_check(self):
        out, rc = qargi(self.fx.env, "skill", "check", "alpha", "build")
        self.assertEqual((out, rc), GOLD_SKILL_CHECK)

    def test_tool_check(self):
        out, rc = qargi(self.fx.env, "tool", "check", "alpha", "build")
        self.assertEqual((out, rc), GOLD_TOOL_CHECK)

    def test_list(self):
        self.assertEqual(qargi(self.fx.env, "skill", "list")[0] + qargi(self.fx.env, "tool", "list")[0], GOLD_LIST)
        self.assertEqual(qargi(self.fx.env, "skill", "list", "alpha", "build")[0] + qargi(self.fx.env, "tool", "list", "alpha", "build")[0], GOLD_LIST_ROLE)

    def test_a_pack_linked_but_gone_and_a_clean_role(self):
        fx = Fixture(extra=lambda lib: skill(lib, "solo"))
        try:
            h = C.content_hash(os.path.join(fx.lib, "skills", "solo"))
            rec = os.path.join(fx.lib, "skills", "solo", ".pack.json")
            d = jload(rec)
            d["sha256"] = h
            put(rec, json.dumps(d))
            links = jload(os.path.join(fx.lib, "links.json"))
            links["links"].append({"pack": "skill:gone", "scope": "project", "project": "alpha"})
            put(os.path.join(fx.lib, "links.json"), json.dumps(links))
            self.assertEqual(qargi(fx.env, "skill", "check", "alpha", "build"), ("FAIL skill:gone: linked but not in the library\nok   skill:solo\n", 1))
            os.remove(os.path.join(fx.lib, "links.json"))
            put(os.path.join(fx.lib, "links.json"), json.dumps({"links": []}))
            self.assertEqual(qargi(fx.env, "skill", "check", "alpha", "build"), ("no pack is linked to any role of alpha\n", 0))
        finally:
            fx.close()


class Processes(unittest.TestCase):
    """The number of processes does not grow with the number of packs."""

    LOG = None

    def count(self, n):
        def many(lib):
            for i in range(n):
                skill(lib, "p-%02d" % i, {"refs/a.md": "x"})
        fx = Fixture(extra=many)
        try:
            for i in range(n):
                p = os.path.join(fx.lib, "skills", "p-%02d" % i)
                rec = os.path.join(p, ".pack.json")
                d = jload(rec)
                d["sha256"] = C.content_hash(p)
                put(rec, json.dumps(d))
            shim = os.path.join(fx.dir, "shim")
            log = os.path.join(fx.dir, "calls.log")
            os.makedirs(shim)
            for t in ("jq", "find", "sort", "xargs", "sha256sum", "python3", "grep", "sed"):
                real = shutil.which(t)
                put(os.path.join(shim, t), "#!/bin/sh\necho %s >> '%s'\nexec '%s' \"$@\"\n" % (t, log, real), 0o755)
            env = dict(fx.env, PATH=shim + os.pathsep + os.environ["PATH"])
            out, rc = qargi(env, "skill", "check", "alpha", "build")
            self.assertEqual((out, rc), ("".join("ok   skill:p-%02d\n" % i for i in range(n)), 0))
            counts = {}
            with open(log) as f:
                for t in f.read().split():
                    counts[t] = counts.get(t, 0) + 1
            return counts
        finally:
            fx.close()

    def test_the_processes_do_not_grow_with_the_packs(self):
        few, many = self.count(3), self.count(12)
        self.assertEqual(few, many, "processes started by `skill check` for 3 packs and for 12")


if __name__ == "__main__":
    unittest.main()
