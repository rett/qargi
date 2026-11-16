#!/usr/bin/env python3
"""Opt-in managed member skills. Canonical links select; private lifecycle bytes deliver.

Limits: 64 skills, 4096 tree entries, 2,000,000 bytes per file, 16 MiB
aggregate (including records), 1 MiB manifest, 16 path components/512 bytes.
The canonical review's tighter per-pack limits still apply. Approval hashes
retain their existing meaning; full SHA256s and normalized modes protect copies.
No provider name, rendered union, RUN mirror or pack prose grants authority.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import packs_check as C
import packs_compat
import packs_mcp as M
import packs_render
import paths
import provider as P

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


def collect(root):
    """Bounded nofollow reads; reject hardlinks/specials before opening a body."""
    import attempts as A
    fd = A.directory(os.path.abspath(root), private_leaf=False)
    files, dirs = {}, []
    total = count = 0

    def walk(dfd, prefix=''):
        nonlocal total, count
        names = os.listdir(dfd)
        need(len(names) <= MAX_ENTRIES, "too many entries")
        for name in sorted(names):
            rel = prefix + name
            count += 1
            need(count <= MAX_ENTRIES and safe_path(rel), "unsafe path or too many entries")
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
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
                try:
                    now = os.fstat(child)
                    need((now.st_dev, now.st_ino) == (st.st_dev, st.st_ino), "file changed")
                    data = b''
                    while len(data) <= MAX_FILE:
                        chunk = os.read(child, min(65536, MAX_FILE + 1 - len(data)))
                        if not chunk:
                            break
                        data += chunk
                    need(len(data) <= MAX_FILE and stat.S_ISREG(now.st_mode) and now.st_nlink == 1,
                         'file changed or exceeds bound')
                    after = os.fstat(child)
                    need((after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                         (now.st_size, now.st_mtime_ns, now.st_ctime_ns), "file changed while reading")
                finally:
                    os.close(child)
                total += len(data)
                need(total <= MAX_TOTAL, "aggregate content exceeds 16 MiB")
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
    relevant = [x for x in links if x.get('scope') == 'user'
                or x.get('scope') == 'user-role' and x.get('role') == role
                or x.get('scope') == 'project' and x.get('project') == project
                or x.get('scope') == 'project-role' and x.get('project') == project and x.get('role') == role]
    answers = P.project_answers(project, conf)
    off = ((answers.get('roles') or {}).get(role) or {}).get('packs_off', [])
    packs, bodies, dirs, skipped = [], {}, [], []
    for entry in entries:
        kind, sep, name = entry.partition(':')
        need(sep and kind in ('skill', 'tool') and M.PACK_NAME.fullmatch(name), "unsupported linked kind/name")
        if kind == 'tool':
            continue
        files, subdirs = collect(os.path.join(conf, 'packs', 'skills', name))
        need('.pack.json' in files and 'SKILL.md' in files, "missing record or SKILL.md: " + name)
        try:
            rec = json.loads(files['.pack.json'][0])
        except (ValueError, UnicodeError) as e:
            raise Invalid('member skills: malformed pack record') from e
        approval = rec.get('sha256') if isinstance(rec, dict) else None
        need(isinstance(approval, str) and re.fullmatch(r'[0-9a-f]{16}', approval), "missing/empty content approval: " + name)
        declared = rec.get('compatible_providers')
        need(packs_compat.problem(declared) is None, "invalid compatibility: " + name)
        ok, reason = packs_compat.evaluate(declared, answers, project, ['local'])
        # Keep excluded content identity too: approval/content changes require a new prepare.
        packs.append(dict(name=name, approved=approval, files=descriptions(files), dirs=subdirs, included=ok))
        if not ok:
            skipped.append(dict(name=name, reason=reason.strip()))
        for p, value in files.items():
            bodies[name + '/' + p] = value
        dirs.extend([name] + [name + '/' + d for d in subdirs])
    need(len(packs) <= MAX_SKILLS and len(bodies) + len(dirs) <= MAX_ENTRIES,
         "too many skills or entries")
    need(sum(len(v[0]) for v in bodies.values()) <= MAX_TOTAL, "aggregate content exceeds 16 MiB")
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
    top = A.directory(root)

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
                os.close(fd)
    finally:
        os.close(top)


def qualify(root, facts):
    """Review the bounded safe private copy, explicitly require matching approval."""
    for pack in facts['packs']:
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
        need(type(pack) is dict and set(pack) == {'name', 'approved', 'files', 'dirs', 'included'}
             and isinstance(pack['name'], str) and M.PACK_NAME.fullmatch(pack['name'])
             and isinstance(pack['approved'], str) and re.fullmatch(r'[0-9a-f]{16}', pack['approved'])
             and type(pack['included']) is bool, 'invalid manifest skill')
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


def ownership(store, dest):
    """Read only; never adopt or delete an unrecorded/replaced destination."""
    import attempts as A
    first = store.run + '/' + dest
    # Own the first skills_dir component, including any nested destination.
    parent, name = os.path.split(first)
    try:
        fd = A.directory(store.path)
        try:
            owner = A.decode(A.read_at(fd, 'skills-delivery.json', 4096, 0o600))
        finally:
            os.close(fd)
    except FileNotFoundError:
        owner = None
    if owner is not None:
        need(type(owner) is dict and set(owner) == {'path', 'dev', 'ino', 'parent_dev', 'parent_ino'} and owner['path'] == first
             and all(type(owner[k]) is int and owner[k] >= 0 for k in ('dev', 'ino', 'parent_dev', 'parent_ino')),
             'invalid delivery ownership')
    try:
        pfd = A.directory(parent, private_leaf=False)
    except FileNotFoundError:
        need(owner is None, 'delivery parent missing; preserve evidence')
        return None
    try:
        pst = os.fstat(pfd)
        try:
            st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
        except FileNotFoundError:
            need(owner is None, 'owned delivery missing; preserve evidence')
            return None
        need(owner is not None and stat.S_ISDIR(st.st_mode) and (st.st_dev, st.st_ino) == (owner['dev'], owner['ino'])
             and (pst.st_dev, pst.st_ino) == (owner['parent_dev'], owner['parent_ino']),
             'foreign/replaced delivery or missing ownership; preserve evidence')
        return owner
    finally:
        os.close(pfd)


def clear(store, dest):
    import attempts as A
    owner = ownership(store, dest)
    if owner is None:
        return
    parent, name = os.path.split(owner['path'])
    fd = A.directory(parent, private_leaf=False)
    try:
        shutil.rmtree(name, dir_fd=fd)
    finally:
        os.close(fd)
    fd = A.directory(store.path)
    try:
        os.unlink('skills-delivery.json', dir_fd=fd)
    finally:
        os.close(fd)


def deliver(store, prepared):
    import attempts as A
    doc = manifest(store, prepared['skills'], full=True)
    dest = doc['facts']['delivery_root']
    clear(store, dest)
    # Use the frozen layout as well as frozen bodies. Current configuration is
    # compared by preflight, never rebound here, even during a concurrent edit.
    parent_rel, first = dest.rsplit('/', 1)
    parent = store.run + '/' + parent_rel
    fd = A.directory(parent, private_leaf=False)
    try:
        os.mkdir(first, 0o700, dir_fd=fd)
        st, pst = os.stat(first, dir_fd=fd, follow_symlinks=False), os.fstat(fd)
        owner = dict(path=parent + '/' + first, dev=st.st_dev, ino=st.st_ino, parent_dev=pst.st_dev, parent_ino=pst.st_ino)
        private = A.directory(store.path)
        try:
            A.atomic(private, 'skills-delivery.json', encode(owner))
        except BaseException:
            os.rmdir(first, dir_fd=fd)
            raise
        finally:
            os.close(private)
    finally:
        os.close(fd)
    try:
        root = store.run + '/' + doc['facts']['destination']
        nested = doc['facts']['destination'][len(dest):].strip('/')
        if nested:
            fd = A.directory(parent + '/' + first)
            try:
                for part in nested.split('/'):
                    os.mkdir(part, 0o700, dir_fd=fd)
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
            finally:
                os.close(fd)
        files, dirs = collect(store.path + '/skills')
        names = {p['name'] for p in doc['facts']['packs'] if p['included']}
        put_tree(root, {p: v for p, v in files.items() if p.split('/')[0] in names and p.split('/', 1)[1] != '.pack.json'},
                 [d for d in dirs if d.split('/')[0] in names])
    except BaseException:
        clear(store, dest)
        raise


def gate(project, choice):
    """Recomputed plan; disabling never loads new pack content or runtime data."""
    old = enabled(project)
    if choice is None:
        return dict(project=project, old=old, new=old)
    answers = P.project_answers(project)
    roles = sorted(r for r in (answers.get('roles') or {}) if r != 'lead')
    config = dict(models={k: (answers.get('models') or {}).get(k) for k in ('provider', 'extensions')},
                  roles={r: dict(exclusions=(answers['roles'][r] or {}).get('packs_off', []),
                                 selected=M.effective(paths.conf(), project, r)) for r in roles})
    link_file = os.path.join(paths.conf(), 'packs', 'links.json')
    links = M._load(link_file, 'pack links')['links'] if os.path.exists(link_file) else []
    config['links'] = sorted([x for x in links if x.get('scope') == 'user'
        or x.get('scope') == 'user-role' and x.get('role') in roles
        or x.get('scope') == 'project' and x.get('project') == project
        or x.get('scope') == 'project-role' and x.get('project') == project and x.get('role') in roles], key=encode)
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
    try:
        need(len(argv) == 3 and argv[0] == 'plan' and argv[2] in ('enable', 'disable', 'status'), 'usage: plan PROJECT enable|disable|status')
        print(encode(gate(argv[1], {'enable': True, 'disable': False, 'status': None}[argv[2]])).decode(), end='')
        return 0
    except (Invalid, M.McpError, P.ProviderError, OSError, ValueError) as e:
        print('qargi: ' + str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
