"""Authority fixture for injected runner failures (not a production launch path).

These unit cases assume unchanged refs; public Git comparison is exercised by
test_attempt_integration. They still take the real lock and bind pending plans
to the owning process, rather than bypassing lifecycle checks for tests.
"""
import contextlib
import fcntl
import json
import os
import tempfile
import time


@contextlib.contextmanager
def attempt(run):
    import attempts as A
    store = A.Store(run)
    fd = store.open_lock()
    if fd != 7:
        os.dup2(fd, 7)
        os.close(fd)
    fcntl.flock(7, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        store.reconcile()
        gate = store.gate()
        with open(store.path + "/" + gate["baseline"], "rb") as stream:
            refs = stream.read()
        pending = {"pending": store.gate_pending(refs, epoch=int(time.time())), "refs": refs.decode()}
        with tempfile.TemporaryFile() as stream:
            stream.write(json.dumps(pending).encode())
            stream.seek(0)
            os.dup2(stream.fileno(), 8)
            try:
                yield pending
            finally:
                try:
                    os.close(8)
                except OSError:
                    pass  # main consumed the plan descriptor
    finally:
        os.close(7)


def wire(runtime):
    main, run_it = runtime.main, runtime.run_it

    def owned_main(argv):
        with attempt(argv[0]):
            return main(argv)

    def owned_run(plan, run, pending=None):
        if pending is not None:
            return run_it(plan, run, pending)
        with attempt(run) as pending:
            return run_it(plan, run, pending)

    runtime.main, runtime.run_it = owned_main, owned_run
