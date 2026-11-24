# shellcheck shell=bash
# Sourced by the shell tests that need a runtime or a family that exists only in a copy of the tool. A runtime is a schema 2 definition
# (one runtime, one surface), so a fake one is built from the shipped claude-code (the local surface) or claude-platform (the cloud
# surface) under another name: it keeps their renderers, resources, barrier and adapter, and the test changes only what it is about with
# a jq filter. Needs jq. SRC is the checkout, TOOL a copy of it (TOOL/lib/providers is written).
#
#   fake_runtime SRC TOOL NAME SURFACE [FILTER]
#       TOOL/lib/providers/NAME.json: the shipped runtime of SURFACE named NAME, in no family, then FILTER (jq, run on the whole
#       definition). The adapter directory is copied under the new name (the adapter finds its definition by its directory name); a
#       FILTER that sets .adapter to null leaves it out, and the adapter_verbs with it.
#   fake_catalog SRC TOOL NAME [FILTER]
#       TOOL/lib/providers/catalogs/NAME.json: the claude catalog under the family name NAME, then FILTER.
#   fake_family SRC TOOL NAME [CATALOG_FILTER [LOCAL_FILTER [CLOUD_FILTER]]]
#       the catalog NAME and two runtimes of family NAME that use it, NAME-local and NAME-cloud; a project names them as
#       {"local": "NAME-local", "cloud": "NAME-cloud"}, or by the family name NAME alone (resolved with a notice).

fake_runtime() {
  local src=$1 tool=$2 name=$3 surface=$4 filter=${5:-.} base
  case $surface in local) base=claude-code;; cloud) base=claude-platform;; *) echo "fake_runtime: surface local or cloud" >&2; return 2;; esac
  jq --arg n "$name" ".provider = \$n | .family = null | ($filter) | if .adapter == null then del(.adapter_verbs) else . end" \
    "$src/lib/providers/$base.json" > "$tool/lib/providers/$name.json.new" || { rm -f "$tool/lib/providers/$name.json.new"; return 1; }
  mv "$tool/lib/providers/$name.json.new" "$tool/lib/providers/$name.json"
  rm -rf "${tool:?}/lib/providers/$name"
  if jq -e '.adapter != null' "$tool/lib/providers/$name.json" >/dev/null; then cp -r "$src/lib/providers/$base" "$tool/lib/providers/$name"; fi
}

fake_catalog() {
  local src=$1 tool=$2 name=$3 filter=${4:-.}
  mkdir -p "$tool/lib/providers/catalogs"
  jq --arg n "$name" ".family = \$n | ($filter)" "$src/lib/providers/catalogs/claude.json" > "$tool/lib/providers/catalogs/$name.json"
}

fake_family() {
  local src=$1 tool=$2 name=$3
  fake_catalog "$src" "$tool" "$name" "${4:-.}" || return 1
  fake_runtime "$src" "$tool" "$name-local" local ".family = \"$name\" | .models.catalog = \"$name\" | (${5:-.})" || return 1
  fake_runtime "$src" "$tool" "$name-cloud" cloud ".family = \"$name\" | .models.catalog = \"$name\" | (${6:-.})"
}

#   fake_command_runtime SRC TOOL NAME [FILTER]
#       TOOL/lib/providers/NAME.json: the shipped codex definition under another name, in no family (its model table is the openai catalog's),
#       a runtime of the local surface that qargi local run starts as a command. Its command is a stub, TOOL/stubs/NAME: it reads the prompt,
#       commits one file in the clone it is given with -C and writes the final message to the file it is given with -o, and nothing else. Its
#       sign-in source is a scratch file, ~/.NAME-members/auth.json of the test's HOME (the test makes it: the directory is not under ~/.codex),
#       and the variable of its run home is NAME_HOME in capitals, the dashes made underscores. FILTER (jq, run on the whole definition)
#       changes what the test is about: the barrier claim (.capabilities.read_only_barrier.value: yes, partial or no), the reads claim
#       (.dispatch.reads), the links, the override claims.
fake_command_runtime() {
  local src=$1 tool=$2 name=$3 filter=${4:-.} var
  var=$(tr 'a-z-' 'A-Z_' <<<"$name")_HOME
  mkdir -p "$tool/lib/providers" "$tool/stubs"
  jq --arg n "$name" --arg stub "$tool/stubs/$name" --arg v "$var" --arg from '~'"/.$name-members/auth.json" \
    ".provider = \$n | .family = null | .dispatch.argv[0] = \$stub | .dispatch.home.env = \$v
     | .dispatch.home.link = [{from: \$from, to: \"auth.json\"}] | .resources.skills.user_dir = \"~/.\(\$n)/skills\"
     | .resources.skills.exclusion.file = \"~/.\(\$n)/config.toml\" | .resources.instructions.user_file = \"~/.\(\$n)/AGENTS.md\" | ($filter)" \
    "$src/lib/providers/codex.json" > "$tool/lib/providers/$name.json.new" || { rm -f "$tool/lib/providers/$name.json.new"; return 1; }
  mv "$tool/lib/providers/$name.json.new" "$tool/lib/providers/$name.json"
  rm -rf "${tool:?}/lib/providers/$name"
  cp -r "$src/lib/providers/codex" "$tool/lib/providers/$name"
  cat > "$tool/stubs/$name" <<'STUB'
#!/usr/bin/env bash
# the command of a fake command runtime: commits one file in the clone (-C) and writes the final message (-o)
clone='' final=''
while [ $# -gt 0 ]; do
  case $1 in -C) clone=$2; shift 2;; -o) final=$2; shift 2;; *) shift;; esac
done
cat > /dev/null
if [ -n "$clone" ]; then
  cd "$clone" || exit 1
  echo stub > stub.txt
  git add stub.txt
  git commit -q -m "Stub: a file"
fi
if [ -n "$final" ]; then echo "stub report" > "$final"; fi
STUB
  chmod +x "$tool/stubs/$name"
}
