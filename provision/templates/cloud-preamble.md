Cloud session specifics (this is the cloud backend of /qargi-task):
- Wait for a task. Do no repository work until a coordinator message gives you
  TASK and DONE.
- If the repository named in the task is already mounted under /workspace (the case
  for private repositories), use it; otherwise clone it into /workspace. Fetch tags and
  initialise any submodules the checks need.
- Your role is {{ROLE}}. Memory stores are under /mnt/memory. Read each store's
  README.md and follow it. Write to a store only as the task block's MEMORY packet
  says; otherwise propose new verified notes in your report and the lead files them.
- Run checks as a non-root user when the repository's tests require it.
- The coordinator downloads OUT after you go idle and runs any private-name
  scrub itself, because private patterns are not available here.

