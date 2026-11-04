#!/usr/bin/env python3
"""The qargi documentation site generator (Python >= 3.11, standard library only).

  site.py build   --release V --source DIR --out DIR [--pages DIR] [--config FILE] [--url URL] [--allow-unreleased]
  site.py check   --release V --source DIR [--pages DIR] [--config FILE] [--url URL] [--allow-unreleased]
  site.py check-output DIR
  site.py diff    OLD NEW --source-old DIR --source-new DIR [--pages DIR]

--source is a checkout (or an extracted `git archive`) of the release: lib/commands.py, CHANGELOG.md, VERSION and
LICENSE are read from it. The reference pages (/reference/) and the releases page (/releases/) are generated from
commands.py and CHANGELOG.md; every other page is a hand page, a Markdown file in --pages (front matter: title,
description) converted by lib/site_md.py. `check` validates the hand pages against the source and writes nothing;
`build` runs the same checks and then writes the site; `check-output` validates a built tree; `diff` lists what
changed in the command line between two sources and which hand pages still name what is gone.

Exit status: 0 ok, 1 errors found (warnings never fail), 2 a usage error or a refusal (an unsafe path).
Run it as `python3 -I lib/site.py ...`: it loads its own parts by path and needs nothing installed.
"""
import argparse
import datetime
import difflib
import html
import importlib.util
import json
import os
import posixpath
import re
import shlex
import string
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "site", "templates")
CSS_FILE = os.path.join(HERE, "site", "site.css")
CSS_WARN_BYTES = 15 * 1024
MAX_PAGE_BYTES = 512 * 1024
MAX_STATIC_BYTES = 5 * 1024 * 1024
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
RESERVED = ("reference", "releases", "assets", "404")
FRONT_KEYS = ("title", "description", "doctype", "nav")
DOCTYPES = ("tutorial", "how-to", "reference", "explanation")
CODE_SHELL = ("bash", "sh", "shell", "console", "zsh")
SITE_NAME = "qargi"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MD = _load("qargi_site_md", "site_md.py")
esc = MD.esc


class Refusal(Exception):
    """An unsafe or unusable input: exit status 2."""


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def err(self, where, msg):
        self.errors.append("%s: %s" % (where, msg))

    def warn(self, where, msg):
        self.warnings.append("%s: %s" % (where, msg))

    def show(self, label, file=sys.stdout):
        for w in self.warnings:
            print("warning: " + w, file=file)
        for e in self.errors:
            print("error: " + e, file=file)
        print("%s: %d error(s), %d warning(s)" % (label, len(self.errors), len(self.warnings)), file=file)
        return 1 if self.errors else 0


# ------------------------------------------------------------------ paths
def _real(p):
    return os.path.realpath(p)


def _inside(p, root):
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def allowed_roots(source, extra):
    roots = [source, tempfile.gettempdir()] + list(extra)
    cwd = os.getcwd()
    if _real(cwd) != os.sep:
        roots.append(cwd)
    return [_real(r) for r in roots if r]


def safe_dir(path, roots, what):
    """The real path of an existing directory that lies inside one of the allowed roots."""
    rp = _real(path)
    if not os.path.isdir(rp):
        raise Refusal("%s %s is not a directory" % (what, path))
    if not any(_inside(rp, r) for r in roots):
        raise Refusal("%s %s is outside the allowed roots (the source tree, the current directory, the temporary directory, --allow-root): "
                      "refused" % (what, path))
    return rp


def safe_file(path, roots, what):
    rp = _real(path)
    if not os.path.isfile(rp):
        raise Refusal("%s %s is not a file" % (what, path))
    if not any(_inside(rp, r) for r in roots):
        raise Refusal("%s %s is outside the allowed roots: refused" % (what, path))
    return rp


def read_text(path, limit=MAX_PAGE_BYTES):
    if os.path.getsize(path) > limit:
        raise Refusal("%s is larger than %d bytes" % (path, limit))
    with open(path, "rb") as f:
        data = f.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise Refusal("%s is not UTF-8 text (%s)" % (path, e))


def read_tree(root, suffix):
    """Regular files under root with the suffix, as sorted relative paths; a symlink anywhere is a refusal."""
    out = []
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(dirs) + sorted(files):
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                raise Refusal("%s is a symbolic link: refused" % full)
        for name in sorted(files):
            if name.endswith(suffix):
                out.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
    return sorted(out)


def prepare_out(out, roots_forbidden):
    """--out must be absent or an empty directory, and must not contain the source or the pages."""
    p = os.path.abspath(out)
    rp = _real(os.path.dirname(p))
    final = os.path.join(rp, os.path.basename(p))
    if final == os.sep or final == _real(os.path.expanduser("~")):
        raise Refusal("--out %s: refused" % out)
    if os.path.lexists(final):
        if os.path.islink(final) or not os.path.isdir(final):
            raise Refusal("--out %s exists and is not a directory" % out)
        if os.listdir(final):
            raise Refusal("--out %s is not empty: give a new or empty directory" % out)
    for r in roots_forbidden:
        if r and _inside(r, final):
            raise Refusal("--out %s would contain %s: refused" % (out, r))
    os.makedirs(final, exist_ok=True)
    return final


class Writer:
    def __init__(self, root):
        self.root = root
        self.written = {}

    def write(self, rel, data):
        if rel.startswith("/") or ".." in rel.split("/") or not rel:
            raise Refusal("refusing to write %r" % rel)
        if rel in self.written:
            raise Refusal("two files would be written to %s" % rel)
        dest = os.path.join(self.root, *rel.split("/"))
        d = os.path.dirname(dest)
        os.makedirs(d, exist_ok=True)
        if not _inside(_real(d), self.root):
            raise Refusal("refusing to write outside the output directory: %s" % rel)
        with open(dest, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        self.written[rel] = True


# ------------------------------------------------------------------ the source
_LOADER = (
    "import json, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import commands as C\n"
    "keys = ('TAGLINE', 'INTRO', 'COMMANDS', 'GROUPS', 'TOPICS', 'ENVIRONMENT', 'FILES', 'WORKFLOW')\n"
    "print(json.dumps({k: getattr(C, k) for k in keys}))\n"
)


class Cmds:
    """The command line as the source describes it (lib/commands.py), loaded in a child process."""

    def __init__(self, data):
        self.tagline = data["TAGLINE"]
        self.intro = data["INTRO"]
        self.commands = data["COMMANDS"]
        self.groups = [(t, list(cs)) for t, cs in data["GROUPS"]]
        self.topics = data["TOPICS"]
        self.environment = data["ENVIRONMENT"]
        self.files = data["FILES"]
        self.workflow = data["WORKFLOW"]
        self.all_flags = set()
        for spec in self.commands.values():
            for o in spec.get("opts", []):
                self.all_flags.add(o["flag"])
            for v in self.verbs(spec).values():
                for o in v["opts"]:
                    self.all_flags.add(o["flag"])

    @staticmethod
    def verbs(spec):
        v = spec.get("verbs")
        return v if isinstance(v, dict) else {}

    def opts_of(self, spec, verb=None):
        if verb is not None:
            return {o["flag"]: o for o in self.verbs(spec)[verb]["opts"]}
        return {o["flag"]: o for o in spec.get("opts", [])}


def load_commands(source):
    lib = os.path.join(source, "lib")
    if not os.path.isfile(os.path.join(lib, "commands.py")):
        raise Refusal("%s has no lib/commands.py" % source)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"}
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", _LOADER, lib], capture_output=True, text=True, env=env, timeout=120)
    except subprocess.TimeoutExpired:
        raise Refusal("loading %s/commands.py timed out" % lib)
    if r.returncode != 0:
        raise Refusal("cannot load %s/commands.py: %s" % (lib, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "exit %d" % r.returncode))
    try:
        return Cmds(json.loads(r.stdout))
    except (ValueError, KeyError) as e:
        raise Refusal("lib/commands.py of %s does not describe the command line as expected (%s)" % (source, e))


_REL_HEAD = re.compile(r"^## \[([^\]]+)\](?: - (\d{4}-\d{2}-\d{2}))?[ ]*$")


class Source:
    def __init__(self, path, release, allow_unreleased, rep):
        self.path = path
        self.release = release
        self.cmds = load_commands(path)
        vf = os.path.join(path, "VERSION")
        self.version = read_text(vf, 100).strip() if os.path.isfile(vf) else ""
        if not re.match(r"^\d+\.\d+\.\d+$", release):
            raise Refusal("--release %r is not X.Y.Z" % release)
        self.unreleased = False
        if self.version != release:
            if not allow_unreleased:
                rep.err("VERSION", "the source is version %r, not --release %s (use --allow-unreleased to build a page set ahead of a release)"
                        % (self.version, release))
            self.unreleased = True
        cl = os.path.join(path, "CHANGELOG.md")
        self.sections = []      # (version, date or None, first_line, text)
        if os.path.isfile(cl):
            self._split(read_text(cl, 8 * 1024 * 1024))
        self.release_date = None
        for v, d, _, _ in self.sections:
            if v == release:
                self.release_date = d
        if self.release_date is None and not self.unreleased:
            rep.err("CHANGELOG.md", "no dated section [%s]" % release)
        self.license_id = None
        lf = os.path.join(path, "LICENSE")
        if os.path.isfile(lf):
            first = read_text(lf, 100000).split("\n", 1)[0].strip()
            if first == "MIT License":
                self.license_id = "MIT"

    def _split(self, text):
        lines = text.split("\n")
        cur = None
        for n, ln in enumerate(lines, 1):
            m = _REL_HEAD.match(ln)
            if m:
                if m.group(2):
                    try:
                        datetime.date.fromisoformat(m.group(2))
                    except ValueError:
                        raise Refusal("CHANGELOG.md:%d: %s is not a date" % (n, m.group(2)))
                cur = [m.group(1), m.group(2), n + 1, []]
                self.sections.append(cur)
            elif cur is not None:
                cur[3].append(ln)
        out = []
        for v, d, first, body in self.sections:
            while body and (re.match(r"^\[[^\]]+\]: ", body[-1]) or not body[-1].strip()):
                body.pop()
            out.append((v, d, first, "\n".join(body)))
        self.sections = out

    @property
    def stamp(self):
        return "qargi " + (self.release if not self.unreleased else "(unreleased)")


# ------------------------------------------------------------------ the site configuration
class Config:
    def __init__(self, data, where):
        if not isinstance(data, dict):
            raise Refusal("%s: not an object" % where)
        known = {"schema", "release", "url", "pages", "forbidden", "repo", "og_image", "name"}
        extra = set(data) - known
        if extra:
            raise Refusal("%s: unknown key(s) %s" % (where, ", ".join(sorted(extra))))
        self.data = data
        self.url = data.get("url")
        self.release = data.get("release")
        self.pages = data.get("pages", [])
        self.forbidden = data.get("forbidden", [])
        self.repo = data.get("repo")
        self.og_image = data.get("og_image")
        self.name = data.get("name", SITE_NAME)
        for k, t in (("pages", list), ("forbidden", list)):
            v = data.get(k, t())
            if not isinstance(v, t) or not all(isinstance(x, str) and x for x in v):
                raise Refusal("%s: %s must be a list of non-empty strings" % (where, k))
        for k in ("url", "release", "repo", "og_image", "name"):
            if data.get(k) is not None and not isinstance(data[k], str):
                raise Refusal("%s: %s must be a string" % (where, k))
        self.dir = None


def normalize_url(url, what="url"):
    u = urllib.parse.urlsplit(url or "")
    if u.scheme != "https" or not u.netloc or u.query or u.fragment or u.username or u.password:
        raise Refusal("%s %r must be an https:// address without a query or fragment" % (what, url))
    if re.search(r"[\s<>\"'\\]", url):
        raise Refusal("%s %r has characters that do not belong in a url" % (what, url))
    return url if url.endswith("/") else url + "/"


def find_config(args, pages_dir, roots):
    cand = []
    if args.config:
        cand = [args.config]
    elif pages_dir:
        cand = [os.path.join(pages_dir, "site.json"), os.path.join(pages_dir, "..", "site.json")]
    for c in cand:
        if os.path.isfile(c):
            rp = safe_file(c, roots, "config")
            try:
                cfg = Config(json.loads(read_text(rp, 1024 * 1024)), rp)
            except ValueError as e:
                raise Refusal("%s: not JSON (%s)" % (rp, e))
            cfg.dir = os.path.dirname(rp)
            return cfg
    if args.config:
        raise Refusal("config %s does not exist" % args.config)
    return None


# ------------------------------------------------------------------ pages
class Page:
    def __init__(self, path, kind, title, description, body, headings=(), crumbs=(), src=None):
        self.path = path                  # the url path below the site root: "" or "install/"
        self.kind = kind                  # home, hand, reference, releases, notfound
        self.title = title
        self.description = description
        self.body = body
        self.headings = list(headings)    # (level, id, text)
        self.crumbs = list(crumbs)        # (title, path) from the home page to this one, this one last
        self.src = src
        self.nav = title
        self.doctype = None
        self.doc = None
        self.lines_offset = 0
        self.lastmod = None
        self.published = None
        self.toc = True

    @property
    def file(self):
        if self.kind == "notfound":
            return "404.html"
        return self.path + "index.html"

    @property
    def ids(self):
        return {h[1] for h in self.headings}


def slug_ok(s):
    return all(re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", part) for part in s.split("/"))


def hrefs_to(html_text, fn):
    """Rewrite every site-root link (href="/...") in generated HTML with fn(path_with_fragment, no leading slash)."""
    def sub(m):
        return 'href="%s"' % esc(fn(html.unescape(m.group(1))[1:]))
    return re.sub(r'href="(/[^"]*)"', sub, html_text)


def git_dates(path):
    """(last commit date, first commit date) of a tracked, unmodified file, as YYYY-MM-DD, else (None, None)."""
    d, name = os.path.dirname(path), os.path.basename(path)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "HOME": "/nonexistent",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}

    def run(*a):
        try:
            r = subprocess.run(["git", "-C", d] + list(a), capture_output=True, text=True, env=env, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout if r.returncode == 0 else None
    st = run("status", "--porcelain", "--", name)
    if st is None or st.strip():
        return None, None
    last = run("log", "-1", "--format=%cs", "--", name)
    first = run("log", "--diff-filter=A", "--format=%cs", "--", name)
    ok = lambda s: s and re.match(r"^\d{4}-\d{2}-\d{2}$", s.strip().splitlines()[-1] if s.strip() else "")
    if not ok(last):
        return None, None
    return last.strip().splitlines()[0], (first.strip().splitlines()[-1] if ok(first) else None)


def gather_hand(pages_dir, rep):
    pages = []
    for rel in read_tree(pages_dir, ".md"):
        slug = rel[:-3]
        full = os.path.join(pages_dir, *rel.split("/"))
        if not slug_ok(slug):
            rep.err(rel, "page names are lower-case words joined by hyphens, in folders of the same kind")
            continue
        if slug == "index":
            path = ""
        else:
            path = slug + "/"
            if slug.split("/")[0] in RESERVED:
                rep.err(rel, "the name %s is reserved for generated pages" % slug.split("/")[0])
                continue
        try:
            text = read_text(full)
        except Refusal as e:
            rep.err(rel, str(e))
            continue
        try:
            meta, used = MD.parse_front_matter(text, FRONT_KEYS)
        except MD.MdError as e:
            rep.err("%s:%d" % (rel, e.line), e.msg)
            continue
        if not meta:
            rep.err(rel + ":1", "no front matter: start the file with --- title: ... description: ... ---")
            continue
        for k in ("title", "description"):
            if not meta.get(k):
                rep.err(rel + ":1", "front matter needs %s" % k)
        if "doctype" in meta and meta["doctype"] not in DOCTYPES:
            rep.err(rel + ":1", "doctype must be one of %s" % ", ".join(DOCTYPES))
        if not meta.get("title") or not meta.get("description"):
            continue
        body = "\n".join(text.split("\n")[used:])
        if not body.strip():
            rep.err(rel, "the page has no text")
            continue
        try:
            doc = MD.convert(body, start_level=2, first_line=used + 1)
        except MD.MdError as e:
            rep.err("%s:%d" % (rel, e.line), e.msg)
            continue
        p = Page(path, "home" if path == "" else "hand", meta["title"], meta["description"], doc.html,
                 [(lv, i, t) for lv, i, t, _ in doc.headings], src=full)
        p.rel = rel
        p.doc = doc
        p.raw = text
        p.nav = meta.get("nav") or meta["title"]
        p.doctype = meta.get("doctype")
        p.slug = slug
        pages.append(p)
    return pages


def h_html(level, sid, inner):
    return '<h%d id="%s">%s <a class="anchor" href="#%s" aria-label="Link to this section">#</a></h%d>' % (level, esc(sid), inner, esc(sid), level)


def code_block(text, lang="text", label=None):
    return '<pre class="code" tabindex="0" aria-label="%s"><code class="language-%s">%s</code></pre>' % (esc(label or lang + " code"), esc(lang), esc(text))


def table(head, rows):
    th = "".join('<th scope="col">%s</th>' % h for h in head)
    tr = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)
    return '<div class="table-wrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, tr)


# ---- the reference, from the command description
def argstr(args):
    out = []
    for a in args:
        name, kind = a[0], a[1]
        optional = a[2] if len(a) > 2 else False
        implied = (kind.split(":")[0] if isinstance(kind, str) else kind) == "project" and not optional
        out.append("[%s]" % name if (optional or implied) else name)
    return " ".join(out)


def has_project_arg(args):
    return any((a[1].split(":")[0] if isinstance(a[1], str) else a[1]) == "project" and not (a[2] if len(a) > 2 else False) for a in args)


def usage_of(cmd, spec, verb=None):
    vs = Cmds.verbs(spec)
    if verb:
        v = vs[verb]
        return "qargi %s %s%s" % (cmd, verb, (" " + argstr(v["args"])) if v["args"] else "") + (" [OPTIONS]" if v["opts"] else "")
    args = spec.get("usage", [])
    return "qargi %s%s%s" % (cmd, (" " + argstr(args)) if args else "", " [OPTIONS]" if spec.get("opts") else "")


def opt_table(opts):
    rows = []
    for o in opts:
        rows.append(["<code>%s</code>" % esc(o["flag"]), ("<code>%s</code>" % esc(o["arg"])) if o["arg"] else "", esc(o["help"])])
    return table(["Option", "Argument", "What it does"], rows)


def sentence(s):
    s = s.strip()
    return s if s.endswith((".", "!", "?")) else s + "."


class RefBuilder:
    def __init__(self, cmds):
        self.cmds = cmds
        self.used = set()

    def uid(self, base):
        if base in self.used:
            raise Refusal("reference anchor %r would be used twice" % base)
        self.used.add(base)
        return base

    def command(self, name):
        spec = self.cmds.commands[name]
        parts, heads = [], []
        sid = self.uid(name)
        heads.append((2, sid, "qargi " + name))
        parts.append(h_html(2, sid, "qargi " + esc(name)))
        parts.append('<p class="summary">%s</p>' % esc(sentence(spec["summary"])))
        if spec.get("desc"):
            parts.append("<p>%s</p>" % esc(spec["desc"]))
        vs = Cmds.verbs(spec)
        if vs:
            rows = [['<a href="#%s-%s"><code>%s</code></a>' % (esc(name), esc(v), esc(v)), esc(vd["summary"])] for v, vd in vs.items()]
            parts.append(table(["Verb", "What it does"], rows))
            for v, vd in vs.items():
                vid = self.uid("%s-%s" % (name, v))
                heads.append((3, vid, "qargi %s %s" % (name, v)))
                parts.append(h_html(3, vid, "qargi %s %s" % (esc(name), esc(v))))
                parts.append('<p class="usage"><code>%s</code></p>' % esc(usage_of(name, spec, v)))
                parts.append("<p>%s</p>" % esc(sentence(vd["summary"])))
                if vd["desc"]:
                    parts.append("<p>%s</p>" % esc(vd["desc"]))
                if has_project_arg(vd["args"]):
                    parts.append("<p>PROJECT can be left out inside the project's repository, or set QARGI_PROJECT.</p>")
                if vd["opts"]:
                    parts.append(opt_table(vd["opts"]))
                if vd["examples"]:
                    parts.append(code_block("\n".join(vd["examples"]), "bash", "example commands"))
        else:
            parts.append('<p class="usage"><code>%s</code></p>' % esc(usage_of(name, spec)))
            if spec.get("opts"):
                parts.append(opt_table(spec["opts"]))
            if spec.get("examples"):
                parts.append(code_block("\n".join(spec["examples"]), "bash", "example commands"))
        return "\n".join(parts), heads


def generated_pages(src, rep, repo=None):
    """The reference and releases pages from the source: a list of Page."""
    c = src.cmds
    pages = []
    ref_crumb = [("Home", ""), ("Reference", "reference/")]
    rb = RefBuilder(c)
    group_pages = []
    seen = set()
    for title, names in c.groups:
        slug = MD.slugify(title)
        if slug in seen or slug in ("topics", "files", "environment"):
            raise Refusal("two reference pages would be named %s" % slug)
        seen.add(slug)
        body, heads = [], []
        for n in names:
            if n not in c.commands:
                raise Refusal("the group %r names the command %r, which is not described" % (title, n))
            b, h = rb.command(n)
            body.append(b)
            heads += h
        desc = ('Reference for the "%s" group of qargi commands: every verb with its arguments, options and examples, generated from the release.' % title)
        group_pages.append((title, slug, names))
        pages.append(Page("reference/%s/" % slug, "reference", "Reference: " + title, desc, "\n".join(body), heads, ref_crumb + [("Reference: " + title, "reference/%s/" % slug)]))
    # topics
    body, heads = [], []
    body.append("<p>Each topic is also printed by <code>qargi help TOPIC</code>.</p>")
    for t, (ttitle, paras) in c.topics.items():
        sid = "topic-" + t
        heads.append((2, sid, ttitle))
        body.append(h_html(2, sid, esc(ttitle)))
        body += ["<p>%s</p>" % esc(p) for p in paras]
    pages.append(Page("reference/topics/", "reference", "Reference: help topics",
                      "The qargi help topics: the ideas behind the commands, such as roles, approvals, the guard, naming, memory and who may push, as qargi help prints them.",
                      "\n".join(body), heads, ref_crumb + [("Reference: help topics", "reference/topics/")]))
    # files
    rows = [["<code>%s</code>" % esc(p), esc(d)] for p, d in c.files]
    pages.append(Page("reference/files/", "reference", "Reference: files",
                      "The files qargi reads and writes in its configuration and state directories: the answers, registry, profiles, packs, audit log and collected runs.",
                      table(["Path", "What it holds"], rows) + '\n<p>Nothing is stored in a repository. See also <a href="/reference/topics/#topic-files">Where things are</a>.</p>',
                      [], ref_crumb + [("Reference: files", "reference/files/")]))
    pages[-1].toc = False
    rows = [["<code>%s</code>" % esc(k), esc(d)] for k, d in c.environment]
    pages.append(Page("reference/environment/", "reference", "Reference: environment",
                      "The environment variables qargi reads, such as QARGI_HOME, QARGI_CONF, QARGI_STATE and QARGI_PROJECT, with what each one changes and its default.",
                      table(["Variable", "What it changes"], rows), [], ref_crumb + [("Reference: environment", "reference/environment/")]))
    pages[-1].toc = False
    # the index
    body, heads = [], []
    body.append("<p>%s</p>" % esc(c.intro))
    body.append("<p>%s This reference is generated from the command description of %s, so it matches that release.</p>" % (esc(sentence(c.tagline)), esc(src.stamp)))
    for title, slug, names in group_pages:
        sid = "group-" + slug
        heads.append((2, sid, title))
        body.append(h_html(2, sid, '<a href="/reference/%s/">%s</a>' % (esc(slug), esc(title))))
        rows = [['<a href="/reference/%s/#%s"><code>%s</code></a>' % (esc(slug), esc(n), esc(n)), esc(c.commands[n]["summary"])] for n in names]
        body.append(table(["Command", "What it does"], rows))
    heads.append((2, "more", "Topics, files and environment"))
    body.append(h_html(2, "more", "Topics, files and environment"))
    body.append('<ul><li><a href="/reference/topics/">Help topics</a>: the ideas behind the commands.</li>'
                '<li><a href="/reference/files/">Files</a>: what qargi stores and where.</li>'
                '<li><a href="/reference/environment/">Environment</a>: the variables it reads.</li></ul>')
    heads.append((2, "typical-use", "Typical use"))
    body.append(h_html(2, "typical-use", "Typical use"))
    for t, lines in c.workflow:
        body.append("<p>%s</p>" % esc(t))
        body.append(code_block("\n".join(lines), "bash", "example commands"))
    pages.append(Page("reference/", "reference", "Command reference",
                      "The qargi command reference: every command, verb, argument and option, the help topics, files and environment variables, from the release it names.",
                      "\n".join(body), heads, ref_crumb[:1] + [("Command reference", "reference/")]))
    # releases
    body, heads, ids = [], [], set()
    released = [s for s in src.sections if s[0].lower() != "unreleased"]
    if not released:
        rep.err("CHANGELOG.md", "no released section to build the releases page from")
    for ver, date, first, text in released:
        sid = "v" + re.sub(r"[^0-9A-Za-z]+", "-", ver)
        ids.add(sid)
        heads.append((2, sid, ver))
        body.append(h_html(2, sid, esc(ver)))
        meta = []
        if date:
            meta.append("Released %s." % esc(date))
        if repo:
            meta.append('<a href="%s/releases/tag/%s">The GitHub release</a>' % (esc(repo), esc(urllib.parse.quote(ver, safe=""))))
        if meta:
            body.append('<p class="release-meta">%s</p>' % " ".join(meta))
        try:
            doc = MD.convert(text, start_level=3, id_prefix=sid + "-", ids=ids, first_line=first, literal=True)
        except MD.MdError as e:
            rep.err("CHANGELOG.md:%d" % e.line, e.msg)
            continue
        body.append(doc.html)
        heads += [(lv, i, t) for lv, i, t, _ in doc.headings]
    first_v = released[0][0] if released else "?"
    last_v = released[-1][0] if released else "?"
    pages.append(Page("releases/", "releases", "Releases",
                      "Release notes for qargi, from %s back to %s: what was added, changed, removed, fixed and secured in each version, from the changelog." % (first_v, last_v),
                      "\n".join(body), heads, [("Home", ""), ("Releases", "releases/")]))
    return pages


def build_model(args, rep):
    """The whole site as pages, with everything checked that can be checked without writing. Returns a Site."""
    source = _real(args.source)
    if not os.path.isdir(source):
        raise Refusal("--source %s is not a directory" % args.source)
    roots = allowed_roots(source, getattr(args, "allow_root", []) or [])
    pages_dir = safe_dir(args.pages, roots, "--pages") if args.pages else None
    cfg = find_config(args, pages_dir, roots)
    src = Source(source, args.release, args.allow_unreleased, rep)
    site = Site(src, cfg, roots)
    url = args.url or (cfg.url if cfg else None)
    if url:
        site.url = normalize_url(url)
    if cfg and cfg.release and cfg.release != args.release:
        rep.err("site.json", "release is %s but --release is %s" % (cfg.release, args.release))
    hand = gather_hand(pages_dir, rep) if pages_dir else []
    gen = generated_pages(src, rep, cfg.repo.rstrip("/") if cfg and cfg.repo else None)
    pages = {}
    for p in hand + gen:
        if p.path in pages:
            rep.err(getattr(p, "rel", p.path), "two pages would be built at /%s" % p.path)
            continue
        pages[p.path] = p
    if "" not in pages:
        pages[""] = default_home(src, hand)
    site.pages = pages
    # order: the home page, hand pages in the configured order, then the generated ones
    order = list(cfg.pages) if cfg else []
    hand_by_slug = {p.slug: p for p in hand if p.path}
    for s in order:
        if s != "index" and s not in hand_by_slug:
            rep.err("site.json", "pages lists %r, which is not a page in --pages" % s)
    listed = [hand_by_slug[s] for s in order if s in hand_by_slug]
    rest = sorted((p for p in hand if p.path and p not in listed), key=lambda p: p.slug)
    for p in rest:
        rep.warn(p.rel, "not listed in site.json pages; it is added at the end of the menu")
    site.hand_order = listed + rest
    for p in site.hand_order:
        p.crumbs = [("Home", ""), (p.title, p.path)]
    if "" in pages:
        pages[""].crumbs = [("Home", "")]
    for p in pages.values():
        if p.src:
            p.lastmod, p.published = git_dates(p.src)
        if not p.lastmod:
            p.lastmod = src.release_date
    pages["404"] = Page("404", "notfound", "Page not found", "The page you asked for is not part of the qargi documentation. Use the links below to reach the home page, the reference or the releases.", "")
    validate(site, hand, rep)
    return site


def default_home(src, hand):
    c = src.cmds
    items = ["<li><a href=\"/%s\">%s</a></li>" % (esc(p.path), esc(p.title)) for p in sorted(hand, key=lambda p: p.slug) if p.path]
    items += ['<li><a href="/reference/">Command reference</a></li>', '<li><a href="/releases/">Releases</a></li>']
    body = "<p>%s</p>\n<p>%s</p>\n<h2 id=\"pages\">Pages <a class=\"anchor\" href=\"#pages\" aria-label=\"Link to this section\">#</a></h2>\n<ul>%s</ul>" % (
        esc(c.intro), esc(sentence(c.tagline)), "".join(items))
    p = Page("", "home", "qargi documentation", "Documentation for qargi, which hands development tasks to sandboxed agents and takes the work back as patches you review and apply yourself.", body, [(2, "pages", "Pages")])
    p.toc = False
    return p


class Site:
    def __init__(self, src, cfg, roots):
        self.src = src
        self.cfg = cfg
        self.roots = roots
        self.url = None
        self.pages = {}
        self.hand_order = []
        self.static = {}     # relative path -> real path

    @property
    def name(self):
        return self.cfg.name if self.cfg else SITE_NAME


# ------------------------------------------------------------------ checking hand pages
PLACEHOLDER = re.compile(r"^(?:[A-Z][A-Z0-9_]*|.*[<>\[\]{}$|*].*|\.\.\.|\.\.\.)$")


def is_placeholder(tok):
    return bool(PLACEHOLDER.match(tok)) or tok.startswith("$")


def tokens_of(line):
    """Split one shell-like line into commands (lists of words) at ; & | and friends; raises ValueError."""
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    segs, cur = [], []
    for t in lex:
        if set(t) <= set(";&|()<>"):
            if t in ("<", ">", ">>", "<<", "<<<"):
                # a redirection ends the command's words; the target is not one
                segs.append(cur)
                cur = []
                nxt = next(lex, None)
                if nxt is None:
                    break
                continue
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    return [s for s in segs if s]


def check_words(cmds, words):
    """None, or a message, for the words after `qargi`."""
    if not words:
        return None
    t0 = words[0]
    if is_placeholder(t0) or t0 in ("--help", "-h", "--version"):
        return None
    if t0.startswith("-"):
        return "unknown option %s before the command name" % t0
    if t0 not in cmds.commands:
        near = difflib.get_close_matches(t0, list(cmds.commands), 1)
        return "qargi has no command '%s'%s" % (t0, " (did you mean '%s'?)" % near[0] if near else "")
    spec = cmds.commands[t0]
    rest = words[1:]
    if t0 == "help":
        for k, w in enumerate(rest[:2]):
            if is_placeholder(w) or w.startswith("-"):
                return None
            if k == 0:
                if w not in cmds.topics and w not in cmds.commands:
                    return "qargi help: no command or topic '%s'" % w
            else:
                vs = Cmds.verbs(cmds.commands.get(rest[0], {}))
                if rest[0] in cmds.commands and w not in vs:
                    return "qargi %s has no verb '%s'" % (rest[0], w)
        return None
    verbs = Cmds.verbs(spec)
    allowed = {}
    if verbs:
        if not rest:
            return None
        v = rest[0]
        if v in ("--help", "-h"):
            return None
        if v.startswith("-"):
            return "put the verb right after qargi %s (got %s)" % (t0, v)
        if is_placeholder(v):
            return None
        if v not in verbs:
            near = difflib.get_close_matches(v, list(verbs), 1)
            return "qargi %s has no verb '%s'%s; verbs: %s" % (t0, v, " (did you mean '%s'?)" % near[0] if near else "", ", ".join(verbs))
        allowed = cmds.opts_of(spec, v)
        rest = rest[1:]
        where = "qargi %s %s" % (t0, v)
    else:
        allowed = cmds.opts_of(spec)
        where = "qargi " + t0
    skip = False
    for w in rest:
        if skip:
            skip = False
            continue
        if not w.startswith("-") or w == "-" or re.match(r"^-\d", w) or is_placeholder(w):
            continue
        name = w.split("=", 1)[0]
        if name in ("--help", "-h"):
            continue
        if name not in allowed:
            near = difflib.get_close_matches(name, list(allowed), 1)
            return "%s has no option %s%s" % (where, name, " (did you mean %s?)" % near[0] if near else "")
        if allowed[name]["arg"] and "=" not in w:
            skip = True
    return None


def check_code(cmds, kind, text, line):
    """Yield (line, message) for the qargi commands and options in one code span or fenced block."""
    if kind == "span":
        t = text.strip()
        if t == "qargi" or t.startswith("qargi "):
            try:
                segs = tokens_of(t)
            except ValueError as e:
                yield line, "cannot read `%s` (%s)" % (t, e)
                return
            for seg in segs:
                if seg and seg[0] == "qargi":
                    msg = check_words(cmds, seg[1:])
                    if msg:
                        yield line, "`%s`: %s" % (t, msg)
        else:
            m = re.match(r"^(--[a-z0-9][a-z0-9-]*)(?:[= ]|$)", t)
            if m and m.group(1) not in cmds.all_flags and m.group(1) != "--help":
                near = difflib.get_close_matches(m.group(1), sorted(cmds.all_flags), 1)
                yield line, "no qargi command has the option %s%s" % (m.group(1), " (did you mean %s?)" % near[0] if near else "")
        return
    lang = kind.split(":", 1)[1]
    if lang not in CODE_SHELL:
        return
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        start = i
        cur = lines[i]
        while cur.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            cur = cur.rstrip()[:-1] + " " + lines[i].strip()
        i += 1
        s = cur.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("$ "):
            s = s[2:]
        if "qargi" not in s:
            continue
        try:
            segs = tokens_of(s)
        except ValueError as e:
            yield line + 1 + start, "cannot read the command line (%s)" % e
            continue
        for seg in segs:
            while seg and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[0]):
                seg = seg[1:]
            if seg and seg[0] == "qargi":
                msg = check_words(cmds, seg[1:])
                if msg:
                    yield line + 1 + start, msg


def split_target(url):
    path, _, frag = url.partition("#")
    return path, frag


def validate(site, hand, rep):
    cmds = site.src.cmds
    cfg = site.cfg
    pages = site.pages
    files = {"sitemap.xml", "robots.txt", "assets/site.css", ".nojekyll"}
    if cfg and cfg.dir:
        sd = os.path.join(cfg.dir, "static")
        if os.path.islink(sd):
            raise Refusal("%s is a symbolic link: refused" % sd)
        if os.path.isdir(sd):
            for rel in read_tree(sd, ""):
                if not re.match(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$", rel):
                    rep.err("static/" + rel, "file names use letters, digits, dot, hyphen and underscore")
                    continue
                full = os.path.join(sd, *rel.split("/"))
                if os.path.getsize(full) > MAX_STATIC_BYTES:
                    rep.err("static/" + rel, "larger than %d bytes" % MAX_STATIC_BYTES)
                    continue
                if rel in files or rel.endswith("/index.html") or rel == "404.html" or rel == "index.html":
                    rep.err("static/" + rel, "collides with a generated file")
                    continue
                site.static[rel] = full
                files.add(rel)
    if cfg and cfg.og_image and cfg.og_image not in site.static:
        rep.err("site.json", "og_image %r is not a file in static/" % cfg.og_image)
    titles, descs = {}, {}
    for p in hand:
        where = p.rel
        if len(p.description) < 120 or len(p.description) > 155:
            rep.warn(where, "description is %d characters; 120 to 155 reads best in search results" % len(p.description))
        full_title = p.title if p.kind == "home" else "%s · %s" % (p.title, site.name)
        if len(full_title) > 60:
            rep.warn(where, "the page title '%s' is %d characters; search results cut it near 60" % (full_title, len(full_title)))
        if p.title in titles:
            rep.err(where, "the title '%s' is also used by %s" % (p.title, titles[p.title]))
        titles[p.title] = where
        if p.description in descs:
            rep.warn(where, "the description is the same as %s" % descs[p.description])
        descs[p.description] = where
        # forbidden words
        for k, ln in enumerate(p.raw.split("\n"), 1):
            low = ln.lower()
            for w in (cfg.forbidden if cfg else []):
                if w.lower() in low:
                    rep.err("%s:%d" % (where, k), "contains the forbidden word '%s'" % w)
        # commands and options
        for line, kind, text in p.doc.code:
            for ln, msg in check_code(cmds, kind, text, line):
                rep.err("%s:%d" % (where, ln), msg)
        # links
        for line, url in p.doc.links:
            if site.url and url.startswith(site.url):
                rep.err("%s:%d" % (where, line), "link to %s: write the site path (/%s) so the generator can resolve it" % (url, url[len(site.url):]))
                continue
            if url.startswith(("https://", "http://", "mailto:")):
                continue
            path, frag = split_target(url)
            if path == "":
                if frag and frag not in p.ids:
                    rep.err("%s:%d" % (where, line), "link %s: no heading with that id on this page (ids: %s)" % (url, ", ".join(sorted(p.ids)) or "none"))
                continue
            key = path[1:]
            if key in files:
                if frag:
                    rep.err("%s:%d" % (where, line), "link %s: a fragment on a file" % url)
                continue
            if key not in pages or pages[key].kind == "notfound":
                known = sorted("/" + k for k in pages if k != "404")
                near = difflib.get_close_matches(path, known, 1)
                rep.err("%s:%d" % (where, line), "link %s: no such page%s" % (url, " (did you mean %s?)" % near[0] if near else ""))
                continue
            if frag and frag not in pages[key].ids:
                near = difflib.get_close_matches(frag, sorted(pages[key].ids), 1)
                rep.err("%s:%d" % (where, line), "link %s: page %s has no heading with id '%s'%s" % (url, path, frag, " (did you mean #%s?)" % near[0] if near else ""))
    if cfg and cfg.repo:
        try:
            normalize_url(cfg.repo, "site.json repo")
        except Refusal as e:
            rep.err("site.json", str(e))
    if cfg and cfg.og_image and not site.url:
        rep.warn("site.json", "og_image needs a url")


# ------------------------------------------------------------------ rendering
def tmpl(name):
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as f:
        return string.Template(f.read())


def rel_link(from_path, target):
    """A relative link from the page at from_path (a directory url path or "") to the site path target ("install/#x")."""
    path, frag = split_target(target)
    start = from_path.rstrip("/") or "."
    if path == "":
        rel = posixpath.relpath(".", start)
        rel = "./" if rel == "." else rel + "/"
    else:
        rel = posixpath.relpath(path.rstrip("/"), start)
        rel = rel + ("/" if path.endswith("/") else "")
    return rel + ("#" + frag if frag else "")


def json_ld(obj):
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def page_title(site, p):
    if p.kind == "home":
        return p.title
    return "%s · %s" % (p.title, site.name)


def render_page(site, p):
    url = site.url
    absolute = p.kind == "notfound"

    def L(target):
        return url + target if absolute else rel_link(p.path, target)
    cfg = site.cfg
    repo = cfg.repo.rstrip("/") if cfg and cfg.repo else None
    # navigation
    nav_items = [("Home", "")] + [(h.nav, h.path) for h in site.hand_order] + [("Reference", "reference/"), ("Releases", "releases/")]
    lis = []
    for label, path in nav_items:
        cur = (p.path == path) or (path == "reference/" and p.kind == "reference")
        lis.append('<li><a href="%s"%s>%s</a></li>' % (esc(L(path)), ' aria-current="page"' if cur else "", esc(label)))
    nav = "<ul>\n%s\n</ul>" % "\n".join(lis)
    # breadcrumb
    crumb = ""
    if len(p.crumbs) > 1:
        items = []
        for k, (t, path) in enumerate(p.crumbs):
            if k == len(p.crumbs) - 1:
                items.append('<li aria-current="page">%s</li>' % esc(t))
            else:
                items.append('<li><a href="%s">%s</a></li>' % (esc(L(path)), esc(t)))
        crumb = '<nav class="crumbs" aria-label="Breadcrumb"><ol>%s</ol></nav>' % "".join(items)
    # table of contents
    toc = ""
    h2 = [(i, t) for lv, i, t in p.headings if lv == 2]
    if p.toc and len(h2) >= 3:
        toc = '<details class="toc" open><summary>On this page</summary><ul>%s</ul></details>' % "".join(
            '<li><a href="#%s">%s</a></li>' % (esc(i), esc(t)) for i, t in h2)
    body = hrefs_to(p.body, L)
    # head
    title = page_title(site, p)
    canon = url + p.path
    head_robots, head_canon, social, ld = "", "", "", ""
    if p.kind == "notfound":
        head_robots = '<meta name="robots" content="noindex">'
        body = tmpl("404.html").substitute(home=esc(L("")), reference=esc(L("reference/")), releases=esc(L("releases/")))
    else:
        head_canon = '<link rel="canonical" href="%s">' % esc(canon)
        og = [("og:type", "website" if p.kind == "home" else "article"), ("og:title", title), ("og:description", p.description),
              ("og:url", canon), ("og:site_name", site.name)]
        tw = [("twitter:card", "summary_large_image" if cfg and cfg.og_image else "summary"), ("twitter:title", title), ("twitter:description", p.description)]
        if cfg and cfg.og_image:
            img = url + cfg.og_image
            og.append(("og:image", img))
            tw.append(("twitter:image", img))
        social = "\n".join(['<meta property="%s" content="%s">' % (k, esc(v)) for k, v in og] + ['<meta name="%s" content="%s">' % (k, esc(v)) for k, v in tw])
        ld = '<script type="application/ld+json">%s</script>' % json_ld(jsonld_for(site, p, canon, repo))
    # footer
    foot = ["<p>Checked against %s.</p>" % esc(site.src.stamp)]
    bits = []
    if site.src.license_id:
        bits.append("Licensed under the %s License." % esc(site.src.license_id))
    if repo:
        bits.append('<a href="%s">Source</a>' % esc(repo))
        issue = repo + "/issues/new?title=" + urllib.parse.quote("Docs: /" + p.path if p.kind != "notfound" else "Docs: broken link", safe="")
        bits.append('<a href="%s">Report a problem with this page</a>' % esc(issue))
    if bits:
        foot.append("<p>%s</p>" % " · ".join(bits))
    page = tmpl("page.html").substitute(
        title=esc(title), description=esc(p.description), robots=head_robots, canonical=head_canon,
        css=esc(L("assets/site.css")), social=social, jsonld=ld, home=esc(L("")), site_name=esc(site.name),
        stamp=esc(site.src.stamp), nav=nav, breadcrumb=crumb, h1=esc(p.title), toc=toc, body=body, footer="\n".join(foot))
    return page


def jsonld_for(site, p, canon, repo):
    url = site.url
    ctx = "https://schema.org"
    org = {"@type": "Organization", "name": SITE_NAME}
    if p.kind == "home":
        app = {"@context": ctx, "@type": "SoftwareApplication", "name": SITE_NAME, "description": p.description, "url": canon,
               "applicationCategory": "DeveloperApplication", "operatingSystem": "Linux", "softwareVersion": site.src.release,
               "author": org, "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"}}
        if site.src.license_id == "MIT":
            app["license"] = "https://opensource.org/licenses/MIT"
        if repo:
            app["downloadUrl"] = repo + "/releases"
        return app
    items = []
    for k, (t, path) in enumerate(p.crumbs, 1):
        items.append({"@type": "ListItem", "position": k, "name": t, "item": url + path})
    art = {"@type": "TechArticle", "headline": p.title, "description": p.description, "url": canon, "inLanguage": "en",
           "author": org, "isPartOf": {"@type": "WebSite", "name": site.name, "url": url},
           "about": {"@type": "SoftwareApplication", "name": SITE_NAME}}
    if p.lastmod:
        art["dateModified"] = p.lastmod
    if p.published:
        art["datePublished"] = p.published
    return {"@context": ctx, "@graph": [art, {"@type": "BreadcrumbList", "itemListElement": items}]}


def sitemap_xml(site):
    ET.register_namespace("", SITEMAP_NS)
    root = ET.Element("{%s}urlset" % SITEMAP_NS)
    for path in sorted(k for k in site.pages if k != "404"):
        p = site.pages[path]
        u = ET.SubElement(root, "{%s}url" % SITEMAP_NS)
        ET.SubElement(u, "{%s}loc" % SITEMAP_NS).text = site.url + p.path
        if p.lastmod:
            ET.SubElement(u, "{%s}lastmod" % SITEMAP_NS).text = p.lastmod
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def write_site(site, out):
    w = Writer(out)
    for key in sorted(site.pages):
        p = site.pages[key]
        w.write(p.file, render_page(site, p))
    with open(CSS_FILE, "rb") as f:
        css = f.read()
    w.write("assets/site.css", css)
    w.write("sitemap.xml", sitemap_xml(site))
    w.write("robots.txt", tmpl("robots.txt").substitute(sitemap=site.url + "sitemap.xml"))
    w.write(".nojekyll", b"")
    for rel, full in sorted(site.static.items()):
        with open(full, "rb") as f:
            w.write(rel, f.read())
    return w


# ------------------------------------------------------------------ check-output
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
LOCAL_SCHEMES = ("mailto:", "tel:", "data:")


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.ids = []
        self.links = []       # (line, tag, attr, value)
        self.headings = []    # (line, level, text)
        self.imgs_noalt = []
        self.meta = {}        # name or property -> content
        self.rels = {}        # rel -> href
        self.title = ""
        self.lang = None
        self.scripts = []
        self._cap = None
        self._script = None
        self._title = False

    def err(self, msg):
        self.errors.append((self.getpos()[0], msg))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        names = [k for k, _ in attrs]
        if len(set(names)) != len(names):
            self.err("<%s> repeats an attribute" % tag)
        if "id" in a:
            self.ids.append(a["id"])
            if not a["id"] or re.search(r"\s", a["id"]):
                self.err("id %r is empty or has whitespace" % a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        for attr in ("href", "src"):
            if attr in a and a[attr] is not None:
                self.links.append((self.getpos()[0], tag, attr, a[attr]))
        if tag == "img" and not a.get("alt") and "alt" not in a:
            self.imgs_noalt.append(self.getpos()[0])
        if tag == "meta":
            k = a.get("name") or a.get("property")
            if k:
                self.meta[k] = a.get("content", "")
        if tag == "link" and a.get("rel"):
            self.rels[a["rel"]] = a.get("href")
        if re.match(r"^h[1-6]$", tag):
            self._cap = [self.getpos()[0], int(tag[1]), ""]
        if tag == "script":
            self._script = [a.get("type", ""), ""]
        if tag == "title":
            self._title = True
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID:
            self.err("<%s/> is not a void element" % tag)
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID:
            self.err("</%s> closes a void element" % tag)
            return
        if not self.stack:
            self.err("</%s> has no open element" % tag)
            return
        top, line = self.stack[-1]
        if top != tag:
            self.err("</%s> closes <%s> opened on line %d" % (tag, top, line))
            if any(t == tag for t, _ in self.stack):
                while self.stack and self.stack[-1][0] != tag:
                    self.stack.pop()
                self.stack.pop()
            return
        self.stack.pop()
        if self._cap and re.match(r"^h[1-6]$", tag):
            self.headings.append((self._cap[0], self._cap[1], self._cap[2].strip()))
            self._cap = None
        if tag == "script" and self._script is not None:
            self.scripts.append(tuple(self._script))
            self._script = None
        if tag == "title":
            self._title = False

    def handle_data(self, data):
        if self._script is not None:
            self._script[1] += data
        elif self._cap is not None:
            self._cap[2] += data
        if self._title:
            self.title += data

    def close(self):
        super().close()
        for t, line in self.stack:
            self.errors.append((line, "<%s> is never closed" % t))


def parse_html(path):
    t = Tree()
    with open(path, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        t.errors.append((0, "not UTF-8"))
        return t
    t.feed(text)
    t.close()
    return t


def check_output(out):
    rep = Report()
    out = _real(out)
    if not os.path.isdir(out):
        raise Refusal("%s is not a directory" % out)
    files = {}
    for dirpath, dirs, fs in os.walk(out, followlinks=False):
        for n in fs + dirs:
            if os.path.islink(os.path.join(dirpath, n)):
                rep.err(os.path.relpath(os.path.join(dirpath, n), out), "a symbolic link in the output")
        for n in fs:
            full = os.path.join(dirpath, n)
            files[os.path.relpath(full, out).replace(os.sep, "/")] = full
    for need in ("index.html", "404.html", "sitemap.xml", "robots.txt", ".nojekyll", "assets/site.css"):
        if need not in files:
            rep.err(need, "missing from the output")
    trees = {}
    for rel, full in sorted(files.items()):
        # a page is index.html of a directory or 404.html; any other .html file is a verbatim static file
        if rel == "404.html" or rel == "index.html" or rel.endswith("/index.html"):
            trees[rel] = parse_html(full)
    if "assets/site.css" in files and os.path.getsize(files["assets/site.css"]) > CSS_WARN_BYTES:
        rep.warn("assets/site.css", "larger than %d bytes" % CSS_WARN_BYTES)
    site_url = None
    if "index.html" in trees:
        site_url = trees["index.html"].rels.get("canonical")
    if not site_url:
        rep.err("index.html", "the home page has no canonical link, so the site address is unknown")
    for rel, t in sorted(trees.items()):
        for line, msg in t.errors:
            rep.err("%s:%d" % (rel, line), msg)
        if t.lang != "en":
            rep.err(rel, "<html> needs lang=\"en\"")
        if not t.title.strip():
            rep.err(rel, "no <title>")
        desc = t.meta.get("description", "")
        if not desc:
            rep.err(rel, "no meta description")
        elif rel != "404.html" and not 120 <= len(desc) <= 155:
            rep.warn(rel, "meta description is %d characters; 120 to 155 reads best" % len(desc))
        if "viewport" not in t.meta:
            rep.err(rel, "no viewport meta")
        seen = set()
        for i in t.ids:
            if i in seen:
                rep.err(rel, "id '%s' is used more than once" % i)
            seen.add(i)
        h1 = [h for h in t.headings if h[1] == 1]
        if len(h1) != 1:
            rep.err(rel, "the page needs exactly one h1, has %d" % len(h1))
        last = 0
        for line, lv, text in t.headings:
            if last and lv > last + 1:
                rep.err("%s:%d" % (rel, line), "heading level jumps from h%d to h%d" % (last, lv))
            last = lv
        for line in t.imgs_noalt:
            rep.err("%s:%d" % (rel, line), "<img> without alt text")
        if rel == "404.html":
            if "noindex" not in t.meta.get("robots", ""):
                rep.err(rel, "the 404 page must be noindex")
        else:
            expect = (site_url or "") + (rel[:-len("index.html")] if rel.endswith("index.html") else rel)
            if t.rels.get("canonical") != expect:
                rep.err(rel, "canonical is %r, expected %r" % (t.rels.get("canonical"), expect))
            if t.meta.get("og:url") != expect:
                rep.err(rel, "og:url is %r, expected %r" % (t.meta.get("og:url"), expect))
            for k in ("og:title", "og:description", "og:type", "og:site_name", "twitter:card"):
                if not t.meta.get(k):
                    rep.err(rel, "no %s" % k)
            _check_jsonld(rel, t, rep, expect)
            if t.meta.get("og:image"):
                _check_target(rel, 0, t.meta["og:image"], site_url, files, trees, rep)
        for line, tag, attr, val in t.links:
            _check_target(rel, line, val, site_url, files, trees, rep, tag, attr)
    _check_sitemap(out, files, trees, site_url, rep)
    return rep


def _check_jsonld(rel, t, rep, canon):
    found = [s for ty, s in t.scripts if ty == "application/ld+json"]
    if not found:
        rep.err(rel, "no JSON-LD")
        return
    h1 = [h[2] for h in t.headings if h[1] == 1]
    for s in found:
        try:
            data = json.loads(s)
        except ValueError as e:
            rep.err(rel, "JSON-LD is not valid JSON (%s)" % e)
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else []
        types = [n.get("@type") for n in nodes if isinstance(n, dict)]
        if rel == "index.html":
            if "SoftwareApplication" not in types:
                rep.err(rel, "the home page needs SoftwareApplication JSON-LD")
        else:
            if "TechArticle" not in types or "BreadcrumbList" not in types:
                rep.err(rel, "JSON-LD needs TechArticle and BreadcrumbList")
        for n in nodes:
            if n.get("@type") == "TechArticle" and n.get("headline") not in h1:
                rep.err(rel, "TechArticle headline %r is not the page's h1 %r" % (n.get("headline"), h1))
            if n.get("@type") == "BreadcrumbList":
                pos = [i.get("position") for i in n.get("itemListElement", [])]
                if pos != list(range(1, len(pos) + 1)):
                    rep.err(rel, "BreadcrumbList positions are not 1..n")
                for i in n.get("itemListElement", []):
                    if i.get("name") is None or not str(i.get("item", "")).startswith("https://"):
                        rep.err(rel, "BreadcrumbList item needs a name and an https url")


def _local_target(rel, val, site_url):
    """(path in the output, is a directory, fragment) of a link; None when it leaves the site; an error string."""
    if val.startswith(LOCAL_SCHEMES):
        return None
    if val.lower().startswith("javascript:"):
        return "javascript: links are not allowed"
    path, _, frag = val.partition("#")
    path = path.split("?", 1)[0]
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", path) or path.startswith("//"):
        if site_url and path.startswith(site_url):
            rest = path[len(site_url):]
            if rest == "":
                return "", True, frag
            full = posixpath.normpath(rest)
            return ("" if full == "." else full), rest.endswith("/"), frag
        return None
    if path == "":
        return rel, False, frag
    if path.startswith("/"):
        return "link %s is root-relative; use a relative or absolute address" % val
    full = posixpath.normpath(posixpath.join(posixpath.dirname(rel), path))
    if full == ".." or full.startswith("../"):
        return "link leaves the site: %s" % val
    return ("" if full == "." else full), path.endswith("/") or full == ".", frag


def _check_target(rel, line, val, site_url, files, trees, rep, tag="", attr=""):
    where = "%s:%d" % (rel, line) if line else rel
    r = _local_target(rel, val, site_url)
    if r is None:
        return
    if isinstance(r, str):
        rep.err(where, r)
        return
    path, is_dir, frag = r
    if path == rel and not is_dir:
        target = rel
    elif is_dir:
        target = (path + "/" if path else "") + "index.html"
    else:
        target = path
        if (path + "/index.html") in files:
            rep.err(where, "link %s should end with / (the page lives at %s/)" % (val, path))
            return
    if target not in files:
        rep.err(where, "link %s: no such file %s in the output" % (val, target))
        return
    if frag and target.endswith(".html") and frag not in trees[target].ids:
        rep.err(where, "link %s: no element with id '%s' in %s" % (val, frag, target))


def _check_sitemap(out, files, trees, site_url, rep):
    if "sitemap.xml" not in files:
        return
    try:
        root = ET.parse(files["sitemap.xml"]).getroot()
    except ET.ParseError as e:
        rep.err("sitemap.xml", "not well-formed XML (%s)" % e)
        return
    if root.tag != "{%s}urlset" % SITEMAP_NS:
        rep.err("sitemap.xml", "the root element is not urlset in the sitemap namespace")
        return
    locs = []
    for u in root:
        loc = u.find("{%s}loc" % SITEMAP_NS)
        lm = u.find("{%s}lastmod" % SITEMAP_NS)
        if loc is None or not (loc.text or "").strip():
            rep.err("sitemap.xml", "a url without loc")
            continue
        locs.append(loc.text.strip())
        if lm is not None:
            try:
                d = datetime.date.fromisoformat(lm.text.strip())
                if d > datetime.date.today():
                    rep.err("sitemap.xml", "lastmod %s of %s is in the future" % (lm.text, loc.text))
            except ValueError:
                rep.err("sitemap.xml", "lastmod %r of %s is not YYYY-MM-DD" % (lm.text, loc.text))
        for ch in u:
            if ch.tag.split("}")[-1] in ("priority", "changefreq"):
                rep.warn("sitemap.xml", "%s is ignored by search engines; remove it" % ch.tag.split("}")[-1])
    if len(set(locs)) != len(locs):
        rep.err("sitemap.xml", "a url is listed twice")
    pages = {r for r in trees if r != "404.html"}
    want = set()
    for r in pages:
        want.add((site_url or "") + (r[:-len("index.html")] if r.endswith("index.html") else r))
    for loc in sorted(set(locs) - want):
        rep.err("sitemap.xml", "%s is listed but no page is built there" % loc)
    for loc in sorted(want - set(locs)):
        rep.err("sitemap.xml", "%s is a page but is not listed" % loc)
    if "robots.txt" in files:
        txt = open(files["robots.txt"], encoding="utf-8").read()
        sm = [ln.split(":", 1)[1].strip() for ln in txt.split("\n") if ln.lower().startswith("sitemap:")]
        if (site_url or "") + "sitemap.xml" not in sm:
            rep.err("robots.txt", "no Sitemap line for %ssitemap.xml" % (site_url or ""))
        if re.search(r"(?im)^disallow:\s*/\s*$", txt):
            rep.err("robots.txt", "disallows the whole site")


# ------------------------------------------------------------------ diff
def option_set(c):
    out = {}
    for name, spec in c.commands.items():
        vs = Cmds.verbs(spec)
        if vs:
            for v, vd in vs.items():
                out[(name, v)] = {o["flag"] for o in vd["opts"]}
        else:
            out[(name, None)] = {o["flag"] for o in spec.get("opts", [])}
    return out


def summaries(c):
    out = {}
    for name, spec in c.commands.items():
        out[(name, None)] = spec["summary"]
        for v, vd in Cmds.verbs(spec).items():
            out[(name, v)] = vd["summary"]
    return out


def fmt(k):
    return "qargi %s" % k[0] + (" " + k[1] if k[1] else "")


def run_diff(args):
    old, new = (_real(args.source_old), _real(args.source_new))
    for s in (old, new):
        if not os.path.isdir(s):
            raise Refusal("%s is not a directory" % s)
    co, cn = load_commands(old), load_commands(new)
    oo, on = option_set(co), option_set(cn)
    so, sn = summaries(co), summaries(cn)
    print("Changes in the command line, %s to %s" % (args.old, args.new))
    n = 0
    for k in sorted(set(so) - set(sn), key=lambda k: (k[0], k[1] or "")):
        label = "removed" if k[1] is not None else "removed command"
        print("  %s: %s" % (label, fmt(k)))
        n += 1
    for k in sorted(set(sn) - set(so), key=lambda k: (k[0], k[1] or "")):
        print("  added: %s" % fmt(k))
        n += 1
    for k in sorted(set(oo) & set(on), key=lambda k: (k[0], k[1] or "")):
        for f in sorted(oo[k] - on[k]):
            print("  option removed: %s %s" % (fmt(k), f))
            n += 1
        for f in sorted(on[k] - oo[k]):
            print("  option added: %s %s" % (fmt(k), f))
            n += 1
    for k in sorted(set(so) & set(sn), key=lambda k: (k[0], k[1] or "")):
        if so[k] != sn[k]:
            print("  summary changed: %s: %r -> %r" % (fmt(k), so[k], sn[k]))
            n += 1
    if n == 0:
        print("  none")
    rc = 0
    if args.pages:
        roots = allowed_roots(new, args.allow_root or [])
        pages_dir = safe_dir(args.pages, roots, "--pages")
        rep = Report()
        hand = gather_hand(pages_dir, rep)
        blocking = 0
        for p in hand:
            for line, kind, text in p.doc.code:
                for ln, msg in check_code(cn, kind, text, line):
                    print("  blocking: %s:%d: %s" % (p.rel, ln, msg))
                    blocking += 1
        for e in rep.errors:
            print("  error: " + e)
            blocking += 1
        print("%d hand page problem(s) against %s" % (blocking, args.new))
        rc = 1 if blocking else 0
    return rc


# ------------------------------------------------------------------ command line
def common(p):
    p.add_argument("--release", required=True, help="the release the source is, X.Y.Z")
    p.add_argument("--source", required=True, help="a checkout or extracted archive of that release")
    p.add_argument("--pages", help="the directory of hand pages (Markdown with front matter) and its site.json")
    p.add_argument("--config", help="the site.json (default: site.json in --pages or beside it)")
    p.add_argument("--url", help="the site address, https://...; overrides site.json url")
    p.add_argument("--allow-unreleased", action="store_true", help="accept a source whose VERSION is not --release")
    p.add_argument("--allow-root", action="append", default=[], help="another directory --pages and --config may be under")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="site.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    b = sub.add_parser("build", help="check and write the site")
    common(b)
    b.add_argument("--out", required=True, help="a new or empty directory")
    c = sub.add_parser("check", help="check the hand pages against the source; write nothing")
    common(c)
    o = sub.add_parser("check-output", help="validate a built tree")
    o.add_argument("dir")
    d = sub.add_parser("diff", help="the command line changes between two sources")
    d.add_argument("old")
    d.add_argument("new")
    d.add_argument("--source-old", required=True)
    d.add_argument("--source-new", required=True)
    d.add_argument("--pages")
    d.add_argument("--allow-root", action="append", default=[])
    args = ap.parse_args(argv)
    try:
        if args.verb == "check-output":
            return check_output(args.dir).show("check-output")
        if args.verb == "diff":
            return run_diff(args)
        rep = Report()
        site = build_model(args, rep)
        if args.verb == "build" and not site.url:
            raise Refusal("build needs the site address: --url, or url in site.json")
        if rep.errors or args.verb == "check":
            return rep.show("check")
        source_roots = [_real(args.source)] + ([_real(args.pages)] if args.pages else [])
        out = prepare_out(args.out, source_roots)
        write_site(site, out)
        rc = rep.show("build")
        print("built %d page(s) in %s" % (len([k for k in site.pages]), out))
        return rc
    except Refusal as e:
        print("site.py: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
