#!/usr/bin/env python3
"""Command requests prepared by the lead; RUN files never select a request.

The profile resolver remains agent for. This module binds its answer to the
runtime, catalog and effective policy, and validates explicit run overrides.
These are requested controls, not observations of the runtime's identity.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider as P
from procenv import clean_path

HERE = os.path.dirname(os.path.abspath(__file__))
GUIDANCE = "; re-prepare with qargi local prepare before running"
BINDINGS = ("runtime", "catalog", "composition", "selection", "policy")


class Invalid(ValueError):
    """A malformed or stale prepared request."""


def need(ok, message):
    if not ok:
        raise Invalid(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def validate(request):
    """Strict bounded shape, shared with the private lifecycle record reader."""
    need(type(request) is dict and set(request) == set(
        "schema project runtime mode role class selector profile base model model_id effort binding".split()),
        "invalid prepared command request fields")
    need(type(request["schema"]) is int and request["schema"] == 1 and request["mode"] == "command",
         "invalid prepared command request schema/mode")
    for key in ("project", "runtime", "role", "profile"):
        need(isinstance(request[key], str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", request[key]),
             "invalid prepared command request " + key)
    need(request["selector"] is None or (isinstance(request["selector"], str)
         and re.fullmatch(r"[a-z][a-z0-9-]{0,30}", request["selector"])), "invalid prepared profile selector")
    need((request["base"], request["class"]) in (("worker", "write"), ("reviewer", "read-only")),
         "invalid prepared command request base/class")
    for key in ("model", "model_id"):
        value = request[key]
        try:
            valid = isinstance(value, str) and 1 <= len(value.encode("utf-8")) <= 1024
        except UnicodeError:
            valid = False
        need(valid and all(ord(c) >= 32 and ord(c) != 127 for c in value), "invalid prepared command request " + key)
    need(request["effort"] in P.EFFORTS, "invalid prepared command request effort")
    b = request["binding"]
    need(type(b) is dict and set(b) == set(BINDINGS), "invalid prepared command request binding")
    for value in b.values():
        need(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "invalid prepared command request hash")
    return request


def prepare(project, runtime, role, cls, selector=None):
    """Resolve and bind before prepare creates RUN/TMP/clone artifacts."""
    comp = P.compose(runtime, "local", project)
    dispatch = comp["definition"].get("dispatch")
    need(isinstance(dispatch, dict) and dispatch.get("mode") == "command", "runtime dispatch mode changed" + GUIDANCE)
    args = ["bash", HERE + "/agent.sh", "for", role, "--project", project, "--json"]
    if selector is not None:
        args += ["--profile", selector]
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            env=dict(os.environ, PATH=clean_path(), DA_NOSETUP="1"), close_fds=True, timeout=30)
    need(result.returncode == 0, result.stderr.strip() or "command profile resolution failed")
    try:
        selection = json.loads(result.stdout)
        need(selection["mode"] == "command" and selection["class"] == cls, "command profile mode/class mismatch")
        model = selection["model"] or selection["model_id"]
        request = dict(schema=1, project=project, runtime=runtime, mode="command", role=role,
                       **{"class": cls}, selector=selector, profile=selection["profile"], base=selection["base"],
                       model=model, model_id=selection["model_id"], effort=selection["effort"])
    except (ValueError, KeyError, TypeError) as e:
        raise Invalid("malformed command profile resolution") from e
    models = P.models_of(runtime, "local", project=project)
    policy = {key: P.cap(runtime, "local", key, project=project) for key in (
        "per_dispatch_model_override", "per_dispatch_effort_override", "read_only_barrier")}
    policy["accept_no_barrier"] = P.accepted(project, "local")
    profiles = (P.project_answers(project) or {}).get("profiles")
    selected_input = {"present": isinstance(profiles, dict) and selection["profile"] in profiles,
                      "value": profiles.get(selection["profile"]) if isinstance(profiles, dict) else None}
    with open(HERE + "/model-defaults.json", encoding="utf-8") as source:
        defaults = json.load(source)
    request["binding"] = dict(runtime=P.definition_hash(runtime), catalog=digest(models),
                              composition=digest(comp), selection=digest([selection, selected_input, defaults]), policy=digest(policy))
    return validate(request)


def current(request, project, runtime, cls):
    """Fail closed on drift; never bless changed inputs or update private state."""
    validate(request)
    need((project, runtime, cls) == (request["project"], request["runtime"], request["class"]),
         "prepared command request project/runtime/class drift" + GUIDANCE)
    try:
        fresh = prepare(project, runtime, request["role"], cls, request["selector"])
    except (Invalid, P.ProviderError, subprocess.SubprocessError, OSError) as e:
        raise Invalid("prepared command request cannot be resolved: %s%s" % (e, GUIDANCE)) from e
    need(fresh == request, "prepared command request runtime/mode/catalog/profile/policy drift" + GUIDANCE)


def values(request, model, effort):
    """None means omitted; explicit empty values refuse. Do not mutate request."""
    runtime, project = request["runtime"], request["project"]
    ms = P.models_of(runtime, "local", project=project)
    name = request["model"]
    if model is not None:
        need(bool(model), "--model must not be empty")
        if model in P.TIERS:
            name = P.model_for(ms, model)
        else:
            row = next((r for r in ms["tiers"].values() if model in (r.get("model"), r.get("alias"))), None)
            need(row is not None or re.search(ms["pattern"] or r"^.+$", model),
                 "--model %s: neither a tier nor a model of the current catalog/pattern of %s" % (model, runtime))
            if row:
                name = (row.get("alias") if ms.get("use") == "alias" else None) or row["model"]
            else:
                name = model
        # Compare identities, so spelling a prepared id through its alias needs no override support.
        same = name == request["model"] or any(request["model_id"] == r.get("model") and name in (r.get("model"), r.get("alias"))
                                                for r in ms["tiers"].values())
        need(same or P.effective(runtime, "local", "per_dispatch_model_override", project=project) in ("yes", "partial"),
             "--model override is not supported by %s (per_dispatch_model_override); choose a profile and re-prepare" % runtime)
    level = request["effort"] if effort is None else effort
    need(level in ms["effort"], "--effort %s: one of %s" % (level, ", ".join(ms["effort"])))
    native = ms["effort"][level]
    need(effort is None or native is None or native == ms["effort"][request["effort"]]
         or P.effective(runtime, "local", "per_dispatch_effort_override", project=project) in ("yes", "partial"),
         "--effort override is not supported by %s (per_dispatch_effort_override); choose a profile and re-prepare" % runtime)
    notes = [] if native is not None else ["effort %s is dropped: %s has no control for it" % (level, runtime)]
    return name, native, notes, level


def main(argv):
    try:
        if len(argv) == 2 and argv[0] == "mode":
            dispatch = P.definition(argv[1], "local").get("dispatch")
            need(dispatch is None or isinstance(dispatch, dict), "invalid runtime dispatch data")
            print((dispatch or {}).get("mode", ""))
            return 0
        need(len(argv) in (4, 5), "prepared request requires PROJECT RUNTIME ROLE CLASS [PROFILE]")
        print(json.dumps(prepare(*argv[:4], selector=argv[4] if len(argv) == 5 else None), sort_keys=True))
        return 0
    except (Invalid, P.ProviderError, subprocess.SubprocessError, OSError) as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
