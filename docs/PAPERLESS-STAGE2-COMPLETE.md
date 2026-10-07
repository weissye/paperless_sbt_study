# Completed live hierarchy campaign

## Scope and results

The original archive's SHA256 is e753d4f24334c50b3718cfa27548e2be562e153742b5a953bca17a127ea30727. The supplied console reports source commit b0040f5. Six actual Provengo executions completed with exit code 0 and runtime receipts, as checked independently against archived native samples and executed step order. Each schedule contains 59 native steps and 397 successful checks. The aggregate is 2382 passing checks and 356 recorded Paperless responses; response counts vary due to ingestion polling. One ordinary user (ID 8), with no staff/superuser privileges, runs each case in a fresh resource namespace.

| Case | Fresh runs | Final response | Readback conclusion |
|---|---:|---|---|
| Legal hierarchy then reparent unused T3 | 2 | 200 | Intended parent change; preserved document identities, links and original checksums |
| Length-2 cycle attempt | 2 | 400, Cannot set parent to a descendant | No tag/document state change |
| Length-3 cycle attempt | 2 | 400, Cannot set parent to a descendant | No tag/document state change |

All runs reach five checkpoints, each reading three tags, two documents and both document metadata resources. The final checkpoint occurs after the final attempted mutation. Document A retains T1, document B retains T2 plus ancestor T1, and both retain their document type. Original PDF hashes match metadata. The verifier also checks fresh IDs within each resource family; equal numeric IDs across different resource families are valid.

The 400 responses are correct validation outcomes rather than failures: the attempt to make an ancestor a descendant is disallowed, and state remains consistent afterward. This mirrors Mealie's cycle campaign: rejecting an invalid cycle is acceptable when independent reads show no unintended persisted change.

## Qualification limits

No new semantic bug is confirmed by these schedules. Coverage is limited to this three-tag topology, these interleavings and one ordinary-user configuration. It is not complete dependency-graph coverage or a general proof of correctness. Full reset/replay remains pending.

In S2-CYCLE-2 repetition 2, document A metadata `lang` changes from ca to en between chain and final checkpoints. The reason is not established by these observations; document content, relationships and original checksum are unchanged. The protected-state comparisons deliberately cover tags, document bodies and checksums; they do not claim metadata-language immutability. Preserve this observation for a separate bounded investigation if repeated instability becomes relevant.

The previous children-representation and ancestor-inheritance stops were oracle qualifications, separately retained. Provengo supplies dependency-respecting execution orders and native replay. The semantic oracle adds explicit hierarchy policy and independent readbacks, so a rejected operation that changes state would still fail.
