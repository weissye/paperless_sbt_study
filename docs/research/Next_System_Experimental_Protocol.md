# Prospective Evaluation of OpenAPI Generated Provengo Scenarios

Experimental protocol and system selection assessment

Yeshayahu Weiss | 5 October 2026 | Version 1.0

## Research decision

We recommend Paperless-ngx v3.2.1 as the next research system, subject to a local compatibility acceptance step. It provides a different application domain, relationships between documents and metadata objects, and explicitly shared objects used by ordinary users. These properties support a prospective evaluation of the generator developed during the Mealie study. The purpose is to measure transferability and the contribution of composed scenarios, rather than to reproduce the same Mealie defects in another application.

The source assessment identifies a real limitation: the frozen relationship compiler requires an OAuth password flow, an access_token response and a Bearer header. Paperless documents Token authentication. Consequently, the existing relationship compiler is not accepted for live use with Paperless. Authentication support must be qualified separately, with any generic extension recorded before discovery begins. A successful installation, static generation or unexpected HTTP status is not evidence of a new application defect.

## Questions and hypotheses

RQ1 asks how much of the entity and relationship model can be recovered from a previously unstudied OpenAPI contract without changing the generator. RQ2 asks whether composed schedules expose more independently adjudicated state discrepancies than separate CRUD lifecycles under the same request budget. RQ3 asks what additional value comes from semantic readback checks and multiple actor contexts.

The exploratory hypotheses are that composition increases the range of observable state transitions and that semantic checks detect discrepancies invisible to status checks. A null finding is a valid result. One additional system supports a bounded transfer case study; it cannot establish superiority across software systems or prove that Provengo is necessary for every finding.

## Selection and acceptance criteria

Select a locally deployable open-source application with a versioned OpenAPI contract, persistent writable resources, at least three useful relationships, ordinary user identities, explicit sharing rules and a repeatable clean-state procedure. Prefer a domain different from the systems already investigated. Record the selection rationale before looking for known defects in the chosen mechanisms.

Accept the local deployment only after recording the application tag and image digest, database and broker versions, contract SHA256, generator source digest, runtime versions and fixture hashes. The actual exported contract must parse, generate separated interfaces and stories, and produce a useful relationship map. Every missing or ambiguous relationship must be classified; identical integer shapes do not establish a relationship. Confirm authentication and authorized positive controls before accepting native replay. The included preflight performs contract inspection and static generation only.

First evaluate the frozen generator G0. If it cannot execute the accepted scope, preserve that result. A generic extension G1 may be introduced in a separate feasibility stage of at most eight analyst hours. Record its motivation, implementation, regression checks and impact on existing contracts. Freeze G1, profiles and oracles before the discovery stage. Do not add a Paperless-specific branch to the generator or silently alter a failing oracle after seeing results.

## Three experimental configurations

| Configuration | Scenario construction | Online checks |
| --- | --- | --- |
| C1 Basic lifecycle | Separate CRUD lifecycles over the accepted resource families | Common status, identity and basic readback checks |
| C2 Composed lifecycle | The same operation vocabulary arranged through relationship dependencies and actor schedules | Exactly the C1 checks |
| C3 Semantic composition | The C2 construction method and operation vocabulary | C1 checks plus declared relationship and state invariants |

C1 versus C2 estimates the contribution of composition while holding the online checks fixed. C2 versus C3 estimates the contribution of stronger oracles. Use one common offline adjudicator for all configurations and preserve the response data it needs. Otherwise, a stronger detector could be mistaken for better scenario generation. Declare differences in endpoint reachability and operation distributions; do not attribute those differences solely to scheduling.

## Accounts users and actor contexts

An application account is a server principal. A human can own two accounts, but the server normally treats them as two different principals. Two clients logged into one account are two actor contexts for one principal, not two accounts. Record principal ID, group membership, credential type and actor label without storing plaintext secrets. Verify the mapping at the beginning of each run.

| Identity configuration | Server principals | Client contexts and intended meaning |
| --- | --- | --- |
| I1 Baseline | One ordinary user | One client and one credential context |
| I2 Same user | One ordinary user | Two separate clients or sessions acting sequentially under the same principal |
| I3 Shared objects | Two ordinary users | Two clients with explicit authorization to common objects |
| I4 Private objects | Two ordinary users | Separate owned objects and no sharing grants; owner reads establish the state of each space |

Cross C1 through C3 with I1 through I4: twelve experimental cells. Provisioning uses a separate administrator; the measured application operations use ordinary users. Requests are sequential. Provengo varies the order of actor events while keeping each actor's prerequisites and identity binding. This studies composition and state transitions, not simultaneous HTTP execution.

Paperless exposes user and group grants on objects. A group is not assumed to be a tenant or household. I3 requires verified grants, not merely common group membership. I4 requires private ownership and a checked absence of unintended grants. Do not assume two independent API tokens exist for one user: the inspected token regeneration code replaces the previous token. I2 may use two isolated clients with the same valid token; independent login sessions can be qualified separately. The credential arrangement must be reported accurately.

## Initial mechanisms and entity relationships

Use a small scope anchored in Document to Tag, Document to Correspondent and Document to DocumentType. Include Owner and explicit User or Group grants as context relationships. Qualify each relation against the exported contract and authorized observations. Application-specific ownership semantics and deletion policies are supplied as evidence-bearing profiles; OpenAPI alone is not assumed to encode them.

Template T1 changes metadata on a document while preserving its other links. T2 reuses a metadata object across two documents, then changes that object's display attributes and checks both documents by stable identity. T3 lets two explicitly authorized clients update different declared fields, checking the resulting links and unrelated fields after each completed action. I4 runs the corresponding lifecycles on each user's own resources. These are new mechanisms in a document domain, rather than another quantity-collision campaign.

Document ingestion is asynchronous and uses multipart upload. Treat ingestion and bounded task completion as fixture preparation initially; the generator must bind the resulting document identity from evidence rather than assume that an upload response is a completed document. Use small artificial text PDFs, disable optional external AI and mail integrations, and record readiness. Version editing, bulk operations and ingestion races are deferred until the initial scope is complete.

## Execution design and budgets

Use three fixed seeds, 1101, 1102 and 1103, and two accepted schedules per seed per cell: six discovery schedules per cell and seventy-two in total. A schedule is capped at eighty application API requests, including authentication, polling and readbacks performed during that schedule. The resulting discovery ceiling is 5760 requests. Provisioning requests and analyst time are recorded separately. A maximum of 1000 additional requests is reserved for confirmation; confirmations are not counted as independent discoveries.

Allocate the three templates evenly within the six schedules. Produce an eligibility table first: unsupported template and identity combinations remain visible as unsupported, with their unused budgets reported. C1 uses a fixed topological lifecycle order; C2 and C3 use sampled accepted schedules. Balance configuration execution order across seeds. Reset from a verified equivalent fixture snapshot before every cell and use new fixture identities for confirmation. Keep optional background workflows off and wait for required tasks to finish before observations are compared.

Stop a block if identity mapping is wrong, fixture readiness is uncertain, response capture is incomplete or a resource limit is reached. Preserve the stopped run. Do not score it as a clean application pass or retry it silently. An oracle correction requires versioned requalification of all affected archived runs, not another application mutation to make the result fit.

## Measurements and adjudication

Report unique confirmed defect mechanisms, first failing schedules, confirmation outcomes and known-issue classifications. Several orders or manifestations of one cause count as one defect with multiple reproductions. A candidate needs a declared invariant, the actual request and response, and the relevant authorized before and after observations. An HTTP 500 alone remains an error candidate until its meaning is qualified.

Report confirmed mechanisms per 1000 discovery requests, candidates rejected by adjudication, time to first qualified finding, generation and native execution failures, elapsed time, peak memory, sample size and analyst hours. Report automated extraction separately from manual bindings, policy statements, fixture choices and oracle work. Compare paired seed outcomes descriptively; these small blocks do not justify strong statistical claims.

Coverage includes selected operations, resource families, qualified relationship edges, actor transitions and exercised invariants. Publish the denominator from the contract map and the accepted scope separately. List unresolved candidates, excluded operations and untested edges. Do not claim coverage of the entire dependency graph from successful schedules over a subset.

Every run retains the contract and source digests, profiles, seed, generated stories, shared interfaces, selected event order, redacted request and response bodies, task receipts, owner readbacks, logs, result and checksums. Preserve the first failure before reduction. Confirm with fresh owned fixtures and complete a clean reset and replay before labeling a defect reproducible from installation. Record upstream similarity as known, similar, apparently unreported, or unresolved; absence of a search result does not prove novelty.

## Stop rules and next decision

Stop discovery after the fixed seventy-two schedules or twelve analyst hours after compatibility acceptance, whichever occurs first. Stop feasibility after eight analyst hours if the initial scope still cannot be generated and replayed. Stop immediately on exhausted storage or memory, incomplete evidence, unexpected fixture drift or an unqualified authorization policy. Never stop solely because an early result appears favorable.

At completion, classify transfer as unchanged engine, generic extension required, substantial manual adaptation, or unsupported. Continue to a new mechanism only if its research question and additional budget are specified in advance. Zero confirmed defects can still provide useful evidence about transfer costs, unsupported contract features, coverage and oracle reliability.

## Candidate assessment

| Candidate | Useful properties | Decision |
| --- | --- | --- |
| Paperless ngx | REST resources, document metadata links, user and group object grants, local Compose deployment | Recommended subject to authentication and ingestion acceptance |
| Immich | Assets and albums, multiple users, explicit viewer and editor sharing | Reserve candidate; already present in the study environment and adds file processing complexity |
| Outline | Documents and collections, OpenAPI published, collaboration | Lower priority; RPC style POST endpoints weaken compatibility with the current REST family inference |

Paperless source tag v3.2.1 resolves to commit 7575d6078227ebdb4cf443f263d53ebc7575aa37. The inspected router registers documents, tags, correspondents, document_types, storage_paths, users, groups and tasks. Models and serializers contain foreign-key and many-to-many relationships. The upstream API schema tests generate and validate the schema, but this assessment did not obtain the full live schema or execute Paperless locally. No operation count, native acceptance or application defect is claimed.

The first deliverable from the local setup is therefore a compatibility record, not a bug report. It must resolve Token authentication, integer identity binding, scalar relationship semantics, document fixture completion, pagination, permissions and clean reset. The current compiler authentication restriction is an observed blocker; the remaining items are pending checks. The checked-in source audit and preflight tools distinguish these states.

## Sources and registration record

R1. Paperless-ngx v3.2.1 source and release, https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.2.1. Inspected tag commit above on 5 October 2026.

R2. Pinned Paperless API documentation, docs/api.md at v3.2.1. Public documentation entry: https://docs.paperless-ngx.com/api/.

R3. Pinned usage documentation, docs/usage.md at v3.2.1. Public documentation entry: https://docs.paperless-ngx.com/usage/.

R4. Pinned source files src/paperless/urls.py, src/paperless/views.py, src/documents/models.py, src/documents/serialisers.py and src/documents/tests/test_api_schema.py. Retrieved file hashes are in source_audit.json.

R5. Official Compose example at v3.2.1, docker/compose/docker-compose.postgres.yml. The example uses latest for the application; the experiment must replace it with the pinned version and record the resolved image digest.

R6. Immich sharing documentation, https://docs.immich.app/features/sharing/. Outline API documentation, https://www.getoutline.com/developers.

R7. Mealie generator freeze in the supervisor review package committed as 4df22f7007c097ffd31e1256c2f3242ebabb6084. The assessed source tree is source/generic-generator; its local content digest is recorded in source_audit.json. No engine changes were made for this assessment.

Register the final protocol commit, chosen image and contract digests, accepted templates, eligibility table, policy sources, oracle version and G0 or G1 digest before discovery. Candidate selection involved documentation, source and release metadata review; this is not a blind system selection. No deliberate issue mining or live defect search was performed for this protocol.
