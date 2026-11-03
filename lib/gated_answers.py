#!/usr/bin/env python3
"""The one place that stores the two answers no `qargi project` verb stores: models.extensions (what a project adds to its runtime) and
models.accept_no_barrier.SURFACE (the owner's acceptance of a provider surface with no read-only barrier). Both change what an agent may run
on, so each has its own verb with a plan token and an approval (`qargi provider enable|disable`, `qargi provider accept`), and those verbs
store through here, after their gate, and nowhere else: `qargi project set` and `qargi project init` refuse the keys always, and nothing a
caller can set (no environment variable, no option) opens them there.

  gated_answers.py store PROJECT PATH JSON [--conf DIR]     PATH is models.extensions or models.accept_no_barrier.local|cloud

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
    """The two paths that may be stored here, or Refused."""
    if path == "models.extensions":
        return
    m = re.fullmatch(r"models\.accept_no_barrier\.([a-z]+)", path or "")
    if m and m.group(1) in SURFACES:
        return
    raise Refused("%s is not stored here: only models.extensions and models.accept_no_barrier.%s" % (path, "|".join(SURFACES)))


def store(project, path, value, conf=None):
    """Set the answer at path (JSON value) in the stored answers of project, after the validation of project.sh; nothing changes when it fails."""
    check_path(path)
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
    models = doc.get("models")
    if models is None:
        models = doc["models"] = {}
    if not isinstance(models, dict):
        raise Refused("models of project %s is not an object" % project)
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
