# bash completion for qargi. Install: qargi's install.sh --user does it, or
#   source /path/to/qargi/completions/qargi.bash
# The candidates come from `qargi __complete`, which reads the same description as the help and the
# man page, and offers your real projects, instances, teams, sessions (only the ones the verb can act on),
# packs, stores, branches, project answers and the values they take.
_qargi() {
  local cur prefix='' out
  local -a words
  COMPREPLY=()
  cur=${COMP_WORDS[COMP_CWORD]}
  words=("${COMP_WORDS[@]:1:COMP_CWORD}")
  # --option=value: bash splits the word at '=', so put it back together and take the option off the candidates again
  if [[ $cur == = && $COMP_CWORD -ge 2 ]]; then
    prefix=${COMP_WORDS[COMP_CWORD-1]}=; cur=''
    words=("${COMP_WORDS[@]:1:COMP_CWORD-2}" "$prefix")
  elif [[ $COMP_CWORD -ge 3 && ${COMP_WORDS[COMP_CWORD-1]} == = ]]; then
    prefix=${COMP_WORDS[COMP_CWORD-2]}=
    words=("${COMP_WORDS[@]:1:COMP_CWORD-3}" "$prefix$cur")
  fi
  out=$(qargi __complete "${words[@]}" 2>/dev/null) || return 0
  case $out in
    @file*) compopt -o filenames 2>/dev/null; mapfile -t COMPREPLY < <(compgen -f -- "$cur"); return 0;;
    @dir*)  compopt -o filenames 2>/dev/null; mapfile -t COMPREPLY < <(compgen -d -- "$cur"); return 0;;
  esac
  mapfile -t COMPREPLY < <(compgen -W "$out" -- "$prefix$cur")
  [[ -z $prefix ]] || COMPREPLY=("${COMPREPLY[@]#"$prefix"}")
}
complete -F _qargi qargi
