"""A strict converter for the Markdown subset the documentation site accepts (stdlib only).

It refuses what it does not support, with the line number, instead of rendering it wrongly. All text goes
through html.escape; no raw HTML is passed through, and there is no allowlist for it.

Supported
  front matter       a --- block of `key: value` lines at the top (parse_front_matter)
  headings           # to #### (ATX only); levels may not skip; the page's own h1 is the generator's
  paragraphs         lines joined; a blank line ends one
  fenced code        ``` with a language word (text for output); closed by ``` on its own line
  lists              `- ` bullets and `1. ` numbers, two levels deep at most, items indented under their text
  tables             pipe tables with a header, a separator row and rows of the same width
  block quotes       > lines (paragraphs and lists inside)
  rules              --- or *** or ___ alone on a line, after a blank line
  inline             `code`, **bold**, *italic*, _italic_, [text](url), backslash escapes of punctuation
  links              https:// http:// mailto:, /site/path/ (resolved by the generator) and #anchor

Refused (with a message that says what to write instead)
  raw HTML and < before a letter or / outside code, &entity; references, images, autolinks, reference
  links and footnotes, setext headings, indented code, ~~~ fences, a fence without a language, * and +
  bullets, lazy list continuation, a block that touches a paragraph without a blank line, lists nested
  deeper than two, headings in lists or quotes, tabs in indentation, unmatched * _ ` [ markers.
"""
import html
import re
import unicodedata


class MdError(Exception):
    def __init__(self, line, msg):
        super().__init__("line %d: %s" % (line, msg))
        self.line = line
        self.msg = msg


class Doc:
    """The result: html, headings [(level, id, text, line)], links [(line, url)],
    code [(line, kind, text)] with kind 'fence:LANG' or 'span', and the number of tables."""

    def __init__(self):
        self.html = ""
        self.headings = []
        self.links = []
        self.code = []
        self.tables = 0


def esc(s):
    return html.escape(s, quote=True)


def anchor_html(sid, text):
    """The link at the end of a heading; its name says which section it leads to."""
    return '<a class="anchor" href="#%s" aria-label="%s">#</a>' % (esc(sid), esc("Link to: " + text))


def pre_html(lang, text, label=None):
    """A code block that can be scrolled with the keyboard and has a name (role region, since a pre may not be named)."""
    return '<pre class="code" tabindex="0" role="region" aria-label="%s"><code class="language-%s">%s</code></pre>' % (esc(label or lang + " code"), esc(lang), esc(text))


def table_html(head_cells, body_rows):
    """A table inside a wrapper that can be scrolled with the keyboard."""
    return ('<div class="table-wrap" tabindex="0" role="region" aria-label="Table"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
            % (head_cells, body_rows))


def slugify(text):
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "section"


def parse_front_matter(text, allowed=None):
    """(dict, number of lines used). Front matter is `---`, `key: value` lines, `---`; a value may be
    wrapped in double quotes. Raises MdError for a block that never closes, a bad line, a repeated key or a
    key outside `allowed`. No front matter: ({}, 0)."""
    if text.startswith("\ufeff"):
        raise MdError(1, "the file starts with a byte order mark: save it as UTF-8 without one")
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return {}, 0
    meta = {}
    for n in range(1, len(lines)):
        ln = lines[n].rstrip()
        if ln == "---":
            return meta, n + 1
        if not ln.strip():
            continue
        m = re.match(r"^([a-z][a-z0-9_-]*):[ ]+(.*)$", ln)
        if not m:
            raise MdError(n + 1, "front matter lines are `key: value`")
        k, v = m.group(1), m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] == '"':
            v = v[1:-1].replace('\\"', '"')
        if k in meta:
            raise MdError(n + 1, "front matter key '%s' is repeated" % k)
        if allowed is not None and k not in allowed:
            raise MdError(n + 1, "front matter key '%s' is not allowed (allowed: %s)" % (k, ", ".join(sorted(allowed))))
        meta[k] = v
    raise MdError(1, "front matter is not closed with ---")


_FENCE = re.compile(r"^```(.*)$")
# a body line that starts (after block quote and list markers) with an HTML-like tag: a Kramdown (Jekyll) page reads it as a raw
# HTML block and shows the rest of the page as plain text
_LINE_PREFIX = re.compile(r"^(?:[> \t]*(?:(?:[-*+]|\d+[.)])[ \t]+)?)+")
_HTML_START = re.compile(r"^<(?:/?([A-Za-z][A-Za-z0-9-]*)|(!--)|[/!])")
INLINE_TAGS = ("a", "br", "code", "kbd", "sup", "sub")   # not details or summary: Kramdown reads them as block HTML
HTML_START_FIX = ("keep a code span that holds a placeholder on one line, or put the placeholder after other text, "
                  "so that no wrapped line begins with <")
_HEADING = re.compile(r"^(#{1,6})([ ]+(.*?))?([ ]+#+)?[ ]*$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})[ ]*$")
_SETEXT = re.compile(r"^(?:=+|-+)[ ]*$")
_BULLET = re.compile(r"^([-*+])([ ]+)(.*)$")
_ORDERED = re.compile(r"^(\d{1,9})([.)])([ ]+)(.*)$")
_TABLE_SEP = re.compile(r"^\|(?:[ ]*:?-+:?[ ]*\|)+[ ]*$")
_SCHEMES = ("https://", "http://", "mailto:")
_PUNCT = "\\`*_{}[]()#+-.!|<>~&\"'/:,;=?@$%^"


def html_starts(text, first_line=1, allow=INLINE_TAGS):
    """[(line, message)] for each line outside a fence that starts with an HTML-like tag (`<` and a letter, / or !), also behind
    block quote and list markers, except the inline tags in `allow` and comments."""
    found = []
    fence = False
    for k, ln in enumerate(text.split("\n")):
        rest = ln[_LINE_PREFIX.match(ln).end():]
        if rest.startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            continue
        m = _HTML_START.match(rest)
        if not m or m.group(2) or (m.group(1) or "").lower() in allow:
            continue
        found.append((first_line + k, "this line starts with \"%s\": a Kramdown (Jekyll) page reads it as the start of a raw HTML block and "
                                      "shows everything after it as plain text; %s" % (rest[:m.end()], HTML_START_FIX)))
    return found


class _Converter:
    def __init__(self, start_level, id_prefix, ids, max_heading, literal):
        self.literal = literal
        self.doc = Doc()
        self.start_level = start_level
        self.max_heading = max_heading
        self.prefix = id_prefix
        self.ids = ids if ids is not None else set()
        self.last_level = start_level - 1

    # ------------------------------------------------------------------ inline
    def inline(self, text, line):
        """(html, plain text) of a run of inline Markdown beginning on `line`."""
        out, plain, pos = self._inline(text, 0, None, line, False)
        return out, plain

    def _err(self, text, pos, line, msg):
        raise MdError(line + text.count("\n", 0, pos), msg)

    def _inline(self, s, i, closer, line, in_link):
        out, plain, n = [], [], len(s)
        buf = []

        def flush():
            if buf:
                t = "".join(buf)
                out.append(esc(t))
                plain.append(t)
                buf.clear()

        while i < n:
            c = s[i]
            if closer and s.startswith(closer, i) and self._can_close(s, i, closer):
                flush()
                return "".join(out), "".join(plain), i
            if c == "\\":
                if i + 1 < n and s[i + 1] in _PUNCT:
                    buf.append(s[i + 1])
                    i += 2
                    continue
                self._err(s, i, line, "a backslash escapes punctuation only; write \\\\ for a backslash")
            if c == "`":
                j = i
                while j < n and s[j] == "`":
                    j += 1
                run = s[i:j]
                k = s.find(run, j)
                while k != -1 and (s[k - 1:k] == "`" or s[k + len(run):k + len(run) + 1] == "`"):
                    k = s.find(run, k + 1)
                if k == -1:
                    self._err(s, i, line, "unclosed code span (a lone backtick: write \\`)")
                body = s[j:k].replace("\n", " ")
                if len(body) > 2 and body[0] == " " and body[-1] == " " and body.strip():
                    body = body[1:-1]
                flush()
                out.append("<code>%s</code>" % esc(body))
                plain.append(body)
                self.doc.code.append((line + s.count("\n", 0, i), "span", body))
                i = k + len(run)
                continue
            if c == "<" and not self.literal and i + 1 < n and (s[i + 1].isalpha() or s[i + 1] in "/!?"):
                self._err(s, i, line, "raw HTML and autolinks are not supported; put placeholders like <name> in `code`")
            if c == "&" and not self.literal and re.match(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);", s[i:i + 12]):
                self._err(s, i, line, "character references are not supported; write the character itself")
            if c == "!" and s.startswith("![", i):
                self._err(s, i, line, "images are not supported")
            if c == "[":
                if s.startswith("[^", i):
                    self._err(s, i, line, "footnotes are not supported")
                if in_link:
                    self._err(s, i, line, "a link cannot contain a link")
                flush()
                h, p, i = self._link(s, i, line)
                out.append(h)
                plain.append(p)
                continue
            if c == "]":
                self._err(s, i, line, "a stray ] (write \\] for the character)")
            if c == "*" or c == "_":
                dbl = s.startswith(c * 2, i)
                delim = c * 2 if dbl else c
                prev = s[i - 1] if i > 0 else " "
                nxt = s[i + len(delim)] if i + len(delim) < n else " "
                if c == "_" and (prev.isalnum() or nxt.isspace()):
                    buf.append(delim)       # snake_case, or a lone underscore: a literal
                    i += len(delim)
                    continue
                if nxt.isspace():
                    if prev.isspace():
                        buf.append(delim)       # " * " between spaces: a literal
                        i += len(delim)
                        continue
                    self._err(s, i, line, "unmatched %s (write \\%s for the character)" % (delim, c))
                flush()
                h, p, j = self._inline(s, i + len(delim), delim, line + s.count("\n", 0, i), in_link)
                if j >= n or not s.startswith(delim, j):
                    self._err(s, i, line, "unclosed %s (write \\%s for the character)" % (delim, c))
                tag = "strong" if dbl else "em"
                out.append("<%s>%s</%s>" % (tag, h, tag))
                plain.append(p)
                i = j + len(delim)
                continue
            buf.append(c)
            i += 1
        flush()
        return "".join(out), "".join(plain), i

    @staticmethod
    def _can_close(s, i, closer):
        if closer in ("**", "*", "_", "__"):
            prev = s[i - 1] if i > 0 else " "
            if prev.isspace():
                return False
            if closer in ("_", "__"):
                nxt = s[i + len(closer)] if i + len(closer) < len(s) else " "
                return not nxt.isalnum()
            if closer == "*" and s.startswith("**", i):
                return False
        return True

    def _link(self, s, i, line):
        h, p, j = self._inline(s, i + 1, "]", line + s.count("\n", 0, i), True)
        if j >= len(s) or s[j] != "]":
            self._err(s, i, line, "unclosed [ (write \\[ for the character)")
        if not s.startswith("](", j):
            self._err(s, i, line, "bracketed text that is not an inline link [text](url); reference links are not supported (write \\[ for the character)")
        k = s.find(")", j + 2)
        if k == -1:
            self._err(s, i, line, "unclosed link target")
        url = s[j + 2:k]
        ln = line + s.count("\n", 0, i)
        self._check_url(url, ln)
        self.doc.links.append((ln, url))
        if not p.strip():
            self._err(s, i, line, "a link needs text")
        return '<a href="%s">%s</a>' % (esc(url), h), p, k + 1

    def _check_url(self, url, line):
        if not url or re.search(r"[\s<>\"'`\\\x00-\x1f\x7f()\u200e\u200f\u202a-\u202e\u2066-\u2069]", url):
            raise MdError(line, "link target %r has a space, quote, parenthesis, control character or text-direction character (titles and wrapped urls are not supported)" % url)
        if url.startswith("//"):
            raise MdError(line, "link target %r is protocol-relative; write https://..." % url)
        if url.startswith(_SCHEMES) or url.startswith("#") or url.startswith("/"):
            return
        raise MdError(line, "link target %r: use https://, http://, mailto:, a site path starting with / (such as /install/) or #anchor" % url)

    # ------------------------------------------------------------------ blocks
    def blocks(self, lines, depth, in_quote):
        """lines: list of (lineno, text). Returns a list of (kind, html)."""
        out = []
        i, n = 0, len(lines)
        while i < n:
            ln, t = lines[i]
            if not t.strip():
                i += 1
                continue
            if re.match(r"^[ ]*\t", t):
                raise MdError(ln, "tabs are not supported in indentation")
            if t.startswith(" "):
                raise MdError(ln, "unexpected indentation (list items are indented under their text; code uses fences)")
            m = _FENCE.match(t)
            if m:
                i = self._fence(lines, i, m, out)
                continue
            if t.startswith("~~~"):
                raise MdError(ln, "use ``` fences, not ~~~")
            if t.startswith("#"):
                if depth or in_quote:
                    raise MdError(ln, "headings are not supported inside lists and quotes")
                out.append(("h", self._heading(ln, t)))
                i += 1
                continue
            if _HR.match(t):
                out.append(("hr", "<hr>"))
                i += 1
                continue
            if t.startswith(">"):
                i = self._quote(lines, i, depth, out)
                continue
            if t.startswith("|"):
                i = self._table(lines, i, out)
                continue
            if _BULLET.match(t) or _ORDERED.match(t):
                i = self._list(lines, i, depth, in_quote, out)
                continue
            if t.startswith("<") and not self.literal:
                raise MdError(ln, "raw HTML is not supported; " + HTML_START_FIX)
            if re.match(r"^\[[^\]]+\]:[ ]", t):
                raise MdError(ln, "reference link definitions are not supported; write [text](url)")
            i = self._paragraph(lines, i, out, depth > 0)
        return out

    def _fence(self, lines, i, m, out):
        ln = lines[i][0]
        lang = m.group(1).strip()
        if not lang:
            raise MdError(ln, "a fenced block needs a language (bash for commands, text for output)")
        if not re.match(r"^[a-z0-9+_-]{1,20}$", lang):
            raise MdError(ln, "the fence language is one lower-case word, got %r" % lang)
        j = i + 1
        body = []
        while j < len(lines) and lines[j][1].rstrip() != "```":
            body.append(lines[j])
            j += 1
        if j >= len(lines):
            raise MdError(ln, "fenced block is never closed")
        text = "\n".join(t for _, t in body)
        for _, t in body:
            if t.startswith("```"):
                raise MdError(ln, "fence inside a fence")
        self.doc.code.append((ln, "fence:" + lang, text))     # the text starts on line ln + 1
        out.append(("pre", pre_html(lang, text)))
        return j + 1

    def _heading(self, ln, t):
        m = _HEADING.match(t)
        if not m or not m.group(3):
            raise MdError(ln, "a heading is # to #### then a space then text")
        level = len(m.group(1))
        if level < self.start_level:
            raise MdError(ln, "heading level %d: this page's title is the h1, start at %s" % (level, "#" * self.start_level))
        if level > self.max_heading:
            raise MdError(ln, "heading level %d is deeper than the supported %d" % (level, self.max_heading))
        if level > self.last_level + 1:
            raise MdError(ln, "heading level jumps from %d to %d" % (self.last_level, level))
        self.last_level = level
        h, plain, _ = self._inline(m.group(3), 0, None, ln, False)
        base = self.prefix + slugify(plain)
        sid, k = base, 2
        while sid in self.ids:
            sid = "%s-%d" % (base, k)
            k += 1
        self.ids.add(sid)
        self.doc.headings.append((level, sid, plain, ln))
        return '<h%d id="%s">%s %s</h%d>' % (level, esc(sid), h, anchor_html(sid, plain), level)

    def _is_block_start(self, t):
        return bool(_BULLET.match(t) or _ORDERED.match(t) or t.startswith((">", "|")) or _HR.match(t) or _SETEXT.match(t))

    def _paragraph(self, lines, i, out, in_item):
        start = lines[i][0]
        parts = []
        while i < len(lines):
            ln, t = lines[i]
            if not t.strip():
                break
            if parts:
                if _FENCE.match(t) or t.startswith("#") or (in_item and (_BULLET.match(t) or _ORDERED.match(t))):
                    break
                if _SETEXT.match(t) and not _BULLET.match(t):
                    raise MdError(ln, "setext headings and a rule right under text are not supported; use # headings and a blank line before ---")
                if self._is_block_start(t):
                    raise MdError(ln, "put a blank line before this list, table, quote or rule")
                if t.startswith("<") and not self.literal:
                    raise MdError(ln, "raw HTML is not supported; " + HTML_START_FIX)
            if t.startswith(" "):
                raise MdError(ln, "unexpected indentation (lazy continuation is not supported)")
            parts.append(t.rstrip())
            i += 1
        text = "\n".join(parts)
        h, _ = self.inline(text, start)
        out.append(("p", "<p>%s</p>" % h))
        return i

    def _quote(self, lines, i, depth, out):
        inner = []
        j = i
        while j < len(lines) and lines[j][1].startswith(">"):
            t = lines[j][1][1:]
            if t.startswith(" "):
                t = t[1:]
            inner.append((lines[j][0], t))
            j += 1
        if j < len(lines) and lines[j][1].strip():
            if not (_FENCE.match(lines[j][1]) or lines[j][1].startswith("#")):
                raise MdError(lines[j][0], "put a blank line after a quote (lazy continuation is not supported)")
        blocks = self.blocks(inner, depth, True)
        out.append(("quote", "<blockquote>%s</blockquote>" % "".join(h for _, h in blocks)))
        return j

    def _cells(self, ln, t):
        t = t.rstrip()
        if not t.endswith("|") or t.endswith("\\|") and not t.endswith("\\\\|"):
            raise MdError(ln, "a table row starts and ends with |")
        body = t[1:-1]
        cells, cur, k = [], [], 0
        while k < len(body):
            ch = body[k]
            if ch == "\\" and k + 1 < len(body) and body[k + 1] == "|":
                cur.append("|")
                k += 2
                continue
            if ch == "\\" and k + 1 < len(body):
                cur.append(body[k:k + 2])
                k += 2
                continue
            if ch == "|":
                cells.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
            k += 1
        cells.append("".join(cur).strip())
        return cells

    def _table(self, lines, i, out):
        ln = lines[i][0]
        if i + 1 >= len(lines) or not _TABLE_SEP.match(lines[i + 1][1].rstrip()):
            raise MdError(ln, "a line starting with | must be a table: a header row, then a |---|---| row")
        head = self._cells(ln, lines[i][1])
        sep = self._cells(lines[i + 1][0], lines[i + 1][1])
        if len(sep) != len(head):
            raise MdError(lines[i + 1][0], "the separator row has %d cells, the header %d" % (len(sep), len(head)))
        align = []
        for c in sep:
            c = c.replace(" ", "")
            align.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "left" if c.startswith(":") else "")
        rows = []
        j = i + 2
        while j < len(lines) and lines[j][1].strip():
            if not lines[j][1].startswith("|"):
                raise MdError(lines[j][0], "a table row starts with | (end the table with a blank line)")
            cells = self._cells(lines[j][0], lines[j][1])
            if len(cells) != len(head):
                raise MdError(lines[j][0], "this row has %d cells, the header %d" % (len(cells), len(head)))
            rows.append((lines[j][0], cells))
            j += 1

        def cell(tag, text, a, line, scope=""):
            h, _ = self.inline(text, line)
            st = ' style="text-align:%s"' % a if a else ""
            return "<%s%s%s>%s</%s>" % (tag, scope, st, h, tag)
        th = "".join(cell("th", c, align[k], ln, ' scope="col"') for k, c in enumerate(head))
        trs = "".join("<tr>%s</tr>" % "".join(cell("td", c, align[k], rl) for k, c in enumerate(cs)) for rl, cs in rows)
        self.doc.tables += 1
        out.append(("table", table_html(th, trs)))
        return j

    def _list(self, lines, i, depth, in_quote, out):
        if depth >= 2:
            raise MdError(lines[i][0], "lists nested deeper than two levels are not supported")
        first = lines[i][1]
        ordered = bool(_ORDERED.match(first))
        items = []     # (start_line, [(lineno, text)])
        start_num = None
        j = i
        while j < len(lines):
            ln, t = lines[j]
            mb, mo = _BULLET.match(t), _ORDERED.match(t)
            m = mo if ordered else mb
            if not m:
                if mb or mo:
                    raise MdError(ln, "do not mix bullets and numbers in one list; separate them with a paragraph")
                break
            if not ordered:
                if m.group(1) != "-":
                    raise MdError(ln, "use - for bullets (not %s)" % m.group(1))
                width = 2
                if len(m.group(2)) != 1:
                    raise MdError(ln, "one space after the bullet")
                rest = m.group(3)
            else:
                if m.group(2) != ".":
                    raise MdError(ln, "numbers are written 1. 2. 3.")
                if len(m.group(3)) != 1:
                    raise MdError(ln, "one space after the number")
                width = len(m.group(1)) + 2
                rest = m.group(4)
                if start_num is None:
                    start_num = int(m.group(1))
            if not rest.strip():
                raise MdError(ln, "an empty list item")
            body = [(ln, rest)]
            j += 1
            while j < len(lines):
                l2, t2 = lines[j]
                if not t2.strip():
                    # blank: the item goes on only when the next non-blank line is indented under it
                    k = j
                    while k < len(lines) and not lines[k][1].strip():
                        k += 1
                    if k < len(lines) and lines[k][1].startswith(" " * width):
                        body.extend((x, "") for x, _ in lines[j:k])
                        j = k
                        continue
                    break
                if t2.startswith(" " * width):
                    body.append((l2, t2[width:]))
                    j += 1
                    continue
                if t2.startswith(" "):
                    raise MdError(l2, "list continuation lines are indented %d spaces, under the item text" % width)
                if _BULLET.match(t2) or _ORDERED.match(t2):
                    break
                if _FENCE.match(t2) or t2.startswith("#"):
                    raise MdError(l2, "put a blank line after the list")
                raise MdError(l2, "lazy continuation is not supported: indent %d spaces to continue the item, or leave a blank line" % width)
            while body and not body[-1][1].strip():
                body.pop()
            items.append(body)
            # a blank line followed by another item of the same list keeps the list going
            k = j
            while k < len(lines) and not lines[k][1].strip():
                k += 1
            if k < len(lines) and k > j:
                nt = lines[k][1]
                if (ordered and _ORDERED.match(nt)) or (not ordered and _BULLET.match(nt)):
                    j = k
                    continue
                break
            if k == j and j < len(lines):
                continue
        lis = []
        for body in items:
            loose = any(not t.strip() for _, t in body)
            blocks = self.blocks(body, depth + 1, in_quote)
            if blocks and blocks[0][0] == "p" and not loose:
                blocks[0] = ("p", blocks[0][1][3:-4])
            lis.append("<li>%s</li>" % "".join(h for _, h in blocks))
        tag = "ol" if ordered else "ul"
        attr = ' start="%d"' % start_num if ordered and start_num != 1 else ""
        out.append((tag, "<%s%s>%s</%s>" % (tag, attr, "".join(lis), tag)))
        return j


def convert(text, start_level=2, id_prefix="", ids=None, first_line=1, max_heading=4, literal=False):
    """Convert Markdown to a Doc. `start_level` is the first heading level allowed (the page's h1 belongs to the
    generator); `ids` is a set of heading ids already used on the page; `first_line` numbers the first line.
    `literal` is for a trusted file written for another renderer (the changelog): `<` and `&` are then plain
    text, still escaped. Raw HTML is never passed through."""
    if "\r" in text:
        raise MdError(first_line, "use LF line endings")
    if "\x00" in text:
        raise MdError(first_line, "a NUL character")
    c = _Converter(start_level, id_prefix, ids, max_heading, literal)
    lines = [(first_line + k, t) for k, t in enumerate(text.split("\n"))]
    blocks = c.blocks(lines, 0, False)
    c.doc.html = "\n".join(h for _, h in blocks)
    return c.doc
