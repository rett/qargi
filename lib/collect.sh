#!/usr/bin/env bash
# Download a cloud session's captured outputs into a fresh directory.
# Everything downloaded is untrusted data: never execute it. The file listing
# carries base names only, so the result is a flat directory (patches, manifest.json, log.txt);
# a team's role-prefixed files are split into one directory per member.
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

# a listed name may carry the directory the session writes to; that is the cloud runtime's to say (notes of its definition), and the project is the
# one in the name of the session's instance
inst=$(jq -r --arg s "$sid" '.[$s].instance // empty' "$TRK" 2>/dev/null || true)
outd=''
[ -z "$inst" ] || outd=$(cloud_note "${inst%%-*}" output-dir 2>/dev/null) || outd=''
outd=${outd%/}

n=0
while read -r f; do
  id=$(jq -r .id <<<"$f")
  name=$(jq -r '.filename // .name // .id' <<<"$f")
  [ -z "$outd" ] || name=${name#"$outd"/}
  case $name in /*) name=${name##*/};; esac   # an absolute name that is not under the session's output directory: its base name only
  case $name in *..*) die "refusing unsafe file name: $name";; esac
  mkdir -p "$dir/$(dirname "$name")"
  [ ! -e "$dir/$name" ] || die "two output files share the name $name; the file listing carries base names only"
  # </dev/null: ant treats a piped stdin as a request body and would eat the rest of the list
  ant beta:files download --file-id "$id" --output "$dir/$name" </dev/null >/dev/null 2>&1 || die "download failed: $name"
  n=$((n+1))
done <<<"$list"

# A team's members share one outputs directory and the listing carries base names only, so each
# member prefixes its files with its role (build--manifest.json). Split them back into one
# directory per member, patches under patches/.
for f in "$dir"/*--*; do
  [ -f "$f" ] || continue
  b=$(basename "$f"); r=${b%%--*}; rest=${b#*--}
  printf '%s' "$r" | grep -Eq '^[a-z]+$' || continue
  case $rest in */*|'') continue;; esac
  sub=$dir/$r
  case $rest in [0-9][0-9][0-9][0-9]-*.patch) sub=$dir/$r/patches;; esac
  mkdir -p "$sub"; mv "$f" "$sub/$rest"
done
if [ -f "$dir/manifest.json" ]; then :
elif ls "$dir"/*/manifest.json >/dev/null 2>&1 || [ -f "$dir/lead/team.json" ]; then echo "team outputs: $(cd "$dir" && ls -d */ | tr -d / | tr '\n' ' ')"
else die "downloaded $n file(s) but there is no manifest.json; not marked collected"
fi
json_update "$TRK" '.[$s].outputs_collected = true' --arg s "$sid"
python3 -I "$(dirname "$(readlink -f "$0")")/noticed.py" ingest "$sid" "$dir" || echo "noticed: could not record the manifest's notes" >&2
echo "collected $n file(s) into $dir"
