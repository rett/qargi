# A sample for tests/test_hermetic.sh: what tests/hermetic_lint.py must find. Not run.
import time


def test():
    time.sleep(2)
    t0 = time.time()
    assert time.time() - t0 < 5
