# Docs workflow

Sources: <list the project files and the maintainer's instructions this was written from>

## Contents

### Producing a document
1. Load memory: the README, then the indexes, then the files the task needs; check
   `roles/docs/project/open-items.md`.
2. Read the project's sources for the topic (`workflow/source-map.md`); check every
   command you plan to use.
3. Outline by the reader's task, not by command. Follow `writing/conventions.md`.
4. Write or edit on the docs branch from the profile; one change per branch.
5. Run the profile's checks (command check, link check, build) until they report no
   problems; render the delivery formats and look at the result.
6. Log the document in `roles/docs/project/history.md`; record new learnings in
   their subject file.
7. Summarise: the files, the sections, the choices you made, anything you could not
   verify.

### Definition of done (state it as a checklist in the report)
- [ ] The page has one document type and stays in it; reference facts are cited, not copied.
- [ ] Every command, flag and output is traced to a source; `Sources:` lines are given.
- [ ] The profile's checks report no problems.
- [ ] Example values come from `shared/conventions/examples.md`.
- [ ] Commands and output are in separate blocks; placeholders are `<name>`.
- [ ] The rendered formats were looked at.
- [ ] The page names the release or version it was checked against.
- [ ] New or removed pages: navigation, index and cross-links updated.
- [ ] History is logged; no generated files are stored in memory.

### Per-release sync
After each release: fetch the new tag, diff the commands and options against the
previous release, fix every page for each operator-visible change (renamed or removed
commands block other work), update the "checked against" lines and the release notes
page, run the checks, and update `knowledge/facts.md`.

### Reviewing a document written elsewhere
Check every command and claim against the source; look for wrong audience, missing
safety warnings and vendor differences. Align it with the collection (style, example
names). Report grouped as accuracy, safety, additions and consistency.
