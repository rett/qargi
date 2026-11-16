"""Disposable descriptor/phase fixtures; no provider or live lifecycle state."""
import os
from pathlib import Path
from types import SimpleNamespace

import attempts as A


class DeliveryFixture:
    def __init__(self, root):
        root = Path(root)
        self.run, self.private = root / 'run', root / 'private'
        self.private.mkdir(mode=0o700)
        self.parent = self.run / 'home/.fake'
        self.parent.mkdir(parents=True, mode=0o700)
        self.delivery = self.parent / 'skills'
        self.record = self.private / 'skills-delivery.json'
        self.dispatch = dict(member=None, runner=dict(pid=os.getpid(), token=A.process(os.getpid())['token']), ended=None)
        self.store = SimpleNamespace(run=str(self.run), path=str(self.private),
            require_lock=lambda: None,
            show=lambda: dict(prepared=dict(identity='a' * 32), attempts=[dict(dispatch=self.dispatch)]),
            _owned_dispatch=lambda record: record['attempts'][-1]['dispatch'])

    def existing(self):
        self.delivery.mkdir(mode=0o700)
        (self.delivery / 'original').write_text('owned')
        self.record.write_bytes(A.encode(dict(path=str(self.delivery), parent=self.identity(self.parent),
            private=self.identity(self.private), identity='a' * 32, phase='published', inode=self.identity(self.delivery))))
        self.record.chmod(0o600)

    @staticmethod
    def identity(path):
        st = path.stat()
        return [st.st_dev, st.st_ino]

    def swap_root(self):
        self.delivery.rename(self.parent / 'owned-moved')
        self.delivery.mkdir(mode=0o700)
        (self.delivery / 'sentinel').write_text('foreign')

    def swap_parent(self):
        self.parent.rename(self.parent.with_name('parent-moved'))
        self.parent.mkdir(mode=0o700)
        self.delivery.mkdir(mode=0o700)
        (self.delivery / 'sentinel').write_text('foreign')
