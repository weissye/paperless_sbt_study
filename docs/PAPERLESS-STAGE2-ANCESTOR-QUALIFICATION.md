# Stage 2: ancestor-tag expectation qualification

## Evidence and conclusion

The preserved live campaign stopped in the first legal hierarchy control. The ordinary fixture user (ID 7) had neither staff nor superuser privileges. All 38 recorded target responses succeeded; one of 207 checks failed, at the immediate response to `attach_B`.

The recorded order was: attach tag T1 (16) and document type Y (10) to document A (20); set T2 (15).parent to T1 (16); attach T2 and Y to document B (19). The last PATCH requested tags [15], returned HTTP 200 and tags [15,16]. The omitted tag in the expected set was exactly the known ancestor, not an unrelated resource.

Pinned Paperless source commit 7575d6078227ebdb4cf443f263d53ebc7575aa37, `src/documents/serialisers.py`, `DocumentSerializer.update`, explicitly implements: adding a child adds its ancestors. The expectation [15] was incomplete. This run is an oracle false positive, not a confirmed semantic defect.

Two preceding checkpoints contain independent reads of all three tags, both documents and both document metadata resources. Direct parent identities are consistent, and original document checksums match the retained input PDFs. The final PATCH response preserves B's stable identity, owner, content and document type while adding the expected parent tag. No post-PATCH GET of B was reached. No cycle attempt or final hierarchy control action was reached. No conclusion about those unexecuted operations is supported.

## Correction and scope

The explicit Stage2 profile policy `add_with_ancestor_closure` derives expected tags from requested IDs and the independent expected parent graph. It does not learn expectations from the target response. The comparison remains exact: an unrelated tag is still a discrepancy. Cyclic or unbound expected parent graphs are rejected as incomplete.

This policy applies to this stage's addition operations only. Paperless also has rules for removing a parent and descendants; those are not implemented or claimed as covered here. Stage1 semantics remain unchanged. Embedded-child representation qualification is retained separately.

## Validation and continuation

Six bounded actual Provengo schedules passed against a local HTTP fixture implementing ancestor addition. An injected parent mutation on rejected cycle creation was detected; all seven checkpoint reads were retained. Python regression tests also detect unrelated tag insertion. These are adapter validations, not new Paperless live evidence.

No complete live Stage2 schedule has yet passed. After installing and preserving this correction, run all six Stage2 schedules with fresh resources. Do not repeat the six accepted Stage1 schedules. Preserve the resulting campaign ZIP before qualification. No automatic retry, deletion, reset or rollback is performed.
