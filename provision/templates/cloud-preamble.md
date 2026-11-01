Cloud session specifics (this is the cloud backend of /qargi-task):
- Wait for a task. Do no repository work until a coordinator message gives you
  TASK and DONE.
- If the repository named in the task is already mounted under /workspace (the case
  for private repositories), use it; otherwise clone it into /workspace. Fetch tags and
  initialise any submodules the checks need. RUN_DIR is /mnt/session/outputs.
- Your role is {{ROLE}}. Memory stores are under /mnt/memory: the memory store is
  read-write, the reference store read-only. Read each store's README.md and follow
  it. Write new verified facts only to the memory store under roles/{{ROLE}}/. shared/ is curated: propose a shared note in your report, never write it.
- Run checks as a non-root user when the repository's tests require it. Start
  long commands detached and poll their log in later calls.
- The coordinator downloads RUN_DIR after you go idle and runs any private-name
  scrub itself, because private patterns are not available here.
- You have no standing permission to push: never run git push, even if the
  access provided to you would allow it.

