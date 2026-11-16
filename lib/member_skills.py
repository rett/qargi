#!/usr/bin/env python3
"""Opt-in managed member skills. Canonical links select; private lifecycle bytes deliver.

Limits: 64 skills, 4096 tree entries, 2,000,000 bytes per file, 16 MiB
aggregate (including records), 1 MiB manifest, 16 path components/512 bytes.
The canonical review's tighter per-pack limits still apply. Approval hashes
retain their existing meaning; full SHA256s and normalized modes protect copies.
No provider name, rendered union, RUN mirror or pack prose grants authority.
"""
import hashlib
import contextlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import packs_check as C
import packs_compat
import packs_mcp as M
import packs_render
import paths
import provider as P
import role as R
import linker

MAX_SKILLS = 64
MAX_ENTRIES = 4096
MAX_FILE = 2_000_000
MAX_TOTAL = 16 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024


class Invalid(ValueError):
    """Refuse without changing authority; re-prepare after drift."""


def need(ok, message):
    if not ok:
        raise Invalid("member skills: " + message)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(name):
    return (isinstance(name, str) and len(name.encode('utf-8')) <= 512
            and len(name.split('/')) <= 16 and all(
                re.fullmatch(r'[A-Za-z0-9_.-]+', p) and p not in ('.', '..') for p in name.split('/')))


def enabled(project, conf=None):
    doc = P.project_answers(project, conf or paths.conf())
    need(isinstance(doc, dict), "project answers unavailable")
    packs = doc.get('packs')
    if packs is None:
        packs = {}
    need(isinstance(packs, dict), "packs must be an object")
    value = packs.get('member_skills', False)
    need(type(value) is bool, "packs.member_skills must be boolean")
    return value


def destination(comp):
    disp = comp['definition'].get('dispatch') or {}
    need(disp.get('mode') == 'command', "opt-in requires command dispatch; in-session delivery is unsupported")
    home = disp.get('home')
    need(isinstance(home, dict) and 'skills_dir' in home,
         "command runtime needs dispatch.home.skills_dir")
    bad = P.home_problems(home, disp.get('env_pass', [])) + P.run_config_problems(
        disp, comp['definition'].get('resources'))
    need(not bad, '; '.join(bad))
    return 'home/' + home['dir'] + '/' + home['skills_dir']


def collect(root, budget=None, prefix=''):
    """Bounded nofollow reads; reject hardlinks/specials before opening a body."""
    import attempts as A
    fd = A.directory(os.path.abspath(root), private_leaf=False)
    files, dirs = {}, []
    # The caller shares [entries, bytes] across included packs. Check the
    # advertised size before reading, and bound reads by the remaining bytes.
    budget = [0, 0] if budget is None else budget

    def walk(dfd, relative_prefix=''):
        names = os.listdir(dfd)
        need(len(names) <= MAX_ENTRIES, "too many entries")
        for name in sorted(names):
            rel = relative_prefix + name
            budget[0] += 1
            need(budget[0] <= MAX_ENTRIES, 'too many entries')
            need(safe_path(prefix + rel), 'unsafe path: ' + (prefix + rel)[:512])
            st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            need(st.st_uid == os.geteuid(), "source is not owner-owned")
            if stat.S_ISDIR(st.st_mode):
                dirs.append(rel)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dfd)
                try:
                    need((st.st_dev, st.st_ino) == (os.fstat(child).st_dev, os.fstat(child).st_ino), "directory changed")
                    walk(child, rel + '/')
                finally:
                    os.close(child)
            else:
                need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size <= MAX_FILE,
                     "symlink, hardlink, special or oversized file: " + rel)
                need(budget[1] + st.st_size <= MAX_TOTAL, 'aggregate content exceeds 16 MiB')
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
                try:
                    now = os.fstat(child)
                    need((now.st_dev, now.st_ino) == (st.st_dev, st.st_ino), "file changed")
                    data = b''
                    limit = min(MAX_FILE, MAX_TOTAL - budget[1])
                    while len(data) <= limit:
                        chunk = os.read(child, min(65536, limit + 1 - len(data)))
                        if not chunk:
                            break
                        data += chunk
                    need(len(data) <= limit and stat.S_ISREG(now.st_mode) and now.st_nlink == 1,
                         'file changed or exceeds bound')
                    after = os.fstat(child)
                    need((after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                         (now.st_size, now.st_mtime_ns, now.st_ctime_ns), "file changed while reading")
                finally:
                    os.close(child)
                budget[1] += len(data)
                files[rel] = (data, 0o700 if st.st_mode & 0o111 else 0o600)
    try:
        walk(fd)
    finally:
        os.close(fd)
    return files, dirs


def descriptions(files):
    return [dict(path=p, sha256=sha(data), size=len(data), mode=mode)
            for p, (data, mode) in sorted(files.items())]


def selection(project, role, runtime, comp=None):
    """Read only. Full file identity is compared to the copy that passed review.

    Compatibility uses the same declaration/evaluation rules as C.usable, on
    bounded nofollow metadata. Tool packs stay with existing MCP policy.
    """
    conf = paths.conf()
    comp = comp or P.compose(runtime, 'local', project)
    dest = destination(comp)
    entries = M.effective(conf, project, role)
    need(len(entries) <= MAX_ENTRIES, "too many links")
    links_path = os.path.join(conf, 'packs', 'links.json')
    links = M._load(links_path, 'pack links')['links'] if os.path.exists(links_path) else []
    relevant = [x for x in links if M.reaches(x, project, role)]
    answers = P.project_answers(project, conf)
    off = ((answers.get('roles') or {}).get(role) or {}).get('packs_off', [])
    packs, bodies, dirs, skipped = [], {}, [], []
    skills = []
    for entry in entries:
        kind, sep, name = entry.partition(':')
        need(sep and kind in ('skill', 'tool') and M.PACK_NAME.fullmatch(name), "unsupported linked kind/name")
        if kind == 'tool':
            continue
        skills.append(name)
    need(len(skills) <= MAX_SKILLS, 'too many skills')
    budget = [0, 0]
    import attempts as A
    for name in skills:
        root = os.path.join(conf, 'packs', 'skills', name)
        fd = A.directory(root, private_leaf=False)
        try:
            metadata = A.read_at(fd, '.pack.json', MAX_FILE)
        finally:
            os.close(fd)
        try:
            rec = json.loads(metadata)
        except (ValueError, UnicodeError) as e:
            raise Invalid('member skills: malformed pack record') from e
        need(isinstance(rec, dict), 'malformed pack record')
        declared = rec.get('compatible_providers')
        need(packs_compat.problem(declared) is None, "invalid compatibility: " + name)
        ok, reason = packs_compat.evaluate(declared, answers, project, ['local'])
        if not ok:
            skipped.append(dict(name=name, reason=reason.strip()))
            packs.append(dict(name=name, approved=None, files=[], dirs=[], included=False, compatibility=declared))
            continue
        approval = rec.get('sha256')
        need(isinstance(approval, str) and re.fullmatch(r'[0-9a-f]{16}', approval), "missing/empty content approval: " + name)
        budget[0] += 1  # The pack directory is part of the cross-pack inventory.
        need(budget[0] <= MAX_ENTRIES, 'too many entries')
        files, subdirs = collect(root, budget, name + '/')
        need('.pack.json' in files and 'SKILL.md' in files, "missing record or SKILL.md: " + name)
        need(files['.pack.json'][0] == metadata, 'compatibility metadata changed: ' + name)
        packs.append(dict(name=name, approved=approval, files=descriptions(files), dirs=subdirs, included=True, compatibility=declared))
        for p, value in files.items():
            bodies[name + '/' + p] = value
        dirs.extend([name] + [name + '/' + d for d in subdirs])
    home = comp['definition']['dispatch']['home']
    facts = dict(project=project, role=role, runtime=runtime, composition=sha(encode(comp)),
                 delivery_root='home/' + home['dir'] + '/' + home['skills_dir'].split('/')[0],
                 destination=dest, links=sorted(relevant, key=lambda x: encode(x)), exclusions=off,
                 packs=packs, skipped=skipped)
    need(len(encode(facts)) <= MAX_MANIFEST, "manifest exceeds 1 MiB")
    return facts, bodies, dirs


def put_tree(root, files, dirs):
    """Only inside an exclusively created owned tree."""
    import attempts as A
    top = os.dup(root) if type(root) is int else A.directory(root)

    def parent(path):
        need(safe_path(path), 'unsafe copy path')
        fd = os.dup(top)
        try:
            for component in path.split('/')[:-1]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            return os.dup(fd)
        finally:
            os.close(fd)
    try:
        for d in sorted(dirs, key=lambda p: (p.count('/'), p)):
            fd = parent(d)
            try:
                os.mkdir(d.split('/')[-1], 0o700, dir_fd=fd)
            finally:
                A.sync_dir(fd, 'skill copy')
                os.close(fd)
        for p, (data, mode) in files.items():
            fd = parent(p)
            try:
                child = os.open(p.split('/')[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
                with os.fdopen(child, 'wb') as target:
                    target.write(data)
                    target.flush()
                    os.fchmod(target.fileno(), mode)
                    os.fsync(target.fileno())
            finally:
                A.sync_dir(fd, 'skill copy')
                os.close(fd)
    finally:
        os.close(top)


def qualify(root, facts):
    """Review the bounded safe private copy, explicitly require matching approval."""
    for pack in facts['packs']:
        if not pack['included']:
            continue
        p = os.path.join(root, pack['name'])
        need(C.approved_of(p) == pack['approved'] and C.content_hash(p) == pack['approved'],
             "content/approval drift: " + pack['name'])
        need(C.review('skill', p)[1] == 0, "fails review: " + pack['name'])
        import attempts as A
        fd = A.directory(p)
        try:
            body = A.read_at(fd, 'SKILL.md', MAX_FILE)
        finally:
            os.close(fd)
        try:
            packs_render.check_front_matter(pack['name'], body)
        except SystemExit as e:
            raise Invalid('member skills: invalid canonical skill name/front matter') from e


def freeze(store, request):
    """Init owns store.path exclusively and removes that tree on any failure."""
    if not enabled(request['project']):
        return None
    facts, files, dirs = selection(request['project'], request['role'], request['runtime'])
    root = store.path + '/skills'
    os.mkdir(root, 0o700)
    put_tree(root, files, dirs)
    qualify(root, facts)
    manifest = dict(schema=1, facts=facts, files=descriptions(files), dirs=dirs)
    data = encode(manifest)
    need(len(data) <= MAX_MANIFEST, 'manifest exceeds 1 MiB')
    import attempts as A
    fd = A.directory(store.path)
    try:
        A.atomic(fd, 'skills.json', data)
    finally:
        os.close(fd)
    return dict(manifest='skills.json', sha256=sha(data))


def manifest(store, ref, full=False):
    import attempts as A
    need(type(ref) is dict and set(ref) == {'manifest', 'sha256'} and ref['manifest'] == 'skills.json'
         and isinstance(ref['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', ref['sha256']), 'invalid manifest reference')
    fd = A.directory(store.path)
    try:
        data = A.read_at(fd, 'skills.json', MAX_MANIFEST, 0o600)
    finally:
        os.close(fd)
    need(sha(data) == ref['sha256'], 'manifest identity changed')
    doc = A.decode(data)
    need(type(doc) is dict and set(doc) == {'schema', 'facts', 'files', 'dirs'} and type(doc['schema']) is int and doc['schema'] == 1,
         'invalid manifest')
    facts = doc['facts']
    need(type(facts) is dict and set(facts) == set('project role runtime composition destination delivery_root links exclusions packs skipped'.split()),
         'invalid manifest facts')
    need(all(isinstance(facts[k], str) for k in ('project', 'role', 'runtime', 'composition', 'destination', 'delivery_root'))
         and P._plain_relative(facts['destination']) and P._plain_relative(facts['delivery_root'])
         and (facts['destination'] == facts['delivery_root'] or facts['destination'].startswith(facts['delivery_root'] + '/')),
         'invalid manifest destination')
    need(type(doc['files']) is list and type(doc['dirs']) is list
         and len(doc['files']) + len(doc['dirs']) <= MAX_ENTRIES, 'invalid manifest inventory')
    need(type(facts['packs']) is list and len(facts['packs']) <= MAX_SKILLS, 'invalid manifest skills')
    for pack in facts['packs']:
        need(type(pack) is dict and set(pack) == {'name', 'approved', 'files', 'dirs', 'included', 'compatibility'}
             and isinstance(pack['name'], str) and M.PACK_NAME.fullmatch(pack['name'])
             and type(pack['included']) is bool and packs_compat.problem(pack['compatibility']) is None
             and (isinstance(pack['approved'], str) and re.fullmatch(r'[0-9a-f]{16}', pack['approved']) if pack['included'] else
                  pack['approved'] is None and pack['files'] == [] and pack['dirs'] == []), 'invalid manifest skill')
    if full:
        files, dirs = collect(store.path + '/skills')
        need(descriptions(files) == doc['files'] and sorted(dirs) == sorted(doc['dirs']), 'snapshot bytes changed')
        for path in [''] + dirs:
            st = os.stat(store.path + '/skills/' + path, follow_symlinks=False)
            need(stat.S_ISDIR(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o700, 'snapshot directory mode changed')
        # Modes in private evidence are normalized and owner-only.
        for row in doc['files']:
            need(stat.S_IMODE(os.stat(store.path + '/skills/' + row['path']).st_mode) == row['mode'], 'snapshot mode changed')
    return doc


def current(store, prepared, project, runtime):
    ref = prepared.get('skills')
    on = enabled(project)
    need(on == (ref is not None), 'opt-in changed; re-prepare')
    if ref is None:
        return None
    doc = manifest(store, ref, full=True)
    qualify(store.path + '/skills', doc['facts'])
    fresh, _, _ = selection(project, prepared['request']['role'], runtime)
    need(fresh == doc['facts'], 'selection/content/approval/runtime drift; re-prepare')
    return doc


DELIVERY_RECORD = 'skills-delivery.json'
DELIVERY_STAGE = 'skills.stage'
PRESERVE = '; preserve skills-delivery.json and skills.stage; inspect ownership, then re-prepare in a fresh run'


def identity(st):
    return [st.st_dev, st.st_ino]


def entry(fd, name):
    import attempts as A
    return A.Store._work_entry(fd, name)


def matched(st, expected):
    return st is not None and stat.S_ISDIR(st.st_mode) and identity(st) == expected


def anchored(path, fd):
    """A moved anchor remains safe to use, but no longer qualifies for launch."""
    import attempts as A
    check = A.directory(path, private_leaf=False)
    try:
        need(identity(os.fstat(check)) == identity(os.fstat(fd)), 'delivery parent replaced' + PRESERVE)
    finally:
        os.close(check)


@contextlib.contextmanager
def delivery_state(store, dest):
    """Hold original private and delivery parents through every mutation.

    The private lifecycle directory is controller-only cooperative authority,
    as for init's partial copies. Never infer creation ownership in RUN. The
    allocation phase covers only children of that exclusive private directory;
    an identity is persisted before any tree can leave it.
    """
    import attempts as A
    path = store.run + '/' + dest
    parent, name = os.path.split(path)
    with contextlib.ExitStack() as stack:
        private = A.directory(store.path)
        stack.callback(os.close, private)
        try:
            owner = A.decode(A.read_at(private, DELIVERY_RECORD, 4096, 0o600))
        except FileNotFoundError:
            owner = None
        if owner is not None:
            need(type(owner) is dict and set(owner) == {'path', 'parent', 'private', 'identity', 'phase', 'inode'}
                 and owner['path'] == path and owner['identity'] == store.show()['prepared']['identity']
                 and owner['phase'] in ('allocating', 'ready', 'published', 'cleaning'), 'invalid delivery ownership')
            for key in ('parent', 'private', 'inode'):
                value = owner[key]
                valid = type(value) is list and len(value) == 2 and all(type(n) is int and n >= 0 for n in value)
                need((value is None if owner['phase'] == 'allocating' else valid) if key == 'inode' else valid,
                     'invalid delivery identity')
            need(owner['private'] == identity(os.fstat(private)), 'private delivery parent replaced' + PRESERVE)
        try:
            pfd = A.directory(parent, private_leaf=False)
            stack.callback(os.close, pfd)
        except FileNotFoundError:
            need(owner is None, 'delivery parent missing' + PRESERVE)
            need(entry(private, DELIVERY_STAGE) is None, 'unrecorded private delivery staging' + PRESERVE)
            yield None, None, private
            return
        if owner is not None:
            need(owner['parent'] == identity(os.fstat(pfd)), 'delivery parent replaced' + PRESERVE)
        source, stage = entry(pfd, name), entry(private, DELIVERY_STAGE)
        if owner is None:
            need(source is None and stage is None, 'foreign delivery or missing ownership' + PRESERVE)
        else:
            if source is not None:
                need(owner['phase'] != 'allocating' and matched(source, owner['inode']), 'foreign/replaced delivery' + PRESERVE)
            if stage is not None:
                # A partial allocation never left exclusive private authority.
                # It is cleaned there, never adopted as a publishable snapshot.
                need(owner['phase'] == 'allocating' and matched(stage, identity(stage))
                     and stage.st_uid == os.geteuid() and stat.S_IMODE(stage.st_mode) == 0o700
                     and stage.st_dev == os.fstat(private).st_dev
                     or owner['phase'] != 'allocating' and matched(stage, owner['inode']),
                     'staged delivery identity mismatch' + PRESERVE)
            need(source is None or stage is None, 'ambiguous delivery/staging' + PRESERVE)
        yield owner, pfd, private


def ownership(store, dest):
    """Read-only inspection, including recoverable absent and partial states."""
    with delivery_state(store, dest) as (owner, _, __):
        return owner


def cleanup_quiescent(store, dispatch_state=None):
    import attempts as A
    store.require_lock()
    record = store.show()
    d = record['attempts'][-1]['dispatch']
    need(d is not None, 'delivery cleanup requires native attempt begin' + PRESERVE)
    need(not dispatch_state or not dispatch_state['spawned'] or dispatch_state['recorded'],
         'member group was never recorded; cleanup membership unknown' + PRESERVE)
    if d['member'] is not None:
        try:
            alive = A.group_alive(d['member']['pid'])
        except A.Refuse as e:
            raise Invalid('member skills: cleanup group membership unknown' + PRESERVE) from e
        need(not alive, 'member process group is present; skill cleanup refused' + PRESERVE)
    else:
        store._owned_dispatch(record)  # Only this native pre-spawn runner may recover.


def remove_staged(private, expected):
    """Private anchored tombstone; retain mounted filesystems and mismatches."""
    import attempts as A
    need(shutil.rmtree.avoids_symlink_attacks, 'safe cleanup unavailable' + PRESERVE)
    child = os.open(DELIVERY_STAGE, os.O_RDONLY | os.O_DIRECTORY | A.NOFOLLOW, dir_fd=private)
    try:
        need(matched(os.fstat(child), expected) and matched(entry(private, DELIVERY_STAGE), expected),
             'staged delivery identity mismatch' + PRESERVE)
        # Same anchored-parent, one-filesystem deletion as lifecycle clean_work.
        try:
            subprocess.run(['rm', '-rf', '--one-file-system', '--',
                            '/proc/self/fd/%d/%s' % (private, DELIVERY_STAGE)],
                           env={'PATH': A.clean_path()}, pass_fds=(private,), close_fds=True, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise Invalid('member skills: skill cleanup incomplete; retained staging' + PRESERVE) from e
        need(entry(private, DELIVERY_STAGE) is None, 'skill cleanup incomplete; retained mounted filesystem' + PRESERVE)
        A.sync_dir(private, 'skill staging deletion')
    finally:
        os.close(child)


def move_new(source, name, target, new):
    """Use existing Linux no-replace support, with both parents held open."""
    try:
        moved = linker.renameat2(source, name, '/proc/self/fd/%d/%s' % (target, new), 1)
    except FileExistsError as e:
        raise Invalid('member skills: foreign delivery/staging already exists' + PRESERVE) from e
    need(moved, 'atomic no-replace directory rename unavailable' + PRESERVE)


def clear(store, dest, dispatch_state=None):
    import attempts as A
    ownership(store, dest)  # Advisory read; mutations acquire and revalidate their own anchors.
    with delivery_state(store, dest) as (owner, parent, private):
        if owner is None:
            return
        cleanup_quiescent(store, dispatch_state)
        path, name = os.path.split(owner['path'])
        anchored(path, parent)
        source, stage = entry(parent, name), entry(private, DELIVERY_STAGE)
        if source is not None:
            root = os.open(name, os.O_RDONLY | os.O_DIRECTORY | A.NOFOLLOW, dir_fd=parent)
            try:
                need(matched(os.fstat(root), owner['inode']), 'foreign/replaced delivery' + PRESERVE)
                owner['phase'] = 'cleaning'
                A.atomic(private, DELIVERY_RECORD, encode(owner))  # Intent precedes rename.
                move_new(parent, name, private, DELIVERY_STAGE)
                A.sync_dir(parent, 'skill cleanup rename')
                A.sync_dir(private, 'skill cleanup rename')
                need(matched(entry(private, DELIVERY_STAGE), owner['inode']), 'staged delivery identity mismatch' + PRESERVE)
            finally:
                os.close(root)
            stage = entry(private, DELIVERY_STAGE)
        if stage is not None:
            expected = identity(stage) if owner['phase'] == 'allocating' else owner['inode']
            remove_staged(private, expected)
        anchored(path, parent)
        need(entry(parent, name) is None, 'foreign/replaced delivery during cleanup' + PRESERVE)
        os.unlink(DELIVERY_RECORD, dir_fd=private)
        A.sync_dir(private, 'skill delivery record retirement')


def launch_ready(store, prepared):
    doc = manifest(store, prepared['skills'])
    dest = doc['facts']['delivery_root']
    with delivery_state(store, dest) as (owner, parent, _):
        need(owner is not None and owner['phase'] == 'published'
             and matched(entry(parent, os.path.basename(owner['path'])), owner['inode']),
             'delivery incomplete or missing before launch' + PRESERVE)
        anchored(os.path.dirname(owner['path']), parent)


def deliver(store, prepared):
    import attempts as A
    doc = manifest(store, prepared['skills'], full=True)
    dest = doc['facts']['delivery_root']
    clear(store, dest)
    cleanup_quiescent(store)
    with delivery_state(store, dest) as (owner, parent, private):
        need(owner is None and parent is not None, 'delivery parent unavailable' + PRESERVE)
        need(os.fstat(parent).st_dev == os.fstat(private).st_dev,
             'delivery and private state must share a filesystem; use --scratch on the state filesystem')
        owner = dict(path=store.run + '/' + dest, parent=identity(os.fstat(parent)), private=identity(os.fstat(private)),
                     identity=store.show()['prepared']['identity'], phase='allocating', inode=None)
        A.atomic(private, DELIVERY_RECORD, encode(owner))
        try:
            # Only allocate inside existing exclusive lifecycle authority. A
            # foreign RUN replacement can never become our creation identity.
            os.mkdir(DELIVERY_STAGE, 0o700, dir_fd=private)
            root = os.open(DELIVERY_STAGE, os.O_RDONLY | os.O_DIRECTORY | A.NOFOLLOW, dir_fd=private)
            try:
                owner.update(inode=identity(os.fstat(root)), phase='ready')
                A.sync_dir(private, 'skill allocation')
                A.atomic(private, DELIVERY_RECORD, encode(owner))
                target = os.dup(root)
                try:
                    nested = doc['facts']['destination'][len(dest):].strip('/')
                    if nested:
                        for part in nested.split('/'):
                            os.mkdir(part, 0o700, dir_fd=target)
                            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | A.NOFOLLOW, dir_fd=target)
                            A.sync_dir(target, 'nested skill allocation')
                            os.close(target)
                            target = child
                    files, dirs = collect(store.path + '/skills')
                    need(descriptions(files) == doc['files'] and sorted(dirs) == sorted(doc['dirs']), 'snapshot bytes changed during delivery')
                    names = {p['name'] for p in doc['facts']['packs'] if p['included']}
                    put_tree(target, {p: v for p, v in files.items() if p.split('/')[0] in names and p.split('/', 1)[1] != '.pack.json'},
                             [d for d in dirs if d.split('/')[0] in names])
                finally:
                    os.close(target)
                anchored(os.path.dirname(owner['path']), parent)
                name = os.path.basename(owner['path'])
                need(entry(parent, name) is None, 'foreign delivery before publication' + PRESERVE)
                move_new(private, DELIVERY_STAGE, parent, name)
                A.sync_dir(private, 'skill publication')
                A.sync_dir(parent, 'skill publication')
                need(matched(entry(parent, name), owner['inode']), 'foreign/replaced delivery after publication' + PRESERVE)
                anchored(os.path.dirname(owner['path']), parent)
                owner['phase'] = 'published'
                A.atomic(private, DELIVERY_RECORD, encode(owner))
            finally:
                os.close(root)
        except BaseException:
            # Native retries recover recorded partial work. Do not destroy
            # evidence on a crash; ordinary caught failures can clean safely.
            if sys.exc_info()[0] not in (KeyboardInterrupt, SystemExit):
                clear(store, dest)
            raise
    launch_ready(store, prepared)


def role_inventory(answers):
    """Inventory prepare's catalogue, without granting or restricting access."""
    declarations = answers.get('roles') or {}
    rows = []
    for name in sorted(set(R.role_names()) | set(declarations)):
        if name == 'lead':
            continue
        directory = R.role_dir(name) if R.NAME.fullmatch(name) else None
        cls = R.role_class(name) if directory else None
        problems = R.check_one(name)[0] if directory else ['role files unavailable']
        applicable = directory is not None and cls in ('write', 'read-only')
        rows.append(dict(role=name, declared=name in declarations, cls=cls,
                         status='qualified' if applicable else 'invalid' if directory else 'unavailable',
                         metadata='invalid' if problems else 'valid', problems=problems))
    return rows


def gate(project, choice):
    """Recomputed plan; disabling never loads new pack content or runtime data."""
    old = enabled(project)
    if choice is None:
        return dict(project=project, old=old, new=old)
    answers = P.project_answers(project)
    inventory = role_inventory(answers)
    roles = [r['role'] for r in inventory if r['status'] == 'qualified']
    config = dict(inventory=inventory, models={k: (answers.get('models') or {}).get(k) for k in ('provider', 'extensions')},
                  roles={r: dict(exclusions=((answers.get('roles') or {}).get(r) or {}).get('packs_off', []),
                                 selected=M.effective(paths.conf(), project, r)) for r in roles})
    link_file = os.path.join(paths.conf(), 'packs', 'links.json')
    links = M._load(link_file, 'pack links')['links'] if os.path.exists(link_file) else []
    config['links'] = sorted([x for x in links if any(M.reaches(x, project, r) for r in roles)], key=encode)
    facts = []
    if choice:
        runtime = P.resolve_project(answers, 'local', project)[0]
        comp = P.compose(runtime, 'local', project)
        destination(comp)
        for role in roles:
            selected, files, dirs = selection(project, role, runtime, comp)
            with tempfile.TemporaryDirectory(prefix='member-skills-') as tmp:
                put_tree(tmp, files, dirs)
                qualify(tmp, selected)
            facts.append(selected)
    else:
        # Revocation shows bounded approval metadata when available, never
        # loading new bodies, composing a runtime or requiring a passing review.
        import attempts as A
        for role in roles:
            packs = []
            for entry in config['roles'][role]['selected']:
                kind, _, name = entry.partition(':')
                if kind != 'skill' or not M.PACK_NAME.fullmatch(name):
                    continue
                approved = 'unavailable'
                try:
                    fd = A.directory(os.path.join(paths.conf(), 'packs', 'skills', name), private_leaf=False)
                    try:
                        rec = A.decode(A.read_at(fd, '.pack.json', MAX_FILE))
                    finally:
                        os.close(fd)
                    value = rec.get('sha256') if isinstance(rec, dict) else None
                    if isinstance(value, str) and re.fullmatch(r'[0-9a-f]{16}', value):
                        approved = value
                except (OSError, A.Refuse, ValueError):
                    pass
                packs.append(dict(name=name, approved=approved, included=False))
            facts.append(dict(role=role, destination='disabled (runtime not qualified)', packs=packs))
    result = dict(project=project, old=old, new=choice, roles=facts, config=config)
    if choice:
        result['runtime'] = runtime
        result['composition'] = sha(encode(comp))
    return result


def main(argv):
    import attempts as A
    try:
        need(len(argv) == 3 and argv[0] == 'plan' and argv[2] in ('enable', 'disable', 'status'), 'usage: plan PROJECT enable|disable|status')
        print(encode(gate(argv[1], {'enable': True, 'disable': False, 'status': None}[argv[2]])).decode(), end='')
        return 0
    except (Invalid, A.Refuse, M.McpError, P.ProviderError, OSError, ValueError) as e:
        print('qargi: ' + str(e)[:1000], file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
