# Controlled quantity and merge investigation

This increment extends the existing generic OpenAPI generator. No live Mealie requests were sent while preparing the package. The original repeated 19-versus-20 discrepancy remains frozen; these controls do not redefine that result or count repeated symptoms as separate bugs.

## Cases, in execution order

1. `duplicate-no-merge`: two identical food/unit ingredient occurrences, add 2 recipe copies, remove 1, add 0.5, remove 1.5. No merge operation is sent.
2. `merge-no-decrement`: original two-food recipes share one unit; add 2 primary copies and 3 copies of another recipe, merge food 1 into food 2, then add 0.5 primary copy. No decrement precedes the fractional addition.
3. `single-ingredient`: one food/unit ingredient per recipe; add 2, remove 1, add 0.5, remove 1.5. This controls for duplicate ingredients.
4. `three-ingredient`: three ingredients share one unit; add 2 copies, merge food 1 into food 2, remove 1, add 0.5, merge food 2 into food 3, remove 1.5.
5. `chain-readd`: two-food recipes share one unit; add primary and secondary contributions, merge 1 into 2 and 2 into 3, decrement and fractionally increment, remove all recipe contributions, add 0.5 again, remove 0.5 again.

Each case uses three recipes, three lists, manual quantity 7 per list, and newly owned resources for each live replay. Two native schedules are sampled once per case. Each schedule is replayed once. The second schedule provides independent resources and an opportunity to reproduce a semantic failure; it is not an automatic retry of the first schedule. The sampler may produce identical orders; distinctness must be checked from preserved evidence before claiming order diversity.

The runner requests the password once and uses a 1 GiB Java heap. At least 2 GiB free RAM and 1 GiB free disk are checked. Existing accepted models, original evidence and server data are preserved. No automatic deletion, rollback, full reset or cleanup is performed.

## Evidence and verdicts

`Downloads/mealie-controls-TIMESTAMP/campaign.zip` contains generation, sampling and both live review ZIPs per completed case, a summary, and offline validation of the original evidence when it is available in `evidence/collision-originals`.

Native runtime acceptance is required for `PASS`. Only an actual native runtime semantic warning becomes `SEMANTIC_CANDIDATE`. Authentication failures, missing evidence and other unclassified failures stop the campaign. A semantic candidate is preserved, the second schedule is executed, and the investigation proceeds to the next independent case. A candidate does not establish an additional distinct bug; classify and minimize the preserved symptoms after review.

HTTP operations remain in generated interfaces. Stories request logical tasks. The independent Python verifier recomputes quantities and references from ordered runtime receipts. Every transition reads all three recipes and lists. These reviews contain callback observations and native logs; they are not a complete raw-wire capture.

## Generic opt-in configuration

`semantic_program.phases` overrides the legacy semantic phase schedule. It accepts a bounded list of contribution phases (`kind`, numeric nonzero `amount`, integer `offset`) and merge phases (`kind`, one-based `from_index`, `to_index`). Removal beyond available association stock and merging retired identities are rejected before execution. All operation identities and payload fields are still validated against the OpenAPI contract.

`target_bindings.target_indices` defines repeated target occurrences for array relationships. It is mutually exclusive with legacy `target_index`; typed identities, array shape, ownership restrictions and dependencies are validated.

`baseline_reference_total` declares the initial aggregate recipe quantity for controlled duplicate groups. Actual ingredient quantities remain checked by native callbacks; aggregate totals and integer multiples are independently checked in Python. Existing profiles without these options retain byte-identical generated output.

Run `scripts/Run-Generic-Collision-Controls.ps1 -Username changeme@example.com`. Review the campaign ZIP before interpreting or reporting any finding.
