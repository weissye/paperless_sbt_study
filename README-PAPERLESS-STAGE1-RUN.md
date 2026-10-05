# Paperless stage 1 execution release

## Scope and prerequisites

This delta installs stages 1–4 of the prospective Paperless study: one ordinary user, one client, two distinct synthetic PDF documents per run, a shared tag and a shared document type. The pinned Paperless 3.2.1 study instance must be running locally at http://127.0.0.1:9930. Existing native infrastructure pilot, Python 3, Docker CLI access and Provengo 0.7.5-SNAPSHOT are prerequisites. No additional Python dependencies are required.

The release runs three cases, twice each on fresh resources: sequential construction control; shared-metadata renaming between document bindings; detach, edit the other document and reattach. A complete campaign retains one ordinary user, twelve documents, six tags and six document types. Nothing is deleted, reset or retried automatically. A failure stops the campaign; a later fresh-resource confirmation is an explicit follow-up, not an automatic retry.

## Run at home

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $root = 'D:\Yeshayahu\Temp\paperless_sbt_study'
    Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\paperless_stage1_execution_delta.zip" -DestinationPath $root -Force
    Set-Location $root
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
    Unblock-File '.\scripts\Run-Paperless-Stage1.ps1'
    & .\scripts\Run-Paperless-Stage1.ps1
}
```

If automatic container selection is ambiguous, pass `-Container 'actual-running-paperless-container-name'`. Selection expects one running container publishing port 9930. The script never starts another instance or changes ports.

`-SampleOnly` compiles and audits six native samples, without Docker fixture provisioning or Paperless API requests. Generated files are in each run's `model/spec/js/` directory. Every case uses the same generated interfaces structure and the profile-driven story compiler.

Expected complete status: `STAGE1_SIX_RUNS_PASS`. Upload the printed `runs/stage1-.../campaign.zip` for independent qualification. A pass means these bounded oracles passed; it does not imply exhaustive graph coverage or a confirmed new bug.

## Stages and previous-system connection

| Stage | Paperless behavior | Connection to Mealie |
|---|---|---|
| 1: ingestion and identity | Provision ordinary fixture user; upload PDFs; bind task id to exactly one returned document id | Create prerequisites and capture identities; additionally qualify asynchronous ingestion |
| 2: valid construction | Attach the same tag and type to A, then B; verify exact ids, owner and file checksums | Shared ingredients/resources and valid relationship control |
| 3: interleaved mutation | Rename tag between attaching A and B; rename type after both attachments | Shared updates during construction, preserving stable identities |
| 4: local lifecycle | Detach tag from A, edit B's title, reattach A; read both after each mutation | Removal/re-addition and local-versus-shared effects |

The ordinary user has explicit add/view/change permissions for documents, tags and document types, plus view permission for ingestion tasks. It is neither staff nor superuser. The user is provisioned locally through Docker/Django; this administrative fixture step is outside the measured API sequence. Credentials are generated in memory and are not saved. This stage performs no cross-owner probes.

## Architecture and research transparency

`paperless_stage1.py` is an explicit profile compiler and local recording transport. It validates domain-operation membership against the pinned OpenAPI and compiles native bthreads from a dependency DAG. The current ordinary-user provisioning, multipart ingestion, asynchronous task binding and relationship oracles are explicitly configured additions. They are **not inferred automatically from OpenAPI**, and this release does not claim to be an unchanged application of the legacy generator.

Each generated interface emits one native REST call to a loopback-only, capability-protected transport step. Stories contain no HTTP implementation. The transport dispatches the declared domain operation, records full sanitized write/read bodies, binds returned ids and runs the oracle. An upload step emits one multipart upload. A wait step may emit several task reads and one final document read; a native transport step is therefore not always one target API request. Separate counts and timestamps are retained. These distinctions must remain explicit in any tool comparison.

All HTTP requests are serial. Provengo chooses among dependency-ready actors, including resource creation, ingestion polling and independent readbacks. The important mutation order inside each case is constrained by its prospective policy. This is a bounded construction experiment, **not true simultaneous HTTP concurrency or exhaustive mutation-order exploration**. Provengo records the exact sampled order and the runner checks native completion against it. This installed CLI has no `sample --random-seed` flag; exact replay is grounded in retained sample bytes and hashes, not a claimed deterministic sampler seed.

A fresh namespace and distinct PDF bytes are generated during replay, avoiding filename/title/max-id identity guesses. Each ingestion deadline is 180 seconds from successful upload; 18 native wait windows of at most 10 seconds each bound polling. Success must have exactly one `related_document_ids` entry matching the upload's task id. Timeout, missing task permission, unsupported shape, HTTP transport failure or unexpected target response is INCOMPLETE. A state mismatch is SEMANTIC_CANDIDATE and requires independent review; it is not automatically a confirmed bug.

The oracle checks exact owner and identity, tag sets, document-type ids and titles; protects selected content/metadata fields; and verifies the original document checksum against the uploaded bytes. Controlled tag/type renaming intentionally does not protect slug equality. Archive-generated checksums or modified timestamps are not treated as immutable. All target bodies remain available for additional review.

## Evidence and Git

The campaign ZIP includes contract/profile registration hashes, compiled plans and source hashes, symbolic sample files and their audits, native output/result files, complete sanitized target HTTP request/response records, ordered native-step receipts, identity/task bindings, synthetic PDFs and check-by-check observations. Authentication credentials/tokens and the temporary local bridge key are redacted. The original pinned contract remains in the repository; its SHA256 must match registration.

The script neither commits nor pushes. Preserve this release's source/profile/README/validation first, then archive a qualified live campaign separately. Keep the `model/paperless-openapi.json -text` Git attribute already installed. Do not stage all `runs` or `provengo` directories indiscriminately.

## Validation limits

Release tests use a local HTTP fixture plus actual Provengo 0.7.5-SNAPSHOT, with five Python regression tests and six complete native sample/replay tests. The fixture tests detect an injected other-document tag corruption and stop on ambiguous task identity. Docker/Django provisioning and actual Paperless ingestion have not been exercised by the authoring runtime; the home run qualifies those integration boundaries. Preserve the first failure ZIP before making any change.
