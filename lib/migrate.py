#!/usr/bin/env python3
"""qargi migrate roles: bring an installation made with the old role names to the current ones.

  migrate.py roles [--member-names build=NAME,write=NAME,review=NAME,test=NAME]
  migrate.py roles --apply --plan TOKEN --asked "<the user's words>" [--member-names ...]

Without --apply it prints the plan and a plan token and changes nothing (it reads the cloud). The plan covers, in
the order they are applied:
  1. this machine: registry entries, tracker rows, project answers, pack links and saved definitions renamed
     (dev -> build, docs -> write; review, test and lead keep their names);
  2. the memory and reference stores of every project: notes under roles/dev|docs/ moved to roles/build|write/,
     and the role names in indexes, the README and the canon marker fixed;
  3. the cloud resources of every cloud instance, as `qargi instances normalize` names them (agent <project>-<role>,
     deployment <project>-deployment-<role>; renaming is an update, nothing is archived), then the system prompt
     rebuilt from the current contract as `qargi instances refresh-prompt` does (a lead also gets its members'
     new versions);
  4. the local agents an earlier version installed (qargi-dev, qargi-docs, qargi-review, qargi-test): each symlink
     is removed and a member of that ability is created (qargi agent add) under the name --member-names gives
     (default builder, writer, reviewer, tester).
Apply needs the token of the plan the user saw and, when the plan touches the cloud, --asked. It is re-runnable:
what is already renamed is not in the plan any more. It stops at the first failure and says where.
"""
import datetime, hashlib, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import roles as R  # noqa: E402

CONF, STATE = R.conf(), R.state()
NESTED_APPROVAL = "qargi migrate roles"


def F(name):
    """An option of another tool (ant, registry.sh, agent.sh), spelled out so it is not taken for one of this command's."""
    return "--" + name


def die(msg, code=1):
    print("qargi: " + msg, file=sys.stderr)
    raise SystemExit(code)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit(detail, asked, approved):
    os.makedirs(STATE, mode=0o700, exist_ok=True)
    f = os.path.join(STATE, "audit.log")
    with open(f, "a") as fh:
        fh.write(json.dumps({"ts": now(), "verb": "migrate-roles", "detail": detail, "asked": asked, "approved": approved, "nested": False}) + "\n")
    os.chmod(f, 0o600)


def ant(args, stdin=None):
    try:
        r = subprocess.run(["ant"] + args, input=(stdin or "").encode(), capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return r.returncode, r.stdout.decode("utf-8", "replace")


def ant_json(args):
    rc, out = ant(args)
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def stream(out):
    """ant prints a list as a stream of JSON values."""
    dec, i, items = json.JSONDecoder(), 0, []
    while True:
        while i < len(out) and out[i] in " \t\r\n,[]":
            i += 1
        if i >= len(out):
            return items
        try:
            m, i = dec.raw_decode(out, i)
        except ValueError:
            return items
        items.append(m)


def store_notes(store):
    rc, out = ant(["beta:memory-stores:memories", "list", F("memory-store-id"), store, F("path-prefix"), "/", F("view"), "full", F("max-items"), "-1"])
    if rc != 0:
        die("cannot read the memory store %s (is ant logged in?); nothing was changed" % store)
    return {m["path"]: m for m in stream(out) if isinstance(m, dict) and m.get("type", "memory") == "memory" and "path" in m}


def jload(path, default):
    return R.jload(path, default)


def bash_lib(snippet, conf=None, env_extra=None):
    """Run a snippet with lib.sh loaded; returns (rc, stdout)."""
    env = dict(os.environ, **(env_extra or {}))
    if conf:
        env["QARGI_CONF"] = conf
    r = subprocess.run(["bash", "-c", '. "$1"; shift; %s' % snippet, "bash", os.path.join(HERE, "lib.sh")],
                       capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout


def member_names(arg):
    names = dict(R.MEMBER_DEFAULT)
    for part in [p for p in (arg or "").split(",") if p.strip()]:
        k, _, v = part.partition("=")
        k, v = k.strip(), v.strip()
        if k not in R.ABILITIES or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", v) or len(v) > 40:
            die("--member-names: ability=name pairs, for example build=forge,write=scribe (abilities: %s; names kebab-case)" % ", ".join(R.ABILITIES))
        names[k] = v
    if len(set(names.values())) != len(names):
        die("--member-names: give each ability its own member (one member for several abilities: qargi agent add NAME --abilities LIST)")
    return names


class Plan:
    def __init__(self):
        self.lines, self.actions, self.cloud = [], [], False

    def say(self, line):
        self.lines.append(line)

    def act(self, label, fn, cloud=False):
        self.actions.append((label, fn))
        self.cloud = self.cloud or cloud

    def token(self):
        return hashlib.sha256("\n".join(self.lines).encode()).hexdigest()[:12]


def plan_local(p):
    p.say("== 1. this machine (registry, tracker, project answers, pack links)")
    steps = R.local_steps()
    if not [s for s in steps if s[0]]:
        p.say("  nothing to rename")
        return
    for what, a, b, _ in steps:
        if what:
            p.say("  %-17s %s%s" % (what + ":", a, (" -> " + b) if b else ""))
    p.act("rename the local state", lambda: subprocess.run([sys.executable, "-I", os.path.join(HERE, "roles.py"), "local-apply"], check=True))


def projects():
    out = {}
    d = os.path.join(CONF, "projects")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".json"):
            a = jload(os.path.join(d, f), None)
            if isinstance(a, dict):
                out[f[:-5]] = R.answers(a)
    return out


def plan_memory(p, projs, work):
    p.say("== 2. memory stores (notes under roles/dev/ and roles/docs/, and the role names in the texts)")
    today = datetime.date.today().isoformat()
    any_ = False
    for proj, a in projs.items():
        for kind in ("memory", "reference"):
            store = (a.get("memory") or {}).get(kind + "_store") or ""
            if not store:
                continue
            mems = store_notes(store)
            sp = R.store_plan(mems, today)
            if not sp["ops"]:
                continue
            any_ = True
            p.say("  %s %s store %s: %d step(s)" % (proj, kind, store, len(sp["ops"])))
            for op in sp["ops"]:
                if op["op"] == "move":
                    p.say("    move   %s -> %s" % (op["from"], op["to"]))
                    p.say("           ant beta:memory-stores:memories update --memory-store-id %s --memory-id %s --path %s" % (store, op["id"], op["to"]))
                else:
                    p.say("    update %s (role names in the text)" % op["path"])
                    p.say("           ant beta:memory-stores:memories update --memory-store-id %s --memory-id %s (new content, precondition: unchanged)" % (store, op["id"]))
            for n in sp["notes"]:
                p.say("    note: " + n)
            f = os.path.join(work, "%s-%s.json" % (proj, kind))
            with open(f, "w") as fh:
                json.dump(sp, fh)

            def run(store=store, f=f, label="%s %s store" % (proj, kind)):
                rc, _ = bash_lib("mem_exec_ops %s %s" % (sh(store), sh(f)))
                if rc != 0:
                    raise RuntimeError("the %s: a step failed (see the message above)" % label)
            p.act("the %s %s store" % (proj, kind), run, cloud=True)
    if not any_:
        p.say("  nothing to move")


def sh(s):
    return "'" + s.replace("'", "'\\''") + "'"


def plan_cloud(p, projs, work):
    p.say("== 3. cloud resources (named as qargi instances normalize names them; nothing is archived)")
    reg = jload(os.path.join(CONF, "instances.json"), {})
    # the prompts are built from the answers as they will be after step 1
    conf2 = os.path.join(work, "conf")
    os.makedirs(os.path.join(conf2, "projects"), exist_ok=True)
    for proj, a in projs.items():
        with open(os.path.join(conf2, "projects", proj + ".json"), "w") as fh:
            json.dump(a, fh)
    cloud = sorted((R.instance(k), v) for k, v in reg.items() if isinstance(v, dict) and v.get("location") == "cloud")
    cloud.sort(key=lambda kv: kv[0].endswith("-lead"))      # a lead after its members
    bumped, shown = set(), 0
    if not cloud:
        p.say("  no cloud instances")
    for name, v in cloud:
        proj, _, role = name.partition("-")
        aid, did, eid = (v.get("agent") or {}).get("id"), v.get("deployment_id"), v.get("environment_id")
        ag = ant_json(["beta:agents", "retrieve", F("agent-id"), aid or ""])
        dep = ant_json(["beta:deployments", "retrieve", F("deployment-id"), did or ""])
        env = ant_json(["beta:environments", "retrieve", F("environment-id"), eid or ""])
        if ag is None or dep is None or env is None:
            die("cannot read the agent, deployment or environment of %s (is ant logged in?); nothing was changed" % name)
        calls, ver = [], ag.get("version")
        if ag.get("name") != "%s-%s" % (proj, role):
            calls += ["ant beta:agents update --agent-id %s --version %s --name %s-%s" % (aid, ver, proj, role),
                      "ant beta:deployments update --deployment-id %s --agent %s" % (did, aid)]
            ver = "<the version after the rename>"
            bumped.add(aid)
        if env.get("name") != "%s-environment" % proj:
            calls.append("ant beta:environments update --environment-id %s --name %s-environment" % (eid, proj))
        for r in v.get("resources") or []:
            if r.get("type") != "memory_store":
                continue
            ms = ant_json(["beta:memory-stores", "retrieve", F("memory-store-id"), r.get("memory_store_id", "")]) or {}
            want = "%s-memory" % proj if r.get("access") == "read_write" else ("%s-reference" % proj if str(ms.get("name", "")).endswith("-reference") else None)
            if want and ms.get("name") != want:
                calls.append("ant beta:memory-stores update --memory-store-id %s --name %s" % (r["memory_store_id"], want))
        if dep.get("name") != "%s-deployment-%s" % (proj, role):
            calls.append("ant beta:deployments update --deployment-id %s --name %s-deployment-%s" % (did, proj, role))
        rc, prompt = bash_lib('agent_prompt %s %s' % (sh(role), sh(proj)), conf=conf2)
        if rc != 0:
            die("could not build the prompt of %s" % name)
        members = [m.get("id") for m in ((ag.get("multiagent") or {}).get("agents") or [])]
        stale = [m for m in members if m in bumped]
        if not stale:
            for m in members:
                cur = ant_json(["beta:agents", "retrieve", F("agent-id"), m]) or {}
                pinned = next((x.get("version") for x in ag["multiagent"]["agents"] if x.get("id") == m), None)
                if cur.get("version") != pinned:
                    stale.append(m)
        prompt = prompt.rstrip("\n")   # as the shell's $(agent_prompt ...) gives it to refresh-prompt
        prompt_change = (ag.get("system") or "") != prompt
        if prompt_change or stale:
            what = []
            if prompt_change:
                what.append("--system <the %s prompt: preamble, %s; %d chars>" % (role, "lead contract and teams" if role == "lead" else "contract, skill qargi-" + role, len(prompt)))
            if stale:
                what.append("--multiagent <members %s at their versions after the steps above>" % ", ".join(stale))
            calls += ["ant beta:agents update --agent-id %s --version %s %s" % (aid, ver, " ".join(what)),
                      "ant beta:deployments update --deployment-id %s --agent %s" % (did, aid)]
            bumped.add(aid)
        if not calls:
            continue
        shown += 1
        p.say("  %s (agent %s -> %s-%s, deployment %s -> %s-deployment-%s)" % (name, ag.get("name"), proj, role, dep.get("name"), proj, role))
        for c in calls:
            p.say("    " + c)

        def run(name=name, rename=any(F("name") in c for c in calls), refresh=prompt_change or bool(stale)):
            env2 = dict(os.environ, QARGI_NESTED="1")
            for verb, needed in (("normalize", rename), ("refresh-prompt", refresh)):
                if not needed:
                    continue
                r = subprocess.run([os.path.join(HERE, "registry.sh"), verb, name, "--asked", ASKED[0], F("approved"), NESTED_APPROVAL],
                                   env=env2, stdin=subprocess.DEVNULL)
                if r.returncode != 0:
                    raise RuntimeError("%s %s failed" % (verb, name))
        p.act("the cloud resources of %s" % name, run, cloud=True)
    if cloud and not shown:
        p.say("  every cloud resource has its name and prompt already")


def plan_agents(p, names):
    p.say("== 4. local agents (the four definitions an earlier version linked become members you named)")
    adir = os.path.join(os.path.expanduser("~"), ".claude", "agents")
    members = jload(os.path.join(CONF, "agents.json"), {})
    reg = jload(os.path.join(CONF, "instances.json"), {})
    did = False
    for old, ability in R.OLD_AGENTS.items():
        f = os.path.join(adir, old + ".md")
        new = names[ability]
        have = members.get(new)
        if have and ability not in (have.get("abilities") or []):
            die("the member %s exists and does not serve %s; choose another name with --member-names %s=NAME" % (new, ability, ability))
        if os.path.islink(f):
            did = True
            p.say("  remove %s (a symlink to %s)" % (f, os.readlink(f)))
            p.act("remove " + f, lambda f=f: os.remove(f))
        elif os.path.exists(f):
            did = True
            p.say("  keep %s: not a symlink (installed as a copy); delete it yourself once the member exists" % f)
        else:
            continue
        if not have:
            p.say("  qargi agent add %s --abilities %s    (%s)" % (new, ability, os.path.join(adir, new + ".md")))

            def add(new=new, ability=ability):
                r = subprocess.run([os.path.join(HERE, "agent.sh"), "add", new, F("abilities"), ability], stdin=subprocess.DEVNULL)
                if r.returncode != 0:
                    raise RuntimeError("qargi agent add %s failed" % new)
            p.act("add the member " + new, add)
        for iname, v in sorted(reg.items()):
            af = ((v.get("local") or {}).get("agent_file") or "") if isinstance(v, dict) else ""
            if os.path.basename(af) == old + ".md":
                target = os.path.join(adir, new + ".md")
                p.say("  registry %s: agent file %s -> %s" % (R.instance(iname), af, target))

                def point(iname=iname, target=target):
                    path = os.path.join(CONF, "instances.json")
                    r = jload(path, {})
                    key = iname if iname in r else R.instance(iname)
                    rec = r[key]
                    rec["local"]["agent_file"] = target
                    if os.path.exists(target):
                        rec["local"]["sha256"] = hashlib.sha256(open(target, "rb").read()).hexdigest()
                    R.jwrite(path, r)
                p.act("point %s at %s" % (iname, target), point)
    if not did:
        p.say("  no agent definitions of the old names in %s" % adir)


ASKED = [""]


def build(names, work):
    p = Plan()
    p.say("Roles: dev -> build, docs -> write (review, test and lead keep their names)")
    p.say("Members: " + ", ".join("%s -> %s (%s)" % (o, names[a], a) for o, a in R.OLD_AGENTS.items()))
    p.say("Cloud names: agent <project>-agent-<role> -> <project>-<role>; deployment <project>-deployment-<role>")
    projs = projects()
    plan_local(p)
    plan_memory(p, projs, work)
    plan_cloud(p, projs, work)
    plan_agents(p, names)
    return p


def main(argv):
    if argv[:1] == ["home"]:
        import migrate_home
        return migrate_home.main(argv[1:])
    if argv[:1] != ["roles"]:
        print("usage: qargi migrate roles|home [--member-names build=NAME,...] [--apply --plan TOKEN --asked \"...\"]", file=sys.stderr)
        return 2
    apply, token, asked, names_arg = False, "", "", ""
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--apply": apply = True; i += 1
        elif a == "--plan" and i + 1 < len(argv): token = argv[i + 1]; i += 2
        elif a == "--asked" and i + 1 < len(argv): asked = argv[i + 1]; i += 2
        elif a == "--member-names" and i + 1 < len(argv): names_arg = argv[i + 1]; i += 2
        else: die("unknown argument %s (qargi help migrate roles)" % a, 2)
    ASKED[0] = asked
    names = member_names(names_arg)
    work = tempfile.mkdtemp(prefix="qargi-migrate.")
    try:
        p = build(names, work)
        print("qargi migrate roles: %s" % ("applying this plan" if apply else "plan (nothing is changed)"))
        print("\n".join(p.lines))
        if not p.actions:
            print("nothing to migrate")
            return 0
        tok = p.token()
        if not apply:
            print("plan token: %s   (apply with: qargi migrate roles --apply --plan %s%s%s)" % (
                tok, tok, " --asked \"<the user's words>\"" if p.cloud else "", (" --member-names " + names_arg) if names_arg else ""))
            return 0
        if token != tok:
            die("the plan changed or --plan is missing: run qargi migrate roles, show the plan to the user, then apply exactly that with --plan %s" % tok)
        if p.cloud and not asked:
            die("the plan changes cloud resources: --asked \"<the user's request for this migration>\" is required")
        audit("plan %s" % tok, asked, "plan %s" % tok)
        for n, (label, fn) in enumerate(p.actions, 1):
            print("-- %d/%d %s" % (n, len(p.actions), label))
            sys.stdout.flush()
            try:
                fn()
            except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
                print("qargi: stopped at step %d/%d (%s): %s. Steps 1-%d are done. Run qargi migrate roles again: the plan shows what remains." % (
                    n, len(p.actions), label, e, n - 1), file=sys.stderr)
                audit("stopped at %d/%d: %s" % (n, len(p.actions), label), asked, "plan %s" % tok)
                return 1
        audit("done: %d step(s)" % len(p.actions), asked, "plan %s" % tok)
        print("migrated: %d step(s). Run qargi migrate roles again to confirm nothing is left." % len(p.actions))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
