# Paperless Stage 5: lifecycle composition and document version graphs

Install this delta over the existing paperless_sbt_study checkout. The pinned model and existing generic-generator dependencies must be present. No archive from a prior live campaign is overwritten.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Unblock-File '.\scripts\Save-Paperless-Stage5.ps1'
Unblock-File '.\scripts\Run-Paperless-Stage5.ps1'
& .\scripts\Save-Paperless-Stage5.ps1 -Push
& .\scripts\Run-Paperless-Stage5.ps1
```

Run with `-SampleOnly` to generate and select native schedules without creating a fixture user or sending Paperless API requests. Run with `-Container <name>` if automatic discovery of the container publishing port 9930 is ambiguous.

Three cases × two fresh resource sets = six live runs. Each case samples 16 candidates and requires two different business operation orders. The last case explicitly deletes two owned non-root versions and its shared tag/type. Root and control documents remain. One ordinary user is provisioned through local Docker administration; all scenario requests use that user's token.

The release has been checked against local HTTP fixtures using actual native Provengo execution. It has NOT yet been run against your Paperless server. A live candidate is not a confirmed bug until its bodies, semantic policy and subsequent state are independently qualified.

For a successful live campaign, preserve its printed campaign.zip and run:

```powershell
py -3 -B .\tools\verify_paperless_stage5.py '<printed campaign.zip path>'
```

An incomplete/candidate campaign intentionally fails that completeness check; retain it for analysis instead of rerunning automatically. The source Save script commits release files only; it does not commit future live evidence.

See docs/PAPERLESS-STAGE5-VERSION-LIFECYCLES.md for the entity graph, lifecycle compiler, explicit semantic policies, Mealie comparison and remaining coverage limits.
