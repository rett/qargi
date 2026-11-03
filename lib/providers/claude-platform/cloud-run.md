# In a cloud run
OUT is /mnt/session/outputs, the directory your task block calls RUN_DIR.
There is no GIT wrapper: run git directly in the repository clone under /workspace/<repo> (your CLONE),
and still use no ssh or gh and never push, tag or merge.
Start a long command detached and poll its log in later calls, never with `pgrep -f`:
`(nohup bash -c '<cmd> </dev/null; echo EXIT=$?' > out 2>&1 &)`
