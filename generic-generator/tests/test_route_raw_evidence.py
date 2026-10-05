"""Offline extraction of evidence from successful and interrupted route runs."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from tools.route_raw_evidence import export, extract

class RawRouteEvidenceTests(unittest.TestCase):
    def test_latest_interrupted_record_retains_exact_request_and_error_body(self):
        first={'task_id':'route-identity:example','raw_observations':[]}
        row={'phase':0,'kind':'write','instance':'example#1','operation':'PUT /example/{alias}','code':500,
             'request_body':json.dumps({'name':"Today's renamed resource"}),
             'body':json.dumps({'detail':"Can't complete update"})}
        last={'task_id':first['task_id'],'raw_observations':[row]}
        lines=["RTV: setting 'rel_route_test_example' to '"+json.dumps(r)+"'" for r in [first,last]]
        self.assertEqual(extract('\n'.join(lines)),[last])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'failed.zip'
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('execution-review/run-output.txt','\n'.join(lines))
                archive.writestr('execution-review/run-acceptance.json','{"live_accepted":false}')
                archive.writestr('relationship_scenario_plan.json',json.dumps({'tasks':[{'id':first['task_id'],'kind':'route_identity'}]}))
            result=export(path)
            self.assertEqual(result['observations'],1);self.assertEqual(result['route_records'][0]['raw_observations'][0],row)
            self.assertFalse(result['new_bug_confirmed'])
    def test_incomplete_write_evidence_is_rejected(self):
        record={'task_id':'route-identity:example','raw_observations':[{'kind':'write','code':200,'body':'{}'}]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'invalid.zip'
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('execution-review/run-output.txt',"setting 'rel_route_test_example' to '"+json.dumps(record)+"'")
                archive.writestr('execution-review/run-acceptance.json','{}')
                archive.writestr('relationship_scenario_plan.json',json.dumps({'tasks':[{'id':record['task_id'],'kind':'route_identity'}]}))
            with self.assertRaises(ValueError):export(path)

if __name__=='__main__':unittest.main()
