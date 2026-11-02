#!/usr/bin/env python3
"""Which providers may use a pack: the compatible_providers a skill or tool pack declares, and whether a project's provider is one.

Every pack declares it (in its record, .pack.json, and the pack's content hash covers it): a list of runtime names, family names, or the
single word "any". A pack renders for a project only when the declaration matches the runtime the project uses on the surface being
rendered; otherwise it is skipped, with a note that says why, and never attached silently.

Matching is by name: a runtime name matches that runtime, a family name matches every runtime of the family (provider.definition(R).family),
and a name that provider.resolve_runtime() turns into the runtime matches it too. The names need not exist (a pack may name a provider
that is not installed yet); one that matches nothing only skips the pack.

As a library (import packs_compat, found beside this file):
  problem(declared)                         None when DECLARED is a valid declaration, else a sentence saying what is wrong
  evaluate(declared, answers, project, surfaces)
                                            (True, "") or (False, why): is the project's provider one of DECLARED on at least one of
                                            SURFACES (local, cloud)? "any" needs no provider; any other declaration needs the project to
                                            name one
  matches(declared, project, answers, surfaces)   the same, as a bool

Usage: packs_compat.py valid JSON                          exit 0, or 2 and the problem on stdout
       packs_compat.py check PROJECT SURFACES JSON [--conf DIR]
                                                           SURFACES: local, cloud or local,cloud. Exit 0 when compatible; 1 with the
                                                           reason on stdout (the pack is to be skipped); 2 when JSON is not a valid
                                                           declaration (the pack is not usable at all: its review fails)"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
SURFACES = ("local", "cloud")
ANY = "any"


def problem(declared):
    """None when DECLARED is a valid compatible_providers, else what is wrong with it."""
    if declared is None:
        return "not declared; every pack declares the providers that can use it (a list of runtime or family names, or [\"any\"])"
    if not isinstance(declared, list) or not declared:
        return "must be a non-empty list of runtime or family names, or [\"any\"]"
    for d in declared:
        if not isinstance(d, str) or not NAME_RE.match(d):
            return "%s is not a runtime or family name (lower case letters, digits and -, at most 40) or \"any\"" % json.dumps(d)
    if ANY in declared and len(declared) > 1:
        return "\"any\" stands alone; it cannot be listed with other names"
    if len(set(declared)) != len(declared):
        return "names a provider twice"
    return None


def _provider():
    sys.path.insert(0, HERE)
    import provider
    return provider


def _runtime(P, answers, project, surface):
    """(runtime or None, why-not): the runtime the project's answers name for one surface."""
    try:
        return P.resolve_project(answers, surface, project)[0], None
    except P.NoProvider:
        return None, None                      # nothing named: the reason is the same whatever the surface
    except P.ProviderError as e:
        return None, str(e)


def _family(P, runtime, surface):
    try:
        return P.definition(runtime, surface).get("family")
    except P.ProviderError:
        return None


def _names(P, declared, runtime, surface):
    """True when one of the declared names stands for RUNTIME on the surface."""
    fam = _family(P, runtime, surface)
    if runtime in declared or (fam and fam in declared):
        return True
    for d in declared:                       # the resolver's rule: a runtime of that name, or a family with exactly one runtime
        try:
            if P.resolve_runtime(d, surface) == runtime:
                return True
        except P.ProviderError:
            pass
    return False


def evaluate(declared, answers, project, surfaces):
    bad = problem(declared)
    if bad:
        raise ValueError(bad)
    if declared == [ANY]:
        return True, ""
    P = _provider()
    tried, why = [], ""
    for s in surfaces:
        runtime, err = _runtime(P, answers, project, s) if isinstance(answers, dict) else (None, "no such project")
        if runtime is None:
            why = why or err or ""
            continue
        if _names(P, declared, runtime, s):
            return True, ""
        if runtime not in tried:
            tried.append(runtime)
    names = ", ".join(declared)
    if not tried:
        return False, ("project %s names no provider to match against (it declares %s)" % (project or "?", names)
                       + ("; " + why if why else ""))
    return False, "not compatible with %s (it declares %s)" % (", ".join(tried), names)


def matches(declared, project, answers, surfaces):
    try:
        return evaluate(declared, answers, project, surfaces)[0]
    except ValueError:
        return False


def main(argv):
    try:
        if len(argv) == 2 and argv[0] == "valid":
            try:
                declared = json.loads(argv[1]) if argv[1].strip() else None
            except ValueError:
                declared = "not JSON"
            bad = problem(declared)
            if bad:
                print(bad)
                return 2
            return 0
        if len(argv) >= 4 and argv[0] == "check":
            conf = None
            if len(argv) == 6 and argv[4] == "--conf":
                conf = argv[5]
            elif len(argv) != 4:
                raise IndexError
            project, surfaces = argv[1], [s for s in argv[2].split(",") if s]
            if not surfaces or any(s not in SURFACES for s in surfaces):
                print("surfaces: local, cloud or local,cloud")
                return 2
            try:
                declared = json.loads(argv[3])
            except ValueError:
                declared = "not JSON"
            bad = problem(declared)
            if bad:
                print(bad)
                return 2
            answers = None
            if declared != [ANY]:
                answers = _provider().project_answers(project, conf)
            ok, why = evaluate(declared, answers, project, surfaces)
            if not ok:
                print(why)
                return 1
            return 0
    except IndexError:
        pass
    print("usage: packs_compat.py valid JSON | check PROJECT SURFACES JSON [--conf DIR]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
