#!/usr/bin/env python3
"""Managed member snapshots through public offline prepare/run/verify paths."""
import hermetic  # noqa: F401
import json
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

import prepared_request_cases

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import attempts as A
import member_skills as MS
import packs_check as C
import provider as P


class MemberSkills(unittest.TestCase):
    setUp = prepared_request_cases.PreparedRequests.setUp
    git = prepared_request_cases.PreparedRequests.git
    save_answers = prepared_request_cases.PreparedRequests.save_answers
    install = prepared_request_cases.PreparedRequests.install
    cmd = prepared_request_cases.PreparedRequests.cmd
    prepare = prepared_request_cases.PreparedRequests.prepare

    def configure(self, runtime='cmdone', on=True):
        self.answers['models']['provider']['local'] = runtime
        self.answers['packs'] = {'member_skills': on}
        self.answers['roles'] = {r: {'base': 'main', 'push': {'mode': 'none'}, 'effort': 'high'} for r in ('build', 'review', 'write')}
        self.answers['repo']['url'] = 'https://git.test/demo.git'
        self.answers['budget_cents'] = 100
        self.save_answers()
        for name, doc in self.definitions.items():
            doc['dispatch']['home'] = {'env': 'FAKE_HOME', 'dir': '.fake', 'skills_dir': 'skills', 'link': []}
            self.install(name, doc)
            exe = doc['dispatch']['argv'][0]
            (self.bin / exe).write_text('#!/usr/bin/env python3\nimport json,os,time\nfrom pathlib import Path\n'
                'home=Path(os.environ["FAKE_HOME"]); run=Path.cwd().parent\n'
                'files={str(p.relative_to(home/"skills")):p.read_text() for p in (home/"skills").rglob("*") if p.is_file()}\n'
                '(run/"out/report.md").write_text("DONE\\n")\nprint(json.dumps(files,sort_keys=True))\n'
                'if (run/"hold").exists():\n'
                ' (run/"ready").touch(); deadline=time.monotonic()+15\n'
                ' while not (run/"release").exists() and time.monotonic()<deadline: time.sleep(.02)\n'
                'if (run/"replace").exists():\n'
                ' (home/"skills").rename(home/"owned-moved"); (home/"skills").mkdir(); (home/"skills/keep").write_text("foreign")\n')
            (self.bin / exe).chmod(0o755)

    def pack(self, name, scopes=('project',), role=None, compatible=None):
        p = self.conf / 'packs/skills' / name
        p.mkdir(parents=True)
        (p / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Offline fixture guidance\n---\nRead the supporting reference.\n')
        (p / 'reference.txt').write_text('bounded support\n')
        (p / '.pack.json').write_text(json.dumps({'compatible_providers': compatible or ['any']}))
        self.seal(p)
        links_path = self.conf / 'packs/links.json'
        links = json.loads(links_path.read_text()) if links_path.exists() else {'links': []}
        for scope in scopes:
            links['links'].append(dict(pack='skill:' + name, scope=scope, project='demo', role=role))
        links_path.write_text(json.dumps(links))
        return p

    def seal(self, p):
        rec = json.loads((p / '.pack.json').read_text())
        rec['sha256'] = C.content_hash(str(p))
        (p / '.pack.json').write_text(json.dumps(rec))

    def ref(self):
        return self.store.show()['prepared'].get('skills')

    def transcript(self):
        return json.loads((self.run / 'out/transcript').read_text())

    def test_default_old_shape_and_enabled_empty_two_command_runtimes(self):
        self.prepare('--role', 'review')
        self.assertIsNone(self.ref())
        self.cmd('local', 'run', self.run)
        self.configure()
        self.assertIn('re-prepare', self.cmd('local', 'run', self.run, '--dry-run', code=2))
        self.configure(on=False)
        self.prepare('--role', 'review')
        self.answers['packs']['member_skills'] = True
        self.save_answers()
        self.assertIn('opt-in changed', self.cmd('local', 'run', self.run, '--dry-run', code=2))
        for runtime in ('cmdone', 'cmdtwo'):
            self.configure(runtime)
            self.prepare('--role', 'review')
            self.assertIsNotNone(self.ref())
            self.cmd('local', 'run', self.run)
            self.assertEqual(self.transcript(), {})
            self.assertFalse((self.run / 'home/.fake/skills').exists())

    def test_four_scopes_roles_classes_lead_exclusion_and_support(self):
        self.configure()
        self.pack('broad-user', ('user',))
        self.pack('broad-project')
        self.pack('builder', ('user-role', 'project-role'), 'build')
        self.pack('reviewer', ('project-role',), 'review')
        self.pack('management', ('project-role',), 'lead')
        for role, expected in [('build', {'broad-user', 'broad-project', 'builder'}),
                               ('review', {'broad-user', 'broad-project', 'reviewer'})]:
            self.prepare('--role', role)
            self.cmd('local', 'run', self.run)
            files = self.transcript()
            self.assertEqual({p.split('/')[0] for p in files}, expected)
            self.assertTrue(all(not p.endswith('.pack.json') for p in files))
            self.assertTrue(all(name + '/reference.txt' in files for name in expected))

    def test_public_gate_token_boolean_and_disable_bad_content(self):
        self.configure(on=False)
        p = self.pack('fixture')
        out = self.cmd('packs', 'member-skills', 'demo', '--enable')
        token = out.split('plan token: ')[1].split()[0]
        self.assertIn('fixture', out)
        (p / 'reference.txt').write_text('changed\n')
        self.assertIn('drift', self.cmd('packs', 'member-skills', 'demo', '--enable', '--plan', token, '--approved', 'fixture', code=2))
        self.seal(p)
        self.assertIn('plan changed', self.cmd('packs', 'member-skills', 'demo', '--enable', '--plan', token, '--approved', 'fixture', code=1))
        out = self.cmd('packs', 'member-skills', 'demo', '--enable')
        token = out.split('plan token: ')[1].split()[0]
        self.cmd('packs', 'member-skills', 'demo', '--enable', '--plan', token, '--approved', 'fixture')
        self.assertTrue(MS.enabled('demo'))
        shutil.rmtree(p)
        self.answers = json.loads((self.conf / 'projects/demo.json').read_text())
        self.answers['models']['provider']['local'] = 'missing'
        self.save_answers()
        out = self.cmd('packs', 'member-skills', 'demo', '--disable')
        token = out.split('plan token: ')[1].split()[0]
        self.cmd('packs', 'member-skills', 'demo', '--disable', '--plan', token, '--approved', 'fixture')
        self.assertFalse(MS.enabled('demo'))
        self.cmd('packs', 'member-skills', 'demo', '--enable', '--disable', code=2)

    def test_dry_run_no_writes_mirrors_cannot_select_and_retry_same_snapshot(self):
        self.configure()
        self.pack('fixture')
        self.prepare('--role', 'review')
        (self.run / 'skills.json').write_text('{"forged":true}')
        (self.run / 'request.json').write_text('{}')
        def snapshot():
            return {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for root in (self.run, self.state, self.conf)
                    for p in root.rglob('*') if p.is_file()}
        before = snapshot()
        out = self.cmd('local', 'run', self.run, '--dry-run')
        self.assertIn('MEMBER_SKILLS=fixture:', out)
        self.assertEqual(before, snapshot())
        self.cmd('local', 'run', self.run)
        original = self.transcript()
        self.cmd('local', 'run', self.run, '--again')
        self.assertEqual(original, self.transcript())

    def test_compatibility_exclusions_and_names_have_no_lead_metadata(self):
        self.configure()
        self.pack('qargi-lead-instructions')
        self.pack('other-client', compatible=['cmdtwo'])
        self.pack('off')
        self.answers['roles']['review']['packs_off'] = ['skill:off']
        self.save_answers()
        self.prepare('--role', 'review')
        self.cmd('local', 'run', self.run)
        self.assertEqual({p.split('/')[0] for p in self.transcript()}, {'qargi-lead-instructions'})

    def test_content_approval_scope_optin_and_exclusion_drift(self):
        self.configure()
        p = self.pack('fixture')
        for change in ('body', 'approval', 'scope', 'off', 'opt-in', 'runtime'):
            with self.subTest(change=change):
                original_answers = json.loads(json.dumps(self.answers))
                links = (self.conf / 'packs/links.json').read_text()
                body = (p / 'reference.txt').read_text()
                rec = (p / '.pack.json').read_text()
                self.prepare('--role', 'review')
                if change == 'body':
                    (p / 'reference.txt').write_text('new body')
                elif change == 'approval':
                    d = json.loads(rec); d['sha256'] = '0' * 16
                    (p / '.pack.json').write_text(json.dumps(d))
                elif change == 'scope':
                    d = json.loads(links); d['links'][0]['scope'] = 'user'
                    (self.conf / 'packs/links.json').write_text(json.dumps(d))
                elif change == 'off':
                    self.answers['roles']['review']['packs_off'] = ['skill:fixture']
                elif change == 'opt-in':
                    self.answers['packs']['member_skills'] = False
                else:
                    self.answers['models']['provider']['local'] = 'cmdtwo'
                self.save_answers()
                self.assertIn('re-prepare', self.cmd('local', 'run', self.run, '--dry-run', code=2))
                self.answers = original_answers
                self.save_answers()
                (self.conf / 'packs/links.json').write_text(links)
                (p / 'reference.txt').write_text(body)
                (p / '.pack.json').write_text(rec)

    def test_unrelated_answers_and_unrelated_links_do_not_drift(self):
        self.configure()
        self.pack('fixture')
        self.prepare('--role', 'review')
        self.answers['budget_cents'] += 10
        self.answers['roles']['write']['purpose'] = 'unrelated'
        self.save_answers()
        links = self.conf / 'packs/links.json'
        doc = json.loads(links.read_text())
        doc['links'].append({'scope': 'project-role', 'project': 'demo', 'role': 'lead', 'pack': 'skill:absent'})
        links.write_text(json.dumps(doc))
        self.cmd('local', 'run', self.run)

    def test_project_paths_types_whole_file_and_native_member_refusal(self):
        self.configure(on=False)
        for value in ('true', 'false', 'null', '1', '[]'):
            self.assertIn('member-skills', self.cmd('project', 'set', 'demo', 'packs.member_skills', value, code=2))
        self.cmd('project', 'unset', 'demo', 'packs.member_skills', code=2)
        self.cmd('project', 'set', 'demo', 'packs', '{"member_skills":true}', code=2)
        import gated_answers as G
        with mock.patch.dict(os.environ, QARGI_MEMBER_RUN='fixture'):
            with self.assertRaises(G.Refused):
                G.store('demo', 'packs.member_skills', True)
        with mock.patch.dict(self.env, QARGI_MEMBER_RUN='fixture'):
            self.cmd('packs', 'member-skills', 'demo', '--disable', code=1)
        for value in ('yes', 1, [], {}, None):
            self.answers['packs']['member_skills'] = value
            self.save_answers()
            self.cmd('project', 'validate', 'demo', code=1)
        self.answers['packs']['member_skills'] = False
        self.save_answers()
        self.cmd('project', 'set', 'demo', 'budget_cents', '200')
        # Whole-file unchanged/removal can narrow; addition or boolean change cannot.
        file = self.root / 'answers.json'
        file.write_text(json.dumps(self.answers))
        self.cmd('project', 'init', 'demo', '--answers', file, '--force')
        self.answers['packs']['member_skills'] = True
        file.write_text(json.dumps(self.answers))
        self.assertIn('packs.member_skills', self.cmd('project', 'init', 'demo', '--answers', file, '--force', code=1))
        self.save_answers()
        self.cmd('project', 'init', 'demo', '--answers', file, '--force')
        self.answers['packs']['member_skills'] = False
        file.write_text(json.dumps(self.answers))
        self.cmd('project', 'init', 'demo', '--answers', file, '--force', code=1)
        del self.answers['packs']['member_skills']
        file.write_text(json.dumps(self.answers))
        self.cmd('project', 'init', 'demo', '--answers', file, '--force')
        self.answers['packs']['member_skills'] = False
        file.write_text(json.dumps(self.answers))
        self.cmd('project', 'init', 'demo', '--answers', file, '--force')

    def test_missing_empty_approval_bad_review_and_unsupported_links(self):
        self.configure()
        p = self.pack('fixture')
        rec = json.loads((p / '.pack.json').read_text())
        for approval in (None, '', False):
            d = dict(rec)
            if approval is None:
                del d['sha256']
            else:
                d['sha256'] = approval
            (p / '.pack.json').write_text(json.dumps(d))
            self.assertIn('approval', self.cmd('packs', 'member-skills', 'demo', '--enable', code=2))
        (p / '.pack.json').write_text(json.dumps(rec))
        (p / 'SKILL.md').write_text('no front matter')
        self.seal(p)
        self.assertIn('review', self.cmd('packs', 'member-skills', 'demo', '--enable', code=2))
        (p / 'SKILL.md').write_text('---\nname: different\ndescription: Valid description\n---\nText.\n')
        self.seal(p)
        self.assertIn('canonical skill name', self.cmd('packs', 'member-skills', 'demo', '--enable', code=2))
        for entry in ('unknown:fixture', 'skill:../fixture', 'skill:/escape'):
            (self.conf / 'packs/links.json').write_text(json.dumps({'links': [{'scope': 'project', 'project': 'demo', 'pack': entry}]}))
            self.assertIn('unsupported', self.cmd('packs', 'member-skills', 'demo', '--enable', code=2))

    def test_destination_validation_and_structural_support(self):
        self.configure()
        doc = self.definitions['cmdone']
        for path in ('../escape', '/absolute', 'a//b', 'a/./b', '~/.skills'):
            home = dict(doc['dispatch']['home'], skills_dir=path)
            self.assertTrue(P.home_problems(home))
        for path in ('auth.json/sub', 'auth.json.from-run/sub'):
            home = dict(doc['dispatch']['home'], skills_dir=path, link=[{'from': '~/.fake/auth.json', 'to': 'auth.json'}])
            self.assertTrue(P.home_problems(home))
        disp = dict(doc['dispatch'], home=dict(doc['dispatch']['home'], skills_dir='config.toml/sub'),
                    run_config={'in': 'home', 'file': 'config.toml'})
        self.assertIn('overlaps', ' '.join(P.run_config_problems(disp, {})))
        for mode, home in [('in-session', doc['dispatch']['home']), ('command', None)]:
            comp = {'definition': {'dispatch': {'mode': mode, 'home': home}}}
            with self.assertRaises(MS.Invalid):
                MS.destination(comp)
        self.answers['models']['provider']['local'] = 'claude-code'
        self.save_answers()
        self.assertIn('in-session', self.cmd('packs', 'member-skills', 'demo', '--enable', code=2))
        self.assertIn('in-session', self.cmd('local', 'prepare', '--repo', self.repo, '--base', 'main',
            '--slug', 'session-refused', '--scratch', self.root, '--role', 'review', code=1))

    def test_reject_symlink_hardlink_special_unsafe_path_and_bounds(self):
        self.configure()
        p = self.pack('fixture')
        target = p / 'entry'
        for kind in ('symlink', 'hardlink', 'fifo', 'unsafe', 'oversize', 'count'):
            with self.subTest(kind=kind):
                if kind == 'symlink': target.symlink_to(p / 'SKILL.md')
                elif kind == 'hardlink': os.link(p / 'SKILL.md', target)
                elif kind == 'fifo': os.mkfifo(target)
                elif kind == 'unsafe': target = p / 'bad name'; target.write_text('bad')
                elif kind == 'oversize': target.write_bytes(b'x' * (MS.MAX_FILE + 1))
                else:
                    for i in range(100): (p / ('extra-' + str(i))).write_text('x')
                    self.seal(p)
                self.cmd('packs', 'member-skills', 'demo', '--enable', code=2)
                if kind == 'count':
                    for i in range(100): (p / ('extra-' + str(i))).unlink()
                else: target.unlink()
                target = p / 'entry'
        # Aggregate limits apply across otherwise ordinary packs too.
        with mock.patch.object(MS, 'MAX_TOTAL', 10):
            with self.assertRaises(MS.Invalid):
                MS.selection('demo', 'review', 'cmdone')

    def test_private_body_tamper_refuses_launch_and_save(self):
        self.configure()
        self.pack('fixture')
        self.prepare('--role', 'review')
        body = Path(self.store.path) / 'skills/fixture/reference.txt'
        body.write_text('forged private body')
        self.assertIn('snapshot bytes', self.cmd('local', 'run', self.run, '--dry-run', code=2))
        self.cmd('local', 'verify', self.run, code=1)

    def test_completed_output_saves_with_changed_configuration(self):
        for on in (False, True):
            with self.subTest(on=on):
                self.configure(on=on)
                if on:
                    self.pack('fixture')
                self.prepare('--role', 'review')
                self.cmd('local', 'run', self.run)
                self.answers['packs']['member_skills'] = not on
                self.answers['models']['provider']['local'] = 'missing'
                self.save_answers()
                links = self.conf / 'packs/links.json'
                links.write_text('malformed current links')
                self.cmd('local', 'verify', self.run)
                self.cmd('local', 'verify', '--saved', self.run.name)
                links.unlink()

    def test_frozen_evidence_does_not_requalify_current_review(self):
        self.configure()
        self.pack('fixture')
        self.prepare('--role', 'review')
        self.cmd('local', 'run', self.run)
        fd = self.store.open_lock()
        os.dup2(fd, 7)
        if fd != 7:
            os.close(fd)
        fcntl.flock(7, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            gate = self.store.gate()
            refs = (Path(self.store.path) / gate['baseline']).read_bytes()
            with mock.patch.object(C, 'review', side_effect=AssertionError('current review used for frozen evidence')):
                A.save_product(self.store, refs)
                saved = self.store.saved_copy()
                self.assertTrue((Path(saved) / 'skills/fixture/SKILL.md').exists())
            with mock.patch.object(C, 'review', return_value=([], 1)):
                with self.assertRaisesRegex(MS.Invalid, 'fails review: fixture'):
                    MS.current(self.store, self.store.show()['prepared'], 'demo', 'cmdone')
        finally:
            os.close(7)

    def test_foreign_delivery_symlink_parent_and_missing_ownership(self):
        self.configure()
        self.pack('fixture')
        for kind in ('foreign', 'symlink', 'parent'):
            self.prepare('--role', 'review')
            home = self.run / 'home/.fake'
            home.mkdir(parents=True)
            target = home / 'skills'
            if kind == 'foreign': target.mkdir(); (target / 'keep').write_text('foreign')
            elif kind == 'symlink': target.symlink_to(self.repo)
            else: home.rmdir(); home.symlink_to(self.repo)
            self.cmd('local', 'run', self.run, '--dry-run', code=2)
            self.assertTrue(target.is_dir() if kind == 'foreign' else target.is_symlink() if kind == 'symlink' else home.is_symlink())

    def test_saved_evidence_retry_generations_and_owned_cleanup(self):
        self.configure()
        self.pack('fixture')
        self.prepare('--role', 'review')
        self.cmd('local', 'run', self.run)
        self.cmd('local', 'verify', self.run)
        saved = self.state / 'runs' / self.run.name
        self.assertEqual((saved / 'skills.json').read_bytes(), (Path(self.store.path) / 'skills.json').read_bytes())
        self.assertTrue((saved / 'skills/fixture/reference.txt').is_file())
        self.cmd('local', 'run', self.run, '--again')
        self.cmd('local', 'verify', self.run)
        self.assertTrue(list(Path(self.store.path).glob('a*.saved.*')))
        self.cmd('local', 'clean', self.run, '--discard')
        self.assertFalse(saved.exists() or self.run.exists() or Path(self.store.path).exists())

    def test_failed_initialization_and_materialization_remove_only_owned_partial(self):
        self.configure()
        self.pack('fixture')
        self.prepare('--role', 'review')
        prepared = self.store.show()['prepared']
        home = self.run / 'home/.fake'
        home.mkdir(parents=True)
        with mock.patch.object(MS, 'put_tree', side_effect=OSError('injected copy failure')):
            with self.assertRaises(OSError): MS.deliver(self.store, prepared)
        self.assertFalse((home / 'skills').exists())
        self.assertFalse((Path(self.store.path) / 'skills-delivery.json').exists())
        with mock.patch.object(MS, 'MAX_MANIFEST', 10):
            with self.assertRaises(MS.Invalid): MS.freeze(self.store, prepared['request'])

    def test_public_init_failure_cleans_exclusive_private_state(self):
        self.configure()
        p = self.pack('fixture')
        (p / 'reference.txt').write_text('unapproved change')
        out = self.cmd('local', 'prepare', '--repo', self.repo, '--base', 'main', '--slug', 'failed-init',
                       '--scratch', self.root, '--role', 'review', code=1)
        self.assertIn('cannot initialize prepared authority', out)
        self.assertEqual(list((self.state / 'attempts').glob('qargi.*')), [])

    def test_replacement_is_preserved_and_retry_refuses_without_adoption(self):
        self.configure()
        self.pack('fixture')
        self.prepare('--role', 'review')
        (self.run / 'replace').touch()
        self.assertIn('replaced', self.cmd('local', 'run', self.run, code=2))
        foreign = self.run / 'home/.fake/skills/keep'
        self.assertEqual(foreign.read_text(), 'foreign')
        self.cmd('local', 'run', self.run, '--again', code=2)
        self.assertEqual(foreign.read_text(), 'foreign')
        self.assertTrue((self.run / 'home/.fake/owned-moved/fixture/SKILL.md').exists())

    def test_parallel_runs_and_concurrent_attempt_lock(self):
        self.configure()
        self.pack('fixture')
        self.prepare('--role', 'review')
        first = self.run
        self.prepare('--role', 'review')
        second = self.run
        children = []
        try:
            for run in (first, second):
                (run / 'hold').touch()
                children.append(subprocess.Popen([str(ROOT / 'bin/qargi'), 'local', 'run', str(run)],
                    env=self.env, cwd=self.repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT))
            deadline = time.monotonic() + 15
            while not all((r / 'ready').exists() for r in (first, second)):
                self.assertLess(time.monotonic(), deadline, 'fake runtimes did not start')
                time.sleep(.02)
            self.assertTrue(all((r / 'home/.fake/skills/fixture/SKILL.md').exists() for r in (first, second)))
            busy = subprocess.run([str(ROOT / 'bin/qargi'), 'local', 'run', str(first), '--again'], env=self.env,
                                  cwd=self.repo, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(busy.returncode, 0)
            self.assertIn('busy', busy.stdout + busy.stderr)
            for run in (first, second): (run / 'release').touch()
            for child in children:
                output, _ = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, output)
            self.assertTrue(all(not (r / 'home/.fake/skills').exists() for r in (first, second)))
        finally:
            for child in children:
                if child.poll() is None: child.kill()
                child.communicate(timeout=10)

    def test_nested_destination_private_modes_and_saved_copy_integrity(self):
        self.configure()
        doc = self.definitions['cmdone']
        doc['dispatch']['home'].update(dir='.fake/nested', skills_dir='managed/skills')
        self.install('cmdone', doc)
        exe = self.bin / doc['dispatch']['argv'][0]
        exe.write_text(exe.read_text().replace('home/"skills"', 'home/"managed/skills"'))
        self.pack('fixture')
        self.prepare('--role', 'review')
        self.cmd('local', 'run', self.run)
        self.assertIn('fixture/reference.txt', self.transcript())
        self.assertFalse((self.run / 'home/.fake/nested/managed').exists())
        self.cmd('local', 'verify', self.run)
        saved = self.state / 'runs' / self.run.name
        (saved / 'skills/fixture/reference.txt').write_text('changed saved evidence')
        self.cmd('local', 'verify', '--saved', self.run.name, code=3)
        body = Path(self.store.path) / 'skills/fixture/reference.txt'
        body.chmod(0o644)
        self.assertIn('mode changed', self.cmd('local', 'run', self.run, '--dry-run', code=2))


if __name__ == '__main__':
    unittest.main()
