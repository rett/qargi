"""The review of a pack directory: what the person reads before a provider, catalog or extension pack is stored, sealed or enabled, and
the rules a pack must meet to be stored at all. Stdlib only; a library for lib/provider.py and lib/conformance/library.py (it does
nothing when run).

  stage(src, dst)                 copy the regular files of src to dst (a new directory); symbolic links, special files and .git are not
                                  copied and are returned as failures
  scan(root, definition=None)     the review of a directory as a dict (below); definition is the pack's definition.json as a dict, when
                                  it has one: the files it names as executables are then executables whatever their mode
  lines(review, title)            the review as text, one line each
  executables(review)             {path: sha256} of every executable of the review
  policy(root)                    the text-only rules alone, as a list of failures: what a pack of any kind must meet (scan applies them too);
                                  `python3 -I review.py policy DIR` prints them as FAIL lines (exit 1 when there is one), and `review.py vis` is vis() on
                                  standard input, for a shell caller; for a file (a tool pack's JSON) it applies the same rules to the file and to every key and
                                  string of its JSON
  strings_problems(doc)           the failures for a parsed JSON document with a control, escape or bidi character in a key or a string, after the JSON
                                  escapes are decoded ("\\u001b" in a file is plain ASCII, the string it decodes to is not): [message]
  vis(text)                       text with control, escape, bidi and unpaired-surrogate characters written out (\\x1b, \\u202e): what is
                                  printed for a person to read, so that nothing in a pack can move the cursor, hide a line or reorder text

The rules (the owner's policy for what a pack may hold):
  * Only text. A file with a NUL byte or invalid UTF-8, a file that starts with the magic of an executable (ELF, Mach-O, PE) or of an
    archive or compressed file, is refused, whatever its name or mode. A pack bundles only examinable scripts; a vendor CLI is installed by
    the user and named in the definition (the review lists it as "needs on PATH").
  * No control characters: a file with a C0 or C1 control other than tab, newline and a carriage return before a newline, or with a bidi
    control (U+202A-202E, U+2066-2069, U+200E, U+200F, U+061C), or a file name with any, is refused. Such a character can erase or hide a
    line of the review or reorder text, so that what the person approves is not what is stored. The review is also printed through vis().
  * No symbolic links; at most 200 files, 1 MB a file and 2 MB in all.
  * Secrets (a token, a key) are refused; the review names the file and line, never the value.
  * Flagged, not refused, so that the person reads them: network commands and URLs, writes outside the run directory, reads of
    environment variables that look like secrets, eval/exec, scripts that fetch code and run it, base64 or hex blobs and very long lines
    (opaque content).
An executable is a file with an executable mode, a shebang line, a script suffix, or one the definition names (adapter, renderer command,
adapter verbs). The review lists each with its sha256, interpreter and first lines; the person approves them by name.

The review dict: files [{path, size, sha256, exec, text}], executables [{path, sha256, why, interpreter, head}], fail [msg], warn [msg],
urls [url], network ["path:line: text"], flags ["path:line: what"], secrets ["path:line"], needs_on_path [command], argv [text],
env_pass [name] (the variables of the caller's environment the runtime's command receives; a credential-looking one is also a warning), bytes, count."""
import hashlib
import json
import os
import re
import shutil
import stat

MAX_FILES = 200
MAX_FILE = 1000000
MAX_TOTAL = 2000000
LONG_LINE = 4000
SCRIPT_SUFFIX = (".sh", ".bash", ".zsh", ".py", ".pl", ".rb", ".js", ".mjs", ".lua", ".php", ".ps1", ".bat", ".cmd", ".awk", ".tcl")
MAGICS = ((b"\x7fELF", "an ELF executable"), (b"\xfe\xed\xfa\xce", "a Mach-O executable"), (b"\xfe\xed\xfa\xcf", "a Mach-O executable"),
          (b"\xce\xfa\xed\xfe", "a Mach-O executable"), (b"\xcf\xfa\xed\xfe", "a Mach-O executable"), (b"\xca\xfe\xba\xbe", "a Mach-O or Java class file"),
          (b"MZ", "a PE executable"), (b"PK\x03\x04", "a zip archive"), (b"PK\x05\x06", "a zip archive"), (b"\x1f\x8b", "a gzip file"),
          (b"BZh", "a bzip2 file"), (b"\xfd7zXZ\x00", "an xz file"), (b"7z\xbc\xaf\x27\x1c", "a 7z archive"), (b"Rar!\x1a\x07", "a rar archive"),
          (b"\x28\xb5\x2f\xfd", "a zstd file"), (b"!<arch>\n", "an ar archive"), (b"\x00asm", "a WebAssembly module"))
SECRET = re.compile(r"sk-ant-|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY|Bearer [A-Za-z0-9._-]{20,}")
URL = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&*+,;=%-]+")
NETWORK = re.compile(r"\b(curl|wget|nc|ncat|ssh|scp|sftp|telnet|ftp|rsync)\b|urllib|requests\.|httpx|aiohttp|http\.client|socket\.|/dev/tcp/")
FETCH_EXEC = re.compile(r"(curl|wget)[^|;&\n]*\|\s*(sudo\s+)?(sh|bash|zsh|python3?|perl|ruby|node)\b|(sh|bash|source|\.)\s+<\(\s*(curl|wget)|"
                        r"(exec|eval)\s*\(\s*[^)]*(urlopen|requests\.|httpx|\.read\(\))|base64\s+(-d|--decode)[^|\n]*\|\s*(sh|bash|python3?)")
EVAL_EXEC = re.compile(r"(^|[^A-Za-z0-9_.])(eval|exec)\b\s*[(\s\"']|shell\s*=\s*True|os\.system\(")
WRITES = re.compile(r">>?\s*(?!/dev/(null|stderr|stdout|fd/))(/|~|\$HOME|\$\{HOME\})|"
                    r"\b(rm|mv|cp|chmod|chown|ln|tee|install)\b[^\n|;&]*?\s(/etc|/usr|/var|/opt|/home|/root|~|\$HOME|\$\{HOME\})|"
                    r"\bopen\([^)]*[\"'][wax]b?\+?[\"']|\.write_text\(|\.write_bytes\(|shutil\.(rmtree|move|copy)|os\.(remove|unlink|rmdir|rename|makedirs)\(")
SECRET_ENV = re.compile(r"(environ\s*(\[|\.get\s*\()|getenv\s*\()\s*[\"'][A-Za-z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Za-z0-9_]*[\"']|"
                        r"\$\{?[A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*\}?")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL")
BLOB = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}|\b[0-9a-fA-F]{128,}\b")


# characters a reader's terminal or eye is moved by: C0 (but tab and newline) and C1 controls, DEL, bidi controls, line and paragraph
# separators, and the unpaired surrogates a file name that is not UTF-8 has under os.walk
_SHOW = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ud800-\udfff]")
_BAD_TEXT = re.compile("[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]|\r(?!\n)")
_BAD_NAME = re.compile("[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ud800-\udfff]")


def vis(text):
    """text with every control, escape, bidi or surrogate character written out (\\x1b, \\u202e, \\r), tab and newline kept: for anything printed
    for a person to read, and to approve."""
    if not isinstance(text, str):
        text = str(text)
    return _SHOW.sub(lambda m: "\\r" if m.group() == "\r" else "\\x%02x" % ord(m.group()) if ord(m.group()) < 256 else "\\u%04x" % ord(m.group()), text)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def stage(src, dst):
    """Copy the regular files and directories of src into the new directory dst (the executable bit kept, every other mode dropped).
    Returns the failures: a symbolic link or a special file is not copied; .git and .pack.json are left out without a word."""
    bad = []
    os.makedirs(dst, mode=0o700)
    for dp, dns, fns in os.walk(src, followlinks=False):
        rel = os.path.relpath(dp, src)
        dns[:] = sorted(d for d in dns if d != ".git")
        for d in list(dns):
            if os.path.islink(os.path.join(dp, d)):
                bad.append("%s is a symbolic link, which a pack may not hold" % os.path.normpath(os.path.join(rel, d)))
                dns.remove(d)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in sorted(fns):
            p = os.path.join(dp, f)
            r = os.path.normpath(os.path.join(rel, f))
            st = os.lstat(p)
            if f == ".pack.json" and rel == ".":
                continue
            if stat.S_ISLNK(st.st_mode):
                bad.append("%s is a symbolic link, which a pack may not hold" % r)
            elif not stat.S_ISREG(st.st_mode):
                bad.append("%s is not a regular file" % r)
            else:
                out = os.path.join(dst, r)
                shutil.copyfile(p, out)
                os.chmod(out, 0o700 if st.st_mode & 0o111 else 0o600)
    return bad


def _text_problem(raw):
    """(is_text, why, content): why names what the bytes are when they are not text; content is the decoded text when they are."""
    for magic, what in MAGICS:
        if raw.startswith(magic) and (magic != b"MZ" or b"\x00" in raw[:512]):
            return False, what, None
    if len(raw) > 262 and raw[257:262] == b"ustar":
        return False, "a tar archive", None
    if b"\x00" in raw:
        return False, "binary (it has a NUL byte)", None
    try:
        return True, None, raw.decode("utf-8")
    except UnicodeDecodeError:
        return False, "not UTF-8 text", None


def _control(rel, content):
    """The failure for the first control or bidi character of a text, or None. It names the line and the code point, never the character."""
    m = _BAD_TEXT.search(content)
    if not m:
        return None
    n = len(_BAD_TEXT.findall(content))
    return "%s:%d has a control or bidi character (U+%04X)%s, which can change what a reader sees; a pack holds plain text" % (
        vis(rel), content.count("\n", 0, m.start()) + 1, ord(m.group()), "" if n == 1 else " and %d more" % (n - 1))


def policy(root):
    """The text-only rules alone, for a pack of any kind (a skill's directory, say): [failure message]. A symbolic link or special file, a
    file that is a binary, an archive or not UTF-8 text, a control or bidi character in a file or in its name. Sizes and counts are the
    caller's own rules."""
    out = []
    for rel, p in _files(root):
        shown = vis(rel)
        if _BAD_NAME.search(rel):
            out.append("%s: the file name has a control or bidi character, which can change what a reader sees" % shown)
        if os.path.islink(p):
            out.append("%s is a symbolic link, which a pack may not hold" % shown)
            continue
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode):
            out.append("%s is not a regular file" % shown)
            continue
        if st.st_size > MAX_FILE:
            continue
        try:
            with open(p, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        text, why, content = _text_problem(raw)
        if not text:
            out.append("%s is %s: a pack holds only text files (scripts you can read)" % (shown, why))
            continue
        c = _control(rel, content)
        if c:
            out.append(c)
    return out


def strings_problems(doc, limit=10):
    """The failures for a parsed JSON document (a definition, a tool pack) that holds a control, escape, bidi or surrogate character in a key
    or in a string, whether it was written raw or as a JSON escape (\\u001b): the bytes of a file can be plain ASCII and still decode to a
    string that moves a reader's cursor, so the rule is applied to the parsed values. Tab and newline are refused too: a definition holds
    one-line text. Each message names the place and the code point, never the character; at most limit are returned, then a count."""
    found = []

    def say(path, what, m):
        found.append("%s: %s has a control or bidi character (U+%04X), which can change what a reader sees; a definition holds plain one-line text"
                     % (vis(path) or "the document", what, ord(m.group())))

    def walk(x, path):
        if isinstance(x, dict):
            for k, v in x.items():
                here = "%s.%s" % (path, k) if path else str(k)
                m = _BAD_NAME.search(k) if isinstance(k, str) else None
                if m:
                    say(here, "the key", m)
                walk(v, here)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, "%s[%d]" % (path, i))
        elif isinstance(x, str):
            m = _BAD_NAME.search(x)
            if m:
                say(path, "the value", m)
    walk(doc, "")
    if len(found) > limit:
        found = found[:limit] + ["and %d more strings with such characters" % (len(found) - limit)]
    return found


def _policy_file(path, label):
    """The text-only rules for one file; when it is JSON, also strings_problems() of what it decodes to."""
    out = []
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE + 1)
    except OSError:
        return out
    text, why, content = _text_problem(raw)
    if not text:
        return ["%s is %s: a pack holds only text files (scripts you can read)" % (label, why)]
    c = _control(label, content)
    if c:
        out.append(c)
    try:
        return out + strings_problems(json.loads(content))
    except (ValueError, RecursionError):
        return out


def _files(root):
    out = []
    for dp, dns, fns in os.walk(root, followlinks=False):
        dns.sort()
        for f in sorted(fns):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            if rel == ".pack.json":
                continue
            out.append((rel, p))
        for d in dns:
            if os.path.islink(os.path.join(dp, d)):
                out.append((os.path.relpath(os.path.join(dp, d), root), os.path.join(dp, d)))
    return sorted(out)


def _named(definition):
    """{path: why} of the files a definition names as executables (paths as written; a path that escapes the pack is reported by scan)."""
    out = {}

    def add(v, why):
        if isinstance(v, list) and v and isinstance(v[0], str):
            v = v[0]
        if isinstance(v, str) and v and "{" not in v:
            out[v] = why
    if not isinstance(definition, dict):
        return out
    add(definition.get("adapter"), "the adapter")
    for k, r in (definition.get("renderers") or {}).items() if isinstance(definition.get("renderers"), dict) else ():
        if isinstance(r, dict) and r.get("engine") == "command":
            add(r.get("command"), "the %s renderer" % k)
    adds = definition.get("adds") if isinstance(definition.get("adds"), dict) else {}
    for verb, path in (adds.get("adapter_verbs") or {}).items() if isinstance(adds.get("adapter_verbs"), dict) else ():
        add(path, "the adapter verb %s" % verb)
    for k, r in (adds.get("renderers") or {}).items() if isinstance(adds.get("renderers"), dict) else ():
        if isinstance(r, dict) and r.get("engine") == "command":
            add(r.get("command"), "the %s renderer" % k)
    return out


def _words(v):
    if isinstance(v, str):
        return v.split()[:1]
    if isinstance(v, list):
        return [x for x in v[:1] if isinstance(x, str)]
    return []


def needs_on_path(definition):
    """The commands the definition runs that the pack does not bundle: the first word of a dispatch argv and of the session launch line."""
    out = []
    if not isinstance(definition, dict):
        return out
    disp = definition.get("dispatch") if isinstance(definition.get("dispatch"), dict) else {}
    ses = definition.get("session") if isinstance(definition.get("session"), dict) else {}
    for w in _words(disp.get("argv")) + _words(ses.get("launch")):
        if w and "{" not in w and w not in out and not w.startswith(("./", "/")):
            out.append(w)
    return out


def _argv_text(definition):
    out = []
    disp = definition.get("dispatch") if isinstance(definition, dict) and isinstance(definition.get("dispatch"), dict) else {}
    for key in ("argv", "resume"):
        v = disp.get(key)
        v = v.get("argv") if key == "resume" and isinstance(v, dict) else v
        if isinstance(v, list):
            out.append("dispatch.%s: %s" % (key, " ".join(x if isinstance(x, str) else "<%s>" % ",".join(sorted(x)) if isinstance(x, dict) else str(x) for x in v)))
    ses = definition.get("session") if isinstance(definition, dict) and isinstance(definition.get("session"), dict) else {}
    if isinstance(ses.get("launch"), str):
        out.append("session.launch: %s" % ses["launch"])
    return out


def _env_pass(definition):
    """The variable names dispatch.env_pass lists (the caller's environment that the runtime's command receives), as written."""
    disp = definition.get("dispatch") if isinstance(definition, dict) and isinstance(definition.get("dispatch"), dict) else {}
    v = disp.get("env_pass")
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def scan(root, definition=None):
    r = {"files": [], "executables": [], "fail": [], "warn": [], "urls": [], "network": [], "flags": [], "secrets": [], "needs_on_path": [],
         "argv": [], "env_pass": [], "bytes": 0, "count": 0}
    files = _files(root)
    named = _named(definition)
    norm = {}
    for p, why in named.items():
        n = os.path.normpath(p)
        if os.path.isabs(p) or n == ".." or n.startswith("../") or n.startswith("~"):
            r["fail"].append("%s (%s) is not a path inside the pack" % (p, why))
        else:
            norm[n] = why
    r["count"] = len(files)
    if len(files) > MAX_FILES:
        r["fail"].append("more than %d files" % MAX_FILES)
    seen = set()
    for rel, p in files:
        shown = vis(rel)
        if _BAD_NAME.search(rel):
            r["fail"].append("%s: the file name has a control or bidi character, which can change what a reader sees" % shown)
        if os.path.islink(p):
            r["fail"].append("%s is a symbolic link, which a pack may not hold" % shown)
            continue
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode):
            r["fail"].append("%s is not a regular file" % shown)
            continue
        r["bytes"] += st.st_size
        if st.st_size > MAX_FILE:
            r["fail"].append("%s is larger than %d bytes" % (shown, MAX_FILE))
            continue
        try:
            with open(p, "rb") as f:
                raw = f.read()
        except OSError as e:
            r["fail"].append("%s cannot be read: %s" % (shown, e.strerror))
            continue
        text, why, content = _text_problem(raw)
        isx = bool(st.st_mode & 0o111)
        row = {"path": rel, "size": st.st_size, "sha256": sha256_bytes(raw), "exec": isx, "text": text}
        r["files"].append(row)
        if not text:
            r["fail"].append("%s is %s: a pack holds only text files (scripts you can read); install a vendor program yourself and name it in the definition" % (shown, why))
            continue
        ctrl = _control(rel, content)
        if ctrl:
            r["fail"].append(ctrl)
        shebang = content.startswith("#!")
        suffix = rel.lower().endswith(SCRIPT_SUFFIX)
        reason = None
        if rel in norm:
            reason = norm[rel]
        elif isx:
            reason = "executable mode"
        elif shebang:
            reason = "shebang"
        elif suffix:
            reason = "script suffix"
        if rel in norm:
            seen.add(rel)
        if reason:
            head = [ln[:120] for ln in content.splitlines()[:3]]
            interp = content.splitlines()[0][2:].strip() if shebang else None
            r["executables"].append({"path": rel, "sha256": row["sha256"], "why": reason, "interpreter": interp, "head": head, "mode_x": isx})
        _lines(rel, content, r)
    if r["bytes"] > MAX_TOTAL:
        r["fail"].append("more than %d bytes in all" % MAX_TOTAL)
    for n, why in sorted(norm.items()):
        if n not in seen and not any(f["path"] == n for f in r["files"]):
            r["fail"].append("%s (%s) is not in the pack" % (n, why))
    for n in sorted(norm):
        row = next((e for e in r["executables"] if e["path"] == n), None)
        if row is not None and not row["mode_x"]:
            r["warn"].append("%s (%s) has no executable mode, so it cannot be run as it is" % (n, norm[n]))
    r["urls"] = sorted(set(r["urls"]))[:15]
    r["needs_on_path"] = needs_on_path(definition)
    r["argv"] = _argv_text(definition)
    r["env_pass"] = _env_pass(definition)
    for n in r["env_pass"]:
        if SECRET_NAME.search(n.upper()):
            r["warn"].append("dispatch.env_pass hands %s to the command: the name looks like a credential, and it reaches everything that command does; approve it only if the "
                             "command needs it" % n)
    return r


def _lines(rel, content, r):
    for i, ln in enumerate(content.splitlines(), 1):
        at = "%s:%d" % (rel, i)
        if SECRET.search(ln):
            r["secrets"].append(at)
            r["fail"].append("%s looks like a secret (the value is not shown)" % at)
        r["urls"].extend(URL.findall(ln))
        shown = ln.strip()[:110]
        if NETWORK.search(ln):
            r["network"].append("%s: %s" % (at, shown))
        if FETCH_EXEC.search(ln):
            r["flags"].append("%s: fetches code and runs it: %s" % (at, shown))
        if EVAL_EXEC.search(ln):
            r["flags"].append("%s: eval or exec: %s" % (at, shown))
        if WRITES.search(ln):
            r["flags"].append("%s: writes files (maybe outside the run directory): %s" % (at, shown))
        if SECRET_ENV.search(ln):
            r["flags"].append("%s: reads an environment variable that looks like a secret: %s" % (at, shown))
        if len(ln) > LONG_LINE:
            r["flags"].append("%s: a line of %d characters (opaque content)" % (at, len(ln)))
        elif BLOB.search(ln):
            r["flags"].append("%s: a base64 or hex blob (opaque content)" % at)


def executables(review):
    return {e["path"]: e["sha256"] for e in review["executables"]}


def lines(review, title):
    """The review as text: files, every executable with what it is, URLs, network commands, flagged constructs, what is needed on the PATH,
    the argv templates, and the failures last. A failure line starts with FAIL."""
    out = ["== review of %s" % title]
    out.append("files: %d, %d bytes" % (review["count"], review["bytes"]))
    for f in review["files"][:60]:
        out.append("  %s  %s  %d bytes%s" % (f["sha256"][:12], f["path"], f["size"], "" if f["text"] else "  (NOT TEXT)"))
    if len(review["files"]) > 60:
        out.append("  ... %d more" % (len(review["files"]) - 60))
    if review["executables"]:
        out.append("executables (code that runs with your rights; approve each by name with --approve-exec):")
        for e in review["executables"]:
            out.append("  %s  sha256 %s  (%s%s)" % (e["path"], e["sha256"], e["why"], ", interpreter " + e["interpreter"] if e["interpreter"] else ""))
            for h in e["head"]:
                out.append("      | %s" % h)
    else:
        out.append("executables: none")
    if review["needs_on_path"]:
        out.append("needs on PATH (installed by you, not part of the pack): %s" % ", ".join(review["needs_on_path"]))
    for a in review["argv"]:
        out.append("runs: %s" % a)
    if review.get("env_pass"):
        out.append("environment handed to the command (env_pass): %s" % ", ".join(review["env_pass"]))
    if review["urls"]:
        out.append("URLs mentioned:")
        out.extend("  " + u for u in review["urls"])
    if review["network"]:
        out.append("network commands mentioned:")
        out.extend("  " + n for n in review["network"][:10])
    if review["flags"]:
        out.append("flagged constructs (read them before you approve):")
        out.extend("  " + n for n in review["flags"][:20])
    out.append("secret findings: %s" % (", ".join(review["secrets"]) if review["secrets"] else "none"))
    for w in review["warn"]:
        out.append("warn: %s" % w)
    for m in review["fail"]:
        out.append("FAIL: %s" % m)
    return [vis(ln) for ln in out]               # nothing a pack holds reaches the reader's terminal raw


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "policy" and (os.path.isdir(sys.argv[2]) or os.path.isfile(sys.argv[2])):
        found = policy(sys.argv[2]) if os.path.isdir(sys.argv[2]) else _policy_file(sys.argv[2], "the tool file")
        for m in found:
            print("FAIL: %s" % vis(m))
        sys.exit(1 if found else 0)
    if len(sys.argv) == 2 and sys.argv[1] == "vis":
        sys.stdout.write(vis(sys.stdin.buffer.read().decode("utf-8", "surrogateescape")))
        sys.exit(0)
    print("usage: review.py policy DIR|FILE | vis", file=sys.stderr)
    sys.exit(2)
