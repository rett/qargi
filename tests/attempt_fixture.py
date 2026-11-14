"""Authority fixture for injected runner failures (not a production launch path).

These unit cases assume unchanged refs; public Git comparison is exercised by
test_attempt_integration. They still take the real lock and bind pending plans
to the owning process, rather than bypassing lifecycle checks for tests.
"""
import contextlib
import ctypes
import fcntl
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time


class ForkAfterEnumeration:
    """Fork only after the caller captures /proc, then reap the listed leader.

    All handshakes and child waits are bounded. The fixture temporarily becomes
    a subreaper so cleanup does not depend on the host's orphan reaper.
    """
    CODE = """import os, select, sys
print('ready', flush=True)
if not select.select([0], [], [], 10)[0] or not os.read(0, 1):
    sys.exit(1)
child = os.fork()
if child == 0:
    select.select([int(sys.argv[1])], [], [], 30)
    os._exit(0)
print(child, flush=True)
os._exit(0)
"""

    def __enter__(self):
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.previous = ctypes.c_int()
        if self.libc.prctl(37, ctypes.byref(self.previous), 0, 0, 0) or self.libc.prctl(36, 1, 0, 0, 0):
            raise OSError(ctypes.get_errno(), "subreaper unavailable")
        self.child = None
        low_gate, low_release = os.pipe()
        gate = fcntl.fcntl(low_gate, fcntl.F_DUPFD_CLOEXEC, 20)
        self.release = fcntl.fcntl(low_release, fcntl.F_DUPFD_CLOEXEC, 20)
        os.close(low_gate)
        os.close(low_release)
        try:
            self.leader = subprocess.Popen([sys.executable, '-c', self.CODE, str(gate)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           bufsize=0, start_new_session=True, pass_fds=(gate,))
            self.pgid = self.leader.pid
            # Lifecycle fixtures reserve descriptors 7 and 8; keep handshakes
            # above them even while the caller acquires or releases its lock.
            for name, mode in (('stdin', 'wb'), ('stdout', 'rb')):
                stream = getattr(self.leader, name)
                fd = fcntl.fcntl(stream.fileno(), fcntl.F_DUPFD_CLOEXEC, 20)
                stream.close()
                setattr(self.leader, name, os.fdopen(fd, mode, buffering=0))
            if self.line() != b'ready\n':
                raise AssertionError('leader did not become ready')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise
        finally:
            os.close(gate)

    def line(self):
        data = b''
        deadline = time.monotonic() + 10
        while not data.endswith(b'\n'):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.leader.stdout], [], [], remaining)[0]:
                raise AssertionError('fork handshake timed out')
            part = os.read(self.leader.stdout.fileno(), 1)
            if not part:
                raise AssertionError('fork handshake closed')
            data += part
        return data

    def fork_and_exit(self):
        if self.child is None:
            self.leader.stdin.write(b'x')
            self.child = int(self.line())
            self.leader.wait(timeout=10)

    def __exit__(self, *exc):
        try:
            if hasattr(self, 'leader'):
                try:
                    os.killpg(self.pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.leader.wait(timeout=10)
                deadline = time.monotonic() + 10
                while True:
                    try:
                        pid, _ = os.waitpid(-self.pgid, os.WNOHANG)
                    except ChildProcessError:
                        break
                    if pid == 0:
                        if time.monotonic() >= deadline:
                            raise AssertionError('child reaping timed out')
                        time.sleep(.01)
                self.leader.stdin.close()
                self.leader.stdout.close()
        finally:
            os.close(self.release)
            self.libc.prctl(36, self.previous.value, 0, 0, 0)


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
