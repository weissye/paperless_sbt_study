import http.client,json,unittest
import paperless_stage1 as s
class Engine:
    failed=None
    def __init__(self):self.calls=[]
    def execute(self,step):self.calls.append(step);return {'ok':True,'step':step}
class Tests(unittest.TestCase):
    def test_repeated_post_bodies_have_framed_close_responses(self):
        engine=Engine();server,key=s.serve(engine)
        try:
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            for i in range(120):
                connection.request('POST','/sbt/step/wait_B_11',body=b'{}',headers={'X-SBT-Key':key,'Content-Type':'application/json'})
                response=connection.getresponse();raw=response.read()
                self.assertEqual(response.status,200);self.assertEqual(response.version,11)
                self.assertEqual(response.getheader('Connection'),'close')
                self.assertEqual(int(response.getheader('Content-Length')),len(raw));self.assertTrue(json.loads(raw)['ok'])
            connection.close();self.assertEqual(len(engine.calls),120)
        finally:server.shutdown();server.server_close()
    def test_invalid_key_does_not_execute(self):
        engine=Engine();server,key=s.serve(engine)
        try:
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            connection.request('POST','/sbt/step/start',b'{}',{'X-SBT-Key':'invalid'})
            self.assertEqual(connection.getresponse().status,403);connection.close();self.assertEqual(engine.calls,[])
        finally:server.shutdown();server.server_close()
if __name__=='__main__':unittest.main()
