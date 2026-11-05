# A sample for tests/test_hermetic.sh: what tests/hermetic_lint.py must not find. Not run.
import hermetic
import time


def test():
    for _ in range(50):
        time.sleep(0.1)
