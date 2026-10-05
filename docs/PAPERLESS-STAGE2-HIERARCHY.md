# Paperless Stage 2: tag hierarchy integrity

## Position in the study

Stage1 has six accepted live schedules, 1,562 passing checks, 261 target responses and 22 PATCH requests. These are drawn from three original accepted runs and three fresh continuation runs; a fourth original run stopped at the local bridge and is excluded from successful-run totals. No Paperless defect was confirmed. Both original archives are preserved with byte checksums and offline verification. User-reported source push for the bridge correction: b784e13.

Stage2 extends the relationship lifecycle before multiple clients or identities. Subsequent stages will address deletion of linked objects, bulk additions/removals, document merges/versions and duplicate ingestion. No claim of complete graph coverage or generality follows from this bounded campaign.

## Three policies, two fresh sets each

Every schedule creates three owned tags, one document type and two different synthetic PDFs with a new namespace. A is explicitly linked to T1; B is explicitly linked to T2. The ordinary user is not staff or superuser. Resources are retained; there is no deletion, reset or automatic retry.

1. CONTROL: build T2.parent=T1, then T3.parent=T2; reparent T3 to T1. Expect HTTP 200 and direct parent/children consistency.
2. CYCLE-2: build the same legal chain; attempt T1.parent=T2. Expect HTTP 400 and preservation of the pre-attempt state.
3. CYCLE-3: build the same legal chain; attempt T1.parent=T3. Expect HTTP 400 and preservation of the pre-attempt state.

The intended model is a hierarchy. The pinned local source Tag.clean rejects self-parenting and assigning a descendant as parent; TagSerializer.validate invokes that check. OpenAPI alone declares a nullable integer parent and does not encode the acyclicity invariant. Cycle rejection is therefore an explicit semantic profile policy, not an automatically inferred rule. Self-loop and maximum-depth testing are deferred.

## Oracles and evidence

After attaching A, each hierarchy write, attaching B and the final change, the adapter reads all three tags, both documents and both original metadata checksums. It captures all seven responses before evaluating discrepancies. Direct children are derived independently from expected parent IDs. Stable tag/document IDs, names, owners, exact explicit document tag sets, document type, protected content fields and original SHA256s are checked. Modified timestamps and derived counters are not equality oracles. The campaign does not assume inheritance of explicit document tag IDs.

Expected rejection is accepted only with preserved states and matching status. Unexpected status or state produces a candidate and stops further mutations; a candidate is not automatically a confirmed defect. Document ingestion uses exact returned task IDs with bounded polling, as qualified in Stage1.

## Provengo and generator scope

The existing native compiler admits profile steps according to their prerequisites, producing interfaces and stories from the pinned OpenAPI and explicit semantic profile. A and B ingestion, setup and ready steps may interleave; the domain mutation sequence is deliberately controlled. The seven reads of a hierarchy checkpoint execute inside one bridge step. There is no overlapping target HTTP or exhaustive permutation claim. Target operations are delegated through the shared recording adapter by native REST interfaces, not embedded in stories.

The common runner keeps its legacy S1 event/callback labels and generated filenames; these are implementation identifiers reused by Stage2. Campaign folders, case IDs and final status identify Stage2. Stage1 remains the default profile and its regression tests are included.

Run scripts/Save-Paperless-Stage2.ps1 -Push to preserve source and Stage1 completion evidence. Run scripts/Run-Paperless-Stage2.ps1 for six live schedules; -SampleOnly sends no server requests. Upload the printed campaign.zip before scheduling additional work. PowerShell is supplied for Windows; local authoring validation executes Python and native Java on Linux, not Windows PowerShell.
