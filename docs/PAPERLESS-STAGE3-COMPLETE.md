# Paperless linked deletion: completed live qualification

The original campaign SHA256 is 28fa4aa61d7f1d1e8f22a55e34f09b052d377115db77d643c8c2d1edf16b8166. The supplied console confirms source commit bf1661464d0dbb0ab49f6cea249e40f2ca187fc8. Six complete native executions have matching models/sample hashes, audited dependency order, completed-step receipts and exit code 0. They use one ordinary user (ID 9) with explicit delete_tag and delete_documenttype permissions and no staff/superuser or delete_document privilege.

| Case | Runs | Native steps/run | Checks/run | Result |
|---|---:|---:|---:|---|
| Detached-delete control | 2 | 62 | 414 | Deleted tag remains absent; detached documents retain unrelated tag and type |
| Shared-tag deletion | 2 | 58 | 294 | Only deleted tag association removed from both documents |
| Shared-type deletion | 2 | 58 | 294 | Both document_type values become null; tag sets preserved |

Aggregate: 2004 successful checks and 343 target responses. Request counts vary because asynchronous ingestion polling is bounded but not fixed. Six explicit DELETEs return 204. Each is followed by all seven checkpoint GETs: T, U, Y, A, B and both document metadata resources. The deleted resource returns 404 and every survivor/metadata read returns 200. Independent before/after inspection confirms stable IDs, owners, titles, content, original filenames, notes, custom fields, version records and original PDF SHA256. Only declared relationships change.

No semantic bug is confirmed in these bounded schedules. Passing results support these particular referential lifecycle policies, not exhaustive graph coverage. Metadata language immutability, document trash/restore, hierarchy deletion, bulk operations, merge, duplicate ingestion and multi-user behavior were not tested here. Full reset/replay remains pending.

The mechanism differs from hierarchy/cycle validation: a stateful prefix creates two documents sharing metadata, a rename is interleaved before the second association, then the shared object is removed. Provengo enforces admitted dependency-respecting schedules and native replay; the independent oracle checks declared deletion effects and frame conditions on surviving resources. API success alone is insufficient for acceptance.
