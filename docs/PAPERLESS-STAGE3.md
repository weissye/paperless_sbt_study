# Paperless Stage3: referenced-resource deletion

## Purpose and boundary

Six bounded native schedules: three cases, two fresh namespaces per case. One new ordinary user and one client, with no simultaneous HTTP requests. This advances from the accepted Stage2 hierarchy campaign to the deletion lifecycle tested earlier in Mealie. It tests state composition and referential cleanup, not a rerun of cycle validation.

Each namespace contains two unique synthetic PDFs (A/B), shared tag T, retained unrelated tag U and shared document type Y. Flat tags and matching_algorithm=0 exclude ancestor inheritance and auto-matching from these cases. The first document is linked, the shared resource is renamed and read back, then the second document is linked and both are read back before deletion.

| Case | Explicit action | Required final state |
|---|---|---|
| S3-DETACHED-DELETE-CONTROL | Detach T from both documents, verify, then DELETE T | T direct read 404; A/B retain U and Y |
| S3-SHARED-TAG-DELETE | DELETE T while both documents reference it | T direct read 404; only T disappears from A/B tags; U and Y remain |
| S3-SHARED-TYPE-DELETE | DELETE Y while both documents reference it | Y direct read 404; A/B document_type null; T and U remain |

DELETE is expected to return 204 in all three cases. Every checkpoint reads T, U, Y, A, B and both document metadata resources before evaluating any discrepancy. Thus an unexpected DELETE response can be correlated with the persisted state. A 500 after a mutation is not masked by an early status assertion.

## Oracles and evidence

OpenAPI supplies declared DELETE/GET/PATCH routes and DELETE status 204. Source-backed profile policies supply many-to-many association cleanup and document_type SET_NULL, based on Paperless commit 7575d6078227ebdb4cf443f263d53ebc7575aa37. Expectations use captured stable IDs and intended actions; they are not learned from the post-delete response.

Check IDs, owners, names, exact tag sets, document types, protected document fields and original SHA256. Language metadata is recorded but is not asserted immutable. Per-resource states are compared only with other instances of the same family; equal numeric IDs across families are valid.

The common compiler emits native interfaces/stories and a plan from the pinned contract and explicit profile. Each step has one actor; a coordinator enforces the dependency DAG. Control has 62 native steps (63 bthreads including coordinator); other cases have 58 (59 bthreads). Ingestion polling is bounded and may send several target requests within one native step. Legacy S1 event/receipt/file labels remain internal compatibility names; campaign/result labels are STAGE3.

This is a profile-driven experimental extension, not fully automatic discovery of deletion semantics from OpenAPI alone. Preserve the profile alongside the contract and generator for reproducibility.

## Fixture provisioning and retained resources

Docker exec provisions one new ordinary user, adding delete_tag/delete_documenttype permissions only when the deletion profile is selected. It does not grant staff/superuser or delete_document. The explicit test deletion is restricted to T or Y created and identity-checked within that namespace. It is not automatic cleanup. Documents, users, unrelated tag U and evidence are retained. There is no automatic retry, reset or rollback.

## Installation and execution

Apply this delta over the repository containing the ancestor correction and completed Stage2 evidence (source b0040f5; evidence be4de64). Save-Paperless-Stage3.ps1 verifies release files, runs local regression tests, verifies existing Stage2 evidence, then commits only release paths; -Push additionally verifies the remote branch head. Run-Paperless-Stage3.ps1 runs local checks and six fresh schedules; -SampleOnly creates/audits native samples without provisioning or sending Paperless requests. Container can be specified explicitly; otherwise exactly one container publishing 9930 is required.

Java heap defaults to 1 GiB unless already configured. All requests target the local service on port 9930. No administrator password is required: Docker access performs fixture provisioning. Do not stop Paperless while the campaign is running.

Stop at the first semantic candidate or incomplete execution. Preserve its campaign.zip before qualification or reproduction. A completed run prints STAGE3_SIX_RUNS_PASS in campaign-summary.json. Existing Stage1/2 live campaigns are not repeated.

## Local validation and limits

Nineteen Python regression tests passed (6 Stage1, 2 bridge, 6 Stage2, 5 Stage3). Six actual Provengo schedules against a local HTTP fixture passed: 2004 checks, 320 target responses. A separate native injected mutation-then-500 run stopped as SEMANTIC_CANDIDATE and retained all seven final readbacks. Fixture tests additionally detect dangling deleted-tag references and loss of unrelated tags. These validate the adapter/oracle, not live Paperless behavior. PowerShell scripts were inspected but not executed in this Linux environment.

Live Stage3 acceptance is pending. Document trash/restore, parent-tag deletion, merge, duplicate handling and multi-user configurations remain outside this campaign.
