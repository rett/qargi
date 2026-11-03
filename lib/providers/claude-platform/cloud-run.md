# In a cloud run
OUT is /mnt/session/outputs.
There is no GIT wrapper: run git directly in the repository clone under /workspace/<repo> (your CLONE);
still use no ssh or gh.
Start a long command detached (the one allowed form of a trailing `&`) and poll its log in later calls:
`(nohup bash -c '<cmd> </dev/null; echo EXIT=$?' > out 2>&1 &)`
