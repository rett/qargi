#!/bin/sh
# GIT_ASKPASS helper of git_auth_env (lib/lib.sh): prints the token for git. The credential file comes in QARGI_ASKPASS_FILE, so no
# helper file is made per call and nothing is left to clean up; the token is never in an argument.
exec cat -- "$QARGI_ASKPASS_FILE"
