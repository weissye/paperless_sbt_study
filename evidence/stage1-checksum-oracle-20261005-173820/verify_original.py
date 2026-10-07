"""Offline qualification of the first live run. No API requests or writes."""
import hashlib,json,zipfile
from pathlib import Path
folder=Path(__file__).resolve().parent
qualification=json.loads((folder/'qualification.json').read_text(encoding='utf-8-sig'))
archive=folder/'campaign-original.zip'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==qualification['archive_sha256'],'Archive checksum mismatch'
with zipfile.ZipFile(archive) as z:
    names={n.replace('\\','/'):n for n in z.namelist()}
    def read(path):return z.read(names[path])
    def obj(path):return json.loads(read(path))
    for path,expected in obj('s1-control-1/model-hashes.json').items():
        assert hashlib.sha256(read('s1-control-1/model/'+path)).hexdigest()==expected,path
    checks=obj('s1-control-1/checks.json')
    failed=[c for c in checks if c['passed'] is not True]
    assert len(failed)==1 and failed[0]['check']=='A.original_checksum'
    original=read('s1-control-1/inputs/A.pdf')
    assert failed[0]['expected']==hashlib.md5(original).hexdigest()
    assert failed[0]['observed']==hashlib.sha256(original).hexdigest()
    http=[obj(n) for n in sorted(names) if n.startswith('s1-control-1/http/') and n.endswith('.json')]
    assert len(http)==17 and all(x['http_status'] in (200,201) for x in http)
    assert all(x['method']!='PATCH' for x in http)
    assert obj('ordinary-user.json')['is_superuser'] is False
print('ORACLE_FALSE_POSITIVE_VERIFIED: SHA256 matches original PDF; MD5 comparison was incorrect. 17 successful responses; no relationship PATCH was executed.')
