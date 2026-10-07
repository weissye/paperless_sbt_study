# First live stage1 run: checksum oracle correction

## Classification

ORACLE_FALSE_POSITIVE_CONFIRMED. No Paperless defect is confirmed by this run.
The first control stopped at baseline_checksum_A after 17 successful HTTP responses and before any relationship PATCH. The ordinary user was neither staff nor superuser. Both PDFs were ingested and task-bound to separate owned document ids.

The test expected the MD5 of A.pdf, while Paperless returned its SHA256. Recomputing SHA256 directly from the archived original PDF gives exactly the server value. Fifty-eight other checks passed under the original oracle. The checksum guard must stay; the expected algorithm was wrong. The corrected oracle compares the explicit profile's SHA256 policy to the uploaded input bytes, with no digest-length guessing and no fallback to MD5.

## Methodological lesson

The OpenAPI describes original_checksum as a string; it does not specify the digest algorithm. This is an explicit semantic policy requiring external evidence. A local fixture that shares the same mistaken MD5 assumption cannot independently establish that policy. Therefore acceptance of the authoring fixture was insufficient to qualify this boundary. The original live archive and old release remain preserved; the correction is versioned separately.

## Continuation

Run verify_original.py offline, preserve this correction in Git, then start one new bounded stage1 campaign with fresh owned fixtures. Keep the stopped run's user and resources. Do not mark its unexecuted relationship checks as passed. No reset or automatic deletion is needed. A complete new campaign must still pass six live runs, native completion receipts, full bodies and readbacks. The archive alone cannot establish full graph coverage.
