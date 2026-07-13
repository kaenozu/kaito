# Release operations and approval gates

This document separates version-controlled safeguards from repository settings and production credentials. A green pull request does not by itself authorize a merge, tag, signing-secret use, or Release publication.

## Non-negotiable authorization boundaries

The following actions require an explicit decision for the exact target and must not be inferred from a successful CI run or an earlier approval:

- marking a Draft pull request Ready for Review;
- merging or enabling auto-merge;
- creating or moving a tag;
- creating, publishing, or deleting a Release outside an authorized canary;
- using production signing secrets, a production certificate, or a production timestamp service.

Do not substitute self-approval, a bot comment, a resolved thread, or a successful workflow for an independent approving review.

## Repository capability and protection gate

Protect `master` before merging PR #11. The first release-pipeline merge must not occur while repository policy is only documented but unenforced.

Required branch protection or ruleset controls:

- require a pull request before merging;
- require at least one independent approving review;
- dismiss stale approvals after a new commit;
- require approval of the most recent push by someone other than the pusher when supported;
- require all review conversations to be resolved;
- require the normal Windows CI, Release Hardening, and Release Rehearsal checks;
- require the pull request to be current with `master` when supported;
- prevent force pushes and branch deletion;
- apply the rule to administrators or prohibit administrative bypass during this release sequence.

The repository is private. Verify the active GitHub plan before relying on Environment protection. Environment secrets and deployment branches require a plan that supports private-repository Environments. Required reviewers and wait timers can have narrower private-repository availability. If required reviewers are unavailable, production signing remains blocked until an explicitly accepted alternative control exists; creating an unprotected `production` Environment is not equivalent.

## Fixed-head pull-request approval gate

Workflow: `Release PR approval gate`

Purpose: produce fail-closed evidence for a specific pull request, HEAD SHA, current `master` SHA, exact changed-file set, required workflow set, review-thread state, auto-merge state, and independent approval.

The workflow is manual and read-only. It requires the exact confirmation phrase `VERIFY_FIXED_PR_GATE` and uploads JSON evidence. A result is:

- `PASS` only when every check passes;
- `BLOCKED` when the only missing condition is an independent approval of the fixed HEAD;
- `FAIL` for a state, SHA, file, workflow, review-thread, or auto-merge mismatch;
- `INCONCLUSIVE` when GitHub state cannot be retrieved or evaluated completely.

For PR #11, the reviewed snapshot is:

- base ref: `master`;
- current base SHA: `bfcbd9904196043e371a8f398edc71a6de30cdf1`;
- fixed HEAD: `9174b11a87d80e4654c987b7d1708427367b5ee0`;
- comparison: 62 ahead, 0 behind;
- required workflows: `CI`, `Release hardening checks`, `Release rehearsal`;
- exact changed files: 12.

The pull-request metadata endpoint previously reported 13 files because it exposed `tests/test_productivity_services.py`, a change already present on the current `master`. The direct current-`master` comparison is authoritative for the gate and must still be reconfirmed immediately before approval and immediately before merge.

## Required repository settings

Configure a GitHub Environment named `production` before enabling production signing.

- Add at least one independent Required Reviewer when the repository plan supports it.
- Prevent self-review when supported.
- Store `WINDOWS_CERTIFICATE_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD` as Environment secrets, not repository-wide secrets.
- Store `WINDOWS_TIMESTAMP_URL` as an Environment variable and require an HTTPS RFC 3161 endpoint.
- Restrict Environment deployment branches or tags to the intended release policy.
- Verify ordinary pull-request workflows cannot read production secrets.

These settings are not created by workflow YAML. Their presence must be checked in repository settings before production use.

## Pull-request and merge sequence

1. Confirm the GitHub plan and identify a human reviewer with write, maintain, or admin permission who is not the pull-request author.
2. Protect `master` before merging PR #11 with the controls listed above.
3. Reconfirm PR #11 against the fixed base SHA, fixed HEAD, exact 12-file set, three successful workflows, zero unresolved threads, and disabled auto-merge.
4. Obtain an independent `APPROVED` review anchored to the fixed PR #11 HEAD.
5. Run the fixed-head approval gate and retain its JSON evidence.
6. Merge PR #11 only after a separate explicit merge authorization and with an expected-head guard.
7. Retarget PR #12 to `master`, update it to the new `master`, rerun all three required workflows, obtain a fresh independent approval, run the gate, and merge only after explicit authorization.
8. Retarget PR #15 to `master`, update it to the new `master`, rerun all three required workflows, obtain a fresh independent approval, run the gate, and merge only after explicit authorization.
9. Configure and verify the `production` Environment, Environment-scoped credentials, deployment restrictions, and secret isolation before any production-signing canary.
10. Complete GitGuardian incident disposition before production credentials are used.
11. Run the Draft Release roundtrip canary only after explicit temporary-tag and Draft-Release authorization.
12. Run the production signing canary only after explicit production-secret authorization and any required Environment approval.
13. Perform an actual release only under a separate fixed tag, commit, and publication decision.

Any new commit, base movement, changed-file difference, failed or missing workflow, unresolved thread, or stale approval invalidates the previous gate evidence.

## Draft Release roundtrip canary

Workflow: `Draft Release roundtrip canary`

Purpose: exercise the real GitHub tag, Draft Release, asset upload, Release API download, shared verifier, and cleanup path without publishing a Release.

Preconditions:

1. PR #11, PR #12, and PR #15 are merged in order under the approval process above.
2. The selected `source_ref` has successful CI, Hardening, and Rehearsal checks.
3. No Release or tag exists with the generated `draft-roundtrip-<run>-<attempt>` name.
4. The operator has explicit authorization to create and delete a temporary tag and Draft Release.

Run procedure:

1. Open **Actions → Draft Release roundtrip canary → Run workflow**.
2. Select the reviewed source ref, normally `master`.
3. Enter `CREATE_AND_DELETE_DRAFT` exactly.
4. Confirm that the run creates only a Draft Release.
5. Confirm that the five assets are downloaded and verified with the `rehearsal` trust profile.
6. Confirm that cleanup deletes both the Draft Release and temporary tag.
7. Retain the metadata-only Actions evidence.

The workflow contains no publication command. Cleanup refuses to silently delete an unexpectedly public Release and fails if absence of both objects cannot be proven.

## Production signing canary

Workflow: `Production signing canary`

Purpose: validate the real production PFX, trusted certificate chain, timestamp endpoint, SignTool strict verification, and Authenticode identity without creating a tag or Release.

Preconditions:

1. The `production` Environment and its protection controls have been verified.
2. Environment secrets and `WINDOWS_TIMESTAMP_URL` are configured.
3. The certificate is the intended production code-signing certificate and is currently valid.
4. Secret use has explicit authorization.
5. If Environment Required Reviewers are unavailable for this private repository, an explicitly approved alternative control is active; otherwise the canary remains blocked.

Run procedure:

1. Open **Actions → Production signing canary → Run workflow**.
2. Enter `SIGN_CANARY_WITH_PRODUCTION_CERT` exactly.
3. Complete the Environment approval when configured.
4. Confirm the fresh executable is unsigned before signing.
5. Confirm required-mode signing succeeds with the configured HTTPS timestamp URL.
6. Confirm independent SignTool verification succeeds and Authenticode reports `Valid`.
7. Confirm the signer thumbprint matches the signing status and is not the CI test certificate.
8. Confirm the signed executable is deleted before evidence upload.

Only JSON and text evidence is retained. The signed canary binary is not uploaded.

## Manual security disposition

GitGuardian incidents must be dispositioned in the GitGuardian dashboard after direct inspection. A code comment or successful CI run does not change dashboard incident status.

Record the following for each incident:

- detector and incident ID;
- affected historical commit and line;
- whether the value was a runtime-generated test value, fixture, or real credential;
- final-tree search result;
- rotation requirement, if any;
- reviewer and disposition date.

Do not rewrite shared history solely to hide a false-positive fixture unless a real credential was committed or repository policy requires history removal.
