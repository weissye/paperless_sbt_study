# Stage2 children representation qualification

The live run stage2-20261005-181529-a4b6d061 stopped at check_parent_2 in the first legal control. The sole failed comparison expected T1.children=[12] but received an embedded Tag object with id=12, parent=13 and owner=6. The explicit T2 read reported parent=13. Both writes returned 200; all 34 target responses were 200/201. Both documents and original SHA256s were preserved across the recorded checkpoint. This is an oracle false positive for semantic hierarchy integrity, not a confirmed parent/child integrity defect.

A separate contract representation deviation exists: the pinned OpenAPI declares Tag.children array items as integer, whereas this server returned Tag objects. Its severity, novelty and applicability to other versions have not been established. This observation is retained, not silently erased by semantic normalization. No cycle attempt or final reparenting was executed in this partial run; the remaining five schedules were not started.

The earlier fixture echoed the schema's integer representation and missed the server's embedded representation. This is a methodological limitation of schema-only mocks. The corrected fixture exercises embedded children; a second functional test retains integer-form coverage. The semantic oracle accepts explicit child identity forms while rejecting missing, boolean and duplicate IDs. Embedded child name, owner and parent are checked against their independently expected tag state. Full raw bodies remain archived, and representation observations are recorded separately at checkpoints.

The correction is a versioned semantic policy, not an alteration of the pinned OpenAPI. A forged list of wrong child IDs or mutated parent is still a discrepancy. Tests include an injected server which returns 400 while changing the relationship: the native run must fail after capturing all seven post-write reads.

Archive SHA256: cc3eecd261470ad0b0888c59f385a2201d8a68f22bfd1c4ae1693ba5efb07c42. Source campaign push was reported as 17eb66b. verify_stage2_children_original.py checks the archive and the limited observed state without HTTP. No new Paperless semantic bug is confirmed.

Rerun Stage2 only after installing and saving this correction. None of its six complete scenarios has been accepted yet, so all six use fresh resource sets and a new ordinary user. The partial original resources are retained. Stage1's six qualified runs do not need to be repeated. Local native validation uses a fixture, and live qualification remains pending.
