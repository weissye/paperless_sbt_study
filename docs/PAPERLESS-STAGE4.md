# Paperless Stage4: bulk relationship composition

## Scope and new mechanism

Use the declared POST /api/documents/bulk_edit/ path with add_tag/remove_tag, explicit document IDs and parameters.tag. This tests a different implementation path than the accepted individual PATCH and deletion stages. Six schedules: three cases, each in two fresh namespaces. One ordinary user, one client, no concurrent HTTP and no deletion permission requested.

Each fresh set contains three unique synthetic PDF documents A/B/C, flat tag T, unrelated retained tag U and document type Y. Set U/Y on all three, then independently read them before any bulk operation. A/B are selected, C is an unselected negative control.

| Case | Sequence | Oracle |
|---|---|---|
| S4-BULK-CONTROL | Bulk add T to A/B | A/B exact T+U; C exact U |
| S4-REPEATED-ADD-REMOVE | Add twice, remove twice, add again, with readbacks after each | Set/idempotency semantics; no duplicates, no unrelated loss, no C mutation |
| S4-SUBSET-ISOLATION | Add T to A/B, rename T, remove T from A only, re-add to A | B retains T; C untouched; A converges back |

All three retain Y, identities, owners, content, protected fields and original SHA256. This follows repeated relationship-operation testing in Mealie, while exercising Paperless bulk editing and an unselected third resource. It does not repeat accepted live Stage1-3 schedules.

## Completion and evidence

Pinned OpenAPI declares bulk_edit POST and response 200. The inspected pinned source (`src/documents/views.py`, BulkEditView.post, commit 7575d6078227ebdb4cf443f263d53ebc7575aa37) calls the selected method before returning its result. The serializer requires parameters.tag for add_tag/remove_tag. Immediate post-response readbacks are therefore the initial completion criterion. No task polling or inferred asynchronous success is added for these two methods. If live results indicate delayed completion, preserve and qualify that separately before changing the oracle.

Exact flat-tag set semantics and idempotency are explicit experimental profile policies, not facts inferred from OpenAPI alone. Expected state is updated from the declared operation and stable bindings, not from a server response body. Different numeric IDs may coincide across different resource families; identity comparisons stay within a family.

Each checkpoint captures nine responses before assertions: T, U, Y, A, B, C and each document's metadata. A 500 with persisted changes, a partial update or mutation of C therefore retains all required state evidence. Check original SHA256 against each retained input PDF. Metadata language is recorded but is not asserted immutable.

Stop at first candidate/incomplete. No automatic retry, cleanup, deletion, reset or rollback. All users, documents, tags, types and evidence are retained. For a candidate retain the first failing native schedule, qualify it offline, then reproduce on fresh resources. Count repeated manifestations of one mechanism as one defect.

## Generator and installation

The pinned contract and explicit Stage4 profile generate native interfaces/stories through the common bounded compiler; all target HTTP travels through the existing interfaces/recording adapter. The dependency coordinator admits ready actors one at a time. Native sampling chooses a dependency-respecting order; this is sequential interleaving, not true concurrency. Stage4 uses 77/85/83 steps (78/86/84 bthreads including coordinator). Eighteen bounded ingestion windows per document remain explicit actors; an already-ready window sends no target request.

Legacy S1 event/receipt/model-file names remain internal compatibility names. Stage4 campaign statuses are STAGE4_FUNCTIONAL_PASS and STAGE4_SIX_RUNS_PASS. Three-document support is opt-in; Stage1-3 default two-document behavior is preserved.

Apply over the repository containing bf16614. The package additionally includes qualified Stage3 original evidence and offline verifier. Save-Paperless-Stage4.ps1 verifies release files, runs 25 local tests, verifies Stage3 evidence, commits only release paths and optionally pushes/verifies the remote branch. Run-Paperless-Stage4.ps1 performs local checks then executes only Stage4. -SampleOnly generates/audits samples without provisioning or sending Paperless requests. -Container selects the server explicitly; otherwise exactly one container publishing port 9930 is required.

Docker provisions one new ordinary user with view/add/change permissions and no staff/superuser privilege. No administrator password is needed. Java heap defaults to 1 GiB unless configured. The server must remain running. No further Python dependencies are added.

## Validation and research limits

Twenty-five Python tests passed: Stage1 6, bridge 2, Stage2 6, Stage3 5, Stage4 6. Six actual native Provengo fixture executions passed (2586 checks, 398 fixture target responses). A separate native unselected-document mutation stopped as SEMANTIC_CANDIDATE and retained all nine checkpoint reads. Fixture tests also detect partial updates, duplicate links, unrelated tag loss and mutation followed by 500. These validate adapter/oracle behavior, not live Paperless acceptance. PowerShell scripts were inspected but not executed in this Linux environment.

Live Stage4 acceptance is pending. Hierarchical bulk updates, document trash/restore, merge, duplicate ingestion and multiple users/clients remain separate later experiments.
