#!/usr/bin/env python3
"""pty_run.py CMD [ARG...]: run CMD with a pseudo-terminal as its stdin, stdout and stderr (so `[ -t 0 ]` holds in it), copy what it prints
to this program's stdout, and exit with its status. Nothing is ever typed to it: a test uses this to stand in for a person's terminal
without a real passphrase prompt. The tests of `qargi release sign` use it, because that verb refuses a stdin that is no terminal."""
import os, pty, sys


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execvp(argv[0], argv)
        except OSError as e:
            print("pty_run: %s: %s" % (argv[0], e), file=sys.stderr)
            os._exit(127)
    chunks = []
    while True:
        try:
            data = os.read(fd, 65536)
        except OSError:               # EIO: the child closed its side
            break
        if not data:
            break
        chunks.append(data)
    _, status = os.waitpid(pid, 0)
    sys.stdout.write(b"".join(chunks).decode("utf-8", "replace").replace("\r\n", "\n"))
    return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
