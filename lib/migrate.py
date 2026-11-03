#!/usr/bin/env python3
"""qargi migrate home: copy the data of the earlier XDG directories to ~/.qargi (see migrate_home.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    if sys.argv[1:2] != ["home"]:
        print("usage: qargi migrate home [--plan TOKEN --approved \"...\"]", file=sys.stderr)
        sys.exit(2)
    import migrate_home
    sys.exit(migrate_home.main(sys.argv[2:]))
