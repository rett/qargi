#!/usr/bin/env bash
# Members: the local agents that do the work, named by you. qargi ships one neutral member definition (agents/member.json and
# agents/member.body.md, no word of any runtime); `add` renders it through the renderers.agent data of the project's local runtime (lib/render.py)
# under the name you choose, with the abilities it serves (roles: build, write, review, test and yours; a task block carries the role's text).
# The members are recorded in ~/.qargi/config/agents.json with the hash of the file and of what it was rendered from: `list` and `models`
# show STALE when the definition, the catalog or the body changed since (qargi agent refresh) and DRIFT when the file was edited by hand.
#
#   agent.sh add NAME [--abilities build,write,review,test] [--model M] [--effort E] (--project P | --user)
#   agent.sh list
#   agent.sh rename OLD NEW [--user]
#   agent.sh refresh NAME [--user]      re-render a member from the current definition, keeping its name, abilities, model and effort
#
# Where a member's file goes. A project's member (--project) goes where the runtime's definition links the project's agents (resources.agents.link.project):
# entry-symlinks, dir-symlink or copy: into the project's member render under ~/.qargi (state/render/P/RUNTIME.agents), which `qargi project link P
# --resource agents` links into the checkout; none: straight into the checkout's agents directory (hidden from git), as it always was. Nothing is
# ever written to a runtime's user-level directory (for Claude Code ~/.claude/agents) unless --user says so, on add, refresh and rename.
#   agent.sh models [--project P] [--json]     the bases, the profiles (shipped and the project's), the members and what is wrong with them
#   agent.sh remove NAME
#   agent.sh for ROLE [--profile P] [--project P] [--json]     the member, model and effort for ROLE under a profile: dispatch spawns it
#   agent.sh for ROLE [--profile P] --surface cloud --project P [--opt-in] [--json]     the same for the cloud: the registered instance
#                                                              (<project>-worker or -reviewer, else the legacy <project>-ROLE), its model id and effort
. "$(dirname "$0")/lib.sh"

root=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
DEFAULTS=$root/lib/model-defaults.json   # the one table: the bases (one per guard class) and the profiles (a base, a tier and an effort each)

# The provider definitions are read through lib/provider.py (the shipped ones and the library's, schema 1 and 2), never as files. The member
# renderer is that module's neighbour, lib/render.py. This program runs isolated; AGENT_PY holds it, apy runs it.
AGENT_PY=$(cat <<'PYEOF'
# The member renderer, run by lib/agent.sh as: python3 -I -c "$AGENT_PY" LIBDIR VERB ARGS...  (stdlib only, isolated)
#   pdesc PROV                                        the provider as the loader shows it: tiers, aliases, effort, model_pattern, local.reserved_names, adapter
#   names                                             the providers that have a definition, one per line
#   render PROV NAME ABILITIES CLASS MODEL EFFORT [PROJECT]
#                                                     the member file the runtime of PROV renders: {runtime, path, content, sha256, inputs_hash, notes, agents}
#                                                     (a provider with no renderers.agent, a schema 1 descriptor, has its adapter render: verb dispatch-local).
#                                                     With a PROJECT the runtime is the one composed with the extensions the project enabled (its
#                                                     renderer and agents resource, and the extensions in the inputs hash); without, the runtime's own
#   states MEMBERS_FILE ROLE_CLASSES_JSON             {member: [MISSING | STALE | DRIFT ...]} against what the runtime would render today
import hashlib
import json
import os
import subprocess
import sys

LIB = sys.argv[1]
sys.path.insert(0, LIB)
import provider as P  # noqa: E402
import render as R  # noqa: E402

AGENTS = os.path.join(os.path.dirname(LIB), "agents")


class Fail(Exception):
    pass


def render_runtime(prov, project=None):
    """The runtime whose definition renders the members of PROV: PROV itself when its definition carries renderers.agent. A schema 1
    descriptor (the shipped claude.json) carries none; its members are rendered by the one local runtime whose family is its name.
    None when there is no such runtime: the descriptor is then a schema 1 one with nothing but its adapter (render_legacy). With a
    project the definition is the composed one: a renderer an enabled extension adds counts, and a conflict or a changed extension
    of the project is raised (ProviderError), not hidden."""
    def has(n):
        try:
            P.definition(n, "local")                    # a runtime that does not load is no candidate (whatever it is)
        except P.ProviderError:
            return False
        return bool(((P.composed(n, "local", project).get("renderers") or {}).get("agent")))
    if has(prov):
        return prov
    found = [n for n in P.names() if n != prov and has(n) and P.definition(n, "local").get("family") == prov]
    if len(found) > 1:
        raise Fail("the family '%s' has more than one local runtime with a member renderer (%s); name one of them" % (prov, ", ".join(found)))
    return found[0] if found else None


def guard_command(rt, cls):
    """The hook command of a member: it names the runtime only when that runtime's hook protocol is not the one the guard assumes."""
    cmd = "qargi __guard"
    try:
        import guard
        plain = guard.hook_of(rt) == guard.CLAUDE_HOOK
    except Exception:
        plain = False
    if not plain:
        cmd += " --provider " + rt
    return cmd + (" --class read-only" if cls == "read-only" else "")


def render_legacy(prov, name, abilities, cls, model, effort):
    """A schema 1 descriptor has no renderers: its adapter renders the member (verb dispatch-local), as it did before renderers existed."""
    d = P.load(prov)
    ad = d.get("adapter")
    if not isinstance(ad, str) or not os.path.isfile(os.path.join(os.path.dirname(LIB), ad)):
        raise Fail("the provider '%s' has no member renderer (its definition names no renderers.agent) and no adapter to render with, so it cannot serve members" % prov)
    req = {"member": name, "abilities": list(abilities), "class": cls, "model": model, "effort": effort or None}
    r = subprocess.run([os.path.join(os.path.dirname(LIB), ad), "dispatch-local"], input=json.dumps(req), capture_output=True, text=True)
    try:
        text = json.loads(r.stdout)["definition"]["text"] if r.returncode == 0 else None
        err = None if r.returncode == 0 else json.loads(r.stdout).get("error")
    except (ValueError, KeyError, TypeError):
        text, err = None, "unreadable answer"
    if text is None:
        raise Fail("the adapter of %s could not render the member definition (exit %d): %s" % (prov, r.returncode, err or ""))
    ag = (P.definition(prov, "local").get("resources") or {}).get("agents") or {}
    if not ag.get("project_dir"):
        raise Fail("the provider '%s' keeps no agent files (its definition has no resources.agents), so it cannot serve members" % prov)
    content = text.rstrip("\n") + "\n"
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    inputs = json.dumps({"adapter": ad, "request": req, "definition": P.definition_hash(prov), "content": sha}, sort_keys=True, separators=(",", ":"))
    return {"runtime": prov, "path": name + (ag.get("ext") or ".md"), "content": content, "sha256": sha,
            "inputs_hash": hashlib.sha256(inputs.encode("utf-8")).hexdigest(), "notes": [],
            "agents": {"project_dir": ag["project_dir"], "user_dir": ag.get("user_dir"), "link": ag.get("link")}}


def render_member(prov, name, abilities, cls, model, effort, project=None):
    rt = render_runtime(prov, project)
    if rt is None:
        return render_legacy(prov, name, abilities, cls, model, effort)
    comp = P.compose(rt, "local", project) if project else None
    doc = comp["definition"] if comp else P.definition(rt, "local")
    spec = doc["renderers"]["agent"]
    if spec.get("engine", "map") != "map":
        raise Fail("the member renderer of %s is a '%s' renderer; only the map engine renders members for now" % (rt, spec.get("engine")))
    res = doc.get("resources") or {}
    ag = res.get("agents")
    if not isinstance(ag, dict) or not ag.get("project_dir"):
        raise Fail("the runtime %s keeps no agent files (its definition has no resources.agents), so it cannot serve members" % rt)
    with open(os.path.join(AGENTS, "member.json"), encoding="utf-8") as f:
        meta = json.load(f)
    with open(os.path.join(AGENTS, meta["body"]), encoding="utf-8") as f:
        body = f.read()
    models = P.models_of(rt, "local")
    tier = next((t for t in P.TIERS if model in (models["tiers"][t].get("alias"), models["tiers"][t]["model"])), None)

    def resolve(kind, value, definition):
        if kind == "effort":
            return models["effort"].get(value)
        if kind == "model":
            return P.model_for(models, value) if value in models["tiers"] else None
        raise R.RenderError("no resolver for %r" % kind)
    inst = {"name": name, "description": meta["description"].replace("{abilities}", ", ".join(abilities)), "abilities": list(abilities),
            "class": cls, "tier": tier, "model": model, "effort": effort or None, "tools": meta["tools"],
            "barrier": {"class": cls, "guard_command": guard_command(rt, cls)},
            "body": body.replace("{skills_dir}", (res.get("skills") or {}).get("project_dir") or "skills")}
    try:
        extra = {"runtime": rt, "definition": P.definition_hash(rt)}
        if comp and comp["extensions"]:                  # a changed extension makes the render STALE; a project with none keeps the hash it always had
            extra["extensions"] = {x: P.extension_hash(x, rt, "local") for x in comp["extensions"]}
        out = R.render_map(inst, spec, resolver=resolve, extra=extra)
    except R.RenderError as e:
        raise Fail("the member cannot be rendered for %s: %s" % (rt, e))
    out["runtime"] = rt
    out["agents"] = {"project_dir": ag["project_dir"], "user_dir": ag.get("user_dir"), "link": ag.get("link")}
    return out


def states(members_file, rc):
    with open(members_file, encoding="utf-8") as f:
        members = json.load(f)
    out = {}
    for name, rec in members.items():
        st, r, f = [], rec.get("render"), rec.get("file") or ""
        if not os.path.isfile(f):
            out[name] = ["MISSING"]
            continue
        with open(f, "rb") as fh:
            if isinstance(r, dict) and r.get("hash") and hashlib.sha256(fh.read()).hexdigest() != r["hash"]:
                st.append("DRIFT")
        ab = rec.get("abilities") or []
        cls = "read-only" if ab and all(rc.get(a) == "read-only" for a in ab) else "write"
        try:
            if not (isinstance(r, dict) and r.get("inputs_hash")) or not rec.get("provider"):
                raise Fail("no render is recorded")
            now = render_member(rec["provider"], name, ab, cls, rec.get("model") or "", rec.get("effort") or "", rec.get("project"))
            if now["inputs_hash"] != r["inputs_hash"]:
                raise Fail("the inputs changed")
        except (Fail, P.ProviderError):
            st.insert(0, "STALE")
        out[name] = st
    return out


def main(argv):
    verb, a = argv[2], argv[3:]
    try:
        if verb == "pdesc" and len(a) == 1:
            print(json.dumps(P.load(a[0])))
        elif verb == "names" and not a:
            print("\n".join(P.names()))
        elif verb == "render" and len(a) in (6, 7):
            print(json.dumps(render_member(a[0], a[1], [x for x in a[2].split(",") if x], a[3], a[4], a[5], (a[6] if len(a) == 7 else "") or None)))
        elif verb == "states" and len(a) == 2:
            print(json.dumps(states(a[0], json.loads(a[1]))))
        else:
            raise Fail("usage: agent.sh internal call %s" % verb)
    except (Fail, P.ProviderError) as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1
    return 0


sys.exit(main(sys.argv))
PYEOF
)
apy() { python3 -I -c "$AGENT_PY" "$root/lib" "$@"; }
PCACHE=$(mktemp -d); trap 'rm -rf "$PCACHE"' EXIT   # a provider is read once per run, however many subshells ask
pdesc() { # provider -> its description as the loader gives it: tiers, aliases, effort, model_pattern, local.reserved_names, adapter
  [ -s "$PCACHE/$1" ] || apy pdesc "$1" > "$PCACHE/$1.tmp" || return 1
  [ -s "$PCACHE/$1" ] || mv "$PCACHE/$1.tmp" "$PCACHE/$1"
  cat "$PCACHE/$1"
}

verb=${1:-}; shift || true
POS=() ABIL='' MODEL='' EFFORT='' PROJ='' JSON='' PROFILE='' SURFACE='' OPTIN='' USERLVL=''
while [ $# -gt 0 ]; do
  case $1 in
    --abilities) ABIL=$2; shift 2;;
    --model) MODEL=$2; shift 2;;
    --effort) EFFORT=$2; shift 2;;
    --project) PROJ=$2; shift 2;;
    --profile) PROFILE=$2; shift 2;;
    --json) JSON=1; shift;;
    --surface) SURFACE=${2:-}; shift 2;;
    --opt-in) OPTIN=1; shift;;
    --user) USERLVL=1; shift;;
    -*) die "unknown option $1";;
    *) POS+=("$1"); shift;;
  esac
done

valid_name() { # name provider -> dies with the rule (the reserved names are the provider's)
  local n=$1 b lc p=$2
  printf '%s' "$n" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$' && [ "${#n}" -le 40 ] \
    || die "'$n' is not a member name: kebab-case, lower-case letters, digits and single '-' (at most 40)"
  lc=$(printf '%s' "$n" | tr '[:upper:]' '[:lower:]')
  for b in $(pdesc "$p" | jq -r '.local.reserved_names[]'); do
    [ "$lc" != "$b" ] || die "'$n' is a built-in agent type of the provider; choose another name"
  done
  if [ "$n" = lead ] || valid_role "$n"; then die "'$n' is a role; name the member after itself, for example forge or scribe"; fi
}

repo_path() { # project -> its local repository (dies when the answers name none)
  local f=$DA_CONF/projects/$1.json rp
  [ -f "$f" ] || die "no stored answers for $1"
  rp=$(jq -r '.repo.path // ""' "$f"); rp=${rp/#\~/$HOME}
  [ -n "$rp" ] && [ -d "$rp" ] || die "--project $1: its answers name no local repository (repo.path)"
  echo "$rp"
}

link_mode() { # rendered-json -> how the runtime's definition links the project's agents (entry-symlinks, dir-symlink, copy or none)
  jq -r '.agents.link.project // "none"' <<<"$1"
}

agents_dir() { # project-or-empty rendered-json -> the directory the definition goes to
  # a project's member: the project's member render when the definition links the project's agents (project link puts them in the checkout), else the checkout's
  # agents directory; a user-level member (--user, no project): the runtime's user-level directory, which nothing else ever writes
  local d
  if [ -n "$1" ]; then
    if [ "$(link_mode "$2")" != none ]; then python3 -I "$root/lib/project_link.py" members-dir "$1" "$(jq -r .runtime <<<"$2")"; return; fi
    d=$(jq -r '.agents.project_dir' <<<"$2"); echo "$(repo_path "$1")/$d"
  else
    d=$(jq -r '.agents.user_dir // empty' <<<"$2")
    [ -n "$d" ] || die "the runtime $(jq -r .runtime <<<"$2") keeps no user-level agents; give --project"
    echo "${d/#\~/$HOME}"
  fi
}

need_place() { # verb project-of-the-member-or-empty: a member of no project is a user-level one, and nothing writes there without --user (exit 2)
  if [ -n "$USERLVL" ] && [ -n "$2" ]; then echo "qargi: --user is for a user-level member; this one belongs to project $2" >&2; exit 2; fi
  if [ -z "$USERLVL" ] && [ -z "$2" ]; then
    echo "qargi: $1 writes the definition of a member: give --project NAME (the project it belongs to; its definition goes where the runtime links the project's agents) or --user (a user-level member, in the runtime's own user-level directory)" >&2
    exit 2
  fi
}

link_note() { # project rendered-json file: a member in the project's member render is seen by the checkout once project link has linked it
  local co d
  [ "$(link_mode "$2")" != none ] || return 0
  co=$(repo_path "$1" 2>/dev/null) || return 0
  d=$(jq -r '.agents.project_dir' <<<"$2")
  [ "$(readlink -f "$co/$d/$(basename "$3")" 2>/dev/null)" != "$(readlink -f "$3")" ] || return 0
  echo "qargi: note: the checkout $co does not see this file yet: qargi project link $1 --resource agents (run it inside each worktree that should have it)" >&2
}

hide_in_git() { # repo file: keep a project-level definition out of the repository's commits
  local repo=$1 rel=$2 ex
  git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || return 0
  ex=$(git -C "$repo" rev-parse --git-path info/exclude); case $ex in /*) ;; *) ex=$repo/$ex;; esac
  mkdir -p "$(dirname "$ex")"; touch "$ex"
  grep -qx -F "/$rel" "$ex" || printf '/%s\n' "$rel" >> "$ex"
}

default_row() { # ability -> the table's profile row for it (a role of yours falls back to its class: write -> build, read-only -> review)
  case " $ROLE_BUILTIN " in *" $1 "*) jq -e --arg a "$1" '.profiles | has($a)' "$DEFAULTS" >/dev/null && { echo "$1"; return; };; esac
  case $(role_class "$1" 2>/dev/null) in read-only) echo review;; *) echo build;; esac
}

project_answer() { # project ability field(model|effort) -> the project's valid answer, or nothing
  local f=$DA_CONF/projects/$1.json v
  [ -n "$1" ] && [ -f "$f" ] || return 0
  v=$(jq -r --arg a "$2" --arg k "$3" 'if $a == "lead" then .lead[$k] else .roles[$a][$k] end // empty' "$f" 2>/dev/null) || return 0
  case $3 in
    model) printf '%s' "$v" | grep -Eq '^[a-z0-9][a-z0-9.-]*$' && echo "$v";;
    effort) case $v in low|medium|high|xhigh|max) echo "$v";; esac;;
  esac
  return 0
}

project_in_effect() { # explicit-project-or-empty -> that project, else the one in effect here (QARGI_PROJECT, else the checkout's), else empty
  if [ -n "$1" ]; then echo "$1"; else python3 -I "$root/lib/help.py" infer; fi
}

provider_for() { # project-or-empty surface -> the project's runtime on that surface (models.provider; no default, see project_provider); dies when it has no descriptor
  local p; p=$(project_provider "$1" "$2") || return $?   # exit 2 with the shared message: no project, no such project, no provider for the surface
  local err
  err=$(pdesc "$p" 2>&1 >/dev/null) || die "models.provider '$p' cannot be loaded (${err#qargi: }); available: $(apy names | paste -sd, - | sed 's/,/, /g')"
  echo "$p"
}

no_effort() { # provider -> 0 when the provider has no effort control (every effort level is null in its definition)
  pdesc "$1" | jq -e '[.effort[]] | all(. == null)' >/dev/null
}

tier_model() { # provider tier -> the provider's model id
  pdesc "$1" | jq -r --arg t "$2" '.tiers[$t]'
}

adapter_run() { # provider surface verb < request -> the adapter's answer on stdout, its exit status; lib/provider.py finds it (a library pack's only as a sealed private copy)
  python3 -I "$root/lib/provider.py" adapter-run "$@"
}

default_for() { # project ability field provider -> the project's answer for it, else the table's value (a tier is resolved through the project's provider)
  local v; v=$(project_answer "$1" "$2" "$3")
  if [ -z "$v" ]; then
    if [ "$3" = model ]; then v=$(tier_model "$4" "$(jq -r --arg r "$(default_row "$2")" '.profiles[$r].tier' "$DEFAULTS")")
    else v=$(jq -r --arg r "$(default_row "$2")" --arg k "$3" '.profiles[$r][$k]' "$DEFAULTS"); fi
  fi
  echo "$v"
}

member_class() { # abilities-csv -> the guard class of a member: read-only when every ability is, else write
  local a cls=read-only
  for a in $(printf '%s' "$1" | tr ',' ' '); do [ "$(role_class "$a")" = read-only ] || cls='write'; done
  echo "$cls"
}

render_member() { # name abilities-csv model effort-or-empty provider [project] -> prints {runtime, path, content, sha256, inputs_hash, notes, agents} (the runtime's renderers.agent,
  local e=$4                                       # as composed with the extensions of the member's project, when it has one)
  ! no_effort "$5" || e=''
  apy render "$5" "$1" "$2" "$(member_class "$2")" "$3" "$e" "${6:-}"
}

member_record() { # rendered-json -> what the member's record keeps of it: the path, the hash of the bytes and the hash of the inputs
  jq -c '{path: .path, hash: .sha256, inputs_hash: .inputs_hash}' <<<"$1"
}

write_member() { # rendered-json file: say what the runtime could not express, then write the file (the old one is replaced whole)
  local r=$1 f=$2
  jq -r '.notes[] | "qargi: note: " + .' <<<"$r" >&2
  mkdir -p "$(dirname "$f")"
  jq -j .content <<<"$r" > "$f.tmp.$$" && mv -f "$f.tmp.$$" "$f"
}

add() {
  local n=${POS[0]:-} eproj a list='' dir file seq first bc prov r ro ORIG_EFFORT=$EFFORT
  [ -n "$n" ] || die "usage: qargi agent add NAME [--abilities build,write,review,test] [--model M] [--effort E] (--project P | --user)"
  need_place "agent add" "$PROJ"
  # the provider is the project's (models.provider; no default): --project, else the project in effect here. --project makes the member the
  # project's (its file goes where the runtime links the project's agents); --user makes it a user-level one and the project in effect lends its provider for this run
  eproj=$(project_in_effect "$PROJ")
  prov=$(provider_for "$eproj" local) || exit $?
  valid_name "$n" "$prov"
  jq -e --arg n "$n" 'has($n)' "$MEMBERS_FILE" >/dev/null && die "a member named $n exists already (qargi agent list)"
  bc=$(jq -r --arg n "$n" '.bases[$n].class // empty' "$DEFAULTS")   # a base name takes the abilities of its class only
  [ -z "$bc" ] || [ -n "$ABIL" ] || ABIL=$(jq -r --arg n "$n" '.bases[$n].abilities | join(",")' "$DEFAULTS")
  for a in $(printf '%s' "${ABIL:-build,write,review,test}" | tr ',' ' '); do
    [ "$a" != lead ] && valid_role "$a" || die "--abilities: a comma-separated list of roles ($DA_ROLES; qargi role list)"
    [ -z "$bc" ] || [ "$(role_class "$a")" = "$bc" ] || die "--abilities: $n is a base of the $bc class; $a is $(role_class "$a")"
    case ",$list," in *",$a,"*) ;; *) list=${list:+$list,}$a;; esac
  done
  [ -n "$list" ] || die "--abilities: give at least one"
  first=${list%%,*}
  # a member that only reviews is read-only by class: the provider must have a read-only barrier on the local surface, or the project must have accepted that
  ro=1; for a in $(printf '%s' "$list" | tr ',' ' '); do [ "$(role_class "$a")" = read-only ] || ro=''; done
  [ -z "$ro" ] || barrier_guard local "$eproj"
  [ -n "$MODEL" ] || MODEL=$(default_for "$PROJ" "$first" model "$prov")
  [ -n "$EFFORT" ] || EFFORT=$(default_for "$PROJ" "$first" effort "$prov")
  if no_effort "$prov"; then   # the provider cannot be told how hard to think: the member records none
    [ -z "$ORIG_EFFORT" ] || echo "qargi: note: effort ignored ($prov has no effort control)" >&2
    EFFORT=''
  fi
  printf '%s' "$MODEL" | grep -Eq '^[a-z0-9][a-z0-9.-]*$' || die "--model: a model alias or id (letters, digits, . -)"
  case $EFFORT in ''|low|medium|high|xhigh|max) ;; *) die "--effort low|medium|high|xhigh|max";; esac
  r=$(render_member "$n" "$list" "$MODEL" "$EFFORT" "$prov" "$PROJ") || exit 1
  dir=$(agents_dir "$PROJ" "$r") || exit 1; file=$dir/$(jq -r .path <<<"$r")
  [ ! -e "$file" ] && [ ! -L "$file" ] || die "$file exists already; choose another name or remove it first"
  write_member "$r" "$file"
  [ -z "$PROJ" ] || [ "$(link_mode "$r")" != none ] || hide_in_git "$(repo_path "$PROJ")" "$(jq -r '.agents.project_dir + "/" + .path' <<<"$r")"
  seq=$(jq '[.[].seq // 0] | max // 0 | . + 1' "$MEMBERS_FILE")
  json_update "$MEMBERS_FILE" '.[$n] = {abilities: ($a | split(",")), file: $f, model: $m, effort: (if $e == "" then null else $e end),
      project: (if $p == "" then null else $p end), created: $t, seq: $s, provider: $v, surface: "local", render: $r}' \
    --arg n "$n" --arg a "$list" --arg f "$file" --arg m "$MODEL" --arg e "$EFFORT" --arg p "$PROJ" --arg t "$(now)" --argjson s "$seq" \
    --arg v "$prov" --argjson r "$(member_record "$r")"
  echo "member $n ($list) at $file"
  [ -z "$PROJ" ] || link_note "$PROJ" "$r" "$file"
}

# The profile resolver, in jq. Inputs ($d the table, $tiers and $aliases the provider's, $pf the project's answers or {}, $rc each role's class):
# `profiles` is the list of every profile, the shipped ones with the project's entries merged over them key by key. It is defensive:
# a malformed entry, key or value is ignored, never an error; what cannot be honoured is marked in `refused`.
PJQ=$(cat <<'EOF'
def okeff: . == "low" or . == "medium" or . == "high" or . == "xhigh" or . == "max";
def okmod: type == "string" and test("^[a-z0-9][a-z0-9.-]*$");
def tier_of($m): ([$aliases | to_entries[] | select(.value == $m) | .key][0]) // ([$tiers | to_entries[] | select(.value == $m) | .key][0]);
def pclean: if type == "object" then
    {} + (if (.base | type) == "string" then {base} else {} end)
       + (if (.tier | type) == "string" and (.tier | test("^[a-z]+$")) then {tier} else {} end)
       + (if (.model | okmod) then {model} else {} end)
       + (if (.effort | okeff) then {effort} else {} end)
       + (if (.purpose | type) == "string" then {purpose} else {} end)
       + (if (.abilities | type) == "array" then {abilities: [.abilities[] | select(type == "string")]} else {} end)
  else null end;
def pprofiles: (($pf.profiles // {}) | if type == "object" then . else {} end)
  | with_entries(select((.key | test("^[a-z][a-z0-9-]{0,30}$")) and .key != "lead") | .value |= pclean)
  | with_entries(select(.value != null));
def legacy($n): (if $n == "lead" then $pf.lead else (($pf.roles // {}) | .[$n]?) end)
  | if type == "object" then {model: (if (.model | okmod) then .model else null end), effort: (if (.effort | okeff) then .effort else null end)} else {model: null, effort: null} end;
def profiles:
  $d[0].profiles as $sh | pprofiles as $pp | $d[0].bases as $bases
  | [($sh | keys_unsorted[]), (($pp | keys_unsorted) - ($sh | keys_unsorted))[]][] as $n
  | $sh[$n] as $s | $pp[$n] as $p
  | (if $p == null then legacy($n) else {model: null, effort: null} end) as $lg
  | (($s // {}) + ($p // {})) as $m
  | ($m.base // null) as $base
  | (if $p.model then {k: "m", v: $p.model} elif $p.tier then {k: "t", v: $p.tier} elif $lg.model then {k: "m", v: $lg.model}
     else {k: "t", v: ($m.tier // "balanced")} end) as $sel
  | (if $sel.k == "m" then tier_of($sel.v) as $t | {tier: ($t // $m.tier // null), alias: (if $t then ($aliases[$t] // null) else null end), id: (if $t then ($tiers[$t] // null) else $sel.v end)}
     else {tier: $sel.v, alias: ($aliases[$sel.v] // null), id: ($tiers[$sel.v] // null)} end) as $r
  | (if $base == null then (if $n == "lead" then null else "no base: give base worker or reviewer" end)
     elif $bases[$base] == null then "base \($base) is not a base (\($bases | keys | join(", ")))"
     elif ([($m.abilities // [])[] | select($rc[.] != null and $rc[.] != $bases[$base].class)] | length) > 0
       then "abilities \(($m.abilities // []) | join(",")) do not fit base \($base) (\($bases[$base].class))"
     else null end) as $refused
  | {name: $n, base: $base, class: (if $base != null then ($bases[$base].class? // null) else null end), tier: $r.tier, model: $r.alias, model_id: $r.id,
     effort: (if $noeffort then null else ($p.effort // $lg.effort // $m.effort // "medium") end), opt_in: ($s.opt_in // false), purpose: ($m.purpose // ""),
     abilities: ($m.abilities // null), shipped: ($s != null), project: ($p != null), via_roles: (($lg.model != null or $lg.effort != null)),
     source: (if $p != null or $lg.model != null or $lg.effort != null then "project" else "shipped" end), refused: $refused};
EOF
)

pf_json() { # project-or-empty -> the project's stored answers as one object ({} when there are none or they are unreadable)
  local f=$DA_CONF/projects/$1.json
  if [ -n "$1" ] && [ -f "$f" ]; then jq -c 'if type == "object" then . else {} end' "$f" 2>/dev/null || echo '{}'; else echo '{}'; fi
}

member_states() { # role-classes-json -> {member: [MISSING | STALE | DRIFT]}: the file and the render on record against what the runtime renders today
  apy states "$MEMBERS_FILE" "$1"
}

role_classes() { # -> {role: class} for every role (a role without a readable class is left out)
  local r c o='{}'
  for r in $DA_ROLES; do
    [ "$r" != lead ] || continue
    c=$(role_class "$r" 2>/dev/null) || continue
    o=$(jq -c --arg r "$r" --arg c "$c" '.[$r] = $c' <<<"$o")
  done
  echo "$o"
}

models() { # the bases, the profiles with the project's own merged in, the escalation and the registered members
  local proj=$PROJ pf prov pd tiers aliases rc out noeff=false st
  if [ -n "$proj" ]; then [ -f "$DA_CONF/projects/$proj.json" ] || die "no stored answers for $proj"
  else proj=$(python3 -I "$root/lib/help.py" infer); fi
  pf=$(pf_json "$proj")
  prov=$(provider_for "$proj" local) || exit $?   # the members are local
  pd=$(pdesc "$prov") || exit 1
  tiers=$(jq -c .tiers <<<"$pd"); aliases=$(jq -c '.aliases // {}' <<<"$pd")
  rc=$(role_classes)
  ! no_effort "$prov" || noeff=true
  st=$(member_states "$rc") || exit 1
  out=$(jq -n --slurpfile d "$DEFAULTS" --slurpfile m "$MEMBERS_FILE" --argjson pf "$pf" --argjson tiers "$tiers" --argjson aliases "$aliases" --argjson rc "$rc" --argjson st "$st" --argjson noeffort "$noeff" --arg prov "$prov" --arg pat "$(jq -r .model_pattern <<<"$pd")" "$PJQ"'
    def mclass: if ((.abilities // []) | length) > 0 and all((.abilities // [])[]; $rc[.] == "read-only") then "read-only" else "write" end;
    ($d[0].bases) as $bases
    | ([$m[0] | to_entries[] | .value | mclass] | unique) as $have
    | def baseof($c): [$bases | to_entries[] | select(.value.class == $c) | .key][0];
    {provider: $prov, effort_control: ($noeffort | not), aliases: $aliases,
       bases: ($bases | with_entries(.key as $k | .value += {registered: ($m[0] | has($k))}
         | .value += {flags: (if .value.registered or (.value.class | IN($have[])) then [] else ["no \($k): \(.value.abilities | join(",")) profiles cannot dispatch"] end)})),
       profiles: ([profiles | .flags = ([if .refused then "refused: \(.refused)" else empty end,
           if .tier != null and ($aliases[.tier] // null) == null then "tier \(.tier) has no alias" else empty end,
           if .tier == null and .model_id != null then "model \(.model_id) has no alias; the definition of the member applies" else empty end]) | {key: .name, value: .}] | from_entries),
       escalate: ($d[0].escalate | with_entries(.value = {tier: .value, model: $tiers[.value]})),
       members: [$m[0] | to_entries | sort_by(.value.seq // 0)[] | .key as $k | (.value | mclass) as $c | baseof($c) as $bn | .value.abilities as $ab
         | {name: $k, abilities: $ab, class: $c, model: (.value.model // null),
         effort: (.value.effort // null), project: (.value.project // null), state: ($st[$k] // []),
         pinned: ((.value.model // "") | test($pat)),
         frontier: (((.value.model // "") == $tiers.frontier) or ((.value.model // "") == $aliases.frontier)),
         flags: ([if ($bases | has($k) | not) and $bn != null then (if ($m[0] | has($bn)) then "legacy: retire after \($bn) exists" else "legacy (in use: no \($bn))" end) else empty end,
           if ([$ab[] | select($rc[.] == "read-only")] | length) > 0 and ([$ab[] | select($rc[.] != "read-only")] | length) > 0 then "write class; never serves review" else empty end,
           if ($st[$k] // []) | index("MISSING") then "definition file missing" else empty end,
           if ($st[$k] // []) | index("STALE") then "STALE: rendered from an older definition, catalog or body, or from none on record (qargi agent refresh \($k))" else empty end,
           if ($st[$k] // []) | index("DRIFT") then "DRIFT: the file was edited by hand (qargi agent refresh \($k) replaces it)" else empty end,
           if (((.value.model // "") == $tiers.frontier) or ((.value.model // "") == $aliases.frontier)) and $k != "researcher" then "frontier model outside the researcher" else empty end])}]}
    | .warnings = ([(.bases | to_entries[] | .key as $k | .value.flags[] | {kind: "base", name: $k, message: .}),
        (.profiles[] | .name as $k | .flags[] | {kind: "profile", name: $k, message: .}),
        (.members[] | .name as $k | .flags[] | {kind: "member", name: $k, message: .})])')
  if [ -n "$JSON" ]; then printf '%s\n' "$out"; return 0; fi
  echo "bases (one member each, by guard class)"
  jq -r '.bases | to_entries[] | [.key, .value.class, (.value.abilities | join(",")), (if .value.registered then "registered" else "not registered" end), (.value.flags | map("! " + .) | join("; "))] | @tsv' <<<"$out" \
    | while IFS=$'\t' read -r n c a r fl; do printf '  %-10s %-10s %-18s %-15s %s\n' "$n" "$c" "$a" "$r" "$fl"; done
  echo "profiles (provider: $prov; tier -> alias -> model/effort; a role of yours uses its class: write -> build, read-only -> review)"
  [ "$noeff" = false ] || echo "  effort: ignored ($prov has no effort control)"
  jq -r '.profiles[] | [.name, (.base // "-"), ((.tier // "?") + " -> " + (.model // "-") + " -> " + (.model_id // "-") + "/" + (.effort // "default")),
      (.source + (if .via_roles then " (roles)" else "" end)), (if .opt_in then "opt-in" elif .name == "lead" then "never dispatched" else "" end), (.flags | map("! " + .) | join("; "))] | @tsv' <<<"$out" \
    | while IFS=$'\t' read -r n b d s t fl; do printf '  %-11s %-9s %-52s %-10s %s\n' "$n" "$b" "$d" "$s" "${t:+$t }$fl"; done
  jq -r '"  offer \(.escalate.build.tier) (\(.escalate.build.model)) for a hard task: only when asked"' <<<"$out"
  echo "members"
  if [ "$(jq '.members | length' <<<"$out")" = 0 ]; then echo "  none yet (qargi agent add NAME --project P, or --user)"; else
    jq -r '.members[] | "  \(.name)\t\(.abilities | join(","))\t\(.model // "-")/\(.effort // "default")\t\(.flags | map("! " + .) | join("; "))"' <<<"$out" \
      | while IFS=$'\t' read -r n a me note; do printf '  %-12s %-22s %-28s %s\n' "${n# }" "$a" "$me" "$note"; done
  fi
}

# the dispatch resolver, in jq (with $PJQ): one role, one profile -> the base member, model and effort, or an error with its exit code.
# RESOLVE_HEAD picks the profile and defines `refusal` (null, or the error of a profile that cannot run for this role); the local
# resolver (RESOLVEJQ) and the cloud one (CLOUDJQ) both start from it, so they refuse the same profiles in the same words.
RESOLVE_HEAD='
  [profiles | {key: .name, value: .}] | from_entries as $P
  | $d[0].bases as $bases
  | (if $rclass == "read-only" then "review" else "build" end) as $row
  | (if $prof != "" then $prof elif $P[$role] != null then $role else null end) as $want
  | (if $want != null then $want else $row end) as $pn
  | $P[$pn] as $p
  | def refusal:
      if $p == null then {code: 1, err: "no profile named \($pn) (qargi agent models lists them)"}
      elif $p.base == null then {code: 2, err: "the \($pn) profile has no base and is never dispatched"}
      elif $p.refused != null then {code: 2, err: "the \($pn) profile is refused: \($p.refused)"}
      elif $p.class != $rclass then {code: 2, err: "the \($role) role is \($rclass) but the \($pn) profile has base \($p.base), which is \($p.class); use a profile of a \($rclass) base"}
      else null end;'
RESOLVEJQ="$RESOLVE_HEAD"'
  def mclass: if ((.abilities // []) | length) > 0 and all((.abilities // [])[]; $rc[.] == "read-only") then "read-only" else "write" end;
  def serves($a): any((.abilities // [])[]; . == $a);
  ($m[0] | to_entries | map(select((.value.project // null) == null or .value.project == $proj))
      | sort_by((if (.value.project // "") == $proj and $proj != "" then 0 else 1 end), (.value.seq // 0))) as $E
  | def cands($a): [$E[] | select(.value | serves($a) and mclass == $rclass)];
    refusal // (
      ([$E[] | select(.key == $p.base and (.value | (any((.abilities // [])[]; $rc[.] == $rclass)) and mclass == $p.class))][0]) as $b
      | (if $b != null then {m: $b, legacy: false}
         else (cands($role)[0] // (if $row != $role then cands($row)[0] else null end)) as $l | if $l != null then {m: $l, legacy: true} else null end end) as $sel
      | if $sel == null then {code: 1, err: "no member serves the \($role) role: qargi agent add NAME --abilities \($role) (--project P | --user)"}
        else {code: 0, out: {role: $role, class: $rclass, profile: $pn,
          profile_source: (if $want == null then "class-fallback" elif $p.source == "project" then "project" else "shipped" end),
          base: $p.base, member: $sel.m.key, member_scope: (if $sel.m.value.project != null then "project" else "user" end), legacy: $sel.legacy,
          tier: $p.tier, model: $p.model, model_id: $p.model_id, effort: $p.effort, opt_in: $p.opt_in, purpose: $p.purpose}} end
    )'

resolve_for() { # role profile-or-empty project-or-empty -> prints the answer, or the reason on stderr (exit 1, or 2 for a refusal)
  local role=$1 prof=$2 proj=$3 pf prov pd res code noeff=false mem mm want ov
  pf=$(pf_json "$proj"); prov=$(provider_for "$proj" local) || exit $?
  ! no_effort "$prov" || noeff=true
  pd=$(pdesc "$prov") || exit 1
  res=$(jq -n --slurpfile d "$DEFAULTS" --slurpfile m "$MEMBERS_FILE" --argjson pf "$pf" --argjson tiers "$(jq -c .tiers <<<"$pd")" \
    --argjson aliases "$(jq -c '.aliases // {}' <<<"$pd")" --argjson rc "$(role_classes)" --argjson noeffort "$noeff" \
    --arg role "$role" --arg rclass "$(role_class "$role")" --arg prof "$prof" --arg proj "$proj" "$PJQ$RESOLVEJQ") || die "could not resolve the profile"
  code=$(jq -r .code <<<"$res")
  if [ "$code" != 0 ]; then echo "qargi: $(jq -r .err <<<"$res")" >&2; exit "$code"; fi
  # a provider that cannot set the model per dispatch runs the member's own model and no other
  ov=$(python3 -I "$root/lib/provider.py" effective "$prov" local per_dispatch_model_override ${proj:+--project "$proj"} 2>/dev/null) || ov=no
  if [ "$ov" = no ]; then
    mem=$(jq -r .out.member <<<"$res"); mm=$(jq -r --arg m "$mem" '.[$m].model // ""' "$MEMBERS_FILE")
    want=$(jq -r '.out.model // .out.model_id // ""' <<<"$res")
    if [ -n "$mm" ] && [ -n "$want" ] && [ "$mm" != "$want" ] && [ "$mm" != "$(jq -r '.out.model_id // ""' <<<"$res")" ]; then
      echo "qargi: the provider $prov cannot set the model per dispatch (per_dispatch_model_override is not supported on local), so member $mem (model $mm) cannot run the $(jq -r .out.profile <<<"$res") profile (model $want). Use one member per profile: qargi agent add NAME --abilities $role --model $want$([ -n "$proj" ] && echo " --project $proj" || echo " --user"), or choose a profile with the model of the member" >&2
      exit 2
    fi
  fi
  if [ -n "$JSON" ]; then jq '.out' <<<"$res"; return 0; fi
  jq -r '.out | "\(.member) \(.model // "-") \(.effort // "default") \(.profile)"' <<<"$res"
  if [ "$(jq -r '.out.model // ""' <<<"$res")" = "" ]; then
    echo "qargi: warning: model $(jq -r '.out.model_id' <<<"$res") has no alias; the definition of member $(jq -r .out.member <<<"$res") applies" >&2
  fi
}

# the cloud resolver, in jq (with $PJQ and RESOLVE_HEAD): one role, one profile -> the profile's base, tier, model id and effort, or the
# refusal. Which instance runs it is decided by resolve_cloud, from the registry.
CLOUDJQ="$RESOLVE_HEAD"'
  refusal // {code: 0, out: {role: $role, class: $rclass, profile: $pn, base: $p.base, tier: $p.tier, model: $p.model, model_id: $p.model_id,
    effort: $p.effort, opt_in: $p.opt_in}}'

cloud_inst() { # name -> the registry record when the name is a registered cloud instance, else nothing (inst_get dies on a miss: in a subshell)
  [ -f "$REG" ] || return 0
  (inst_get "$1" 2>/dev/null | jq -ec 'select(.location == "cloud")') 2>/dev/null || true
}

resolve_cloud() { # role profile-or-empty project -> prints INSTANCE MODEL EFFORT PROFILE (or --json), or the reason on stderr (exit 1, or 2 for a refusal)
  local role=$1 prof=$2 proj=$3 pf prov pd res code noeff=false base cls row model alias effort req out rc ovm=no ove=yes
  local inst='' legacy=true brec='' rec rm n why='' ov alt
  [ -n "$proj" ] || die "--surface cloud needs --project (the instances are named <project>-<role>)"
  pf=$(pf_json "$proj"); prov=$(provider_for "$proj" cloud) || exit $?
  ! no_effort "$prov" || noeff=true
  pd=$(pdesc "$prov") || exit 1
  res=$(jq -n --slurpfile d "$DEFAULTS" --argjson pf "$pf" --argjson tiers "$(jq -c .tiers <<<"$pd")" \
    --argjson aliases "$(jq -c '.aliases // {}' <<<"$pd")" --argjson rc "$(role_classes)" --argjson noeffort "$noeff" \
    --arg role "$role" --arg rclass "$(role_class "$role")" --arg prof "$prof" "$PJQ$CLOUDJQ") || die "could not resolve the profile"
  code=$(jq -r .code <<<"$res")
  if [ "$code" != 0 ]; then echo "qargi: $(jq -r .err <<<"$res")" >&2; exit "$code"; fi
  prof=$(jq -r .out.profile <<<"$res"); base=$(jq -r .out.base <<<"$res"); cls=$(jq -r .out.class <<<"$res")
  if [ "$(jq -r .out.opt_in <<<"$res")" = true ] && [ -z "$OPTIN" ]; then
    echo "qargi: the $prof profile is opt-in (it runs the frontier model on a cloud session): pass --opt-in when you or the person who dispatches the task names it" >&2; exit 2
  fi
  # the model id and the effort come from the provider's adapter (the profile's tier, on the cloud surface); a model with no tier is used as it is
  model=$(jq -r '.out.model_id // empty' <<<"$res"); alias=$(jq -r '.out.model // empty' <<<"$res"); effort=$(jq -r '.out.effort // empty' <<<"$res")
  if [ -n "$(jq -r '.out.tier // empty' <<<"$res")" ] && [ -n "$model" ]; then
    adapter_run "$prov" cloud resolve --check || exit $?
    req=$(jq -nc --arg t "$(jq -r .out.tier <<<"$res")" --arg e "$effort" --arg p "$prof" '{surface: "cloud", tier: $t, effort: (if $e == "" then null else $e end), profile: $p}')
    out=$(adapter_run "$prov" cloud resolve <<<"$req") && rc=0 || rc=$?
    [ "$rc" = 0 ] || die "the adapter of the provider '$prov' could not resolve the $prof profile on the cloud surface (exit $rc): $(jq -r '.error // empty' <<<"$out" 2>/dev/null)"
    model=$(jq -r .model <<<"$out"); effort=$(jq -r '.effort_native // empty' <<<"$out")
  fi
  [ -n "$model" ] || die "the $prof profile resolves to no model on the $prov provider"
  # the base instance takes the model and the effort of the session as overrides: only when the provider is verified to honour them
  row=build; [ "$cls" != read-only ] || row=review
  ov=$(python3 -I "$root/lib/provider.py" effective "$prov" cloud per_dispatch_model_override --project "$proj" 2>/dev/null) || ov=no
  [ "$ov" = yes ] && ovm=yes
  if [ -n "$effort" ]; then
    ov=$(python3 -I "$root/lib/provider.py" effective "$prov" cloud per_dispatch_effort_override --project "$proj" 2>/dev/null) || ov=no
    [ "$ov" = yes ] || ove=no
  fi
  [ "$ovm" = yes ] || why=per_dispatch_model_override
  [ "$ove" = yes ] || why=${why:+$why and }per_dispatch_effort_override
  rec=$(cloud_inst "$proj-$base")
  if [ -n "$rec" ] && [ "$ovm" = yes ] && [ "$ove" = yes ]; then
    inst=$proj-$base; legacy=false
  else
    [ -z "$rec" ] || brec=$proj-$base
    for n in "$proj-$role" "$proj-$row"; do   # the role's own instance, then its class's, as the local order does
      rec=$(cloud_inst "$n"); [ -z "$rec" ] || { inst=$n; break; }
    done
    if [ -z "$inst" ]; then
      if [ -n "$brec" ]; then
        alt=$proj-$role; [ "$role" = "$row" ] || alt="$alt or $proj-$row"
        echo "qargi: the instance $brec is registered, but the provider $prov cannot set the model and effort per dispatch on cloud ($why not verified), and no legacy instance $alt is registered to fall back on. Register one (qargi instances init --location cloud --provision --name $proj-$row), or verify the capability in the provider descriptor" >&2
        exit 2
      fi
      echo "qargi: no cloud instance is registered for the $role role of project $proj: expected $proj-$base (the $cls base) or $proj-$role (qargi instances list; qargi instances init --location cloud ...)" >&2
      exit 1
    fi
    rm=$(jq -r '.agent.model // ""' <<<"$rec")
    if [ "$rm" != "$model" ] && { [ -z "$alias" ] || [ "$rm" != "$alias" ]; }; then
      echo "qargi: the instance $inst runs ${rm:-an unrecorded model} and cannot take another per dispatch ($([ -n "$why" ] && echo "$why not verified for the provider $prov" || echo "the base $proj-$base is not registered")), so it cannot run the $prof profile (model $model). Register the base instance: qargi instances init --location cloud --provision --name $proj-$base, or choose a profile with the model of the instance" >&2
      exit 2
    fi
  fi
  if [ -n "$JSON" ]; then
    jq -n --arg i "$inst" --arg b "$base" --argjson l "$legacy" --arg m "$model" --arg e "$effort" --arg p "$prof" --arg c "$cls" \
      '{instance: $i, base: (if $l then null else $b end), legacy: $l, model: $m, effort: (if $e == "" then null else $e end), profile: $p, class: $c}'
    return 0
  fi
  echo "$inst $model ${effort:-default} $prof"
}

case $verb in
  add) add;;
  list)
    st=$(member_states "$(role_classes)") || exit 1
    jq -r --argjson st "$st" 'to_entries | sort_by(.value.seq // 0)[] | [.key, (.value.abilities | join(",")), (if .value.project then "project " + .value.project else "user" end),
        (.value.model // "-") + "/" + (.value.effort // "default"),
        (.value.file + (if ($st[.key] // []) | length > 0 then " (" + (($st[.key]) | join(", ")) + ")" else "" end))] | @tsv' "$MEMBERS_FILE" \
      | column -t -s "$(printf '\t')"
    [ "$(jq length "$MEMBERS_FILE")" != 0 ] || echo "no members yet: qargi agent add NAME [--abilities build,write,review,test] (--project P | --user)";;
  rename)
    old=${POS[0]:-}; new=${POS[1]:-}
    [ -n "$old" ] && [ -n "$new" ] || die "usage: qargi agent rename OLD NEW [--user]"
    rec=$(jq -ce --arg n "$old" '.[$n]' "$MEMBERS_FILE") || die "no member named $old (qargi agent list)"
    mproj=$(jq -r '.project // ""' <<<"$rec")
    need_place "agent rename" "$mproj"
    prov=$(provider_for "$(project_in_effect "$mproj")" local) || exit $?
    valid_name "$new" "$prov"
    jq -e --arg n "$new" 'has($n)' "$MEMBERS_FILE" >/dev/null && die "a member named $new exists already"
    f=$(jq -r .file <<<"$rec"); ab=$(jq -r '.abilities | join(",")' <<<"$rec")
    # the file carries the name, so the member is rendered again under the new one, into the directory of the old file
    r=$(render_member "$new" "$ab" "$(jq -r --arg d "$(pdesc "$prov" | jq -r '.aliases.balanced // .tiers.balanced')" '.model // $d' <<<"$rec")" "$(jq -r '.effort // ""' <<<"$rec")" "$prov" "$mproj") || exit 1
    oldrel=$(jq -r '.render.path // ""' <<<"$rec"); base=$(dirname "$f")
    [ -z "$oldrel" ] || [ "${f%/"$oldrel"}" = "$f" ] || base=${f%/"$oldrel"}
    # a project's member whose runtime links the project's agents belongs in the member render, wherever the old file was
    [ -z "$mproj" ] || [ "$(link_mode "$r")" = none ] || base=$(agents_dir "$mproj" "$r") || exit 1
    nf=$base/$(jq -r .path <<<"$r")
    [ ! -e "$nf" ] || die "$nf exists already"
    write_member "$r" "$nf"
    [ ! -f "$f" ] || rm -f "$f"
    [ -z "$mproj" ] || [ "$(link_mode "$r")" != none ] || hide_in_git "$(repo_path "$mproj")" "$(jq -r '.agents.project_dir + "/" + .path' <<<"$r")"
    json_update "$MEMBERS_FILE" '.[$new] = (.[$old] | .file = $f | .provider = $v | .surface = "local" | .render = $r) | del(.[$old])' --arg old "$old" --arg new "$new" --arg f "$nf" \
      --arg v "$prov" --argjson r "$(member_record "$r")"
    echo "renamed member $old -> $new ($nf)"
    [ -z "$mproj" ] || link_note "$mproj" "$r" "$nf";;
  refresh)
    n=${POS[0]:-}; [ -n "$n" ] || die "usage: qargi agent refresh NAME [--user]"
    rec=$(jq -ce --arg n "$n" '.[$n]' "$MEMBERS_FILE") || die "no member named $n (qargi agent list)"
    f=$(jq -r .file <<<"$rec"); [ -n "$f" ] || die "member $n records no definition file"
    mproj=$(jq -r '.project // ""' <<<"$rec")
    need_place "agent refresh" "$mproj"
    prov=$(provider_for "$(project_in_effect "$mproj")" local) || exit $?
    r=$(render_member "$n" "$(jq -r '.abilities | join(",")' <<<"$rec")" "$(jq -r --arg d "$(pdesc "$prov" | jq -r '.aliases.balanced // .tiers.balanced')" '.model // $d' <<<"$rec")" \
      "$(jq -r '.effort // ""' <<<"$rec")" "$prov" "$mproj") || exit 1
    # a project's member whose runtime links the project's agents belongs in the member render: a file written to the checkout by an earlier version is moved there
    # (the old file is removed only while it is what qargi wrote)
    if [ -n "$mproj" ] && [ "$(link_mode "$r")" != none ]; then
      nf=$(agents_dir "$mproj" "$r")/$(jq -r .path <<<"$r") || exit 1
      if [ "$nf" != "$f" ]; then
        [ ! -e "$nf" ] && [ ! -L "$nf" ] || die "$nf exists already"
        write_member "$r" "$nf"
        gone="the old file $f is gone"
        if [ -f "$f" ] && [ ! -L "$f" ]; then
          if [ "$(sha256sum < "$f" | cut -d' ' -f1)" = "$(jq -r '.render.hash // ""' <<<"$rec")" ]; then rm -f "$f"
          else gone="the old file $f was edited by hand and is left where it is"; fi
        fi
        json_update "$MEMBERS_FILE" '.[$n] += {file: $f, provider: $v, surface: "local", render: $r}' --arg n "$n" --arg f "$nf" --arg v "$prov" --argjson r "$(member_record "$r")"
        echo "refreshed member $n: now in the member render ($nf); $gone"
        link_note "$mproj" "$r" "$nf"; exit 0
      fi
    fi
    # the file is the render's bytes: written again unless it is already those (a hand-edited file is replaced, and the output says so)
    drift=''; want=$(jq -r '.render.hash // ""' <<<"$rec")
    [ -z "$want" ] || [ ! -f "$f" ] || [ "$(sha256sum < "$f" | cut -d' ' -f1)" = "$want" ] || drift=1
    if [ -f "$f" ] && [ "$(sha256sum < "$f" | cut -d' ' -f1)" = "$(jq -r .sha256 <<<"$r")" ]; then
      json_update "$MEMBERS_FILE" '.[$n] += {provider: $v, surface: "local", render: $r}' --arg n "$n" --arg v "$prov" --argjson r "$(member_record "$r")"
      echo "member $n is current ($f)"; exit 0
    fi
    write_member "$r" "$f"
    json_update "$MEMBERS_FILE" '.[$n] += {provider: $v, surface: "local", render: $r}' --arg n "$n" --arg v "$prov" --argjson r "$(member_record "$r")"
    echo "refreshed member $n ($f); sessions started afterwards use it${drift:+; the edits made to the file by hand are gone}"
    [ -z "$mproj" ] || link_note "$mproj" "$r" "$f";;
  models) models;;
  remove)
    n=${POS[0]:-}; [ -n "$n" ] || die "usage: qargi agent remove NAME"
    rec=$(jq -ce --arg n "$n" '.[$n]' "$MEMBERS_FILE") || die "no member named $n (qargi agent list)"
    f=$(jq -r .file <<<"$rec"); [ ! -f "$f" ] || rm -f "$f"
    json_update "$MEMBERS_FILE" 'del(.[$n])' --arg n "$n"
    echo "removed member $n${f:+ ($f)}"
    case $f in *.agents/*) echo "qargi: note: a worktree that linked it still has a dangling link; qargi project link $(jq -r '.project // ""' <<<"$rec") --resource agents drops it" >&2;; esac;;
  for)
    a=${POS[0]:-}
    [ -n "$a" ] && [ "$a" != lead ] && valid_role "$a" || die "usage: qargi agent for ROLE [--profile P] [--project P] [--json]   (a role of: $DA_ROLES)"
    [ -z "$PROFILE" ] || printf '%s' "$PROFILE" | grep -Eq '^[a-z][a-z0-9-]{0,30}$' || die "--profile: a profile name (lower-case letters, digits and '-', at most 31)"
    [ -n "$PROJ" ] || PROJ=$(python3 -I "$root/lib/help.py" infer)
    case $SURFACE in
      ''|local) resolve_for "$a" "$PROFILE" "$PROJ";;
      cloud) [ -n "$PROJ" ] || PROJ=$(python3 -I "$root/lib/help.py" infer); resolve_cloud "$a" "$PROFILE" "$PROJ";;
      *) die "--surface: local or cloud";;
    esac;;
  *) die "usage: qargi agent add|list|models|rename|refresh|remove|for ...";;
esac
