"""Export transport regression cases for the optional Node comparison."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from generator_v56.pipeline import run_pipeline

entries = []
for contract in sorted((ROOT / 'compatibility/contracts').glob('*.json')):
    for profile in ('parallel-crud', 'long-interleaving'):
        result = run_pipeline(str(contract), 'regression', 'http://127.0.0.1:9925', 2,
                              story_profile=profile, long_rounds=(2, 2),
                              emit_prefix_witnesses=True)
        entries.extend(result.transport_manifest)
Path(sys.argv[1]).write_text(json.dumps(entries), encoding='utf-8')
print('Exported ' + str(len(entries)) + ' transport comparison cases.')
