Cloud session specifics (this is the cloud backend of /dev-task):
- Wait for a task. Do no repository work until a coordinator message gives you
  TASK and DONE.
- Clone the repository named in the task into /workspace with the access
  provided to you, fetch tags, and initialise any submodules the checks need.
  RUN_DIR is /mnt/session/outputs.
- First read the README of the mounted recipes store (under /mnt/memory) and
  load only the recipes the task needs. Add durable how-to facts to recipes/
  only as the contract says.
- Run checks as a non-root user when the repository's tests require it. Start
  long commands detached and poll their log in later calls.
- The coordinator downloads RUN_DIR after you go idle and runs any private-name
  scrub itself, because private patterns are not available here.
- You have no standing permission to push: never run git push, even if the
  access provided to you would allow it.

