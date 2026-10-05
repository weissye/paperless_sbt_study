"""Offline regressions from archived live bodies; no API requests."""
import copy,io,json,os,unittest,zipfile
from pathlib import Path
from tools.copy_receipts import validate_copy_receipts,CopyMismatch
from tools.verify_copy_campaign import verify
ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=Path(os.environ.get('COPY_LIVE_REGRESSION_ARCHIVE',str(ROOT.parent/'evidence/copy-isolation-20261005-082853/campaign-original.zip')))


@unittest.skipUnless(ARCHIVE.is_file(),'Preserved live campaign required')
class LiveCopyQualificationTests(unittest.TestCase):
    def load(self,case):
        with zipfile.ZipFile(ARCHIVE) as campaign:
            matches=[n for n in campaign.namelist() if n.replace('\\','/')==case+'/live-1.zip']
            self.assertEqual(len(matches),1)
            with zipfile.ZipFile(io.BytesIO(campaign.read(matches[0]))) as live:
                acceptance=json.loads(live.read('execution-review/run-acceptance.json'))
                plan=json.loads(live.read('relationship_scenario_plan.json'))
                return acceptance['runtime_receipt'],plan
    def test_requalification_retains_original_classifications(self):
        report=verify(ARCHIVE)
        self.assertEqual(sum(r['status']=='PASS' for r in report['runs']),6)
        self.assertEqual(sum(r['status']=='COPY_CANDIDATE' for r in report['runs']),2)
        self.assertEqual(report['distinct_owned_identities'],104)
        self.assertEqual(sum(r['original_status']=='COPY_CANDIDATE' and r['status']=='PASS' for r in report['runs']),4)
    def test_quantity_and_counterpart_changes_are_not_excluded(self):
        receipt,plan=self.load('source-first');validate_copy_receipts(receipt,plan)
        task=next(t for t in plan['tasks'] if t['kind']=='copy_isolation')
        for path in ['quantity','note']:
            broken=copy.deepcopy(receipt)
            row=next(r for r in broken['copy_isolations'][0]['observations'] if r['phase']=='mutation-0' and r['kind']=='read' and r['instance']==task['copy_instance'])
            body=json.loads(row['body']);body['recipeIngredient'][0][path]=999 if path=='quantity' else 'COUNTERPART_LEAK';row['body']=json.dumps(body)
            with self.assertRaises(CopyMismatch):validate_copy_receipts(broken,plan)
    def test_internal_reference_defect_survives_display_fix(self):
        receipt,plan=self.load('internal-reference')
        with self.assertRaisesRegex(CopyMismatch,'Dangling internal child reference'):validate_copy_receipts(receipt,plan)
