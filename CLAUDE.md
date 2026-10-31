# qargi

Dispatches development tasks to members and cloud agents and verifies what they return. See `README.md` and
`CONTRIBUTING.md`.

- Skills (`skills/qargi-*`, installed by `install.sh --user`) and the project's memory and reference stores carry the
  workflow and the rules; load the matching skill instead of working from this file.
- Run the suite isolated, never against live data: `T=$(mktemp -d -p /dev/shm); mkdir $T/h; HOME=$T/h bash tests/run.sh`.
- The manual page is generated: edit `lib/commands.py`, then `python3 lib/help.py man > man/qargi.1`.
