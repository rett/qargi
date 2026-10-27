Cloud session specifics (this is the cloud backend of /dev-task):
- Wait for a task. Do no repository work until a coordinator message gives you
  TASK and DONE.
- Clone the repository named in the task into /workspace with the access
  provided to you, fetch tags, and initialise any submodules the checks need.
  RUN_DIR is /mnt/session/outputs.
- Your role is {{ROLE}}. Under /mnt/memory are the project's memory store
  (read-write) and reference store (read-only). In each, read README.md first, then
  shared/INDEX.md and roles/{{ROLE}}/INDEX.md, and load only the files the task
  needs. Never read or write under another role's folder. Write new verified
  facts only under shared/ (if every role needs them) or roles/{{ROLE}}/ in the
  memory store, as the contract says; the reference store is read-only.
- Run checks as a non-root user when the repository's tests require it. Start
  long commands detached and poll their log in later calls.
- The coordinator downloads RUN_DIR after you go idle and runs any private-name
  scrub itself, because private patterns are not available here.
- You have no standing permission to push: never run git push, even if the
  access provided to you would allow it.

