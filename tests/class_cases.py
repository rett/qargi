"""Focused cases invoked by test_runs_close.sh with a hermetic prepared run."""
import json
import os
from pathlib import Path
import subprocess
import sys

run, registry, cli = map(Path, sys.argv[1:])
saved = registry.read_bytes()
records = [json.loads(line) for line in saved.splitlines()]
cases = json.loads(Path('tests/fixtures/run-classes.json').read_text())
report = run / 'out/report.md'
evidence = report.read_bytes()
env = dict(os.environ)
env.pop('QARGI_MEMBER_RUN', None)


def call(args, environ=env):
    return subprocess.run(args, env=environ, capture_output=True)


try:
    for case in cases:
        rows = [dict(row) for row in records]
        for row in rows:
            if row['run'] == str(run):
                row.pop('class', None)
                if 'value' in case:
                    row['class'] = case['value']
        text = ''.join(json.dumps(row) + '\n' for row in rows)
        # Keep Unicode escapes in valid input: validate the decoded JSON enum.
        if case['name'] == 'escaped-write':
            text = text.replace('"class": "write"', '"class": "\\u0077rite"')
        if case['name'] == 'escaped-read-only':
            text = text.replace('"class": "read-only"', '"class": "read\\u002donly"')
        registry.write_text(text)
        public = call(['bash', '-c', '. lib/lib.sh; reg_load; run_class "$1"', '_', str(run)])
        if case.get('valid'):
            assert public.returncode == 0 and public.stdout == (case['value'] + '\n').encode() and not public.stderr, (case, public)
            continue
        assert public.returncode != 0 and public.stdout == b'', (case, public)
        expected = ('qargi: the lead\'s registry has no valid class for %s (expected write or read-only); nothing was done\n' % run).encode()
        assert public.stderr == expected, (case, public.stderr)
        for args in [('local', v, str(run)) for v in ('verify', 'run', 'clean', 'report')]+[
            ('local', 'close', str(run), '--applied-by-am'), ('review', 'apply', str(run)), ('review', 'check', str(run / 'out'))]:
            result = call([str(cli), *args])
            assert result.returncode == 3 and result.stderr == expected, (case, args, result)
            assert run.is_dir() and report.read_bytes() == evidence
            assert not (run / 'verified').exists() and not (run / 'applied').exists()
        print('class refusal: ' + case['name'] + ' PASS')
finally:
    registry.write_bytes(saved)
print('exact registry classes: PASS')
