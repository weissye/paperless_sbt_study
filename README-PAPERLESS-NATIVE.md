# Paperless native infrastructure pilot

This package extends the frozen generic OpenAPI generator. It does not modify
the Mealie study directory. The pinned contract is the operator-exported
Paperless OpenAPI 3.0.3 document (93 paths, 163 operations, 206 schemas).
Application version: operator installation of Paperless-ngx v3.2.1.

## Run on Windows

Prerequisites: Python 3.10 or newer with the `py -3` launcher; Provengo on PATH;
Java supported by that Provengo installation; existing Paperless listening on
`http://127.0.0.1:9930`. No new Python dependencies are required for JSON input.

Extract the archive into the existing `paperless_sbt_study` directory. Then:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Unblock-File '.\scripts\Run-Paperless-Native-Smoke.ps1'
& .\scripts\Run-Paperless-Native-Smoke.ps1 -Username 'research_admin'
```

For sampling without any HTTP requests, add `-SampleOnly`. Each invocation
creates a new project and a new review directory. The runner prompts for the
password only after sampling and audit succeed. Do not paste credentials into
scripts or Git. Native output is scrubbed for passwords and token fields.

## Exact scope

One native schedule, two logical actors, sequential HTTP: authentication (1),
statistics GETs (4), creation POSTs (2), tag GETs (2): **9 requests** total.
Two tags are retained. No update, deletion, permission change, foreign-owner
access, document ingestion, automatic retry, or reset/replay is performed.

The runner defaults to the existing administrator. This is explicitly an
**infrastructure pilot**, not an ordinary-user authorization experiment.
Using another principal requires its legitimate tag create/read and statistics
permissions; this package does not provision users or establish private owners.

Success is `NATIVE_RELATIONSHIP_CALLBACKS_PASS`, backed by a complete runtime
receipt. The callbacks check creation response projection and stable tag route
identity on GET. They do not prove full equality of every returned tag field.
`full_json_schema_validator` remains false. HTTP 200 or native exit zero alone
is insufficient for acceptance.

Review files are printed under `runs/native-smoke-<timestamp>/`:
`sampling-review.zip` and `live-review.zip`. Upload **live-review.zip** after
the run; if sampling fails, upload sampling-review.zip instead.

## Generic changes and research provenance

G0 source freeze: Mealie supervisor archive, operator Git commit
`4df22f7007c097ffd31e1256c2f3242ebabb6084`.
G1 adds an optional documented credential-to-header-apiKey binding. The explicit
profile supplies token endpoint, security scheme, response token field, prefix,
and static Accept header. No Paperless name or endpoint is embedded in the
compiler. The form is deliberately restricted to documented username/password
without additional required credentials; MFA and other flows are not supported.

A second opt-in extension handles a single scalar `allOf` branch in runtime
projection. The first native mock exposed the old object-only allOf assumption
on `matching_algorithm`. This is a generator compatibility defect, not a
Paperless application bug. Multiple scalar allOf branches remain unsupported.
Existing profiles keep their previous projection and OAuth behavior.

HTTP and callbacks remain in `interfaces.paperless.js`; generated stories only
coordinate symbolic tasks. The existing native sampler/replay auditor is reused.
The Python runner discovers its root from the PowerShell script location; paths
are passed as separate arguments, and no inline Python quoting is used.

## Verification and limits

See `validation/validation-summary.json`, `legacy-byte-equivalence.json`, and
`native-fixture-validation.json`. Native Provengo sampling and execution were
tested in Linux against a local HTTP fixture. Positive execution passed; changed
GET identity and empty token responses were rejected. Five transport regression
tests, fifteen compiled-relationship tests and six credential tests passed.
Mealie compiled interfaces, stories and reports matched the frozen source byte
for byte in the default pilot. The uploaded administrator smoke summary is
preserved separately and is operator evidence, not our live server execution.

Windows PowerShell and the real Paperless native replay still require the
operator run. No new application bug has been confirmed by this package.

Next research gate: qualify ordinary-user permissions and ownership, then add
document fixtures and positive relationship composition with bounded schedules.
Two clients of one principal must be distinguished from two different users.
Identity configurations are not considered covered by this infrastructure pilot.

## Preservation

The archive includes the generator snapshot, its optional extensions, profiles,
pinned OpenAPI, validation evidence, generated model and launch scripts. Package
SHA256 checksums are in `SHA256SUMS.json`. The local run writes fresh models;
it does not regenerate or overwrite the archived validation model.
This package has not been pushed to Git. Commit it only after reviewing the
pilot result and the project-specific ignore rules. Exclude secrets and raw
runtime directories; preserve sanitized review archives and source explicitly.
