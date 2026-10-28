# fish completion for qargi. Install: install.sh --user puts this file in ~/.config/fish/completions.
# The candidates come from `qargi __complete`, the same description that drives the help and the man page.
function __qargi_complete
    set -l tokens (commandline -opc)
    set -l cur (commandline -ct)
    set -l out (qargi __complete --described $tokens[2..-1] "$cur" 2>/dev/null)
    switch "$out[1]"
        case '@file'
            __fish_complete_path "$cur"
        case '@dir'
            __fish_complete_directories "$cur"
        case '*'
            printf '%s\n' $out
    end
end

complete -c qargi -f -a '(__qargi_complete)'
