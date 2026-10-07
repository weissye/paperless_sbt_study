# Paperless Stage 1: partial live qualification and bounded continuation

## Preserved live evidence

Source release: user-reported Git commit dd42922. Original campaign: stage1-20261005-174618-feef3ea5, SHA256 c15f19f99de8138a8c0f488c70e60fad66b0d09644d441ceaae1a122859839cc.

Two CONTROL runs passed (181 checks each); one INTERLEAVED-RENAME run passed (263 checks). Their sampled schedules, model byte hashes, completed action orders and final runtime receipts were checked offline. They observed 111 target HTTP responses and eight PATCH requests. These results qualify only the sampled one-user/one-client scenarios, not the full dependency graph.

The fourth run completed 21 steps and 38 passing checks. Both uploaded documents were successfully bound to their own task identities (A=10, B=9; ordinary owner=4). Its 13 Paperless responses were all HTTP 200/201. No relationship PATCH was executed. Provengo reported `HTTP/1.1 header parser received no bytes` on the local bridge step wait_B_11, then skipped actuation. The subsequent Selected events do not establish that target requests were sent. No Paperless semantic defect is established by this transport stop.

## Adapter correction and uncertainty

The previous BaseHTTPRequestHandler used the default HTTP/1.0 response and did not consume the POST body. The corrected adapter drains the bounded request body, emits HTTP/1.1 with Content-Length and explicit Connection: close, and flushes the response. This removes ambiguous connection lifecycle handling. There is no Python server traceback in the original archive; the precise original failure cause cannot be proven. This correction is a tested transport hardening, not a demonstrated causal diagnosis or guarantee of Windows stability.

Tests cover 120 sequential POSTs with request bodies, explicit response framing/connection closure and rejection of an invalid local capability key. The existing six functional fixture tests remain required. Native replay validation uses actual Provengo against a local HTTP fixture; it is not live Paperless validation.

## Continuation policy

Complete-Paperless-Stage1.ps1 first verifies the exact immutable original archive. It creates a new ordinary fixture user and new document/tag/type namespaces, and runs only:

1. INTERLEAVED-RENAME, fresh set 2.
2. DETACH-REATTACH, fresh set 1.
3. DETACH-REATTACH, fresh set 2.

No restoration of partial state, no automatic retry or deletion, no rerun of the accepted controls. The continuation has its own campaign archive and provenance linking the previous archive by SHA256. Successful completion is reported as STAGE1_REMAINING_THREE_PASS, not as six newly executed runs. Full reset/replay and multiple identity configurations remain untested.

Save-Paperless-Stage1.ps1 -Push saves the corrected source, this report, original campaign and validation files via its checksum-scoped release manifest. A successful source push does not archive the future live continuation; preserve its campaign.zip after inspection.
