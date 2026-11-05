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
