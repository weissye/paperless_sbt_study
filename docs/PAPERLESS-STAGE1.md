# Paperless stage 1: shared metadata and interleaved construction

These are prospective test definitions, not an executable campaign release.
The accepted home run qualifies infrastructure only. No Paperless defect has been confirmed.

The first set uses one ordinary user, two synthetic documents, one shared tag and one shared document type. Three cases separate a sequential control, metadata renaming during construction, and detach/reattach isolation. Each case receives fresh fixtures twice (six bounded schedules total). All HTTP belongs in interfaces; stories determine schedules. HTTP requests remain serial: interleaving is not simultaneous execution.

Before compiling this set, qualify multipart ingestion and bounded asynchronous task-to-document identity binding. An upload response is not proof that a document exists. Neither title lookup nor selecting the largest id is an acceptable binding mechanism. Keep full sanitized write-response bodies and authorized readbacks. Stop on ingestion timeout and classify it as incomplete, not a semantic defect.

Apply the previous study's progression to Paperless semantics rather than replaying Mealie scenarios verbatim: infrastructure -> valid relationship construction -> interleaved updates -> local relationship lifecycle -> identity configurations -> independent requalification -> isolated reset/replay. Cycles, copy operations and deletion semantics require their own documented preconditions before inclusion.

## Home evidence qualification

Native exit 0 and SUCCESS; nine selected HTTP requests; two completed tasks; tag ids 1 and 2; owner 2; create/readback identity agreement; matching readback names and slugs. Four archived model hashes match sampling acceptance. There is no full independent raw-response trace and no symbolic sample payload in this review ZIP. Thus its callback receipt is corroborated, but exact sample replay is not independently re-audited here.

## Git portability

The pinned contract is byte-addressed. Preserve model/paperless-openapi.json with Git attribute -text. Do not replace its expected SHA256 with the home CRLF version. The preservation script adds the rule to the existing attributes file and stages only this release's paths. It does not commit or push; inspect staged changes before committing.
