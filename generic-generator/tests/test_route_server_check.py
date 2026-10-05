"""Native read-only preflight: matching version, mismatch and HTTP rejection."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from tools.check_route_server import check

@unittest.skipUnless(os.environ.get('PROVENGO_TEST_JAR') and shutil.which('java'),'Native jar required')
class RouteServerCheckTests(unittest.TestCase):
    def test_version_and_http_failures_stop_before_any_resource_write(self):
        command=['java','-Xmx256m','-jar',str(Path(os.environ['PROVENGO_TEST_JAR']).resolve())]
        for version,status in [('v3.28.0',200),('wrong',200),('v3.28.0',404)]:
            requests=[]
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    requests.append(('GET',self.path));self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'info':{'version':version}}).encode())
                def log_message(self,*args):pass
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);contract=root/'generic-generator/compatibility/contracts/mealie.json';contract.parent.mkdir(parents=True);contract.write_text('{"info":{"version":"v3.28.0"}}')
                    def launch(args,project):return subprocess.run(command+args+[str(project)],capture_output=True,text=True,timeout=60)
                    with patch('tools.check_route_server.native',launch):
                        if status==200 and version=='v3.28.0':self.assertEqual(check(root,f'http://127.0.0.1:{server.server_port}',root/'review')['status'],'PINNED_SERVER_VERSION_PASS')
                        else:
                            with self.assertRaises(ValueError):check(root,f'http://127.0.0.1:{server.server_port}',root/'review')
                    self.assertEqual(requests,[('GET','/openapi.json')])
                    project=next((root/'provengo').iterdir());self.assertNotIn('checkSvc.',(project/'spec/js/stories.server-check.js').read_text())
            finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
