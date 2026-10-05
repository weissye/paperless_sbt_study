# Generic semantic campaign: merge and quantity accounting

This is an additive extension of the existing OpenAPI generator. API paths and
business policies are supplied by explicit runtime profiles; the compiler does
not contain Mealie paths. OpenAPI validates documented operations, request and
response fields, numeric types, route bindings and selected resource boundaries.
OpenAPI alone does not specify additive accounting or merge semantics. Those
expectations are explicit test policies, pending verification on the local
Mealie v3.28.0 server. An unexpected response is evidence for triage, not an
automatic declaration of a new bug.

## Three independently sampled families

| Family | Tasks per run | HTTP calls per run | Semantic mutations |
| --- | ---: | ---: | --- |
| merge | 36 | 147 | 3 additions and 2 successive food merges |
| quantity | 49 | 245 | 18 additions/removals across 3 lists |
| combined | 51 | 267 | 18 additions/removals and 2 successive food merges |

The default campaign samples each family once with 3 native samples, then
replays each sample once: 9 runs and 1,977 HTTP calls if all complete. A first
replay failure stops further replay. Native schedules vary the ordering of
independent actors while requests execute sequentially.

Each run creates 3 foods, 3 units, 3 recipes, 3 lists and 3 manual items.
Recipes share food/unit references. Recipe yield quantity is explicitly set to
1; each ingredient quantity is 2. Each list begins with 7 manual units and no
recipe contributions. Recursive recipe references are excluded from this
focused scope; prior cycle and attached-deletion campaigns remain available.

The quantity sequence for each list adds 2 copies of one recipe, adds 3 copies
of a second, removes 1 of the first, adds 0.5 of the first, removes all 3 of the
second, then removes the remaining 1.5 of the first. Independent lists may
perform the same phase in different orders. Final accounting must return to
the manual baseline of 7 with no positive recipe contribution remaining. Zero-quantity
association rows are allowed; this oracle does not assert physical row deletion.

The merge chain is F1 -> F2 -> F3. In the combined family, the first merge
occurs between contribution phases and the second before the final removals.
The expected recipe and list food identities change, but quantities and unit
identities must be preserved. Old food identities must return 404 and targets
must remain readable with stable identity. Only resources created by that run
are merged. Merger targets are read before and after each merge.

## Oracles and evidence

Before a mutation, callbacks derive the expected state from the last verified
state. After each mutation, all 3 recipes and all 3 lists are read. Quantities
are summed by (food ID, unit ID); duplicate rows are allowed. Recipe association
quantities are checked separately. Controls in other lists must remain
unchanged. No unit conversion or row-count assumption is made. Numeric
comparison uses configured tolerance 1e-8.

A separate Python validator recomputes every transition from the ordered
receipts. It verifies ownership, increment/decrement values, prior-state
continuity, reference quantities, food remapping and complete fresh readbacks.
The review collector checks native task order, HTTP method order, model hashes
and agreement between log receipts and accepted replay evidence. A matching
forged expected/observed quantity is rejected by independent recomputation.

This does not inspect every possible API field, prove absence of bugs, or
perform server reset/replay. The controlled baseline must pass before semantic
mutations begin. A failure can indicate an application defect, an unmet API
precondition or a policy mismatch; retain the first failed review for analysis.

## Local execution

Extract the delta into the existing study tree, then run:

```powershell
Set-Location 'C:\work\temp\mealie_sbt_study'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Unblock-File '.\scripts\Run-Generic-Semantic-Campaign.ps1'
& .\scripts\Run-Generic-Semantic-Campaign.ps1 -Username 'changeme@example.com'
```

Git, Python, Node, Java and the existing Provengo launcher must be available.
The runner verifies the local server version before replay, uses a 1 GiB Java heap, requires 2 GiB free RAM and 1 GiB free disk,
and prompts for the password once. Chrome can stay open when that RAM is
available. It writes a timestamped Downloads folder with generation, sampling
and live reviews per family. Upload the outer `campaign.zip`, also on failure.
It contains all available family evidence without full sample files. Existing
model/sample files are retained. No retry, full reset or cleanup is automatic.

## Software compatibility

New policy keys (`semantic_program`, `create_defaults`, `excluded_relationships`)
are opt-in. Semantic profiles currently run separately from shared-update and
delete profiles; incompatible combinations are rejected explicitly. All HTTP
calls stay in generated interfaces; stories request and synchronize tasks.
The callback isolation implementation remains unchanged.

Regression includes native Provengo 0.7.5-SNAPSHOT with a local HTTP fixture,
Node scheduling tests, injected quantity/remapping faults, forged receipts,
strict OpenAPI binding checks, prior-profile byte comparisons and 466 transport
argument/callback comparisons. The local fixture is not the live Mealie server.
