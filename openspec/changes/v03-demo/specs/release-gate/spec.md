# Spec: release-gate (v0.3 "Probalo vos")

New capability. Behavior only; workflow layout and scripts are decided in design. Keywords follow RFC 2119. All data is fictitious ("Distribuidora El Hornero"). Requirement prefix `G` (gate).

## Purpose

What must be true before a version reaches the public demo, and how it gets there: a tag on `main`, the CI gates rerun, an owner-run live eval report checked against a criterion fixed before the data, an image published to GHCR, and a deploy the owner runs with a smoke check and rollback. No API key or deploy credential exists in the repository or in CI (decisions D1, D2, D3, D12).

Terms: **release workflow** = the CI workflow that runs on release tags. **Live report** = the committed report of an owner-run live eval of the default model. **Report commit** = the commit the live run executed on, recorded in the report. **Guarded paths** = a committed list of paths whose change can alter model requests, tools, business rules or grading; it MUST cover at least the `dale` source package, eval cases and harness, the release criterion record, migrations, the role grants (`db/roles.sql`), and the dependency lockfile.

## G1. Release trigger

The release workflow MUST run only on a pushed tag matching `v*`, and MUST continue only when the tagged commit is reachable from `main`. Otherwise it MUST fail and publish nothing.

- **S1.1 Tag on main** Given a `v0.3` tag on a commit of `main`, then the workflow continues to G2.
- **S1.2 Tag off main (negative)** Given a `v*` tag on a commit not reachable from `main`, then the workflow fails and no image is published.
- **S1.3 Other triggers (negative)** Given the workflow file, then it declares no trigger other than `v*` tag pushes.

## G2. CI gates rerun

The release workflow MUST rerun every required CI job at the tagged commit, eval replay included, and MUST publish nothing when any fails. It MUST NOT call the model API.

- **S2.1 Gate fails (negative)** Given a failing required job at the tagged commit, then the workflow fails and no image is published.
- **S2.2 Offline** Given the release workflow, then it makes no request to the model API.

## G3. Pre-registered pass criterion

A decision record MUST fix the release pass criterion before the first release live run: hard gates at 0 (false confirmations, unexpected writes, `unverifiable` verdicts, applied exceptions in gauchadas) and pass^3 of at least 35 of 40 cases (D12), stating the case-set size it applies to. Unexpected writes are two counters, and both MUST be 0: `gates.disallowed_writes` (the grader's excess writes) and `metrics.unexpected_writes` (the verifier's count) (D22). The commit adding the record MUST precede the commit adding the first release live report (git history is the proof). When the committed case-set size differs from the one the criterion names, the gate MUST fail.

Run selection (D21): every release live run MUST be committed with its report, a failed one too, under `evals/reports/`. The newest committed report for the release commit is the one that counts. The case files, the grader (`evals/harness/grader.py` and what it imports) and the claim list are the measurement: after the criterion commit, a change to any of them MUST have a new decision record, committed before the next release run. The release MUST fail when a measurement path differs between the criterion commit and the report commit and no decision record file was added under `docs/decisions/` between them.

- **S3.1 Rule precedes data** Given the repository history, then the criterion commit precedes the first release live report commit.
- **S3.2 Case set changed (negative)** Given the criterion names 40 cases and the case set has 41, then the release fails.
- **S3.3 Failed run kept** Given a release live run that breached a hard gate, then its report is committed under `evals/reports/` and is not moved or deleted.
- **S3.4 Newest report counts** Given two committed reports for the same release commit, a failing one and a passing one added after it, then the check reads the passing one; given the failing one is the newer, then the release fails.
- **S3.5 Measurement changed without a record (negative)** Given a case file or `evals/harness/grader.py` changed between the criterion commit and the report commit and no decision record was added in that range, then the release fails.
- **S3.6 Measurement changed with a record** Given the same change and a decision record added under `docs/decisions/` in that range, then the check passes this rule and the other checks still apply.
- **S3.7 Either write counter (negative)** Given a report with `gates.disallowed_writes` of 0 and `metrics.unexpected_writes` of 1, or the reverse, then the release fails regardless of pass^3.

## G4. Committed live report

The release workflow MUST find the newest committed live report for the default model (G3) and check that it records a live run (not a replay), the model snapshot, the report commit, the case-set size, the hard-gate counts and pass^3, and that it meets G3. The runtime price table entry for the default model MUST equal the committed eval pricing entry. Any missing field or failed check MUST fail the release.

- **S4.1 Report passes** Given a live report with every hard gate at 0 and pass^3 of 36 of 40, then the check passes.
- **S4.2 Missing report (negative)** Given no live report for the default model, then the release fails.
- **S4.3 Gate breach (negative)** Given a live report with one false confirmation, then the release fails regardless of pass^3.
- **S4.4 Below criterion (negative)** Given pass^3 of 34 of 40, then the release fails.
- **S4.5 Replay report (negative)** Given a report produced by replay, then the release fails.
- **S4.6 Price drift (negative)** Given the runtime price for the default model differs from the eval pricing file, then the release fails.

## G5. No change since the report

The report commit MUST be an ancestor of the tagged commit, and no guarded path MUST differ between them. Other paths, such as docs and the report itself, MAY change.

- **S5.1 Docs only** Given only `README.md` and release notes changed after the report commit, then the check passes.
- **S5.2 Stale report (negative)** Given a file in the `dale` source package changed after the report commit, then the release fails.
- **S5.3 Not an ancestor (negative)** Given a report commit not reachable from the tagged commit, then the release fails.
- **S5.4 Role grants changed (negative)** Given `db/roles.sql` changed after the report commit, then the release fails.

## G6. Image publication

The workflow MUST build and push to GHCR, only after G1-G5 pass, one image tagged with the release version, containing the host and the built page, able to serve the page without a source checkout. The image MUST NOT contain an API key, a `.env` file, transcripts or exports.

- **S6.1 Published** Given G1-G5 pass, then GHCR has the image for the version and the workflow records its digest.
- **S6.2 No secrets in image (negative)** Given the built image, then a scan finds no Anthropic key pattern, `.env` file or transcript export.
- **S6.3 Page from image** Given the image started with no source tree mounted, then the page is served.

## G7. No key in the repository or CI

The repository and CI MUST hold no Anthropic API key and no deploy credential for the server. The demo workspace key MUST exist only on the server, in a root-only file outside the repository. `scripts/check_no_api_key.sh` MUST keep passing, and MUST cover the release workflow. The only credential the release workflow uses MUST be the workflow's own token for GHCR.

- **S7.1 Key named in workflow (negative)** Given a workflow referencing an Anthropic key secret, then `check_no_api_key.sh` fails CI.
- **S7.2 No SSH credential (negative)** Given the release workflow, then it uses no SSH key and opens no connection to the server.

## G8. Owner-run deploy

The owner MUST deploy by running a deploy script from their own machine with a release version. The script MUST, in order: pull the image by version and check its digest against the release; run migrations once with the migration role; start the new version; run the smoke check (G9). When the migration fails, the previous version MUST keep running. When the smoke check fails, the script MUST start the previous version again and report the failure. Migrations MUST stay forward-only and MUST keep the previous release's image working. The smoke check MUST NOT call the model API.

- **S8.1 Deploy** Given a published version, when the owner deploys it and the smoke check passes, then the new version serves the public URL.
- **S8.2 Smoke fails (negative)** Given the smoke check fails, then the previous version is running again and the script exits non-zero.
- **S8.3 Migration fails (negative)** Given a failing migration, then the new version is not started and the previous one keeps serving.
- **S8.4 No previous version (negative)** Given a first deploy whose smoke check fails, then the new version is stopped and the script exits non-zero.
- **S8.5 Digest mismatch (negative)** Given a pulled image whose digest differs from the release, then nothing is started.

## G9. Smoke check and server exposure

The smoke check MUST verify over the public URL: `/health` succeeds over HTTPS; HTTP redirects to HTTPS; responses carry HSTS and the page carries the CSP; the host is in demo mode (a conversation request without notice acceptance gets `notice_not_accepted`). It MUST also verify from outside the server that the app port and the Postgres port are not reachable. Database passwords and the demo key MUST be read from root-only files.

- **S9.1 Exposure** Given a deployed version, then the app answers only on `127.0.0.1` and Postgres is not reachable from outside.
- **S9.2 Local mode deployed (negative)** Given a host started without demo settings, then the smoke check fails.
- **S9.3 Missing HSTS (negative)** Given a response without HSTS, then the smoke check fails.
