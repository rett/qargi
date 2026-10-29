# Write rules

Rules for documentation work. Replace each `<...>` with the project's own value and
tag each entry with its source; an entry without a source is not trusted.

Kind: rule
Applies to: <project and ref range, or "any">
Sources: <list the project files and the maintainer's instructions this was written from>

## Contents

### Accuracy
- Never invent commands, flags, output or behaviour. Every command is traceable to the
  project's documentation, manual or code. (source: <where>)
- Never fabricate sample output: quote what the sources show, or describe it in words.
- If a detail cannot be verified, leave it out.

### Writing to the project
- The project's files are read-only for this role except through `<the documentation branch
  and push policy from the profile>`. Publishing anywhere else is a write: get
  approval first. (source: <where>)
- Deliver in the formats `<formats>`; final files go to `<output folder>`, nothing else
  in the outputs root.

### Audience and scope
- Write for `<audience>`. Respect explicit exclusions the maintainer gave. (source: <where>)

### Memory
- Resolve conflicts yourself: a new explicit instruction beats memory, the project
  beats memory on behaviour, the published page beats older history. Record the
  decision in the file it belongs to. (source: <where>)
