# Paperless: entity lifecycles and version graph composition

## Purpose and change from earlier stages

Stages 1–3 established selected functional controls. They did not establish exhaustive graph coverage. The previous bulk stage predominantly used a fixed business suffix; native step counts included many ingestion waits. This campaign replaces that design with independent entity lifecycle actors and persistent prerequisite joins. It searches for composition faults in an owned document version graph, rather than authorization boundary failures.

The generic compiler consumes lifecycle descriptors and explicit prerequisites, checks missing parents and prerequisite cycles, and emits one bthread per entity. A readiness coordinator remembers completed prerequisites. It offers every eligible frontier to Provengo. Each entity uses waitFor on its readiness event, then invokes the shared interfaces boundary and completes its step. A child cannot lose a readiness condition merely because its parent completed earlier. Multi-parent prerequisites are an ALL join; parent order is unrestricted. Alternative-parent selection is not implemented in this release.

Target HTTP remains sequential. This tests different interleavings of lifecycle operations; it does not test simultaneous network requests. Readback checkpoints are indivisible observations after an action, so another actor cannot write between that action and its checkpoint. This deliberately reduces ambiguity when qualifying a discrepancy.

## Structural fixture

Each fresh set contains initial documents A, B, C and D; shared tags T/U; shared document type Y; and a subsequently uploaded file version V. All initial documents are created with distinct synthetic PDFs. A is the selected root. B and C become versions of A. D does not participate in version transformations and supplies an independent control. The resulting version graph has A plus B, C and V. T/U/Y are shared dependencies, and root metadata changes while this graph is being built.

D is protected against unintended version operations. In the deletion case, deliberate deletion of its shared tag/type has an explicitly expected effect on D too; D is not claimed to stay literally unchanged after those parent deletions.

## Three cases, two distinct schedules each

| Case | Composition |
| --- | --- |
| S5-CONTROL | B is attached and labelled before C is attached. Independent metadata lifecycles still run. Upload V to the established graph. |
| S5-INTERLEAVED | B/C attachment and label actors can interleave with root rename, root tag detach/reattach, tag rename and type rename. Upload and label V after the required joins. |
| S5-REMOVE-VERSION | Build the same graph; remove owned non-root B and subsequently V; delete shared T/Y; verify surviving graph, root metadata, D and original file contents. |

The runner samples 16 candidates per case, projects each onto business operations, and selects two different projected orders. Setup/read/wait permutations alone do not qualify as diversity. Fewer than two distinct business orders stops that case before its live execution. This is bounded adaptive selection, not exhaustive state-space exploration and not proof that every operation pair has both orders covered. Six fresh sets use one newly provisioned ordinary user. No staff or superuser privilege is granted to that user.

## Source-backed policies

The retained Paperless source snapshot is pinned to commit 7575d6078227ebdb4cf443f263d53ebc7575aa37; the exact contract SHA256 is 7840d7816133c13fdeb43e1cd9a3013c7fff886538f5612bff3d0b42b2119d0c. Local source inspection grounds these rules:

* usage.md, Document File Versions: root metadata remains on the root; other selected documents become file versions; the root can already have versions; sources with their own version histories cannot be attached.
* src_documents_serialisers.py, MergeDocumentsAsVersionsSerializer: selected root must be selected; only top-level sources are admissible; sources with version histories are rejected.
* src_documents_serialisers.py, get_versions: explicit version membership includes the root and its versions, with IDs, labels, checksums and root markers.
* src_documents_views.py, retrieve/metadata: explicit ?version= selects that version's extracted content/file metadata; default file selection uses the effective version.
* src_documents_views.py, update_version: asynchronous ingestion returns a task identifier; accepted submission is not treated as completed ingestion.
* src_documents_views.py, delete_version: only non-root versions can be removed; root metadata is retained.
* src_documents_models.py: document type uses SET_NULL; tag associations use many-to-many membership. Earlier accepted Stage3 evidence established corresponding linked deletion behavior.

The explicit policies are not automatically inferred from OpenAPI. OpenAPI supplies and validates operation shapes; the semantic profile supplies meaning. New applications still require policy qualification.

## Oracles and evidence

After each business mutation, capture all graph observations before asserting: A/D, T/U/Y, every expected version's explicit content read and explicit metadata read, D's original checksum, and root effective file metadata. Compare exact member IDs, uniqueness, root flags, labels, original input SHA256s, existing version extracted content, root ownership/title/tags/type, selected root protected metadata, and control document state. A response error does not suppress the readbacks.

The effective default file is checked against the first returned version entry as a cross-view consistency invariant. This is not an independent proof of newest-version selection ordering. V's bytes are independently checked against its uploaded PDF; its OCR text is not independently predicted. Source document metadata inheritance is not equated with root metadata preservation. Reads capture bodies and status codes. Authentication credentials and tokens are redacted. Input PDFs, models, sample hashes, selected orders, runtime receipts and response evidence are retained.

Each initial document has upload, readiness, read, update and verification. B/V additionally exercise deletion in the third case. T/Y exercise create/read/update/delete. Root A, document C, control D and tag U are retained. Thus full CRUD for every fixture entity is not claimed. Root trash/restore, rejected graph transformations, external document-reference custom fields, multiple identities and reset/replay are outside this release.

## Run and preserve

Expand the delta in the existing study repository. Run scripts/Save-Paperless-Stage5.ps1 -Push to verify package checksums, run local fixture tests, commit only release paths and verify the remote head. Then run scripts/Run-Paperless-Stage5.ps1. The latter requires the existing pinned model and generic-generator dependencies, Docker service on 127.0.0.1:9930, Python and Provengo on PATH. The caller's explicit Java heap configuration is respected; otherwise the runner uses -Xmx1g.

The runner creates its regular user through local Docker administration and sends every scenario API request with that regular user's token. It retains fixtures and stops at the first incomplete or semantic candidate; there is no automatic retry or cleanup. Preserve the printed campaign.zip before further execution. Source push does not archive future live results; these need independent qualification and a separate evidence commit after the campaign.

## Relationship to the Mealie findings

Mealie quantity findings required transformations followed by inverse operations and conservation checks. The copy finding required checking reference closure after new identities were assigned. This campaign transfers that structural approach: graph membership changes, updates between construction steps, explicit per-version identity/file checks, later removals, and a shared-resource control. It does not transplant Mealie quantity semantics or claim guaranteed defect discovery. Passing fixture tests establish that the test machinery detects selected injected faults; they do not establish Paperless correctness.
