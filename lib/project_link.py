#!/usr/bin/env python3
"""Where the members of a project are rendered for a runtime, for lib/agent.sh.

  project_link.py members-dir PROJECT RUNTIME     print state/render/PROJECT/RUNTIME.agents

A runtime whose definition links the project's agents (resources.agents.link.project is not none) has the members of a project rendered into
this directory, under ~/.qargi, and linked into the checkout from there (qargi project link). It lies beside the runtime's render, not in it:
a packs render replaces its directory whole, and the members must survive that. The directory name has a dot, which no runtime name has.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import packs_render  # noqa: E402  (render_dir)
import paths  # noqa: E402


def members_dir(state, project, runtime):
    """Where the members of a project are rendered for a runtime: state/render/PROJECT/RUNTIME.agents. The one place that says so."""
    return packs_render.render_dir(state, project, runtime) + ".agents"


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "members-dir":
        print(members_dir(paths.state(), sys.argv[2], sys.argv[3]))
        return
    print("qargi: usage: project_link.py members-dir PROJECT RUNTIME", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
