# Stage4 protocol: bounded bulk updates and repeated relationship operations

## New mechanism

Use POST /api/documents/bulk_edit/, declared by the pinned OpenAPI with response 200, rather than individual document PATCHs. The contract declares method and parameter fields, but exact tag-set/idempotency policies must be confirmed against pinned source before implementing the profile. Existing Stage1-3 results do not cover this bulk path.

Three cases, two fresh sets per case: six schedules with one ordinary user and one client. Each set contains documents A/B selected for operations, document C deliberately unselected, shared flat tag T, unrelated retained tag U and a retained type Y. No parents, merge or document deletion in this campaign.

1. **S4-BULK-CONTROL.** Establish unrelated U/Y on all documents, then bulk-add T to A/B. Independently read all three documents: A/B contain exactly T+U and C still only U. Compare the effect with the already-validated individual association policy, without assuming that the bulk implementation shares it.
2. **S4-REPEATED-ADD-REMOVE.** Bulk-add T to A/B twice; read after each operation. Bulk-remove T twice; read after each; re-add T and read. Check set semantics, absence of duplicate links, preservation of U/Y and C, stable IDs and original checksums. Do not count the same discrepancy in repeated steps as multiple bugs.
3. **S4-SUBSET-ISOLATION.** Bulk-add T to A/B, rename the shared tag, then bulk-remove T from A alone. Verify B retains T and C remains untouched; re-add T to A and verify convergence. This tests changes between relationship construction, shared-resource update and subset removal.

Before implementation, inspect actual bulk completion semantics. If the operation queues work, use a bounded completion criterion and distinguish timeout from semantic failure; never assume a successful status means committed state. Record redacted request/response bodies and all surviving-document/tag/type/metadata reads before evaluating assertions. Preserve explicit stable IDs, source/profile/contract hashes, native samples/order and receipts.

Stop at the first discrepancy or incomplete run. Qualify the response and persisted state before reproducing with fresh resources. No automatic retry, cleanup, reset or rollback. Existing accepted live stages are retained and need not be repeated.

This is the next campaign plan, not an executable Stage4 release. Later mechanisms remain document trash/restore, merge, duplicate ingestion and multiple clients/users.
