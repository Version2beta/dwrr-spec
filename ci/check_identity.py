"""Verify the reviewed spec/tool/driver identities and complete corpus counts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
record = json.loads((ROOT / 'ci/identity.json').read_text())
expected = record['sha256']
# Explicit driver source inventory excludes ignored/local build products.
actual = {
    'SPEC.md', 'PROTOCOL.md', 'corpus/README.md',
    'drivers/go/README.md', 'drivers/go/go.mod', 'drivers/go/go.sum',
    'drivers/go/main.go', 'drivers/go/main_test.go',
}
for pattern in ('corpus/*.jsonl', 'tools/*.py'):
    actual.update(str(p.relative_to(ROOT)) for p in ROOT.glob(pattern) if p.is_file())
assert actual == set(expected), 'identity inventory changed'
for name, digest in expected.items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
cases = steps = 0
files = sorted((ROOT / 'corpus').glob('*.jsonl'))
for path in files:
    for line in path.read_text().splitlines():
        case = json.loads(line)
        assert case['name'] and case['steps']
        for step in case['steps']:
            assert set(step) == {'request', 'response'}
        cases += 1
        steps += len(case['steps'])
assert (len(files), cases, steps) == (7, 1839, 44728)
print('PASS reviewed identities: 7 corpus files, 1839 cases, 44728 steps')
