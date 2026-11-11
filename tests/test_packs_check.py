#!/usr/bin/env python3
"""lib/packs_check.py: the per-pack work of `skill check`, `tool check`, `packs check` and `skill|tool list` in one process.

The expected values were produced by the shell code this script replaced (content_hash, compat_of, review and the loops of lib/packs.sh at
version 0.2.8, run in the locale of the hermetic environment, C.UTF-8): the approval hash of a library pack is stored with it, so it may not
change by a bit, and the lines of the verbs are what people and scripts read. The packs are the awkward ones: names with a newline, a
backslash or a tab, a link, a hard link, a pipe, an empty directory, a nested record, a case and punctuation mix whose order depends on the
locale, a tool pack whose JSON is not what the review expects. The last test counts processes: a check of 3 packs and of 12 start the
same number of jq, find, sort, xargs, sha256sum and python3 (the shell started about 70 per pack).
The findings about a tool pack's document are no longer the shell's: lib/packs_check.py holds the one definition of them (tool_msgs: which tool names
write, which names a tools map may hold) and the shell review asks it. ToolNames below is its table; the lines of t-array, t-keynl and t-toolsarr in
GOLD_TOOL_CHECK are what that definition says (a file that is not an object, or a tools map that is not one, fails; the shell's jq program ended in an
error on them and said nothing).
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
    'tool:t-array: FAIL: not a JSON object: a tool pack is one object with name, url and tools\n'
    'tool:t-array: FAIL: vault_ids must be vault ids (vlt_...), never secrets\n'
    'tool:t-badjson: FAIL: not valid JSON\n'
    'tool:t-badurl: FAIL: url: a real https URL\n'
    'tool:t-keynl: FAIL: tools.a\n'
    'tool:t-keynl: FAIL: forged: the key has a control or bidi character (U+000A), which can change what a reader sees; a definition holds plain one-line text\n'
    'tool:t-keynl: FAIL: tools."a\\nFAIL: forged": not a tool name (letters, digits, _ . - /, at most 128 characters, no blank)\n'
    'tool:t-keynl: FAIL: forged=always_allow\n'
    'ok   tool:t-ok\n'
    'tool:t-secret: FAIL: looks like a secret (credentials belong in a vault)\n'
    'tool:t-toolsarr: FAIL: tools: an explicit allowlist of tool names with a policy each\n'
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


# The names of tools as MCP servers write them, and whether the name says the tool writes (C.write_like). The rule: a name is cut into words at every
# character that is not a letter and at a camelCase boundary; a word that starts with a write word counts, a write word inside or at the end of a
# word does not, and the READ_ALIKE words (settings, address, postal ...) do not.
WRITES = ("create_issue", "platform.delete_knowledge", "repo/push", "issue-close", "deleteItem", "updateRecord", "HTTPPost", "bulk.remove", "files/write",
          "send-message", "branch.merge", "setValue", "add_label", "editPage", "post_comment", "items.v2.delete", "DELETE_ITEM", "api/v1/users/create",
          "x__update", "comment", "getOrCreate", "iOSUpdate", "DELETEitem", "SENDmail",
          "deleteall", "sendmail", "postmessage",                    # no separator: the word starts with a write word
          "created_at_list", "list_comments", "setup_hook", "sender.lookup")   # not on the read-alike list: taken for a write, so asked about
READS = ("platform.list_items", "getStatus", "search", "get_item", "listIssues", "repo/read", "fetch-page", "items.v2.list", "GET_ITEM", "query",
         "settings_view", "address_list", "postal_code_lookup", "getSettings", "user.address", "closest_store", "additional_info", "postcode/find",   # look-alikes: READ_ALIKE
         "offset_page", "dataset.query", "preset_list", "asset/get", "list_assets", "subset_view", "getDataset")   # a write word inside or at the end of a word


class ToolNames(unittest.TestCase):
    """The one definition of a write-like tool name and of a name a tools map may hold, and that the shell review says what it says."""

    def test_a_write_word_counts_however_the_name_is_spelled(self):
        self.assertGreaterEqual(len(WRITES) + len(READS), 40)
        self.assertEqual([n for n in WRITES if not C.write_like(n)], [], "names that write and were taken for a read")
        self.assertEqual([n for n in READS if C.write_like(n)], [], "names that read and were taken for a write")

    def test_the_words_of_a_name(self):
        for name, words in (("platform.delete_knowledge", ["platform", "delete", "knowledge"]), ("repo/push", ["repo", "push"]), ("issue-close", ["issue", "close"]),
                            ("deleteItem", ["delete", "item"]), ("HTTPPost", ["http", "post", "httpp"]), ("getHTTPStatus", ["get", "http", "status", "https"]),
                            ("DELETEitem", ["delet", "eitem", "delete"]),      # a run of capitals before lower-case letters is read both ways
                            ("items.v2.delete", ["items", "v", "delete"]), ("DELETE_ITEM", ["delete", "item"]), ("settings_view", ["settings", "view"]), ("", [])):
            self.assertEqual(C.name_words(name), words, name)
        for odd in (None, 7, ["delete"]):
            self.assertEqual(C.name_words(odd), [])
            self.assertFalse(C.write_like(odd))

    def test_the_names_a_tools_map_may_hold(self):
        good = ("read_x", "platform.list_items", "repo/push", "issue-close", "deleteItem", "_private", "a", "A.b/c-d_e", "x" * 128, "9lives")
        bad = ("", "x" * 129, "a b", "a\tb", "a\nb", "a\x00b", "a*", "mcp__x(*)", 'a"b', "a'b", ".hidden", "-opt", "/abs", "a:b", "a,b", "café", "a‮b", "a\n")
        for k in good:
            self.assertEqual(C.tool_msgs(dict(TOOL, tools={k: "always_ask"})), [], k)
        for k in bad:
            got = C.tool_msgs(dict(TOOL, tools={k: "always_ask"}))
            self.assertEqual(len(got), 1, k)
            self.assertTrue(got[0].startswith("FAIL: tools.") and got[0].endswith(": not a tool name (letters, digits, _ . - /, at most 128 characters, no blank)"), got)
            self.assertNotIn("\n", got[0])
            self.assertTrue(got[0].isascii() and got[0].isprintable(), got)
        # the name of the pack keeps its own rule: lower-case letters, digits and -
        for n in ("t-ok", "a", "0x", "a" * 41):
            self.assertEqual(C.tool_msgs(dict(TOOL, name=n)), [], n)
        for n in ("T", "a.b", "a/b", "a_b", "-a", "", "a" * 42, "t-ok\n", 7, None):
            self.assertEqual(C.tool_msgs(dict(TOOL, name=n)), ["FAIL: name: lower-case letters, digits, -"], n)

    def test_a_write_like_tool_may_not_run_unattended(self):
        line = "FAIL: tools.%s: a write-like tool may not run unattended (use always_ask) unless write_ok is true on the pack, on purpose"
        for n in WRITES:
            for pol in ("always_allow", "auto"):
                self.assertEqual(C.tool_msgs(dict(TOOL, tools={n: pol})), [line % n], n)
                self.assertEqual(C.tool_msgs(dict(TOOL, tools={n: pol}, write_ok=True)), [], n)
                self.assertEqual(C.tool_msgs(dict(TOOL, tools={n: pol}, write_ok="true")), [line % n], "only the JSON true is a yes")
            self.assertEqual(C.tool_msgs(dict(TOOL, tools={n: "always_ask"})), [], n)
        for n in READS:
            for pol in C.POLICY_WORDS:
                self.assertEqual(C.tool_msgs(dict(TOOL, tools={n: pol})), [], n)

    def test_a_document_that_is_no_tool_pack(self):
        for d in (C.BAD, [1, 2], "x", 3, None):
            self.assertEqual(C.tool_msgs(d), ["FAIL: not a JSON object: a tool pack is one object with name, url and tools"])
        for tools in (["always_allow"], {}, "read_x", None, 1):
            self.assertEqual(C.tool_msgs(dict(TOOL, tools=tools)), ["FAIL: tools: an explicit allowlist of tool names with a policy each"], tools)
        self.assertEqual(C.tool_msgs(dict(TOOL, tools={"read_x": "sometimes", "list_y": 1})),
                         ["FAIL: tools.read_x: policy must be always_allow, always_ask or auto", "FAIL: tools.list_y: policy must be always_allow, always_ask or auto"])

    def test_the_shell_review_says_what_the_definition_says(self):
        """`tool check` (this file's review) and `tool show` (the review of lib/packs.sh) print the same findings for names in every spelling, and the
        write words are written down in one place."""
        def packs(lib):
            tool(lib, "t-spell", dict(TOOL, name="t-spell", tools={n: "always_allow" for n in WRITES[:8] + READS[:14]}))
            tool(lib, "t-reads", dict(TOOL, name="t-reads", tools={n: "always_allow" for n in READS}))
            tool(lib, "t-meant", dict(TOOL, name="t-meant", write_ok=True, tools={n: "auto" for n in WRITES}))
            tool(lib, "t-key", dict(TOOL, name="t-key", tools={"a b": "always_ask", "ok.name/x": "always_ask"}))
        fx = Fixture(extra=packs)
        try:
            for n in ("t-spell", "t-reads", "t-meant", "t-key"):
                p = os.path.join(fx.lib, "tools", n + ".json")
                rec = jload(p[:-5] + ".pack.json")
                rec["sha256"] = C.content_hash(p)
                put(p[:-5] + ".pack.json", json.dumps(rec))
            out, rc = qargi(fx.env, "tool", "check", "alpha", "build")
            want = "".join("tool:t-spell: FAIL: tools.%s: a write-like tool may not run unattended (use always_ask) unless write_ok is true on the pack, on purpose\n" % n
                           for n in WRITES[:8])
            self.assertEqual((out, rc), ('tool:t-key: FAIL: tools."a b": not a tool name (letters, digits, _ . - /, at most 128 characters, no blank)\n'
                                         "ok   tool:t-meant\nok   tool:t-reads\n" + want, 1))
            for n, fails in (("t-spell", 8), ("t-reads", 0), ("t-meant", 0), ("t-key", 1)):
                shown, _ = qargi(fx.env, "tool", "show", n)
                got = [ln for ln in shown.split("\n") if ln.startswith("FAIL")]
                self.assertEqual(got, [ln.split(": ", 1)[1] for ln in out.split("\n") if ln.startswith("tool:%s: FAIL" % n)], n)
                self.assertEqual(len(got), fails, n)
            self.assertIn("NOTE: write_ok is set: write-like tools may run unattended", qargi(fx.env, "tool", "show", "t-meant")[0])
        finally:
            fx.close()
        held = []
        for d in ("lib", "bin"):
            for dp, _, fns in os.walk(os.path.join(ROOT, d)):
                for f in fns:
                    if f.endswith((".py", ".sh", "qargi")) and "__pycache__" not in dp:
                        with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                            if "create|update|delete" in fh.read():
                                held.append(os.path.relpath(os.path.join(dp, f), ROOT))
        self.assertEqual(held, [], "the write words are in lib/packs_check.py (WRITE_WORDS) and nowhere as a second pattern")


# The server's own tool listing: an MCP tools/list result. Of the pack's tools it marks two read-only, leaves one unmarked, marks one destructive and
# does not name one; it names a tool the pack does not allow (extra), which is nobody's business here.
LISTING = {"tools": [{"name": "platform.list_items", "description": "x", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
                     {"name": "getStatus", "annotations": {"readOnlyHint": True, "destructiveHint": False}},
                     {"name": "fetch_all"},
                     {"name": "wipe/everything", "annotations": {"destructiveHint": True}},
                     {"name": "extra", "annotations": {"readOnlyHint": True}}]}
LISTED = {"name": "t-listed", "url": "https://example.net/mcp",
          "tools": {"platform.list_items": "always_allow", "getStatus": "auto", "fetch_all": "always_ask", "wipe/everything": "always_ask", "unlisted": "always_ask"}}
HINTS = {"platform.list_items": "read-only", "getStatus": "read-only", "fetch_all": "write", "wipe/everything": "destructive"}
NOT_READ_ONLY = ("FAIL: tools.%s: the server's tool listing does not mark it read-only (readOnlyHint), so it may not run unattended (use always_ask) "
                 "unless write_ok is true on the pack, on purpose")


class ToolListing(unittest.TestCase):
    """`tool import|seal --tool-list FILE`: the server's own tool listing, read from a file, is judged in the review, kept in the record and covered by the hash."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tl.")
        self.conf, self.home = os.path.join(self.dir, "conf"), os.path.join(self.dir, "home")
        os.makedirs(self.home)
        project(self.conf, "alpha", os.path.join(self.dir, "repo"))
        self.env = dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=os.path.join(self.dir, "state"), HOME=self.home)
        self.pack, self.listing = os.path.join(self.dir, "t-listed.json"), os.path.join(self.dir, "listing.json")
        put(self.pack, json.dumps(LISTED))
        put(self.listing, json.dumps(LISTING))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def sha(self, path):
        import hashlib
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def token(self, out):
        return [ln.split()[2] for ln in out.split("\n") if ln.startswith("plan token: ")][0]

    def test_what_a_listing_says_of_the_packs_tools(self):
        tl, notes = C.read_listing(self.listing, self.pack)
        self.assertEqual((tl, notes), ({"sha256": self.sha(self.listing), "tools": HINTS}, []))
        self.assertIsNone(C.listing_problem(tl))
        # the JSON-RPC response that holds the result, and one page of several
        put(self.listing, json.dumps({"jsonrpc": "2.0", "id": 1, "result": dict(LISTING, nextCursor="abc")}))
        tl, notes = C.read_listing(self.listing, self.pack)
        self.assertEqual(tl["tools"], HINTS)
        self.assertEqual(len(notes), 1)
        self.assertIn("nextCursor", notes[0])
        # only the JSON true is a hint, and destructive wins over read-only
        put(self.listing, json.dumps({"tools": [{"name": "getStatus", "annotations": {"readOnlyHint": "true"}}, {"name": "fetch_all", "annotations": {"readOnlyHint": 1}},
                                                {"name": "platform.list_items", "annotations": {"readOnlyHint": True, "destructiveHint": True}},
                                                {"name": "unlisted", "annotations": ["readOnlyHint"]}]}))
        self.assertEqual(C.read_listing(self.listing, self.pack)[0]["tools"],
                         {"getStatus": "write", "fetch_all": "write", "platform.list_items": "destructive", "unlisted": "write"})

    def test_a_file_that_is_no_listing(self):
        for text, why in (("{nope", "is not JSON"), ("[]", "is not an MCP tools/list result"), ('{"tools": {}}', "is not an MCP tools/list result"),
                          ('{"result": {"x": 1}}', "is not an MCP tools/list result"), ('{"tools": [{"title": "x"}]}', "tools[0] has no name"),
                          ('{"tools": ["read_x"]}', "tools[0] has no name"), ('{"tools": [{"name": 3}]}', "tools[0] has no name"),
                          ('{"tools": [{"name": "a"}, {"name": "b"}, {"name": "a"}]}', "names the tool a twice"),
                          (json.dumps({"tools": [{"name": "x" * (C.MAX_LISTING + 1)}]}), "is larger than")):
            put(self.listing, text)
            with self.assertRaises(C.ListingError) as cm:
                C.read_listing(self.listing, self.pack)
            self.assertIn(why, str(cm.exception), text[:40])
        with self.assertRaises(C.ListingError) as cm:
            C.read_listing(os.path.join(self.dir, "nosuch.json"), self.pack)
        self.assertIn("cannot be read", str(cm.exception))

    def test_a_tool_the_listing_does_not_mark_read_only_may_not_run_unattended(self):
        tl = {"sha256": "ab" * 32, "tools": HINTS}
        notes = ["NOTE: tools.wipe/everything: the server's tool listing marks it destructive (destructiveHint)", "NOTE: tools.unlisted: not in the server's tool listing",
                 "NOTE: tool listing abababababababab: it marks 2 of the pack's 5 tools read-only"]
        self.assertEqual(C.tool_msgs(LISTED, tl), notes)
        self.assertEqual(C.tool_msgs(LISTED), [], "without a listing: as before")
        for name in ("fetch_all", "wipe/everything", "unlisted"):
            for pol in ("always_allow", "auto"):
                doc = dict(LISTED, tools=dict(LISTED["tools"], **{name: pol}))
                self.assertEqual(C.tool_msgs(doc, tl), [NOT_READ_ONLY % name] + notes, (name, pol))
                self.assertEqual(C.tool_msgs(dict(doc, write_ok=True), tl), notes, "write_ok on the pack, on purpose")
                self.assertEqual(C.tool_msgs(doc), [], "the name of %s is no write: without a listing it passes" % name)
        # the name check still applies, and a tool it failed is not failed twice
        doc = dict(LISTED, tools={"delete_item": "always_allow", "list_items": "always_allow"})
        tl2 = {"sha256": "cd" * 32, "tools": {"delete_item": "read-only", "list_items": "read-only"}}
        self.assertEqual(C.tool_msgs(doc, tl2), ["FAIL: tools.delete_item: a write-like tool may not run unattended (use always_ask) unless write_ok is true on the pack, on purpose",
                                                 "NOTE: tool listing cdcdcdcdcdcdcdcd: it marks 2 of the pack's 2 tools read-only"])
        tl2["tools"]["delete_item"] = "write"
        self.assertEqual(len([m for m in C.tool_msgs(doc, tl2) if m.startswith("FAIL")]), 1)
        self.assertEqual(C.tool_msgs(LISTED, C.BAD)[0][:16], "FAIL: tool_list:")

    def test_a_tool_list_is_what_this_file_writes_or_it_is_refused(self):
        good = {"sha256": "ab" * 32, "tools": HINTS}
        self.assertIsNone(C.listing_problem(good))
        self.assertIsNone(C.listing_problem({"sha256": "0" * 64, "tools": {}}))
        for bad in (None, [], "x", {}, {"sha256": "ab" * 32}, dict(good, extra=1), dict(good, sha256="AB" * 32), dict(good, sha256="ab" * 31), dict(good, sha256="ab" * 32 + "\n"),
                    dict(good, tools=[]), dict(good, tools={"a b": "read-only"}), dict(good, tools={"x": "safe"}), dict(good, tools={"x": True}), dict(good, tools={"x": ["read-only"]})):
            self.assertIsNotNone(C.listing_problem(bad), bad)
        self.assertIsNone(C.parse_tool_list(""))
        self.assertEqual(C.parse_tool_list(json.dumps(good)), good)
        for text in ("{nope", "null", "false", json.dumps(dict(good, tools={"x": "safe"}))):
            self.assertIs(C.parse_tool_list(text), C.BAD, text)

    def test_import_and_seal_judge_keep_and_hash_the_listing(self):
        lib = os.path.join(self.conf, "packs")
        stored, rec = os.path.join(lib, "tools", "t-listed.json"), os.path.join(lib, "tools", "t-listed.pack.json")
        plain, rc = qargi(self.env, "tool", "import", self.pack, "--compatible", "any")
        self.assertEqual(rc, 0, plain)
        # a tool the listing does not mark read-only, unattended: refused with the listing, not without
        put(self.pack, json.dumps(dict(LISTED, tools=dict(LISTED["tools"], fetch_all="always_allow"))))
        self.assertEqual(qargi(self.env, "tool", "import", self.pack, "--compatible", "any")[1], 0)
        out, rc = qargi(self.env, "tool", "import", self.pack, "--compatible", "any", "--tool-list", self.listing)
        self.assertEqual(rc, 1, out)
        self.assertIn(NOT_READ_ONLY % "fetch_all" + "\n", out)
        self.assertIn("refused: fix the source first", out)
        self.assertNotIn("plan token", out)
        put(self.pack, json.dumps(LISTED))
        out, rc = qargi(self.env, "tool", "import", self.pack, "--compatible", "any", "--tool-list", self.listing)
        self.assertEqual(rc, 0, out)
        for line in ("NOTE: tools.wipe/everything: the server's tool listing marks it destructive (destructiveHint)", "NOTE: tools.unlisted: not in the server's tool listing",
                     "NOTE: tool listing %s: it marks 2 of the pack's 5 tools read-only" % self.sha(self.listing)[:16]):
            self.assertIn(line + "\n", out)
        tok = self.token(out)
        self.assertNotEqual(tok, self.token(plain), "the listing is part of what the token approves")
        self.assertFalse(os.path.exists(stored))
        out, rc = qargi(self.env, "tool", "import", self.pack, "--compatible", "any", "--tool-list", self.listing, "--plan", tok, "--approved", "test")
        self.assertEqual(rc, 0, out)
        r = jload(rec)
        self.assertEqual(r["tool_list"], {"sha256": self.sha(self.listing), "tools": HINTS})
        self.assertEqual((r["sha256"], C.content_hash(stored)), (tok, tok), "the shell and this file hash the pack with its tool_list alike")
        self.assertEqual(C.tool_list_of(stored), r["tool_list"])
        put(os.path.join(lib, "links.json"), json.dumps({"links": [{"pack": "tool:t-listed", "scope": "project", "project": "alpha"}]}))
        self.assertEqual(qargi(self.env, "tool", "check", "alpha", "build"), ("ok   tool:t-listed\n", 0))
        shown, _ = qargi(self.env, "tool", "show", "t-listed")
        self.assertIn("NOTE: tool listing %s: it marks 2 of the pack's 5 tools read-only\n" % self.sha(self.listing)[:16], shown)
        self.assertIn('"tool_list"', shown)
        # what the record keeps of the listing is approved: a hint changed by hand is drift
        put(rec, json.dumps(dict(r, tool_list={"sha256": r["tool_list"]["sha256"], "tools": dict(HINTS, fetch_all="read-only")})))
        out, rc = qargi(self.env, "tool", "check", "alpha", "build")
        self.assertEqual(rc, 1, out)
        self.assertIn("FAIL tool:t-listed: content changed since it was approved (drift: %s -> " % tok, out)
        put(rec, json.dumps(dict(r, tool_list={"sha256": "nope", "tools": {}})))
        out, rc = qargi(self.env, "tool", "check", "alpha", "build")
        self.assertEqual(rc, 1, out)
        self.assertIn("tool:t-listed: FAIL: tool_list: what the pack's record keeps of the server's tool listing is not what qargi wrote", out)
        put(rec, json.dumps(r))
        # an edit that lets an unmarked tool run unattended: seal keeps the record's listing and refuses
        put(stored, json.dumps(dict(LISTED, tools=dict(LISTED["tools"], unlisted="auto"))))
        out, rc = qargi(self.env, "tool", "seal", "t-listed")
        self.assertEqual(rc, 1, out)
        self.assertIn(NOT_READ_ONLY % "unlisted" + "\n", out)
        # the server's new listing marks it read-only: seal --tool-list replaces what the record keeps
        new = os.path.join(self.dir, "listing2.json")
        put(new, json.dumps({"tools": LISTING["tools"] + [{"name": "unlisted", "annotations": {"readOnlyHint": True}}]}))
        out, rc = qargi(self.env, "tool", "seal", "t-listed", "--tool-list", new)
        self.assertEqual(rc, 0, out)
        self.assertIn("tool listing changes: %s -> %s\n" % (self.sha(self.listing)[:16], self.sha(new)[:16]), out)
        out, rc = qargi(self.env, "tool", "seal", "t-listed", "--tool-list", new, "--plan", self.token(out), "--approved", "test")
        self.assertEqual(rc, 0, out)
        r2 = jload(rec)
        self.assertEqual(r2["tool_list"], {"sha256": self.sha(new), "tools": dict(HINTS, unlisted="read-only")})
        self.assertEqual(r2["sha256"], C.content_hash(stored))
        # a later seal without the option keeps it
        out, rc = qargi(self.env, "tool", "seal", "t-listed")
        self.assertEqual((rc, self.token(out)), (0, r2["sha256"]), out)
        self.assertEqual(qargi(self.env, "tool", "check", "alpha", "build"), ("ok   tool:t-listed\n", 0))

    def test_the_option_goes_with_tool_import_and_seal_and_names_a_file(self):
        for args in (("skill", "import", self.dir, "--compatible", "any"), ("skill", "seal", "x"), ("tool", "link", "x", "--scope", "user"), ("tool", "new", "x", "--compatible", "any"),
                     ("tool", "check", "alpha", "build"), ("packs", "seed")):
            out, rc = qargi(self.env, *args, "--tool-list", self.listing)
            self.assertEqual(rc, 2, args)
            self.assertIn("--tool-list FILE (the server's own tool listing) goes with qargi tool import and qargi tool seal", out)
        out, rc = qargi(self.env, "tool", "import", self.pack, "--compatible", "any", "--tool-list", os.path.join(self.dir, "nosuch.json"))
        self.assertEqual(rc, 1, out)
        self.assertIn("cannot be read", out)
        self.assertNotIn("plan token", out)
        out, rc = qargi(self.env, "tool", "import", self.pack, "--compatible", "any", "--tool-list", self.pack)
        self.assertEqual(rc, 1, out)
        self.assertIn("is not an MCP tools/list result", out)
        self.assertEqual(qargi(self.env, "tool", "import", self.pack, "--compatible", "any", "--tool-list")[1], 2)


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
