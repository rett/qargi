#!/usr/bin/env bash
# Download a cloud session's captured outputs into a fresh directory.
# Everything downloaded is untrusted data: never execute it.
# Usage: collect.sh SID DIR      (DIR must not exist or be empty)
. "$(dirname "$0")/lib.sh"

sid=${1:-}; dir=${2:-}
[ -n "$sid" ] && [ -n "$dir" ] || die "usage: collect.sh SID DIR"
mkdir -p "$dir"
[ -z "$(ls -A "$dir")" ] || die "$dir is not empty; use a fresh directory"

list=
for _ in 1 2 3; do
  list=$(ant beta:files list --scope-id "$sid" --beta "$BETA" --max-items -1 2>/dev/null | jq -c 'select(.id != null)')
  [ -n "$list" ] && break
  sleep 10   # outputs appear a few seconds after the session goes idle
done
[ -n "$list" ] || die "no output files found for $sid"

n=0
while read -r f; do
  id=$(jq -r .id <<<"$f")
  name=$(jq -r '.filename // .name // .id' <<<"$f")
  name=${name#/mnt/session/outputs/}; name=${name#/}
  case $name in *..*) die "refusing unsafe file name: $name";; esac
  mkdir -p "$dir/$(dirname "$name")"
  ant beta:files download --file-id "$id" --output "$dir/$name" >/dev/null 2>&1 || die "download failed: $name"
  n=$((n+1))
done <<<"$list"

[ -f "$dir/manifest.json" ] || die "downloaded $n file(s) but there is no manifest.json; not marked collected"
json_update "$TRK" '.[$s].outputs_collected = true' --arg s "$sid"
echo "collected $n file(s) into $dir"
