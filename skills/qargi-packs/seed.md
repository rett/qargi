Load when seeding the baseline packs.

# Baseline packs

qargi ships skills in `packs/` (listed in `packs/baseline.json`), each declared `compatible_providers: ["any"]`. `qargi packs seed [--install] [--plan TOKEN --approved "..."]` stores them in the library. Without `--approved` it prints one line per shipped pack and a plan token:

- `add skill N (content H)`: the library has no pack of that name; it is stored.
- `current skill N`: the library copy is the shipped one.
- `update skill N (content OLD -> H; links: ...)`: an untouched shipped copy is replaced by the newer text.
- `kept skill N: ...`: not touched, either edited in your library (changed or not yet sealed) or the name belongs to a pack you created or imported.

With nothing to add or update it prints `nothing to seed` and no token. Show the person the plan and wait for their go-ahead, as for any change to a skill. Seeding never links: a pack reaches nobody until you `link` it, for example `qargi skill link NAME --scope project --project P`. `--install` only adds missing packs, needs no token, never updates and notes when a newer shipped version exists (this is what `install.sh --user` runs).

After an update of a linked pack, seed prints the follow-ups: `qargi packs apply --target RUNTIME P` for each project the links reach and `qargi packs apply INSTANCE` for cloud agents. To take the shipped version of an edited pack again: unlink it, remove it (the `remove` verb of `skill`), seed.
