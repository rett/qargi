# bash completion for qargi. Install: qargi's install.sh --user does it, or
#   source /path/to/qargi/completions/qargi.bash
# The candidates come from `qargi __complete`, which reads the same description as the help and the
# man page, and offers your real projects, instances, teams, sessions and packs.
_qargi() {
  local cur out
  COMPREPLY=()
  cur=${COMP_WORDS[COMP_CWORD]}
  out=$(qargi __complete "${COMP_WORDS[@]:1:COMP_CWORD}" 2>/dev/null) || return 0
  case $out in
    @file*) compopt -o filenames 2>/dev/null; mapfile -t COMPREPLY < <(compgen -f -- "$cur"); return 0;;
    @dir*)  compopt -o filenames 2>/dev/null; mapfile -t COMPREPLY < <(compgen -d -- "$cur"); return 0;;
  esac
  mapfile -t COMPREPLY < <(compgen -W "$out" -- "$cur")
}
complete -F _qargi qargi
