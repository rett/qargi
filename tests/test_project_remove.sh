#!/usr/bin/env bash
# qargi project remove NAME: retire a project behind a plan token. The plan changes nothing; the apply removes the project's stored answers, its members
# (member file, copy of the render, entry in agents.json) and its approved verify.environment declaration, and nothing else: other projects stay byte
# for byte and the repository is not touched. It refuses (exit 2, nothing changed, the one command that clears it) for an unknown project, an open
# feature, an open run, a live marshal lease, an open release cut, a linked work tree, a cloud binding and a registered instance; in a member run and
# under a coordinator label too. A token stays good after a refusal. Hermetic: scratch home, conf and state; a runtime defined by data alone.
# Run: tests/test_project_remove.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi; HANDSEAL=$PWD/tests/handseal.py; SE=$PWD/lib/suite_env.py
trap 'rm -rf "$T" "$HERMETIC"' EXIT
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/s"
cd "$T" || exit 1   # a member run is told by the working directory: the checks below must not depend on where the suite was started

# a runtime defined by data alone: members as TOML files linked one by one into the checkout (entry-symlinks), memory in a directory of the home
LIB=$T/c/packs/providers/fakelink; mkdir -p "$LIB"
jq -n '{schema:2, kind:"provider", provider:"fakelink", family:null, surface:"local",
  models:{pattern:"^fake-[a-z0-9.-]+$", tiers:{"*":{model:"fake-m", alias:null, verified_on:null, source:"test"}}, effort:{low:"l", medium:"m", high:"h", xhigh:null, max:null}},
  resources:{agents:{project_dir:".fake/agents", user_dir:"~/.fake/agents", items:"file-per-item", ext:".toml", link:{project:"entry-symlinks", user:"none"}},
             memory:{user_dir:"~/.fake/mem/{checkout_key}", checkout_key:"sha256-16", link:{user:"dir-symlink"}}},
  agents:{reserved_names:["fake-builtin"]},
  renderers:{agent:{engine:"map", format:"toml", path:"{name}.toml", fields:[
    {from:"name", to:"name", refuse_if_missing:true}, {from:"description", to:"description"},
    {from:"model", to:"model", refuse_if_missing:true}, {from:"effort", to:"effort", resolve:"effort"},
    {from:"tools", to:"tools", tool_map:{shell:"sh", read:"cat", edit:"ed", write:"tee"}}, {from:"class", to:"mode"},
    {from:"body", to:"prompt"}]}},
  dispatch:{mode:"in-session"}, barrier:{kind:"none"}}' > "$LIB/definition.json"
python3 -I "$HANDSEAL" "$LIB"                             # a library pack counts only once sealed

lproj() { # NAME REPO: stored answers of a project on the runtime above
  jq -n --arg p "$1" --arg r "$2" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:$r,long_lived:["master","develop"]},
    roles:{build:{base:"develop",push:{mode:"none"}}},models:{provider:"fakelink"},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/$1.json"
}
for p in alpha beta; do make_repo "$T/r$p"; lproj "$p" "$T/r$p"; done
$DA agent add forge --roles build --project alpha >/dev/null 2>&1 && $DA agent add scribe --roles write --project alpha >/dev/null 2>&1 \
  && $DA agent add smith --roles build --project beta >/dev/null 2>&1 && ok "setup: alpha has two members, beta one" || no "setup: agent add"
AM=$T/s/render/alpha/fakelink.agents; BM=$T/s/render/beta/fakelink.agents
python3 -I "$SE" approved set alpha '{"fds":"ci-like"}' --by test --state "$T/s" >/dev/null
python3 -I "$SE" approved set beta '{"fds":"ci-like"}' --by test --state "$T/s" >/dev/null
[ -f "$AM/forge.toml" ] && [ -f "$T/c/agents/alpha/forge.toml" ] && [ -f "$BM/smith.toml" ] && ok "setup: the members' files and the copies of their renders are there" || no "setup files: $(ls -R "$T/s/render" "$T/c/agents")"

# what must not move: every file of conf and state that is not alpha's (the files that hold both are compared by their beta part), the repositories
beta_part() { jq -S '.projects.beta' "$T/c/agents.json"; jq -S '.projects.beta' "$T/s/verify-env.json"; }
others() { # a fingerprint of everything that is not alpha's and not a plan record or the audit log
  ( cd "$T" && find c s -type f ! -path 'c/projects/alpha.json' ! -path 'c/agents/alpha/*' ! -path 's/render/alpha/*' ! -path 's/plans/*' ! -name audit.log ! -name '*.lock' \
      ! -name agents.json ! -name verify-env.json -print0 | sort -z | xargs -0 sha256sum; beta_part ) | sha256sum
}
alpha_all() { # the whole of alpha: its answers, member files, copies, the two shared files and its repository (refs, HEAD, tree)
  ( cd "$T" && { find c s -type f ! -path 's/plans/*' ! -name audit.log ! -name '*.lock' -print0 | sort -z | xargs -0 sha256sum; }
    git -C "$T/ralpha" for-each-ref; git -C "$T/ralpha" symbolic-ref -q HEAD; git -C "$T/ralpha" status --porcelain
    find "$T/ralpha" -path "$T/ralpha/.git" -prune -o -type f -print0 | sort -z | xargs -0 -r sha256sum; find "$T/ralpha" -path "$T/ralpha/.git" -prune -o -type l -print | sort ) | sha256sum
}
repo_state() { git -C "$1" for-each-ref; git -C "$1" symbolic-ref -q HEAD; git -C "$1" status --porcelain; git -C "$1" worktree list; }
refused() { # NAME... : the last command exited 2 with these words (the refusal code first) on its standard error
  local rc=$1 w; shift
  [ "$rc" = 2 ] || return 1
  for w in "$@"; do grep -qF -- "$w" "$T/e" || { echo "missing '$w' in: $(cat "$T/e")"; return 1; }; done
}
run() { "$@" >"$T/o" 2>"$T/e"; }

# --- the plan: it names what the apply removes and changes nothing
before=$(alpha_all); b_others=$(others); repo0=$(repo_state "$T/ralpha")
run "$DA" project remove alpha; rc=$?
tok0=$(tokof)
{ [ $rc = 0 ] && [ -n "$tok0" ] && grep -q "^remove project alpha" "$T/o" && grep -qF "$T/c/projects/alpha.json" "$T/o" && grep -q "forge (build)" "$T/o" && grep -q "scribe (write)" "$T/o" \
  && grep -qF "$AM/forge.toml" "$T/o" && grep -qF "$T/c/agents/alpha/forge.toml" "$T/o" && grep -q "approved verify.environment declaration" "$T/o" && grep -q "not touched: the repository" "$T/o" \
  && ! grep -qw smith "$T/o" && ! grep -qw beta "$T/o"; } && ok "the plan names the answers, each member with its file and copy, and the approved declaration; it names nothing of another project" || no "plan: rc=$rc $(out)"
[ "$before" = "$(alpha_all)" ] && ok "the plan changes nothing: no file of conf or state, no ref, no file of the repository" || no "the plan changed something"
run "$DA" plan show "$tok0"; grep -q "project remove" "$T/o" && grep -q "^target: alpha answers" "$T/o" && ok "qargi plan show keeps the plan: the verb and the target alpha answers" || no "plan show: $(out)"
run "$DA" project remove alpha --plan "$tok0"; rc=$?
[ $rc = 0 ] && [ "$(tokof)" = "$tok0" ] && [ "$before" = "$(alpha_all)" ] && ok "--plan without --approved is only the plan again (the same token)" || no "plan with --plan: rc=$rc $(out)"
run "$DA" project remove alpha --approved go; rc=$?
{ [ $rc = 1 ] && grep -q "plan-missing" "$T/e" && [ "$before" = "$(alpha_all)" ]; } && ok "--approved without --plan is refused (plan-missing), nothing changed" || no "no plan: rc=$rc $(out)"
run "$DA" project remove alpha --plan 000000000000 --approved go; rc=$?
{ [ $rc = 1 ] && grep -q "plan-stale" "$T/e" && [ "$before" = "$(alpha_all)" ]; } && ok "a wrong token is refused (plan-stale), nothing changed" || no "wrong token: rc=$rc $(out)"
run "$DA" project remove alpha --bogus; rc=$?
{ [ $rc = 2 ] && grep -q "unknown option --bogus" "$T/e"; } && ok "an unknown option is a usage error (exit 2)" || no "bogus option: rc=$rc $(out)"
run "$DA" project remove; rc=$?; { [ $rc = 2 ] && grep -q "which project" "$T/e"; } && ok "no name is a usage error (exit 2): the project is asked for" || no "no name: rc=$rc $(out)"
run "$DA" project remove Bad_Name; rc=$?; [ $rc = 2 ] && ok "a name that is not a project name is a usage error (exit 2)" || no "bad name: rc=$rc $(out)"

# --- an unknown project, for the plan and for an apply
for args in "" "--plan $tok0 --approved go"; do
  # shellcheck disable=SC2086  # the words of args are separate arguments
  run "$DA" project remove nosuch $args; rc=$?
  refused $rc "project-remove-unknown" "no project named nosuch has stored answers" "qargi project list" && ! grep -q "^plan token" "$T/o" && [ "$before" = "$(alpha_all)" ] \
    && ok "an unknown project is refused (project-remove-unknown, exit 2), with no token${args:+ (the apply too)}" || no "unknown ${args:-plan}: rc=$rc $(out)"
done

# --- what holds the project: each refuses with the plan and with the apply, changes nothing, and names the one command that clears it
hold() { # LABEL CODE CLEARS...: both phases refuse with CODE and name every CLEARS word, and nothing changed
  local label=$1 code=$2 w s; shift 2
  for s in plan apply; do
    if [ $s = plan ]; then run "$DA" project remove alpha; else run "$DA" project remove alpha --plan "$tok0" --approved go; fi; rc=$?
    refused $rc "$code" "$@" && ! grep -q "^plan token" "$T/o" && [ "$before" = "$(alpha_all)" ] || { no "$label ($s): rc=$rc $(out)"; return; }
  done
  ok "$label: refused with $code in the plan and in the apply (exit 2), names $*, nothing changed"
}
# an open feature: a branch feature/* of the repository
git -C "$T/ralpha" branch feature/zed develop; before=$(alpha_all)
hold "an open feature" project-remove-feature "open feature(s): zed" "qargi feature finish FEATURE"
run "$DA" project remove alpha; grep -q "^qargi: refused \[project-remove-feature\] project remove .*zed" "$T/e" && grep -q '^qargi-refusal/1 {"code":"project-remove-feature","exit":2,"verb":"project remove","project":"alpha"' "$T/e" \
  && ok "the refusal prints the contract line (code, exit 2, verb, project) and the human line" || no "the feature refusal line: $(cat "$T/e")"
run "$DA" project remove beta; [ $? = 0 ] && ok "another project's removal does not see alpha's feature" || no "beta plan with alpha's feature: $(out)"
git -C "$T/ralpha" branch -D feature/zed >/dev/null; before=$(alpha_all)

# an open run of the lead's registry: not cleaned and not closed; a cleaned run, a closed one and another project's run hold nothing
REG=$T/s/local-runs.jsonl
jq -nc --arg r "$T/runs/qargi.aaa111" '{lifecycle:1,run:$r,slug:"x",ability:"build",base:"develop",project:"alpha",repo:"'"$T"'/ralpha"}' > "$REG"
jq -nc --arg r "$T/runs/qargi.bbb222" '{lifecycle:1,run:$r,slug:"y",ability:"build",base:"develop",project:"beta"}' >> "$REG"
before=$(alpha_all)
hold "an open run" project-remove-run "qargi.aaa111" "qargi local clean RUN"
grep -q "qargi.bbb222" "$T/e" && no "another project's run is named"
jq -c 'if .project == "alpha" then . + {cleaned:"2026-01-01T00:00:00Z"} else . end' "$REG" > "$REG.new" && mv "$REG.new" "$REG"
run "$DA" project remove alpha; [ $? = 0 ] && ok "a cleaned run holds nothing" || no "cleaned run still holds: $(out)"
jq -c 'if .project == "alpha" then del(.cleaned) + {closed:"2026-01-01T00:00:00Z"} else . end' "$REG" > "$REG.new" && mv "$REG.new" "$REG"
run "$DA" project remove alpha; [ $? = 0 ] && ok "a closed run (local close --applied-by-am) holds nothing" || no "closed run still holds: $(out)"
jq -nc --arg r "$T/runs/qargi.ccc333" '{lifecycle:1,run:$r,slug:"z",ability:"build",base:"develop",project:"",repo:"'"$T"'/ralpha"}' >> "$REG"
before=$(alpha_all)
hold "a run of the project's repository (no project recorded)" project-remove-run "qargi.ccc333"
rm -f "$REG"; before=$(alpha_all)

# a live marshal lease: a record of a feature with a lead that renewed it less than the lease length ago; a stale one, a finished one and a record without a lead hold nothing
F=$T/s/features; mkdir -p "$F"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ); old=$(date -u -d '2 hours ago' +%Y-%m-%dT%H:%M:%SZ)
jq -n --arg t "$now" '{feature:"live",project:"alpha",status:"active",lead:{id:"alice",user:"u",host:"h",since:$t},renewed_at:$t}' > "$F/alpha-live.json"
jq -n --arg t "$old" '{feature:"stale",project:"alpha",status:"active",lead:{id:"alice",user:"u",host:"h",since:$t},renewed_at:$t}' > "$F/alpha-stale.json"
jq -n --arg t "$now" '{feature:"done",project:"alpha",status:"finished",lead:{id:"alice",user:"u",host:"h",since:$t},renewed_at:$t}' > "$F/alpha-done.json"
jq -n '{feature:"unled",project:"alpha",status:"unled",lead:null}' > "$F/alpha-unled.json"
jq -n --arg t "$now" '{feature:"theirs",project:"beta",status:"active",lead:{id:"alice",user:"u",host:"h",since:$t},renewed_at:$t}' > "$F/beta-theirs.json"
before=$(alpha_all)
hold "a live marshal lease" project-remove-lease "live" "qargi marshal release FEATURE"
grep -qw "stale\|done\|unled\|theirs" "$T/e" && no "a stale, finished, unled or another project's record is named: $(cat "$T/e")"
rm -f "$F/alpha-live.json"; run "$DA" project remove alpha; [ $? = 0 ] && ok "a stale lease, a finished feature, a record with no lead and another project's lease hold nothing" || no "leases: $(out)"
printf '{"feature":"odd"' > "$F/alpha-odd.json"; before=$(alpha_all)
hold "a marshal record that cannot be read" project-remove-lease "odd"
rm -f "$F/alpha-odd.json"; before=$(alpha_all)
jq -n --arg t "$now" '{feature:"timeless",project:"alpha",status:"active",lead:{id:"alice"},renewed_at:"not a time"}' > "$F/alpha-timeless.json"; before=$(alpha_all)
hold "a lease whose renewal time cannot be read" project-remove-lease "timeless"
rm -f "$F/alpha-timeless.json"; before=$(alpha_all)

# an open release cut: a cut record with no finish step; a finished one and another project's hold nothing
R=$T/s/release; mkdir -p "$R"
jq -n '{schema:1,project:"alpha",version:"9.9.9",steps:["start","push","finish"],done:{start:{at:"2026-01-01T00:00:00Z"}}}' > "$R/alpha-9.9.9.cut.json"
jq -n '{schema:1,project:"alpha",version:"9.9.8",steps:["start","finish"],done:{start:{at:"x"},finish:{at:"y"}}}' > "$R/alpha-9.9.8.cut.json"
jq -n '{schema:1,project:"beta",version:"9.9.7",steps:["start","finish"],done:{start:{at:"x"}}}' > "$R/beta-9.9.7.cut.json"
echo '{}' > "$R/alpha-9.9.9.after.json"
before=$(alpha_all)
hold "an open release cut" project-remove-release "9.9.9" "qargi release finish VERSION"
grep -qw "9.9.8\|9.9.7" "$T/e" && no "a finished cut or another project's cut is named"
jq '.done.finish = {at:"z"}' "$R/alpha-9.9.9.cut.json" > "$R/x" && mv "$R/x" "$R/alpha-9.9.9.cut.json"
run "$DA" project remove alpha; [ $? = 0 ] && ok "a cut that reached finish holds nothing" || no "finished cut still holds: $(out)"
rm -f "$R"/alpha-* "$R"/beta-*; before=$(alpha_all)

# a registered instance: an entry of instances.json named alpha-...; another project's holds nothing
echo '{"alpha-worker":{"location":"cloud"},"beta-worker":{"location":"cloud"},"alphabet-worker":{"location":"cloud"}}' > "$T/c/instances.json"
before=$(alpha_all)
hold "a registered instance" project-remove-instances "alpha-worker" "qargi instances remove INSTANCE"
grep -q "beta-worker\|alphabet" "$T/e" && no "another project's instance is named"
echo '{"beta-worker":{"location":"cloud"},"alphabet-worker":{"location":"cloud"}}' > "$T/c/instances.json"
run "$DA" project remove alpha; [ $? = 0 ] && ok "an instance of another project (also one whose name starts like the project's) holds nothing" || no "other instances hold: $(out)"
echo '{}' > "$T/c/instances.json"; before=$(alpha_all)

# a linked work tree: the checkout and a work tree of the repository; project link records nothing, so the links are what is found
tokplan() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
mkdir -p "$HOME/.qargi/memory/projects/alpha"; echo note > "$HOME/.qargi/memory/projects/alpha/a.md"
(cd "$T/ralpha" && t=$($DA project link alpha | tokplan) && $DA project link alpha --plan "$t" --approved test >/dev/null 2>&1); [ -L "$T/ralpha/.fake/agents/forge.toml" ] && ok "setup: the checkout of alpha is linked" || no "setup link: $(ls -A "$T/ralpha")"
before=$(alpha_all)
hold "a linked checkout" project-remove-linked "$T/ralpha" "qargi project unlink NAME"
(cd "$T/ralpha" && t=$($DA project unlink alpha | tokplan) && $DA project unlink alpha --plan "$t" --approved test >/dev/null 2>&1)
git -C "$T/ralpha" status --porcelain | grep -q . && no "the repository is not clean after the unlink: $(git -C "$T/ralpha" status --porcelain)"
run "$DA" project remove alpha; [ $? = 0 ] && ok "after project unlink nothing holds it" || no "after unlink: $(out)"
git -C "$T/ralpha" worktree add -q -b wt-branch "$T/wt" develop
(cd "$T/wt" && t=$($DA project link alpha --resource agents | tokplan) && $DA project link alpha --resource agents --plan "$t" --approved test >/dev/null 2>&1); [ -L "$T/wt/.fake/agents/forge.toml" ] && ok "setup: a work tree of the repository is linked" || no "setup wt link: $(ls -A "$T/wt")"
before=$(alpha_all)
hold "a linked work tree of the repository" project-remove-linked "$T/wt" "qargi project unlink NAME"
(cd "$T/wt" && t=$($DA project unlink alpha | tokplan) && $DA project unlink alpha --plan "$t" --approved test >/dev/null 2>&1)
git -C "$T/ralpha" worktree remove --force "$T/wt"; git -C "$T/ralpha" branch -D wt-branch >/dev/null
run "$DA" project remove alpha; [ $? = 0 ] && ok "after the work tree is unlinked nothing holds it" || no "after wt unlink: $(out)"
rm -rf "$HOME/.qargi/memory/projects/alpha" "$HOME/.fake"; before=$(alpha_all)

# several holds: the first is the refusal, a note names the rest
git -C "$T/ralpha" branch feature/two develop
jq -nc --arg r "$T/runs/qargi.ddd444" '{lifecycle:1,run:$r,slug:"x",ability:"build",base:"develop",project:"alpha"}' > "$REG"
echo '{"alpha-reviewer":{"location":"cloud"}}' > "$T/c/instances.json"
run "$DA" project remove alpha; rc=$?
{ refused $rc "project-remove-feature" "two" && grep -q "note: also held: run, instances" "$T/e"; } && ok "with several holds the first is the refusal (feature) and a note names the others (run, instances)" || no "several holds: rc=$rc $(out)"
git -C "$T/ralpha" branch -D feature/two >/dev/null; rm -f "$REG"; echo '{}' > "$T/c/instances.json"; before=$(alpha_all)

# what cannot be read holds the project (project-remove-unreadable): a source that is there and fails is never "nothing holds it"; one that is not there holds nothing
unread() { # LABEL WORDS...: both phases refuse with project-remove-unreadable naming every word, no plan token, no "nothing holds it back", nothing changed
  local label=$1 s; shift
  for s in plan apply; do
    if [ $s = plan ]; then run "$DA" project remove alpha; else run "$DA" project remove alpha --plan "$tok0" --approved go; fi; rc=$?
    refused $rc "project-remove-unreadable" "could not be read" "$@" && ! grep -q "^plan token\|nothing holds it back" "$T/o" && [ "$before" = "$(alpha_all)" ] || { no "$label ($s): rc=$rc $(out)"; return; }
  done
  ok "$label: refused with project-remove-unreadable in the plan and in the apply (exit 2), names $*, nothing changed"
}
cp "$T/c/projects/alpha.json" "$T/alpha.json.keep"
printf '{"schema":1,"project":' > "$T/c/projects/alpha.json"; before=$(alpha_all)
unread "stored answers that are not JSON" "$T/c/projects/alpha.json" "qargi project validate alpha"
printf '["not","an","object"]\n' > "$T/c/projects/alpha.json"; before=$(alpha_all)
unread "stored answers that are not an object" "$T/c/projects/alpha.json" "qargi project validate alpha"
cp "$T/alpha.json.keep" "$T/c/projects/alpha.json"
printf '{oops' > "$T/c/instances.json"; before=$(alpha_all)
unread "an instances.json that is not JSON" "$T/c/instances.json" "qargi instances list"
echo '{}' > "$T/c/instances.json"
mkdir "$REG"; before=$(alpha_all)
unread "a registry of runs that cannot be read" "$REG" "qargi local list"
rmdir "$REG"; printf '{"run":"%s","project":"beta"}\nthis is not json\n' "$T/runs/qargi.eee555" > "$REG"; before=$(alpha_all)
unread "a registry line that is not JSON" "1 line(s) of the registry of runs" "$REG"
rm -f "$REG"
mv "$T/s/features" "$T/s/features.keep"; echo x > "$T/s/features"; before=$(alpha_all)
unread "a directory of marshal records that cannot be listed" "$T/s/features" "qargi marshal status --project alpha"
rm -f "$T/s/features"; mv "$T/s/features.keep" "$T/s/features"
mv "$T/s/release" "$T/s/release.keep"; echo x > "$T/s/release"; before=$(alpha_all)
unread "a directory of release cuts that cannot be listed" "$T/s/release" "qargi release status --project alpha"
rm -f "$T/s/release"; mv "$T/s/release.keep" "$T/s/release"; before=$(alpha_all)
# git in the repository fails: a shim that stands for a repository whose refs cannot be read (every other git command is the real one)
REALGIT=$(command -v git); mkdir "$T/shim"
printf '#!/bin/sh\nfor a in "$@"; do case $a in for-each-ref|worktree) exit 128;; esac; done\nexec %s "$@"\n' "$REALGIT" > "$T/shim/git"; chmod +x "$T/shim/git"
PATH=$T/shim:$PATH run "$DA" project remove alpha; rc=$?
refused $rc project-remove-unreadable "could not be read" "for-each-ref" "worktree list" && ! grep -q "^plan token\|nothing holds it back" "$T/o" && [ "$before" = "$(alpha_all)" ] \
  && ok "git that fails in the repository (for-each-ref, worktree list): refused with project-remove-unreadable, no plan" || no "git fails: rc=$rc $(out)"
PATH=$T/shim:$PATH run "$DA" project remove alpha --plan "$tok0" --approved go; rc=$?
refused $rc project-remove-unreadable "for-each-ref" && [ "$before" = "$(alpha_all)" ] && ok "the same in the apply: refused, nothing changed" || no "git fails (apply): rc=$rc $(out)"
# a repository path that is not a repository has no feature and no work tree: nothing there fails to be read
mkdir "$T/notrepo"; jq --arg r "$T/notrepo" '.repo.path = $r' "$T/alpha.json.keep" > "$T/c/projects/alpha.json"
PATH=$T/shim:$PATH run "$DA" project remove alpha; rc=$?
{ [ $rc = 0 ] && ! grep -q "could not be read" "$T/e"; } && ok "a repository path that is not a repository holds nothing (and git is not asked)" || no "not a repository: rc=$rc $(out)"
cp "$T/alpha.json.keep" "$T/c/projects/alpha.json"; before=$(alpha_all)
# a git that takes too long, and a plan of project unlink that cannot run, are things that could not be read too (the clock and the process are replaced inside a copy of the module)
printf '#!/bin/sh\nsleep 5\n' > "$T/shim/git"
python3 -I - "${DA%/bin/qargi}/lib" "$T/ralpha" "$T/shim" <<'PYEOF' && ok "a git that takes too long, or a plan of project unlink that does not run, is reported as unreadable" || no "timeout/OSError unit checks"
import os, subprocess, sys
sys.path.insert(0, sys.argv[1])
import project_remove as PR
repo, shim = sys.argv[2], sys.argv[3]
os.environ["PATH"] = shim + os.pathsep + os.environ["PATH"]
PR.GIT_TIMEOUT = 1
conf = os.path.dirname(repo) + "/c"
bad = PR.Unreadable()
assert PR.instances(conf, "alpha", bad) == [] and not bad.items
open(conf + "/instances.json", "w").write("[1]\n")      # not an object (the help of the command line cannot read it either, so it is tried here)
assert PR.instances(conf, "alpha", bad) == [] and len(bad.items) == 1 and "instances.json" in bad.items[0][0], bad.items
open(conf + "/instances.json", "w").write("{}\n")
bad = PR.Unreadable()
assert PR.features(repo, bad) == [] and len(bad.items) == 1 and "for-each-ref" in bad.items[0][0] and "took more than 1 s" in bad.items[0][0], bad.items
real = subprocess.run
os.environ["PATH"] = os.environ["PATH"].split(os.pathsep, 1)[1]      # the real git again for the work trees
for exc in (subprocess.TimeoutExpired("x", 1), OSError("no interpreter")):
    def boom(*a, **k):
        if a and isinstance(a[0], list) and a[0][0] == "git":
            return real(*a, **k)
        raise exc
    PR.subprocess.run = boom
    bad = PR.Unreadable()
    assert PR.linked("alpha", repo, bad) == [] and len(bad.items) >= 1 and "project unlink" in bad.items[0][0] and "run qargi project unlink alpha inside" in bad.items[0][1], bad.items
PYEOF
rm -rf "$T/shim" "$T/notrepo"; before=$(alpha_all)

# a cloud binding: it is an answer of the project, so it is tried on a project of its own
lproj gamma "$T/ralpha"; jq '.cloud = {profile:"p1", workspace_id:"wrkspc_01ABCDEFGHIJK"}' "$T/c/projects/gamma.json" > "$T/g" && mv "$T/g" "$T/c/projects/gamma.json"
g0=$(sha256sum "$T/c/projects/gamma.json")
run "$DA" project remove gamma; rc=$?
{ refused $rc "project-remove-cloud" "gamma is bound to a cloud workspace" "qargi cloud unset NAME" && [ "$g0" = "$(sha256sum "$T/c/projects/gamma.json")" ]; } && ok "a cloud binding is refused (project-remove-cloud, exit 2), naming qargi cloud unset" || no "cloud: rc=$rc $(out)"
run "$DA" cloud unset gamma; run "$DA" project remove gamma; rc=$?
{ [ $rc = 0 ] && [ -n "$(tokof)" ]; } && ok "after cloud unset the plan is made" || no "after cloud unset: rc=$rc $(out)"
run "$DA" project remove gamma --plan "$(tokof)" --approved "retire gamma"; rc=$?
{ [ $rc = 0 ] && [ ! -e "$T/c/projects/gamma.json" ] && grep -q "removed project gamma: its stored answers and 0 member(s)" "$T/o"; } && ok "a project with no member is removed (members: none in its plan)" || no "gamma apply: rc=$rc $(out)"
jq -e 'select(.verb == "project:remove") | .approved == "retire gamma" and (.detail | startswith("gamma"))' "$T/s/audit.log" >/dev/null && ok "the audit line project:remove carries the owner's words" || no "audit: $(tail -2 "$T/s/audit.log")"

# --- nobody but the lead: a member's run, a member mark, a coordinator label
mkdir -p "$T/memrun"; : > "$T/memrun/ability"; : > "$T/memrun/refs.before"
for how in "run directory" "member mark" "coordinator label"; do
  case $how in
    "run directory") (cd "$T/memrun" && run "$DA" project remove alpha); rc=$?;;
    "member mark") QARGI_MEMBER_RUN=$T/memrun run "$DA" project remove alpha; rc=$?;;
    *) QARGI_ACTOR=lead1:coord:feat:1 run "$DA" project remove alpha; rc=$?;;
  esac
  { [ $rc = 2 ] && [ "$before" = "$(alpha_all)" ] && ! grep -q "^plan token" "$T/o"; } && ok "refused in a $how (exit 2), no plan, nothing changed" || no "$how: rc=$rc $(out)"
done
grep -q "member-lead-verb" "$T/e" || true

# --- the token stays good after all those refusals, and the apply removes alpha and only alpha
run "$DA" project remove alpha; rc=$?
{ [ $rc = 0 ] && [ "$(tokof)" = "$tok0" ]; } && ok "the plan is the same token after every refusal (nothing that holds the project is part of it)" || no "token after refusals: rc=$rc $(tokof) vs $tok0"
alpha_files_before=$(find "$T/c" "$T/s" -type f \( -path "*alpha*" \) | sort)
repo1=$(repo_state "$T/ralpha"); b_own=$(sha256sum "$T/c/projects/beta.json" "$BM/smith.toml" "$T/c/agents/beta/smith.toml"); b_part=$(beta_part); b_others=$(others)
run "$DA" project remove alpha --plan "$tok0" --approved "retire alpha, it is done"; rc=$?
{ [ $rc = 0 ] && grep -q "removed project alpha: its stored answers and 2 member(s)" "$T/o" && grep -q "approved: retire alpha, it is done" "$T/o"; } && ok "the apply with the first token removes the project" || no "apply: rc=$rc $(out)"
{ [ ! -e "$T/c/projects/alpha.json" ] && ! $DA project list | grep -qx alpha && $DA project list | grep -qx beta; } && ok "its stored answers are gone and beta's stay listed" || no "project list: $($DA project list)"
{ [ ! -e "$AM/forge.toml" ] && [ ! -e "$AM/scribe.toml" ] && [ ! -e "$T/c/agents/alpha" ] && jq -e '.projects | has("alpha") | not' "$T/c/agents.json" >/dev/null; } && ok "its members are gone: the files, the copies of the renders and the entries of agents.json" || no "members left: $(find "$T/c/agents" "$AM" 2>&1) $(jq -c .projects "$T/c/agents.json")"
jq -e '.projects | has("alpha") | not' "$T/s/verify-env.json" >/dev/null && ok "the approved verify.environment declaration of alpha is forgotten" || no "verify-env: $(cat "$T/s/verify-env.json")"
[ "$b_own" = "$(sha256sum "$T/c/projects/beta.json" "$BM/smith.toml" "$T/c/agents/beta/smith.toml")" ] && [ "$b_part" = "$(beta_part)" ] && [ "$b_others" = "$(others)" ] \
  && ok "beta is byte for byte as it was: its answers, its member and the copy, its entries in agents.json and verify-env.json, and every other file of conf and state" || no "beta moved"
{ [ "$repo1" = "$(repo_state "$T/ralpha")" ] && [ "$repo0" = "$(repo_state "$T/ralpha")" ] && [ -z "$(git -C "$T/ralpha" status --porcelain)" ] && [ "$(git -C "$T/ralpha" symbolic-ref --short HEAD)" = master ]; } && ok "the repository is as it was: the same refs and HEAD, a clean tree, no worktree added or removed" || no "repository moved: $(repo_state "$T/ralpha")"
[ "$alpha_files_before" != "$(find "$T/c" "$T/s" -type f -path "*alpha*" | sort)" ] && ! find "$T/c" "$T/s" -type f -path "*alpha*" | grep -qE "projects/alpha.json|agents/alpha|render/alpha/fakelink.agents/(forge|scribe)" && ok "no file of alpha's answers, members or copies is left in conf or state" || no "left: $(find "$T/c" "$T/s" -path '*alpha*')"
jq -e 'select(.verb == "project:remove") | select(.detail | startswith("alpha")) | .approved == "retire alpha, it is done" and (.detail | test("2 member"))' "$T/s/audit.log" >/dev/null && ok "the audit line project:remove carries the owner's words" || no "audit: $(tail -2 "$T/s/audit.log")"
run "$DA" project remove alpha --plan "$tok0" --approved again; rc=$?
refused $rc "project-remove-unknown" && ok "applying again is refused: the project is gone (project-remove-unknown)" || no "second apply: rc=$rc $(out)"
run "$DA" agent list --project alpha; ! grep -qw "forge\|scribe" "$T/o" "$T/e" && ok "agent list shows no member of alpha" || no "agent list: $(out)"

# --- a removed project's name can be used again: a project of the same name starts with no approved declaration to be compared with
"$DA" project template alpha | jq --arg r "$T/ralpha" '.repo.url = "https://github.com/example/alpha" | .repo.path = $r | .models.provider = "fakelink" | .verify = {environment: {fds: "close"}}' > "$T/a"
run "$DA" project init alpha --answers "$T/a"; rc=$?
{ [ $rc = 0 ] && ! grep -q "verify-env-change-unapproved" "$T/e"; } && ok "the name is free again: project init stores answers with another verify.environment (no stale approval)" || no "re-create: rc=$rc $(out)"

# --- the neighbours of the verb
run "$DA" help project remove; { [ $? = 0 ] && grep -q "project-remove-feature" "$T/o" && grep -q "qargi project remove acme" "$T/o"; } && ok "help project remove describes the refusals and shows examples" || no "help: $(head -5 "$T/o")"
run "$DA" project; grep -q "remove" "$T/e" "$T/o" && ok "the project usage line lists remove" || no "usage"

exit $fail
