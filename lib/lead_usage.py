#!/usr/bin/env python3
"""The lead session's context: how much of it is in use, and whether it is safe to compact.

  lead_usage.py usage         [--project P] [--session ID | --transcript FILE] [--json]
  lead_usage.py compact-check [--project P] [--advise] [--json]
  lead_usage.py advice        [--project P] [--feature NAME]        (the one line the stage verbs print)
  lead_usage.py open-runs     [--project P] --feature NAME          (the open runs of feature/NAME, one per line: run, slug, role, state; exit 1 when there are some)

The lead's own context is the cost the owner cares about most, so qargi measures it and says when a compact (the owner's /compact; no
hook can run it) is safe. Where the transcripts are and how to read the context in use from one come from the project's local runtime
(resources.transcripts of lib/providers/NAME.json, lib/provider.py): a directory of JSON-line files named for the session id, and
JSON pointers that pick the last assistant turn and add up its input, cache-read and cache-creation tokens. The window is the answer
lead.context_window, else the one the runtime's definition (resources.transcripts.windows) gives for the model id of that turn, else the
definition's single window, which is only assumed: then every line that shows a percentage adds "(window assumed N; set lead.context_window)".
--json says which in window_source: "answer", "model" or "assumed". Nothing is written; a transcript that cannot be found or read is "unknown" (exit 0).

compact-check exits 0 when a compact is safe and 1 when it is not, naming every reason: a local run prepared and not verified, a run
verified and not applied (or applied and not merged), a merge waiting in the conflicts directory, a whole-suite run in progress
(a live pid file in $STATE/busy, which feature verify and release verify keep), a handoff note (the file `marshal handoff --write` records
in $STATE/handoff/PROJECT.json) older than the last merge of the ref journal, and a release or hotfix branch that is open. Either way it
prints the restart block: what the lead reads again after the compact to resume from stored state. --advise adds the verdict on the
context: "compact advised" from 50% and "compact strongly advised" from 70% (when safe; when not, it says what to clear first).

advice prints one line when the context is at or above the answer lead.compact_advice_pct (default 40; 0 disables): that a compact is
safe now, or why not. With --feature NAME it prints only when no open run of feature/NAME is left. It never fails.

Environment: QARGI_LEAD (the session id, which names the transcript), QARGI_LEAD_NOW (epoch seconds; tests). Run through lib/lead.sh;
python3 -I, standard library only."""
import argparse, importlib.util, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
ADVISED, STRONG = 50, 70          # percent of the window: compact advised, strongly advised
DEFAULT_PCT = 40                  # lead.compact_advice_pct
SCAN_MAX = 64 * 1024 * 1024       # bytes of a transcript read from the end while looking for the last assistant turn
BLOCK = 1024 * 1024
MERGE_VERBS = (":merge", ":sync", ":finish")


class Soft(Exception):
    """Something that makes the usage unknown: said in one line, never an error."""


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def now():
    v = os.environ.get("QARGI_LEAD_NOW")
    try:
        return int(float(v)) if v else int(time.time())
    except ValueError:
        return int(time.time())


def clean(s):
    return re.sub(r"[\x00-\x1f\x7f]", "", s) if isinstance(s, str) else ""


def answers_of(conf, project):
    try:
        with open(os.path.join(conf, "projects", project + ".json")) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def lead_answer(answers, key, default, low):
    """lead.KEY of the answers as an integer of at least low, else the default."""
    v = (answers.get("lead") or {}).get(key) if isinstance(answers.get("lead"), dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= low else default


def git(repo, *args):
    if not repo:
        return None
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", repo] + list(args), capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, env=env, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def repo_of(answers):
    r = (answers.get("repo") or {}).get("path") if isinstance(answers.get("repo"), dict) else ""
    return os.path.expanduser(r) if isinstance(r, str) else ""


# ---- the transcript ------------------------------------------------------------------------------------------------

def pointer(rec, ptr):
    """The value at the JSON pointer in rec, or None."""
    node = rec
    for part in ptr.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def turn_of(line, rule):
    """(tokens, model) when the line is a turn the rule picks and that used tokens, else None."""
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    if not isinstance(rec, dict):
        return None
    if any(pointer(rec, k) != v for k, v in (rule.get("select") or {}).items()):
        return None
    if any(pointer(rec, k) == v and pointer(rec, k) is not None for k, v in (rule.get("skip") or {}).items()):
        return None
    counts = pointer(rec, rule.get("tokens") or "")
    if not isinstance(counts, dict):
        return None
    total = 0
    for f in rule.get("fields") or ():
        n = counts.get(f)
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            total += n
    if total <= 0:
        return None
    model = pointer(rec, rule["model"]) if rule.get("model") else None
    return total, (clean(model)[:80] if isinstance(model, str) else "")


def last_turn(path, rule):
    """(tokens, model) of the last turn the rule picks, reading the file from its end; None when there is none."""
    with open(path, "rb") as f:
        size = f.seek(0, os.SEEK_END)
        pos, tail, scanned = size, b"", 0
        while pos > 0 and scanned < SCAN_MAX:
            step = min(BLOCK, pos)
            pos -= step
            f.seek(pos)
            chunk = f.read(step) + tail
            scanned += step
            lines = chunk.split(b"\n")
            tail = lines[0] if pos > 0 else b""         # the first piece may be the end of a line that starts earlier
            for raw in reversed(lines[1:] if pos > 0 else lines):
                if raw.strip():
                    t = turn_of(raw.decode("utf-8", "replace"), rule)
                    if t:
                        return t
    return None


def checkouts(a, answers):
    """The directories a session of this lead may have been started in: here, the work tree around here, the repository."""
    cwd = os.path.realpath(a.cwd or os.getcwd())
    out = [cwd]
    top = git(cwd, "rev-parse", '--show-toplevel')
    if top and top.strip():
        out.append(os.path.realpath(top.strip()))
    repo = repo_of(answers)
    if repo:
        out.append(os.path.realpath(repo))
    return list(dict.fromkeys(out))


def find_transcript(a, answers, tr_for):
    """-> (path, session id, why not): the transcript to read."""
    if a.transcript:
        p = os.path.abspath(a.transcript)
        return (p, os.path.basename(p).rsplit(".", 1)[0], "") if os.path.isfile(p) else (None, "", "no such file %s" % clean(a.transcript))
    want = a.session or os.environ.get("QARGI_LEAD") or ""
    if a.session and not SESSION_RE.match(a.session):
        raise Soft("%s is not a session id" % clean(a.session))
    seen = []
    for co in checkouts(a, answers):
        tr = tr_for(co)
        d, ext = tr["dir"], tr["ext"]
        seen.append(d)
        if want and SESSION_RE.match(want):
            p = os.path.join(d, want + ext)
            if os.path.isfile(p):
                return p, want, ""
        if a.session:
            continue
        try:
            files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(ext) and os.path.isfile(os.path.join(d, n))]
        except OSError:
            continue
        if files:
            p = max(files, key=lambda x: (os.path.getmtime(x), x))
            return p, os.path.basename(p)[:-len(ext)], ""
    if a.session:
        return None, a.session, "no transcript of session %s in %s" % (clean(a.session), clean(seen[0]) if seen else "?")
    return None, "", "no transcript under %s" % (clean(seen[0]) if seen else "?")


def measure(a, conf):
    """-> the usage as a dict; known is False with why when it cannot be read."""
    out = {"known": False, "tokens": None, "window": None, "window_source": "", "percent": None, "model": "", "session": "", "transcript": "", "bytes": None, "why": ""}
    try:
        project = a.project
        if not project:
            raise Soft("no project, so no runtime to read a transcript with (--project NAME)")
        answers = answers_of(conf, project)
        if not answers:
            raise Soft("no stored answers for project %s" % clean(project))
        P = load("provider")
        try:
            prov = P.provider_of(answers, "local", project)
            tr_for = lambda co: P.transcripts(prov, co, conf=conf)             # noqa: E731
            tr0 = tr_for(os.getcwd())
        except P.ProviderError as e:
            raise Soft(clean(str(e)))
        out["window"] = lead_answer(answers, "context_window", None, 1000)
        out["window_source"] = "answer" if out["window"] else ""
        path, sid, why = find_transcript(a, answers, tr_for)
        out["session"] = sid
        if not path:
            raise Soft(why)
        out["transcript"] = path
        out["bytes"] = os.path.getsize(path)
        t = last_turn(path, tr0["usage"])
        if not t:
            raise Soft("no turn with a token count in the transcript yet")
        out["tokens"], out["model"] = t
        if not out["window"]:
            out["window"], out["window_source"] = P.transcript_window(tr0, out["model"])
        out["percent"] = round(t[0] * 100.0 / out["window"], 1)
        out["known"] = True
    except Soft as e:
        out["why"] = str(e)
    except OSError as e:
        out["why"] = "cannot read the transcript (%s)" % (e.strerror or e.__class__.__name__)
    return out


def human_bytes(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return "%d %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def assumed(u):
    """The words that keep a percentage of a guessed window from reading as fact; empty when the window is the answer's or the model's."""
    return " (window assumed %s; set lead.context_window)" % format(u["window"], ",") if u.get("window_source") == "assumed" else ""


def show_usage(u):
    if not u["known"]:
        print("context: unknown (%s)" % u["why"])
        if u["transcript"]:
            print("transcript: %s" % clean(u["transcript"]))
        return
    print("context: %s of %s tokens in use (%s%%)%s" % (format(u["tokens"], ","), format(u["window"], ","), ("%.1f" % u["percent"]).rstrip("0").rstrip("."), assumed(u)))
    print("transcript: %s (%s)" % (clean(u["transcript"]), human_bytes(u["bytes"])))
    if u["model"]:
        print("model: %s" % u["model"])


# ---- is it safe to compact -----------------------------------------------------------------------------------------

def registry(state):
    out = []
    try:
        with open(os.path.join(state, "local-runs.jsonl"), errors="replace") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and isinstance(r.get("run"), str):
                    out.append(r)
    except OSError:
        pass
    return out


def merged(repo, tip):
    """True when the commit tip is on a local branch other than agent/*."""
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", tip or ""):
        return False
    refs = git(repo, "for-each-ref", "--contains=" + tip, "--format=%(refname)", "--", "refs/heads") or ""
    return any(r and not r.startswith("refs/heads/agent/") for r in refs.split())


def open_runs(state, repo, url):
    """The runs of this project that still need the lead: [(run dir, slug, role, base, what)]."""
    rp = os.path.realpath(repo) if repo else ""
    res = []
    for r in registry(state):
        d = r["run"]
        if not os.path.isdir(d) or r.get("cleaned") or r.get("closed"):
            continue                                      # cleaned, or closed (local close --applied-by-am: taken in by hand)
        same = (r.get("repo") and rp and os.path.realpath(r["repo"]) == rp) or (r.get("url") and url and r["url"] == url)
        if not same:
            continue
        base, slug, role = clean(str(r.get("base") or "")), clean(str(r.get("slug") or "")), clean(str(r.get("ability") or r.get("role") or ""))
        if os.path.exists(os.path.join(d, "applied")):
            try:
                tip = open(os.path.join(d, "applied"), errors="replace").read().split()[1]
            except (OSError, IndexError):
                tip = ""
            if not merged(repo, tip):
                res.append((d, slug, role, base, "applied, not merged"))
        elif os.path.exists(os.path.join(d, "verified")):
            res.append((d, slug, role, base, "verified, not applied"))
        else:
            res.append((d, slug, role, base, "prepared, not verified"))
    return res


def live(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def busy(state, project):
    """The whole-suite runs in progress: pid files $STATE/busy/PROJECT.KIND.NAME.pid whose process is alive."""
    d, out = os.path.join(state, "busy"), []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if not (n.startswith(project + ".") and n.endswith(".pid")):
            continue
        try:
            pid = int(open(os.path.join(d, n)).read().split()[0])
        except (OSError, ValueError, IndexError):
            continue
        if pid > 0 and live(pid):
            out.append((n[len(project) + 1:-4], pid))
    return out


def conflicts(state, project):
    d = os.path.join(state, "conflicts")
    try:
        return sorted(n for n in os.listdir(d) if n.startswith(project + "-"))
    except OSError:
        return []


def last_merge(state, project):
    """The epoch of the last merge the ref journal records for the project (0 when none)."""
    best = 0
    try:
        with open(os.path.join(state, "ref-journal.jsonl"), errors="replace") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("project") == project and isinstance(r.get("epoch"), int) and str(r.get("verb", "")).endswith(MERGE_VERBS):
                    best = max(best, r["epoch"])
    except OSError:
        pass
    return best


def handoff_of(state, project):
    try:
        with open(os.path.join(state, "handoff", project + ".json")) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("epoch"), int) else None
    except (OSError, ValueError):
        return None


def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(t))


def release_branches(repo, answers):
    pats = ["release/{version}", "hotfix/{version}"]
    try:
        M = load("methodology")
        b = M.load(answers.get("methodology") or "gitflow")[2]["branches"]
        pats = [b.get("release", pats[0]), b.get("hotfix", pats[1])]
    except (Exception, SystemExit):                   # noqa: BLE001  (a missing methodology is not a reason to fail the check)
        pass
    refs = []
    for p in pats:
        if "{version}" in p:
            refs += (git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/" + p.split("{version}")[0] + "*") or "").split()
    return sorted(set(refs))


def features_of(repo):
    return sorted(b[len("feature/"):] for b in (git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/feature/*") or "").split())


def check(a, conf, state):
    """-> {safe, reasons, restart: [lines], open_runs, features}"""
    project = a.project
    answers = answers_of(conf, project)
    repo = repo_of(answers)
    url = (answers.get("repo") or {}).get("url") if isinstance(answers.get("repo"), dict) else ""
    reasons, runs = [], open_runs(state, repo, url)
    for d, slug, role, base, what in runs:
        if what == "prepared, not verified":
            reasons.append("a local run is prepared and not verified: %s (%s %s on %s); verify it (qargi local verify %s) or discard it" % (d, role, slug, base, d))
        elif what == "verified, not applied":
            reasons.append("a local run is verified and not applied: %s (%s %s on %s); apply it (qargi review apply %s BRANCH) and merge it, or close it if you applied it by hand (qargi local close %s --applied-by-am), or clean it" % (d, role, slug, base, d, d))
        else:
            reasons.append("a local run is applied and not merged: %s (%s %s on %s); merge it (qargi feature merge NAME BRANCH), then qargi local clean" % (d, role, slug, base))
    for n in conflicts(state, project):
        reasons.append("a merge waits to be resolved or applied (%s under the conflicts directory): resolve it and run the same command with --resolved, or abandon it" % clean(n))
    for what, pid in busy(state, project):
        reasons.append("the whole suite is running (%s, pid %d): wait for it" % (clean(what), pid))
    h, lm = handoff_of(state, project), last_merge(state, project)
    if h and lm > h["epoch"]:
        reasons.append("the handoff note (written %s) is older than the last merge (%s): write it again (qargi marshal handoff --write FILE)" % (stamp(h["epoch"]), stamp(lm)))
    rel = release_branches(repo, answers)
    if rel:
        reasons.append("a release is in progress (%s): finish it first (qargi release finish)" % ", ".join(clean(r) for r in rel))
    feats = features_of(repo)
    restart = ["After the compact, resume from stored state, not from memory:"]
    if h and h.get("file"):
        restart.append("  1. read the handoff note: %s (written %s)" % (clean(str(h["file"])), stamp(h["epoch"])))
    else:
        restart.append("  1. no handoff note is recorded: write one first (qargi marshal handoff%s --write FILE)" % (" " + feats[0] if len(feats) == 1 else ""))
    restart.append("  2. qargi marshal status --all --brief   (who leads what; your lease)")
    for f in feats:
        restart.append("  3. qargi feature status %s" % f)
    if not feats:
        restart.append("  3. no feature branch is open")
    if runs:
        restart.append("  4. open runs (qargi local list): " + "; ".join("%s %s [%s]" % (r[2], r[1], r[4]) for r in runs))
    else:
        restart.append("  4. open runs: none")
    return {"safe": not reasons, "reasons": reasons, "restart": restart, "open_runs": [{"run": r[0], "slug": r[1], "role": r[2], "base": r[3], "state": r[4]} for r in runs], "features": feats}


def verdict(u, safe, pct_advised=ADVISED, pct_strong=STRONG, note=True):
    """The advice on the context (a string), from the usage and whether a compact is safe; note adds the words about an assumed window."""
    if not u["known"]:
        return "context unknown (%s): no advice on compacting" % u["why"]
    p = u["percent"]
    if p >= pct_strong:
        word = "compact strongly advised"
    elif p >= pct_advised:
        word = "compact advised"
    else:
        return "no compact needed (%s%% of the context)%s" % ("%.0f" % p, assumed(u) if note else "")
    return "%s (%s%% of the context)%s%s" % (word, "%.0f" % p, assumed(u) if note else "", "" if safe else ", but not safe yet: clear the reasons above first")


def cmd_usage(a, conf, state):
    u = measure(a, conf)
    if a.json:
        print(json.dumps(u, indent=1))
    else:
        show_usage(u)
    return 0


def cmd_check(a, conf, state):
    if not a.project:
        print("qargi: which project? Give --project NAME or run this inside its repository", file=sys.stderr)
        return 2
    if not answers_of(conf, a.project):
        print("qargi: no stored answers for project %s" % clean(a.project), file=sys.stderr)
        return 2
    c = check(a, conf, state)
    u = measure(a, conf) if a.advise else None
    if a.json:
        o = dict(c)
        if u:
            o["usage"], o["advice"] = u, verdict(u, c["safe"])
        print(json.dumps(o, indent=1))
        return 0 if c["safe"] else 1
    print("compact is safe now" if c["safe"] else "do not compact now:")
    for r in c["reasons"]:
        print("  - " + r)
    if u:
        show_usage(u)
        print(verdict(u, c["safe"], note=False))
    print()
    print("\n".join(c["restart"]))
    return 0 if c["safe"] else 1


def cmd_open_runs(a, conf, state):
    """The open runs of feature/NAME, which finishing the feature refuses on: "RUN<TAB>SLUG<TAB>ROLE<TAB>STATE" each; exit 1 when there are some."""
    answers = answers_of(conf, a.project or "")
    repo = repo_of(answers)
    url = (answers.get("repo") or {}).get("url") if isinstance(answers.get("repo"), dict) else ""
    found = [r for r in open_runs(state, repo, url) if r[3] == "feature/" + a.feature]
    for d, slug, role, base, what in found:
        print("%s\t%s\t%s\t%s" % (d, slug, role, what))
    return 1 if found else 0


def cmd_advice(a, conf, state):
    """The one line of a stage verb. Never fails, prints nothing when there is nothing to say."""
    try:
        answers = answers_of(conf, a.project or "")
        pct = lead_answer(answers, "compact_advice_pct", DEFAULT_PCT, 0)
        if not answers or pct == 0:
            return 0
        if a.feature:
            repo = repo_of(answers)
            url = (answers.get("repo") or {}).get("url") if isinstance(answers.get("repo"), dict) else ""
            if any(r[3] == "feature/" + a.feature for r in open_runs(state, repo, url)):
                return 0
        ns = argparse.Namespace(project=a.project, session=None, transcript=None, cwd=a.cwd, json=False, advise=False)
        u = measure(ns, conf)
        if not u["known"] or u["percent"] < pct:
            return 0
        c = check(ns, conf, state)
        p = "%.0f%% context%s" % (u["percent"], assumed(u))
        if c["safe"]:
            print("lead: %s; compact is safe now: run /compact" % p)
        else:
            print("lead: %s; compact is not safe yet: %s (qargi lead compact-check)" % (p, c["reasons"][0].split(":")[0]))
    except Exception:                                # noqa: BLE001  (an advice line never blocks a verb)
        pass
    return 0


def main(argv):
    # flags are single-quoted: tests/test_help.py treats a double-quoted option string as a user-facing option that commands.py must
    # describe; --state, --conf, --cwd and --feature are only passed by lib/lead.sh and the stage verbs
    p = argparse.ArgumentParser(prog="lead_usage.py", allow_abbrev=False)
    p.add_argument("verb", choices=["usage", "compact-check", "advice", "open-runs"])
    p.add_argument('--state', required=True)
    p.add_argument('--conf', required=True)
    p.add_argument('--project', default="")
    p.add_argument('--cwd', default="")
    p.add_argument('--feature', default="")
    p.add_argument("--session")
    p.add_argument("--transcript")
    p.add_argument("--json", action="store_true")
    p.add_argument("--advise", action="store_true")
    a = p.parse_args(argv)
    try:
        return {"usage": cmd_usage, "compact-check": cmd_check, "advice": cmd_advice, "open-runs": cmd_open_runs}[a.verb](a, a.conf, a.state)
    except Soft as e:
        print("context: unknown (%s)" % e)
        return 0 if a.verb != "compact-check" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
