#!/bin/sh
# A stand-in for the go command in the tests (tests/test_tools.py, tests/test_env_apply.py). Offline; nothing is compiled.
#   go install PKG@VERSION   appends "install PKG@VERSION" to go-log next to this script and writes $GOBIN/NAME (a script that prints
#                            VERSION) with a side file naming the package and the version, as a go build would carry them
#   go version -m FILE       prints the mod line of a FILE this script installed; exit 1 for any other file (not a go build)
d=$(dirname "$0")
case "$1" in
  install)
    echo "install $2" >> "$d/go-log"
    pkg=${2%@*}; ver=${2#*@}; name=${pkg##*/}
    [ -n "$GOBIN" ] || { echo "fake go: GOBIN is not set" >&2; exit 1; }
    [ "$ver" != v0.0.0-broken ] || { echo "go: $pkg@$ver: no matching version"; exit 1; }
    mkdir -p "$GOBIN"
    printf '#!/bin/sh\necho %s\n' "$ver" > "$GOBIN/$name"; chmod 755 "$GOBIN/$name"
    printf '%s %s\n' "$pkg" "$ver" > "$GOBIN/.$name.mod"
    ;;
  version)
    [ "$2" = -m ] || { echo "go version go1.22.0 linux/amd64"; exit 0; }
    f=$3; side="$(dirname "$f")/.$(basename "$f").mod"
    [ -f "$side" ] || { echo "go: $f: not a Go executable" >&2; exit 1; }
    read -r pkg ver < "$side"
    printf '%s: go1.22.0\n\tpath\t%s\n\tmod\t%s\t%s\th1:0000\n' "$f" "$pkg" "$pkg" "$ver"
    ;;
  *) echo "fake go: unknown verb $1" >&2; exit 2;;
esac
