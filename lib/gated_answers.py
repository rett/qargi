#!/usr/bin/env python3
"""Store dedicated gated answers: packs.member_skills, models.extensions, models.extra_runtimes.local, models.run_options.local.RUNTIME and models.accept_no_barrier.SURFACE.

The member-skills path is boolean and stores only through its dedicated packs
gate. Project validation is shared; ordinary project writes cannot bypass it.
The provider answers are models.extensions (what a project adds to its runtime), models.extra_runtimes.local (the other runtimes of the local
surface it may start members on), models.run_options.local.RUNTIME (the options of its runtime's definition that a profile of the project may select: a
tool that runs outside the member's sandbox, say) and models.accept_no_barrier.SURFACE (the owner's acceptance of a provider surface with no read-only
barrier). All four change what an agent may run on, so each has its own verb with a plan token and an approval (`qargi provider enable|disable`, with
`--runtime` for the second, `--runtime NAME --option OPT` for the third, and `qargi provider accept`), and those verbs
store through here, after their gate, and nowhere else: `qargi project set` and `qargi project init` refuse the keys always, and nothing a
caller can set (no environment variable, no option) opens them there.

  gated_answers.py store PROJECT PATH JSON [--conf DIR]     PATH is packs.member_skills, models.extensions, models.extra_runtimes.local, models.run_options.local.RUNTIME or models.accept_no_barrier.local|cloud

A module for lib/conformance/library.py (store()) and the script lib/provider.sh calls. The script has no gate of its own, as lib/project_link.py
has none: the verb that calls it has passed its plan token first. The guard therefore refuses any use of the script to a member (lib/guard.py),
like the other helpers behind a refused verb. It stores nothing the answers' own validation (project.sh validate) would not accept."""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import paths  # noqa: E402

SURFACES = ("local", "cloud")


class Refused(Exception):
    """The value is not stored; the message says why."""


def check_path(path):
    """Only the exact dedicated gated paths may be stored here."""
    if path in ("models.extensions", "models.extra_runtimes.local", "packs.member_skills"):
        return
    m = re.fullmatch(r"models\.accept_no_barrier\.([a-z]+)", path or "")
    if m and m.group(1) in SURFACES:
        return
    if re.fullmatch(r"models\.run_options\.local\.[a-z][a-z0-9-]{0,40}", path or ""):
        return
    raise Refused("%s is not stored here: only models.extensions, models.extra_runtimes.local, models.run_options.local.RUNTIME, packs.member_skills and models.accept_no_barrier.%s" % (path, "|".join(SURFACES)))


def store(project, path, value, conf=None):
    """Set the answer at path (JSON value) in the stored answers of project, after the validation of project.sh; nothing changes when it fails."""
    check_path(path)
    if path == 'packs.member_skills':
        import marshal_refs
        if os.environ.get('QARGI_MEMBER_RUN') or marshal_refs.in_member_run():
            raise Refused('packs.member_skills is not stored in a member run')
    conf = conf or paths.conf()
    if not re.fullmatch(r"[a-z][a-z0-9]{0,23}", project or ""):
        raise Refused("no project named %r" % project)
    pdir = os.path.join(conf, "projects")
    target = os.path.join(pdir, project + ".json")
    try:
        with open(target) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        raise Refused("no readable stored answers for project %s" % project)
    if not isinstance(doc, dict):
        raise Refused("the stored answers of project %s are not an object" % project)
    root = path.split('.')[0]
    models = doc.get(root)
    if models is None:
        models = doc[root] = {}
    if not isinstance(models, dict):
        raise Refused("%s of project %s is not an object" % (root, project))
    key = path.split(".")[1:]
    node = models
    for n, k in enumerate(key[:-1]):
        node = node.setdefault(k, {})
        if not isinstance(node, dict):
            raise Refused("%s of project %s is not an object" % (".".join(["models"] + key[:n + 1]), project))
    node[key[-1]] = value
    fd, tmp = tempfile.mkstemp(prefix=".gated.", dir=pdir)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, 0o600)
        r = subprocess.run([os.path.join(HERE, "project.sh"), "validate", tmp], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, QARGI_CONF=conf))
        if r.returncode != 0:
            raise Refused("that would make the project invalid: %s" % (r.stdout or r.stderr).strip())
        os.replace(tmp, target)
        tmp = None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def main(argv):
    conf = None
    if "--conf" in argv:
        k = argv.index("--conf")
        conf = argv[k + 1] if k + 1 < len(argv) else None
        argv = argv[:k] + argv[k + 2:]
        if conf is None:
            print("qargi: --conf needs a directory", file=sys.stderr)
            return 2
    if len(argv) != 4 or argv[0] != "store":
        print("usage: gated_answers.py store PROJECT PATH JSON [--conf DIR]", file=sys.stderr)
        return 2
    try:
        value = json.loads(argv[3])
    except ValueError:
        print("qargi: the value is not JSON", file=sys.stderr)
        return 2
    try:
        store(argv[1], argv[2], value, conf)
    except Refused as e:
        print("qargi: %s; nothing changed" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
