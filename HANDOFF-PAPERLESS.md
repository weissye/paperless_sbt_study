# Handoff: Paperless study, 2026-10-05

Stage3: six accepted live linked-deletion schedules.
Original campaign archive preserved with its verified SHA256.
No new semantic defect confirmed in that campaign.

Stage5: entity lifecycle compiler and version-graph campaign prepared.
Local validation: six adapter tests and six native fixture executions passed.
Injected post-write HTTP 500 was detected with retained readbacks.
Stage5 has NOT yet been executed against the real Paperless server.

Next at work:
1. Pull main with --ff-only.
2. Start the existing Paperless Docker environment.
3. Run scripts/Run-Paperless-Stage5.ps1.
4. Preserve the printed campaign.zip.
5. Qualify results before retrying or declaring a bug.

The campaign requires two distinct business orders per case.
The final case deletes owned non-root versions and shared tag/type fixtures.
Root and control documents are retained. Reset/replay remains pending.