# Stage3 protocol: deletion while resources are referenced

## Research question

Does deleting shared metadata preserve each surviving document's identity, content, original bytes and unrelated relationships, while removing only the deleted relationship? This advances from cycle validation to referential lifecycle consistency. It follows the linked-deletion stage of the Mealie study and tests Paperless-specific policies explicitly, without reusing Mealie response assumptions.

## Boundary and design

Three cases, two fresh sets per case: six bounded schedules. Use one ordinary user and one client, with HTTP events dispatched through the existing interfaces and recorder. Administrator use is limited to fixture provisioning. Each fresh set has two synthetic PDF documents A and B, a flat shared tag T, an unrelated retained tag U and a shared document type Y. No tag parent hierarchy or automatic matching is enabled; hierarchy deletion is a separate experiment.

1. **S3-DETACHED-DELETE-CONTROL.** Build A-T and B-T links, detach T from both documents, read back, then delete T. This establishes the unreferenced deletion baseline. Expect 204 for DELETE, 404 on later direct T read, unchanged surviving documents and U/Y relations.
2. **S3-SHARED-TAG-DELETE.** Link A to T, modify T's name, read back, link B to T, read back both documents, then delete T while both still reference it. Expect 204, then 404 for T, absence of T from both documents, preservation of U, Y, IDs, owners, content and original checksums. This combines relationship construction, an intervening shared-resource change, and deletion.
3. **S3-SHARED-TYPE-DELETE.** Bind Y to A, modify Y's name, read back, bind Y to B, then delete Y while both reference it. Expect 204, then 404 for Y, document_type null for both documents, and unchanged tags, IDs, owners, content and original checksums.

## Oracle basis

The pinned OpenAPI declares DELETE /api/tags/{id}/ and /api/document_types/{id}/ with status 204. Pinned Paperless source commit 7575d6078227ebdb4cf443f263d53ebc7575aa37 defines Document.document_type with SET_NULL and Document.tags as many-to-many. These source-backed expectations must be explicit profile policies, separate from contract-derived routes and schemas. Confirm the running image and contract before starting; do not learn expected relationships from the post-delete response.

## Evidence and stopping

Record each mutation's full redacted request/response, every checkpoint read and ordering, stable bindings, input PDFs, checksums, model/sample hashes and native receipt. Capture both surviving documents and metadata before asserting the final deletion outcome, even when DELETE returns an unexpected code. This avoids losing state evidence after a failing status check, as occurred in earlier campaigns.

Only scenario-owned T or Y is deleted as the explicit subject of a test. Retain documents, users, U and evidence; no cleanup, automatic retry, reset or rollback. Stop at the first candidate or incomplete run. Qualify oracle, transport and asynchronous-ingestion causes before further live execution. For a new discrepancy retain the first failing schedule and reproduce on fresh resources. Count the same mechanism under different orders as one bug with multiple reproductions.

## Later work, outside this six-run campaign

Document soft-delete/trash/restore, deletion of parent tags with descendants, bulk add/remove, merge and duplicate handling follow separately. Multiple clients/users follow after single-user baselines. This document defines the next campaign; it is not an executable Stage3 release.
