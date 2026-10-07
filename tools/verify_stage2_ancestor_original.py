"""Offline qualification of preserved ancestor-tag expectation mismatch."""
import hashlib,json,sys,zipfile
from pathlib import Path
from paperless_stage1 import audit_sample
PIN="cb8c6ad88370ee6dde47cfd2d5266c96ac5418a6725822248d716a2cd48328d8"
def verify(root):
    path=Path(root)/"evidence/stage2-ancestor-oracle-20261005-182215/campaign-original.zip"
    assert hashlib.sha256(path.read_bytes()).hexdigest()==PIN
    with zipfile.ZipFile(path) as z:
        def j(n):return json.loads(z.read(n))
        prefix="s2-hierarchy-control-1/"
        user=j("ordinary-user.json")
        assert user["id"]==7 and not user["is_staff"] and not user["is_superuser"]
        ids=j(prefix+"bindings.json")["ids"]
        failed=[c for c in j(prefix+"checks.json") if not c["passed"]]
        assert len(failed)==1 and failed[0]["check"]=="B.tags" and failed[0]["native_step"]=="attach_B"
        assert failed[0]["expected"]==[ids["T2"]]
        assert set(failed[0]["observed"])=={ids["T2"],ids["T1"]}
        responses=sorted([j(n) for n in z.namelist() if n.startswith(prefix+"http/") and n.endswith(".json")],key=lambda r:r["sequence"])
        assert len(responses)==38 and all(r["http_status"] in (200,201) for r in responses)
        writes=[r for r in responses if r["method"]=="PATCH"]
        assert [r["step"] for r in writes]==["attach_A","link_T2_T1","attach_B"]
        assert writes[1]["request_body"]=={"parent":ids["T1"]}
        assert writes[1]["response_body"]["parent"]==ids["T1"]
        last=writes[-1];assert last["request_body"]["tags"]==[ids["T2"]]
        assert set(last["response_body"]["tags"])=={ids["T2"],ids["T1"]}
        before=j(prefix+"hierarchy/check_A.json");after=j(prefix+"hierarchy/check_parent_2.json")
        assert len(before)==len(after)==7 and all(r["status"]==200 for r in after.values())
        assert after["T2"]["body"]["parent"]==ids["T1"] and after["T1"]["body"]["parent"] is None
        for entity in ("A","B"):
            assert before[entity]["body"]==after[entity]["body"]
            assert after[entity+"_metadata"]["body"]["original_checksum"]==hashlib.sha256(z.read(prefix+"inputs/"+entity+".pdf")).hexdigest()
        old=after["B"]["body"];new=last["response_body"]
        for key in ("id","owner","title","content","correspondent","storage_path","custom_fields","notes","original_file_name","mime_type","page_count","root_document"):
            assert old.get(key)==new.get(key),key
        assert new["document_type"]==ids["Y"]
        assert not any(r["sequence"]>last["sequence"] for r in responses)
        assert prefix+"hierarchy/check_B.json" not in z.namelist()
        for name,h in j(prefix+"model-hashes.json").items():assert hashlib.sha256(z.read(prefix+"model/"+name)).hexdigest()==h
        sample=j(prefix+"sample-acceptance.json")
        assert hashlib.sha256(z.read(prefix+"model/samples.json")).hexdigest()==sample["samples_sha256"]
        assert audit_sample(j(prefix+"model/samples.json"),j(prefix+"model/stage1-plan.json"))==sample["order"]
    print("STAGE2_ANCESTOR_ORACLE_FALSE_POSITIVE_VERIFIED: child plus known ancestor in successful PATCH response; post-write GET and cycle cases not reached. No API requests sent.")
if __name__=="__main__":verify(sys.argv[1])
