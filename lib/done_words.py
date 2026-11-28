#!/usr/bin/env python3
"""The command words of a DONE line: the one scanner behind `qargi local prepare` (lib/local.sh taskblock_check) and `qargi flow plan check`
(lib/run_plan.py), so that a DONE the one accepts is a DONE the other accepts.

  done_words.py LINE      the command words of LINE, one per line (nothing for a line with no command word)

A small scanner: a quoted string, a backquoted one, ${ } and $(( )) are one word; ; & | < > ( ) end a word; a redirection operator takes the next word as
its target, a number before it is the file descriptor. Then the rule: a word is a command word at the start of the line and after a separator or an
opening parenthesis, past NAME=value words and the keywords that a command follows (! { if then else elif do while until time). A name the line defines
(name() { ...; }) is no command word; the words of a [[ ]] test are not read. What the scanner cannot read it leaves out: at a case, function or select
command word, at (( and at an array assignment (NAME=( ) it reports the words found before that point and stops, so the rest of the line is accepted
on `bash -n` alone (a case pattern, an arithmetic for header and the elements of an array are not command words). That only lets a line through, it never
refuses one. Standard library only; run as python3 -I."""
import re
import sys

OPS = ";&|<>"
KEEP = {"!", "{", "if", "then", "else", "elif", "do", "while", "until", "time"}
ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*[+]?=")


def tokens(s):
    """The tokens of the line: ("w", word), ("redir",), ("sep",), ("open",), ("close",) and ("stop",) (a construct the scanner does not read)."""
    toks = []
    cur, has, i, n = "", False, 0, len(s)

    def flush():
        nonlocal cur, has
        if has:
            toks.append(("w", cur))
        cur, has = "", False

    while i < n:
        c = s[i]
        if c in " \t":
            flush()
            i += 1
        elif c == "#" and not has:
            break
        elif c == "\\":
            cur += s[i + 1:i + 2]
            has = True
            i += 2
        elif c == "'":
            j = s.find("'", i + 1)
            j = n if j < 0 else j
            cur += s[i + 1:j]
            has = True
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            cur += s[i + 1:j]
            has = True
            i = j + 1
        elif c == "`":
            j = s.find("`", i + 1)
            j = n if j < 0 else j
            cur += s[i:j + 1]
            has = True
            i = j + 1
        elif s.startswith("$((", i) or s.startswith("${", i):
            e = "))" if s[i + 1] == "(" else "}"
            j = s.find(e, i)
            j = n if j < 0 else j + len(e)
            cur += s[i:j]
            has = True
            i = j
        elif c == "$" and s.startswith("(", i + 1):
            cur += "$"
            has = True
            flush()
            i += 1
        elif c in OPS:
            if has and cur.isdigit() and c in "<>":
                cur, has = "", False
            flush()
            j = i
            while j < n and s[j] in OPS:
                j += 1
            run = s[i:j]
            i = j
            toks.append(("redir",) if ("<" in run or ">" in run) else ("sep",))
        elif c == "(" and (s.startswith("(", i + 1) or cur.endswith("=")):
            flush()
            toks.append(("stop",))
            break
        elif c == "(":
            flush()
            toks.append(("open",))
            i += 1
        elif c == ")":
            flush()
            toks.append(("close",))
            i += 1
        else:
            cur += c
            has = True
            i += 1
    flush()
    return toks


def command_words(s):
    """The command words of the line S, in order (a list of strings)."""
    toks = tokens(s)
    out, cmd, pend, defined, k = [], True, False, set(), 0
    while k < len(toks):
        t = toks[k]
        k += 1
        if t[0] == "redir":
            pend = True
        elif t[0] == "w":
            w = t[1]
            if pend:
                pend = False
            elif cmd and not ASSIGN.match(w) and w not in KEEP:
                if w in ("case", "function", "select"):
                    out.append(w)
                    break
                if w == "[[":
                    out.append(w)
                    while k < len(toks) and toks[k] != ("w", "]]"):
                        k += 1
                    cmd = False
                    continue
                if k + 1 < len(toks) and toks[k][0] == "open" and toks[k + 1][0] == "close":
                    defined.add(w)
                elif w and w not in defined:
                    out.append(w)
                cmd = False
        elif t[0] == "stop":
            out.append(":")
            break
        else:
            pend = False
            cmd = t[0] in ("sep", "open")
    return out


def main(argv):
    if len(argv) != 1:
        print("usage: done_words.py LINE", file=sys.stderr)
        return 2
    print("\n".join(command_words(argv[0])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
