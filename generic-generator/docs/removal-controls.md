# Removal diagnosis controls

Install this delta over the merge-lifecycle study. Run scripts/Run-Generic-Removal-Controls.ps1 -Username changeme@example.com. The delivery preserves the preceding live campaign under evidence/removal-findings-20261004 and verifies it offline before requesting a password.

Four cases, two native schedules each, new owned resources per live replay:

| Case | Recipe ingredients | Merge operations | Contribution lifecycle |
| --- | --- | --- | --- |
| food-integer-no-merge | Two quantity-2 ingredients sharing food/unit | None | Add 1, remove 1, add 1, remove 1 |
| unit-integer-no-merge | Three quantity-2 ingredients sharing food/unit | None | Add 1, remove 1, add 1, remove 1 |
| food-integer-one-merge | Two quantity-2 ingredients, different foods/shared unit | Food 1 into food 2 | Add two recipes, merge, remove both, re-add one, remove it |
| unit-integer-one-merge | Three quantity-2 ingredients, shared food/different units | Unit 1 into unit 2 | Add two recipes, merge, remove both, re-add one, remove it |

No-merge case names reflect their originating family; neither performs any food or unit merge. Together they test multiplicity two versus three. The one-merge cases test whether a second merge is necessary. Controlled recipe yield is 1. The manual list quantity is 7. All contribution multipliers are integers.

Complete schedules have 197 HTTP requests for no-merge and 256 for one-merge; eight complete runs would have 1,812 requests. A detected discrepancy stops that individual schedule, so later actions are not claimed as executed. Requests are sequential. Stories schedule the generated tasks and interfaces contain all HTTP.

The runner retains existing classification behavior: a semantic candidate is preserved, then the second fresh reproduction and next case run. Authentication, infrastructure and unclassified failures stop the campaign. Candidate count is not confirmed bug count. No automatic resource cleanup, retry, rollback or full server reset is performed.

Prerequisites: existing pinned local Mealie, Python, Node, installed Provengo, 2 GiB free RAM and 1 GiB free disk. Java heap is limited to 1 GiB; full existing compatibility checks run first. Password is requested once. At completion or a failure inside the execution loop, upload Downloads/mealie-removal-controls-TIMESTAMP/campaign.zip.

These diagnostic profiles are new. Local mocked and native Provengo checks establish generator/oracle execution; live Mealie acceptance remains pending. Food/unit deletion and modifying already-added recipes remain outside this diagnostic campaign.
