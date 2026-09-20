"""Write-once SHA-256 inventory of this new dataset directory only."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'MANIFEST.json'


def inventory():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ROOT.rglob('*')) if p.is_file()
            and p != MANIFEST and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['freeze', 'verify'])
    args = parser.parse_args()
    current = inventory()
    if args.command == 'freeze':
        payload = {'version': 'aldertrace-study-v2-draft-1',
                   'phase': 'pre-inference-dataset-integrity',
                   'model_definition_frozen': False, 'human_reviewed': False,
                   'results_status': 'provisional; agent-authored and unreviewed',
                   'assets': current}
        with MANIFEST.open('x', encoding='utf8') as out:
            out.write(json.dumps(payload, indent=2) + '\n')
    else:
        saved = json.loads(MANIFEST.read_text())
        if saved['assets'] != current:
            changed = sorted(k for k in set(saved['assets']) | set(current)
                             if saved['assets'].get(k) != current.get(k))
            raise SystemExit('Dataset inventory drift: ' + ', '.join(changed))
    print(json.dumps({'verified_assets': len(current),
                      'manifest_sha256': hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
                      'human_reviewed': False}))


if __name__ == '__main__':
    main()
