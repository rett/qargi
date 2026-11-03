#!/usr/bin/env python3
"""Where qargi keeps its per-user data: the one place the Python scripts ask. lib/lib.sh does the same for the shell
scripts (DA_CONF, DA_STATE); keep the two in step.

  configuration   QARGI_CONF, else <root>/config      (instances, projects, packs, credentials)
  state           QARGI_STATE, else <root>/state      (sessions, audit.log, runs, backups)
  root            QARGI_HOME, else <tool root>/.qargi in a dev run (below), else ~/.qargi

QARGI_CONF and QARGI_STATE win (tests use them); QARGI_HOME replaces the root. XDG_CONFIG_HOME and XDG_STATE_HOME are
not used for qargi's own data (the ant CLI keeps its login under the former). They only help to find the earlier
layout, ${XDG_CONFIG_HOME:-~/.config}/qargi and ${XDG_STATE_HOME:-~/.local/state}/qargi, which `qargi migrate home`
copies from.

Installed and dev runs: `install.sh --user` records the tool root it installed in <live config>/install.json. A checkout
whose real path differs from that record, run without QARGI_HOME, QARGI_CONF or QARGI_STATE, is a dev run: it keeps its
data in <tool root>/.qargi (git-ignored), so a branch checkout never touches live data. With no record, or the same
tool root, the run is the installed one and uses ~/.qargi. The "live" locations (live_root, live_conf) are the ones an
installed run uses; the record is read from there, and `migrate home` uses them too.
Importing this module never creates anything.

  paths.py banner    in a dev run print the banner to stderr, else nothing; exit 0 (bin/qargi runs it before every command
                     except help, version, __complete, __guard and the run-event hooks)"""
import json, os, sys


def tool_root():
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def explicit():
    """True when the person named a location, so there is no default to choose between."""
    return any(os.environ.get(k) for k in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME"))


def live_root():
    return os.environ.get("QARGI_HOME") or os.path.join(os.path.expanduser("~"), ".qargi")


def live_conf():
    return os.environ.get("QARGI_CONF") or os.path.join(live_root(), "config")


def installed_tool_root():
    """The tool root install.sh recorded, or None (no record, or one that cannot be read)."""
    try:
        with open(os.path.join(live_conf(), "install.json")) as f:
            t = json.load(f).get("tool_root")
    except (OSError, ValueError, AttributeError):
        return None
    return os.path.realpath(t) if isinstance(t, str) and t else None


def dev_run():
    if explicit():
        return False
    rec = installed_tool_root()
    return rec is not None and rec != tool_root()


def root():
    if os.environ.get("QARGI_HOME"):
        return os.environ["QARGI_HOME"]
    return os.path.join(tool_root(), ".qargi") if dev_run() else live_root()


def conf():
    return os.environ.get("QARGI_CONF") or os.path.join(root(), "config")


def state():
    return os.environ.get("QARGI_STATE") or os.path.join(root(), "state")


def legacy_conf():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "qargi")


def legacy_state():
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state"), "qargi")


def banner():
    if not dev_run():
        return ""
    return "dev run from %s; data in %s (QARGI_HOME=~/.qargi uses live data)" % (tool_root(), os.path.join(tool_root(), ".qargi"))


if __name__ == "__main__":
    if sys.argv[1:] == ["banner"]:
        if banner():
            print("qargi: " + banner(), file=sys.stderr)
        sys.exit(0)
    print("usage: paths.py banner", file=sys.stderr)
    sys.exit(2)
