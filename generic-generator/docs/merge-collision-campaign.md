# Final focused merge-collision campaign

## Purpose and boundary

The preceding nine-run campaign passed on the pinned local Mealie v3.28.0
server. Its twelve food merges did not collapse any existing (food ID, unit ID)
quantity groups: units differed. This focused campaign closes that specific
coverage gap before evaluating further investment in this application.

Only three new native samples are generated and replayed. Earlier accepted
models and samples are retained. Each run has 51 tasks and 267 HTTP requests;
three complete runs total 801 requests. HTTP calls are sequential and remain
in generated interfaces; stories admit and synchronize independent actors.

## Controlled initial state and transitions

The generator creates three foods, three units, three recipes, three lists and
three manual items. Recipes retain their two distinct food ingredients, with
quantity 2 for each. Explicit typed target bindings assign the same owned unit
to every recipe ingredient and manual item. Unit links wait for food links so
all ingredient occurrences exist before the shared unit is assigned. Unused
units remain outside the merge chain.

The shared unit is a configuration policy, not a Mealie special case in the
compiler. New `target_bindings` validate exact resource types, selected target
index, relationship paths and prerequisite fields. Overrides of contained-child
ownership or recursive links are rejected. Cyclic execution prerequisites are
rejected by the existing compiler dependency audit.

Each list starts with seven manual units. The contribution sequence adds two
copies of one recipe and three copies of another, merges F1 into F2, removes one
copy of the first recipe, adds another half copy, merges F2 into F3, removes the
three copies of the second recipe, then removes the remaining 1.5 copies of the
first. Independent lists may perform a phase in different orders.

After each mutation all three recipes and all three lists are read. Numeric
accounting aggregates all rows by (food ID, unit ID), without assuming that the
server physically consolidates rows. Recipe contribution quantities are checked
separately. Each list must return to seven manual units with no positive recipe
contribution remaining after the final removals.

## Actual coverage is required

`require_merge_collision: true` selects an additive callback variant. Before
each merge, it independently computes how many existing group keys will collapse
when the source identity is replaced by the target. Zero collisions stop the
scenario; an accepted HTTP response alone cannot establish coverage.

Runtime receipts record `collision_groups`. A separate Python validator
recomputes this count and every numeric transition, rejecting forged counts,
wrong quantities, missing readbacks and unowned merge identities. It also
requires source absence (404) and stable owned target identity after merge.

In the controlled local fixture, the first merge collapses four groups across
recipe/list views and the second collapses five. These are per-view group
reductions, not counts of database rows or distinct physical objects. Each run
must prove positive coverage in both merges on the actual server. Any live
failure requires triage; it is not automatically a confirmed application bug.

## Run

Extract the delta into the existing study tree and invoke:

```powershell
Set-Location 'C:\work\temp\mealie_sbt_study'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Unblock-File '.\scripts\Run-Generic-Collision-Campaign.ps1'
& .\scripts\Run-Generic-Collision-Campaign.ps1 -Username 'changeme@example.com'
```

The runner checks the pinned server version, runs compatibility tests, generates
one focused model, samples it once with three native samples and replays each
sample once. It uses a 1 GiB Java heap and requires 2 GiB free RAM and 1 GiB free
disk space. It prompts for the API password once. Chrome can remain open when
those resources are available. New owned food sources are deleted by the merge
operation; existing application resources are not selected for mutation.

Upload the `campaign.zip` under the timestamped Downloads `mealie-collision-*`
folder. The runner stops at the first live failure and bundles available live
reviews. If execution stops before the first live review, provide its printed
generation or sampling review instead. No automatic retry, cleanup or full
server reset/replay is performed.

## Compatibility and decision

The change is opt-in. Eight earlier runtime profiles retain byte-identical
interfaces, stories and maps for fixed inputs, including the three previously
accepted semantic families. Compact callback isolation is unchanged. Regression
covers injected loss of one colliding ingredient, removal of manual stock,
forged collision counts and a scenario that merges without real collisions.

Passing this campaign means the specified collision/accounting tests did not
find a bug. It does not prove all Mealie behavior correct. Full server reset/
replay, authorization boundaries, conversion semantics and other unexplored
operations are outside this focused completion campaign. Its live evidence will
support the next decision about whether to continue this study.
