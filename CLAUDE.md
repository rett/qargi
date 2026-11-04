# qargi

Dispatches development tasks to members and cloud agents and verifies what they return. See `README.md` and
`CONTRIBUTING.md`.

- Rules, specs and design live in this repo (`README.md`, `CONTRIBUTING.md`); memory stores hold working notes only and
  never override the repo.
- The workflow comes from the skills (`skills/qargi-*`, installed by `install.sh --user`); load the matching skill instead
  of working from this file.
- Run the suite isolated, never against live data: `T=$(mktemp -d -p /dev/shm); mkdir $T/h; HOME=$T/h bash tests/run.sh`.
- The manual page is generated: edit `lib/commands.py`, then `python3 lib/help.py man --keep-date man/qargi.1 > man/qargi.1.new && mv man/qargi.1.new man/qargi.1` (a plain `> man/qargi.1` empties the file before the date in it is read).
