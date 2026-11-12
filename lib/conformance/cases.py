"""The hermetic cases of `qargi provider check`: what can be shown about a provider definition without a live runtime, and which
capabilities that backs. A library for lib/conformance/library.py; it does nothing when run.

  CAP_CASES      capability -> the cases that back it: a capability is verified when it is CLAIMED (yes or partial), at least one of its
                 cases applies to the definition and passed, and none failed or could not run. A capability that no case backs (the
                 vendor's own behaviour: a model id, an OS sandbox, a spend ceiling the vendor enforces) stays unverified until the owner
                 attests it (qargi provider attest).
  CAP_GATES      capability -> cases that can only hold it back: one that failed leaves the capability unverified, one that passed
                 verifies nothing (what it shows is qargi's side; the runtime's side is attested)
  run(...)       {case: {status: pass|fail|skip|na, notes: [..]}}   na: the definition has nothing of that kind; skip: it could not run
  verdicts(...)  {capability: (verified, why)} for every capability the definition claims

The cases:
  render-agent     agent_definitions   the agent renderer of the definition renders a sample member (write and read-only) twice with the same
                                       bytes, and each render reads back (lib/render.py checks that); a command renderer runs from a private
                                       copy of the sealed pack, after its hash was checked
  link-skills      skills              the link engine plans, applies and undoes the skills link in a temporary git repository
  barrier-hook     read_only_barrier   the barrier corpus (lib/conformance/barrier-corpus.jsonl), turned into the hook's own payloads with the
                                       pointers and tool names of the definition, goes through `qargi __guard --provider NAME`: every deny
                                       is a deny in the hook's way, every allow an allow
  barrier-adapter  read_only_barrier   the conformance harness (lib/conformance/run.sh) on the adapter of the pack, case 8
  barrier-sandbox-args  read_only_barrier (a gate)   for the barrier kind sandbox-args: the argv qargi local run builds for a read-only run
                                       (lib/local_run.py, with a value for every placeholder) carries the read-only arguments (the class_argv
                                       of the class, the {"class": "read-only"} groups), sets each of their flags only there, and carries
                                       no flag with its value of the write class's arguments (a write grant such as --add-dir DIR); whether
                                       the runtime's sandbox holds is attested
  adapter-cost     session_budget_ceiling   the harness, case 7 (cost is in cents or null), for a pack with an adapter and a conformance/ stub
Pack code (an adapter, a command renderer, the stub) runs only from a private copy of a SEALED pack, after the hashes were checked
(provider.exec_copy, whose copy provider.discard_exec_copy removes, with the temporary directory around it); an unsealed pack, or a
directory, gets the cases that run no pack code."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.realpath(__file__))
LIB = os.path.dirname(HERE)
if LIB not in sys.path:
    sys.path.insert(0, LIB)
import provider as P  # noqa: E402

CAP_CASES = {
    "agent_definitions": ("render-agent",),
    "skills": ("link-skills",),
    "read_only_barrier": ("barrier-hook", "barrier-adapter"),
    "session_budget_ceiling": ("adapter-cost",),
}
CAP_GATES = {
    "read_only_barrier": ("barrier-sandbox-args",),
}
CORPUS = os.path.join(HERE, "barrier-corpus.jsonl")
RUN_SH = os.path.join(HERE, "run.sh")
HARNESS_TIMEOUT = 600


def result(status, *notes):
    return {"status": status, "notes": [n for n in notes if n]}


def verdicts(doc, results):
    """For every capability the definition claims (yes or partial): (verified, why)."""
    out = {}
    caps = doc.get("capabilities") if isinstance(doc.get("capabilities"), dict) else {}
    for cap, cell in sorted(caps.items()):
        if not isinstance(cell, dict) or cell.get("value") not in ("yes", "partial"):
            continue
        gates = [(i, results[i]) for i in CAP_GATES.get(cap, ()) if i in results and results[i]["status"] != "na"]
        if any(r["status"] == "fail" for _, r in gates):
            out[cap] = (False, "failed: " + ", ".join(i for i, r in gates if r["status"] == "fail"))
            continue
        ids = CAP_CASES.get(cap)
        if gates and not [i for i in ids or () if i in results and results[i]["status"] != "na"]:
            out[cap] = (False, "%s passed, which shows qargi's side only; that the runtime holds it is a fact of the runtime: qargi provider attest records a check you ran"
                        % ", ".join(i for i, _ in gates))
            continue
        if not ids:
            out[cap] = (False, "no hermetic case backs it (a fact about the vendor's runtime); qargi provider attest records a check you ran")
            continue
        rs = [(i, results[i]) for i in ids if i in results and results[i]["status"] != "na"]
        if not rs:
            out[cap] = (False, "no case applies to this definition; qargi provider attest records a check you ran")
        elif any(r["status"] == "fail" for _, r in rs):
            out[cap] = (False, "failed: " + ", ".join(i for i, r in rs if r["status"] == "fail"))
        elif any(r["status"] == "skip" for _, r in rs):
            out[cap] = (False, "could not run: " + "; ".join("%s (%s)" % (i, "; ".join(r["notes"]) or "skipped") for i, r in rs if r["status"] == "skip"))
        else:
            out[cap] = (True, "cases " + ", ".join(i for i, _ in rs))
    return out


def run(doc, directory, name, entry, sealed=False, opts=None, rv=None):
    """All the cases for a provider definition. directory: the pack directory; name: its library name or None; sealed: pack code may run."""
    usable = name is not None and entry is not None and P.seal_state(entry)[0] == "sealed"
    res = {}
    for case in (render_agent, link_skills, barrier_hook, barrier_sandbox_args, adapter_harness):
        try:
            res.update(case(doc, directory, name, sealed, usable))
        except Exception as e:                                       # a case that breaks is a failure of the pack, not a crash of the verb
            res[case.__name__.replace("_", "-")] = result("fail", "%s: %s" % (type(e).__name__, e))
    return res


def run_extension(comp, ext, directory, opts=None):
    """The cases for the capabilities an extension provides, on the composition of its runtime and this extension alone (provider.compose):
    {case: result}. Only the cases of those capabilities run. A renderer runs from the pack that provides it (extension or runtime).
    The guard and the adapter harness read a runtime by its name, not a composition, so what only they could show is skipped, and the
    capability stays unverified until it is attested."""
    doc, prov = comp["definition"], comp["provenance"]
    mine = [c for c, pack in prov.items() if pack == ext and c.startswith("capabilities.")]
    needed = {i for c in mine for i in CAP_CASES.get(c[13:], ())}
    res = {}
    for case, ids in ((render_agent, ("render-agent",)), (link_skills, ("link-skills",))):
        if not needed & set(ids):
            continue
        pack = prov.get("renderers.agent", ext) if case is render_agent else ext
        pe = P.entry_any(pack)
        sealed = pe is not None and P.seal_state(pe)[0] == "sealed"
        try:
            res.update(case(doc, directory, pack, sealed, True))
        except Exception as e:                                       # a case that breaks is a failure of the pack, not a crash of the verb
            res[ids[0]] = result("fail", "%s: %s" % (type(e).__name__, e))
    for i in sorted(needed & {"barrier-hook", "barrier-adapter", "adapter-cost"}):
        res[i] = result("skip", "the guard and the adapter harness read a runtime by its name, not a composition; qargi provider attest records a check you ran")
    return res


# ---- render-agent -----------------------------------------------------------------------------------------------------------------

SAMPLES = (
    {"name": "conformance-member", "description": "a sample member: it renders and does nothing else", "abilities": ["build"], "class": "write", "tier": "balanced",
     "model": "balanced", "effort": "high", "tools": {"required": ["read"], "optional": ["shell", "edit", "write", "search_text", "search_files"]},
     "body": "You are a sample member.\nDo the task and report.\n", "guard_command": "qargi __guard", "barrier": {"class": "write", "guard_command": "qargi __guard"}},
    {"name": "conformance-reviewer", "description": "a sample reviewer: it reads and reports", "abilities": ["review"], "class": "read-only", "tier": "deep",
     "model": "deep", "effort": "high", "tools": {"required": ["read"], "optional": ["search_text", "search_files"]},
     "body": "You review and write nothing.\n", "guard_command": "qargi __guard --class read-only", "barrier": {"class": "read-only", "guard_command": "qargi __guard --class read-only"}},
)


def resolver_of(doc):
    models = P._resolve_models(doc)

    def resolve(kind, value, definition):
        if kind == "model":
            row = models["tiers"].get(value)
            return (row["alias"] if models.get("use") == "alias" and row.get("alias") else row["model"]) if row else None
        if kind == "effort":
            return models["effort"].get(value)
        return None
    return resolve


def render_agent(doc, directory, name, sealed, usable):
    spec = (doc.get("renderers") or {}).get("agent") if isinstance(doc.get("renderers"), dict) else None
    if not isinstance(spec, dict):
        return {"render-agent": result("na")}
    import render as RN
    engine = spec.get("engine", "map")
    root, tmp = None, None
    try:
        if engine == "command":
            if not (sealed and name):
                return {"render-agent": result("skip", "a command renderer runs only from a sealed library pack")}
            cmd = spec.get("command")
            rel = cmd[0] if isinstance(cmd, list) and cmd else None
            tmp, _ = P.exec_copy(name, rel)       # tmp is the pack inside qargi-exec.XXXX/: discard_exec_copy removes the whole of it
            root = tmp
        resolver = resolver_of(doc)
        seen = []
        for sample in SAMPLES:
            a = RN.render(sample, spec, root=root, resolver=resolver)
            b = RN.render(sample, spec, root=root, resolver=resolver)
            if a["content"] != b["content"] or a["sha256"] != b["sha256"]:
                return {"render-agent": result("fail", "the %s sample renders differently twice" % sample["class"])}
            seen.append("%s %s" % (sample["class"], a["path"]))
        return {"render-agent": result("pass", "rendered twice, the same bytes, read back: " + ", ".join(seen))}
    except RN.RenderError as e:
        return {"render-agent": result("fail", str(e))}
    finally:
        if tmp:
            P.discard_exec_copy(tmp)


# ---- link-skills ------------------------------------------------------------------------------------------------------------------

def link_skills(doc, directory, name, sealed, usable):
    sk = (doc.get("resources") or {}).get("skills") if isinstance(doc.get("resources"), dict) else None
    link = (sk or {}).get("link") if isinstance(sk, dict) else None
    mode = link.get("project") if isinstance(link, dict) else None
    if not isinstance(sk, dict) or not sk.get("project_dir") or mode in (None, "none"):
        return {"link-skills": result("na")}
    import linker as LK
    tmp = tempfile.mkdtemp(prefix="qargi-link.")
    here = os.getcwd()
    try:
        os.chmod(tmp, 0o700)
        repo, state = os.path.join(tmp, "repo"), os.path.join(tmp, "state")
        source = os.path.join(state, "render", "skills")
        os.makedirs(os.path.join(source, "sample-skill"))
        os.makedirs(repo)
        with open(os.path.join(source, "sample-skill", "SKILL.md"), "w") as f:
            f.write("---\nname: sample-skill\ndescription: a sample for the link check\n---\n\nnothing\n")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        r = subprocess.run(["git", "init", "-q", repo], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            return {"link-skills": result("skip", "git is not available here")}
        os.chdir(tmp)
        lk = LK.Link("skills", "conformance", repo, sk["project_dir"], source, mode, state)
        dest = os.path.join(repo, sk["project_dir"])

        def attempt(verb):
            def go():
                facts = LK.plan(verb, lk)
                if facts["state"] != "linked":
                    LK.cmd_apply(verb, lk, LK.token_of(facts))
            from conformance.library import quiet
            rc, out = quiet(go)
            return rc, out
        rc, out = attempt("link")
        if rc not in (None, 0):
            return {"link-skills": result("fail", "the link plan or apply was refused: " + out.strip().splitlines()[-1][:200] if out.strip() else "refused")}
        ok = False
        if mode == "dir-symlink":
            ok = os.path.islink(dest) and os.path.realpath(dest) == os.path.realpath(source)
        elif mode == "entry-symlinks":
            e = os.path.join(dest, "sample-skill")
            ok = os.path.isdir(dest) and not os.path.islink(dest) and os.path.islink(e) and os.path.realpath(e) == os.path.realpath(os.path.join(source, "sample-skill"))
        elif mode == "copy":
            f = os.path.join(dest, "sample-skill", "SKILL.md")
            ok = os.path.isfile(f) and not os.path.islink(f)
        if not ok:
            return {"link-skills": result("fail", "after the link, %s does not show the sample skill the way the %s mode should" % (sk["project_dir"], mode))}
        rc, out = attempt("unlink")
        if rc not in (None, 0):
            return {"link-skills": result("fail", "the unlink was refused: " + out.strip().splitlines()[-1][:200] if out.strip() else "refused")}
        if mode == "dir-symlink" and os.path.islink(dest):
            return {"link-skills": result("fail", "the unlink left the link")}
        if mode == "entry-symlinks" and os.path.lexists(os.path.join(dest, "sample-skill")):
            return {"link-skills": result("fail", "the unlink left the entry link")}
        return {"link-skills": result("pass", "%s linked and unlinked in a temporary repository" % mode)}
    finally:
        os.chdir(here)
        shutil.rmtree(tmp, ignore_errors=True)


# ---- barrier-hook -----------------------------------------------------------------------------------------------------------------

TOOL_CATEGORY = {"Bash": "shell", "Edit": "write", "Write": "write", "NotebookEdit": "write", "MultiEdit": "write", "Read": "read", "NotebookRead": "read",
                 "Grep": "search", "Glob": "search"}


def put_pointer(obj, pointer, value):
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/")[1:]]
    cur = obj
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def fill(v, run, clone, out):
    if isinstance(v, str):
        return v.replace("{RUN}", run).replace("{CLONE}", clone).replace("{OUT}", out)
    if isinstance(v, dict):
        return {k: fill(x, run, clone, out) for k, x in v.items()}
    if isinstance(v, list):
        return [fill(x, run, clone, out) for x in v]
    return v


def hook_problem(hook):
    """What is wrong with hook protocol data according to the guard itself (lib/guard.py hook_problem), or None."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("qargi_guard_hook_data", os.path.join(LIB, "guard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.hook_problem(hook)


def barrier_hook(doc, directory, name, sealed, usable):
    bar = doc.get("barrier") if isinstance(doc.get("barrier"), dict) else {}
    if bar.get("kind") != "hook":
        return {"barrier-hook": result("na")}
    hook = bar.get("hook") if isinstance(bar.get("hook"), dict) else {}
    if not name or not usable:
        return {"barrier-hook": result("skip", "the guard reads the hook data of a usable library or shipped definition by name; seal the pack first")}
    if doc.get("surface") != "local":
        return {"barrier-hook": result("na")}
    why = hook_problem(hook)
    if why:                                               # data the guard would not use, or one whose refusal reads as an allow: no corpus call can tell
        return {"barrier-hook": result("fail", "the guard cannot use the hook data: " + why)}
    tmp = tempfile.mkdtemp(prefix="qargi-barrier.")
    try:
        os.chmod(tmp, 0o700)
        run_dir = os.path.join(tmp, "run")
        clone, out = os.path.join(run_dir, "clone"), os.path.join(run_dir, "out")
        os.makedirs(os.path.join(clone, "src"))
        os.makedirs(out)
        for fn, text in (("ability", "build\n"), ("class", "write\n"), ("refs.before", "")):
            with open(os.path.join(run_dir, fn), "w") as f:
                f.write(text)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME")}
        env["HOME"] = home
        guard = os.path.join(LIB, "guard.py")
        names = hook.get("tool_names") if isinstance(hook.get("tool_names"), dict) else {}
        pointers = hook.get("path_pointers") if isinstance(hook.get("path_pointers"), dict) else {}
        deny = hook.get("deny") if isinstance(hook.get("deny"), dict) else {}
        allow = hook.get("allow") if isinstance(hook.get("allow"), dict) else {}
        n, skipped, problems = 0, 0, []
        with open(CORPUS, encoding="utf-8") as fh:
            rows = [json.loads(ln) for ln in fh if ln.strip()]
        for row in rows:
            tc = fill(row["tool_call"], run_dir, clone, out)
            cat = TOOL_CATEGORY.get(tc.get("tool"))
            native = (names.get(cat) or [None])[0] if cat else None
            if row.get("surface") != "local" or not native:
                skipped += 1
                continue
            payload = {}
            try:
                put_pointer(payload, hook["tool_pointer"], native)
                if cat == "shell":
                    put_pointer(payload, hook["command_pointer"], tc["command"])
                else:
                    ptrs = pointers.get(cat) or pointers.get("read" if cat == "search" else cat) or []
                    if not ptrs:
                        skipped += 1
                        continue
                    put_pointer(payload, ptrs[0], tc["path"])
                if hook.get("cwd_pointer"):
                    put_pointer(payload, hook["cwd_pointer"], tc["cwd"])
            except (KeyError, TypeError, IndexError):
                return {"barrier-hook": result("fail", "the hook data lacks the pointers it needs (tool_pointer, command_pointer, path_pointers, cwd_pointer)")}
            cmd = [sys.executable, "-I"] + (["-B"] if sys.dont_write_bytecode else []) + [guard, "--provider", name] + (["--class", "read-only"] if row["class"] == "read-only" else [])
            r = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, env=env, cwd=clone, timeout=60)
            n += 1
            d_exit = deny.get("exit", 2)
            denied = r.returncode == d_exit and (d_exit != 0 or bool(r.stdout.strip()))
            allowed = r.returncode == allow.get("exit", 0) and not (d_exit == 0 and r.stdout.strip())
            if row["expect"] == "deny" and not denied:
                problems.append("expected a deny (%s), got exit %d: %s" % (row["why"], r.returncode, json.dumps(tc)[:120]))
            elif row["expect"] == "allow" and not allowed:
                problems.append("expected an allow (%s), got exit %d %s" % (row["why"], r.returncode, (r.stderr or r.stdout).strip()[:100]))
        if problems:
            return {"barrier-hook": result("fail", "%d of %d corpus calls went wrong" % (len(problems), n), *problems[:4])}
        if n == 0:
            return {"barrier-hook": result("skip", "the definition names none of the tool kinds the corpus uses")}
        return {"barrier-hook": result("pass", "%d corpus calls through the guard in the hook's own protocol (%d not expressible and left out)" % (n, skipped))}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- barrier-sandbox-args ---------------------------------------------------------------------------------------------------------

SAMPLE_RUN = "/conformance/run"
SAMPLE_VALUES = {"member": "conformance-member", "model": "conformance-model", "effort_native": "conformance-effort", "prompt_file": SAMPLE_RUN + "/prompt/prompt.md",
                 "prompt_arg": "conformance prompt", "clone": SAMPLE_RUN + "/clone", "run_dir": SAMPLE_RUN, "out_dir": SAMPLE_RUN + "/out",
                 "project": "conformance", "run_config": SAMPLE_RUN + "/config/conformance.toml", "final_message": SAMPLE_RUN + "/final.conformance/message.md"}


def class_group(items, values, cls, runtime):
    """The arguments the {"class": cls} groups of an argv-like list give for a run of that class (inside the if-groups that are kept too)."""
    import local_run as LR
    out = []
    for it in items:
        if isinstance(it, dict) and it.get("class") == cls:
            out += LR.expand(it["then"], values, cls, "dispatch.argv", runtime)
        elif isinstance(it, dict) and "if" in it and values.get(LR.ALIASES.get(it["if"], it["if"])) not in (None, ""):
            out += class_group(it["then"], values, cls, runtime)
    return out


def settings(args):
    """{setting: count} of the flags in an argument list: a flag is an argument that starts with '-'; one whose value is KEY=VALUE (in the
    next argument, or after '=') is the setting 'FLAG KEY', so that a repeated -c KEY=VALUE names a different setting for each KEY."""
    out = {}
    for i, a in enumerate(args):
        if not a.startswith("-") or a in ("-", "--"):
            continue
        flag, _, val = a.partition("=")
        if not val and i + 1 < len(args) and not args[i + 1].startswith("-"):
            val = args[i + 1]
        key = flag + (" " + val.split("=", 1)[0] if "=" in val else "")
        out[key] = out.get(key, 0) + 1
    return out


def pairs(args):
    """The flags of an argument list with their values, as tuples: (FLAG, VALUE) for a flag followed by a value or written FLAG=VALUE, (FLAG,) for one
    alone. A pair the write class's arguments give that a read-only argv carries too is a write grant in a read-only run (--add-dir DIR)."""
    out = []
    for i, a in enumerate(args):
        if not a.startswith("-") or a in ("-", "--"):
            continue
        flag, eq, val = a.partition("=")
        if not eq and i + 1 < len(args) and not args[i + 1].startswith("-"):
            val = args[i + 1]
        out.append((flag, val) if val else (flag,))
    return out


def group_args(disp, cls):
    """The argument lists a run of class cls gets from its own groups (each {"class": cls} group of argv, also inside an if-group, and
    class_argv), as written (with their placeholders). For the harness (lib/conformance/run.sh), which looks for each in the argv a command
    really got (carries)."""
    out = []

    def walk(items):
        for it in items if isinstance(items, list) else ():
            if isinstance(it, dict) and it.get("class") == cls:
                strs = [x for x in it.get("then") or [] if isinstance(x, str)]
                if strs:
                    out.append(strs)
            elif isinstance(it, dict) and "if" in it:
                walk(it.get("then"))
    walk(disp.get("argv"))
    ca = disp.get("class_argv")
    extra = (ca if cls == "read-only" else []) if isinstance(ca, list) else (ca.get(cls) if isinstance(ca, dict) else None)
    strs = [x for x in extra or [] if isinstance(x, str)]
    if strs:
        out.append(strs)
    return out


def literal(args):
    """Does an argument list hold any text that is not a placeholder? A list of placeholders alone matches any arguments."""
    import local_run as LR
    return any(LR.PLACEHOLDER.sub("", a) for a in args)


def carries(argv, args):
    """Does argv hold the argument list (placeholders match any non-empty text) as a run of consecutive arguments?"""
    import local_run as LR
    pats = ["^" + "".join(".+" if i % 2 else re.escape(p) for i, p in enumerate(LR.PLACEHOLDER.split(a))) + "$" for a in args]
    n = len(pats)
    return any(all(re.match(p, a, re.S) for p, a in zip(pats, argv[i:i + n])) for i in range(len(argv) - n + 1))


def barrier_sandbox_args(doc, directory, name, sealed, usable):
    bar = doc.get("barrier") if isinstance(doc.get("barrier"), dict) else {}
    if bar.get("kind") != "sandbox-args":
        return {"barrier-sandbox-args": result("na")}
    import local_run as LR
    disp = doc.get("dispatch") if isinstance(doc.get("dispatch"), dict) else {}
    runtime = name or doc.get("provider") or "the definition"
    if disp.get("mode") != "command":
        return {"barrier-sandbox-args": result("fail", "the barrier kind sandbox-args is the runtime's own arguments, which only a command dispatch passes (dispatch.mode is %s)"
                                               % json.dumps(disp.get("mode")))}
    argv, group = {}, {}
    try:
        LR.check_items(disp.get("argv"), "dispatch.argv", runtime)
        for cls in LR.CLASSES:
            extra = LR.class_extra(disp, cls, runtime)
            LR.check_items(extra, "dispatch.class_argv", runtime)
            extra = LR.expand(extra, SAMPLE_VALUES, cls, "dispatch.class_argv", runtime)
            argv[cls] = LR.expand(disp["argv"], SAMPLE_VALUES, cls, "dispatch.argv", runtime) + extra
            group[cls] = class_group(disp["argv"], SAMPLE_VALUES, cls, runtime) + extra
    except LR.Stop as e:
        return {"barrier-sandbox-args": result("fail", "qargi local run would refuse the dispatch: %s" % e)}
    ro = group["read-only"]
    if not ro:
        return {"barrier-sandbox-args": result("fail", "a read-only run carries no arguments of its own (class_argv, or a {\"class\": \"read-only\"} group in argv), so nothing holds it")}
    outside = sorted(k for k, n in settings(ro).items() if settings(argv["read-only"]).get(k, 0) > n)
    if outside:
        return {"barrier-sandbox-args": result("fail", "a read-only run also sets %s outside its read-only arguments, which can override them" % ", ".join(outside))}
    granted = [" ".join(p) for p in pairs(group["write"]) if p in pairs(argv["read-only"])]
    if granted:
        return {"barrier-sandbox-args": result("fail", "a read-only run carries %s of the write class (a write grant, such as a writable directory)" % "; ".join(granted))}
    return {"barrier-sandbox-args": result("pass", "a read-only run carries %s%s; that the runtime's sandbox holds is attested" % (
        " ".join(ro), " (a write run: %s)" % " ".join(group["write"]) if group["write"] else ""))}


# ---- the adapter harness ----------------------------------------------------------------------------------------------------------

LINE = re.compile(r"^(ok|FAIL|skip) +\[(\d+)\] ")


def adapter_harness(doc, directory, name, sealed, usable):
    ids = ("barrier-adapter", "adapter-cost")
    ad = doc.get("adapter")
    bar_adapter = isinstance(doc.get("barrier"), dict) and doc["barrier"].get("kind") == "adapter"
    if not isinstance(ad, str) or not ad:
        return {i: result("na") for i in ids}
    if not (sealed and name):
        return {i: result("skip", "an adapter runs only from a sealed library pack") for i in ids}
    stub_dir = os.path.join(directory, "conformance")
    if not os.path.isfile(os.path.join(stub_dir, "stub")):
        return {i: result("skip", "the pack has no conformance/stub (the stand-in for the vendor) to run the adapter against") for i in ids}
    ranges = {}
    tmp = tempfile.mkdtemp(prefix="qargi-adapter.")
    copy = None
    try:
        os.chmod(tmp, 0o700)
        copy, _ = P.exec_copy(name, ad)
        tool = os.path.join(tmp, "tool")
        shutil.copytree(LIB, os.path.join(tool, "lib"), symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(os.path.dirname(LIB), "agents"), os.path.join(tool, "agents"), symlinks=True) if os.path.isdir(os.path.join(os.path.dirname(LIB), "agents")) else None
        provs = os.path.join(tool, "lib", "providers")
        shutil.copytree(copy, os.path.join(provs, name), symlinks=True)
        fam = (doc.get("models") or {}).get("catalog") if isinstance(doc.get("models"), dict) else None
        if fam:
            ce = P._pick(fam, "catalog", None, None)
            if ce is not None:
                os.makedirs(os.path.join(provs, "catalogs"), exist_ok=True)
                shutil.copyfile(ce["file"], os.path.join(provs, "catalogs", fam + ".json"))
        staged = json.loads(json.dumps(doc))
        for cell in (staged.get("capabilities") or {}).values():          # the harness reads a shipped file, where a claim counts when it is dated:
            if isinstance(cell, dict) and cell.get("value") in ("yes", "partial") and not cell.get("verified_on"):   # it is what is being verified here
                cell["verified_on"] = datetime.now().strftime("%Y-%m-%d")
        with open(os.path.join(provs, name + ".json"), "w") as f:
            json.dump(staged, f)
        stubs = os.path.join(tmp, "stubs")
        shutil.copytree(os.path.join(copy, "conformance"), stubs, symlinks=True)
        r = subprocess.run(["bash", RUN_SH, name, "--tool", tool, "--stub", stubs], capture_output=True, text=True, timeout=HARNESS_TIMEOUT, stdin=subprocess.DEVNULL,
                           env=P.pack_env(tmp, tmp))              # the pack's adapter and stub run with nothing of the caller's environment
        lines = r.stdout.splitlines()
        for ln in lines:
            m = LINE.match(ln)
            if m:
                ranges[int(m.group(2))] = (m.group(1), ln)
        if r.returncode == 2 or not ranges:
            return {i: result("fail", "the harness could not run: " + (r.stderr or r.stdout).strip().splitlines()[-1][:200] if (r.stderr or r.stdout).strip() else "no output") for i in ids}
        failed = [ln for st, ln in ranges.values() if st == "FAIL"]
        if failed or r.returncode != 0:
            return {i: result("fail", "the adapter fails the conformance harness", *failed[:3]) for i in ids}

        def of(n, applies=True):
            if not applies:
                return result("na")
            st = ranges.get(n, ("skip", ""))[0]
            return result("pass", "harness case %d" % n) if st == "ok" else result("skip", "harness case %d did not run (the adapter does not serve it)" % n)
        return {"barrier-adapter": of(8, bar_adapter), "adapter-cost": of(7)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if copy:
            P.discard_exec_copy(copy)
